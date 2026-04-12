from __future__ import annotations

from collections import defaultdict, deque

from frameplot.layout.types import LayoutNode, MeasuredText
from frameplot.theme import resolve_theme_metrics


def place_nodes(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    measurements: dict[str, MeasuredText],
    ranks: dict[str, int],
    order: dict[str, int],
    *,
    rank_gap_overrides: dict[tuple[int, int], float] | None = None,
    row_gap_overrides: dict[tuple[int, int], float] | None = None,
    row_gap_floor: float | None = None,
) -> dict[str, LayoutNode]:
    components = _weak_components(validated)
    placed: dict[str, LayoutNode] = {}
    current_top = validated.theme.outer_margin

    for component_id, component_nodes in enumerate(components):
        local_ranks = {node_id: ranks[node_id] for node_id in component_nodes}
        local_rows = {node_id: order[node_id] for node_id in component_nodes}
        min_rank = min(local_ranks.values())

        nodes_by_rank: dict[int, list[str]] = defaultdict(list)
        for node_id in component_nodes:
            nodes_by_rank[local_ranks[node_id] - min_rank].append(node_id)

        for rank_nodes in nodes_by_rank.values():
            rank_nodes.sort(key=lambda node_id: (local_rows[node_id], validated.node_index[node_id]))

        component_rows = sorted({local_rows[node_id] for node_id in component_nodes})
        ranks_in_component = sorted(nodes_by_rank)

        row_heights = {
            row: max(measurements[node_id].height for node_id in component_nodes if local_rows[node_id] == row)
            for row in component_rows
        }
        row_gap_after = _row_gap_after(
            validated,
            component_nodes,
            local_rows,
            component_id=component_id,
            overrides=row_gap_overrides,
            row_gap_floor=row_gap_floor,
        )
        column_widths = {
            rank: max(measurements[node_id].width for node_id in nodes)
            for rank, nodes in nodes_by_rank.items()
        }
        rank_gap_after = _rank_gap_after(
            validated,
            component_nodes,
            local_ranks,
            min_rank=min_rank,
            component_id=component_id,
            overrides=rank_gap_overrides,
        )

        row_tops: dict[int, float] = {}
        cursor_y = current_top
        for index, row in enumerate(component_rows):
            row_tops[row] = cursor_y
            cursor_y += row_heights[row]
            if index < len(component_rows) - 1:
                cursor_y += row_gap_after[row]
        component_height = cursor_y - current_top

        x_positions: dict[int, float] = {}
        cursor_x = validated.theme.outer_margin
        for rank in ranks_in_component:
            x_positions[rank] = cursor_x
            cursor_x += column_widths[rank]
            if rank != ranks_in_component[-1]:
                cursor_x += rank_gap_after[rank]

        for rank in ranks_in_component:
            for node_id in nodes_by_rank[rank]:
                node = validated.node_lookup[node_id]
                measured = measurements[node_id]
                row = local_rows[node_id]
                placed[node_id] = LayoutNode(
                    node=node,
                    rank=local_ranks[node_id],
                    order=row,
                    component_id=component_id,
                    width=round(column_widths[rank], 2),
                    height=round(row_heights[row], 2),
                    x=round(x_positions[rank], 2),
                    y=round(row_tops[row], 2),
                    title_lines=measured.title_lines,
                    subtitle_lines=measured.subtitle_lines,
                    title_line_height=measured.title_line_height,
                    subtitle_line_height=measured.subtitle_line_height,
                    content_height=measured.content_height,
                )

        current_top += component_height + validated.theme.component_gap

    return placed


def _weak_components(validated: "ValidatedPipeline | ValidatedDetailPanel") -> list[tuple[str, ...]]:
    adjacency: dict[str, set[str]] = {node.id: set() for node in validated.nodes}
    for edge in validated.edges:
        target_node_id = validated.edge_targets[edge.id].node_id
        adjacency[edge.source].add(target_node_id)
        adjacency[target_node_id].add(edge.source)

    components: list[tuple[str, ...]] = []
    seen: set[str] = set()

    for node in validated.nodes:
        if node.id in seen:
            continue
        queue = deque([node.id])
        seen.add(node.id)
        members: list[str] = []
        while queue:
            node_id = queue.popleft()
            members.append(node_id)
            for neighbor in sorted(adjacency[node_id], key=validated.node_index.__getitem__):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                queue.append(neighbor)
        members.sort(key=validated.node_index.__getitem__)
        components.append(tuple(members))

    return components


def _row_gap_after(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    component_nodes: tuple[str, ...],
    rows: dict[str, int],
    *,
    component_id: int,
    overrides: dict[tuple[int, int], float] | None,
    row_gap_floor: float | None,
) -> dict[int, float]:
    row_ids = sorted({rows[node_id] for node_id in component_nodes})
    base_gap = _base_row_gap(validated.theme) if row_gap_floor is None else row_gap_floor
    gap_after: dict[int, float] = {}
    for row in row_ids[:-1]:
        override_key = (component_id, row)
        gap_after[row] = round(
            max(base_gap, overrides.get(override_key, base_gap)) if overrides is not None else base_gap,
            2,
        )
    return gap_after


def _rank_gap_after(
    validated: "ValidatedPipeline | ValidatedDetailPanel",
    component_nodes: tuple[str, ...],
    ranks: dict[str, int],
    *,
    min_rank: int,
    component_id: int,
    overrides: dict[tuple[int, int], float] | None,
) -> dict[int, float]:
    normalized_ranks = {node_id: rank - min_rank for node_id, rank in ranks.items()}
    rank_ids = sorted({normalized_ranks[node_id] for node_id in component_nodes})

    gap_after: dict[int, float] = {}
    compact_gap = _base_rank_gap(validated.theme)
    for rank in rank_ids[:-1]:
        override_key = (component_id, rank + min_rank)
        gap_after[rank] = round(
            max(compact_gap, overrides.get(override_key, compact_gap)) if overrides is not None else compact_gap,
            2,
        )
    return gap_after


def _base_row_gap(theme: "Theme") -> float:
    return max(theme.route_track_gap * 1.5, theme.node_gap * 0.75)


def _base_rank_gap(theme: "Theme") -> float:
    return resolve_theme_metrics(theme).compact_rank_gap
