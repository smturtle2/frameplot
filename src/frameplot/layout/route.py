from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TypeVar

from frameplot.layout.types import Bounds, GroupOverlay, LayoutNode, Point, RoutedEdge, union_bounds
from frameplot.theme import resolve_theme_metrics

EPSILON = 0.01
SelectionItem = TypeVar("SelectionItem")


@dataclass(slots=True)
class ComponentGeometry:
    rank_left: dict[int, float]
    rank_right: dict[int, float]
    row_top: dict[int, float]
    row_bottom: dict[int, float]
    gap_after_rank: dict[int, tuple[float, float]]
    gap_before_rank: dict[int, tuple[float, float]]
    gap_after_row: dict[int, tuple[float, float]]
    gap_before_row: dict[int, tuple[float, float]]
    outer_left: float
    outer_top: float
    outer_bottom: float
    outer_right: float


@dataclass(slots=True)
class CandidatePath:
    points: tuple[Point, ...]
    reserved_segments: tuple[int, ...]


@dataclass(slots=True, frozen=True)
class StoredSegment:
    start: float
    end: float
    edge_id: str
    overlap_locked: bool


@dataclass(slots=True)
class Occupancy:
    horizontal: dict[float, list[StoredSegment]] = field(
        default_factory=lambda: defaultdict(list)
    )
    vertical: dict[float, list[StoredSegment]] = field(
        default_factory=lambda: defaultdict(list)
    )


@dataclass(slots=True, frozen=True)
class JoinSegmentChoice:
    target_edge_id: str
    target_node_id: str
    segment_index: int
    start: Point
    end: Point
    orientation: str
    preferred_position: float
    distance: float


@dataclass(slots=True, frozen=True)
class EdgeJoinPlan:
    target_edge_id: str
    target_node_id: str
    segment_index: int
    start: Point
    end: Point
    orientation: str
    join_point: Point


@dataclass(slots=True, frozen=True)
class PathPointLocation:
    segment_index: int
    start: Point
    end: Point
    orientation: str
    point: Point


@dataclass(slots=True, frozen=True)
class GroupRoutingFrame:
    bounds: Bounds
    member_bounds: Bounds
    header_top: float
    header_bottom: float
    top_reserve: float


@dataclass(slots=True, frozen=True)
class PreparedGroupLayout:
    group: "Group"
    bounds: Bounds
    member_bounds: Bounds
    content_bounds: Bounds
    header_top: float
    header_bottom: float
    top_reserve: float
    depth: int


@dataclass(slots=True)
class RoutingGroups:
    frames_by_id: dict[str, GroupRoutingFrame]
    bounds_by_id: dict[str, Bounds]
    node_group_ids: dict[str, tuple[str, ...]]
    component_group_ids: dict[int, tuple[str, ...]]
    depth_by_id: dict[str, int]


@dataclass(slots=True, frozen=True)
class EndpointAccessDescriptor:
    edge_id: str
    node_id: str
    endpoint_kind: str
    side: str
    axis: str
    lane_start_index: int
    lane_end_index: int
    lane_start: Point
    lane_end: Point
    approach_point: Point | None


@dataclass(slots=True, frozen=True)
class InteractionMetrics:
    edge_crossings: int = 0
    edge_overlap_length: float = 0.0
    obstacle_overlap_length: float = 0.0
    obstacle_crossings: int = 0


@dataclass(slots=True, frozen=True)
class CandidateEvaluation:
    clearance_ok: bool
    shared_local: bool
    endpoint_preferred: bool
    clean_direct: bool
    collisions: int
    edge_crossings: int
    edge_overlap_length: float
    kind_priority: int
    backwards: float
    bends: int
    length: float
    candidate_index: int
    candidate: CandidatePath


@dataclass(slots=True, frozen=True)
class PointRouteEvaluation:
    clearance_ok: bool
    shared_local: bool
    edge_crossings: int
    edge_overlap_length: float
    bends: int
    length: float
    slot: int
    points: tuple[Point, ...]


def _resolved_target(validated: "ValidatedPipeline | ValidatedDetailPanel", edge: "Edge"):
    return validated.edge_targets[edge.id]


def _target_node_id(validated: "ValidatedPipeline | ValidatedDetailPanel", edge: "Edge") -> str:
    return validated.edge_targets[edge.id].node_id


def _target_edge_id(validated: "ValidatedPipeline | ValidatedDetailPanel", edge: "Edge") -> str | None:
    return validated.edge_targets[edge.id].edge_id


def _is_edge_target(validated: "ValidatedPipeline | ValidatedDetailPanel", edge: "Edge") -> bool:
    return validated.edge_targets[edge.id].kind == "edge"


def _is_self_loop(validated: "ValidatedPipeline | ValidatedDetailPanel", edge: "Edge") -> bool:
    target = validated.edge_targets[edge.id]
    return target.kind == "node" and edge.source == target.node_id


def route_edges(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
) -> tuple[RoutedEdge, ...]:
    routing_groups = _build_routing_groups(validated, nodes)
    component_geometry = _build_component_geometry(nodes, validated.theme, routing_groups)
    forward_outgoing: dict[str, list["Edge"]] = defaultdict(list)
    forward_incoming: dict[str, list["Edge"]] = defaultdict(list)
    node_target_edges = tuple(edge for edge in validated.edges if not _is_edge_target(validated, edge))
    edge_target_edges = tuple(edge for edge in validated.edges if _is_edge_target(validated, edge))
    target_node_ids = {edge.id: _target_node_id(validated, edge) for edge in validated.edges}

    for edge in node_target_edges:
        source_node = nodes[edge.source]
        target_node = nodes[_target_node_id(validated, edge)]
        if not _is_self_loop(validated, edge) and source_node.rank < target_node.rank:
            forward_outgoing[edge.source].append(edge)
            forward_incoming[target_node.node.id].append(edge)

    pair_offsets = _assign_pair_offsets(validated, nodes)
    back_slots = _assign_back_slots(validated, nodes)
    self_loop_slots = _assign_self_loop_slots(validated)
    occupancies: dict[int, Occupancy] = defaultdict(Occupancy)
    routed_by_id: dict[str, RoutedEdge] = {}

    ordered_node_edges = sorted(
        node_target_edges,
        key=lambda edge: _edge_route_order(edge, nodes, target_node_ids, validated.edge_index[edge.id]),
    )

    for edge in ordered_node_edges:
        source_node = nodes[edge.source]
        target_node = nodes[_target_node_id(validated, edge)]
        geometry = component_geometry[source_node.component_id]

        if _is_self_loop(validated, edge):
            points = _select_self_loop_route(
                source_node=source_node,
                geometry=geometry,
                occupancy=occupancies[source_node.component_id],
                base_slot=self_loop_slots[edge.id],
                pair_offset=pair_offsets.get(edge.id, 0.0),
                routing_groups=routing_groups,
                theme=validated.theme,
            )
            _reserve_points(occupancies[source_node.component_id], points, edge.id)
        elif source_node.rank < target_node.rank:
            candidate = _select_forward_route(
                edge=edge,
                source_node=source_node,
                target_node=target_node,
                geometry=geometry,
                nodes=nodes,
                occupancy=occupancies[source_node.component_id],
                outgoing_count=len(forward_outgoing[edge.source]),
                incoming_count=len(forward_incoming[target_node.node.id]),
                pair_offset=pair_offsets.get(edge.id, 0.0),
                routing_groups=routing_groups,
                theme=validated.theme,
            )
            points = candidate.points
            _reserve_candidate(occupancies[source_node.component_id], candidate, edge.id)
        else:
            points = _select_back_edge_route(
                source_node=source_node,
                target_node=target_node,
                geometry=geometry,
                occupancy=occupancies[source_node.component_id],
                base_slot=back_slots[edge.id],
                pair_offset=pair_offsets.get(edge.id, 0.0),
                routing_groups=routing_groups,
                theme=validated.theme,
            )
            _reserve_points(occupancies[source_node.component_id], points, edge.id)

        routed_by_id[edge.id] = RoutedEdge(
            edge=edge,
            points=points,
            bounds=_bounds_for_points(points, validated.theme.stroke_width, validated.theme.arrow_size),
            stroke=edge.color or validated.theme.edge_color,
            target_kind="node",
            target_node_id=target_node.node.id,
        )

    if edge_target_edges:
        join_plans = _assign_edge_join_plans(
            validated=validated,
            edges=edge_target_edges,
            nodes=nodes,
            routed_by_id=routed_by_id,
            pair_offsets=pair_offsets,
        )
        ordered_join_edges = sorted(
            edge_target_edges,
            key=lambda edge: _edge_route_order(edge, nodes, target_node_ids, validated.edge_index[edge.id]),
        )

        for edge in ordered_join_edges:
            source_node = nodes[edge.source]
            target_node = nodes[_target_node_id(validated, edge)]
            geometry = component_geometry[source_node.component_id]
            plan = join_plans[edge.id]
            candidate = _select_edge_join_route(
                edge=edge,
                source_node=source_node,
                target_node=target_node,
                join_plan=plan,
                geometry=geometry,
                nodes=nodes,
                occupancy=occupancies[source_node.component_id],
                pair_offset=pair_offsets.get(edge.id, 0.0),
                routing_groups=routing_groups,
                theme=validated.theme,
            )
            _reserve_candidate(occupancies[source_node.component_id], candidate, edge.id)
            badge_radius = _join_badge_radius(validated.theme) if edge.merge_symbol is not None else 0.0
            routed_by_id[edge.id] = RoutedEdge(
                edge=edge,
                points=candidate.points,
                bounds=_bounds_for_points(
                    candidate.points,
                    validated.theme.stroke_width,
                    validated.theme.arrow_size,
                    badge_radius=badge_radius,
                ),
                stroke=edge.color or validated.theme.edge_color,
                target_kind="edge",
                target_node_id=plan.target_node_id,
                target_edge_id=plan.target_edge_id,
                join_point=plan.join_point,
                badge_center=plan.join_point if edge.merge_symbol is not None else None,
                join_segment_index=plan.segment_index,
                show_arrowhead=edge.merge_symbol is None,
                join_badge_radius=badge_radius,
            )

    _repair_forward_conflicts(
        validated=validated,
        nodes=nodes,
        routed_by_id=routed_by_id,
        ordered_node_edges=ordered_node_edges,
        component_geometry=component_geometry,
        pair_offsets=pair_offsets,
        routing_groups=routing_groups,
    )
    _separate_overlapping_endpoints(validated, nodes, routed_by_id)

    return tuple(routed_by_id[edge.id] for edge in validated.edges)


def _build_routing_groups(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
) -> RoutingGroups:
    frames_by_id: dict[str, GroupRoutingFrame] = {}
    bounds_by_id: dict[str, Bounds] = {}
    node_group_ids: dict[str, list[str]] = defaultdict(list)
    component_group_ids: dict[int, set[str]] = defaultdict(set)
    prepared_groups = _prepare_group_layouts(validated, nodes)

    for prepared in prepared_groups:
        group = prepared.group
        frames_by_id[group.id] = GroupRoutingFrame(
            bounds=prepared.bounds,
            member_bounds=prepared.member_bounds,
            header_top=prepared.header_top,
            header_bottom=prepared.header_bottom,
            top_reserve=prepared.top_reserve,
        )
        bounds_by_id[group.id] = prepared.bounds
        for node_id in group.node_ids:
            node_group_ids[node_id].append(group.id)
            component_group_ids[nodes[node_id].component_id].add(group.id)

    return RoutingGroups(
        frames_by_id=frames_by_id,
        bounds_by_id=bounds_by_id,
        node_group_ids={node_id: tuple(group_ids) for node_id, group_ids in node_group_ids.items()},
        component_group_ids={
            component_id: tuple(sorted(group_ids))
            for component_id, group_ids in component_group_ids.items()
        },
        depth_by_id={prepared.group.id: prepared.depth for prepared in prepared_groups},
    )


def _prepare_group_layouts(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
    edge_lookup: dict[str, RoutedEdge] | None = None,
) -> tuple[PreparedGroupLayout, ...]:
    groups = tuple(group for group in validated.groups if group.node_ids)
    if not groups:
        return ()

    group_indices = {group.id: index for index, group in enumerate(groups)}
    group_nodes = {group.id: frozenset(group.node_ids) for group in groups}
    parent_ids = _direct_group_parent_ids(groups, group_nodes)
    depths = _group_depths(groups, parent_ids)
    children_by_parent = _group_children_by_parent(parent_ids, group_indices)
    preparation_order = sorted(groups, key=lambda group: (-depths[group.id], group_indices[group.id]))
    ordered_groups = sorted(groups, key=lambda group: (depths[group.id], group_indices[group.id]))
    prepared_by_id: dict[str, PreparedGroupLayout] = {}

    for group in preparation_order:
        member_bounds = union_bounds([nodes[node_id].bounds for node_id in group.node_ids])
        top_reserve = _group_internal_back_edge_top_reserve(group, validated, nodes)
        left_reserve, right_reserve = _group_internal_back_edge_side_reserves(
            group,
            validated,
            nodes,
            validated.theme,
            member_bounds,
        )
        direct_child_ids = children_by_parent.get(group.id, ())
        has_direct_children = bool(direct_child_ids)
        content_bounds = _group_content_bounds(
            group=group,
            nodes=nodes,
            edge_lookup=edge_lookup,
            group_nodes=group_nodes,
            direct_child_ids=direct_child_ids,
            prepared_by_id=prepared_by_id,
        )
        bounds = _group_clearance_bounds_for_member_bounds(
            content_bounds,
            validated.theme,
            top_reserve=top_reserve,
            left_reserve=left_reserve,
            right_reserve=right_reserve,
        )
        header_top = round(bounds.y + _group_label_padding(validated.theme), 2)
        header_bottom = round(content_bounds.y if has_direct_children else member_bounds.y, 2)
        prepared_by_id[group.id] = PreparedGroupLayout(
            group=group,
            bounds=bounds,
            member_bounds=member_bounds,
            content_bounds=content_bounds,
            header_top=header_top,
            header_bottom=header_bottom,
            top_reserve=top_reserve,
            depth=depths[group.id],
        )

    return tuple(prepared_by_id[group.id] for group in ordered_groups)


def _group_content_bounds(
    *,
    group: "Group",
    nodes: dict[str, LayoutNode],
    edge_lookup: dict[str, RoutedEdge] | None,
    group_nodes: dict[str, frozenset[str]],
    direct_child_ids: tuple[str, ...],
    prepared_by_id: dict[str, PreparedGroupLayout],
) -> Bounds:
    if not direct_child_ids:
        return _group_leaf_content_bounds(group, nodes, edge_lookup)

    child_node_ids = {
        node_id
        for child_id in direct_child_ids
        for node_id in group_nodes[child_id]
    }
    bounds = [prepared_by_id[child_id].bounds for child_id in direct_child_ids if child_id in prepared_by_id]
    bounds.extend(nodes[node_id].bounds for node_id in group.node_ids if node_id not in child_node_ids)
    if edge_lookup is not None:
        bounds.extend(edge_lookup[edge_id].bounds for edge_id in group.edge_ids if edge_id in edge_lookup)
    return union_bounds(bounds)


def _group_leaf_content_bounds(
    group: "Group",
    nodes: dict[str, LayoutNode],
    edge_lookup: dict[str, RoutedEdge] | None,
) -> Bounds:
    bounds = [nodes[node_id].bounds for node_id in group.node_ids]
    if edge_lookup is not None:
        bounds.extend(edge_lookup[edge_id].bounds for edge_id in group.edge_ids if edge_id in edge_lookup)
    return union_bounds(bounds)


def _direct_group_parent_ids(
    groups: tuple["Group", ...],
    group_nodes: dict[str, frozenset[str]],
) -> dict[str, str]:
    parent_ids: dict[str, str] = {}

    for group in groups:
        node_ids = group_nodes[group.id]
        candidates = [
            other.id
            for other in groups
            if other.id != group.id and node_ids < group_nodes[other.id]
        ]
        if not candidates:
            continue

        min_size = min(len(group_nodes[group_id]) for group_id in candidates)
        smallest = [group_id for group_id in candidates if len(group_nodes[group_id]) == min_size]
        if len(smallest) == 1:
            parent_ids[group.id] = smallest[0]

    return parent_ids


def _group_depths(
    groups: tuple["Group", ...],
    parent_ids: dict[str, str],
) -> dict[str, int]:
    depths: dict[str, int] = {}

    def _depth(group_id: str) -> int:
        if group_id in depths:
            return depths[group_id]
        parent_id = parent_ids.get(group_id)
        depths[group_id] = 0 if parent_id is None else _depth(parent_id) + 1
        return depths[group_id]

    for group in groups:
        _depth(group.id)
    return depths


def _group_children_by_parent(
    parent_ids: dict[str, str],
    group_indices: dict[str, int],
) -> dict[str, tuple[str, ...]]:
    children_by_parent: dict[str, list[str]] = defaultdict(list)
    for child_id, parent_id in parent_ids.items():
        children_by_parent[parent_id].append(child_id)
    return {
        parent_id: tuple(sorted(child_ids, key=lambda child_id: group_indices[child_id]))
        for parent_id, child_ids in children_by_parent.items()
    }


def _group_clearance_bounds(
    group: "Group",
    nodes: dict[str, LayoutNode],
    theme: "Theme",
) -> Bounds:
    return _group_clearance_bounds_for_member_bounds(
        union_bounds([nodes[node_id].bounds for node_id in group.node_ids]),
        theme,
    )


def _group_clearance_bounds_for_member_bounds(
    member_bounds: Bounds,
    theme: "Theme",
    *,
    top_reserve: float = 0.0,
    left_reserve: float = 0.0,
    right_reserve: float = 0.0,
) -> Bounds:
    bounds = member_bounds.expand(theme.group_padding)
    label_padding = _group_label_padding(theme)
    return Bounds(
        x=bounds.x - left_reserve,
        y=bounds.y - label_padding * 0.5 - top_reserve,
        width=bounds.width + left_reserve + right_reserve,
        height=bounds.height + label_padding * 0.5 + top_reserve,
    )


def _group_label_padding(theme: "Theme") -> float:
    return resolve_theme_metrics(theme).group_label_padding


def _group_internal_back_edge_top_reserve(
    group: "Group",
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
) -> float:
    group_node_ids = set(group.node_ids)
    has_internal_back_edge = any(
        not _is_self_loop(validated, edge)
        and edge.source in group_node_ids
        and _target_node_id(validated, edge) in group_node_ids
        and nodes[edge.source].rank >= nodes[_target_node_id(validated, edge)].rank
        for edge in validated.edges
    )
    if not has_internal_back_edge:
        return 0.0
    member_heights = [nodes[node_id].height for node_id in group.node_ids]
    return round(min(member_heights) * 0.5, 2)


def _group_internal_back_edge_side_reserves(
    group: "Group",
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
    theme: "Theme",
    member_bounds: Bounds,
) -> tuple[float, float]:
    group_node_ids = set(group.node_ids)
    left_reserve = 0.0
    right_reserve = 0.0

    for edge in validated.edges:
        target_node_id = _target_node_id(validated, edge)
        if (
            _is_self_loop(validated, edge)
            or edge.source not in group_node_ids
            or target_node_id not in group_node_ids
            or nodes[edge.source].rank < nodes[target_node_id].rank
        ):
            continue

        source_node = nodes[edge.source]
        target_node = nodes[target_node_id]
        desired_right_corridor = source_node.width * 0.35
        current_right_corridor = theme.group_padding + (member_bounds.right - source_node.right)
        desired_left_corridor = target_node.width * 0.35
        current_left_corridor = theme.group_padding + (target_node.x - member_bounds.x)

        right_reserve = max(right_reserve, desired_right_corridor - current_right_corridor)
        left_reserve = max(left_reserve, desired_left_corridor - current_left_corridor)

    return round(max(left_reserve, 0.0), 2), round(max(right_reserve, 0.0), 2)


def compute_group_overlays(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
    routed_edges: tuple[RoutedEdge, ...],
) -> tuple[GroupOverlay, ...]:
    edge_lookup = {route.edge.id: route for route in routed_edges}
    overlays = [
        GroupOverlay(
            group=prepared.group,
            bounds=prepared.bounds,
            stroke=prepared.group.stroke or validated.theme.group_stroke,
            fill=prepared.group.fill or validated.theme.group_fill,
        )
        for prepared in _prepare_group_layouts(validated, nodes, edge_lookup=edge_lookup)
    ]

    for group in validated.groups:
        if group.node_ids or not group.edge_ids:
            continue
        edge_bounds = [edge_lookup[edge_id].bounds for edge_id in group.edge_ids if edge_id in edge_lookup]
        if not edge_bounds:
            continue
        overlays.append(
            GroupOverlay(
                group=group,
                bounds=_group_clearance_bounds_for_member_bounds(union_bounds(edge_bounds), validated.theme),
                stroke=group.stroke or validated.theme.group_stroke,
                fill=group.fill or validated.theme.group_fill,
            )
        )

    return tuple(overlays)


def _build_component_geometry(
    nodes: dict[str, LayoutNode],
    theme: "Theme",
    routing_groups: RoutingGroups | None = None,
) -> dict[int, ComponentGeometry]:
    by_component: dict[int, list[LayoutNode]] = defaultdict(list)
    for node in nodes.values():
        by_component[node.component_id].append(node)

    geometry_by_component: dict[int, ComponentGeometry] = {}
    for component_id, component_nodes in by_component.items():
        rank_nodes: dict[int, list[LayoutNode]] = defaultdict(list)
        row_nodes: dict[int, list[LayoutNode]] = defaultdict(list)

        for node in component_nodes:
            rank_nodes[node.rank].append(node)
            row_nodes[node.order].append(node)

        sorted_ranks = sorted(rank_nodes)
        sorted_rows = sorted(row_nodes)

        rank_left = {rank: min(node.x for node in rank_nodes[rank]) for rank in sorted_ranks}
        rank_right = {rank: max(node.right for node in rank_nodes[rank]) for rank in sorted_ranks}
        row_top = {row: min(node.y for node in row_nodes[row]) for row in sorted_rows}
        row_bottom = {row: max(node.bounds.bottom for node in row_nodes[row]) for row in sorted_rows}

        gap_after_rank: dict[int, tuple[float, float]] = {}
        gap_before_rank: dict[int, tuple[float, float]] = {}
        for left_rank, right_rank in zip(sorted_ranks, sorted_ranks[1:]):
            gap = (rank_right[left_rank], rank_left[right_rank])
            gap_after_rank[left_rank] = gap
            gap_before_rank[right_rank] = gap

        gap_after_row: dict[int, tuple[float, float]] = {}
        gap_before_row: dict[int, tuple[float, float]] = {}
        for upper_row, lower_row in zip(sorted_rows, sorted_rows[1:]):
            gap = (row_bottom[upper_row], row_top[lower_row])
            gap_after_row[upper_row] = gap
            gap_before_row[lower_row] = gap

        related_groups = ()
        if routing_groups is not None:
            related_groups = tuple(
                routing_groups.bounds_by_id[group_id]
                for group_id in routing_groups.component_group_ids.get(component_id, ())
            )

        outer_left = min(
            [min(rank_left.values()) - theme.back_edge_gap * 2]
            + [group_bounds.x - theme.back_edge_gap * 2 for group_bounds in related_groups]
        )
        outer_top = min(
            [min(row_top.values()) - theme.back_edge_gap]
            + [group_bounds.y - theme.back_edge_gap for group_bounds in related_groups]
        )
        outer_bottom = max(
            [max(row_bottom.values()) + theme.back_edge_gap]
            + [group_bounds.bottom + theme.back_edge_gap for group_bounds in related_groups]
        )
        outer_right = max(
            [max(rank_right.values()) + theme.back_edge_gap * 2]
            + [group_bounds.right + theme.back_edge_gap * 2 for group_bounds in related_groups]
        )

        geometry_by_component[component_id] = ComponentGeometry(
            rank_left=rank_left,
            rank_right=rank_right,
            row_top=row_top,
            row_bottom=row_bottom,
            gap_after_rank=gap_after_rank,
            gap_before_rank=gap_before_rank,
            gap_after_row=gap_after_row,
            gap_before_row=gap_before_row,
            outer_left=round(outer_left, 2),
            outer_top=round(outer_top, 2),
            outer_bottom=round(outer_bottom, 2),
            outer_right=round(outer_right, 2),
        )

    return geometry_by_component


def _assign_pair_offsets(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
) -> dict[str, float]:
    groups: dict[tuple[str, str], list["Edge"]] = defaultdict(list)
    offsets: dict[str, float] = {}

    for edge in validated.edges:
        groups[(edge.source, edge.target)].append(edge)

    for edges in groups.values():
        ordered = sorted(edges, key=lambda edge: edge.id)
        first_target_node_id = _target_node_id(validated, ordered[0])
        max_offset = min(
            validated.theme.route_track_gap * 0.4,
            min(nodes[ordered[0].source].height, nodes[first_target_node_id].height) / 4,
        )
        centered = _centered_offsets(len(ordered), max_offset if max_offset > 0 else 0.0)
        for edge, offset in zip(ordered, centered, strict=True):
            offsets[edge.id] = offset

    return offsets


def _assign_back_slots(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
) -> dict[str, int]:
    by_component: dict[int, list["Edge"]] = defaultdict(list)
    for edge in validated.edges:
        source_node = nodes[edge.source]
        if _is_edge_target(validated, edge):
            continue
        target_node = nodes[_target_node_id(validated, edge)]
        if not _is_self_loop(validated, edge) and source_node.rank >= target_node.rank:
            by_component[source_node.component_id].append(edge)

    slots: dict[str, int] = {}
    for edges in by_component.values():
        ordered = sorted(
            edges,
            key=lambda edge: (
                nodes[edge.source].rank,
                nodes[_target_node_id(validated, edge)].rank,
                nodes[edge.source].order,
                nodes[_target_node_id(validated, edge)].order,
                edge.id,
            ),
        )
        for slot, edge in enumerate(ordered):
            slots[edge.id] = slot
    return slots


def _assign_self_loop_slots(validated: "ValidatedPipeline | ValidatedDetailPanel") -> dict[str, int]:
    by_node: dict[str, list["Edge"]] = defaultdict(list)
    for edge in validated.edges:
        if _is_self_loop(validated, edge):
            by_node[edge.source].append(edge)

    slots: dict[str, int] = {}
    for edges in by_node.values():
        for slot, edge in enumerate(sorted(edges, key=lambda edge: edge.id)):
            slots[edge.id] = slot
    return slots


def _edge_route_order(
    edge: "Edge",
    nodes: dict[str, LayoutNode],
    target_node_ids: dict[str, str],
    edge_index: int,
) -> tuple[int, int, int, int, int]:
    source_node = nodes[edge.source]
    target_node = nodes[target_node_ids[edge.id]]
    if edge.source == target_node.node.id:
        kind = 2
    elif source_node.rank < target_node.rank:
        kind = 0
    else:
        kind = 1

    return (
        kind,
        abs(target_node.rank - source_node.rank),
        abs(target_node.order - source_node.order),
        source_node.rank,
        edge_index,
    )


def _select_forward_route(
    *,
    edge: "Edge",
    source_node: LayoutNode,
    target_node: LayoutNode,
    geometry: ComponentGeometry,
    nodes: dict[str, LayoutNode],
    occupancy: Occupancy,
    outgoing_count: int,
    incoming_count: int,
    pair_offset: float,
    routing_groups: RoutingGroups | None,
    theme: "Theme",
) -> CandidatePath:
    candidates = _build_forward_candidates(
        source_node=source_node,
        target_node=target_node,
        geometry=geometry,
        pair_offset=pair_offset,
        routing_groups=routing_groups,
        theme=theme,
    )
    evaluations: list[CandidateEvaluation] = []

    for candidate_index, (kind, candidate) in enumerate(candidates):
        interactions = _candidate_interaction_metrics(
            candidate,
            occupancy=occupancy,
            source_node_id=source_node.node.id,
            target_node_id=target_node.node.id,
            routing_groups=routing_groups,
        )
        evaluations.append(
            _build_forward_candidate_evaluation(
                kind=kind,
                candidate=candidate,
                candidate_index=candidate_index,
                source_node=source_node,
                target_node=target_node,
                nodes=nodes,
                outgoing_count=outgoing_count,
                incoming_count=incoming_count,
                theme=theme,
                interactions=interactions,
                routing_groups=routing_groups,
            )
        )

    selected = _select_candidate_evaluation(evaluations)
    assert selected is not None
    return selected.candidate


def _build_forward_candidate_evaluation(
    *,
    kind: str,
    candidate: CandidatePath,
    candidate_index: int,
    source_node: LayoutNode,
    target_node: LayoutNode,
    nodes: dict[str, LayoutNode],
    outgoing_count: int,
    incoming_count: int,
    theme: "Theme",
    interactions: InteractionMetrics,
    routing_groups: RoutingGroups | None,
) -> CandidateEvaluation:
    clearance_ok = _path_respects_group_clearance(
        candidate.points,
        source_node.node.id,
        target_node.node.id,
        routing_groups,
    )
    collisions, backwards, bends, length = _route_metrics(
        candidate,
        nodes=nodes,
        ignored_node_ids={source_node.node.id, target_node.node.id},
        theme=theme,
    )
    return CandidateEvaluation(
        clearance_ok=clearance_ok,
        shared_local=_candidate_uses_shared_local(kind),
        endpoint_preferred=_forward_endpoint_preferred(
            candidate,
            source_node=source_node,
            target_node=target_node,
            outgoing_count=outgoing_count,
            incoming_count=incoming_count,
            routing_groups=routing_groups,
        ),
        clean_direct=_forward_clean_direct_preferred(
            kind,
            candidate,
            source_node=source_node,
            target_node=target_node,
            collisions=collisions,
            interactions=interactions,
        ),
        collisions=collisions,
        edge_crossings=interactions.edge_crossings,
        edge_overlap_length=interactions.edge_overlap_length,
        kind_priority=_forward_kind_priority(
            kind=kind,
            outgoing_count=outgoing_count,
            incoming_count=incoming_count,
        ),
        backwards=backwards,
        bends=bends,
        length=length,
        candidate_index=candidate_index,
        candidate=candidate,
    )


def _route_forward(
    *,
    edge: "Edge",
    source_node: LayoutNode,
    target_node: LayoutNode,
    geometry: ComponentGeometry,
    nodes: dict[str, LayoutNode],
    outgoing_count: int,
    incoming_count: int,
    pair_offset: float,
    routing_groups: RoutingGroups | None = None,
    theme: "Theme",
) -> tuple[Point, ...]:
    return _select_forward_route(
        edge=edge,
        source_node=source_node,
        target_node=target_node,
        geometry=geometry,
        nodes=nodes,
        occupancy=Occupancy(),
        outgoing_count=outgoing_count,
        incoming_count=incoming_count,
        pair_offset=pair_offset,
        routing_groups=routing_groups,
        theme=theme,
    ).points


def _assign_edge_join_plans(
    *,
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    edges: tuple["Edge", ...],
    nodes: dict[str, LayoutNode],
    routed_by_id: dict[str, RoutedEdge],
    pair_offsets: dict[str, float],
) -> dict[str, EdgeJoinPlan]:
    by_segment: dict[tuple[str, int], list[tuple["Edge", JoinSegmentChoice]]] = defaultdict(list)
    merge_edges_by_target: dict[str, list["Edge"]] = defaultdict(list)

    for edge in edges:
        target_edge_id = _target_edge_id(validated, edge)
        assert target_edge_id is not None
        if edge.merge_symbol is not None:
            merge_edges_by_target[target_edge_id].append(edge)
            continue
        choice = _choose_join_segment(
            validated=validated,
            edge=edge,
            source_node=nodes[edge.source],
            target_node=nodes[_target_node_id(validated, edge)],
            target_route=routed_by_id[target_edge_id],
            pair_offset=pair_offsets.get(edge.id, 0.0),
        )
        by_segment[(choice.target_edge_id, choice.segment_index)].append((edge, choice))

    plans: dict[str, EdgeJoinPlan] = {}
    for segment_edges in by_segment.values():
        choice = segment_edges[0][1]
        orientation = choice.orientation
        margin = _join_endpoint_margin(validated.theme)
        spacing = _join_spacing(validated.theme)
        if orientation == "h":
            low, high = sorted((choice.start.x, choice.end.x))
        else:
            low, high = sorted((choice.start.y, choice.end.y))
        low += margin
        high -= margin
        if low > high:
            midpoint = round((low + high) / 2, 2)
            low = midpoint
            high = midpoint

        ordered = sorted(
            segment_edges,
            key=lambda item: (
                nodes[item[0].source].order,
                nodes[item[0].source].rank,
                validated.node_index[item[0].source],
                item[0].id,
            ),
        )
        preferred_positions = [item[1].preferred_position for item in ordered]
        coordinates = _distributed_join_positions(low, high, preferred_positions, spacing)

        for coordinate, (edge, edge_choice) in zip(coordinates, ordered, strict=True):
            join_point = (
                Point(round(coordinate, 2), edge_choice.start.y)
                if orientation == "h"
                else Point(edge_choice.start.x, round(coordinate, 2))
            )
            plans[edge.id] = EdgeJoinPlan(
                target_edge_id=edge_choice.target_edge_id,
                target_node_id=edge_choice.target_node_id,
                segment_index=edge_choice.segment_index,
                start=edge_choice.start,
                end=edge_choice.end,
                orientation=orientation,
                join_point=join_point,
            )

    badge_spacing = _merge_badge_spacing(validated.theme)
    margin = _join_endpoint_margin(validated.theme)
    for target_edge_id, target_edges in merge_edges_by_target.items():
        target_route = routed_by_id[target_edge_id]
        total_length = _path_length(target_route.points)
        if total_length <= EPSILON:
            continue

        center_distance = total_length / 2.0
        ordered = sorted(
            target_edges,
            key=lambda edge: (
                nodes[edge.source].order,
                nodes[edge.source].rank,
                validated.node_index[edge.source],
                edge.id,
            ),
        )
        offsets = _centered_offsets(len(ordered), badge_spacing)
        min_distance = margin
        max_distance = total_length - margin

        for edge, offset in zip(ordered, offsets, strict=True):
            distance = center_distance + offset
            if max_distance > min_distance:
                distance = min(max(distance, min_distance), max_distance)
            else:
                distance = center_distance

            location = _path_location_at_distance(target_route.points, distance)
            plans[edge.id] = EdgeJoinPlan(
                target_edge_id=target_edge_id,
                target_node_id=_target_node_id(validated, edge),
                segment_index=location.segment_index,
                start=location.start,
                end=location.end,
                orientation=location.orientation,
                join_point=location.point,
            )

    return plans


def _choose_join_segment(
    *,
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    edge: "Edge",
    source_node: LayoutNode,
    target_node: LayoutNode,
    target_route: RoutedEdge,
    pair_offset: float,
) -> JoinSegmentChoice:
    direction = _edge_direction_kind(source_node, target_node)
    source_reference = _right_port(source_node, pair_offset)
    candidates: list[JoinSegmentChoice] = []
    fallback_candidates: list[JoinSegmentChoice] = []

    for segment_index, (start, end) in enumerate(zip(target_route.points, target_route.points[1:])):
        orientation = _segment_direction(start, end)
        if orientation is None or not _segment_is_join_eligible(start, end, validated.theme):
            continue

        preferred_point = _closest_join_point(source_reference, start, end, validated.theme)
        choice = JoinSegmentChoice(
            target_edge_id=target_route.edge.id,
            target_node_id=target_node.node.id,
            segment_index=segment_index,
            start=start,
            end=end,
            orientation=orientation,
            preferred_position=preferred_point.x if orientation == "h" else preferred_point.y,
            distance=abs(source_reference.x - preferred_point.x) + abs(source_reference.y - preferred_point.y),
        )
        fallback_candidates.append(choice)
        if _segment_is_direction_compatible(source_node, target_node, start, end, direction, validated.theme):
            candidates.append(choice)

    if candidates:
        return min(candidates, key=lambda item: (item.distance, item.segment_index, item.target_edge_id))
    if fallback_candidates:
        return min(fallback_candidates, key=lambda item: (item.distance, item.segment_index, item.target_edge_id))
    raise AssertionError(f"No eligible join segment found for edge {edge.id}.")


def _select_edge_join_route(
    *,
    edge: "Edge",
    source_node: LayoutNode,
    target_node: LayoutNode,
    join_plan: EdgeJoinPlan,
    geometry: ComponentGeometry,
    nodes: dict[str, LayoutNode],
    occupancy: Occupancy,
    pair_offset: float,
    routing_groups: RoutingGroups | None,
    theme: "Theme",
) -> CandidatePath:
    candidates = _build_edge_join_candidates(
        source_node=source_node,
        target_node=target_node,
        join_plan=join_plan,
        geometry=geometry,
        pair_offset=pair_offset,
        routing_groups=routing_groups,
        theme=theme,
    )
    direction = _edge_direction_kind(source_node, target_node)
    evaluations: list[CandidateEvaluation] = []

    for candidate_index, (kind, candidate) in enumerate(candidates):
        interactions = _candidate_interaction_metrics(
            candidate,
            occupancy=occupancy,
            source_node_id=source_node.node.id,
            target_node_id=target_node.node.id,
            routing_groups=routing_groups,
        )
        evaluations.append(
            _build_edge_join_candidate_evaluation(
                kind=kind,
                candidate=candidate,
                candidate_index=candidate_index,
                source_node=source_node,
                target_node=target_node,
                nodes=nodes,
                theme=theme,
                direction=direction,
                interactions=interactions,
                routing_groups=routing_groups,
            )
        )

    selected = _select_candidate_evaluation(evaluations)
    if selected is not None:
        return selected.candidate
    raise AssertionError(f"No viable join route found for edge {edge.id}.")


def _build_edge_join_candidate_evaluation(
    *,
    kind: str,
    candidate: CandidatePath,
    candidate_index: int,
    source_node: LayoutNode,
    target_node: LayoutNode,
    nodes: dict[str, LayoutNode],
    theme: "Theme",
    direction: str,
    interactions: InteractionMetrics,
    routing_groups: RoutingGroups | None,
) -> CandidateEvaluation:
    clearance_ok = _path_respects_group_clearance(
        candidate.points,
        source_node.node.id,
        target_node.node.id,
        routing_groups,
    )
    collisions, backwards, bends, length = _route_metrics(
        candidate,
        nodes=nodes,
        ignored_node_ids={source_node.node.id, target_node.node.id},
        theme=theme,
    )
    return CandidateEvaluation(
        clearance_ok=clearance_ok,
        shared_local=_candidate_uses_shared_local(kind),
        endpoint_preferred=True,
        clean_direct=False,
        collisions=collisions,
        edge_crossings=interactions.edge_crossings,
        edge_overlap_length=interactions.edge_overlap_length,
        kind_priority=_edge_join_kind_priority(
            kind=kind,
            direction=direction,
        ),
        backwards=backwards,
        bends=bends,
        length=length,
        candidate_index=candidate_index,
        candidate=candidate,
    )


def _build_edge_join_candidates(
    *,
    source_node: LayoutNode,
    target_node: LayoutNode,
    join_plan: EdgeJoinPlan,
    geometry: ComponentGeometry,
    pair_offset: float,
    routing_groups: RoutingGroups | None,
    theme: "Theme",
) -> list[tuple[str, CandidatePath]]:
    join_point = join_plan.join_point
    source_right = _right_port(source_node, pair_offset)
    shared_row_lanes = _shared_group_row_lane_positions(
        source_node.node.id,
        target_node.node.id,
        routing_groups,
        theme,
    )
    shared_column_lanes = _shared_group_column_lane_positions(
        source_node,
        target_node,
        geometry,
        routing_groups,
        theme,
    )
    outer_row_lanes = _outer_row_lane_positions(geometry, theme)
    outer_column_lanes = _outer_column_lane_positions(geometry, theme)
    row_lanes = _unique_lanes(
        _source_row_lane_positions(source_node, target_node, geometry, theme)
        + _target_row_lane_positions(source_node, target_node, geometry, theme)
    )
    column_lanes = _unique_lanes(
        _join_column_lane_positions(source_node, target_node, geometry, theme)
    )
    candidates: dict[tuple[Point, ...], tuple[str, CandidatePath]] = {}

    def add_candidate(kind: str, start: Point, segments: list[tuple[Point, str]]) -> None:
        candidate = _build_candidate(start, segments)
        candidates.setdefault(candidate.points, (kind, candidate))

    if join_plan.orientation == "h":
        add_candidate(
            "direct_join",
            source_right,
            [
                (Point(join_point.x, source_right.y), "reserve"),
                (join_point, "stub"),
            ],
        )
        for lane_y in shared_row_lanes:
            source_vertical = _vertical_port(source_node, pair_offset, lane_y)
            add_candidate(
                "shared_row_join",
                source_vertical,
                [
                    (Point(source_vertical.x, lane_y), "stub"),
                    (Point(join_point.x, lane_y), "reserve"),
                    (join_point, "stub"),
                ],
            )
            add_candidate(
                "shared_row_join",
                source_right,
                [
                    (Point(source_right.x, lane_y), "reserve"),
                    (Point(join_point.x, lane_y), "reserve"),
                    (join_point, "stub"),
                ],
            )
        for lane_y in row_lanes:
            source_vertical = _vertical_port(source_node, pair_offset, lane_y)
            add_candidate(
                "row_join",
                source_vertical,
                [
                    (Point(source_vertical.x, lane_y), "stub"),
                    (Point(join_point.x, lane_y), "reserve"),
                    (join_point, "stub"),
                ],
            )
            add_candidate(
                "row_join",
                source_right,
                [
                    (Point(source_right.x, lane_y), "reserve"),
                    (Point(join_point.x, lane_y), "reserve"),
                    (join_point, "stub"),
                ],
            )
        for lane_y in outer_row_lanes:
            source_vertical = _vertical_port(source_node, pair_offset, lane_y)
            add_candidate(
                "outer_row_join",
                source_vertical,
                [
                    (Point(source_vertical.x, lane_y), "stub"),
                    (Point(join_point.x, lane_y), "reserve"),
                    (join_point, "stub"),
                ],
            )
            add_candidate(
                "outer_row_join",
                source_right,
                [
                    (Point(source_right.x, lane_y), "reserve"),
                    (Point(join_point.x, lane_y), "reserve"),
                    (join_point, "stub"),
                ],
            )
        for lane_x in shared_column_lanes:
            for lane_y in shared_row_lanes:
                add_candidate(
                    "shared_join",
                    source_right,
                    [
                        (Point(lane_x, source_right.y), "reserve"),
                        (Point(lane_x, lane_y), "reserve"),
                        (Point(join_point.x, lane_y), "reserve"),
                        (join_point, "stub"),
                    ],
                )
        for lane_x in column_lanes:
            for lane_y in row_lanes:
                add_candidate(
                    "lane_join",
                    source_right,
                    [
                        (Point(lane_x, source_right.y), "reserve"),
                        (Point(lane_x, lane_y), "reserve"),
                        (Point(join_point.x, lane_y), "reserve"),
                        (join_point, "stub"),
                    ],
                )
        for lane_x in _unique_lanes(shared_column_lanes + column_lanes + outer_column_lanes):
            for lane_y in outer_row_lanes:
                add_candidate(
                    "outer_join",
                    source_right,
                    [
                        (Point(lane_x, source_right.y), "reserve"),
                        (Point(lane_x, lane_y), "reserve"),
                        (Point(join_point.x, lane_y), "reserve"),
                        (join_point, "stub"),
                    ],
                )
    else:
        add_candidate(
            "direct_join",
            source_right,
            [
                (Point(source_right.x, join_point.y), "reserve"),
                (join_point, "stub"),
            ],
        )
        for lane_x in shared_column_lanes:
            add_candidate(
                "shared_column_join",
                source_right,
                [
                    (Point(lane_x, source_right.y), "reserve"),
                    (Point(lane_x, join_point.y), "reserve"),
                    (join_point, "stub"),
                ],
            )
        for lane_x in column_lanes:
            add_candidate(
                "column_join",
                source_right,
                [
                    (Point(lane_x, source_right.y), "reserve"),
                    (Point(lane_x, join_point.y), "reserve"),
                    (join_point, "stub"),
                ],
            )
        for lane_x in outer_column_lanes:
            add_candidate(
                "outer_column_join",
                source_right,
                [
                    (Point(lane_x, source_right.y), "reserve"),
                    (Point(lane_x, join_point.y), "reserve"),
                    (join_point, "stub"),
                ],
            )
        for lane_y in shared_row_lanes:
            source_vertical = _vertical_port(source_node, pair_offset, lane_y)
            for lane_x in shared_column_lanes:
                add_candidate(
                    "shared_join",
                    source_vertical,
                    [
                        (Point(source_vertical.x, lane_y), "stub"),
                        (Point(lane_x, lane_y), "reserve"),
                        (Point(lane_x, join_point.y), "reserve"),
                        (join_point, "stub"),
                    ],
                )
        for lane_y in row_lanes:
            source_vertical = _vertical_port(source_node, pair_offset, lane_y)
            for lane_x in column_lanes:
                add_candidate(
                    "lane_join",
                    source_vertical,
                    [
                        (Point(source_vertical.x, lane_y), "stub"),
                        (Point(lane_x, lane_y), "reserve"),
                        (Point(lane_x, join_point.y), "reserve"),
                        (join_point, "stub"),
                    ],
                )
        for lane_y in _unique_lanes(shared_row_lanes + row_lanes + outer_row_lanes):
            source_vertical = _vertical_port(source_node, pair_offset, lane_y)
            for lane_x in outer_column_lanes:
                add_candidate(
                    "outer_join",
                    source_vertical,
                    [
                        (Point(source_vertical.x, lane_y), "stub"),
                        (Point(lane_x, lane_y), "reserve"),
                        (Point(lane_x, join_point.y), "reserve"),
                        (join_point, "stub"),
                    ],
                )

    return list(candidates.values())


def _join_column_lane_positions(
    source_node: LayoutNode,
    target_node: LayoutNode,
    geometry: ComponentGeometry,
    theme: "Theme",
) -> tuple[float, ...]:
    lanes: list[float] = []
    if source_node.rank in geometry.gap_after_rank:
        lanes.extend(_ordered_gap_positions(geometry.gap_after_rank[source_node.rank], theme, "start"))
    if target_node.rank in geometry.gap_before_rank:
        lanes.extend(_ordered_gap_positions(geometry.gap_before_rank[target_node.rank], theme, "end"))
    return tuple(lanes)


def _unique_lanes(lanes: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(dict.fromkeys(round(lane, 2) for lane in lanes))


def _build_forward_candidates(
    *,
    source_node: LayoutNode,
    target_node: LayoutNode,
    geometry: ComponentGeometry,
    pair_offset: float,
    routing_groups: RoutingGroups | None,
    theme: "Theme",
) -> list[tuple[str, CandidatePath]]:
    candidates: list[tuple[str, CandidatePath]] = []
    shared_row_lanes = _shared_group_row_lane_positions(
        source_node.node.id,
        target_node.node.id,
        routing_groups,
        theme,
    )

    if source_node.order == target_node.order:
        candidates.append(("direct", _direct_same_row_candidate(source_node, target_node, geometry, pair_offset, theme)))
    else:
        candidates.append(("direct_elbow", _direct_elbow_candidate(source_node, target_node, pair_offset)))

    for lane_y in shared_row_lanes:
        candidates.append(("shared_row", _row_source_candidate(source_node, target_node, lane_y, pair_offset)))
        candidates.append(("shared_row", _row_target_candidate(source_node, target_node, lane_y, pair_offset)))

    if source_node.rank in geometry.gap_after_rank:
        for lane_x in _ordered_gap_positions(geometry.gap_after_rank[source_node.rank], theme, "start"):
            candidates.append(
                (
                    "column_source",
                    _column_source_candidate(source_node, target_node, lane_x, pair_offset),
                )
            )

    if target_node.rank in geometry.gap_before_rank:
        for lane_x in _ordered_gap_positions(geometry.gap_before_rank[target_node.rank], theme, "end"):
            candidates.append(
                (
                    "column_target",
                    _column_target_candidate(source_node, target_node, lane_x, pair_offset),
                )
            )

    for lane_y in _source_row_lane_positions(source_node, target_node, geometry, theme):
        candidates.append(("row_source", _row_source_candidate(source_node, target_node, lane_y, pair_offset)))

    for lane_y in _target_row_lane_positions(source_node, target_node, geometry, theme):
        candidates.append(("row_target", _row_target_candidate(source_node, target_node, lane_y, pair_offset)))

    for lane_y in _outer_row_lane_positions(geometry, theme):
        candidates.append(("outer_row", _outer_row_candidate(source_node, target_node, lane_y, pair_offset)))

    for lane_x in _outer_column_lane_positions(geometry, theme):
        candidates.append(("outer_column", _outer_column_candidate(source_node, target_node, lane_x, pair_offset)))

    unique: dict[tuple[Point, ...], tuple[str, CandidatePath]] = {}
    for kind, candidate in candidates:
        unique.setdefault(candidate.points, (kind, candidate))

    return list(unique.values())


def _direct_same_row_candidate(
    source_node: LayoutNode,
    target_node: LayoutNode,
    geometry: ComponentGeometry,
    pair_offset: float,
    theme: "Theme",
) -> CandidatePath:
    y = round(source_node.center_y + pair_offset, 2)
    source = Point(source_node.right, y)
    target = Point(target_node.x, y)
    split_x = _stub_x_after_rank(source_node.rank, geometry, theme)
    merge_x = _stub_x_before_rank(target_node.rank, geometry, theme)

    if split_x >= merge_x - EPSILON:
        return _build_candidate(
            source,
            [(target, "reserve")],
        )

    return _build_candidate(
        source,
        [
            (Point(split_x, y), "stub"),
            (Point(merge_x, y), "reserve"),
            (target, "stub"),
        ],
    )


def _direct_elbow_candidate(
    source_node: LayoutNode,
    target_node: LayoutNode,
    pair_offset: float,
) -> CandidatePath:
    source = _right_port(source_node, pair_offset)
    target = _vertical_port(target_node, pair_offset, source.y)
    return _build_candidate(
        source,
        [
            (Point(target.x, source.y), "reserve"),
            (target, "stub"),
        ],
    )


def _column_source_candidate(
    source_node: LayoutNode,
    target_node: LayoutNode,
    lane_x: float,
    pair_offset: float,
) -> CandidatePath:
    source = _right_port(source_node, pair_offset)
    target = _left_port(target_node, pair_offset)
    return _build_candidate(
        source,
        [
            (Point(lane_x, source.y), "stub"),
            (Point(lane_x, target.y), "reserve"),
            (target, "reserve"),
        ],
    )


def _column_target_candidate(
    source_node: LayoutNode,
    target_node: LayoutNode,
    lane_x: float,
    pair_offset: float,
) -> CandidatePath:
    source = _right_port(source_node, pair_offset)
    target = _left_port(target_node, pair_offset)
    return _build_candidate(
        source,
        [
            (Point(lane_x, source.y), "reserve"),
            (Point(lane_x, target.y), "reserve"),
            (target, "stub"),
        ],
    )


def _row_source_candidate(
    source_node: LayoutNode,
    target_node: LayoutNode,
    lane_y: float,
    pair_offset: float,
) -> CandidatePath:
    source = _vertical_port(source_node, pair_offset, lane_y)
    target = _vertical_port(target_node, pair_offset, lane_y)
    return _build_candidate(
        source,
        [
            (Point(source.x, lane_y), "stub"),
            (Point(target.x, lane_y), "reserve"),
            (target, "reserve"),
        ],
    )


def _row_target_candidate(
    source_node: LayoutNode,
    target_node: LayoutNode,
    lane_y: float,
    pair_offset: float,
) -> CandidatePath:
    source = _vertical_port(source_node, pair_offset, lane_y)
    target = _vertical_port(target_node, pair_offset, lane_y)
    return _build_candidate(
        source,
        [
            (Point(source.x, lane_y), "reserve"),
            (Point(target.x, lane_y), "reserve"),
            (target, "stub"),
        ],
    )


def _outer_row_candidate(
    source_node: LayoutNode,
    target_node: LayoutNode,
    lane_y: float,
    pair_offset: float,
) -> CandidatePath:
    source = _vertical_port(source_node, pair_offset, lane_y)
    target = _vertical_port(target_node, pair_offset, lane_y)
    return _build_candidate(
        source,
        [
            (Point(source.x, lane_y), "reserve"),
            (Point(target.x, lane_y), "reserve"),
            (target, "reserve"),
        ],
    )


def _outer_column_candidate(
    source_node: LayoutNode,
    target_node: LayoutNode,
    lane_x: float,
    pair_offset: float,
) -> CandidatePath:
    source = _right_port(source_node, pair_offset)
    target = _left_port(target_node, pair_offset)
    return _build_candidate(
        source,
        [
            (Point(lane_x, source.y), "reserve"),
            (Point(lane_x, target.y), "reserve"),
            (target, "reserve"),
        ],
    )


def _build_candidate(
    start: Point,
    segments: list[tuple[Point, str]],
) -> CandidatePath:
    points = [start]
    kinds: list[str] = []

    for point, kind in segments:
        if point == points[-1]:
            continue
        points.append(point)
        kinds.append(kind)

    reserved = tuple(index for index, kind in enumerate(kinds) if kind == "reserve")
    if not reserved and len(points) >= 2:
        reserved = tuple(range(len(points) - 1))

    return CandidatePath(points=tuple(points), reserved_segments=reserved)


def _source_row_lane_positions(
    source_node: LayoutNode,
    target_node: LayoutNode,
    geometry: ComponentGeometry,
    theme: "Theme",
) -> tuple[float, ...]:
    lanes: list[float] = []

    if target_node.order >= source_node.order:
        gap = geometry.gap_after_row.get(source_node.order)
        if gap is not None:
            lanes.extend(_ordered_gap_positions(gap, theme, "start"))
    if target_node.order <= source_node.order:
        gap = geometry.gap_before_row.get(source_node.order)
        if gap is not None:
            lanes.extend(_ordered_gap_positions(gap, theme, "end"))

    return tuple(lanes)


def _target_row_lane_positions(
    source_node: LayoutNode,
    target_node: LayoutNode,
    geometry: ComponentGeometry,
    theme: "Theme",
) -> tuple[float, ...]:
    lanes: list[float] = []

    if source_node.order <= target_node.order:
        gap = geometry.gap_before_row.get(target_node.order)
        if gap is not None:
            lanes.extend(_ordered_gap_positions(gap, theme, "end"))
    if source_node.order >= target_node.order:
        gap = geometry.gap_after_row.get(target_node.order)
        if gap is not None:
            lanes.extend(_ordered_gap_positions(gap, theme, "start"))

    return tuple(lanes)


def _shared_group_row_lane_positions(
    source_node_id: str,
    target_node_id: str,
    routing_groups: RoutingGroups | None,
    theme: "Theme",
) -> tuple[float, ...]:
    frame = _shared_group_frame(source_node_id, target_node_id, routing_groups)
    if frame is None:
        return ()

    lanes = tuple(_shared_group_back_edge_lane_y(frame, slot, theme) for slot in range(3))
    return _unique_lanes(lanes)


def _shared_group_column_lane_positions(
    source_node: LayoutNode,
    target_node: LayoutNode,
    geometry: ComponentGeometry,
    routing_groups: RoutingGroups | None,
    theme: "Theme",
) -> tuple[float, ...]:
    frame = _shared_group_frame(source_node.node.id, target_node.node.id, routing_groups)
    if frame is None:
        return ()

    lanes: list[float] = []

    if source_node.rank in geometry.gap_after_rank:
        clipped_gap = _clip_lane_gap(geometry.gap_after_rank[source_node.rank], frame.bounds.x, frame.bounds.right)
        if clipped_gap is not None:
            lanes.extend(_ordered_gap_positions(clipped_gap, theme, "start"))

    if target_node.rank in geometry.gap_before_rank:
        clipped_gap = _clip_lane_gap(geometry.gap_before_rank[target_node.rank], frame.bounds.x, frame.bounds.right)
        if clipped_gap is not None:
            lanes.extend(_ordered_gap_positions(clipped_gap, theme, "end"))

    return _unique_lanes(tuple(lanes))


def _outer_row_lane_positions(
    geometry: ComponentGeometry,
    theme: "Theme",
) -> tuple[float, ...]:
    return (
        round(geometry.outer_top, 2),
        round(geometry.outer_top - theme.route_track_gap, 2),
        round(geometry.outer_bottom, 2),
        round(geometry.outer_bottom + theme.route_track_gap, 2),
    )


def _outer_column_lane_positions(
    geometry: ComponentGeometry,
    theme: "Theme",
) -> tuple[float, ...]:
    return (
        round(geometry.outer_right, 2),
        round(geometry.outer_right + theme.route_track_gap, 2),
    )


def _ordered_gap_positions(
    gap: tuple[float, float],
    theme: "Theme",
    preferred_edge: str,
) -> tuple[float, ...]:
    positions = _lane_positions(gap[0], gap[1], theme.route_track_gap)
    boundary = gap[0] if preferred_edge == "start" else gap[1]
    return tuple(
        sorted(
            positions,
            key=lambda position: (
                abs(position - boundary),
                position if preferred_edge == "start" else -position,
            ),
        )
    )


def _clip_lane_gap(
    gap: tuple[float, float],
    lower_bound: float,
    upper_bound: float,
) -> tuple[float, float] | None:
    start = round(max(gap[0], lower_bound), 2)
    end = round(min(gap[1], upper_bound), 2)
    if end - start <= EPSILON:
        return None
    return (start, end)


def _lane_positions(start: float, end: float, step: float) -> tuple[float, ...]:
    width = end - start
    if width <= step:
        return (round((start + end) / 2, 2),)

    count = max(1, int(width // step))
    total = step * (count - 1)
    origin = (start + end) / 2 - total / 2
    return tuple(round(origin + step * index, 2) for index in range(count))


def _stub_x_after_rank(rank: int, geometry: ComponentGeometry, theme: "Theme") -> float:
    if rank not in geometry.gap_after_rank:
        return round(geometry.rank_right[rank], 2)
    metrics = resolve_theme_metrics(theme)
    start, end = geometry.gap_after_rank[rank]
    return round(min(end, start + min(metrics.short_stub_extent, (end - start) / 2)), 2)


def _stub_x_before_rank(rank: int, geometry: ComponentGeometry, theme: "Theme") -> float:
    if rank not in geometry.gap_before_rank:
        return round(geometry.rank_left[rank], 2)
    metrics = resolve_theme_metrics(theme)
    start, end = geometry.gap_before_rank[rank]
    return round(max(start, end - min(metrics.short_stub_extent, (end - start) / 2)), 2)


def _right_port(node: LayoutNode, pair_offset: float) -> Point:
    return Point(node.right, round(node.center_y + pair_offset, 2))


def _left_port(node: LayoutNode, pair_offset: float) -> Point:
    return Point(node.x, round(node.center_y + pair_offset, 2))


def _vertical_port(node: LayoutNode, pair_offset: float, lane_y: float) -> Point:
    x = round(node.center_x + pair_offset, 2)
    if lane_y >= node.center_y:
        return Point(x, node.bounds.bottom)
    return Point(x, node.y)


def _select_candidate_evaluation(
    evaluations: list[CandidateEvaluation],
) -> CandidateEvaluation | None:
    if not evaluations:
        return None

    scoped = list(evaluations)
    scoped = _prefer_true(scoped, key=lambda evaluation: evaluation.clearance_ok)
    scoped = _prefer_true(scoped, key=lambda evaluation: evaluation.shared_local)
    scoped = _prefer_true(scoped, key=lambda evaluation: evaluation.clean_direct)
    scoped = _prefer_true(scoped, key=lambda evaluation: evaluation.endpoint_preferred)
    scoped = _prefer_zero_int(scoped, key=lambda evaluation: evaluation.collisions)
    scoped = _prefer_zero_int(scoped, key=lambda evaluation: evaluation.edge_crossings)
    scoped = _prefer_zero_float(scoped, key=lambda evaluation: evaluation.edge_overlap_length)
    scoped = _prefer_min_int(scoped, key=lambda evaluation: evaluation.kind_priority)
    scoped = _prefer_min_float(scoped, key=lambda evaluation: evaluation.backwards)
    scoped = _prefer_min_int(scoped, key=lambda evaluation: evaluation.bends)
    scoped = _prefer_min_float(scoped, key=lambda evaluation: evaluation.length)
    scoped = _prefer_min_int(scoped, key=lambda evaluation: evaluation.candidate_index)
    return scoped[0]


def _select_point_route_evaluation(
    evaluations: list[PointRouteEvaluation],
) -> PointRouteEvaluation | None:
    if not evaluations:
        return None

    scoped = list(evaluations)
    scoped = _prefer_true(scoped, key=lambda evaluation: evaluation.clearance_ok)
    scoped = _prefer_true(scoped, key=lambda evaluation: evaluation.shared_local)
    scoped = _prefer_zero_int(scoped, key=lambda evaluation: evaluation.edge_crossings)
    scoped = _prefer_zero_float(scoped, key=lambda evaluation: evaluation.edge_overlap_length)
    scoped = _prefer_min_int(scoped, key=lambda evaluation: evaluation.bends)
    scoped = _prefer_min_float(scoped, key=lambda evaluation: evaluation.length)
    scoped = _prefer_min_int(scoped, key=lambda evaluation: evaluation.slot)
    return scoped[0]


def _prefer_true(items: list[SelectionItem], *, key) -> list[SelectionItem]:
    if any(key(item) for item in items):
        return [item for item in items if key(item)]
    return items


def _prefer_zero_int(items: list[SelectionItem], *, key) -> list[SelectionItem]:
    zero_items = [item for item in items if key(item) == 0]
    if zero_items:
        return zero_items
    return _prefer_min_int(items, key=key)


def _prefer_zero_float(items: list[SelectionItem], *, key) -> list[SelectionItem]:
    zero_items = [item for item in items if key(item) <= EPSILON]
    if zero_items:
        return zero_items
    return _prefer_min_float(items, key=key)


def _prefer_min_int(items: list[SelectionItem], *, key) -> list[SelectionItem]:
    best = min(key(item) for item in items)
    return [item for item in items if key(item) == best]


def _prefer_min_float(items: list[SelectionItem], *, key) -> list[SelectionItem]:
    best = min(key(item) for item in items)
    return [item for item in items if key(item) <= best + EPSILON]


def _candidate_uses_shared_local(kind: str) -> bool:
    return kind.startswith("shared_")


def _forward_endpoint_preferred(
    candidate: CandidatePath,
    *,
    source_node: LayoutNode,
    target_node: LayoutNode,
    outgoing_count: int,
    incoming_count: int,
    routing_groups: RoutingGroups | None,
) -> bool:
    if _relevant_group_bounds_for_optional_routing_groups(
        source_node.node.id,
        target_node.node.id,
        routing_groups,
    ):
        return True

    fanout_context = outgoing_count > 1 and incoming_count <= 1
    fanin_context = incoming_count > 1 and outgoing_count <= 1
    preferred = True

    if fanout_context:
        preferred = preferred and candidate.points[0].x == source_node.right
    if fanin_context:
        preferred = preferred and candidate.points[-1].x == target_node.x

    return preferred


def _forward_clean_direct_preferred(
    kind: str,
    candidate: CandidatePath,
    *,
    source_node: LayoutNode,
    target_node: LayoutNode,
    collisions: int,
    interactions: InteractionMetrics,
) -> bool:
    if kind != "direct_elbow":
        return False
    if source_node.order >= target_node.order:
        return False
    if collisions != 0:
        return False
    if interactions.edge_crossings != 0:
        return False
    if interactions.edge_overlap_length > EPSILON:
        return False
    if _backwards_distance(candidate.points) > EPSILON:
        return False
    return _bend_count(candidate.points) == 1


def _route_metrics(
    candidate: CandidatePath,
    *,
    nodes: dict[str, LayoutNode],
    ignored_node_ids: set[str],
    theme: "Theme",
) -> tuple[int, float, int, float]:
    points = candidate.points
    return (
        _count_node_collisions(points, nodes, ignored_node_ids, theme),
        _backwards_distance(points),
        _bend_count(points),
        _path_length(points),
    )


def _candidate_interaction_metrics(
    candidate: CandidatePath,
    *,
    occupancy: Occupancy,
    source_node_id: str,
    target_node_id: str,
    routing_groups: RoutingGroups | None,
) -> InteractionMetrics:
    return _path_interaction_metrics(
        candidate.points,
        occupancy=occupancy,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        routing_groups=routing_groups,
    )


def _path_interaction_metrics(
    points: tuple[Point, ...],
    *,
    occupancy: Occupancy,
    source_node_id: str,
    target_node_id: str,
    routing_groups: RoutingGroups | None,
) -> InteractionMetrics:
    edge_crossings = 0
    edge_overlap_length = 0.0

    for start, end in zip(points, points[1:]):
        segment_crossings, segment_overlap = _segment_interaction_metrics(start, end, occupancy)
        edge_crossings += segment_crossings
        edge_overlap_length += segment_overlap

    obstacle_overlap_length = 0.0
    obstacle_crossings = 0
    for bounds in _obstacle_group_bounds(source_node_id, target_node_id, routing_groups):
        for start, end in zip(points, points[1:]):
            segment_overlap, segment_crossings = _segment_border_interactions(start, end, bounds)
            obstacle_overlap_length += segment_overlap
            obstacle_crossings += segment_crossings

    return InteractionMetrics(
        edge_crossings=edge_crossings,
        edge_overlap_length=round(edge_overlap_length, 2),
        obstacle_overlap_length=round(obstacle_overlap_length, 2),
        obstacle_crossings=obstacle_crossings,
    )


def _segment_interaction_metrics(
    start: Point,
    end: Point,
    occupancy: Occupancy,
) -> tuple[int, float]:
    crossings = 0
    overlap_length = 0.0

    if start.x == end.x:
        x = round(start.x, 2)
        top, bottom = sorted((start.y, end.y))
        for segment in occupancy.vertical.get(x, ()):
            overlap = min(bottom, segment.end) - max(top, segment.start)
            if overlap > EPSILON:
                overlap_length += overlap
        for y, horizontal_segments in occupancy.horizontal.items():
            if top + EPSILON < y < bottom - EPSILON:
                for segment in horizontal_segments:
                    if segment.start + EPSILON < x < segment.end - EPSILON:
                        crossings += 1
        return crossings, overlap_length

    if start.y == end.y:
        y = round(start.y, 2)
        left, right = sorted((start.x, end.x))
        for segment in occupancy.horizontal.get(y, ()):
            overlap = min(right, segment.end) - max(left, segment.start)
            if overlap > EPSILON:
                overlap_length += overlap
        for x, vertical_segments in occupancy.vertical.items():
            if left + EPSILON < x < right - EPSILON:
                for segment in vertical_segments:
                    if segment.start + EPSILON < y < segment.end - EPSILON:
                        crossings += 1
        return crossings, overlap_length

    return 1, 0.0


def _obstacle_group_bounds(
    source_node_id: str,
    target_node_id: str,
    routing_groups: RoutingGroups | None,
    *,
    self_loop: bool = False,
) -> tuple[Bounds, ...]:
    if routing_groups is None:
        return ()
    return _relevant_group_bounds(
        source_node_id,
        target_node_id,
        routing_groups,
        self_loop=self_loop,
    )


def _segment_border_interactions(
    start: Point,
    end: Point,
    bounds: Bounds,
) -> tuple[float, int]:
    overlap_length = 0.0
    crossings = 0

    if start.x == end.x:
        x = round(start.x, 2)
        top, bottom = sorted((start.y, end.y))
        if abs(x - bounds.x) <= EPSILON or abs(x - bounds.right) <= EPSILON:
            overlap = min(bottom, bounds.bottom) - max(top, bounds.y)
            if overlap > EPSILON:
                overlap_length += overlap
        if bounds.x + EPSILON < x < bounds.right - EPSILON and top + EPSILON < bounds.y < bottom - EPSILON:
            crossings += 1
        if bounds.x + EPSILON < x < bounds.right - EPSILON and top + EPSILON < bounds.bottom < bottom - EPSILON:
            crossings += 1
        return overlap_length, crossings

    if start.y == end.y:
        y = round(start.y, 2)
        left, right = sorted((start.x, end.x))
        if abs(y - bounds.y) <= EPSILON or abs(y - bounds.bottom) <= EPSILON:
            overlap = min(right, bounds.right) - max(left, bounds.x)
            if overlap > EPSILON:
                overlap_length += overlap
        if bounds.y + EPSILON < y < bounds.bottom - EPSILON and left + EPSILON < bounds.x < right - EPSILON:
            crossings += 1
        if bounds.y + EPSILON < y < bounds.bottom - EPSILON and left + EPSILON < bounds.right < right - EPSILON:
            crossings += 1
        return overlap_length, crossings

    return 0.0, 1


def _forward_kind_priority(
    kind: str,
    *,
    outgoing_count: int,
    incoming_count: int,
) -> int:
    fanout_context = outgoing_count > 1 and incoming_count <= 1
    fanin_context = incoming_count > 1 and outgoing_count <= 1

    if kind == "direct":
        return 0
    if kind == "shared_row":
        return 1
    if kind == "direct_elbow":
        return 2
    if fanout_context and kind == "column_source":
        return 3
    if fanout_context and kind == "row_source":
        return 4
    if fanin_context and kind == "column_target":
        return 3
    if fanin_context and kind == "row_target":
        return 4
    if kind in {"column_source", "column_target"}:
        return 5
    if kind in {"row_source", "row_target"}:
        return 6
    if kind == "outer_row":
        return 7
    if kind == "outer_column":
        return 8
    return 9


def _edge_join_kind_priority(kind: str, *, direction: str) -> int:
    if kind == "direct_join":
        return 0
    if kind in {"shared_row_join", "shared_column_join"}:
        return 1
    if kind == "shared_join":
        return 2
    if kind in {"row_join", "column_join"}:
        return 3
    if kind == "lane_join":
        return 4
    if kind in {"outer_row_join", "outer_column_join"}:
        return 5
    if kind == "outer_join":
        return 6
    # Keep residual ordering deterministic if new kinds are added later.
    return 7 if direction == "forward" else 8


def _candidate_conflicts(candidate: CandidatePath, occupancy: Occupancy) -> bool:
    reserved_segments = set(candidate.reserved_segments)
    for segment_index in range(len(candidate.points) - 1):
        start = candidate.points[segment_index]
        end = candidate.points[segment_index + 1]
        if _segment_conflicts(
            start,
            end,
            occupancy,
            check_overlap=segment_index in reserved_segments,
        ):
            return True
    return False


def _path_respects_group_clearance(
    points: tuple[Point, ...],
    source_node_id: str,
    target_node_id: str,
    routing_groups: RoutingGroups | None,
    *,
    include_shared: bool = False,
    self_loop: bool = False,
) -> bool:
    if routing_groups is None:
        return True

    relevant_bounds = _relevant_group_bounds(
        source_node_id,
        target_node_id,
        routing_groups,
        include_shared=include_shared,
        self_loop=self_loop,
    )
    if not relevant_bounds:
        return True

    for point in _bend_points(points):
        for bounds in relevant_bounds:
            if _point_within_bounds(point, bounds):
                return False
    return True


def _relevant_group_bounds_for_optional_routing_groups(
    source_node_id: str,
    target_node_id: str,
    routing_groups: RoutingGroups | None,
    *,
    include_shared: bool = False,
    self_loop: bool = False,
) -> tuple[Bounds, ...]:
    if routing_groups is None:
        return ()
    return _relevant_group_bounds(
        source_node_id,
        target_node_id,
        routing_groups,
        include_shared=include_shared,
        self_loop=self_loop,
    )


def _relevant_group_bounds(
    source_node_id: str,
    target_node_id: str,
    routing_groups: RoutingGroups,
    *,
    include_shared: bool = False,
    self_loop: bool = False,
) -> tuple[Bounds, ...]:
    source_groups = set(routing_groups.node_group_ids.get(source_node_id, ()))
    target_groups = set(routing_groups.node_group_ids.get(target_node_id, ()))
    if self_loop:
        relevant_group_ids = source_groups
    elif include_shared:
        relevant_group_ids = source_groups | target_groups
    else:
        relevant_group_ids = source_groups ^ target_groups
    return tuple(
        routing_groups.bounds_by_id[group_id]
        for group_id in sorted(relevant_group_ids)
        if group_id in routing_groups.bounds_by_id
    )


def _shared_group_frame(
    source_node_id: str,
    target_node_id: str,
    routing_groups: RoutingGroups | None,
) -> GroupRoutingFrame | None:
    if routing_groups is None:
        return None

    source_groups = set(routing_groups.node_group_ids.get(source_node_id, ()))
    target_groups = set(routing_groups.node_group_ids.get(target_node_id, ()))
    shared_group_ids = source_groups & target_groups

    candidates = [
        (group_id, routing_groups.frames_by_id[group_id])
        for group_id in shared_group_ids
        if group_id in routing_groups.frames_by_id
        and routing_groups.frames_by_id[group_id].header_top < routing_groups.frames_by_id[group_id].header_bottom - EPSILON
    ]
    if not candidates:
        return None

    _, frame = min(
        candidates,
        key=lambda item: (
            -routing_groups.depth_by_id.get(item[0], 0),
            item[1].bounds.width * item[1].bounds.height,
        ),
    )
    return frame


def _source_clearance_bounds(
    source_node_id: str,
    target_node_id: str,
    routing_groups: RoutingGroups | None,
    *,
    include_shared: bool = False,
    self_loop: bool = False,
) -> tuple[Bounds, ...]:
    if routing_groups is None:
        return ()
    source_groups = set(routing_groups.node_group_ids.get(source_node_id, ()))
    target_groups = set(routing_groups.node_group_ids.get(target_node_id, ()))
    if self_loop or include_shared:
        relevant_group_ids = source_groups
    else:
        relevant_group_ids = source_groups - target_groups
    return tuple(
        routing_groups.bounds_by_id[group_id]
        for group_id in sorted(relevant_group_ids)
        if group_id in routing_groups.bounds_by_id
    )


def _target_clearance_bounds(
    source_node_id: str,
    target_node_id: str,
    routing_groups: RoutingGroups | None,
    *,
    include_shared: bool = False,
) -> tuple[Bounds, ...]:
    if routing_groups is None:
        return ()
    source_groups = set(routing_groups.node_group_ids.get(source_node_id, ()))
    target_groups = set(routing_groups.node_group_ids.get(target_node_id, ()))
    relevant_group_ids = target_groups if include_shared else target_groups - source_groups
    return tuple(
        routing_groups.bounds_by_id[group_id]
        for group_id in sorted(relevant_group_ids)
        if group_id in routing_groups.bounds_by_id
    )


def _repair_forward_conflicts(
    *,
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
    routed_by_id: dict[str, RoutedEdge],
    ordered_node_edges: tuple["Edge", ...] | list["Edge"],
    component_geometry: dict[int, ComponentGeometry],
    pair_offsets: dict[str, float],
    routing_groups: RoutingGroups | None,
) -> None:
    for _ in range(2):
        changed = False

        for edge in ordered_node_edges:
            route = routed_by_id.get(edge.id)
            if route is None or route.target_kind != "node":
                continue

            source_node = nodes[edge.source]
            target_node = nodes[route.target_node_id]
            if source_node.rank >= target_node.rank:
                continue

            occupancy = Occupancy()
            for other_edge_id, other_route in routed_by_id.items():
                if other_edge_id == edge.id:
                    continue
                if nodes[other_route.edge.source].component_id != source_node.component_id:
                    continue
                _reserve_points(occupancy, other_route.points, other_edge_id)

            current_interactions = _path_interaction_metrics(
                route.points,
                occupancy=occupancy,
                source_node_id=source_node.node.id,
                target_node_id=target_node.node.id,
                routing_groups=routing_groups,
            )
            current_key = (
                current_interactions.edge_crossings,
                current_interactions.edge_overlap_length,
                _path_length(route.points),
            )
            if current_key[:2] == (0, 0.0):
                continue

            current_source_side = _point_side_on_node(route.points[0], source_node)
            current_target_side = _point_side_on_node(route.points[-1], target_node)
            geometry = component_geometry[source_node.component_id]
            candidate_evaluations: list[CandidateEvaluation] = []

            for kind, candidate in _same_side_forward_candidates(
                source_node=source_node,
                target_node=target_node,
                geometry=geometry,
                pair_offset=pair_offsets.get(edge.id, 0.0),
                current_source_side=current_source_side,
                current_target_side=current_target_side,
                routing_groups=routing_groups,
                theme=validated.theme,
            ):
                interactions = _candidate_interaction_metrics(
                    candidate,
                    occupancy=occupancy,
                    source_node_id=source_node.node.id,
                    target_node_id=target_node.node.id,
                    routing_groups=routing_groups,
                )
                candidate_evaluations.append(
                    _build_forward_candidate_evaluation(
                        kind=kind,
                        candidate=candidate,
                        candidate_index=len(candidate_evaluations),
                        source_node=source_node,
                        target_node=target_node,
                        nodes=nodes,
                        outgoing_count=0,
                        incoming_count=0,
                        theme=validated.theme,
                        interactions=interactions,
                        routing_groups=routing_groups,
                    )
                )

            replacement = _select_candidate_evaluation(candidate_evaluations)
            if replacement is None:
                continue

            replacement_key = (
                replacement.edge_crossings,
                replacement.edge_overlap_length,
                replacement.length,
            )
            if replacement_key >= current_key:
                continue

            route.points = replacement.candidate.points
            route.bounds = _bounds_for_points(
                replacement.candidate.points,
                validated.theme.stroke_width,
                validated.theme.arrow_size,
                badge_radius=route.join_badge_radius,
            )
            changed = True

        if not changed:
            break


def _same_side_forward_candidates(
    *,
    source_node: LayoutNode,
    target_node: LayoutNode,
    geometry: ComponentGeometry,
    pair_offset: float,
    current_source_side: str,
    current_target_side: str,
    routing_groups: RoutingGroups | None,
    theme: "Theme",
) -> tuple[tuple[str, CandidatePath], ...]:
    candidates: list[tuple[str, CandidatePath]] = []

    for kind, candidate in _build_forward_candidates(
        source_node=source_node,
        target_node=target_node,
        geometry=geometry,
        pair_offset=pair_offset,
        routing_groups=routing_groups,
        theme=theme,
    ):
        if _point_side_on_node(candidate.points[0], source_node) != current_source_side:
            continue
        if _point_side_on_node(candidate.points[-1], target_node) != current_target_side:
            continue
        candidates.append((kind, candidate))

    unique: dict[tuple[Point, ...], tuple[str, CandidatePath]] = {}
    for kind, candidate in candidates:
        unique.setdefault(candidate.points, (kind, candidate))
    return tuple(unique.values())


def _separate_overlapping_endpoints(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
    routed_by_id: dict[str, RoutedEdge],
) -> None:
    descriptors = _endpoint_access_descriptors(validated, nodes, routed_by_id)
    grouped: dict[tuple[str, str, str], list[EndpointAccessDescriptor]] = defaultdict(list)

    for descriptor in descriptors:
        grouped[(descriptor.node_id, descriptor.side, descriptor.endpoint_kind)].append(descriptor)

    translations = _endpoint_translations(routed_by_id)
    for cluster_descriptors in grouped.values():
        if not cluster_descriptors or cluster_descriptors[0].endpoint_kind != "target" or len(cluster_descriptors) <= 1:
            continue
        _apply_endpoint_cluster_spread(
            validated,
            nodes,
            routed_by_id,
            translations,
            tuple(cluster_descriptors),
        )
    _commit_endpoint_translations(validated, routed_by_id, translations)

    descriptors = _endpoint_access_descriptors(validated, nodes, routed_by_id)
    grouped = defaultdict(list)
    for descriptor in descriptors:
        grouped[(descriptor.node_id, descriptor.side, descriptor.endpoint_kind)].append(descriptor)

    translations = _endpoint_translations(routed_by_id)
    for cluster_descriptors in grouped.values():
        for component in _touching_endpoint_components(cluster_descriptors):
            if len(component) <= 1:
                continue
            _apply_endpoint_cluster_spread(
                validated,
                nodes,
                routed_by_id,
                translations,
                component,
            )
    _commit_endpoint_translations(validated, routed_by_id, translations)

    descriptors = _endpoint_access_descriptors(validated, nodes, routed_by_id)
    translations = _endpoint_translations(routed_by_id)
    for component in _overlapping_endpoint_components(list(descriptors)):
        if len(component) <= 1:
            continue
        _apply_endpoint_cluster_spread(
            validated,
            nodes,
            routed_by_id,
            translations,
            component,
        )
    _commit_endpoint_translations(validated, routed_by_id, translations)

    descriptors = _endpoint_access_descriptors(validated, nodes, routed_by_id)
    translations = _endpoint_translations(routed_by_id)
    for component in _crossing_endpoint_components(list(descriptors)):
        if len(component) <= 1:
            continue
        _apply_endpoint_cluster_spread(
            validated,
            nodes,
            routed_by_id,
            translations,
            component,
        )
    _commit_endpoint_translations(validated, routed_by_id, translations)


def _endpoint_translations(
    routed_by_id: dict[str, RoutedEdge],
) -> dict[str, list[tuple[float, float]]]:
    return {
        edge_id: [(0.0, 0.0) for _ in route.points]
        for edge_id, route in routed_by_id.items()
    }


def _commit_endpoint_translations(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    routed_by_id: dict[str, RoutedEdge],
    translations: dict[str, list[tuple[float, float]]],
) -> None:
    for edge_id, route in routed_by_id.items():
        translated_points = _translate_route_points(route.points, translations[edge_id])
        if translated_points == route.points:
            continue
        route.points = translated_points
        route.bounds = _bounds_for_points(
            translated_points,
            validated.theme.stroke_width,
            validated.theme.arrow_size,
            badge_radius=route.join_badge_radius,
        )


def _endpoint_access_descriptors(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
    routed_by_id: dict[str, RoutedEdge],
) -> tuple[EndpointAccessDescriptor, ...]:
    descriptors: list[EndpointAccessDescriptor] = []

    for edge in validated.edges:
        route = routed_by_id[edge.id]
        source_node = nodes[edge.source]
        source_side = _point_side_on_node(route.points[0], source_node)
        source_end_index = _source_access_lane_end_index(route.points)
        descriptors.append(
            EndpointAccessDescriptor(
                edge_id=edge.id,
                node_id=edge.source,
                endpoint_kind="source",
                side=source_side,
                axis=_side_tangent_axis(source_side),
                lane_start_index=0,
                lane_end_index=source_end_index,
                lane_start=route.points[0],
                lane_end=route.points[source_end_index],
                approach_point=None,
            )
        )

        if route.target_kind != "node":
            continue

        target_node = nodes[route.target_node_id]
        target_side = _point_side_on_node(route.points[-1], target_node)
        target_start_index = _target_access_lane_start_index(route.points)
        descriptors.append(
            EndpointAccessDescriptor(
                edge_id=edge.id,
                node_id=route.target_node_id,
                endpoint_kind="target",
                side=target_side,
                axis=_side_tangent_axis(target_side),
                lane_start_index=target_start_index,
                lane_end_index=len(route.points) - 1,
                lane_start=route.points[target_start_index],
                lane_end=route.points[-1],
                approach_point=route.points[target_start_index - 1] if target_start_index > 0 else None,
            )
        )

    return tuple(descriptors)


def _point_side_on_node(point: Point, node: LayoutNode) -> str:
    if abs(point.x - node.x) <= EPSILON:
        return "left"
    if abs(point.x - node.right) <= EPSILON:
        return "right"
    if abs(point.y - node.y) <= EPSILON:
        return "top"
    if abs(point.y - node.bounds.bottom) <= EPSILON:
        return "bottom"

    distances = {
        "left": abs(point.x - node.x),
        "right": abs(point.x - node.right),
        "top": abs(point.y - node.y),
        "bottom": abs(point.y - node.bounds.bottom),
    }
    return min(distances, key=distances.get)


def _side_tangent_axis(side: str) -> str:
    if side in {"left", "right"}:
        return "y"
    return "x"


def _source_access_lane_end_index(points: tuple[Point, ...]) -> int:
    if len(points) <= 1:
        return 0
    first_orientation = _segment_direction(points[0], points[1])
    if first_orientation is None:
        return 1

    end_index = 1
    for segment_index, (start, end) in enumerate(zip(points[1:], points[2:]), start=1):
        if _segment_direction(start, end) != first_orientation:
            break
        end_index = segment_index + 1
    return end_index


def _target_access_lane_start_index(points: tuple[Point, ...]) -> int:
    if len(points) <= 1:
        return 0
    last_orientation = _segment_direction(points[-2], points[-1])
    if last_orientation is None:
        return len(points) - 2

    start_index = len(points) - 2
    for segment_index in range(len(points) - 3, -1, -1):
        if _segment_direction(points[segment_index], points[segment_index + 1]) != last_orientation:
            break
        start_index = segment_index
    return start_index


def _overlapping_endpoint_components(
    descriptors: list[EndpointAccessDescriptor],
) -> tuple[tuple[EndpointAccessDescriptor, ...], ...]:
    return _endpoint_components(descriptors, _endpoint_lanes_overlap)


def _touching_endpoint_components(
    descriptors: list[EndpointAccessDescriptor],
) -> tuple[tuple[EndpointAccessDescriptor, ...], ...]:
    return _endpoint_components(descriptors, _endpoint_lanes_touch_or_overlap)


def _endpoint_components(
    descriptors: list[EndpointAccessDescriptor],
    related: "Callable[[EndpointAccessDescriptor, EndpointAccessDescriptor], bool]",
) -> tuple[tuple[EndpointAccessDescriptor, ...], ...]:
    if len(descriptors) <= 1:
        return ()

    adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {
        _endpoint_descriptor_key(descriptor): set()
        for descriptor in descriptors
    }
    descriptor_by_id = {
        _endpoint_descriptor_key(descriptor): descriptor
        for descriptor in descriptors
    }

    for index, first in enumerate(descriptors):
        for second in descriptors[index + 1 :]:
            if related(first, second):
                first_key = _endpoint_descriptor_key(first)
                second_key = _endpoint_descriptor_key(second)
                adjacency[first_key].add(second_key)
                adjacency[second_key].add(first_key)

    components: list[tuple[EndpointAccessDescriptor, ...]] = []
    seen: set[tuple[str, str]] = set()

    for descriptor in descriptors:
        descriptor_key = _endpoint_descriptor_key(descriptor)
        if descriptor_key in seen or not adjacency[descriptor_key]:
            continue
        queue = [descriptor_key]
        seen.add(descriptor_key)
        members: list[EndpointAccessDescriptor] = []
        while queue:
            current_key = queue.pop()
            members.append(descriptor_by_id[current_key])
            for neighbor in adjacency[current_key]:
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
        components.append(tuple(members))

    return tuple(components)


def _crossing_endpoint_components(
    descriptors: list[EndpointAccessDescriptor],
) -> tuple[tuple[EndpointAccessDescriptor, ...], ...]:
    if len(descriptors) <= 1:
        return ()

    adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {
        _endpoint_descriptor_key(descriptor): set()
        for descriptor in descriptors
    }
    descriptor_by_id = {
        _endpoint_descriptor_key(descriptor): descriptor
        for descriptor in descriptors
    }

    for index, first in enumerate(descriptors):
        for second in descriptors[index + 1 :]:
            if _endpoint_lanes_cross(first, second):
                first_key = _endpoint_descriptor_key(first)
                second_key = _endpoint_descriptor_key(second)
                adjacency[first_key].add(second_key)
                adjacency[second_key].add(first_key)

    components: list[tuple[EndpointAccessDescriptor, ...]] = []
    seen: set[tuple[str, str]] = set()

    for descriptor in descriptors:
        descriptor_key = _endpoint_descriptor_key(descriptor)
        if descriptor_key in seen or not adjacency[descriptor_key]:
            continue
        queue = [descriptor_key]
        seen.add(descriptor_key)
        members: list[EndpointAccessDescriptor] = []
        while queue:
            current_key = queue.pop()
            members.append(descriptor_by_id[current_key])
            for neighbor in adjacency[current_key]:
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
        components.append(tuple(members))

    return tuple(components)


def _endpoint_lanes_overlap(
    first: EndpointAccessDescriptor,
    second: EndpointAccessDescriptor,
) -> bool:
    return _endpoint_lanes_touch_or_overlap(first, second, strict=True)


def _endpoint_lanes_touch_or_overlap(
    first: EndpointAccessDescriptor,
    second: EndpointAccessDescriptor,
    *,
    strict: bool = False,
) -> bool:
    if first.axis != second.axis:
        return False
    if first.axis == "y":
        if abs(first.lane_start.y - second.lane_start.y) > EPSILON or abs(first.lane_end.y - second.lane_end.y) > EPSILON:
            return False
        first_left, first_right = sorted((first.lane_start.x, first.lane_end.x))
        second_left, second_right = sorted((second.lane_start.x, second.lane_end.x))
        overlap = min(first_right, second_right) - max(first_left, second_left)
        return overlap > EPSILON if strict else overlap >= -EPSILON

    if abs(first.lane_start.x - second.lane_start.x) > EPSILON or abs(first.lane_end.x - second.lane_end.x) > EPSILON:
        return False
    first_top, first_bottom = sorted((first.lane_start.y, first.lane_end.y))
    second_top, second_bottom = sorted((second.lane_start.y, second.lane_end.y))
    overlap = min(first_bottom, second_bottom) - max(first_top, second_top)
    return overlap > EPSILON if strict else overlap >= -EPSILON


def _endpoint_descriptor_key(descriptor: EndpointAccessDescriptor) -> tuple[str, str]:
    return descriptor.edge_id, descriptor.endpoint_kind


def _endpoint_lanes_cross(
    first: EndpointAccessDescriptor,
    second: EndpointAccessDescriptor,
) -> bool:
    first_direction = _segment_direction(first.lane_start, first.lane_end)
    second_direction = _segment_direction(second.lane_start, second.lane_end)
    if first_direction is None or second_direction is None or first_direction == second_direction:
        return False

    if first_direction == "h":
        horizontal = first
        vertical = second
    else:
        horizontal = second
        vertical = first

    y = horizontal.lane_start.y
    x = vertical.lane_start.x
    horizontal_left, horizontal_right = sorted((horizontal.lane_start.x, horizontal.lane_end.x))
    vertical_top, vertical_bottom = sorted((vertical.lane_start.y, vertical.lane_end.y))

    return (
        horizontal_left + EPSILON < x < horizontal_right - EPSILON
        and vertical_top + EPSILON < y < vertical_bottom - EPSILON
    )


def _apply_endpoint_cluster_spread(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
    routed_by_id: dict[str, RoutedEdge],
    translations: dict[str, list[tuple[float, float]]],
    descriptors: tuple[EndpointAccessDescriptor, ...],
) -> None:
    sample = descriptors[0]
    node = nodes[sample.node_id]
    side_span = node.height if sample.side in {"left", "right"} else node.width
    spread_gap = min(validated.theme.route_track_gap * 0.4, side_span / 4)
    ordered = sorted(
        descriptors,
        key=lambda descriptor: _endpoint_spread_order_key(validated, nodes, routed_by_id[descriptor.edge_id], descriptor),
    )

    target_coordinates: list[float] | None = None
    offsets: list[float] | None = None
    if sample.endpoint_kind == "target":
        target_coordinates = _target_cluster_slot_coordinates(
            ordered=ordered,
            node=node,
            nodes=nodes,
            routed_by_id=routed_by_id,
            gap=spread_gap if spread_gap > 0 else 0.0,
        )
    else:
        offsets = _centered_offsets(len(ordered), spread_gap if spread_gap > 0 else 0.0)

    for index, descriptor in enumerate(ordered):
        if target_coordinates is not None:
            delta = round(target_coordinates[index] - _descriptor_tangent_coordinate(descriptor), 2)
            shift = (0.0, delta) if descriptor.axis == "y" else (delta, 0.0)
        else:
            assert offsets is not None
            offset = offsets[index]
            shift = (0.0, offset) if descriptor.axis == "y" else (offset, 0.0)
        for point_index in range(descriptor.lane_start_index, descriptor.lane_end_index + 1):
            current_x, current_y = translations[descriptor.edge_id][point_index]
            translations[descriptor.edge_id][point_index] = (
                round(current_x + shift[0], 2),
                round(current_y + shift[1], 2),
            )


def _endpoint_spread_order_key(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
    route: RoutedEdge,
    descriptor: EndpointAccessDescriptor,
) -> tuple[float, int, int, int]:
    if descriptor.endpoint_kind == "source":
        peer_node = nodes[route.target_node_id]
        return (
            float(peer_node.order),
            peer_node.rank,
            0,
            validated.edge_index[descriptor.edge_id],
        )

    source_node = nodes[route.edge.source]
    return (
        _target_approach_depth_priority(descriptor),
        source_node.order,
        source_node.rank,
        validated.edge_index[descriptor.edge_id],
    )


def _target_approach_depth_priority(descriptor: EndpointAccessDescriptor) -> float:
    if descriptor.side == "top":
        return descriptor.lane_start.y
    if descriptor.side == "bottom":
        return -descriptor.lane_start.y
    if descriptor.side == "left":
        return descriptor.lane_start.x
    return -descriptor.lane_start.x


def _descriptor_tangent_coordinate(descriptor: EndpointAccessDescriptor) -> float:
    if descriptor.axis == "y":
        return descriptor.lane_end.y
    return descriptor.lane_end.x


def _target_cluster_slot_coordinates(
    *,
    ordered: list[EndpointAccessDescriptor],
    node: LayoutNode,
    nodes: dict[str, LayoutNode],
    routed_by_id: dict[str, RoutedEdge],
    gap: float,
) -> list[float]:
    side = ordered[0].side
    center = _node_side_center_coordinate(node, side)
    outward_sign = _target_cluster_outward_sign(
        descriptors=ordered,
        node=node,
        nodes=nodes,
        routed_by_id=routed_by_id,
    )
    offsets = _center_out_offsets(len(ordered), gap, outward_sign)
    return [_clamp_side_coordinate(node, side, round(center + offset, 2)) for offset in offsets]


def _node_side_center_coordinate(node: LayoutNode, side: str) -> float:
    if side in {"left", "right"}:
        return round(node.center_y, 2)
    return round(node.center_x, 2)


def _target_cluster_outward_sign(
    *,
    descriptors: list[EndpointAccessDescriptor],
    node: LayoutNode,
    nodes: dict[str, LayoutNode],
    routed_by_id: dict[str, RoutedEdge],
) -> float:
    side = descriptors[0].side
    deltas: list[float] = []

    for descriptor in descriptors:
        if descriptor.approach_point is None:
            continue
        if side in {"top", "bottom"}:
            delta = descriptor.lane_start.x - descriptor.approach_point.x
        else:
            delta = descriptor.lane_start.y - descriptor.approach_point.y
        if abs(delta) > EPSILON:
            deltas.append(delta)

    if deltas:
        average_delta = sum(deltas) / len(deltas)
        if average_delta > EPSILON:
            return -1.0
        if average_delta < -EPSILON:
            return 1.0

    if side in {"top", "bottom"}:
        average_source = sum(
            nodes[routed_by_id[descriptor.edge_id].edge.source].center_x
            for descriptor in descriptors
        ) / len(descriptors)
        return -1.0 if average_source <= node.center_x else 1.0

    average_source = sum(
        nodes[routed_by_id[descriptor.edge_id].edge.source].center_y
        for descriptor in descriptors
    ) / len(descriptors)
    return -1.0 if average_source <= node.center_y else 1.0


def _center_out_offsets(count: int, gap: float, outward_sign: float) -> list[float]:
    if count <= 0:
        return []

    direction = outward_sign if abs(outward_sign) > EPSILON else -1.0
    offsets = [0.0]
    step = 1
    while len(offsets) < count:
        offsets.append(round(direction * gap * step, 2))
        if len(offsets) >= count:
            break
        offsets.append(round(-direction * gap * step, 2))
        step += 1
    return offsets


def _clamp_side_coordinate(node: LayoutNode, side: str, coordinate: float) -> float:
    if side in {"top", "bottom"}:
        low, high = node.x, node.right
    else:
        low, high = node.y, node.bounds.bottom
    return round(min(max(coordinate, low), high), 2)


def _translate_route_points(
    points: tuple[Point, ...],
    translations: list[tuple[float, float]],
) -> tuple[Point, ...]:
    shifted = tuple(
        Point(round(point.x + dx, 2), round(point.y + dy, 2))
        for point, (dx, dy) in zip(points, translations, strict=True)
    )
    return _collapse_points(shifted)


def _bend_points(points: tuple[Point, ...]) -> tuple[Point, ...]:
    bends: list[Point] = []
    for previous, current, following in zip(points, points[1:], points[2:]):
        previous_direction = _segment_direction(previous, current)
        next_direction = _segment_direction(current, following)
        if previous_direction and next_direction and previous_direction != next_direction:
            bends.append(current)
    return tuple(bends)


def _segment_direction(start: Point, end: Point) -> str | None:
    if start.x == end.x and start.y != end.y:
        return "v"
    if start.y == end.y and start.x != end.x:
        return "h"
    return None


def _point_within_bounds(point: Point, bounds: Bounds) -> bool:
    return (
        bounds.x - EPSILON <= point.x <= bounds.right + EPSILON
        and bounds.y - EPSILON <= point.y <= bounds.bottom + EPSILON
    )


def _segment_conflicts(
    start: Point,
    end: Point,
    occupancy: Occupancy,
    *,
    check_overlap: bool,
) -> bool:
    if start.x == end.x:
        x = round(start.x, 2)
        top, bottom = sorted((start.y, end.y))
        for segment in occupancy.vertical.get(x, ()):
            if (
                check_overlap
                and segment.overlap_locked
                and min(bottom, segment.end) - max(top, segment.start) > EPSILON
            ):
                return True
        for y, horizontal_segments in occupancy.horizontal.items():
            if top + EPSILON < y < bottom - EPSILON:
                for segment in horizontal_segments:
                    if segment.start + EPSILON < x < segment.end - EPSILON:
                        return True
        return False

    if start.y == end.y:
        y = round(start.y, 2)
        left, right = sorted((start.x, end.x))
        for segment in occupancy.horizontal.get(y, ()):
            if (
                check_overlap
                and segment.overlap_locked
                and min(right, segment.end) - max(left, segment.start) > EPSILON
            ):
                return True
        for x, vertical_segments in occupancy.vertical.items():
            if left + EPSILON < x < right - EPSILON:
                for segment in vertical_segments:
                    if segment.start + EPSILON < y < segment.end - EPSILON:
                        return True
        return False

    return True


def _reserve_candidate(occupancy: Occupancy, candidate: CandidatePath, edge_id: str) -> None:
    _reserve_points(
        occupancy,
        candidate.points,
        edge_id,
        overlap_locked_segments=set(candidate.reserved_segments),
    )


def _reserve_points(
    occupancy: Occupancy,
    points: tuple[Point, ...],
    edge_id: str,
    *,
    overlap_locked_segments: set[int] | None = None,
) -> None:
    overlap_locked_segments = overlap_locked_segments or set(range(len(points) - 1))

    for segment_index, (start, end) in enumerate(zip(points, points[1:])):
        overlap_locked = segment_index in overlap_locked_segments
        if start.x == end.x:
            top, bottom = sorted((start.y, end.y))
            if bottom - top > EPSILON:
                occupancy.vertical[round(start.x, 2)].append(
                    StoredSegment(top, bottom, edge_id, overlap_locked)
                )
        elif start.y == end.y:
            left, right = sorted((start.x, end.x))
            if right - left > EPSILON:
                occupancy.horizontal[round(start.y, 2)].append(
                    StoredSegment(left, right, edge_id, overlap_locked)
                )


def _points_conflict(points: tuple[Point, ...], occupancy: Occupancy) -> bool:
    for start, end in zip(points, points[1:]):
        if _segment_conflicts(start, end, occupancy, check_overlap=True):
            return True
    return False


def _select_back_edge_route(
    *,
    source_node: LayoutNode,
    target_node: LayoutNode,
    geometry: ComponentGeometry,
    occupancy: Occupancy,
    base_slot: int,
    pair_offset: float,
    routing_groups: RoutingGroups | None,
    theme: "Theme",
) -> tuple[Point, ...]:
    evaluations: list[PointRouteEvaluation] = []
    shared_local = _shared_group_frame(source_node.node.id, target_node.node.id, routing_groups) is not None

    for slot in range(base_slot, base_slot + 8):
        points = _route_back_edge(
            source_node=source_node,
            target_node=target_node,
            geometry=geometry,
            slot=slot,
            pair_offset=pair_offset,
            routing_groups=routing_groups,
            theme=theme,
        )
        clearance_ok = _path_respects_group_clearance(
            points,
            source_node.node.id,
            target_node.node.id,
            routing_groups,
        )
        interactions = _path_interaction_metrics(
            points,
            occupancy=occupancy,
            source_node_id=source_node.node.id,
            target_node_id=target_node.node.id,
            routing_groups=routing_groups,
        )
        evaluations.append(
            PointRouteEvaluation(
                clearance_ok=clearance_ok,
                shared_local=shared_local,
                edge_crossings=interactions.edge_crossings,
                edge_overlap_length=interactions.edge_overlap_length,
                bends=_bend_count(points),
                length=_path_length(points),
                slot=slot,
                points=points,
            )
        )

    selected = _select_point_route_evaluation(evaluations)
    if selected is not None:
        return selected.points
    raise AssertionError("No back-edge route found.")


def _select_self_loop_route(
    *,
    source_node: LayoutNode,
    geometry: ComponentGeometry,
    occupancy: Occupancy,
    base_slot: int,
    pair_offset: float,
    routing_groups: RoutingGroups | None,
    theme: "Theme",
) -> tuple[Point, ...]:
    evaluations: list[PointRouteEvaluation] = []
    shared_local = _shared_group_frame(source_node.node.id, source_node.node.id, routing_groups) is not None

    for slot in range(base_slot, base_slot + 8):
        points = _route_self_loop(
            source_node,
            geometry,
            slot,
            pair_offset,
            routing_groups,
            theme,
        )
        clearance_ok = _path_respects_group_clearance(
            points,
            source_node.node.id,
            source_node.node.id,
            routing_groups,
            self_loop=True,
        )
        interactions = _path_interaction_metrics(
            points,
            occupancy=occupancy,
            source_node_id=source_node.node.id,
            target_node_id=source_node.node.id,
            routing_groups=routing_groups,
        )
        evaluations.append(
            PointRouteEvaluation(
                clearance_ok=clearance_ok,
                shared_local=shared_local,
                edge_crossings=interactions.edge_crossings,
                edge_overlap_length=interactions.edge_overlap_length,
                bends=_bend_count(points),
                length=_path_length(points),
                slot=slot,
                points=points,
            )
        )

    selected = _select_point_route_evaluation(evaluations)
    if selected is not None:
        return selected.points

    raise AssertionError("No self-loop route found.")


def _route_back_edge(
    *,
    source_node: LayoutNode,
    target_node: LayoutNode,
    geometry: ComponentGeometry,
    slot: int,
    pair_offset: float,
    routing_groups: RoutingGroups | None,
    theme: "Theme",
) -> tuple[Point, ...]:
    source = _right_port(source_node, pair_offset)
    target = _left_port(target_node, pair_offset)
    shared_frame = _shared_group_frame(
        source_node.node.id,
        target_node.node.id,
        routing_groups,
    )

    if shared_frame is not None:
        lane_y = _shared_group_back_edge_lane_y(shared_frame, slot, theme)
        exit_x = _shared_group_back_edge_exit_x(source_node, shared_frame, geometry, slot)
        entry_x = _shared_group_back_edge_entry_x(target_node, shared_frame, geometry, slot)
        return _collapse_points(
            (
                source,
                Point(exit_x, source.y),
                Point(exit_x, lane_y),
                Point(entry_x, lane_y),
                Point(entry_x, target.y),
                target,
            )
        )

    source_clearances = _source_clearance_bounds(
        source_node.node.id,
        target_node.node.id,
        routing_groups,
    )
    target_clearances = _target_clearance_bounds(
        source_node.node.id,
        target_node.node.id,
        routing_groups,
    )
    top_clearances = _relevant_group_bounds(
        source_node.node.id,
        target_node.node.id,
        routing_groups,
    )
    exit_floor = max((bounds.right + theme.route_track_gap for bounds in source_clearances), default=source_node.right)
    entry_ceiling = min((bounds.x - theme.route_track_gap for bounds in target_clearances), default=target_node.x)
    top_ceiling = min((bounds.y - theme.route_track_gap for bounds in top_clearances), default=geometry.outer_top)

    lane_y = round(min(geometry.outer_top, top_ceiling) - theme.back_edge_gap * slot, 2)
    exit_x = round(max(source_node.right + theme.route_track_gap * (slot + 1), exit_floor), 2)
    entry_x = round(min(target_node.x - theme.route_track_gap * (slot + 1), entry_ceiling), 2)
    return _collapse_points(
        (
            source,
            Point(exit_x, source.y),
            Point(exit_x, lane_y),
            Point(entry_x, lane_y),
            Point(entry_x, target.y),
            target,
        )
    )


def _shared_group_back_edge_lane_y(
    frame: GroupRoutingFrame,
    slot: int,
    theme: "Theme",
) -> float:
    band_height = frame.header_bottom - frame.header_top
    if band_height <= EPSILON:
        return round(frame.header_top, 2)

    center = frame.header_top + band_height * 0.5
    offset_step = band_height * 0.18
    margin = band_height * 0.2
    lower_bound = frame.header_top + margin
    upper_bound = frame.header_bottom - margin
    desired_lane = center - offset_step * slot
    return round(min(max(desired_lane, lower_bound), upper_bound), 2)


def _shared_group_back_edge_exit_x(
    source_node: LayoutNode,
    frame: GroupRoutingFrame,
    geometry: ComponentGeometry,
    slot: int,
) -> float:
    corridor_start = source_node.right
    corridor_end = frame.bounds.right
    if source_node.rank in geometry.gap_after_rank:
        gap_start, gap_end = geometry.gap_after_rank[source_node.rank]
        corridor_start = max(corridor_start, gap_start)
        corridor_end = min(corridor_end, gap_end)
    return _shared_group_stub_x(corridor_start, corridor_end, slot, from_end=False)


def _shared_group_back_edge_entry_x(
    target_node: LayoutNode,
    frame: GroupRoutingFrame,
    geometry: ComponentGeometry,
    slot: int,
) -> float:
    corridor_start = frame.bounds.x
    corridor_end = target_node.x
    if target_node.rank in geometry.gap_before_rank:
        gap_start, gap_end = geometry.gap_before_rank[target_node.rank]
        corridor_start = max(corridor_start, gap_start)
        corridor_end = min(corridor_end, gap_end)
    return _shared_group_stub_x(corridor_start, corridor_end, slot, from_end=True)


def _shared_group_stub_x(
    corridor_start: float,
    corridor_end: float,
    slot: int,
    *,
    from_end: bool,
) -> float:
    corridor = max(0.0, corridor_end - corridor_start)
    base_ratio = min(0.5 + slot * 0.08, 0.66)
    if from_end:
        return round(corridor_end - corridor * base_ratio, 2)
    return round(corridor_start + corridor * base_ratio, 2)


def _route_self_loop(
    node: LayoutNode,
    geometry: ComponentGeometry,
    slot: int,
    pair_offset: float,
    routing_groups: RoutingGroups | None,
    theme: "Theme",
) -> tuple[Point, ...]:
    source = _right_port(node, pair_offset)
    target = _left_port(node, pair_offset)
    loop_clearances = _source_clearance_bounds(
        node.node.id,
        node.node.id,
        routing_groups,
        self_loop=True,
    )
    loop_x = round(
        max(
            node.right + theme.route_track_gap * (slot + 1),
            max((bounds.right + theme.route_track_gap for bounds in loop_clearances), default=node.right),
        ),
        2,
    )
    lane_y = round(
        min(
            geometry.outer_top - theme.route_track_gap * slot,
            min((bounds.y - theme.route_track_gap for bounds in loop_clearances), default=geometry.outer_top),
        ),
        2,
    )
    left_x = round(
        min(
            geometry.outer_left - theme.route_track_gap * slot,
            min((bounds.x - theme.route_track_gap for bounds in loop_clearances), default=geometry.outer_left),
        ),
        2,
    )
    return _collapse_points(
        (
            source,
            Point(loop_x, source.y),
            Point(loop_x, lane_y),
            Point(left_x, lane_y),
            Point(left_x, target.y),
            target,
        )
    )


def _edge_direction_kind(source_node: LayoutNode, target_node: LayoutNode) -> str:
    if source_node.node.id == target_node.node.id:
        return "self"
    if source_node.rank < target_node.rank:
        return "forward"
    return "back"


def _segment_is_join_eligible(start: Point, end: Point, theme: "Theme") -> bool:
    if start.x == end.x:
        return abs(end.y - start.y) > max(theme.stroke_width * 2.0, 2.0)
    if start.y == end.y:
        return abs(end.x - start.x) > max(theme.stroke_width * 2.0, 2.0)
    return False


def _closest_join_point(source_reference: Point, start: Point, end: Point, theme: "Theme") -> Point:
    margin = _join_endpoint_margin(theme)
    if start.x == end.x:
        top, bottom = sorted((start.y, end.y))
        if bottom - top <= margin * 2 + EPSILON:
            return Point(start.x, round((top + bottom) / 2, 2))
        y = min(max(source_reference.y, top + margin), bottom - margin)
        return Point(start.x, round(y, 2))

    left, right = sorted((start.x, end.x))
    if right - left <= margin * 2 + EPSILON:
        return Point(round((left + right) / 2, 2), start.y)
    x = min(max(source_reference.x, left + margin), right - margin)
    return Point(round(x, 2), start.y)


def _segment_is_direction_compatible(
    source_node: LayoutNode,
    target_node: LayoutNode,
    start: Point,
    end: Point,
    direction: str,
    theme: "Theme",
) -> bool:
    min_x, max_x = sorted((start.x, end.x))
    if direction == "forward":
        return max_x >= source_node.right - EPSILON
    if direction == "self":
        return max_x >= source_node.x - theme.route_track_gap
    return min_x <= source_node.right + theme.route_track_gap * 2


def _distributed_join_positions(
    low: float,
    high: float,
    preferred_positions: list[float],
    spacing: float,
) -> list[float]:
    if not preferred_positions:
        return []
    if len(preferred_positions) == 1:
        return [round(min(max(preferred_positions[0], low), high), 2)]

    usable = max(0.0, high - low)
    effective_spacing = min(spacing, usable / max(1, len(preferred_positions) - 1))
    total_span = effective_spacing * (len(preferred_positions) - 1)
    center_low = low + total_span / 2
    center_high = high - total_span / 2
    preferred_center = sum(preferred_positions) / len(preferred_positions)

    if center_low > center_high:
        center = (low + high) / 2
    else:
        center = min(max(preferred_center, center_low), center_high)

    start = center - total_span / 2
    return [round(start + effective_spacing * index, 2) for index in range(len(preferred_positions))]


def _join_endpoint_margin(theme: "Theme") -> float:
    return max(theme.arrow_size * 2.0, theme.stroke_width * 4.0)


def _join_spacing(theme: "Theme") -> float:
    return max(theme.arrow_size * 1.5, theme.stroke_width * 6.0)


def _join_badge_radius(theme: "Theme") -> float:
    return round(max(theme.arrow_size * 0.9, theme.stroke_width * 3.0), 2)


def _merge_badge_spacing(theme: "Theme") -> float:
    return max(theme.arrow_size * 1.8, theme.stroke_width * 6.0)


def _path_location_at_distance(points: tuple[Point, ...], distance: float) -> PathPointLocation:
    if len(points) < 2:
        raise AssertionError("Path must include at least one segment.")

    total_length = _path_length(points)
    clamped_distance = min(max(distance, 0.0), total_length)
    travelled = 0.0
    last_location: PathPointLocation | None = None

    for segment_index, (start, end) in enumerate(zip(points, points[1:])):
        orientation = _segment_direction(start, end)
        if orientation is None:
            continue

        segment_length = abs(end.x - start.x) + abs(end.y - start.y)
        if segment_length <= EPSILON:
            continue

        next_travelled = travelled + segment_length
        if clamped_distance <= next_travelled + EPSILON:
            remaining = min(max(clamped_distance - travelled, 0.0), segment_length)
            if orientation == "v":
                direction = 1 if end.y >= start.y else -1
                point = Point(start.x, round(start.y + direction * remaining, 2))
            else:
                direction = 1 if end.x >= start.x else -1
                point = Point(round(start.x + direction * remaining, 2), start.y)
            return PathPointLocation(
                segment_index=segment_index,
                start=start,
                end=end,
                orientation=orientation,
                point=point,
            )

        travelled = next_travelled
        last_location = PathPointLocation(
            segment_index=segment_index,
            start=start,
            end=end,
            orientation=orientation,
            point=end,
        )

    if last_location is not None:
        return last_location
    raise AssertionError("No routable segment found for path distance lookup.")


def _centered_offsets(count: int, gap: float) -> list[float]:
    if count <= 1 or gap == 0:
        return [0.0] * count
    start = -gap * (count - 1) / 2
    return [round(start + gap * index, 2) for index in range(count)]


def _collapse_points(points: tuple[Point, ...]) -> tuple[Point, ...]:
    collapsed: list[Point] = []
    for point in points:
        if collapsed and point == collapsed[-1]:
            continue
        collapsed.append(point)
    return tuple(collapsed)


def _bend_count(points: tuple[Point, ...]) -> int:
    directions: list[str] = []
    for start, end in zip(points, points[1:]):
        if start.x == end.x and start.y != end.y:
            directions.append("v")
        elif start.y == end.y and start.x != end.x:
            directions.append("h")

    bends = 0
    for previous, current in zip(directions, directions[1:]):
        if previous != current:
            bends += 1
    return bends


def _path_length(points: tuple[Point, ...]) -> float:
    return sum(abs(start.x - end.x) + abs(start.y - end.y) for start, end in zip(points, points[1:]))


def _backwards_distance(points: tuple[Point, ...]) -> float:
    backwards = 0.0
    for start, end in zip(points, points[1:]):
        if end.x < start.x:
            backwards += start.x - end.x
    return backwards


def _count_node_collisions(
    points: tuple[Point, ...],
    nodes: dict[str, LayoutNode],
    ignored_node_ids: set[str],
    theme: "Theme",
) -> int:
    collisions = 0
    padding = max(theme.stroke_width * 2, 2.0)
    for start, end in zip(points, points[1:]):
        for node_id, node in nodes.items():
            if node_id in ignored_node_ids:
                continue
            if _segment_hits_bounds(start, end, node.bounds, padding):
                collisions += 1
    return collisions


def _segment_hits_bounds(start: Point, end: Point, bounds: Bounds, padding: float) -> bool:
    left = bounds.x - padding
    right = bounds.right + padding
    top = bounds.y - padding
    bottom = bounds.bottom + padding

    if start.x == end.x:
        x = start.x
        segment_top, segment_bottom = sorted((start.y, end.y))
        return left < x < right and segment_bottom > top and segment_top < bottom

    if start.y == end.y:
        y = start.y
        segment_left, segment_right = sorted((start.x, end.x))
        return top < y < bottom and segment_right > left and segment_left < right

    return False


def _bounds_for_points(
    points: tuple[Point, ...],
    stroke_width: float,
    arrow_size: float,
    *,
    badge_radius: float = 0.0,
) -> Bounds:
    padding = max(stroke_width, arrow_size, badge_radius)
    min_x = min(point.x for point in points) - padding
    min_y = min(point.y for point in points) - padding
    max_x = max(point.x for point in points) + padding
    max_y = max(point.y for point in points) + padding
    return Bounds(x=min_x, y=min_y, width=max_x - min_x, height=max_y - min_y)
