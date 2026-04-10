"""Styling defaults for frameplot layout and rendering."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Theme:
    """Control colors, typography, spacing, and routing defaults.

    A theme applies global defaults to the whole diagram. Per-node, per-edge,
    per-group, and per-detail-panel overrides still win when provided.
    """

    background_color: str = "#FFFFFF"
    node_fill: str = "#F8FAFC"
    node_stroke: str = "#0F172A"
    node_text_color: str = "#0F172A"
    edge_color: str = "#334155"
    group_stroke: str = "#94A3B8"
    group_fill: str = "#E2E8F0"
    group_label_color: str = "#475569"
    title_font_family: str = "DejaVu Sans, Arial, sans-serif"
    title_font_size: float = 16.0
    subtitle_font_size: float = 12.0
    title_font_weight: int = 600
    subtitle_font_weight: int = 400
    outer_margin: float = 32.0
    node_padding_x: float = 18.0
    node_padding_y: float = 14.0
    inter_text_gap: float = 8.0
    rank_gap: float = 96.0
    node_gap: float = 32.0
    component_gap: float = 64.0
    group_padding: float = 18.0
    max_text_width: float = 220.0
    min_node_width: float = 140.0
    min_node_height: float = 72.0
    corner_radius: float = 16.0
    group_corner_radius: float = 20.0
    stroke_width: float = 2.0
    group_stroke_width: float = 1.5
    group_fill_opacity: float = 0.14
    detail_panel_gap: float = 48.0
    detail_panel_padding: float = 20.0
    detail_panel_header_height: float = 30.0
    detail_panel_fill: str = "#FFFFFF"
    detail_panel_stroke: str = "#CBD5E1"
    detail_panel_title_color: str = "#475569"
    detail_panel_stroke_width: float = 1.2
    detail_panel_fill_opacity: float = 1.0
    detail_panel_corner_radius: float = 18.0
    detail_panel_guide_color: str = "#CBD5E1"
    detail_panel_guide_width: float = 1.2
    arrow_size: float = 8.0
    route_track_gap: float = 18.0
    back_edge_gap: float = 26.0
    self_loop_size: float = 28.0
