"""Internal layout pipeline used by the public frameplot API."""

from __future__ import annotations

from collections import defaultdict
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace

from frameplot.model import Edge, Node
from frameplot.layout.order import order_nodes
from frameplot.layout.place import place_nodes
from frameplot.layout.rank import assign_ranks
from frameplot.layout.route import _build_component_geometry, compute_group_overlays, route_edges
from frameplot.layout.scc import strongly_connected_components
from frameplot.layout.text import measure_text
from frameplot.layout.types import (
    Bounds,
    DetailPanelLayout,
    GraphLayout,
    GroupOverlay,
    GuideLine,
    LayoutNode,
    LayoutResult,
    MeasuredText,
    Point,
    ResolvedEdgeTarget,
    RoutedEdge,
)
from frameplot.layout.validate import validate_pipeline
from frameplot.theme import resolve_theme_metrics

__all__ = ["build_layout"]

EPSILON = 0.01
MAX_LAYOUT_STABILIZATION_PASSES = 3


@dataclass(slots=True, frozen=True)
class _GroupSpacingInfo:
    bounds: Bounds
    component_id: int
    group_node_ids: frozenset[str]
    min_rank: int
    max_rank: int
    min_row: int
    max_row: int
    member_top: float
    member_bottom: float
    member_left: float
    member_right: float
    top_inside_clearance: float
    bottom_inside_clearance: float
    left_inside_clearance: float
    right_inside_clearance: float


@dataclass(slots=True, frozen=True)
class _ContainerPlacement:
    leaf_nodes: dict[str, LayoutNode]
    group_bounds: dict[str, Bounds]
    bounds: Bounds
    rank_span: int
    order_span: int


@dataclass(slots=True)
class _TempValidatedGraph:
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    groups: tuple[object, ...]
    node_lookup: dict[str, Node]
    edge_lookup: dict[str, Edge]
    edge_targets: dict[str, ResolvedEdgeTarget]
    node_index: dict[str, int]
    edge_index: dict[str, int]
    group_hierarchy: object
    theme: "Theme"
    detail_panel: None = None


def build_layout(pipeline: "Pipeline") -> LayoutResult:
    """Compute positions, routes, and overlays for a pipeline."""

    validated = validate_pipeline(pipeline)
    theme = validated.theme
    main_graph = _layout_graph(validated)

    detail_panel = None
    width = main_graph.width
    height = main_graph.height

    if validated.detail_panel is not None:
        detail_panel = _build_detail_panel_layout(validated.detail_panel, main_graph, theme)
        width = max(width, detail_panel.bounds.right + theme.outer_margin)
        height = max(height, detail_panel.bounds.bottom + theme.outer_margin)
        for guide_line in detail_panel.guide_lines:
            width = max(width, guide_line.bounds.right + theme.outer_margin)
            height = max(height, guide_line.bounds.bottom + theme.outer_margin)

    return LayoutResult(
        main=main_graph,
        detail_panel=detail_panel,
        width=round(width, 2),
        height=round(height, 2),
    )


def _layout_graph(validated: "ValidatedPipeline | ValidatedDetailPanel") -> GraphLayout:
    measurements = measure_text(validated)
    if validated.group_hierarchy.structural_group_ids:
        return _layout_structural_graph(validated, measurements)
    return _layout_flat_graph(validated, measurements)


def _layout_flat_graph(
    validated: "ValidatedPipeline | ValidatedDetailPanel | _TempValidatedGraph",
    measurements: dict[str, MeasuredText],
    *,
    group_bounds_by_id: dict[str, Bounds] | None = None,
) -> GraphLayout:
    scc_result = strongly_connected_components(validated)
    ranks = assign_ranks(validated, scc_result)
    order = order_nodes(validated, ranks)
    rank_gap_overrides: dict[tuple[int, int], float] | None = None
    row_gap_overrides: dict[tuple[int, int], float] | None = None
    row_gap_floor = resolve_theme_metrics(validated.theme).compact_rank_gap

    for _ in range(MAX_LAYOUT_STABILIZATION_PASSES):
        placed_nodes = place_nodes(
            validated,
            measurements,
            ranks,
            order,
            rank_gap_overrides=rank_gap_overrides,
            row_gap_overrides=row_gap_overrides,
            row_gap_floor=row_gap_floor,
        )
        routed_edges = route_edges(validated, placed_nodes, group_bounds_by_id=group_bounds_by_id)
        overlays = compute_group_overlays(
            validated,
            placed_nodes,
            routed_edges,
            group_bounds_by_id=group_bounds_by_id,
        )
        next_rank_overrides = _rank_gap_overrides(validated, placed_nodes, routed_edges, overlays)
        next_row_overrides = _row_gap_overrides(validated, placed_nodes, routed_edges, overlays)
        if (
            next_rank_overrides == (rank_gap_overrides or {})
            and next_row_overrides == (row_gap_overrides or {})
        ):
            break
        rank_gap_overrides = next_rank_overrides or None
        row_gap_overrides = next_row_overrides or None

    return _normalize_graph_layout(placed_nodes, routed_edges, overlays, validated.theme)


def _layout_structural_graph(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    measurements: dict[str, MeasuredText],
) -> GraphLayout:
    placement = _layout_container(validated, measurements, group_id=None)
    placed_nodes = _reindex_hierarchical_components(validated, placement.leaf_nodes)
    routed_edges = route_edges(validated, placed_nodes, group_bounds_by_id=placement.group_bounds)
    overlays = compute_group_overlays(
        validated,
        placed_nodes,
        routed_edges,
        group_bounds_by_id=placement.group_bounds,
    )
    return _normalize_graph_layout(placed_nodes, routed_edges, overlays, validated.theme)


def _layout_container(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    measurements: dict[str, MeasuredText],
    *,
    group_id: str | None,
) -> _ContainerPlacement:
    hierarchy = validated.group_hierarchy
    direct_node_ids = (
        hierarchy.top_level_node_ids if group_id is None else hierarchy.group_child_node_ids.get(group_id, ())
    )
    direct_group_ids = (
        hierarchy.top_level_group_ids if group_id is None else hierarchy.group_child_group_ids.get(group_id, ())
    )
    child_group_placements = {
        child_group_id: _layout_container(validated, measurements, group_id=child_group_id)
        for child_group_id in direct_group_ids
    }
    temp_validated, temp_measurements = _build_temp_graph(
        validated,
        measurements,
        direct_node_ids=direct_node_ids,
        direct_group_ids=direct_group_ids,
        child_group_placements=child_group_placements,
        container_group_id=group_id,
    )
    temp_graph = _layout_flat_graph(temp_validated, temp_measurements)
    temp_graph = _shift_graph_layout(
        temp_graph,
        shift_x=-temp_graph.content_bounds.x,
        shift_y=-temp_graph.content_bounds.y,
    )
    block_rank_spans = {node_id: 1 for node_id in direct_node_ids}
    block_rank_spans.update({child_group_id: placement.rank_span for child_group_id, placement in child_group_placements.items()})
    block_order_spans = {node_id: 1 for node_id in direct_node_ids}
    block_order_spans.update(
        {child_group_id: placement.order_span for child_group_id, placement in child_group_placements.items()}
    )
    rank_widths = _rank_widths_for_blocks(temp_graph.nodes, block_rank_spans)
    order_heights = _order_heights_for_blocks(temp_graph.nodes, block_order_spans)
    rank_offsets = _cumulative_offsets(rank_widths)
    order_offsets = _cumulative_offsets(order_heights)

    leaf_nodes: dict[str, LayoutNode] = {}
    group_bounds: dict[str, Bounds] = {}

    for node_id in direct_node_ids:
        anchor = temp_graph.nodes[node_id]
        leaf_nodes[node_id] = _with_layout_indices(
            anchor,
            rank=rank_offsets[anchor.rank],
            order=order_offsets[anchor.order],
        )

    for child_group_id, child_placement in child_group_placements.items():
        anchor = temp_graph.nodes[child_group_id]
        shift_x = anchor.x - child_placement.bounds.x
        shift_y = anchor.y - child_placement.bounds.y
        rank_offset = rank_offsets[anchor.rank]
        order_offset = order_offsets[anchor.order]
        for leaf_id, node in child_placement.leaf_nodes.items():
            leaf_nodes[leaf_id] = _with_layout_indices(
                _shift_node(node, shift_x, shift_y),
                rank=node.rank + rank_offset,
                order=node.order + order_offset,
            )
        for nested_group_id, bounds in child_placement.group_bounds.items():
            group_bounds[nested_group_id] = Bounds(
                x=round(bounds.x + shift_x, 2),
                y=round(bounds.y + shift_y, 2),
                width=bounds.width,
                height=bounds.height,
            )

    if group_id is None:
        return _ContainerPlacement(
            leaf_nodes=leaf_nodes,
            group_bounds=group_bounds,
            bounds=Bounds(
                x=0.0,
                y=0.0,
                width=round(temp_graph.content_bounds.width, 2),
                height=round(temp_graph.content_bounds.height, 2),
            ),
            rank_span=sum(rank_widths.values()) or 1,
            order_span=sum(order_heights.values()) or 1,
        )

    metrics = resolve_theme_metrics(validated.theme)
    inset_x = validated.theme.group_padding
    inset_top = validated.theme.group_padding + metrics.group_label_padding
    inset_bottom = validated.theme.group_padding

    shifted_nodes = {
        node_id: _shift_node(node, inset_x, inset_top)
        for node_id, node in leaf_nodes.items()
    }
    shifted_group_bounds = {
        nested_group_id: Bounds(
            x=round(bounds.x + inset_x, 2),
            y=round(bounds.y + inset_top, 2),
            width=bounds.width,
            height=bounds.height,
        )
        for nested_group_id, bounds in group_bounds.items()
    }
    own_bounds = Bounds(
        x=0.0,
        y=0.0,
        width=round(temp_graph.content_bounds.width + inset_x * 2, 2),
        height=round(temp_graph.content_bounds.height + inset_top + inset_bottom, 2),
    )
    shifted_group_bounds[group_id] = own_bounds
    return _ContainerPlacement(
        leaf_nodes=shifted_nodes,
        group_bounds=shifted_group_bounds,
        bounds=own_bounds,
        rank_span=sum(rank_widths.values()) or 1,
        order_span=sum(order_heights.values()) or 1,
    )


def _build_temp_graph(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    measurements: dict[str, MeasuredText],
    *,
    direct_node_ids: tuple[str, ...],
    direct_group_ids: tuple[str, ...],
    child_group_placements: dict[str, _ContainerPlacement],
    container_group_id: str | None,
) -> tuple[_TempValidatedGraph, dict[str, MeasuredText]]:
    hierarchy = validated.group_hierarchy
    block_nodes: list[Node] = []
    node_lookup: dict[str, Node] = {}
    node_index: dict[str, int] = {}
    block_measurements: dict[str, MeasuredText] = {}

    for index, node_id in enumerate((*direct_node_ids, *direct_group_ids)):
        if node_id in direct_node_ids:
            node = validated.node_lookup[node_id]
            block_measurements[node_id] = measurements[node_id]
        else:
            group = hierarchy.group_lookup[node_id]
            placement = child_group_placements[node_id]
            node = Node(
                id=node_id,
                title=group.label,
                width=placement.bounds.width,
                height=placement.bounds.height,
                fill=group.fill,
                stroke=group.stroke,
            )
            block_measurements[node_id] = MeasuredText(
                title_lines=(),
                subtitle_lines=(),
                title_line_height=0.0,
                subtitle_line_height=0.0,
                content_height=0.0,
                width=placement.bounds.width,
                height=placement.bounds.height,
            )
        block_nodes.append(node)
        node_lookup[node.id] = node
        node_index[node.id] = index

    projected_edges: list[Edge] = []
    edge_lookup: dict[str, Edge] = {}
    edge_targets: dict[str, ResolvedEdgeTarget] = {}
    edge_index: dict[str, int] = {}
    seen_pairs: set[tuple[str, str]] = set()

    for edge in validated.edges:
        source_block_id = _container_direct_block_id(
            hierarchy,
            edge.source,
            container_group_id=container_group_id,
        )
        target_block_id = _container_direct_block_id(
            hierarchy,
            validated.edge_targets[edge.id].node_id,
            container_group_id=container_group_id,
        )
        if source_block_id is None or target_block_id is None or source_block_id == target_block_id:
            continue
        if source_block_id not in node_lookup or target_block_id not in node_lookup:
            continue
        pair = (source_block_id, target_block_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        projected_edge = Edge(
            id=f"__proj_{len(projected_edges)}",
            source=source_block_id,
            target=target_block_id,
            color=edge.color,
            dashed=edge.dashed,
        )
        projected_edges.append(projected_edge)
        edge_lookup[projected_edge.id] = projected_edge
        edge_targets[projected_edge.id] = ResolvedEdgeTarget(kind="node", node_id=target_block_id)
        edge_index[projected_edge.id] = len(projected_edges) - 1

    temp_validated = _TempValidatedGraph(
        nodes=tuple(block_nodes),
        edges=tuple(projected_edges),
        groups=(),
        node_lookup=node_lookup,
        edge_lookup=edge_lookup,
        edge_targets=edge_targets,
        node_index=node_index,
        edge_index=edge_index,
        group_hierarchy=SimpleNamespace(  # type: ignore[name-defined]
            structural_group_ids=(),
            edge_only_group_ids=(),
            top_level_group_ids=(),
            top_level_node_ids=tuple(node_lookup),
            group_parent_ids={},
            group_child_group_ids={},
            group_child_node_ids={},
            group_descendant_node_ids={},
            node_parent_group_ids={},
            group_depths={},
            group_lookup={},
            group_index={},
        ),
        theme=validated.theme,
    )
    return temp_validated, block_measurements


def _container_direct_block_id(
    hierarchy,
    node_id: str,
    *,
    container_group_id: str | None,
) -> str | None:
    current_group_id = hierarchy.node_parent_group_ids.get(node_id)
    if container_group_id is None:
        if current_group_id is None:
            return node_id
        while hierarchy.group_parent_ids.get(current_group_id) is not None:
            current_group_id = hierarchy.group_parent_ids[current_group_id]
        return current_group_id

    if current_group_id is None:
        return None
    if current_group_id == container_group_id:
        return node_id

    while True:
        parent_group_id = hierarchy.group_parent_ids.get(current_group_id)
        if parent_group_id == container_group_id:
            return current_group_id
        if parent_group_id is None:
            return None
        current_group_id = parent_group_id


def _rank_widths_for_blocks(
    nodes: dict[str, LayoutNode],
    spans_by_block_id: dict[str, int],
) -> dict[int, int]:
    widths: dict[int, int] = defaultdict(lambda: 1)
    for block_id, node in nodes.items():
        widths[node.rank] = max(widths[node.rank], spans_by_block_id.get(block_id, 1))
    return dict(widths)


def _order_heights_for_blocks(
    nodes: dict[str, LayoutNode],
    spans_by_block_id: dict[str, int],
) -> dict[int, int]:
    heights: dict[int, int] = defaultdict(lambda: 1)
    for block_id, node in nodes.items():
        heights[node.order] = max(heights[node.order], spans_by_block_id.get(block_id, 1))
    return dict(heights)


def _cumulative_offsets(spans_by_index: dict[int, int]) -> dict[int, int]:
    offsets: dict[int, int] = {}
    cursor = 0
    for index in sorted(spans_by_index):
        offsets[index] = cursor
        cursor += spans_by_index[index]
    return offsets


def _with_layout_indices(node: LayoutNode, *, rank: int, order: int) -> LayoutNode:
    return LayoutNode(
        node=node.node,
        rank=rank,
        order=order,
        component_id=node.component_id,
        width=node.width,
        height=node.height,
        x=node.x,
        y=node.y,
        title_lines=node.title_lines,
        subtitle_lines=node.subtitle_lines,
        title_line_height=node.title_line_height,
        subtitle_line_height=node.subtitle_line_height,
        content_height=node.content_height,
    )


def _reindex_hierarchical_components(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
) -> dict[str, LayoutNode]:
    component_ids = _component_ids_for_validated_graph(validated)
    reindexed: dict[str, LayoutNode] = {}

    for node_id, node in nodes.items():
        reindexed[node_id] = LayoutNode(
            node=node.node,
            rank=node.rank,
            order=node.order,
            component_id=component_ids[node_id],
            width=node.width,
            height=node.height,
            x=node.x,
            y=node.y,
            title_lines=node.title_lines,
            subtitle_lines=node.subtitle_lines,
            title_line_height=node.title_line_height,
            subtitle_line_height=node.subtitle_line_height,
            content_height=node.content_height,
        )

    return reindexed


def _component_ids_for_validated_graph(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
) -> dict[str, int]:
    adjacency: dict[str, set[str]] = {node.id: set() for node in validated.nodes}
    for edge in validated.edges:
        target_node_id = validated.edge_targets[edge.id].node_id
        adjacency[edge.source].add(target_node_id)
        adjacency[target_node_id].add(edge.source)

    component_ids: dict[str, int] = {}
    seen: set[str] = set()
    component_id = 0

    for node in validated.nodes:
        if node.id in seen:
            continue
        queue = deque([node.id])
        seen.add(node.id)
        while queue:
            node_id = queue.popleft()
            component_ids[node_id] = component_id
            for neighbor in sorted(adjacency[node_id], key=validated.node_index.__getitem__):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
        component_id += 1

    return component_ids


def _rank_gap_overrides(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    placed_nodes: dict[str, LayoutNode],
    routed_edges: tuple[RoutedEdge, ...],
    overlays: tuple[GroupOverlay, ...],
) -> dict[tuple[int, int], float]:
    theme = validated.theme
    metrics = resolve_theme_metrics(theme)
    base_gap = metrics.compact_rank_gap
    geometry_by_component = _build_component_geometry(placed_nodes, theme)
    required_gaps: dict[tuple[int, int], float] = {}
    used_lane_positions: dict[tuple[int, int], set[tuple[str, float]]] = {}

    for component_id, geometry in geometry_by_component.items():
        for left_rank in geometry.gap_after_rank:
            used_lane_positions[(component_id, left_rank)] = set()

    for routed_edge in routed_edges:
        component_id = placed_nodes[routed_edge.edge.source].component_id
        geometry = geometry_by_component[component_id]
        for start, end in zip(routed_edge.points, routed_edge.points[1:]):
            if start.x != end.x:
                continue
            x = round(start.x, 2)
            for left_rank, (gap_start, gap_end) in geometry.gap_after_rank.items():
                if gap_start + 0.01 < x < gap_end - 0.01:
                    used_lane_positions[(component_id, left_rank)].add((routed_edge.edge.id, x))

    overrides: dict[tuple[int, int], float] = {}
    for key, lane_entries in used_lane_positions.items():
        if len(lane_entries) <= 1:
            continue
        lane_positions = sorted(position for _, position in lane_entries)
        required_span = max(
            lane_positions[-1] - lane_positions[0],
            theme.route_track_gap * len(lane_positions),
        )
        required_gap = base_gap + required_span
        if required_gap > base_gap + EPSILON:
            required_gaps[key] = round(required_gap, 2)

    for key, required_gap in _group_boundary_gap_requirements(
        placed_nodes,
        overlays,
        geometry_by_component,
    ).items():
        required_gaps[key] = round(max(required_gaps.get(key, 0.0), required_gap), 2)

    for key, required_gap in _join_target_gap_requirements(
        validated,
        placed_nodes,
        routed_edges,
    ).items():
        required_gaps[key] = round(max(required_gaps.get(key, 0.0), required_gap), 2)

    for key, required_gap in required_gaps.items():
        if required_gap > base_gap + EPSILON:
            overrides[key] = round(required_gap, 2)

    return overrides


def _row_gap_overrides(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    placed_nodes: dict[str, LayoutNode],
    routed_edges: tuple[RoutedEdge, ...],
    overlays: tuple[GroupOverlay, ...],
) -> dict[tuple[int, int], float]:
    theme = validated.theme
    base_gap = resolve_theme_metrics(theme).compact_rank_gap
    geometry_by_component = _build_component_geometry(placed_nodes, theme)
    used_lane_positions: dict[tuple[int, int], set[tuple[str, float]]] = {}
    required_gaps: dict[tuple[int, int], float] = {}

    for component_id, geometry in geometry_by_component.items():
        for upper_row in geometry.gap_after_row:
            used_lane_positions[(component_id, upper_row)] = set()

    for routed_edge in routed_edges:
        component_id = placed_nodes[routed_edge.edge.source].component_id
        geometry = geometry_by_component[component_id]
        for start, end in zip(routed_edge.points, routed_edge.points[1:]):
            if start.y != end.y:
                continue
            y = round(start.y, 2)
            for upper_row, (gap_start, gap_end) in geometry.gap_after_row.items():
                if gap_start + EPSILON < y < gap_end - EPSILON:
                    used_lane_positions[(component_id, upper_row)].add((routed_edge.edge.id, y))

    for key, lane_entries in used_lane_positions.items():
        if not lane_entries:
            continue
        lane_positions = sorted(position for _, position in lane_entries)
        occupied_span = lane_positions[-1] - lane_positions[0]
        required_gap = max(base_gap, occupied_span + theme.route_track_gap)
        if required_gap > base_gap + EPSILON:
            required_gaps[key] = round(required_gap, 2)

    for key, required_gap in _group_row_boundary_gap_requirements(
        placed_nodes,
        overlays,
        geometry_by_component,
    ).items():
        required_gaps[key] = round(max(required_gaps.get(key, 0.0), required_gap), 2)

    return {
        key: round(required_gap, 2)
        for key, required_gap in required_gaps.items()
        if required_gap > base_gap + EPSILON
    }


def _join_target_gap_requirements(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    placed_nodes: dict[str, LayoutNode],
    routed_edges: tuple[RoutedEdge, ...],
) -> dict[tuple[int, int], float]:
    route_by_id = {route.edge.id: route for route in routed_edges}
    joins_by_target_segment: dict[tuple[str, int], list[RoutedEdge]] = {}

    for routed_edge in routed_edges:
        if routed_edge.target_kind != "edge" or routed_edge.target_edge_id is None:
            continue
        if routed_edge.join_segment_index is None:
            continue
        joins_by_target_segment.setdefault(
            (routed_edge.target_edge_id, routed_edge.join_segment_index),
            [],
        ).append(routed_edge)

    required_gaps: dict[tuple[int, int], float] = {}
    badge_diameter = max(validated.theme.arrow_size * 1.8, validated.theme.stroke_width * 6.0)
    join_spacing = max(validated.theme.arrow_size * 1.5, validated.theme.stroke_width * 6.0)

    for (target_edge_id, join_segment_index), joins in joins_by_target_segment.items():
        target_edge = validated.edge_lookup[target_edge_id]
        target_target = validated.edge_targets[target_edge_id]
        source_node = placed_nodes[target_edge.source]
        target_node = placed_nodes[target_target.node_id]
        target_route = route_by_id.get(target_edge_id)
        if target_route is None:
            continue
        if source_node.component_id != target_node.component_id:
            continue
        if source_node.rank >= target_node.rank or source_node.order != target_node.order:
            continue
        if join_segment_index >= len(target_route.points) - 1:
            continue

        start = target_route.points[join_segment_index]
        end = target_route.points[join_segment_index + 1]
        if start.y != end.y:
            continue

        current_segment_length = abs(end.x - start.x)
        required_segment_length = (
            validated.theme.route_track_gap
            + badge_diameter * len(joins)
            + join_spacing * max(0, len(joins) - 1)
        )
        if current_segment_length >= required_segment_length - EPSILON:
            continue

        required_gap = validated.theme.route_track_gap + (required_segment_length - current_segment_length)
        key = (source_node.component_id, source_node.rank)
        required_gaps[key] = max(required_gaps.get(key, 0.0), round(required_gap, 2))

    return required_gaps


def _group_boundary_gap_requirements(
    placed_nodes: dict[str, LayoutNode],
    overlays: tuple[GroupOverlay, ...],
    geometry_by_component: dict[int, "ComponentGeometry"],
) -> dict[tuple[int, int], float]:
    required_gaps: dict[tuple[int, int], float] = {}
    group_infos = _build_group_spacing_infos(placed_nodes, overlays)

    for info in group_infos:
        geometry = geometry_by_component.get(info.component_id)
        if geometry is None:
            continue

        right_outside_node = _nearest_outside_node(
            placed_nodes,
            bounds=info.bounds,
            component_id=info.component_id,
            group_node_ids=info.group_node_ids,
            rank_predicate=lambda rank: rank > info.max_rank,
            side="right",
        )
        if info.max_rank in geometry.gap_after_rank and right_outside_node is not None:
            right_boundary_gap = info.right_inside_clearance * 2.0
            right_neighbor = _nearest_group_neighbor(info, group_infos, side="right")
            if right_neighbor is not None and right_outside_node.node.id in right_neighbor.group_node_ids:
                inter_group_gap = max(info.right_inside_clearance, right_neighbor.left_inside_clearance)
                right_boundary_gap = max(
                    right_boundary_gap,
                    info.right_inside_clearance + inter_group_gap + right_neighbor.left_inside_clearance,
                )
            required_gaps[(info.component_id, info.max_rank)] = round(
                max(required_gaps.get((info.component_id, info.max_rank), 0.0), right_boundary_gap),
                2,
            )

        left_rank = _previous_rank(geometry, info.min_rank)
        left_outside_node = _nearest_outside_node(
            placed_nodes,
            bounds=info.bounds,
            component_id=info.component_id,
            group_node_ids=info.group_node_ids,
            rank_predicate=lambda rank: rank < info.min_rank,
            side="left",
        )
        if left_rank is not None and left_outside_node is not None:
            left_boundary_gap = info.left_inside_clearance * 2.0
            left_neighbor = _nearest_group_neighbor(info, group_infos, side="left")
            if left_neighbor is not None and left_outside_node.node.id in left_neighbor.group_node_ids:
                inter_group_gap = max(info.left_inside_clearance, left_neighbor.right_inside_clearance)
                left_boundary_gap = max(
                    left_boundary_gap,
                    info.left_inside_clearance + inter_group_gap + left_neighbor.right_inside_clearance,
                )
            required_gaps[(info.component_id, left_rank)] = round(
                max(required_gaps.get((info.component_id, left_rank), 0.0), left_boundary_gap),
                2,
            )

    return required_gaps


def _build_group_spacing_infos(
    placed_nodes: dict[str, LayoutNode],
    overlays: tuple[GroupOverlay, ...],
) -> tuple[_GroupSpacingInfo, ...]:
    infos: list[_GroupSpacingInfo] = []

    for overlay in overlays:
        if not overlay.group.node_ids:
            continue
        member_nodes = [placed_nodes[node_id] for node_id in overlay.group.node_ids]
        member_top = min(node.y for node in member_nodes)
        member_bottom = max(node.bounds.bottom for node in member_nodes)
        member_left = min(node.x for node in member_nodes)
        member_right = max(node.right for node in member_nodes)
        infos.append(
            _GroupSpacingInfo(
                bounds=overlay.bounds,
                component_id=member_nodes[0].component_id,
                group_node_ids=frozenset(overlay.group.node_ids),
                min_rank=min(node.rank for node in member_nodes),
                max_rank=max(node.rank for node in member_nodes),
                min_row=min(node.order for node in member_nodes),
                max_row=max(node.order for node in member_nodes),
                member_top=member_top,
                member_bottom=member_bottom,
                member_left=member_left,
                member_right=member_right,
                top_inside_clearance=member_top - overlay.bounds.y,
                bottom_inside_clearance=overlay.bounds.bottom - member_bottom,
                left_inside_clearance=member_left - overlay.bounds.x,
                right_inside_clearance=overlay.bounds.right - member_right,
            )
        )

    return tuple(infos)


def _group_row_boundary_gap_requirements(
    placed_nodes: dict[str, LayoutNode],
    overlays: tuple[GroupOverlay, ...],
    geometry_by_component: dict[int, "ComponentGeometry"],
) -> dict[tuple[int, int], float]:
    required_gaps: dict[tuple[int, int], float] = {}
    group_infos = _build_group_spacing_infos(placed_nodes, overlays)

    for info in group_infos:
        geometry = geometry_by_component.get(info.component_id)
        if geometry is None:
            continue

        upper_row = _previous_row(geometry, info.min_row)
        top_outside_node = _nearest_outside_node_by_row(
            placed_nodes,
            bounds=info.bounds,
            component_id=info.component_id,
            group_node_ids=info.group_node_ids,
            row_predicate=lambda row: row < info.min_row,
            side="top",
        )
        if upper_row is not None and top_outside_node is not None:
            required_gaps[(info.component_id, upper_row)] = round(
                max(required_gaps.get((info.component_id, upper_row), 0.0), info.top_inside_clearance * 2.0),
                2,
            )

        lower_row = info.max_row
        bottom_outside_node = _nearest_outside_node_by_row(
            placed_nodes,
            bounds=info.bounds,
            component_id=info.component_id,
            group_node_ids=info.group_node_ids,
            row_predicate=lambda row: row > info.max_row,
            side="bottom",
        )
        if lower_row in geometry.gap_after_row and bottom_outside_node is not None:
            required_gaps[(info.component_id, lower_row)] = round(
                max(required_gaps.get((info.component_id, lower_row), 0.0), info.bottom_inside_clearance * 2.0),
                2,
            )

    return required_gaps


def _nearest_outside_node(
    placed_nodes: dict[str, LayoutNode],
    *,
    bounds: Bounds,
    component_id: int,
    group_node_ids: frozenset[str],
    rank_predicate: Callable[[int], bool],
    side: str,
) -> LayoutNode | None:
    candidate: LayoutNode | None = None

    for node_id, node in placed_nodes.items():
        if node.component_id != component_id:
            continue
        if node_id in group_node_ids:
            continue
        if not rank_predicate(node.rank):
            continue
        if not _bounds_overlap_vertically(bounds, node.bounds):
            continue
        if candidate is None:
            candidate = node
            continue
        if side == "right" and node.x < candidate.x:
            candidate = node
        if side == "left" and node.right > candidate.right:
            candidate = node

    return candidate


def _nearest_outside_node_by_row(
    placed_nodes: dict[str, LayoutNode],
    *,
    bounds: Bounds,
    component_id: int,
    group_node_ids: frozenset[str],
    row_predicate: Callable[[int], bool],
    side: str,
) -> LayoutNode | None:
    candidate: LayoutNode | None = None

    for node_id, node in placed_nodes.items():
        if node.component_id != component_id:
            continue
        if node_id in group_node_ids:
            continue
        if not row_predicate(node.order):
            continue
        if not _bounds_overlap_horizontally(bounds, node.bounds):
            continue
        if candidate is None:
            candidate = node
            continue
        if side == "top" and node.bounds.bottom > candidate.bounds.bottom:
            candidate = node
        if side == "bottom" and node.y < candidate.y:
            candidate = node

    return candidate


def _nearest_group_neighbor(
    info: _GroupSpacingInfo,
    group_infos: tuple[_GroupSpacingInfo, ...],
    *,
    side: str,
) -> _GroupSpacingInfo | None:
    candidates: list[_GroupSpacingInfo] = []

    for other in group_infos:
        if other == info:
            continue
        if other.component_id != info.component_id:
            continue
        if not _bounds_overlap_vertically(info.bounds, other.bounds):
            continue
        if side == "right" and other.min_rank > info.max_rank:
            candidates.append(other)
        if side == "left" and other.max_rank < info.min_rank:
            candidates.append(other)

    if not candidates:
        return None

    if side == "right":
        return min(candidates, key=lambda other: (other.member_left, other.bounds.x))
    return max(candidates, key=lambda other: (other.member_right, other.bounds.right))


def _bounds_overlap_vertically(first: Bounds, second: Bounds) -> bool:
    return min(first.bottom, second.bottom) - max(first.y, second.y) > EPSILON


def _bounds_overlap_horizontally(first: Bounds, second: Bounds) -> bool:
    return min(first.right, second.right) - max(first.x, second.x) > EPSILON


def _previous_rank(geometry: "ComponentGeometry", rank: int) -> int | None:
    candidates = [candidate_rank for candidate_rank in geometry.rank_right if candidate_rank < rank]
    if not candidates:
        return None
    return max(candidates)


def _previous_row(geometry: "ComponentGeometry", row: int) -> int | None:
    candidates = [candidate_row for candidate_row in geometry.row_bottom if candidate_row < row]
    if not candidates:
        return None
    return max(candidates)


def _normalize_graph_layout(
    placed_nodes: dict[str, LayoutNode],
    routed_edges: tuple[RoutedEdge, ...],
    overlays: tuple[GroupOverlay, ...],
    theme: "Theme",
) -> GraphLayout:
    content_bounds = _collect_graph_bounds(placed_nodes, routed_edges, overlays)

    shift_x = max(0.0, theme.outer_margin - content_bounds.x)
    shift_y = max(0.0, theme.outer_margin - content_bounds.y)
    if shift_x or shift_y:
        placed_nodes = {node_id: _shift_node(node, shift_x, shift_y) for node_id, node in placed_nodes.items()}
        routed_edges = tuple(_shift_edge(route, shift_x, shift_y) for route in routed_edges)
        overlays = tuple(_shift_overlay(overlay, shift_x, shift_y) for overlay in overlays)
        content_bounds = _collect_graph_bounds(placed_nodes, routed_edges, overlays)

    return GraphLayout(
        nodes=placed_nodes,
        edges=routed_edges,
        groups=overlays,
        content_bounds=content_bounds,
        width=round(content_bounds.right + theme.outer_margin, 2),
        height=round(content_bounds.bottom + theme.outer_margin, 2),
    )


def _build_detail_panel_layout(
    validated_panel: "ValidatedDetailPanel",
    main_graph: GraphLayout,
    theme: "Theme",
) -> DetailPanelLayout:
    panel_graph = _layout_graph(validated_panel)
    focus_node = main_graph.nodes[validated_panel.panel.focus_node_id]

    content_width = panel_graph.content_bounds.width
    content_height = panel_graph.content_bounds.height
    label_width = len(validated_panel.panel.label) * theme.subtitle_font_size * 0.62

    panel_width = max(content_width + theme.detail_panel_padding * 2, label_width + theme.detail_panel_padding * 2)
    panel_height = (
        content_height + theme.detail_panel_header_height + theme.detail_panel_padding * 2
    )

    desired_x = focus_node.center_x - panel_width / 2
    max_x = max(theme.outer_margin, main_graph.width - theme.outer_margin - panel_width)
    panel_x = round(max(theme.outer_margin, min(desired_x, max_x)), 2)
    panel_y = round(main_graph.content_bounds.bottom + theme.detail_panel_gap, 2)

    content_x = panel_x + theme.detail_panel_padding
    content_y = panel_y + theme.detail_panel_header_height + theme.detail_panel_padding
    shifted_graph = _shift_graph_layout(
        panel_graph,
        shift_x=content_x - panel_graph.content_bounds.x,
        shift_y=content_y - panel_graph.content_bounds.y,
    )

    bounds = Bounds(
        x=panel_x,
        y=panel_y,
        width=round(panel_width, 2),
        height=round(panel_height, 2),
    )

    return DetailPanelLayout(
        panel=validated_panel.panel,
        graph=shifted_graph,
        bounds=bounds,
        stroke=validated_panel.panel.stroke or theme.detail_panel_stroke,
        fill=validated_panel.panel.fill or theme.detail_panel_fill,
        guide_lines=_build_detail_guides(focus_node, bounds, theme),
    )


def _build_detail_guides(
    focus_node: LayoutNode,
    panel_bounds: Bounds,
    theme: "Theme",
) -> tuple[GuideLine, ...]:
    metrics = resolve_theme_metrics(theme)
    start_left = Point(
        round(focus_node.x + focus_node.width * metrics.guide_anchor_ratio, 2),
        round(focus_node.bounds.bottom, 2),
    )
    start_right = Point(
        round(focus_node.x + focus_node.width * (1.0 - metrics.guide_anchor_ratio), 2),
        round(focus_node.bounds.bottom, 2),
    )
    shoulder_inset = min(metrics.guide_shoulder_inset_cap, panel_bounds.width * metrics.guide_shoulder_inset_ratio)
    end_left = Point(
        round(panel_bounds.x + shoulder_inset, 2),
        round(panel_bounds.y, 2),
    )
    end_right = Point(
        round(panel_bounds.right - shoulder_inset, 2),
        round(panel_bounds.y, 2),
    )
    flare_x = max(theme.route_track_gap * metrics.guide_flare_min_factor, focus_node.width * metrics.guide_flare_ratio)
    bend_y = round(
        start_left.y
        + max(
            metrics.guide_min_bend_drop,
            min(
                theme.detail_panel_gap * metrics.guide_bend_ratio,
                (panel_bounds.y - start_left.y) * metrics.guide_bend_ratio,
            ),
        ),
        2,
    )
    mid_left = Point(
        round(min(start_left.x - flare_x, (start_left.x + end_left.x) / 2), 2),
        bend_y,
    )
    mid_right = Point(
        round(max(start_right.x + flare_x, (start_right.x + end_right.x) / 2), 2),
        bend_y,
    )
    guides = (
        GuideLine(
            points=(start_left, mid_left, end_left),
            bounds=_line_bounds((start_left, mid_left, end_left), theme.detail_panel_guide_width),
            stroke=theme.detail_panel_guide_color,
        ),
        GuideLine(
            points=(start_right, mid_right, end_right),
            bounds=_line_bounds((start_right, mid_right, end_right), theme.detail_panel_guide_width),
            stroke=theme.detail_panel_guide_color,
        ),
    )
    return guides


def _collect_graph_bounds(
    nodes: dict[str, LayoutNode],
    edges: tuple[RoutedEdge, ...],
    overlays: tuple[GroupOverlay, ...],
) -> Bounds:
    bounds = [node.bounds for node in nodes.values()]
    bounds.extend(route.bounds for route in edges)
    bounds.extend(overlay.bounds for overlay in overlays)
    return Bounds(
        x=min(bound.x for bound in bounds),
        y=min(bound.y for bound in bounds),
        width=max(bound.right for bound in bounds) - min(bound.x for bound in bounds),
        height=max(bound.bottom for bound in bounds) - min(bound.y for bound in bounds),
    )


def _line_bounds(points: tuple[Point, ...], stroke_width: float) -> Bounds:
    padding = max(1.0, stroke_width)
    min_x = min(point.x for point in points) - padding
    min_y = min(point.y for point in points) - padding
    max_x = max(point.x for point in points) + padding
    max_y = max(point.y for point in points) + padding
    return Bounds(x=min_x, y=min_y, width=max_x - min_x, height=max_y - min_y)


def _shift_graph_layout(graph: GraphLayout, shift_x: float, shift_y: float) -> GraphLayout:
    shifted_nodes = {node_id: _shift_node(node, shift_x, shift_y) for node_id, node in graph.nodes.items()}
    shifted_edges = tuple(_shift_edge(route, shift_x, shift_y) for route in graph.edges)
    shifted_groups = tuple(_shift_overlay(overlay, shift_x, shift_y) for overlay in graph.groups)
    shifted_bounds = _collect_graph_bounds(shifted_nodes, shifted_edges, shifted_groups)
    return GraphLayout(
        nodes=shifted_nodes,
        edges=shifted_edges,
        groups=shifted_groups,
        content_bounds=shifted_bounds,
        width=round(max(graph.width + shift_x, shifted_bounds.right), 2),
        height=round(max(graph.height + shift_y, shifted_bounds.bottom), 2),
    )


def _shift_node(node: LayoutNode, shift_x: float, shift_y: float) -> LayoutNode:
    return LayoutNode(
        node=node.node,
        rank=node.rank,
        order=node.order,
        component_id=node.component_id,
        width=node.width,
        height=node.height,
        x=round(node.x + shift_x, 2),
        y=round(node.y + shift_y, 2),
        title_lines=node.title_lines,
        subtitle_lines=node.subtitle_lines,
        title_line_height=node.title_line_height,
        subtitle_line_height=node.subtitle_line_height,
        content_height=node.content_height,
    )


def _shift_edge(route: RoutedEdge, shift_x: float, shift_y: float) -> RoutedEdge:
    return RoutedEdge(
        edge=route.edge,
        points=tuple(Point(point.x + shift_x, point.y + shift_y) for point in route.points),
        bounds=Bounds(
            x=route.bounds.x + shift_x,
            y=route.bounds.y + shift_y,
            width=route.bounds.width,
            height=route.bounds.height,
        ),
        stroke=route.stroke,
        target_kind=route.target_kind,
        target_node_id=route.target_node_id,
        target_edge_id=route.target_edge_id,
        join_point=(
            Point(route.join_point.x + shift_x, route.join_point.y + shift_y)
            if route.join_point is not None
            else None
        ),
        badge_center=(
            Point(route.badge_center.x + shift_x, route.badge_center.y + shift_y)
            if route.badge_center is not None
            else None
        ),
        join_segment_index=route.join_segment_index,
        show_arrowhead=route.show_arrowhead,
        join_badge_radius=route.join_badge_radius,
    )


def _shift_overlay(overlay: GroupOverlay, shift_x: float, shift_y: float) -> GroupOverlay:
    return GroupOverlay(
        group=overlay.group,
        bounds=Bounds(
            x=overlay.bounds.x + shift_x,
            y=overlay.bounds.y + shift_y,
            width=overlay.bounds.width,
            height=overlay.bounds.height,
        ),
        stroke=overlay.stroke,
        fill=overlay.fill,
    )
