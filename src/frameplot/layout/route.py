from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from frameplot.layout.types import Bounds, GroupOverlay, LayoutNode, Point, RoutedEdge, union_bounds
from frameplot.theme import resolve_theme_metrics

EPSILON = 0.01


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
class GroupRoutingFrame:
    bounds: Bounds
    member_bounds: Bounds
    header_top: float
    header_bottom: float
    top_reserve: float


@dataclass(slots=True)
class RoutingGroups:
    frames_by_id: dict[str, GroupRoutingFrame]
    bounds_by_id: dict[str, Bounds]
    node_group_ids: dict[str, tuple[str, ...]]
    component_group_ids: dict[int, tuple[str, ...]]


def route_edges(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
) -> tuple[RoutedEdge, ...]:
    routing_groups = _build_routing_groups(validated, nodes)
    component_geometry = _build_component_geometry(nodes, validated.theme, routing_groups)
    forward_outgoing: dict[str, list["Edge"]] = defaultdict(list)
    forward_incoming: dict[str, list["Edge"]] = defaultdict(list)

    for edge in validated.edges:
        source_node = nodes[edge.source]
        target_node = nodes[edge.target]
        if edge.source != edge.target and source_node.rank < target_node.rank:
            forward_outgoing[edge.source].append(edge)
            forward_incoming[target_node.node.id].append(edge)

    pair_offsets = _assign_pair_offsets(validated, nodes)
    back_slots = _assign_back_slots(validated, nodes)
    self_loop_slots = _assign_self_loop_slots(validated)
    occupancies: dict[int, Occupancy] = defaultdict(Occupancy)
    routed_by_id: dict[str, RoutedEdge] = {}

    ordered_edges = sorted(
        validated.edges,
        key=lambda edge: _edge_route_order(edge, nodes, validated.edge_index[edge.id]),
    )

    for edge in ordered_edges:
        source_node = nodes[edge.source]
        target_node = nodes[edge.target]
        geometry = component_geometry[source_node.component_id]

        if edge.source == edge.target:
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
                incoming_count=len(forward_incoming[edge.target]),
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
        )

    return tuple(routed_by_id[edge.id] for edge in validated.edges)


def _build_routing_groups(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
) -> RoutingGroups:
    frames_by_id: dict[str, GroupRoutingFrame] = {}
    bounds_by_id: dict[str, Bounds] = {}
    node_group_ids: dict[str, list[str]] = defaultdict(list)
    component_group_ids: dict[int, set[str]] = defaultdict(set)

    for group in validated.groups:
        if not group.node_ids:
            continue

        member_bounds = union_bounds([nodes[node_id].bounds for node_id in group.node_ids])
        top_reserve = _group_internal_back_edge_top_reserve(group, validated, nodes)
        left_reserve, right_reserve = _group_internal_back_edge_side_reserves(
            group,
            validated,
            nodes,
            validated.theme,
            member_bounds,
        )
        bounds = _group_clearance_bounds_for_member_bounds(
            member_bounds,
            validated.theme,
            top_reserve=top_reserve,
            left_reserve=left_reserve,
            right_reserve=right_reserve,
        )
        header_top = round(bounds.y + _group_label_padding(validated.theme), 2)
        header_bottom = round(member_bounds.y, 2)

        frames_by_id[group.id] = GroupRoutingFrame(
            bounds=bounds,
            member_bounds=member_bounds,
            header_top=header_top,
            header_bottom=header_bottom,
            top_reserve=top_reserve,
        )
        bounds_by_id[group.id] = bounds
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
    )


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
        edge.source != edge.target
        and edge.source in group_node_ids
        and edge.target in group_node_ids
        and nodes[edge.source].rank >= nodes[edge.target].rank
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
        if (
            edge.source == edge.target
            or edge.source not in group_node_ids
            or edge.target not in group_node_ids
            or nodes[edge.source].rank < nodes[edge.target].rank
        ):
            continue

        source_node = nodes[edge.source]
        target_node = nodes[edge.target]
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
    overlays: list[GroupOverlay] = []

    for group in validated.groups:
        group_node_set = set(group.node_ids)
        group_bounds = [nodes[node_id].bounds for node_id in group.node_ids]
        group_bounds.extend(edge_lookup[edge_id].bounds for edge_id in group.edge_ids)

        member_bounds = union_bounds([nodes[node_id].bounds for node_id in group.node_ids])
        top_reserve = _group_internal_back_edge_top_reserve(group, validated, nodes)
        left_reserve, right_reserve = _group_internal_back_edge_side_reserves(
            group,
            validated,
            nodes,
            validated.theme,
            member_bounds,
        )

        bounds = _group_clearance_bounds_for_member_bounds(
            union_bounds(group_bounds),
            validated.theme,
            top_reserve=top_reserve,
            left_reserve=left_reserve,
            right_reserve=right_reserve,
        )
        overlays.append(
            GroupOverlay(
                group=group,
                bounds=bounds,
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
        max_offset = min(
            validated.theme.route_track_gap * 0.4,
            min(nodes[ordered[0].source].height, nodes[ordered[0].target].height) / 4,
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
        target_node = nodes[edge.target]
        if edge.source != edge.target and source_node.rank >= target_node.rank:
            by_component[source_node.component_id].append(edge)

    slots: dict[str, int] = {}
    for edges in by_component.values():
        ordered = sorted(
            edges,
            key=lambda edge: (
                nodes[edge.source].rank,
                nodes[edge.target].rank,
                nodes[edge.source].order,
                nodes[edge.target].order,
                edge.id,
            ),
        )
        for slot, edge in enumerate(ordered):
            slots[edge.id] = slot
    return slots


def _assign_self_loop_slots(validated: "ValidatedPipeline | ValidatedDetailPanel") -> dict[str, int]:
    by_node: dict[str, list["Edge"]] = defaultdict(list)
    for edge in validated.edges:
        if edge.source == edge.target:
            by_node[edge.source].append(edge)

    slots: dict[str, int] = {}
    for edges in by_node.values():
        for slot, edge in enumerate(sorted(edges, key=lambda edge: edge.id)):
            slots[edge.id] = slot
    return slots


def _edge_route_order(edge: "Edge", nodes: dict[str, LayoutNode], edge_index: int) -> tuple[int, int, int, int, int]:
    source_node = nodes[edge.source]
    target_node = nodes[edge.target]
    if edge.source == edge.target:
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
        theme=theme,
    )

    best: CandidatePath | None = None
    best_score: float | None = None
    fallback: CandidatePath | None = None
    fallback_score: float | None = None

    for kind, candidate in candidates:
        score = _forward_score(
            kind=kind,
            candidate=candidate,
            source_node=source_node,
            target_node=target_node,
            nodes=nodes,
            outgoing_count=outgoing_count,
            incoming_count=incoming_count,
            theme=theme,
        )

        if not _path_respects_group_clearance(
            candidate.points,
            source_node.node.id,
            target_node.node.id,
            routing_groups,
        ):
            continue

        if fallback_score is None or score < fallback_score:
            fallback = candidate
            fallback_score = score

        if _candidate_conflicts(candidate, occupancy):
            continue

        if best_score is None or score < best_score:
            best = candidate
            best_score = score

    if best is not None:
        return best
    assert fallback is not None
    return fallback


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


def _build_forward_candidates(
    *,
    source_node: LayoutNode,
    target_node: LayoutNode,
    geometry: ComponentGeometry,
    pair_offset: float,
    theme: "Theme",
) -> list[tuple[str, CandidatePath]]:
    candidates: list[tuple[str, CandidatePath]] = []

    if source_node.order == target_node.order:
        candidates.append(("direct", _direct_same_row_candidate(source_node, target_node, geometry, pair_offset, theme)))

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

    return candidates


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


def _forward_score(
    *,
    kind: str,
    candidate: CandidatePath,
    source_node: LayoutNode,
    target_node: LayoutNode,
    nodes: dict[str, LayoutNode],
    outgoing_count: int,
    incoming_count: int,
    theme: "Theme",
) -> float:
    points = candidate.points
    length = _path_length(points)
    bends = _bend_count(points)
    backwards = _backwards_distance(points)
    collisions = _count_node_collisions(points, nodes, {source_node.node.id, target_node.node.id}, theme)

    score = collisions * 100000 + backwards * 1000 + bends * 120 + length

    if kind.startswith("row_"):
        score += 50
    if kind == "outer_row":
        score += 280
    if kind == "outer_column":
        score += 340
    if kind == "direct":
        score -= 30
    if kind.endswith("source") and outgoing_count > 1:
        score -= 90
    if kind.endswith("target") and incoming_count > 1:
        score -= 90
    if kind.endswith("source") and incoming_count > 1:
        score += 25
    if kind.endswith("target") and outgoing_count > 1:
        score += 25

    return score


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
        routing_groups.frames_by_id[group_id]
        for group_id in shared_group_ids
        if group_id in routing_groups.frames_by_id
        and routing_groups.frames_by_id[group_id].header_top < routing_groups.frames_by_id[group_id].header_bottom - EPSILON
    ]
    if not candidates:
        return None

    return min(
        candidates,
        key=lambda frame: (
            frame.bounds.width * frame.bounds.height,
            frame.bounds.width,
            frame.bounds.height,
        ),
    )


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
    best_points: tuple[Point, ...] | None = None
    fallback_points: tuple[Point, ...] | None = None

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
        best_points = points
        if not _path_respects_group_clearance(
            points,
            source_node.node.id,
            target_node.node.id,
            routing_groups,
        ):
            continue
        if fallback_points is None:
            fallback_points = points
        if not _points_conflict(points, occupancy):
            return points

    if fallback_points is not None:
        return fallback_points
    raise AssertionError("No group-clear back-edge route found.")


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
    best_points: tuple[Point, ...] | None = None
    fallback_points: tuple[Point, ...] | None = None

    for slot in range(base_slot, base_slot + 8):
        points = _route_self_loop(
            source_node,
            geometry,
            slot,
            pair_offset,
            routing_groups,
            theme,
        )
        best_points = points
        if not _path_respects_group_clearance(
            points,
            source_node.node.id,
            source_node.node.id,
            routing_groups,
            self_loop=True,
        ):
            continue
        if fallback_points is None:
            fallback_points = points
        if not _points_conflict(points, occupancy):
            return points

    if fallback_points is not None:
        return fallback_points
    raise AssertionError("No group-clear self-loop route found.")


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


def _bounds_for_points(points: tuple[Point, ...], stroke_width: float, arrow_size: float) -> Bounds:
    padding = max(stroke_width, arrow_size)
    min_x = min(point.x for point in points) - padding
    min_y = min(point.y for point in points) - padding
    max_x = max(point.x for point in points) + padding
    max_y = max(point.y for point in points) + padding
    return Bounds(x=min_x, y=min_y, width=max_x - min_x, height=max_y - min_y)
