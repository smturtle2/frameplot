from __future__ import annotations

import runpy
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from frameplot import DetailPanel, Edge, Group, Node, Pipeline, Theme
from frameplot.layout import build_layout
from frameplot.layout.route import _build_component_geometry, _route_forward
from frameplot.layout.types import LayoutNode
from frameplot.render.png import PNG_SIGNATURE
from frameplot.theme import resolve_theme_metrics

SVG_NS = {"svg": "http://www.w3.org/2000/svg"}


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

    with pytest.raises(ValueError, match="missing target node"):
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


def test_save_svg_writes_file(tmp_path) -> None:
    output = tmp_path / "pipeline.svg"

    build_sample_pipeline().save_svg(output)

    assert output.read_text(encoding="utf-8").startswith("<svg")


def test_png_export_uses_cairosvg(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_svg2png(*, bytestring):
        captured["bytestring"] = bytestring
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
    assert output.read_bytes().startswith(b"\x89PNG")


def test_png_export_rejects_non_png_payloads(monkeypatch) -> None:
    monkeypatch.setitem(
        __import__("sys").modules,
        "cairosvg",
        SimpleNamespace(svg2png=lambda *, bytestring: b"not-a-png"),
    )

    with pytest.raises(RuntimeError, match="non-PNG"):
        build_sample_pipeline().to_png_bytes()


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


def test_svg_serializes_resolved_dash_and_marker_metrics() -> None:
    theme = Theme.presentation()
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
    theme = Theme.presentation()
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

    edge_one = routed["e1"].points
    edge_two = routed["e2"].points

    assert edge_one != edge_two
    assert len(edge_one) <= 4
    assert len(edge_two) <= 4
    assert edge_one[0] == edge_two[0]
    assert edge_two[1].x - edge_two[0].x <= theme.route_track_gap * 2


def test_fanin_routing_uses_short_target_spine() -> None:
    pipeline = Pipeline(
        nodes=[Node("upper", "Upper"), Node("lower", "Lower"), Node("sink", "Sink")],
        edges=[Edge("e1", "upper", "sink"), Edge("e2", "lower", "sink")],
    )

    layout = build_layout(pipeline)
    routed = {edge.edge.id: edge for edge in layout.main.edges}
    theme = Theme()

    edge_one = routed["e1"].points
    edge_two = routed["e2"].points

    assert len(edge_one) <= 4
    assert len(edge_two) <= 4
    assert edge_two[-1] == edge_one[-1]
    assert edge_two[-1].x - edge_two[-2].x <= theme.route_track_gap * 2


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
    assert Path("docs/assets/frameplot-hero-new.png").read_bytes().startswith(PNG_SIGNATURE)
