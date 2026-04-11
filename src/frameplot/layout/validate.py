from __future__ import annotations

from frameplot.layout.types import ResolvedEdgeTarget, ValidatedDetailPanel, ValidatedPipeline


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
        missing_edges = [edge_id for edge_id in group.edge_ids if edge_id not in edge_lookup]
        if missing_nodes:
            raise ValueError(
                f"Group {group.id} references missing node ids: {', '.join(sorted(missing_nodes))}"
            )
        if missing_edges:
            raise ValueError(
                f"Group {group.id} references missing edge ids: {', '.join(sorted(missing_edges))}"
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
    }
