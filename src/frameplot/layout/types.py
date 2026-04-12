from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from frameplot.model import DetailPanel, Edge, Group, Node
from frameplot.theme import Theme


@dataclass(slots=True, frozen=True)
class Point:
    x: float
    y: float


@dataclass(slots=True, frozen=True)
class Bounds:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def expand(self, padding: float) -> "Bounds":
        return Bounds(
            x=self.x - padding,
            y=self.y - padding,
            width=self.width + padding * 2,
            height=self.height + padding * 2,
        )


def union_bounds(bounds: list[Bounds]) -> Bounds:
    min_x = min(bound.x for bound in bounds)
    min_y = min(bound.y for bound in bounds)
    max_x = max(bound.right for bound in bounds)
    max_y = max(bound.bottom for bound in bounds)
    return Bounds(x=min_x, y=min_y, width=max_x - min_x, height=max_y - min_y)


@dataclass(slots=True, frozen=True)
class ResolvedEdgeTarget:
    kind: Literal["node", "edge"]
    node_id: str
    edge_id: str | None = None


@dataclass(slots=True)
class GroupHierarchy:
    group_lookup: dict[str, Group]
    group_index: dict[str, int]
    structural_group_ids: tuple[str, ...]
    edge_only_group_ids: tuple[str, ...]
    top_level_group_ids: tuple[str, ...]
    top_level_node_ids: tuple[str, ...]
    group_parent_ids: dict[str, str]
    group_child_group_ids: dict[str, tuple[str, ...]]
    group_child_node_ids: dict[str, tuple[str, ...]]
    group_descendant_node_ids: dict[str, tuple[str, ...]]
    node_parent_group_ids: dict[str, str]
    group_depths: dict[str, int]


@dataclass(slots=True)
class ValidatedPipeline:
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    groups: tuple[Group, ...]
    node_lookup: dict[str, Node]
    edge_lookup: dict[str, Edge]
    edge_targets: dict[str, ResolvedEdgeTarget]
    node_index: dict[str, int]
    edge_index: dict[str, int]
    group_hierarchy: GroupHierarchy
    theme: Theme
    detail_panel: "ValidatedDetailPanel | None" = None


@dataclass(slots=True)
class ValidatedDetailPanel:
    panel: DetailPanel
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    groups: tuple[Group, ...]
    node_lookup: dict[str, Node]
    edge_lookup: dict[str, Edge]
    edge_targets: dict[str, ResolvedEdgeTarget]
    node_index: dict[str, int]
    edge_index: dict[str, int]
    group_hierarchy: GroupHierarchy
    theme: Theme


@dataclass(slots=True)
class MeasuredText:
    title_lines: tuple[str, ...]
    subtitle_lines: tuple[str, ...]
    title_line_height: float
    subtitle_line_height: float
    content_height: float
    width: float
    height: float


@dataclass(slots=True)
class LayoutNode:
    node: Node
    rank: int
    order: int
    component_id: int
    width: float
    height: float
    x: float
    y: float
    title_lines: tuple[str, ...]
    subtitle_lines: tuple[str, ...]
    title_line_height: float
    subtitle_line_height: float
    content_height: float

    @property
    def bounds(self) -> Bounds:
        return Bounds(self.x, self.y, self.width, self.height)

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2


@dataclass(slots=True)
class RoutedEdge:
    edge: Edge
    points: tuple[Point, ...]
    bounds: Bounds
    stroke: str
    target_kind: Literal["node", "edge"]
    target_node_id: str
    target_edge_id: str | None = None
    join_point: Point | None = None
    badge_center: Point | None = None
    join_segment_index: int | None = None
    show_arrowhead: bool = True
    join_badge_radius: float = 0.0


@dataclass(slots=True)
class GroupOverlay:
    group: Group
    bounds: Bounds
    stroke: str
    fill: str


@dataclass(slots=True)
class GuideLine:
    points: tuple[Point, ...]
    bounds: Bounds
    stroke: str


@dataclass(slots=True)
class GraphLayout:
    nodes: dict[str, LayoutNode]
    edges: tuple[RoutedEdge, ...]
    groups: tuple[GroupOverlay, ...]
    content_bounds: Bounds
    width: float
    height: float


@dataclass(slots=True)
class DetailPanelLayout:
    panel: DetailPanel
    graph: GraphLayout
    bounds: Bounds
    stroke: str
    fill: str
    guide_lines: tuple[GuideLine, ...]


@dataclass(slots=True)
class LayoutResult:
    main: GraphLayout
    detail_panel: DetailPanelLayout | None
    width: float
    height: float
