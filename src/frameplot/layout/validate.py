from __future__ import annotations

from frameplot.layout.types import GroupHierarchy, ResolvedEdgeTarget, ValidatedDetailPanel, ValidatedPipeline


def validate_pipeline(pipeline: "Pipeline") -> ValidatedPipeline:
    from frameplot.api import Pipeline

    if not isinstance(pipeline, Pipeline):
        raise TypeError("pipeline must be a Pipeline instance.")

    validated_graph = _validate_graph_parts(
        nodes=tuple(pipeline.nodes),
        edges=tuple(pipeline.edges),
        groups=tuple(pipeline.groups),
        owner_label="Pipeline",
    )

    detail_panel = None
    if pipeline.detail_panel is not None:
        if pipeline.detail_panel.focus_node_id not in validated_graph["node_lookup"]:
            raise ValueError(
                f"DetailPanel {pipeline.detail_panel.id} references missing focus node: "
                f"{pipeline.detail_panel.focus_node_id}"
            )
        validated_panel = _validate_graph_parts(
            nodes=tuple(pipeline.detail_panel.nodes),
            edges=tuple(pipeline.detail_panel.edges),
            groups=tuple(pipeline.detail_panel.groups),
            owner_label=f"DetailPanel {pipeline.detail_panel.id}",
        )
        detail_panel = ValidatedDetailPanel(
            panel=pipeline.detail_panel,
            nodes=validated_panel["nodes"],
            edges=validated_panel["edges"],
            groups=validated_panel["groups"],
            node_lookup=validated_panel["node_lookup"],
            edge_lookup=validated_panel["edge_lookup"],
            edge_targets=validated_panel["edge_targets"],
            node_index=validated_panel["node_index"],
            edge_index=validated_panel["edge_index"],
            group_hierarchy=validated_panel["group_hierarchy"],
            theme=pipeline.theme,
        )

    return ValidatedPipeline(
        nodes=validated_graph["nodes"],
        edges=validated_graph["edges"],
        groups=validated_graph["groups"],
        node_lookup=validated_graph["node_lookup"],
        edge_lookup=validated_graph["edge_lookup"],
        edge_targets=validated_graph["edge_targets"],
        node_index=validated_graph["node_index"],
        edge_index=validated_graph["edge_index"],
        group_hierarchy=validated_graph["group_hierarchy"],
        theme=pipeline.theme,
        detail_panel=detail_panel,
    )


def _validate_graph_parts(
    *,
    nodes: tuple["Node", ...],
    edges: tuple["Edge", ...],
    groups: tuple["Group", ...],
    owner_label: str,
) -> dict[str, object]:
    if not nodes:
        raise ValueError(f"{owner_label} must contain at least one node.")

    node_lookup: dict[str, object] = {}
    edge_lookup: dict[str, object] = {}
    edge_targets: dict[str, ResolvedEdgeTarget] = {}
    node_index: dict[str, int] = {}
    edge_index: dict[str, int] = {}
    group_lookup: dict[str, object] = {}
    group_index: dict[str, int] = {}

    for index, node in enumerate(nodes):
        if node.id in node_lookup:
            raise ValueError(f"Duplicate node id: {node.id}")
        node_lookup[node.id] = node
        node_index[node.id] = index

    for index, edge in enumerate(edges):
        if edge.id in node_lookup:
            raise ValueError(f"Duplicate id shared by node and edge: {edge.id}")
        if edge.id in edge_lookup:
            raise ValueError(f"Duplicate edge id: {edge.id}")
        edge_lookup[edge.id] = edge
        edge_index[edge.id] = index

    for index, group in enumerate(groups):
        if group.id in node_lookup or group.id in edge_lookup:
            raise ValueError(f"Duplicate id shared by group and node/edge: {group.id}")
        if group.id in group_lookup:
            raise ValueError(f"Duplicate group id: {group.id}")
        group_lookup[group.id] = group
        group_index[group.id] = index

    for edge in edges:
        if edge.source not in node_lookup:
            if edge.source in edge_lookup:
                raise ValueError(f"Edge {edge.id} references edge as source: {edge.source}")
            raise ValueError(f"Edge {edge.id} references missing source node: {edge.source}")

        target_node = node_lookup.get(edge.target)
        target_edge = edge_lookup.get(edge.target)

        if target_node is not None:
            if edge.merge_symbol is not None:
                raise ValueError(f"Edge {edge.id} sets merge_symbol but targets node {edge.target}")
            edge_targets[edge.id] = ResolvedEdgeTarget(kind="node", node_id=edge.target)
            continue

        if target_edge is None:
            raise ValueError(f"Edge {edge.id} references missing target node or edge: {edge.target}")
        if edge.target == edge.id:
            raise ValueError(f"Edge {edge.id} cannot target itself.")
        if target_edge.target in edge_lookup:
            raise ValueError(
                f"Edge {edge.id} targets edge {target_edge.id}, but edge-to-edge chains are not supported."
            )
        if target_edge.target not in node_lookup:
            raise ValueError(
                f"Edge {edge.id} targets edge {target_edge.id}, which references missing target node: "
                f"{target_edge.target}"
            )

        edge_targets[edge.id] = ResolvedEdgeTarget(
            kind="edge",
            node_id=target_edge.target,
            edge_id=target_edge.id,
        )

    for group in groups:
        missing_nodes = [node_id for node_id in group.node_ids if node_id not in node_lookup]
        missing_groups = [group_id for group_id in group.group_ids if group_id not in group_lookup]
        missing_edges = [edge_id for edge_id in group.edge_ids if edge_id not in edge_lookup]
        if missing_nodes:
            raise ValueError(
                f"Group {group.id} references missing node ids: {', '.join(sorted(missing_nodes))}"
            )
        if missing_groups:
            raise ValueError(
                f"Group {group.id} references missing group ids: {', '.join(sorted(missing_groups))}"
            )
        if missing_edges:
            raise ValueError(
                f"Group {group.id} references missing edge ids: {', '.join(sorted(missing_edges))}"
            )

    group_hierarchy = _build_group_hierarchy(
        groups=groups,
        group_lookup=group_lookup,
        group_index=group_index,
        node_index=node_index,
        owner_label=owner_label,
    )

    return {
        "nodes": nodes,
        "edges": edges,
        "groups": groups,
        "node_lookup": node_lookup,
        "edge_lookup": edge_lookup,
        "edge_targets": edge_targets,
        "node_index": node_index,
        "edge_index": edge_index,
        "group_hierarchy": group_hierarchy,
    }


def _build_group_hierarchy(
    *,
    groups: tuple["Group", ...],
    group_lookup: dict[str, "Group"],
    group_index: dict[str, int],
    node_index: dict[str, int],
    owner_label: str,
) -> GroupHierarchy:
    structural_group_ids = tuple(
        group.id for group in groups if group.node_ids or group.group_ids
    )
    edge_only_group_ids = tuple(
        group.id for group in groups if not group.node_ids and not group.group_ids
    )
    structural_group_set = set(structural_group_ids)
    group_parent_ids: dict[str, str] = {}
    group_child_group_lists = {
        group_id: list(group_lookup[group_id].group_ids) for group_id in structural_group_ids
    }

    for group in groups:
        if group.id not in structural_group_set:
            continue

        for child_group_id in group.group_ids:
            if child_group_id == group.id:
                raise ValueError(f"{owner_label} group {group.id} cannot contain itself.")
            if child_group_id not in structural_group_set:
                raise ValueError(
                    f"{owner_label} group {group.id} references non-structural child group {child_group_id}."
                )
            existing_parent = group_parent_ids.get(child_group_id)
            if existing_parent is not None:
                raise ValueError(
                    f"{owner_label} group {child_group_id} has multiple parents: "
                    f"{existing_parent} and {group.id}."
                )
            group_parent_ids[child_group_id] = group.id

    def build_descendant_nodes(
        child_groups_by_id: dict[str, list[str]],
    ) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
        visiting: set[str] = set()
        visited: set[str] = set()
        descendant_cache: dict[str, tuple[str, ...]] = {}
        child_node_ids: dict[str, tuple[str, ...]] = {}

        def descendant_nodes(group_id: str) -> tuple[str, ...]:
            cached = descendant_cache.get(group_id)
            if cached is not None:
                return cached
            if group_id in visiting:
                raise ValueError(f"{owner_label} group hierarchy contains a cycle at {group_id}.")

            visiting.add(group_id)
            child_union: set[str] = set()
            ordered_child_node_ids: list[str] = []

            for child_group_id in child_groups_by_id.get(group_id, ()):
                child_nodes = descendant_nodes(child_group_id)
                child_node_set = set(child_nodes)
                overlap = child_union & child_node_set
                if overlap:
                    shared = ", ".join(sorted(overlap, key=node_index.__getitem__))
                    raise ValueError(
                        f"{owner_label} child groups under {group_id} overlap on nodes: {shared}."
                    )
                child_union.update(child_node_set)
                ordered_child_node_ids.extend(child_nodes)

            direct_node_ids = tuple(
                node_id for node_id in group_lookup[group_id].node_ids if node_id not in child_union
            )
            child_node_ids[group_id] = direct_node_ids
            ordered_node_ids = list(direct_node_ids) + ordered_child_node_ids
            ordered = tuple(dict.fromkeys(sorted(ordered_node_ids, key=node_index.__getitem__)))
            descendant_cache[group_id] = ordered
            visiting.remove(group_id)
            visited.add(group_id)
            return ordered

        for structural_group_id in structural_group_ids:
            if structural_group_id in visited:
                continue
            descendant_nodes(structural_group_id)

        return descendant_cache, child_node_ids

    descendant_cache, group_child_node_ids = build_descendant_nodes(group_child_group_lists)
    effective_node_sets = {
        group_id: set(descendant_cache[group_id]) for group_id in structural_group_ids
    }

    for group_id in structural_group_ids:
        if group_id in group_parent_ids:
            continue
        effective_nodes = effective_node_sets[group_id]
        if not effective_nodes:
            continue
        candidates = [
            other_id
            for other_id in structural_group_ids
            if other_id != group_id and effective_nodes < effective_node_sets[other_id]
        ]
        if not candidates:
            continue

        min_size = min(len(effective_node_sets[candidate_id]) for candidate_id in candidates)
        closest_candidates = [
            candidate_id
            for candidate_id in candidates
            if len(effective_node_sets[candidate_id]) == min_size
        ]
        if len(closest_candidates) > 1:
            names = ", ".join(sorted(closest_candidates, key=group_index.__getitem__))
            raise ValueError(
                f"{owner_label} group {group_id} fits under multiple parent groups ({names}); "
                "use explicit group_ids to disambiguate nesting."
            )
        parent_id = closest_candidates[0]
        group_parent_ids[group_id] = parent_id
        if group_id not in group_child_group_lists[parent_id]:
            group_child_group_lists[parent_id].append(group_id)

    descendant_cache, group_child_node_ids = build_descendant_nodes(group_child_group_lists)
    group_child_group_ids = {
        group_id: tuple(
            sorted(child_group_ids, key=lambda child_group_id: group_index[child_group_id])
        )
        for group_id, child_group_ids in group_child_group_lists.items()
    }

    final_node_sets = {
        group_id: set(descendant_cache[group_id]) for group_id in structural_group_ids
    }
    for index, group_id in enumerate(structural_group_ids):
        group_nodes = final_node_sets[group_id]
        if not group_nodes:
            continue
        for other_group_id in structural_group_ids[index + 1 :]:
            other_nodes = final_node_sets[other_group_id]
            overlap = group_nodes & other_nodes
            if not overlap:
                continue
            if group_nodes < other_nodes or other_nodes < group_nodes:
                continue
            shared = ", ".join(sorted(overlap, key=node_index.__getitem__))
            raise ValueError(
                f"{owner_label} groups {group_id} and {other_group_id} partially overlap on nodes: {shared}."
            )

    node_parent_group_ids: dict[str, str] = {}
    for group_id in structural_group_ids:
        for node_id in group_child_node_ids.get(group_id, ()):
            existing_parent = node_parent_group_ids.get(node_id)
            if existing_parent is not None:
                raise ValueError(
                    f"{owner_label} node {node_id} is assigned to multiple groups: "
                    f"{existing_parent} and {group_id}."
                )
            node_parent_group_ids[node_id] = group_id

    top_level_group_ids = tuple(
        group_id for group_id in structural_group_ids if group_id not in group_parent_ids
    )
    grouped_node_ids = {
        node_id
        for group_id in structural_group_ids
        for node_id in descendant_cache.get(group_id, ())
    }
    top_level_node_ids = tuple(
        node_id for node_id in sorted(node_index, key=node_index.__getitem__) if node_id not in grouped_node_ids
    )
    group_depths = {
        group_id: _group_depth(group_id, group_parent_ids) for group_id in structural_group_ids
    }

    return GroupHierarchy(
        group_lookup={group.id: group for group in groups},
        group_index=dict(group_index),
        structural_group_ids=structural_group_ids,
        edge_only_group_ids=edge_only_group_ids,
        top_level_group_ids=top_level_group_ids,
        top_level_node_ids=top_level_node_ids,
        group_parent_ids=group_parent_ids,
        group_child_group_ids=group_child_group_ids,
        group_child_node_ids=group_child_node_ids,
        group_descendant_node_ids=descendant_cache,
        node_parent_group_ids=node_parent_group_ids,
        group_depths=group_depths,
    )


def _group_depth(group_id: str, group_parent_ids: dict[str, str]) -> int:
    depth = 0
    current = group_parent_ids.get(group_id)
    while current is not None:
        depth += 1
        current = group_parent_ids.get(current)
    return depth
