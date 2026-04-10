from __future__ import annotations

from dataclasses import dataclass

from frameplot.layout.types import ValidatedPipeline


@dataclass(slots=True)
class SccResult:
    components: tuple[tuple[str, ...], ...]
    node_to_component: dict[str, int]


def strongly_connected_components(validated: ValidatedPipeline) -> SccResult:
    adjacency: dict[str, list[str]] = {node.id: [] for node in validated.nodes}
    for edge in validated.edges:
        adjacency[edge.source].append(edge.target)

    for neighbors in adjacency.values():
        neighbors.sort(key=validated.node_index.__getitem__)

    index = 0
    stack: list[str] = []
    active: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node_id: str) -> None:
        nonlocal index
        indices[node_id] = index
        lowlinks[node_id] = index
        index += 1
        stack.append(node_id)
        active.add(node_id)

        for neighbor in adjacency[node_id]:
            if neighbor not in indices:
                visit(neighbor)
                lowlinks[node_id] = min(lowlinks[node_id], lowlinks[neighbor])
            elif neighbor in active:
                lowlinks[node_id] = min(lowlinks[node_id], indices[neighbor])

        if lowlinks[node_id] == indices[node_id]:
            component: list[str] = []
            while True:
                member = stack.pop()
                active.remove(member)
                component.append(member)
                if member == node_id:
                    break
            component.sort(key=validated.node_index.__getitem__)
            components.append(component)

    for node in validated.nodes:
        if node.id not in indices:
            visit(node.id)

    components.sort(key=lambda members: min(validated.node_index[node_id] for node_id in members))

    node_to_component: dict[str, int] = {}
    for component_id, component in enumerate(components):
        for node_id in component:
            node_to_component[node_id] = component_id

    return SccResult(
        components=tuple(tuple(component) for component in components),
        node_to_component=node_to_component,
    )
