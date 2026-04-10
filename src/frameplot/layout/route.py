from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from frameplot.layout.types import Bounds, GroupOverlay, LayoutNode, Point, RoutedEdge, union_bounds

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


def route_edges(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
) -> tuple[RoutedEdge, ...]:
    component_geometry = _build_component_geometry(nodes, validated.theme)
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


def compute_group_overlays(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    nodes: dict[str, LayoutNode],
    routed_edges: tuple[RoutedEdge, ...],
) -> tuple[GroupOverlay, ...]:
    edge_lookup = {route.edge.id: route for route in routed_edges}
    overlays: list[GroupOverlay] = []

    for group in validated.groups:
        group_bounds = [nodes[node_id].bounds for node_id in group.node_ids]
        group_bounds.extend(edge_lookup[edge_id].bounds for edge_id in group.edge_ids)
        bounds = union_bounds(group_bounds).expand(validated.theme.group_padding)
        label_padding = validated.theme.subtitle_font_size + validated.theme.node_padding_y
        bounds = Bounds(
            x=bounds.x,
            y=bounds.y - label_padding * 0.5,
            width=bounds.width,
            height=bounds.height + label_padding * 0.5,
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

        geometry_by_component[component_id] = ComponentGeometry(
            rank_left=rank_left,
            rank_right=rank_right,
            row_top=row_top,
            row_bottom=row_bottom,
            gap_after_rank=gap_after_rank,
            gap_before_rank=gap_before_rank,
            gap_after_row=gap_after_row,
            gap_before_row=gap_before_row,
            outer_top=round(min(row_top.values()) - theme.back_edge_gap, 2),
            outer_bottom=round(max(row_bottom.values()) + theme.back_edge_gap, 2),
            outer_right=round(max(rank_right.values()) + theme.back_edge_gap * 2, 2),
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
    start, end = geometry.gap_after_rank[rank]
    return round(min(end, start + min(theme.route_track_gap, (end - start) / 2)), 2)


def _stub_x_before_rank(rank: int, geometry: ComponentGeometry, theme: "Theme") -> float:
    if rank not in geometry.gap_before_rank:
        return round(geometry.rank_left[rank], 2)
    start, end = geometry.gap_before_rank[rank]
    return round(max(start, end - min(theme.route_track_gap, (end - start) / 2)), 2)


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
    theme: "Theme",
) -> tuple[Point, ...]:
    best_points: tuple[Point, ...] | None = None

    for slot in range(base_slot, base_slot + 8):
        points = _route_back_edge(
            source_node=source_node,
            target_node=target_node,
            geometry=geometry,
            slot=slot,
            pair_offset=pair_offset,
            theme=theme,
        )
        best_points = points
        if not _points_conflict(points, occupancy):
            return points

    assert best_points is not None
    return best_points


def _select_self_loop_route(
    *,
    source_node: LayoutNode,
    geometry: ComponentGeometry,
    occupancy: Occupancy,
    base_slot: int,
    pair_offset: float,
    theme: "Theme",
) -> tuple[Point, ...]:
    best_points: tuple[Point, ...] | None = None

    for slot in range(base_slot, base_slot + 8):
        points = _route_self_loop(
            source_node,
            geometry,
            slot,
            pair_offset,
            theme,
        )
        best_points = points
        if not _points_conflict(points, occupancy):
            return points

    assert best_points is not None
    return best_points


def _route_back_edge(
    *,
    source_node: LayoutNode,
    target_node: LayoutNode,
    geometry: ComponentGeometry,
    slot: int,
    pair_offset: float,
    theme: "Theme",
) -> tuple[Point, ...]:
    source = _right_port(source_node, pair_offset)
    target = _left_port(target_node, pair_offset)
    lane_y = round(geometry.outer_top - theme.back_edge_gap * slot, 2)
    exit_x = round(source_node.right + theme.route_track_gap * (slot + 1), 2)
    entry_x = round(target_node.x - theme.route_track_gap * (slot + 1), 2)
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


def _route_self_loop(
    node: LayoutNode,
    geometry: ComponentGeometry,
    slot: int,
    pair_offset: float,
    theme: "Theme",
) -> tuple[Point, ...]:
    source = _right_port(node, pair_offset)
    target = _left_port(node, pair_offset)
    loop_x = round(node.right + theme.route_track_gap * (slot + 1), 2)
    lane_y = round(geometry.outer_top - theme.route_track_gap * (slot + 1), 2)
    return _collapse_points(
        (
            source,
            Point(loop_x, source.y),
            Point(loop_x, lane_y),
            Point(node.x - theme.route_track_gap, lane_y),
            Point(node.x - theme.route_track_gap, target.y),
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
