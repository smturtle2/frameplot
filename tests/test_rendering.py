from __future__ import annotations

import runpy
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from frameplot import DetailPanel, Edge, Group, Node, Pipeline, Theme
from frameplot.layout import _row_gap_overrides, build_layout
from frameplot.layout.route import (
    _bounds_for_points,
    _build_component_geometry,
    _route_forward,
    _separate_overlapping_endpoints,
)
from frameplot.layout.types import Bounds, LayoutNode, Point, RoutedEdge
from frameplot.layout.validate import validate_pipeline
from frameplot.render.png import PNG_SIGNATURE
from frameplot.render.png import DEFAULT_PNG_SCALE
from frameplot.theme import resolve_theme_metrics

SVG_NS = {"svg": "http://www.w3.org/2000/svg"}


def _build_generate_pipeline_fixture() -> Pipeline:
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "test" / "generate_pipeline.py"))
    return namespace["build_pipeline"]()


def _make_layout_node(
    node_id: str,
    *,
    x: float,
    y: float,
    width: float = 120.0,
    height: float = 80.0,
    rank: int = 0,
    order: int = 0,
) -> LayoutNode:
    node = Node(node_id, node_id.title())
    return LayoutNode(
        node=node,
        rank=rank,
        order=order,
        component_id=0,
        width=width,
        height=height,
        x=x,
        y=y,
        title_lines=(node.title,),
        subtitle_lines=(),
        title_line_height=20.0,
        subtitle_line_height=16.0,
        content_height=20.0,
    )


def _bend_points(points) -> list[object]:
    bends = []

    for previous, current, following in zip(points, points[1:], points[2:]):
        previous_vertical = previous.x == current.x and previous.y != current.y
        previous_horizontal = previous.y == current.y and previous.x != current.x
        next_vertical = current.x == following.x and current.y != following.y
        next_horizontal = current.y == following.y and current.x != following.x

        if (previous_vertical and next_horizontal) or (previous_horizontal and next_vertical):
            bends.append(current)

    return bends


def _point_in_bounds(point, bounds) -> bool:
    return bounds.x <= point.x <= bounds.right and bounds.y <= point.y <= bounds.bottom


def _fmt(value: float) -> str:
    text = f"{value:.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _dasharray(values: tuple[float, float]) -> str:
    return " ".join(_fmt(value) for value in values)


def _node_rect_fill(root: ET.Element, node_id: str) -> str:
    node_group = root.find(f".//svg:g[@id='{node_id}']", SVG_NS)
    assert node_group is not None
    rects = node_group.findall("svg:rect", SVG_NS)
    assert rects
    return rects[-1].attrib["fill"]


def _segment_overlaps(points_a, points_b) -> list[tuple[str, float]]:
    overlaps: list[tuple[str, float]] = []

    for start_a, end_a in zip(points_a, points_a[1:]):
        for start_b, end_b in zip(points_b, points_b[1:]):
            if start_a.x == end_a.x == start_b.x == end_b.x:
                overlap = min(max(start_a.y, end_a.y), max(start_b.y, end_b.y)) - max(
                    min(start_a.y, end_a.y),
                    min(start_b.y, end_b.y),
                )
                if overlap > 0.01:
                    overlaps.append(("v", overlap))
            if start_a.y == end_a.y == start_b.y == end_b.y:
                overlap = min(max(start_a.x, end_a.x), max(start_b.x, end_b.x)) - max(
                    min(start_a.x, end_a.x),
                    min(start_b.x, end_b.x),
                )
                if overlap > 0.01:
                    overlaps.append(("h", overlap))

    return overlaps


def _segment_direction(start, end) -> str | None:
    if start.x == end.x and start.y != end.y:
        return "v"
    if start.y == end.y and start.x != end.x:
        return "h"
    return None


def _source_access_segment(points):
    if len(points) < 2:
        return points[0], points[0]
    direction = _segment_direction(points[0], points[1])
    end_index = 1
    for segment_index, (start, end) in enumerate(zip(points[1:], points[2:]), start=1):
        if _segment_direction(start, end) != direction:
            break
        end_index = segment_index + 1
    return points[0], points[end_index]


def _target_access_segment(points):
    if len(points) < 2:
        return points[-1], points[-1]
    direction = _segment_direction(points[-2], points[-1])
    start_index = len(points) - 2
    for segment_index in range(len(points) - 3, -1, -1):
        if _segment_direction(points[segment_index], points[segment_index + 1]) != direction:
            break
        start_index = segment_index
    return points[start_index], points[-1]


def _collinear_overlap_length(start_a, end_a, start_b, end_b) -> float:
    if start_a.x == end_a.x == start_b.x == end_b.x:
        if start_a.x != start_b.x:
            return 0.0
        return max(
            0.0,
            min(max(start_a.y, end_a.y), max(start_b.y, end_b.y))
            - max(min(start_a.y, end_a.y), min(start_b.y, end_b.y)),
        )
    if start_a.y == end_a.y == start_b.y == end_b.y:
        if start_a.y != start_b.y:
            return 0.0
        return max(
            0.0,
            min(max(start_a.x, end_a.x), max(start_b.x, end_b.x))
            - max(min(start_a.x, end_a.x), min(start_b.x, end_b.x)),
        )
    return 0.0


def _make_routed_edge(edge: Edge, points: tuple[Point, ...], theme: Theme) -> RoutedEdge:
    return RoutedEdge(
        edge=edge,
        points=points,
        bounds=_bounds_for_points(points, theme.stroke_width, theme.arrow_size),
        stroke=edge.color or theme.edge_color,
        target_kind="node",
        target_node_id=edge.target,
    )


def _segment_crossings(points_a, points_b) -> list[tuple[float, float]]:
    crossings: list[tuple[float, float]] = []

    for start_a, end_a in zip(points_a, points_a[1:]):
        for start_b, end_b in zip(points_b, points_b[1:]):
            if start_a.x == end_a.x and start_b.y == end_b.y:
                x = start_a.x
                y = start_b.y
                if (
                    min(start_b.x, end_b.x) < x < max(start_b.x, end_b.x)
                    and min(start_a.y, end_a.y) < y < max(start_a.y, end_a.y)
                ):
                    crossings.append((x, y))
            if start_a.y == end_a.y and start_b.x == end_b.x:
                x = start_b.x
                y = start_a.y
                if (
                    min(start_a.x, end_a.x) < x < max(start_a.x, end_a.x)
                    and min(start_b.y, end_b.y) < y < max(start_b.y, end_b.y)
                ):
                    crossings.append((x, y))

    return crossings


def _row_gap_between_rows(nodes: dict[str, LayoutNode], upper_row: int, lower_row: int) -> float:
    upper_bottom = max(node.bounds.bottom for node in nodes.values() if node.order == upper_row)
    lower_top = min(node.y for node in nodes.values() if node.order == lower_row)
    return round(lower_top - upper_bottom, 2)


def _point_on_segment(point, start, end) -> bool:
    if start.x == end.x == point.x:
        top, bottom = sorted((start.y, end.y))
        return top <= point.y <= bottom
    if start.y == end.y == point.y:
        left, right = sorted((start.x, end.x))
        return left <= point.x <= right
    return False


def _build_detail_row_gap_fixture() -> Pipeline:
    return Pipeline(
        nodes=[Node("focus", "Focus")],
        edges=[],
        detail_panel=DetailPanel(
            "detail",
            "focus",
            "Expanded Focus",
            nodes=(
                Node("shared", "Shared"),
                Node("upper", "Upper"),
                Node("lower", "Lower"),
                Node("upper_out", "Upper Out"),
                Node("lower_out", "Lower Out"),
            ),
            edges=(
                Edge("d1", "shared", "upper"),
                Edge("d2", "shared", "lower"),
                Edge("d3", "upper", "upper_out"),
                Edge("d4", "lower", "lower_out"),
            ),
        ),
    )


def _build_nested_group_fixture() -> Pipeline:
    return Pipeline(
        nodes=[
            Node("top_left", "Top Left"),
            Node("top_mid", "Top Mid"),
            Node("top_right", "Top Right"),
            Node("bottom_left", "Bottom Left"),
            Node("bottom_mid", "Bottom Mid"),
            Node("bottom_right", "Bottom Right"),
        ],
        edges=[
            Edge("e1", "top_left", "top_mid"),
            Edge("e2", "top_mid", "top_right"),
            Edge("e3", "bottom_left", "bottom_mid"),
            Edge("e4", "bottom_mid", "bottom_right"),
        ],
        groups=[
            Group(
                "parent",
                "Parent",
                ("top_left", "top_mid", "top_right", "bottom_left", "bottom_mid", "bottom_right"),
            ),
            Group(
                "child",
                "Child",
                ("bottom_mid",),
            ),
        ],
    )


def _build_nested_detail_panel_fixture() -> Pipeline:
    return Pipeline(
        nodes=[Node("focus", "Focus")],
        edges=[],
        detail_panel=DetailPanel(
            "detail",
            "focus",
            "Expanded Focus",
            nodes=(
                Node("top_left", "Top Left"),
                Node("top_mid", "Top Mid"),
                Node("top_right", "Top Right"),
                Node("bottom_left", "Bottom Left"),
                Node("bottom_mid", "Bottom Mid"),
                Node("bottom_right", "Bottom Right"),
            ),
            edges=(
                Edge("d1", "top_left", "top_mid"),
                Edge("d2", "top_mid", "top_right"),
                Edge("d3", "bottom_left", "bottom_mid"),
                Edge("d4", "bottom_mid", "bottom_right"),
            ),
            groups=(
                Group(
                    "parent",
                    "Parent",
                    ("top_left", "top_mid", "top_right", "bottom_left", "bottom_mid", "bottom_right"),
                ),
                Group("child", "Child", ("bottom_mid",)),
            ),
        ),
    )


def _path_points(path_data: str) -> tuple[Point, ...]:
    tokens = path_data.split()
    points: list[Point] = []
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if token in {"M", "L"}:
            points.append(Point(float(tokens[index + 1]), float(tokens[index + 2])))
            index += 3
            continue
        index += 1

    return tuple(points)


def _polyline_length(points) -> float:
    return sum(abs(start.x - end.x) + abs(start.y - end.y) for start, end in zip(points, points[1:]))


def _distance_to_point_on_path(points: tuple[Point, ...], point: Point) -> float:
    travelled = 0.0
    for start, end in zip(points, points[1:]):
        if _point_on_segment(point, start, end):
            return travelled + abs(point.x - start.x) + abs(point.y - start.y)
        travelled += abs(end.x - start.x) + abs(end.y - start.y)
    raise AssertionError("Point is not on path.")


def build_sample_pipeline() -> Pipeline:
    return Pipeline(
        nodes=[
            Node("start", "Start", "Receive request"),
            Node("fetch", "Fetch Data", "Load source tables"),
            Node("retry", "Retry", "Loop on transient failure", fill="#FFF2CC"),
            Node("done", "Done", "Return result", fill="#D9EAD3"),
        ],
        edges=[
            Edge("e1", "start", "fetch"),
            Edge("e2", "fetch", "retry", dashed=True),
            Edge("e3", "retry", "fetch", color="#C0504D"),
            Edge("e4", "fetch", "done"),
        ],
        groups=[
            Group("g1", "Execution", ["start", "fetch", "retry"], edge_ids=["e2"]),
        ],
    )


def test_svg_contains_expected_visual_elements() -> None:
    svg = build_sample_pipeline().to_svg()

    assert svg.startswith("<svg")
    assert 'marker-end="url(#arrow-' in svg
    assert 'stroke-dasharray="8 6"' in svg
    assert 'Execution' in svg
    assert 'fill="#FFF2CC"' in svg
    assert 'rx="16"' in svg or 'rx="16.0"' in svg


def test_built_in_themes_render_with_white_canvas_background() -> None:
    for theme_factory in (Theme.soft_retro, Theme.retro, Theme.pastel, Theme.dark, Theme.cyberpunk, Theme.monochrome):
        pipeline = Pipeline(nodes=[Node("n1", "Node")], edges=[], theme=theme_factory())
        root = ET.fromstring(pipeline.to_svg())
        background = root.find("./svg:rect", SVG_NS)

        assert background is not None
        assert background.attrib["fill"] == "#FFFFFF"


def test_theme_registry_exposes_named_theme_factories() -> None:
    assert tuple(Theme.themes) == ("soft_retro", "retro", "pastel", "dark", "cyberpunk", "monochrome")

    first = Theme.themes.soft_retro()
    second = Theme.themes.soft_retro()
    indexed = Theme.themes["soft_retro"]()

    assert isinstance(first, Theme)
    assert isinstance(second, Theme)
    assert isinstance(indexed, Theme)
    assert first is not second
    assert indexed is not first


def test_all_built_in_themes_render_group_strokes() -> None:
    for theme_factory in (Theme.soft_retro, Theme.retro, Theme.pastel, Theme.dark, Theme.cyberpunk, Theme.monochrome):
        assert theme_factory().group_stroke != "none"


def test_only_retro_uses_group_accent_line() -> None:
    assert Theme.retro().show_group_accent_line is True

    for theme_factory in (Theme.soft_retro, Theme.pastel, Theme.dark, Theme.cyberpunk, Theme.monochrome):
        assert theme_factory().show_group_accent_line is False


def test_pastel_group_fill_defaults_to_white() -> None:
    theme = Theme.pastel()

    assert theme.group_fill == "#FFFFFF"


def test_node_text_color_auto_switches_between_dark_and_light() -> None:
    pipeline = Pipeline(
        nodes=[
            Node("light", "Light", fill="#F6D36B"),
            Node("dark", "Dark", fill="#2C4695"),
        ],
        edges=[],
    )

    root = ET.fromstring(pipeline.to_svg())
    light_group = root.find(".//svg:g[@id='light']", SVG_NS)
    dark_group = root.find(".//svg:g[@id='dark']", SVG_NS)

    assert light_group is not None
    assert dark_group is not None
    assert light_group.findall("svg:text", SVG_NS)[0].attrib["fill"] == "#111111"
    assert dark_group.findall("svg:text", SVG_NS)[0].attrib["fill"] == "#FFFFFF"


def test_builtin_themes_use_automatic_node_palettes() -> None:
    base_nodes = [Node("first", "First"), Node("second", "Second")]
    base_edges = [Edge("e1", "first", "second")]

    for theme_factory in (Theme.soft_retro, Theme.retro, Theme.pastel, Theme.dark, Theme.cyberpunk, Theme.monochrome):
        theme = theme_factory()
        root = ET.fromstring(Pipeline(nodes=base_nodes, edges=base_edges, theme=theme).to_svg())

        assert theme.color_palette is not None
        assert _node_rect_fill(root, "first") == theme.color_palette[0]
        assert _node_rect_fill(root, "second") == theme.color_palette[1]


def test_built_in_themes_match_curated_palettes() -> None:
    assert Theme.soft_retro().color_palette == (
        "#F6C8B8", "#F8DCA8", "#CFE8C6", "#BFDCEC", "#D8C9F1",
    )
    assert Theme.dark().color_palette == (
        "#171A26", "#2C3540", "#425059", "#657371", "#808C8B",
    )
    assert Theme.monochrome().color_palette == (
        "#4A4E59", "#8890A6", "#3C4A73", "#576BA6", "#C8D3F3",
    )
    assert Theme.cyberpunk().color_palette == (
        "#4A79D9", "#B6F2F2", "#F2B56B", "#F27A5E", "#F25E5E",
    )


def test_soft_retro_preserves_retro_geometry_with_monospace_type() -> None:
    theme = Theme.soft_retro()

    assert theme.corner_radius == 10.0
    assert theme.group_corner_radius == 12.0
    assert theme.detail_panel_corner_radius == 10.0
    assert theme.stroke_width == 2.5
    assert theme.show_group_accent_line is False
    assert "monospace" in theme.title_font_family.lower()


def test_non_retro_themes_have_distinct_visual_profiles() -> None:
    dark = Theme.dark()
    cyberpunk = Theme.cyberpunk()
    pastel = Theme.pastel()
    monochrome = Theme.monochrome()

    assert dark.corner_radius == 16.0
    assert dark.shadow_opacity > 0.0
    assert "serif" in dark.title_font_family.lower()

    assert cyberpunk.corner_radius == 0.0
    assert cyberpunk.stroke_width > dark.stroke_width
    assert "monospace" in cyberpunk.title_font_family.lower()

    assert pastel.corner_radius > dark.corner_radius
    assert pastel.group_corner_radius > pastel.corner_radius
    assert pastel.shadow_blur > dark.shadow_blur * 0.5

    assert monochrome.shadow_opacity == 0.0
    assert monochrome.corner_radius == 8.0
    assert "monospace" in monochrome.title_font_family.lower()


def test_quickstart_forward_group_crossing_bends_outside_group_bounds() -> None:
    layout = build_layout(build_sample_pipeline())
    execution = next(overlay.bounds for overlay in layout.main.groups if overlay.group.id == "g1")
    routed = {edge.edge.id: edge for edge in layout.main.edges}

    bends = _bend_points(routed["e4"].points)

    assert bends
    assert all(not _point_in_bounds(point, execution) for point in bends)


def test_quickstart_shared_group_back_edge_uses_local_gap_midpoints() -> None:
    layout = build_layout(build_sample_pipeline())
    execution = next(overlay.bounds for overlay in layout.main.groups if overlay.group.id == "g1")
    routed = {edge.edge.id: edge for edge in layout.main.edges}
    grouped_node_top = min(layout.main.nodes[node_id].y for node_id in ("start", "fetch", "retry"))
    start_right = layout.main.nodes["start"].right
    fetch_left = layout.main.nodes["fetch"].x
    retry_right = layout.main.nodes["retry"].right

    back_edge = routed["e3"].points
    bends = _bend_points(back_edge)
    lane_y = min(point.y for point in back_edge)
    left_vertical_x = bends[-1].x
    right_vertical_x = bends[0].x

    assert bends
    assert lane_y < grouped_node_top
    assert all(_point_in_bounds(point, execution) for point in bends)
    assert left_vertical_x == pytest.approx((start_right + fetch_left) / 2, abs=0.01)
    assert right_vertical_x == pytest.approx((retry_right + execution.right) / 2, abs=0.01)


def test_quickstart_adjacent_rank_gaps_use_balanced_floor_and_expand_only_at_group_boundary() -> None:
    pipeline = build_sample_pipeline()
    layout = build_layout(pipeline)
    compact_gap = resolve_theme_metrics(pipeline.theme).compact_rank_gap
    execution = next(overlay.bounds for overlay in layout.main.groups if overlay.group.id == "g1")
    done = layout.main.nodes["done"]
    retry = layout.main.nodes["retry"]

    start_to_fetch = layout.main.nodes["fetch"].x - layout.main.nodes["start"].right
    fetch_to_retry = layout.main.nodes["retry"].x - layout.main.nodes["fetch"].right
    retry_to_done = done.x - layout.main.nodes["retry"].right
    inside_clearance = execution.right - retry.right
    outside_clearance = done.x - execution.right

    assert start_to_fetch == pytest.approx(compact_gap, abs=0.01)
    assert fetch_to_retry == pytest.approx(compact_gap, abs=0.01)
    assert retry_to_done > compact_gap
    assert outside_clearance == pytest.approx(inside_clearance, abs=0.01)


def test_group_boundary_gap_expands_to_keep_left_outside_node_outside_overlay() -> None:
    pipeline = Pipeline(
        nodes=[
            Node("start", "Start"),
            Node("middle", "Middle"),
            Node("inside", "Inside"),
        ],
        edges=[
            Edge("e1", "start", "middle"),
            Edge("e2", "middle", "inside"),
            Edge("e3", "inside", "middle", color="#C0504D"),
        ],
        groups=[Group("g1", "Execution", ["middle", "inside"])],
    )

    layout = build_layout(pipeline)
    execution = next(overlay.bounds for overlay in layout.main.groups if overlay.group.id == "g1")
    start = layout.main.nodes["start"]
    middle = layout.main.nodes["middle"]
    compact_gap = resolve_theme_metrics(pipeline.theme).compact_rank_gap
    inside_clearance = middle.x - execution.x
    outside_clearance = execution.x - start.right

    assert middle.x - start.right > compact_gap
    assert outside_clearance == pytest.approx(inside_clearance, abs=0.01)


def test_adjacent_groups_keep_visible_gap_between_group_overlays() -> None:
    pipeline = Pipeline(
        nodes=[
            Node("a1", "A1"),
            Node("a2", "A2"),
            Node("b1", "B1"),
            Node("b2", "B2"),
        ],
        edges=[
            Edge("e1", "a1", "a2"),
            Edge("e2", "a2", "b1"),
            Edge("e3", "b1", "b2"),
        ],
        groups=[
            Group("g1", "Left", ["a1", "a2"]),
            Group("g2", "Right", ["b1", "b2"]),
        ],
    )

    layout = build_layout(pipeline)
    overlays = {overlay.group.id: overlay.bounds for overlay in layout.main.groups}
    left = overlays["g1"]
    right = overlays["g2"]
    left_inner = left.right - layout.main.nodes["a2"].right
    right_inner = layout.main.nodes["b1"].x - right.x

    assert right.x > left.right
    assert right.x - left.right == pytest.approx(max(left_inner, right_inner), abs=0.01)


def test_row_gap_overrides_track_actual_horizontal_lane_span_for_main_and_panel() -> None:
    main_pipeline = Pipeline(
        nodes=[
            Node("upper_left", "Upper Left"),
            Node("upper_right", "Upper Right"),
            Node("lower_left", "Lower Left"),
            Node("lower_right", "Lower Right"),
        ],
        edges=[
            Edge("e1", "upper_left", "lower_left"),
            Edge("e2", "upper_left", "lower_right"),
        ],
    )
    validated_main = validate_pipeline(main_pipeline)
    theme = main_pipeline.theme
    placed_main = {
        "upper_left": _make_layout_node("upper_left", x=0.0, y=0.0, rank=0, order=0),
        "upper_right": _make_layout_node("upper_right", x=220.0, y=0.0, rank=1, order=0),
        "lower_left": _make_layout_node("lower_left", x=0.0, y=200.0, rank=0, order=1),
        "lower_right": _make_layout_node("lower_right", x=220.0, y=200.0, rank=1, order=1),
    }
    routed_main = (
        _make_routed_edge(
            validated_main.edge_lookup["e1"],
            (
                Point(120.0, 40.0),
                Point(150.0, 40.0),
                Point(150.0, 120.0),
                Point(250.0, 120.0),
                Point(250.0, 240.0),
            ),
            theme,
        ),
        _make_routed_edge(
            validated_main.edge_lookup["e2"],
            (
                Point(120.0, 40.0),
                Point(170.0, 40.0),
                Point(170.0, 140.0),
                Point(320.0, 140.0),
                Point(320.0, 240.0),
            ),
            theme,
        ),
    )
    expected_gap = 20.0 + theme.route_track_gap

    assert _row_gap_overrides(validated_main, placed_main, routed_main, ()) == {(0, 0): expected_gap}

    panel_pipeline = _build_detail_row_gap_fixture()
    validated_panel = validate_pipeline(panel_pipeline).detail_panel
    panel_theme = panel_pipeline.theme
    placed_panel = {
        "shared": _make_layout_node("shared", x=0.0, y=0.0, rank=0, order=0),
        "upper": _make_layout_node("upper", x=220.0, y=0.0, rank=1, order=0),
        "lower": _make_layout_node("lower", x=220.0, y=200.0, rank=1, order=1),
        "upper_out": _make_layout_node("upper_out", x=440.0, y=0.0, rank=2, order=0),
        "lower_out": _make_layout_node("lower_out", x=440.0, y=200.0, rank=2, order=1),
    }
    routed_panel = (
        _make_routed_edge(
            validated_panel.edge_lookup["d1"],
            (
                Point(120.0, 40.0),
                Point(150.0, 40.0),
                Point(150.0, 120.0),
                Point(250.0, 120.0),
                Point(250.0, 40.0),
                Point(220.0, 40.0),
            ),
            panel_theme,
        ),
        _make_routed_edge(
            validated_panel.edge_lookup["d2"],
            (
                Point(120.0, 40.0),
                Point(170.0, 40.0),
                Point(170.0, 140.0),
                Point(250.0, 140.0),
                Point(250.0, 240.0),
                Point(220.0, 240.0),
            ),
            panel_theme,
        ),
    )

    assert _row_gap_overrides(validated_panel, placed_panel, routed_panel, ()) == {(0, 0): expected_gap}


def test_nested_groups_keep_visible_inner_gap_and_header_clearance() -> None:
    pipeline = _build_nested_group_fixture()
    layout = build_layout(pipeline)
    overlays = {overlay.group.id: overlay.bounds for overlay in layout.main.groups}
    metrics = resolve_theme_metrics(pipeline.theme)
    parent = overlays["parent"]
    child = overlays["child"]

    assert [overlay.group.id for overlay in layout.main.groups] == ["parent", "child"]
    assert child.x >= parent.x + pipeline.theme.group_padding - 0.01
    assert child.right <= parent.right - pipeline.theme.group_padding + 0.01
    assert child.bottom <= parent.bottom - pipeline.theme.group_padding + 0.01
    assert child.y - parent.y > pipeline.theme.subtitle_font_size * metrics.line_height_ratio


def test_forward_edge_entering_group_bends_outside_group_bounds() -> None:
    pipeline = Pipeline(
        nodes=[
            Node("source", "Source"),
            Node("blocker", "Blocker"),
            Node("target", "Target"),
        ],
        edges=[
            Edge("e1", "source", "blocker"),
            Edge("e2", "blocker", "target"),
            Edge("e3", "source", "target", color="#C0504D"),
        ],
        groups=[Group("g1", "Execution", ["blocker", "target"])],
    )

    layout = build_layout(pipeline)
    execution = next(overlay.bounds for overlay in layout.main.groups if overlay.group.id == "g1")
    routed = {edge.edge.id: edge for edge in layout.main.edges}

    bends = _bend_points(routed["e3"].points)

    assert bends
    assert all(not _point_in_bounds(point, execution) for point in bends)


def test_grouped_forward_edge_can_use_right_side_direct_elbow() -> None:
    layout = build_layout(_build_generate_pipeline_fixture())
    inputs = next(overlay.bounds for overlay in layout.main.groups if overlay.group.id == "feature_stage")
    routed = {edge.edge.id: edge for edge in layout.main.edges}
    guide = layout.main.nodes["h_feature"]
    target = layout.main.nodes["main_blocks"]

    points = routed["h_to_main"].points
    bends = _bend_points(points)

    assert len(points) == 3
    assert bends == [points[1]]
    assert points[0] == Point(guide.right, guide.center_y)
    assert points[-1] == Point(target.center_x, target.y)
    assert all(not _point_in_bounds(point, inputs) for point in bends)


def test_back_edge_leaves_group_before_bending() -> None:
    pipeline = Pipeline(
        nodes=[
            Node("start", "Start"),
            Node("inside", "Inside"),
            Node("done", "Done"),
        ],
        edges=[
            Edge("e1", "start", "inside"),
            Edge("e2", "inside", "done"),
            Edge("e3", "inside", "start", color="#C0504D"),
        ],
        groups=[Group("g1", "Execution", ["inside"])],
    )

    layout = build_layout(pipeline)
    execution = next(overlay.bounds for overlay in layout.main.groups if overlay.group.id == "g1")
    routed = {edge.edge.id: edge for edge in layout.main.edges}

    bends = _bend_points(routed["e3"].points)

    assert bends
    assert all(not _point_in_bounds(point, execution) for point in bends)


def test_grouped_self_loop_bends_outside_group_bounds() -> None:
    pipeline = Pipeline(
        nodes=[Node("task", "Task")],
        edges=[Edge("e1", "task", "task", dashed=True)],
        groups=[Group("g1", "Execution", ["task"])],
    )

    layout = build_layout(pipeline)
    execution = next(overlay.bounds for overlay in layout.main.groups if overlay.group.id == "g1")
    routed = {edge.edge.id: edge for edge in layout.main.edges}

    bends = _bend_points(routed["e1"].points)

    assert bends
    assert all(not _point_in_bounds(point, execution) for point in bends)


def test_validation_raises_for_unknown_nodes() -> None:
    pipeline = Pipeline(
        nodes=[Node("start", "Start")],
        edges=[Edge("e1", "start", "missing")],
    )

    with pytest.raises(ValueError, match="missing target node or edge"):
        pipeline.to_svg()


def test_validation_raises_for_unknown_detail_focus_node() -> None:
    pipeline = Pipeline(
        nodes=[Node("start", "Start")],
        edges=[],
        detail_panel=DetailPanel(
            "detail",
            "missing",
            "Expanded",
            nodes=(Node("inner", "Inner"),),
            edges=(),
        ),
    )

    with pytest.raises(ValueError, match="missing focus node"):
        pipeline.to_svg()


def test_validation_rejects_node_and_edge_id_collisions() -> None:
    pipeline = Pipeline(
        nodes=[Node("dup", "Node"), Node("other", "Other")],
        edges=[Edge("dup", "other", "dup")],
    )

    with pytest.raises(ValueError, match="Duplicate id shared by node and edge"):
        pipeline.to_svg()


def test_validation_rejects_merge_symbol_on_node_target() -> None:
    pipeline = Pipeline(
        nodes=[Node("start", "Start"), Node("done", "Done")],
        edges=[Edge("e1", "start", "done", merge_symbol="+")],
    )

    with pytest.raises(ValueError, match="sets merge_symbol but targets node"):
        pipeline.to_svg()


def test_validation_rejects_edge_to_edge_chains() -> None:
    pipeline = Pipeline(
        nodes=[
            Node("a", "A"),
            Node("b", "B"),
            Node("c", "C"),
            Node("d", "D"),
            Node("e", "E"),
        ],
        edges=[
            Edge("e1", "a", "b"),
            Edge("e2", "c", "e1"),
            Edge("e3", "d", "e2"),
        ],
    )

    with pytest.raises(ValueError, match="edge-to-edge chains are not supported"):
        pipeline.to_svg()


def test_save_svg_writes_file(tmp_path) -> None:
    output = tmp_path / "pipeline.svg"

    build_sample_pipeline().save_svg(output)

    assert output.read_text(encoding="utf-8").startswith("<svg")


def test_png_export_uses_cairosvg(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_svg2png(*, bytestring, scale):
        captured["bytestring"] = bytestring
        captured["scale"] = scale
        return b"\x89PNG\r\n\x1a\nfake"

    monkeypatch.setitem(
        __import__("sys").modules,
        "cairosvg",
        SimpleNamespace(svg2png=fake_svg2png),
    )

    pipeline = build_sample_pipeline()
    png_bytes = pipeline.to_png_bytes()
    output = tmp_path / "pipeline.png"
    pipeline.save_png(output)

    assert png_bytes.startswith(b"\x89PNG")
    assert captured["bytestring"].startswith(b"<svg")
    assert captured["scale"] == DEFAULT_PNG_SCALE
    assert output.read_bytes().startswith(b"\x89PNG")


def test_png_export_rejects_non_png_payloads(monkeypatch) -> None:
    monkeypatch.setitem(
        __import__("sys").modules,
        "cairosvg",
        SimpleNamespace(svg2png=lambda *, bytestring, scale: b"not-a-png"),
    )

    with pytest.raises(RuntimeError, match="non-PNG"):
        build_sample_pipeline().to_png_bytes()


def test_png_export_forwards_custom_scale(monkeypatch) -> None:
    captured = {}

    def fake_svg2png(*, bytestring, scale):
        captured["bytestring"] = bytestring
        captured["scale"] = scale
        return b"\x89PNG\r\n\x1a\nfake"

    monkeypatch.setitem(
        __import__("sys").modules,
        "cairosvg",
        SimpleNamespace(svg2png=fake_svg2png),
    )

    build_sample_pipeline().to_png_bytes(scale=3.0)

    assert captured["bytestring"].startswith(b"<svg")
    assert captured["scale"] == 3.0


def test_render_is_deterministic_and_accepts_theme_none() -> None:
    pipeline = Pipeline(
        nodes=[Node("a", "A"), Node("b", "B"), Node("c", "C")],
        edges=[Edge("e1", "a", "b"), Edge("e2", "b", "c"), Edge("e3", "c", "b")],
        theme=None,
    )

    first = pipeline.to_svg()
    second = pipeline.to_svg()

    assert first == second
    assert 'viewBox="0 0 ' in first


def test_svg_handles_back_edges_and_self_loops() -> None:
    pipeline = Pipeline(
        nodes=[Node("start", "Start"), Node("task", "Task"), Node("end", "End")],
        edges=[
            Edge("e1", "start", "task"),
            Edge("e2", "task", "task", dashed=True),
            Edge("e3", "task", "end"),
            Edge("e4", "end", "task", color="#EA580C"),
        ],
        groups=[Group("g1", "Execution", ["task", "end"], edge_ids=["e3", "e4"])],
    )

    svg = pipeline.to_svg()

    assert svg.count("marker-end=") == 4
    assert "Execution" in svg
    assert 'stroke="#EA580C"' in svg
    assert 'stroke-dasharray="8 6"' in svg


def test_default_theme_uses_larger_arrowheads() -> None:
    pipeline = Pipeline(
        nodes=[Node("start", "Start"), Node("done", "Done")],
        edges=[Edge("e1", "start", "done")],
    )
    root = ET.fromstring(pipeline.to_svg())
    marker = root.find(".//svg:marker", SVG_NS)

    assert marker is not None
    assert marker.attrib["markerWidth"] == "8"
    assert marker.attrib["markerHeight"] == "8"


def test_edge_target_join_terminates_on_target_edge_segment() -> None:
    pipeline = Pipeline(
        nodes=[Node("a", "A"), Node("b", "B"), Node("c", "C"), Node("d", "D")],
        edges=[
            Edge("e1", "a", "b"),
            Edge("e2", "c", "d"),
            Edge("e3", "a", "e2", merge_symbol="+", color="#C0504D"),
        ],
    )

    layout = build_layout(pipeline)
    routed = {edge.edge.id: edge for edge in layout.main.edges}
    join_edge = routed["e3"]
    target_edge = routed["e2"]
    target_node = layout.main.nodes["d"]

    assert join_edge.target_kind == "edge"
    assert join_edge.target_edge_id == "e2"
    assert join_edge.join_point == join_edge.points[-1]
    assert join_edge.join_point is not None
    assert join_edge.badge_center is not None
    assert join_edge.badge_center == join_edge.join_point
    assert any(
        _point_on_segment(join_edge.join_point, start, end)
        for start, end in zip(target_edge.points, target_edge.points[1:])
    )
    assert _distance_to_point_on_path(target_edge.points, join_edge.join_point) == pytest.approx(
        _polyline_length(target_edge.points) / 2.0,
        abs=0.2,
    )
    assert join_edge.join_point.x < target_node.x


def test_edge_target_join_lengthens_target_edge() -> None:
    base_pipeline = Pipeline(
        nodes=[Node("a", "A"), Node("b", "B"), Node("c", "C"), Node("d", "D")],
        edges=[
            Edge("e1", "a", "b"),
            Edge("e2", "c", "d"),
        ],
    )
    joined_pipeline = Pipeline(
        nodes=[Node("a", "A"), Node("b", "B"), Node("c", "C"), Node("d", "D")],
        edges=[
            Edge("e1", "a", "b"),
            Edge("e2", "c", "d"),
            Edge("e3", "a", "e2", merge_symbol="+"),
        ],
    )

    base_layout = build_layout(base_pipeline)
    joined_layout = build_layout(joined_pipeline)

    base_target = next(edge for edge in base_layout.main.edges if edge.edge.id == "e2")
    joined_target = next(edge for edge in joined_layout.main.edges if edge.edge.id == "e2")

    assert _polyline_length(joined_target.points) > _polyline_length(base_target.points)


def test_edge_target_join_picks_nearest_eligible_segment() -> None:
    pipeline = Pipeline(
        nodes=[Node("s", "S"), Node("m", "M"), Node("t", "T"), Node("alt", "Alt"), Node("sink2", "Sink2")],
        edges=[
            Edge("e1", "s", "m"),
            Edge("e2", "m", "t"),
            Edge("e3", "s", "t"),
            Edge("e4", "alt", "sink2"),
            Edge("e5", "sink2", "e3"),
        ],
    )

    layout = build_layout(pipeline)
    routed = {edge.edge.id: edge for edge in layout.main.edges}
    join_edge = routed["e5"]
    target_edge = routed["e3"]
    source_node = layout.main.nodes["sink2"]
    source_point = source_node.right, source_node.center_y

    assert join_edge.join_point is not None

    eligible_distances = []
    for start, end in zip(target_edge.points, target_edge.points[1:]):
        if start.x == end.x:
            top, bottom = sorted((start.y, end.y))
            point = (start.x, min(max(source_point[1], top), bottom))
            distance = abs(source_point[0] - point[0]) + abs(source_point[1] - point[1])
            eligible_distances.append(distance)
        elif start.y == end.y:
            left, right = sorted((start.x, end.x))
            point = (min(max(source_point[0], left), right), start.y)
            distance = abs(source_point[0] - point[0]) + abs(source_point[1] - point[1])
            eligible_distances.append(distance)

    chosen_distance = min(eligible_distances)

    assert abs(source_point[0] - join_edge.join_point.x) + abs(source_point[1] - join_edge.join_point.y) == chosen_distance


def test_edge_target_join_without_merge_symbol_keeps_arrowhead() -> None:
    pipeline = Pipeline(
        nodes=[Node("a", "A"), Node("b", "B"), Node("c", "C"), Node("d", "D")],
        edges=[
            Edge("e1", "a", "b"),
            Edge("e2", "c", "d"),
            Edge("e3", "a", "e2"),
        ],
    )
    root = ET.fromstring(pipeline.to_svg())
    edge_paths = root.findall(".//svg:g[@id='edges']/svg:path", SVG_NS)
    join_badges = root.findall(".//svg:g[@id='edge-joins']/svg:text", SVG_NS)

    assert len(edge_paths) == 3
    assert all("marker-end" in path.attrib for path in edge_paths)
    assert not join_badges


def test_edge_target_join_with_merge_symbol_renders_badge_without_arrowhead() -> None:
    pipeline = Pipeline(
        nodes=[Node("a", "A"), Node("b", "B"), Node("c", "C"), Node("d", "D")],
        edges=[
            Edge("e1", "a", "b"),
            Edge("e2", "c", "d"),
            Edge("e3", "a", "e2", merge_symbol="+", color="#C0504D"),
        ],
    )
    root = ET.fromstring(pipeline.to_svg())
    edge_paths = root.findall(".//svg:g[@id='edges']/svg:path", SVG_NS)
    join_text = root.find(".//svg:g[@id='edge-joins']/svg:text", SVG_NS)
    join_circle = root.find(".//svg:g[@id='edge-joins']/svg:circle", SVG_NS)
    join_path = next(path for path in edge_paths if path.attrib["stroke"] == "#C0504D")
    target_paths = [path for path in edge_paths if path.attrib["stroke"] != "#C0504D"]

    assert len(edge_paths) == 3
    assert sum("marker-end" in path.attrib for path in edge_paths) == 2
    assert join_text is not None
    assert join_circle is not None
    assert join_text.text == "+"
    assert join_circle.attrib["fill"] == "#FFFFFF"

    circle_center = Point(float(join_circle.attrib["cx"]), float(join_circle.attrib["cy"]))
    join_points = _path_points(join_path.attrib["d"])
    target_polylines = [_path_points(path.attrib["d"]) for path in target_paths]
    target_total_length = max(_polyline_length(points) for points in target_polylines)

    assert join_points[-1] != circle_center
    assert any(
        _point_on_segment(circle_center, start, end)
        for points in target_polylines
        for start, end in zip(points, points[1:])
    )
    assert min(
        abs(circle_center.x - points[0].x) + abs(circle_center.y - points[0].y)
        for points in target_polylines
    ) == pytest.approx(target_total_length / 2.0, abs=0.2)

    layout = build_layout(pipeline)
    join_edge = next(edge for edge in layout.main.edges if edge.edge.id == "e3")
    assert join_edge.join_point == join_edge.badge_center


def test_svg_serializes_resolved_dash_and_marker_metrics() -> None:
    theme = Theme.dark()
    theme.arrow_size = 9.0
    theme.stroke_width = 2.25
    theme.group_stroke_width = 1.75
    theme.route_track_gap = 27.0
    theme.group_padding = 30.0
    theme.node_padding_y = 20.0
    theme.subtitle_font_size = 14.0

    pipeline = Pipeline(
        nodes=build_sample_pipeline().nodes,
        edges=build_sample_pipeline().edges,
        groups=build_sample_pipeline().groups,
        theme=theme,
    )
    metrics = resolve_theme_metrics(theme)
    root = ET.fromstring(pipeline.to_svg())

    group_rect = root.find(".//svg:g[@id='groups']/svg:rect", SVG_NS)
    dashed_edge = root.find(".//svg:g[@id='edges']/svg:path[@stroke-dasharray]", SVG_NS)
    marker = root.find(".//svg:marker", SVG_NS)

    assert group_rect is not None
    assert dashed_edge is not None
    assert marker is not None
    assert group_rect.attrib["stroke-dasharray"] == _dasharray(metrics.group_dasharray)
    assert dashed_edge.attrib["stroke-dasharray"] == _dasharray(metrics.edge_dasharray)
    assert marker.attrib["markerWidth"] == _fmt(metrics.marker_width)
    assert marker.attrib["markerHeight"] == _fmt(metrics.marker_height)
    assert marker.attrib["refX"] == _fmt(metrics.marker_ref_x)
    assert marker.attrib["refY"] == _fmt(metrics.marker_ref_y)


def test_compact_rank_gap_tracks_route_track_gap_floor() -> None:
    theme = Theme()

    assert resolve_theme_metrics(theme).compact_rank_gap == pytest.approx(theme.route_track_gap, abs=0.01)

    theme.route_track_gap = 27.0

    assert resolve_theme_metrics(theme).compact_rank_gap == pytest.approx(27.0, abs=0.01)


def test_text_measurement_and_render_share_resolved_baselines() -> None:
    theme = Theme.dark()
    theme.title_font_size = 20.0
    theme.subtitle_font_size = 11.0
    theme.node_padding_x = 24.0
    theme.node_padding_y = 18.0

    pipeline = Pipeline(
        nodes=[Node("focus", "Primary Title", "Secondary line")],
        edges=[],
        theme=theme,
    )
    layout = build_layout(pipeline)
    svg = pipeline.to_svg()
    metrics = resolve_theme_metrics(theme)
    layout_node = layout.main.nodes["focus"]
    node_group = ET.fromstring(svg).find(".//svg:g[@id='focus']", SVG_NS)

    assert node_group is not None
    texts = node_group.findall("svg:text", SVG_NS)
    assert len(texts) == 2
    assert layout_node.title_line_height == pytest.approx(theme.title_font_size * metrics.line_height_ratio)
    assert layout_node.subtitle_line_height == pytest.approx(theme.subtitle_font_size * metrics.line_height_ratio)

    content_top = layout_node.y + (layout_node.height - layout_node.content_height) / 2
    expected_title_y = content_top + theme.title_font_size * metrics.title_baseline_ratio
    expected_subtitle_y = (
        content_top
        + layout_node.title_line_height
        + theme.inter_text_gap
        + theme.subtitle_font_size * metrics.subtitle_baseline_ratio
    )

    assert float(texts[0].attrib["y"]) == pytest.approx(expected_title_y)
    assert float(texts[1].attrib["y"]) == pytest.approx(expected_subtitle_y)


def test_detail_panel_renders_as_separate_block_with_guides() -> None:
    pipeline = Pipeline(
        nodes=[
            Node("source", "Source"),
            Node("backbone", "Backbone", "N repeated blocks"),
            Node("sink", "Sink"),
        ],
        edges=[Edge("e1", "source", "backbone"), Edge("e2", "backbone", "sink")],
        detail_panel=DetailPanel(
            "detail",
            "backbone",
            "Expanded Backbone",
            nodes=(
                Node("z_prev", "z(i-1)"),
                Node("attn", "Neighborhood cross-attention"),
                Node("z_next", "z(i)"),
            ),
            edges=(Edge("d1", "z_prev", "attn"), Edge("d2", "attn", "z_next")),
            groups=(Group("inner", "local_count", ("attn",), ()),),
        ),
    )

    svg = pipeline.to_svg()

    assert 'id="detail-panel-guides"' in svg
    assert 'id="detail-panel-detail"' in svg
    assert "Expanded Backbone" in svg
    assert "Neighborhood" in svg
    assert "cross-attention" in svg
    assert "local_count" in svg
    assert svg.count('marker-end="url(#arrow-') == 4


def test_detail_panel_biases_focus_flow_to_lower_rows() -> None:
    pipeline = Pipeline(
        nodes=[
            Node("main_source", "Main Source"),
            Node("side_source", "Side Source"),
            Node("focus", "Focus"),
            Node("sink", "Sink"),
        ],
        edges=[
            Edge("e1", "main_source", "focus"),
            Edge("e2", "side_source", "focus", dashed=True),
            Edge("e3", "focus", "sink"),
        ],
        detail_panel=DetailPanel(
            "detail",
            "focus",
            "Expanded Focus",
            nodes=(Node("inner", "Inner"),),
            edges=(),
        ),
    )

    layout = build_layout(pipeline)

    assert layout.main.nodes["main_source"].order > layout.main.nodes["side_source"].order
    assert layout.main.nodes["focus"].order == max(node.order for node in layout.main.nodes.values())


def test_detail_panel_guides_expand_outward() -> None:
    pipeline = Pipeline(
        nodes=[
            Node("main_source", "Main Source"),
            Node("side_source", "Side Source"),
            Node("focus", "Focus"),
            Node("sink", "Sink"),
        ],
        edges=[
            Edge("e1", "main_source", "focus"),
            Edge("e2", "side_source", "focus", dashed=True),
            Edge("e3", "focus", "sink"),
        ],
        detail_panel=DetailPanel(
            "detail",
            "focus",
            "Expanded Focus",
            nodes=(Node("inner", "Inner"),),
            edges=(),
        ),
    )

    layout = build_layout(pipeline)

    for guide in layout.detail_panel.guide_lines:
        assert len(guide.points) == 3
        assert guide.points[0].y < guide.points[1].y < guide.points[2].y
        assert guide.points[0].x != pytest.approx(guide.points[1].x)


def test_detail_panel_nested_groups_keep_visible_inner_gap_and_header_clearance() -> None:
    pipeline = _build_nested_detail_panel_fixture()
    layout = build_layout(pipeline)
    overlays = {overlay.group.id: overlay.bounds for overlay in layout.detail_panel.graph.groups}
    metrics = resolve_theme_metrics(pipeline.theme)
    parent = overlays["parent"]
    child = overlays["child"]

    assert [overlay.group.id for overlay in layout.detail_panel.graph.groups] == ["parent", "child"]
    assert child.x >= parent.x + pipeline.theme.group_padding - 0.01
    assert child.right <= parent.right - pipeline.theme.group_padding + 0.01
    assert child.bottom <= parent.bottom - pipeline.theme.group_padding + 0.01
    assert child.y - parent.y > pipeline.theme.subtitle_font_size * metrics.line_height_ratio


def test_detail_panel_shared_guidance_node_stays_above_stream_groups() -> None:
    layout = build_layout(_build_generate_pipeline_fixture())
    panel_nodes = layout.detail_panel.graph.nodes
    panel_groups = layout.detail_panel.graph.groups
    routed = {edge.edge.id: edge for edge in layout.detail_panel.graph.edges}
    h_node = panel_nodes["panel_h"]
    source_lane_one = _source_access_segment(routed["panel_h_to_nca_c"].points)
    source_lane_two = _source_access_segment(routed["panel_h_to_nca_m"].points)

    assert h_node.order == 0
    assert panel_nodes["panel_c_in"].order == panel_nodes["panel_nca_c"].order == 1
    assert panel_nodes["panel_m_in"].order == panel_nodes["panel_nca_m"].order == 2
    assert all(not _point_in_bounds(Point(h_node.center_x, h_node.center_y), overlay.bounds) for overlay in panel_groups)
    assert routed["panel_h_to_nca_c"].points[0].x == h_node.right
    assert routed["panel_h_to_nca_m"].points[0].x == h_node.right
    assert routed["panel_h_to_nca_c"].points[0].y != routed["panel_h_to_nca_m"].points[0].y
    assert _collinear_overlap_length(*source_lane_one, *source_lane_two) == pytest.approx(0.0, abs=0.01)


def test_generate_pipeline_row_gap_no_longer_scales_with_raw_cross_row_edge_count() -> None:
    layout = build_layout(_build_generate_pipeline_fixture())
    gap = _row_gap_between_rows(layout.main.nodes, 0, 1)

    assert gap < 136.0


def test_generate_pipeline_nested_decoder_groups_reserve_parent_header_space() -> None:
    pipeline = _build_generate_pipeline_fixture()
    layout = build_layout(pipeline)
    overlays = {overlay.group.id: overlay.bounds for overlay in layout.main.groups}
    metrics = resolve_theme_metrics(pipeline.theme)
    decoders = overlays["decoders"]
    candidate = overlays["candidate_stream"]
    mask = overlays["mask_stream"]

    assert candidate.x >= decoders.x + pipeline.theme.group_padding - 0.01
    assert candidate.right <= decoders.right - pipeline.theme.group_padding + 0.01
    assert mask.x >= decoders.x + pipeline.theme.group_padding - 0.01
    assert mask.right <= decoders.right - pipeline.theme.group_padding + 0.01
    assert candidate.y - decoders.y > pipeline.theme.subtitle_font_size * metrics.line_height_ratio
    assert mask.y - decoders.y > pipeline.theme.subtitle_font_size * metrics.line_height_ratio


def test_generate_pipeline_separates_shared_source_endpoints() -> None:
    layout = build_layout(_build_generate_pipeline_fixture())
    main = layout.main.nodes["main_blocks"]
    routed = {edge.edge.id: edge for edge in layout.main.edges}
    first = routed["main_to_candidate"].points
    second = routed["main_to_mask"].points
    first_lane = _source_access_segment(first)
    second_lane = _source_access_segment(second)

    assert first[0].x == second[0].x == main.right
    assert first[0].y != second[0].y
    assert _collinear_overlap_length(*first_lane, *second_lane) == pytest.approx(0.0, abs=0.01)


def test_generate_pipeline_separates_shared_target_endpoints() -> None:
    layout = build_layout(_build_generate_pipeline_fixture())
    fusion = layout.main.nodes["fusion"]
    routed = {edge.edge.id: edge for edge in layout.main.edges}
    first = routed["candidate_to_fusion"].points
    second = routed["skip_to_fusion"].points
    first_lane = _target_access_segment(first)
    second_lane = _target_access_segment(second)

    assert first[-1].y == second[-1].y == fusion.y
    assert first[-1].x != second[-1].x
    assert _collinear_overlap_length(*first_lane, *second_lane) == pytest.approx(0.0, abs=0.01)


def test_generate_pipeline_orders_upper_top_entry_closer_to_fusion_center() -> None:
    layout = build_layout(_build_generate_pipeline_fixture())
    fusion = layout.main.nodes["fusion"]
    routed = {edge.edge.id: edge for edge in layout.main.edges}
    candidate = routed["candidate_to_fusion"].points
    skip = routed["skip_to_fusion"].points
    candidate_lane = _target_access_segment(candidate)
    skip_lane = _target_access_segment(skip)

    assert candidate_lane[0].y > skip_lane[0].y
    assert not _segment_crossings(candidate, skip)
    assert abs(skip[-1].x - fusion.center_x) < abs(candidate[-1].x - fusion.center_x)


def test_shared_target_top_side_orders_upper_approach_inward() -> None:
    theme = Theme()
    pipeline = Pipeline(
        nodes=[Node("upper", "Upper"), Node("lower", "Lower"), Node("target", "Target")],
        edges=[Edge("upper_edge", "upper", "target"), Edge("lower_edge", "lower", "target")],
        theme=theme,
    )
    validated = validate_pipeline(pipeline)
    nodes = {
        "upper": _make_layout_node("upper", x=80.0, y=40.0, rank=0, order=0),
        "lower": _make_layout_node("lower", x=80.0, y=160.0, rank=0, order=1),
        "target": _make_layout_node("target", x=300.0, y=300.0, rank=1, order=0),
    }
    routed_by_id = {
        "upper_edge": _make_routed_edge(
            validated.edge_lookup["upper_edge"],
            (Point(200.0, 80.0), Point(350.0, 80.0), Point(350.0, 300.0)),
            theme,
        ),
        "lower_edge": _make_routed_edge(
            validated.edge_lookup["lower_edge"],
            (Point(200.0, 200.0), Point(330.0, 200.0), Point(330.0, 300.0)),
            theme,
        ),
    }

    _separate_overlapping_endpoints(validated, nodes, routed_by_id)

    upper = routed_by_id["upper_edge"].points
    lower = routed_by_id["lower_edge"].points
    target = nodes["target"]

    assert not _segment_crossings(upper, lower)
    assert abs(upper[-1].x - target.center_x) < abs(lower[-1].x - target.center_x)


def test_shared_target_left_side_orders_shallower_approach_inward() -> None:
    theme = Theme()
    pipeline = Pipeline(
        nodes=[Node("outer", "Outer"), Node("inner", "Inner"), Node("target", "Target")],
        edges=[Edge("outer_edge", "outer", "target"), Edge("inner_edge", "inner", "target")],
        theme=theme,
    )
    validated = validate_pipeline(pipeline)
    nodes = {
        "outer": _make_layout_node("outer", x=80.0, y=180.0, width=120.0, height=72.0, rank=0, order=0),
        "inner": _make_layout_node("inner", x=80.0, y=40.0, width=120.0, height=72.0, rank=0, order=1),
        "target": _make_layout_node("target", x=320.0, y=190.0, width=120.0, height=72.0, rank=1, order=0),
    }
    routed_by_id = {
        "outer_edge": _make_routed_edge(
            validated.edge_lookup["outer_edge"],
            (Point(240.0, 222.0), Point(320.0, 222.0)),
            theme,
        ),
        "inner_edge": _make_routed_edge(
            validated.edge_lookup["inner_edge"],
            (Point(240.0, 80.0), Point(280.0, 80.0), Point(280.0, 230.0), Point(320.0, 230.0)),
            theme,
        ),
    }

    _separate_overlapping_endpoints(validated, nodes, routed_by_id)

    outer = routed_by_id["outer_edge"].points
    inner = routed_by_id["inner_edge"].points
    target = nodes["target"]

    assert not _segment_crossings(outer, inner)
    assert abs(outer[-1].y - target.center_y) < abs(inner[-1].y - target.center_y)


def test_shared_row_bands_align_nodes_across_ranks() -> None:
    pipeline = Pipeline(
        nodes=[
            Node("source", "Source"),
            Node("upper", "Upper", "Tall subtitle row"),
            Node("lower", "Lower"),
        ],
        edges=[Edge("e1", "source", "upper"), Edge("e2", "source", "lower")],
    )

    layout = build_layout(pipeline)

    assert layout.main.nodes["source"].center_y == layout.main.nodes["upper"].center_y
    assert layout.main.nodes["lower"].center_y > layout.main.nodes["upper"].center_y
    assert layout.main.nodes["source"].height == layout.main.nodes["upper"].height
    assert layout.main.nodes["upper"].width == layout.main.nodes["lower"].width


def test_forward_edges_stay_within_two_bends() -> None:
    pipeline = Pipeline(
        nodes=[
            Node("source", "Source"),
            Node("upper", "Upper"),
            Node("lower", "Lower"),
            Node("sink", "Sink"),
        ],
        edges=[
            Edge("e1", "source", "upper"),
            Edge("e2", "source", "lower"),
            Edge("e3", "upper", "sink"),
            Edge("e4", "lower", "sink"),
        ],
    )

    layout = build_layout(pipeline)

    for edge in layout.main.edges:
        source_rank = layout.main.nodes[edge.edge.source].rank
        target_rank = layout.main.nodes[edge.edge.target].rank
        if edge.edge.source == edge.edge.target or source_rank >= target_rank:
            continue
        assert len(edge.points) <= 4


def test_fanout_routing_uses_short_source_spine() -> None:
    pipeline = Pipeline(
        nodes=[Node("source", "Source"), Node("upper", "Upper"), Node("lower", "Lower")],
        edges=[Edge("e1", "source", "upper"), Edge("e2", "source", "lower")],
    )

    layout = build_layout(pipeline)
    routed = {edge.edge.id: edge for edge in layout.main.edges}
    theme = Theme()
    source = layout.main.nodes["source"]

    edge_one = routed["e1"].points
    edge_two = routed["e2"].points
    source_lane_one = _source_access_segment(edge_one)
    source_lane_two = _source_access_segment(edge_two)

    assert edge_one != edge_two
    assert len(edge_one) <= 4
    assert len(edge_two) <= 4
    assert edge_one[0].x == edge_two[0].x == source.right
    assert edge_one[0].y != edge_two[0].y
    assert _collinear_overlap_length(*source_lane_one, *source_lane_two) == pytest.approx(0.0, abs=0.01)
    assert source_lane_one[1].x - source_lane_one[0].x <= theme.route_track_gap * 2
    assert source_lane_two[1].x - source_lane_two[0].x <= theme.route_track_gap * 2


def test_fanin_routing_uses_short_target_spine() -> None:
    pipeline = Pipeline(
        nodes=[Node("upper", "Upper"), Node("lower", "Lower"), Node("sink", "Sink")],
        edges=[Edge("e1", "upper", "sink"), Edge("e2", "lower", "sink")],
    )

    layout = build_layout(pipeline)
    routed = {edge.edge.id: edge for edge in layout.main.edges}
    theme = Theme()
    sink = layout.main.nodes["sink"]

    edge_one = routed["e1"].points
    edge_two = routed["e2"].points
    target_lane_one = _target_access_segment(edge_one)
    target_lane_two = _target_access_segment(edge_two)

    assert len(edge_one) <= 4
    assert len(edge_two) <= 4
    assert edge_one[-1].x == edge_two[-1].x == sink.x
    assert edge_one[-1].y != edge_two[-1].y
    assert _collinear_overlap_length(*target_lane_one, *target_lane_two) == pytest.approx(0.0, abs=0.01)
    assert target_lane_one[1].x - target_lane_one[0].x <= theme.route_track_gap * 2
    assert target_lane_two[1].x - target_lane_two[0].x <= theme.route_track_gap * 2


def test_forward_router_can_use_top_and_bottom_ports_when_shorter() -> None:
    theme = Theme()
    source = LayoutNode(
        node=Node("source", "Source"),
        rank=0,
        order=0,
        component_id=0,
        width=100.0,
        height=56.0,
        x=40.0,
        y=40.0,
        title_lines=("Source",),
        subtitle_lines=(),
        title_line_height=20.0,
        subtitle_line_height=16.0,
        content_height=20.0,
    )
    blocker = LayoutNode(
        node=Node("blocker", "Blocker"),
        rank=1,
        order=0,
        component_id=0,
        width=120.0,
        height=56.0,
        x=220.0,
        y=40.0,
        title_lines=("Blocker",),
        subtitle_lines=(),
        title_line_height=20.0,
        subtitle_line_height=16.0,
        content_height=20.0,
    )
    target = LayoutNode(
        node=Node("target", "Target"),
        rank=2,
        order=0,
        component_id=0,
        width=100.0,
        height=56.0,
        x=430.0,
        y=40.0,
        title_lines=("Target",),
        subtitle_lines=(),
        title_line_height=20.0,
        subtitle_line_height=16.0,
        content_height=20.0,
    )
    alternate = LayoutNode(
        node=Node("alternate", "Alternate"),
        rank=1,
        order=1,
        component_id=0,
        width=120.0,
        height=56.0,
        x=220.0,
        y=180.0,
        title_lines=("Alternate",),
        subtitle_lines=(),
        title_line_height=20.0,
        subtitle_line_height=16.0,
        content_height=20.0,
    )
    nodes = {
        "source": source,
        "blocker": blocker,
        "target": target,
        "alternate": alternate,
    }
    geometry = _build_component_geometry(nodes, theme)[0]

    points = _route_forward(
        edge=Edge("edge", "source", "target"),
        source_node=source,
        target_node=target,
        geometry=geometry,
        nodes=nodes,
        outgoing_count=1,
        incoming_count=1,
        pair_offset=0.0,
        theme=theme,
    )

    assert points[0].x == source.center_x
    assert points[0].y == source.bounds.bottom
    assert points[-1].x == target.center_x
    assert points[-1].y == target.bounds.bottom
    assert len(points) <= 4


def test_forward_overlaps_are_limited_to_short_shared_stubs() -> None:
    pipeline = Pipeline(
        nodes=[
            Node("source", "Source"),
            Node("upper", "Upper"),
            Node("lower", "Lower"),
            Node("sink", "Sink"),
        ],
        edges=[
            Edge("e1", "source", "upper"),
            Edge("e2", "source", "lower"),
            Edge("e3", "upper", "sink"),
            Edge("e4", "lower", "sink"),
        ],
    )

    layout = build_layout(pipeline)
    routed = list(layout.main.edges)
    theme = Theme()

    for index, first in enumerate(routed):
        for second in routed[index + 1 :]:
            overlaps = _segment_overlaps(first.points, second.points)
            if not overlaps:
                continue

            assert (
                first.edge.source == second.edge.source
                or first.edge.target == second.edge.target
            )
            assert all(length <= theme.route_track_gap for _, length in overlaps)


def test_sar_example_avoids_interior_edge_crossings() -> None:
    namespace = runpy.run_path("examples/sar_backbone_example.py")
    pipeline = namespace["build_pipeline"]()
    layout = build_layout(pipeline)
    routed = list(layout.main.edges)

    for index, first in enumerate(routed):
        for second in routed[index + 1 :]:
            assert not _segment_crossings(first.points, second.points)


def test_sar_backbone_example_builds() -> None:
    namespace = runpy.run_path("examples/sar_backbone_example.py")
    pipeline = namespace["build_pipeline"]()

    layout = build_layout(pipeline)
    svg = pipeline.to_svg()

    assert "Inside SAR Backbone Block" in svg
    assert 'id="detail-panel-backbone_detail"' in svg
    assert "Neighborhood" in svg
    assert "Cross-Attn" in svg
    assert "Cloud-free Output" in svg
    assert layout.main.nodes["backbone"].order > layout.main.nodes["cloudy_stem"].order


def test_sar_backbone_example_main_writes_real_png(tmp_path) -> None:
    namespace = runpy.run_path("examples/sar_backbone_example.py")
    namespace["main"].__globals__["OUTPUT_DIR"] = tmp_path

    namespace["main"]()

    assert (tmp_path / "sar_backbone_example.svg").read_text(encoding="utf-8").startswith("<svg")
    assert (tmp_path / "sar_backbone_example.png").read_bytes().startswith(PNG_SIGNATURE)


def test_checked_in_docs_assets_use_expected_formats() -> None:
    assert Path("docs/assets/quickstart.svg").read_text(encoding="utf-8").startswith("<svg")
    assert Path("docs/assets/quickstart.png").read_bytes().startswith(PNG_SIGNATURE)
    assert Path("docs/assets/frameplot-hero-soft-retro.png").read_bytes().startswith(PNG_SIGNATURE)
