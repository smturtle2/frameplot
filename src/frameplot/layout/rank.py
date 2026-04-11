from __future__ import annotations

import heapq

from frameplot.layout.scc import SccResult
from frameplot.layout.types import ValidatedPipeline


def assign_ranks(validated: ValidatedPipeline, scc_result: SccResult) -> dict[str, int]:
    component_count = len(scc_result.components)
    component_widths = [max(1, len(component)) for component in scc_result.components]
    predecessors: dict[int, set[int]] = {component_id: set() for component_id in range(component_count)}
    successors: dict[int, set[int]] = {component_id: set() for component_id in range(component_count)}

    for edge in validated.edges:
        source_component = scc_result.node_to_component[edge.source]
        target_component = scc_result.node_to_component[validated.edge_targets[edge.id].node_id]
        if source_component == target_component:
            continue
        predecessors[target_component].add(source_component)
        successors[source_component].add(target_component)

    in_degree = {component_id: len(predecessors[component_id]) for component_id in predecessors}
    heap: list[tuple[int, int]] = []
    for component_id, degree in in_degree.items():
        if degree == 0:
            min_index = min(validated.node_index[node_id] for node_id in scc_result.components[component_id])
            heapq.heappush(heap, (min_index, component_id))

    topo_order: list[int] = []
    while heap:
        _, component_id = heapq.heappop(heap)
        topo_order.append(component_id)
        for successor in sorted(successors[component_id]):
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                min_index = min(
                    validated.node_index[node_id] for node_id in scc_result.components[successor]
                )
                heapq.heappush(heap, (min_index, successor))

    base_rank: dict[int, int] = {}
    for component_id in topo_order:
        base_rank[component_id] = max(
            (base_rank[pred] + component_widths[pred] for pred in predecessors[component_id]),
            default=0,
        )

    ranks: dict[str, int] = {}
    for component_id, component in enumerate(scc_result.components):
        for offset, node_id in enumerate(component):
            ranks[node_id] = base_rank[component_id] + offset

    return ranks
