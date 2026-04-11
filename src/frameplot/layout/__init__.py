"""Internal layout pipeline used by the public frameplot API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
    Point,
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
    member_left: float
    member_right: float
    left_inside_clearance: float
    right_inside_clearance: float


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
    scc_result = strongly_connected_components(validated)
    ranks = assign_ranks(validated, scc_result)
    order = order_nodes(validated, ranks)
    rank_gap_overrides: dict[tuple[int, int], float] | None = None

    for _ in range(MAX_LAYOUT_STABILIZATION_PASSES):
        placed_nodes = place_nodes(
            validated,
            measurements,
            ranks,
            order,
            rank_gap_overrides=rank_gap_overrides,
        )
        routed_edges = route_edges(validated, placed_nodes)
        overlays = compute_group_overlays(validated, placed_nodes, routed_edges)
        next_overrides = _rank_gap_overrides(validated, placed_nodes, routed_edges, overlays)
        if next_overrides == (rank_gap_overrides or {}):
            break
        rank_gap_overrides = next_overrides or None

    return _normalize_graph_layout(placed_nodes, routed_edges, overlays, validated.theme)


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
    used_lane_positions: dict[tuple[int, int], set[float]] = {}

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
                    used_lane_positions[(component_id, left_rank)].add(x)

    overrides: dict[tuple[int, int], float] = {}
    for key, lane_positions in used_lane_positions.items():
        if len(lane_positions) <= 1:
            continue
        required_gap = base_gap + max(lane_positions) - min(lane_positions)
        if required_gap > base_gap + EPSILON:
            required_gaps[key] = round(required_gap, 2)

    for key, required_gap in _group_boundary_gap_requirements(
        placed_nodes,
        overlays,
        geometry_by_component,
    ).items():
        required_gaps[key] = round(max(required_gaps.get(key, 0.0), required_gap), 2)

    for key, required_gap in required_gaps.items():
        if required_gap > base_gap + EPSILON:
            overrides[key] = round(required_gap, 2)

    return overrides


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
        member_left = min(node.x for node in member_nodes)
        member_right = max(node.right for node in member_nodes)
        infos.append(
            _GroupSpacingInfo(
                bounds=overlay.bounds,
                component_id=member_nodes[0].component_id,
                group_node_ids=frozenset(overlay.group.node_ids),
                min_rank=min(node.rank for node in member_nodes),
                max_rank=max(node.rank for node in member_nodes),
                member_left=member_left,
                member_right=member_right,
                left_inside_clearance=member_left - overlay.bounds.x,
                right_inside_clearance=overlay.bounds.right - member_right,
            )
        )

    return tuple(infos)


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


def _previous_rank(geometry: "ComponentGeometry", rank: int) -> int | None:
    candidates = [candidate_rank for candidate_rank in geometry.rank_right if candidate_rank < rank]
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
