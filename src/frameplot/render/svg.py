from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET

from frameplot.layout.types import (
    DetailPanelLayout,
    GraphLayout,
    GuideLine,
    LayoutNode,
    LayoutResult,
    Point,
    RoutedEdge,
)
from frameplot.theme import Theme

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def render_svg(layout: LayoutResult, theme: Theme) -> str:
    """Serialize a computed layout into an SVG document string."""

    root = ET.Element(
        ET.QName(SVG_NS, "svg"),
        attrib={
            "width": _fmt(layout.width),
            "height": _fmt(layout.height),
            "viewBox": f"0 0 {_fmt(layout.width)} {_fmt(layout.height)}",
            "fill": "none",
        },
    )

    defs = ET.SubElement(root, ET.QName(SVG_NS, "defs"))
    
    # Drop Shadow Filter
    filter_elem = ET.SubElement(defs, ET.QName(SVG_NS, "filter"), attrib={"id": "drop-shadow", "x": "-20%", "y": "-20%", "width": "140%", "height": "140%"})
    ET.SubElement(filter_elem, ET.QName(SVG_NS, "feGaussianBlur"), attrib={"in": "SourceAlpha", "stdDeviation": "2"})
    ET.SubElement(filter_elem, ET.QName(SVG_NS, "feOffset"), attrib={"dx": "0", "dy": "2", "result": "offsetblur"})
    ET.SubElement(filter_elem, ET.QName(SVG_NS, "feComponentTransfer")).append(
        ET.Element(ET.QName(SVG_NS, "feFuncA"), attrib={"type": "linear", "slope": "0.08"})
    )
    merge = ET.SubElement(filter_elem, ET.QName(SVG_NS, "feMerge"))
    ET.SubElement(merge, ET.QName(SVG_NS, "feMergeNode"))
    ET.SubElement(merge, ET.QName(SVG_NS, "feMergeNode"), attrib={"in": "SourceGraphic"})

    marker_ids = _build_markers(defs, _all_edges(layout), theme)

    ET.SubElement(
        root,
        ET.QName(SVG_NS, "rect"),
        attrib={
            "x": "0",
            "y": "0",
            "width": _fmt(layout.width),
            "height": _fmt(layout.height),
            "fill": theme.background_color,
        },
    )

    group_layer = ET.SubElement(root, ET.QName(SVG_NS, "g"), attrib={"id": "groups"})
    _render_groups(group_layer, layout.main, theme)

    if layout.detail_panel is not None:
        guide_layer = ET.SubElement(root, ET.QName(SVG_NS, "g"), attrib={"id": "detail-panel-guides"})
        _render_guide_lines(guide_layer, layout.detail_panel.guide_lines, theme)

        panel_layer = ET.SubElement(
            root,
            ET.QName(SVG_NS, "g"),
            attrib={"id": f"detail-panel-{layout.detail_panel.panel.id}"},
        )
        _render_detail_panel_container(panel_layer, layout.detail_panel, theme)
        _render_groups(panel_layer, layout.detail_panel.graph, theme)

    edge_layer = ET.SubElement(root, ET.QName(SVG_NS, "g"), attrib={"id": "edges"})
    _render_edges(edge_layer, layout.main.edges, marker_ids, theme)
    if layout.detail_panel is not None:
        _render_edges(edge_layer, layout.detail_panel.graph.edges, marker_ids, theme)

    node_layer = ET.SubElement(root, ET.QName(SVG_NS, "g"), attrib={"id": "nodes"})
    _render_nodes(node_layer, layout.main.nodes, theme)
    if layout.detail_panel is not None:
        _render_nodes(
            node_layer,
            layout.detail_panel.graph.nodes,
            theme,
            id_prefix=f"detail-panel-{layout.detail_panel.panel.id}-",
        )

    return ET.tostring(root, encoding="unicode")


def _all_edges(layout: LayoutResult) -> tuple[RoutedEdge, ...]:
    if layout.detail_panel is None:
        return layout.main.edges
    return layout.main.edges + layout.detail_panel.graph.edges


def _render_groups(parent: ET.Element, graph: GraphLayout, theme: Theme) -> None:
    for overlay in graph.groups:
        ET.SubElement(
            parent,
            ET.QName(SVG_NS, "rect"),
            attrib={
                "x": _fmt(overlay.bounds.x),
                "y": _fmt(overlay.bounds.y),
                "width": _fmt(overlay.bounds.width),
                "height": _fmt(overlay.bounds.height),
                "rx": _fmt(theme.group_corner_radius),
                "ry": _fmt(theme.group_corner_radius),
                "stroke": overlay.stroke,
                "stroke-width": _fmt(theme.group_stroke_width),
                "fill": overlay.fill,
                "fill-opacity": _fmt(theme.group_fill_opacity),
            },
        )
        # Subtle accent line at the top
        ET.SubElement(
            parent,
            ET.QName(SVG_NS, "line"),
            attrib={
                "x1": _fmt(overlay.bounds.x + 10),
                "y1": _fmt(overlay.bounds.y),
                "x2": _fmt(overlay.bounds.x + 60),
                "y2": _fmt(overlay.bounds.y),
                "stroke": overlay.stroke,
                "stroke-width": _fmt(theme.group_stroke_width * 2.5),
                "stroke-linecap": "round",
            },
        )
        ET.SubElement(
            parent,
            ET.QName(SVG_NS, "text"),
            attrib={
                "x": _fmt(overlay.bounds.x + theme.group_padding),
                "y": _fmt(overlay.bounds.y + theme.subtitle_font_size + 6),
                "fill": theme.group_label_color,
                "font-family": theme.title_font_family,
                "font-size": _fmt(theme.subtitle_font_size),
                "font-weight": str(theme.title_font_weight),
            },
        ).text = overlay.group.label


def _render_guide_lines(parent: ET.Element, guide_lines: tuple[GuideLine, ...], theme: Theme) -> None:
    for guide_line in guide_lines:
        ET.SubElement(
            parent,
            ET.QName(SVG_NS, "path"),
            attrib={
                "d": _path_data(guide_line.points),
                "stroke": guide_line.stroke,
                "stroke-width": _fmt(theme.detail_panel_guide_width),
                "stroke-linecap": "round",
                "stroke-linejoin": "round",
            },
        )


def _render_detail_panel_container(
    parent: ET.Element,
    detail_panel: DetailPanelLayout,
    theme: Theme,
) -> None:
    ET.SubElement(
        parent,
        ET.QName(SVG_NS, "rect"),
        attrib={
            "x": _fmt(detail_panel.bounds.x),
            "y": _fmt(detail_panel.bounds.y),
            "width": _fmt(detail_panel.bounds.width),
            "height": _fmt(detail_panel.bounds.height),
            "rx": _fmt(theme.detail_panel_corner_radius),
            "ry": _fmt(theme.detail_panel_corner_radius),
            "stroke": detail_panel.stroke,
            "stroke-width": _fmt(theme.detail_panel_stroke_width),
            "fill": detail_panel.fill,
            "fill-opacity": _fmt(theme.detail_panel_fill_opacity),
            "filter": "url(#drop-shadow)",
        },
    )
    ET.SubElement(
        parent,
        ET.QName(SVG_NS, "text"),
        attrib={
            "x": _fmt(detail_panel.bounds.x + theme.detail_panel_padding),
            "y": _fmt(detail_panel.bounds.y + theme.subtitle_font_size + 8),
            "fill": theme.detail_panel_title_color,
            "font-family": theme.title_font_family,
            "font-size": _fmt(theme.subtitle_font_size),
            "font-weight": str(theme.title_font_weight),
        },
    ).text = detail_panel.panel.label


def _render_edges(
    parent: ET.Element,
    edges: tuple[RoutedEdge, ...],
    marker_ids: dict[str, str],
    theme: Theme,
) -> None:
    for routed_edge in edges:
        attributes = {
            "d": _path_data(routed_edge.points),
            "stroke": routed_edge.stroke,
            "stroke-width": _fmt(theme.stroke_width),
            "stroke-linecap": "round",
            "stroke-linejoin": "round",
            "marker-end": f"url(#{marker_ids[routed_edge.stroke]})",
        }
        if routed_edge.edge.dashed:
            attributes["stroke-dasharray"] = "8 6"
        ET.SubElement(parent, ET.QName(SVG_NS, "path"), attrib=attributes)


def _render_nodes(
    parent: ET.Element,
    nodes: dict[str, LayoutNode],
    theme: Theme,
    *,
    id_prefix: str = "",
) -> None:
    for node_id in sorted(nodes, key=lambda item: (nodes[item].rank, nodes[item].order, item)):
        _render_node(parent, nodes[node_id], theme, element_id=f"{id_prefix}{node_id}")


def _render_node(
    parent: ET.Element,
    layout_node: LayoutNode,
    theme: Theme,
    *,
    element_id: str,
) -> None:
    node = layout_node.node
    node_group = ET.SubElement(parent, ET.QName(SVG_NS, "g"), attrib={"id": element_id})
    ET.SubElement(
        node_group,
        ET.QName(SVG_NS, "rect"),
        attrib={
            "x": _fmt(layout_node.x),
            "y": _fmt(layout_node.y),
            "width": _fmt(layout_node.width),
            "height": _fmt(layout_node.height),
            "rx": _fmt(theme.corner_radius),
            "ry": _fmt(theme.corner_radius),
            "fill": node.fill or theme.node_fill,
            "stroke": node.stroke or theme.node_stroke,
            "stroke-width": _fmt(theme.stroke_width),
            "filter": "url(#drop-shadow)",
        },
    )

    text_x = layout_node.x + theme.node_padding_x
    content_top = layout_node.y + (layout_node.height - layout_node.content_height) / 2
    current_top = content_top
    title_ascent = theme.title_font_size * 0.8
    subtitle_ascent = theme.subtitle_font_size * 0.8
    text_color = node.text_color or theme.node_text_color

    for line in layout_node.title_lines:
        current_top += layout_node.title_line_height
        ET.SubElement(
            node_group,
            ET.QName(SVG_NS, "text"),
            attrib={
                "x": _fmt(text_x),
                "y": _fmt(current_top - layout_node.title_line_height + title_ascent),
                "fill": text_color,
                "font-family": theme.title_font_family,
                "font-size": _fmt(theme.title_font_size),
                "font-weight": str(theme.title_font_weight),
            },
        ).text = line

    if layout_node.subtitle_lines:
        current_top += theme.inter_text_gap
        for line in layout_node.subtitle_lines:
            current_top += layout_node.subtitle_line_height
            ET.SubElement(
                node_group,
                ET.QName(SVG_NS, "text"),
                attrib={
                    "x": _fmt(text_x),
                    "y": _fmt(current_top - layout_node.subtitle_line_height + subtitle_ascent),
                    "fill": text_color,
                    "font-family": theme.title_font_family,
                    "font-size": _fmt(theme.subtitle_font_size),
                    "font-weight": str(theme.subtitle_font_weight),
                },
            ).text = line


def _build_markers(defs: ET.Element, edges: tuple[RoutedEdge, ...], theme: Theme) -> dict[str, str]:
    marker_ids: dict[str, str] = {}
    for color in sorted({routed_edge.stroke for routed_edge in edges}):
        marker_id = f"arrow-{hashlib.sha1(color.encode('utf-8')).hexdigest()[:10]}"
        marker_ids[color] = marker_id
        marker = ET.SubElement(
            defs,
            ET.QName(SVG_NS, "marker"),
            attrib={
                "id": marker_id,
                "markerWidth": _fmt(theme.arrow_size),
                "markerHeight": _fmt(theme.arrow_size),
                "refX": _fmt(theme.arrow_size),
                "refY": _fmt(theme.arrow_size / 2),
                "orient": "auto",
                "markerUnits": "userSpaceOnUse",
            },
        )
        ET.SubElement(
            marker,
            ET.QName(SVG_NS, "path"),
            attrib={
                "d": f"M0,0 L{_fmt(theme.arrow_size)},{_fmt(theme.arrow_size / 2)} L0,{_fmt(theme.arrow_size)} z",
                "fill": color,
            },
        )
    return marker_ids


def _path_data(points: tuple[Point, ...]) -> str:
    commands = [f"M {_fmt(points[0].x)} {_fmt(points[0].y)}"]
    commands.extend(f"L {_fmt(point.x)} {_fmt(point.y)}" for point in points[1:])
    return " ".join(commands)


def _fmt(value: float) -> str:
    text = f"{value:.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
