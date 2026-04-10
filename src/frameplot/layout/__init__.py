"""Internal layout pipeline used by the public frameplot API."""

from __future__ import annotations

from frameplot.layout.order import order_nodes
from frameplot.layout.place import place_nodes
from frameplot.layout.rank import assign_ranks
from frameplot.layout.route import compute_group_overlays, route_edges
from frameplot.layout.scc import strongly_connected_components
from frameplot.layout.text import measure_text
from frameplot.layout.types import (
    Bounds,
    DetailPanelLayout,
    GraphLayout,
    GroupOverlay,
    GuideLine,
    LayoutNode,
    LayoutResult,
    Point,
    RoutedEdge,
)
from frameplot.layout.validate import validate_pipeline

__all__ = ["build_layout"]


def build_layout(pipeline: "Pipeline") -> LayoutResult:
    """Compute positions, routes, and overlays for a pipeline."""

    validated = validate_pipeline(pipeline)
    theme = validated.theme
    main_graph = _layout_graph(validated)

    detail_panel = None
    width = main_graph.width
    height = main_graph.height

    if validated.detail_panel is not None:
        detail_panel = _build_detail_panel_layout(validated.detail_panel, main_graph, theme)
        width = max(width, detail_panel.bounds.right + theme.outer_margin)
        height = max(height, detail_panel.bounds.bottom + theme.outer_margin)
        for guide_line in detail_panel.guide_lines:
            width = max(width, guide_line.bounds.right + theme.outer_margin)
            height = max(height, guide_line.bounds.bottom + theme.outer_margin)

    return LayoutResult(
        main=main_graph,
        detail_panel=detail_panel,
        width=round(width, 2),
        height=round(height, 2),
    )


def _layout_graph(validated: "ValidatedPipeline | ValidatedDetailPanel") -> GraphLayout:
    measurements = measure_text(validated)
    scc_result = strongly_connected_components(validated)
    ranks = assign_ranks(validated, scc_result)
    order = order_nodes(validated, ranks)
    placed_nodes = place_nodes(validated, measurements, ranks, order)
    routed_edges = route_edges(validated, placed_nodes)
    overlays = compute_group_overlays(validated, placed_nodes, routed_edges)
    return _normalize_graph_layout(placed_nodes, routed_edges, overlays, validated.theme)


def _normalize_graph_layout(
    placed_nodes: dict[str, LayoutNode],
    routed_edges: tuple[RoutedEdge, ...],
    overlays: tuple[GroupOverlay, ...],
    theme: "Theme",
) -> GraphLayout:
    content_bounds = _collect_graph_bounds(placed_nodes, routed_edges, overlays)

    shift_x = max(0.0, theme.outer_margin - content_bounds.x)
    shift_y = max(0.0, theme.outer_margin - content_bounds.y)
    if shift_x or shift_y:
        placed_nodes = {node_id: _shift_node(node, shift_x, shift_y) for node_id, node in placed_nodes.items()}
        routed_edges = tuple(_shift_edge(route, shift_x, shift_y) for route in routed_edges)
        overlays = tuple(_shift_overlay(overlay, shift_x, shift_y) for overlay in overlays)
        content_bounds = _collect_graph_bounds(placed_nodes, routed_edges, overlays)

    return GraphLayout(
        nodes=placed_nodes,
        edges=routed_edges,
        groups=overlays,
        content_bounds=content_bounds,
        width=round(content_bounds.right + theme.outer_margin, 2),
        height=round(content_bounds.bottom + theme.outer_margin, 2),
    )


def _build_detail_panel_layout(
    validated_panel: "ValidatedDetailPanel",
    main_graph: GraphLayout,
    theme: "Theme",
) -> DetailPanelLayout:
    panel_graph = _layout_graph(validated_panel)
    focus_node = main_graph.nodes[validated_panel.panel.focus_node_id]

    content_width = panel_graph.content_bounds.width
    content_height = panel_graph.content_bounds.height
    label_width = len(validated_panel.panel.label) * theme.subtitle_font_size * 0.62

    panel_width = max(content_width + theme.detail_panel_padding * 2, label_width + theme.detail_panel_padding * 2)
    panel_height = (
        content_height + theme.detail_panel_header_height + theme.detail_panel_padding * 2
    )

    desired_x = focus_node.center_x - panel_width / 2
    max_x = max(theme.outer_margin, main_graph.width - theme.outer_margin - panel_width)
    panel_x = round(max(theme.outer_margin, min(desired_x, max_x)), 2)
    panel_y = round(main_graph.content_bounds.bottom + theme.detail_panel_gap, 2)

    content_x = panel_x + theme.detail_panel_padding
    content_y = panel_y + theme.detail_panel_header_height + theme.detail_panel_padding
    shifted_graph = _shift_graph_layout(
        panel_graph,
        shift_x=content_x - panel_graph.content_bounds.x,
        shift_y=content_y - panel_graph.content_bounds.y,
    )

    bounds = Bounds(
        x=panel_x,
        y=panel_y,
        width=round(panel_width, 2),
        height=round(panel_height, 2),
    )

    return DetailPanelLayout(
        panel=validated_panel.panel,
        graph=shifted_graph,
        bounds=bounds,
        stroke=validated_panel.panel.stroke or theme.detail_panel_stroke,
        fill=validated_panel.panel.fill or theme.detail_panel_fill,
        guide_lines=_build_detail_guides(focus_node, bounds, theme),
    )


def _build_detail_guides(
    focus_node: LayoutNode,
    panel_bounds: Bounds,
    theme: "Theme",
) -> tuple[GuideLine, ...]:
    start_left = Point(round(focus_node.x + focus_node.width * 0.2, 2), round(focus_node.bounds.bottom, 2))
    start_right = Point(
        round(focus_node.x + focus_node.width * 0.8, 2),
        round(focus_node.bounds.bottom, 2),
    )
    shoulder_inset = min(40.0, panel_bounds.width * 0.18)
    end_left = Point(
        round(panel_bounds.x + shoulder_inset, 2),
        round(panel_bounds.y, 2),
    )
    end_right = Point(
        round(panel_bounds.right - shoulder_inset, 2),
        round(panel_bounds.y, 2),
    )
    flare_x = max(theme.route_track_gap * 1.5, focus_node.width * 0.18)
    bend_y = round(
        start_left.y + max(18.0, min(theme.detail_panel_gap * 0.45, (panel_bounds.y - start_left.y) * 0.45)),
        2,
    )
    mid_left = Point(
        round(min(start_left.x - flare_x, (start_left.x + end_left.x) / 2), 2),
        bend_y,
    )
    mid_right = Point(
        round(max(start_right.x + flare_x, (start_right.x + end_right.x) / 2), 2),
        bend_y,
    )
    guides = (
        GuideLine(
            points=(start_left, mid_left, end_left),
            bounds=_line_bounds((start_left, mid_left, end_left), theme.detail_panel_guide_width),
            stroke=theme.detail_panel_guide_color,
        ),
        GuideLine(
            points=(start_right, mid_right, end_right),
            bounds=_line_bounds((start_right, mid_right, end_right), theme.detail_panel_guide_width),
            stroke=theme.detail_panel_guide_color,
        ),
    )
    return guides


def _collect_graph_bounds(
    nodes: dict[str, LayoutNode],
    edges: tuple[RoutedEdge, ...],
    overlays: tuple[GroupOverlay, ...],
) -> Bounds:
    bounds = [node.bounds for node in nodes.values()]
    bounds.extend(route.bounds for route in edges)
    bounds.extend(overlay.bounds for overlay in overlays)
    return Bounds(
        x=min(bound.x for bound in bounds),
        y=min(bound.y for bound in bounds),
        width=max(bound.right for bound in bounds) - min(bound.x for bound in bounds),
        height=max(bound.bottom for bound in bounds) - min(bound.y for bound in bounds),
    )


def _line_bounds(points: tuple[Point, ...], stroke_width: float) -> Bounds:
    padding = max(1.0, stroke_width)
    min_x = min(point.x for point in points) - padding
    min_y = min(point.y for point in points) - padding
    max_x = max(point.x for point in points) + padding
    max_y = max(point.y for point in points) + padding
    return Bounds(x=min_x, y=min_y, width=max_x - min_x, height=max_y - min_y)


def _shift_graph_layout(graph: GraphLayout, shift_x: float, shift_y: float) -> GraphLayout:
    shifted_nodes = {node_id: _shift_node(node, shift_x, shift_y) for node_id, node in graph.nodes.items()}
    shifted_edges = tuple(_shift_edge(route, shift_x, shift_y) for route in graph.edges)
    shifted_groups = tuple(_shift_overlay(overlay, shift_x, shift_y) for overlay in graph.groups)
    shifted_bounds = _collect_graph_bounds(shifted_nodes, shifted_edges, shifted_groups)
    return GraphLayout(
        nodes=shifted_nodes,
        edges=shifted_edges,
        groups=shifted_groups,
        content_bounds=shifted_bounds,
        width=round(max(graph.width + shift_x, shifted_bounds.right), 2),
        height=round(max(graph.height + shift_y, shifted_bounds.bottom), 2),
    )


def _shift_node(node: LayoutNode, shift_x: float, shift_y: float) -> LayoutNode:
    return LayoutNode(
        node=node.node,
        rank=node.rank,
        order=node.order,
        component_id=node.component_id,
        width=node.width,
        height=node.height,
        x=round(node.x + shift_x, 2),
        y=round(node.y + shift_y, 2),
        title_lines=node.title_lines,
        subtitle_lines=node.subtitle_lines,
        title_line_height=node.title_line_height,
        subtitle_line_height=node.subtitle_line_height,
        content_height=node.content_height,
    )


def _shift_edge(route: RoutedEdge, shift_x: float, shift_y: float) -> RoutedEdge:
    return RoutedEdge(
        edge=route.edge,
        points=tuple(Point(point.x + shift_x, point.y + shift_y) for point in route.points),
        bounds=Bounds(
            x=route.bounds.x + shift_x,
            y=route.bounds.y + shift_y,
            width=route.bounds.width,
            height=route.bounds.height,
        ),
        stroke=route.stroke,
    )


def _shift_overlay(overlay: GroupOverlay, shift_x: float, shift_y: float) -> GroupOverlay:
    return GroupOverlay(
        group=overlay.group,
        bounds=Bounds(
            x=overlay.bounds.x + shift_x,
            y=overlay.bounds.y + shift_y,
            width=overlay.bounds.width,
            height=overlay.bounds.height,
        ),
        stroke=overlay.stroke,
        fill=overlay.fill,
    )
