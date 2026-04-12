"""Public data models used to describe frameplot diagrams."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class Node:
    """Describe a rendered node in the main graph or a detail panel.

    `id` and `title` are required. Optional colors override the active theme for
    this node only, and `width` or `height` can pin the rendered box size.
    Surrounding whitespace is stripped from text fields.
    """

    id: str
    title: str
    subtitle: str | None = None
    fill: str | None = None
    stroke: str | None = None
    text_color: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    width: float | None = None
    height: float | None = None

    def __post_init__(self) -> None:
        self.id = self.id.strip()
        self.title = self.title.strip()
        if self.subtitle is not None:
            self.subtitle = self.subtitle.strip() or None
        if not self.id:
            raise ValueError("Node id must not be empty.")
        if not self.title:
            raise ValueError("Node title must not be empty.")
        if self.width is not None and self.width <= 0:
            raise ValueError("Node width must be positive.")
        if self.height is not None and self.height <= 0:
            raise ValueError("Node height must be positive.")


@dataclass(slots=True)
class Edge:
    """Connect two nodes with a directional edge.

    `source` must reference a node identifier in the same graph. `target` may
    reference either a node identifier or another edge identifier to create an
    edge-to-edge join. Set `dashed=True` to draw a secondary or conditional
    flow.
    """

    id: str
    source: str
    target: str
    color: str | None = None
    dashed: bool = False
    merge_symbol: Literal["+", "x"] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = self.id.strip()
        self.source = self.source.strip()
        self.target = self.target.strip()
        if self.merge_symbol is not None:
            self.merge_symbol = self.merge_symbol.strip() or None
        if not self.id:
            raise ValueError("Edge id must not be empty.")
        if not self.source or not self.target:
            raise ValueError("Edge source and target must not be empty.")
        if self.merge_symbol not in (None, "+", "x"):
            raise ValueError("Edge merge_symbol must be one of '+', 'x', or None.")


@dataclass(slots=True)
class Group:
    """Describe a structural container group or an edge-only highlight.

    Groups with `node_ids` or `group_ids` participate in layout as container
    blocks that can hold direct child nodes and direct child groups. `edge_ids`
    remain optional visual highlights and do not affect containment structure.
    Prefer explicit nesting via `group_ids`; strict-subset legacy node groups
    are still normalized into a tree for compatibility. At least one node,
    group, or edge reference is required.
    """

    id: str
    label: str
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...] = ()
    group_ids: tuple[str, ...] = ()
    stroke: str | None = None
    fill: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = self.id.strip()
        self.label = self.label.strip()
        self.node_ids = tuple(node_id.strip() for node_id in self.node_ids if node_id.strip())
        self.group_ids = tuple(group_id.strip() for group_id in self.group_ids if group_id.strip())
        self.edge_ids = tuple(edge_id.strip() for edge_id in self.edge_ids if edge_id.strip())
        if not self.id:
            raise ValueError("Group id must not be empty.")
        if not self.label:
            raise ValueError("Group label must not be empty.")
        if not self.node_ids and not self.group_ids and not self.edge_ids:
            raise ValueError("Group must reference at least one node, group, or edge.")


@dataclass(slots=True)
class DetailPanel:
    """Expand a focus node into a lower inset with its own mini-graph.

    Use a detail panel when a node's internal mechanics would otherwise add
    long-range or cross-level edges to the main graph. The focus node must
    exist in the main pipeline graph, and the panel must contain at least one
    node.
    """

    id: str
    focus_node_id: str
    label: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    groups: tuple[Group, ...] = ()
    stroke: str | None = None
    fill: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.id = self.id.strip()
        self.focus_node_id = self.focus_node_id.strip()
        self.label = self.label.strip()
        self.nodes = tuple(self.nodes)
        self.edges = tuple(self.edges)
        self.groups = tuple(self.groups)
        if not self.id:
            raise ValueError("DetailPanel id must not be empty.")
        if not self.focus_node_id:
            raise ValueError("DetailPanel focus_node_id must not be empty.")
        if not self.label:
            raise ValueError("DetailPanel label must not be empty.")
        if not self.nodes:
            raise ValueError("DetailPanel must contain at least one node.")
