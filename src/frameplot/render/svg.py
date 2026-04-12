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
from frameplot.theme import ResolvedThemeMetrics, Theme, resolve_theme_metrics

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def render_svg(layout: LayoutResult, theme: Theme) -> str:
    """Serialize a computed layout into an SVG document string."""

    metrics = resolve_theme_metrics(theme)
    root = ET.Element(
        ET.QName(SVG_NS, "svg"),
        attrib={
            "width": _fmt(layout.width),
            "height": _fmt(layout.height),
            "viewBox": f"0 0 {_fmt(layout.width)} {_fmt(layout.height)}",
            "fill": "none",
            "font-family": theme.title_font_family,  # Basic default
        },
    )

    defs = ET.SubElement(root, ET.QName(SVG_NS, "defs"))

    _build_shadow_filter(defs, metrics)
    marker_ids = _build_markers(defs, _all_edges(layout), theme, metrics)

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
    _render_group_shapes(group_layer, layout.main, theme, metrics)

    if layout.detail_panel is not None:
        guide_layer = ET.SubElement(root, ET.QName(SVG_NS, "g"), attrib={"id": "detail-panel-guides"})
        _render_guide_lines(guide_layer, layout.detail_panel.guide_lines, theme)

        panel_layer = ET.SubElement(
            root,
            ET.QName(SVG_NS, "g"),
            attrib={"id": f"detail-panel-{layout.detail_panel.panel.id}"},
        )
        _render_detail_panel_container_shape(panel_layer, layout.detail_panel, theme, metrics)
        _render_group_shapes(panel_layer, layout.detail_panel.graph, theme, metrics)

    edge_layer = ET.SubElement(root, ET.QName(SVG_NS, "g"), attrib={"id": "edges"})
    _render_edges(edge_layer, layout.main.edges, marker_ids, theme, metrics)
    if layout.detail_panel is not None:
        _render_edges(edge_layer, layout.detail_panel.graph.edges, marker_ids, theme, metrics)

    join_layer = ET.SubElement(root, ET.QName(SVG_NS, "g"), attrib={"id": "edge-joins"})
    _render_join_badges(join_layer, layout.main.edges, theme)
    if layout.detail_panel is not None:
        _render_join_badges(join_layer, layout.detail_panel.graph.edges, theme)

    node_layer = ET.SubElement(root, ET.QName(SVG_NS, "g"), attrib={"id": "nodes"})
    _render_nodes(node_layer, layout.main.nodes, theme, metrics)
    if layout.detail_panel is not None:
        _render_nodes(
            node_layer,
            layout.detail_panel.graph.nodes,
            theme,
            metrics,
            id_prefix=f"detail-panel-{layout.detail_panel.panel.id}-",
        )

    label_layer = ET.SubElement(root, ET.QName(SVG_NS, "g"), attrib={"id": "labels"})
    _render_group_labels(label_layer, layout.main, theme, metrics)
    if layout.detail_panel is not None:
        _render_detail_panel_title(label_layer, layout.detail_panel, theme, metrics)
        _render_group_labels(label_layer, layout.detail_panel.graph, theme, metrics)

    return ET.tostring(root, encoding="unicode")


def _all_edges(layout: LayoutResult) -> tuple[RoutedEdge, ...]:
    if layout.detail_panel is None:
        return layout.main.edges
    return layout.main.edges + layout.detail_panel.graph.edges


def _build_shadow_filter(defs: ET.Element, metrics: ResolvedThemeMetrics) -> None:
    filter_margin = _fmt(metrics.shadow_filter_margin_percent)
    filter_elem = ET.SubElement(
        defs,
        ET.QName(SVG_NS, "filter"),
        attrib={
            "id": "drop-shadow",
            "x": f"-{filter_margin}%",
            "y": f"-{filter_margin}%",
            "width": f"{_fmt(100.0 + metrics.shadow_filter_margin_percent * 2)}%",
            "height": f"{_fmt(100.0 + metrics.shadow_filter_margin_percent * 2)}%",
        },
    )

    merge = ET.SubElement(filter_elem, ET.QName(SVG_NS, "feMerge"))
    for index, layer in enumerate(metrics.filter_shadow_layers, start=1):
        blur_result = f"blur{index}"
        shadow_result = f"shadow{index}"
        ET.SubElement(
            filter_elem,
            ET.QName(SVG_NS, "feGaussianBlur"),
            attrib={"in": "SourceAlpha", "stdDeviation": _fmt(layer.blur), "result": blur_result},
        )
        ET.SubElement(
            filter_elem,
            ET.QName(SVG_NS, "feOffset"),
            attrib={
                "dx": "0",
                "dy": _fmt(layer.offset_y),
                "in": blur_result,
                "result": f"offset{blur_result}",
            },
        )
        ET.SubElement(
            filter_elem,
            ET.QName(SVG_NS, "feComponentTransfer"),
            attrib={"in": f"offset{blur_result}", "result": shadow_result},
        ).append(
            ET.Element(
                ET.QName(SVG_NS, "feFuncA"),
                attrib={"type": "linear", "slope": _fmt(layer.opacity)},
            )
        )
        ET.SubElement(merge, ET.QName(SVG_NS, "feMergeNode"), attrib={"in": shadow_result})
    ET.SubElement(merge, ET.QName(SVG_NS, "feMergeNode"), attrib={"in": "SourceGraphic"})


def _render_group_shapes(
    parent: ET.Element,
    graph: GraphLayout,
    theme: Theme,
    metrics: ResolvedThemeMetrics,
) -> None:
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
                "stroke-dasharray": _dasharray(metrics.group_dasharray),
                "fill": overlay.fill,
                "fill-opacity": _fmt(theme.group_fill_opacity),
            },
        )
        if theme.show_group_accent_line:
            ET.SubElement(
                parent,
                ET.QName(SVG_NS, "line"),
                attrib={
                    "x1": _fmt(overlay.bounds.x + metrics.accent_line_inset_start),
                    "y1": _fmt(overlay.bounds.y),
                    "x2": _fmt(overlay.bounds.x + metrics.accent_line_inset_start + metrics.accent_line_length),
                    "y2": _fmt(overlay.bounds.y),
                    "stroke": overlay.stroke,
                    "stroke-width": _fmt(metrics.accent_line_width),
                    "stroke-linecap": "round",
                },
            )


def _render_group_labels(
    parent: ET.Element,
    graph: GraphLayout,
    theme: Theme,
    metrics: ResolvedThemeMetrics,
) -> None:
    for overlay in graph.groups:
        _render_label_text(
            parent,
            text=overlay.group.label,
            x=overlay.bounds.x + theme.group_padding,
            baseline_y=overlay.bounds.y + metrics.group_label_baseline_offset,
            font_family=theme.title_font_family,
            font_size=theme.subtitle_font_size,
            font_weight=theme.title_font_weight,
            text_color=theme.group_label_color,
            underpaint_color=theme.background_color,
            underpaint_opacity=1.0,
            underpaint_width=max(theme.stroke_width * 3.0, theme.subtitle_font_size * 0.24),
        )


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


def _render_detail_panel_container_shape(
    parent: ET.Element,
    detail_panel: DetailPanelLayout,
    theme: Theme,
    metrics: ResolvedThemeMetrics,
) -> None:
    _render_shadow_layers(
        parent,
        x=detail_panel.bounds.x,
        y=detail_panel.bounds.y,
        width=detail_panel.bounds.width,
        height=detail_panel.bounds.height,
        rx=theme.detail_panel_corner_radius,
        ry=theme.detail_panel_corner_radius,
        metrics=metrics,
    )

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
        },
    )


def _render_detail_panel_title(
    parent: ET.Element,
    detail_panel: DetailPanelLayout,
    theme: Theme,
    metrics: ResolvedThemeMetrics,
) -> None:
    _render_label_text(
        parent,
        text=detail_panel.panel.label,
        x=detail_panel.bounds.x + theme.detail_panel_padding,
        baseline_y=detail_panel.bounds.y + metrics.detail_panel_title_baseline_offset,
        font_family=theme.title_font_family,
        font_size=theme.subtitle_font_size,
        font_weight=theme.title_font_weight,
        text_color=theme.detail_panel_title_color,
        underpaint_color=detail_panel.fill,
        underpaint_opacity=1.0,
        underpaint_width=max(theme.stroke_width * 3.0, theme.subtitle_font_size * 0.26),
    )


def _render_label_text(
    parent: ET.Element,
    *,
    text: str,
    x: float,
    baseline_y: float,
    font_family: str,
    font_size: float,
    font_weight: int,
    text_color: str,
    underpaint_color: str,
    underpaint_opacity: float,
    underpaint_width: float,
) -> None:
    ET.SubElement(
        parent,
        ET.QName(SVG_NS, "text"),
        attrib={
            "x": _fmt(x),
            "y": _fmt(baseline_y),
            "fill": underpaint_color,
            "fill-opacity": _fmt(underpaint_opacity),
            "stroke": underpaint_color,
            "stroke-opacity": _fmt(underpaint_opacity),
            "stroke-width": _fmt(underpaint_width),
            "stroke-linejoin": "round",
            "font-family": font_family,
            "font-size": _fmt(font_size),
            "font-weight": str(font_weight),
        },
    ).text = text

    ET.SubElement(
        parent,
        ET.QName(SVG_NS, "text"),
        attrib={
            "x": _fmt(x),
            "y": _fmt(baseline_y),
            "fill": text_color,
            "font-family": font_family,
            "font-size": _fmt(font_size),
            "font-weight": str(font_weight),
        },
    ).text = text


def _render_edges(
    parent: ET.Element,
    edges: tuple[RoutedEdge, ...],
    marker_ids: dict[str, str],
    theme: Theme,
    metrics: ResolvedThemeMetrics,
) -> None:
    for routed_edge in edges:
        path_points = _render_points_for_edge(routed_edge)
        attributes = {
            "d": _path_data(path_points),
            "stroke": routed_edge.stroke,
            "stroke-width": _fmt(theme.stroke_width),
            "stroke-linecap": "round",
            "stroke-linejoin": "round",
        }
        if routed_edge.show_arrowhead:
            attributes["marker-end"] = f"url(#{marker_ids[routed_edge.stroke]})"
        if routed_edge.edge.dashed:
            attributes["stroke-dasharray"] = _dasharray(metrics.edge_dasharray)
        ET.SubElement(parent, ET.QName(SVG_NS, "path"), attrib=attributes)


def _render_join_badges(
    parent: ET.Element,
    edges: tuple[RoutedEdge, ...],
    theme: Theme,
) -> None:
    badge_diameter = max(theme.arrow_size * 1.8, theme.stroke_width * 6.0)
    badge_radius = badge_diameter / 2.0
    font_size = badge_diameter * 0.7

    for routed_edge in edges:
        badge_center = routed_edge.badge_center or routed_edge.join_point
        if routed_edge.edge.merge_symbol is None or badge_center is None:
            continue

        ET.SubElement(
            parent,
            ET.QName(SVG_NS, "circle"),
            attrib={
                "cx": _fmt(badge_center.x),
                "cy": _fmt(badge_center.y),
                "r": _fmt(badge_radius),
                "fill": "#FFFFFF",
                "stroke": routed_edge.stroke,
                "stroke-width": _fmt(theme.stroke_width),
            },
        )
        text = ET.SubElement(
            parent,
            ET.QName(SVG_NS, "text"),
            attrib={
                "x": _fmt(badge_center.x),
                "y": _fmt(badge_center.y),
                "fill": routed_edge.stroke,
                "text-anchor": "middle",
                "dominant-baseline": "central",
                "font-family": theme.title_font_family,
                "font-size": _fmt(font_size),
                "font-weight": str(theme.title_font_weight),
            },
        )
        text.text = routed_edge.edge.merge_symbol


def _render_points_for_edge(routed_edge: RoutedEdge) -> tuple[Point, ...]:
    if (
        routed_edge.edge.merge_symbol is None
        or routed_edge.join_point is None
        or routed_edge.join_badge_radius <= 0
        or len(routed_edge.points) < 2
    ):
        return routed_edge.points

    start = routed_edge.points[-2]
    end = routed_edge.points[-1]
    segment_length = abs(end.x - start.x) + abs(end.y - start.y)
    if segment_length <= 0.5:
        return routed_edge.points

    trim = min(routed_edge.join_badge_radius, max(segment_length - 0.5, 0.0))
    if trim <= 0:
        return routed_edge.points

    if start.x == end.x:
        direction = 1 if end.y > start.y else -1
        trimmed_end = Point(end.x, round(end.y - direction * trim, 2))
    elif start.y == end.y:
        direction = 1 if end.x > start.x else -1
        trimmed_end = Point(round(end.x - direction * trim, 2), end.y)
    else:
        return routed_edge.points

    return _collapse_render_points(routed_edge.points[:-1] + (trimmed_end,))


def _collapse_render_points(points: tuple[Point, ...]) -> tuple[Point, ...]:
    collapsed: list[Point] = []
    for point in points:
        if collapsed and point == collapsed[-1]:
            continue
        collapsed.append(point)
    return tuple(collapsed)


def _render_nodes(
    parent: ET.Element,
    nodes: dict[str, LayoutNode],
    theme: Theme,
    metrics: ResolvedThemeMetrics,
    *,
    id_prefix: str = "",
) -> None:
    for index, node_id in enumerate(sorted(nodes, key=lambda item: (nodes[item].rank, nodes[item].order, item))):
        _render_node(parent, nodes[node_id], theme, metrics, element_id=f"{id_prefix}{node_id}", palette_index=index)


def _render_node(
    parent: ET.Element,
    layout_node: LayoutNode,
    theme: Theme,
    metrics: ResolvedThemeMetrics,
    *,
    element_id: str,
    palette_index: int = 0,
) -> None:
    node = layout_node.node
    node_group = ET.SubElement(parent, ET.QName(SVG_NS, "g"), attrib={"id": element_id})

    resolved_fill = node.fill or (
        theme.color_palette[palette_index % len(theme.color_palette)]
        if theme.color_palette
        else theme.node_fill
    )

    _render_shadow_layers(
        node_group,
        x=layout_node.x,
        y=layout_node.y,
        width=layout_node.width,
        height=layout_node.height,
        rx=theme.corner_radius,
        ry=theme.corner_radius,
        metrics=metrics,
    )

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
            "fill": resolved_fill,
            "stroke": node.stroke or theme.node_stroke,
            "stroke-width": _fmt(theme.stroke_width),
        },
    )

    text_x = layout_node.x + layout_node.width / 2.0
    content_top = layout_node.y + (layout_node.height - layout_node.content_height) / 2
    current_top = content_top
    title_ascent = theme.title_font_size * metrics.title_baseline_ratio
    subtitle_ascent = theme.subtitle_font_size * metrics.subtitle_baseline_ratio
    text_color = node.text_color or _auto_text_color(resolved_fill, theme.node_text_color)

    for line in layout_node.title_lines:
        current_top += layout_node.title_line_height
        text_el = ET.SubElement(
            node_group,
            ET.QName(SVG_NS, "text"),
            attrib={
                "x": _fmt(text_x),
                "y": _fmt(current_top - layout_node.title_line_height + title_ascent),
                "fill": text_color,
                "text-anchor": "middle",
                "font-family": theme.title_font_family,
                "font-size": _fmt(theme.title_font_size),
                "font-weight": str(theme.title_font_weight),
            },
        )
        text_el.text = line

    if layout_node.subtitle_lines:
        current_top += theme.inter_text_gap
        for line in layout_node.subtitle_lines:
            current_top += layout_node.subtitle_line_height
            sub_text_el = ET.SubElement(
                node_group,
                ET.QName(SVG_NS, "text"),
                attrib={
                    "x": _fmt(text_x),
                    "y": _fmt(current_top - layout_node.subtitle_line_height + subtitle_ascent),
                    "fill": text_color,
                    "text-anchor": "middle",
                    "font-family": theme.title_font_family,
                    "font-size": _fmt(theme.subtitle_font_size),
                    "font-weight": str(theme.subtitle_font_weight),
                    "opacity": _fmt(metrics.subtitle_opacity),
                },
            )
            sub_text_el.text = line


def _auto_text_color(fill: str, fallback: str) -> str:
    rgb = _parse_color(fill)
    if rgb is None:
        return fallback

    # WCAG relative luminance heuristic for picking black/white text.
    luminance = _relative_luminance(rgb)
    contrast_with_black = (luminance + 0.05) / 0.05
    contrast_with_white = 1.05 / (luminance + 0.05)
    return "#111111" if contrast_with_black >= contrast_with_white else "#FFFFFF"


def _parse_color(value: str) -> tuple[int, int, int] | None:
    color = value.strip()
    if color.startswith("#"):
        hex_color = color[1:]
        if len(hex_color) == 3:
            hex_color = "".join(component * 2 for component in hex_color)
        if len(hex_color) != 6:
            return None
        try:
            return tuple(int(hex_color[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError:
            return None

    normalized = color.lower().removeprefix("rgb(").removesuffix(")")
    parts = [part.strip() for part in normalized.split(",")]
    if len(parts) != 3:
        return None
    try:
        return tuple(max(0, min(255, int(part))) for part in parts)
    except ValueError:
        return None


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    channels = []
    for channel in rgb:
        value = channel / 255.0
        if value <= 0.04045:
            channels.append(value / 12.92)
        else:
            channels.append(((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _build_markers(
    defs: ET.Element,
    edges: tuple[RoutedEdge, ...],
    theme: Theme,
    metrics: ResolvedThemeMetrics,
) -> dict[str, str]:
    marker_ids: dict[str, str] = {}
    for color in sorted({routed_edge.stroke for routed_edge in edges}):
        marker_id = f"arrow-{hashlib.sha1(color.encode('utf-8')).hexdigest()[:10]}"
        marker_ids[color] = marker_id
        marker = ET.SubElement(
            defs,
            ET.QName(SVG_NS, "marker"),
            attrib={
                "id": marker_id,
                "viewBox": f"0 0 {_fmt(metrics.marker_viewbox_size)} {_fmt(metrics.marker_viewbox_size)}",
                "refX": _fmt(metrics.marker_ref_x),
                "refY": _fmt(metrics.marker_ref_y),
                "markerWidth": _fmt(metrics.marker_width),
                "markerHeight": _fmt(metrics.marker_height),
                "orient": "auto",
                "markerUnits": "userSpaceOnUse",
            },
        )
        ET.SubElement(
            marker,
            ET.QName(SVG_NS, "path"),
            attrib={
                "d": _marker_path(metrics),
                "fill": color,
                "opacity": _fmt(metrics.marker_opacity),
            },
        )
    return marker_ids


def _render_shadow_layers(
    parent: ET.Element,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    rx: float,
    ry: float,
    metrics: ResolvedThemeMetrics,
) -> None:
    for layer in reversed(metrics.paint_shadow_layers):
        if layer.opacity <= 0:
            continue
        # Use spread to expand the rectangle outwards
        ET.SubElement(
            parent,
            ET.QName(SVG_NS, "rect"),
            attrib={
                "x": _fmt(x - layer.spread),
                "y": _fmt(y + layer.offset_y - layer.spread),
                "width": _fmt(width + layer.spread * 2.0),
                "height": _fmt(height + layer.spread * 2.0),
                "rx": _fmt(rx + layer.spread if rx > 0 else 0),
                "ry": _fmt(ry + layer.spread if ry > 0 else 0),
                "fill": "#000000",
                "opacity": _fmt(layer.opacity),
            },
        )


def _marker_path(metrics: ResolvedThemeMetrics) -> str:
    return (
        f"M 0 {_fmt(metrics.marker_body_inset_y)} "
        f"L {_fmt(metrics.marker_tip_x)} {_fmt(metrics.marker_tip_y)} "
        f"L 0 {_fmt(metrics.marker_viewbox_size - metrics.marker_body_inset_y)} Z"
    )


def _dasharray(values: tuple[float, float]) -> str:
    return " ".join(_fmt(value) for value in values)


def _path_data(points: tuple[Point, ...]) -> str:
    commands = [f"M {_fmt(points[0].x)} {_fmt(points[0].y)}"]
    commands.extend(f"L {_fmt(point.x)} {_fmt(point.y)}" for point in points[1:])
    return " ".join(commands)


def _fmt(value: float) -> str:
    text = f"{value:.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
