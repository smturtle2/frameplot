from __future__ import annotations

from collections import defaultdict, deque

from frameplot.layout.types import ValidatedDetailPanel, ValidatedPipeline


def order_nodes(
    validated: ValidatedPipeline | ValidatedDetailPanel,
    ranks: dict[str, int],
) -> dict[str, int]:
    nodes_by_rank: dict[int, list[str]] = defaultdict(list)
    for node in validated.nodes:
        nodes_by_rank[ranks[node.id]].append(node.id)

    for rank_nodes in nodes_by_rank.values():
        rank_nodes.sort(key=validated.node_index.__getitem__)

    order = {
        node_id: index
        for rank_nodes in nodes_by_rank.values()
        for index, node_id in enumerate(rank_nodes)
    }

    incoming, outgoing = _forward_neighbors(validated, ranks)
    ordered_ranks = sorted(nodes_by_rank)

    for _ in range(4):
        for rank in ordered_ranks[1:]:
            _resort_rank(nodes_by_rank[rank], incoming, order, validated)
            _refresh_order(nodes_by_rank[rank], order)
        for rank in reversed(ordered_ranks[:-1]):
            _resort_rank(nodes_by_rank[rank], outgoing, order, validated)
            _refresh_order(nodes_by_rank[rank], order)

    if getattr(validated, "detail_panel", None) is not None:
        _apply_detail_panel_bias(validated, nodes_by_rank, ranks, order)

    return order


def _forward_neighbors(
    validated: ValidatedPipeline | ValidatedDetailPanel,
    ranks: dict[str, int],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)

    for edge in validated.edges:
        if ranks[edge.source] < ranks[edge.target]:
            incoming[edge.target].append(edge.source)
            outgoing[edge.source].append(edge.target)

    return incoming, outgoing


def _resort_rank(
    rank_nodes: list[str],
    neighbors: dict[str, list[str]],
    order: dict[str, int],
    validated: ValidatedPipeline | ValidatedDetailPanel,
) -> None:
    rank_nodes.sort(
        key=lambda node_id: (
            _barycenter(neighbors.get(node_id, ()), order, validated.node_index[node_id]),
            validated.node_index[node_id],
            node_id,
        )
    )


def _barycenter(neighbors: list[str] | tuple[str, ...], order: dict[str, int], fallback: int) -> float:
    if not neighbors:
        return float(fallback)
    return sum(order[neighbor] for neighbor in neighbors) / len(neighbors)


def _refresh_order(rank_nodes: list[str], order: dict[str, int]) -> None:
    for index, node_id in enumerate(rank_nodes):
        order[node_id] = index


def _apply_detail_panel_bias(
    validated: ValidatedPipeline,
    nodes_by_rank: dict[int, list[str]],
    ranks: dict[str, int],
    order: dict[str, int],
) -> None:
    focus_node_id = validated.detail_panel.panel.focus_node_id
    focus_path_nodes = _detail_focus_path_nodes(validated, ranks, focus_node_id)
    if not focus_path_nodes:
        return

    component_nodes = _weak_component_nodes(validated, focus_node_id)
    component_ranks = sorted({ranks[node_id] for node_id in component_nodes})
    max_row = max(len(nodes_by_rank[rank]) for rank in component_ranks) - 1

    for rank in component_ranks:
        rank_nodes = nodes_by_rank[rank]
        rank_focus_nodes = [node_id for node_id in rank_nodes if node_id in focus_path_nodes]
        if not rank_focus_nodes:
            _refresh_order(rank_nodes, order)
            continue

        rank_other_nodes = [node_id for node_id in rank_nodes if node_id not in focus_path_nodes]
        start_row = max_row - len(rank_focus_nodes) + 1

        for index, node_id in enumerate(rank_other_nodes):
            order[node_id] = index
        for index, node_id in enumerate(rank_focus_nodes):
            order[node_id] = start_row + index


def _detail_focus_path_nodes(
    validated: ValidatedPipeline,
    ranks: dict[str, int],
    focus_node_id: str,
) -> set[str]:
    forward_outgoing: dict[str, list[str]] = defaultdict(list)
    forward_incoming: dict[str, list[str]] = defaultdict(list)

    for edge in validated.edges:
        if edge.dashed or ranks[edge.source] >= ranks[edge.target]:
            continue
        forward_outgoing[edge.source].append(edge.target)
        forward_incoming[edge.target].append(edge.source)

    ancestors = _reachable(focus_node_id, forward_incoming)
    descendants = _reachable(focus_node_id, forward_outgoing)
    focus_path = ancestors | descendants | {focus_node_id}

    if focus_path:
        return focus_path
    return {focus_node_id}


def _reachable(start: str, adjacency: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    queue = deque([start])

    while queue:
        node_id = queue.popleft()
        for neighbor in adjacency.get(node_id, ()):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append(neighbor)

    return seen


def _weak_component_nodes(validated: ValidatedPipeline, start_node_id: str) -> set[str]:
    adjacency: dict[str, set[str]] = {node.id: set() for node in validated.nodes}
    for edge in validated.edges:
        adjacency[edge.source].add(edge.target)
        adjacency[edge.target].add(edge.source)

    seen = {start_node_id}
    queue = deque([start_node_id])

    while queue:
        node_id = queue.popleft()
        for neighbor in sorted(adjacency[node_id], key=validated.node_index.__getitem__):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append(neighbor)

    return seen
