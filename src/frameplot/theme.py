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
    title_font_family: str = "Inter, 'Geist Sans', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
    title_font_size: float = 16.0
    subtitle_font_size: float = 12.0
    title_font_weight: int = 600
    subtitle_font_weight: int = 400
    outer_margin: float = 40.0
    node_padding_x: float = 20.0
    node_padding_y: float = 16.0
    inter_text_gap: float = 8.0
    rank_gap: float = 110.0
    node_gap: float = 40.0
    component_gap: float = 64.0
    group_padding: float = 24.0
    max_text_width: float = 240.0
    min_node_width: float = 160.0
    min_node_height: float = 80.0
    corner_radius: float = 12.0
    group_corner_radius: float = 16.0
    stroke_width: float = 1.5
    group_stroke_width: float = 1.0
    group_fill_opacity: float = 0.08
    detail_panel_gap: float = 56.0
    detail_panel_padding: float = 24.0
    detail_panel_header_height: float = 36.0
    detail_panel_fill: str = "#FFFFFF"
    detail_panel_stroke: str = "#E2E8F0"
    detail_panel_title_color: str = "#64748B"
    detail_panel_stroke_width: float = 1.0
    detail_panel_fill_opacity: float = 1.0
    detail_panel_corner_radius: float = 20.0
    detail_panel_guide_color: str = "#CBD5E1"
    detail_panel_guide_width: float = 1.5
    arrow_size: float = 6.0
    route_track_gap: float = 20.0
    back_edge_gap: float = 30.0
    self_loop_size: float = 32.0

    @classmethod
    def modern(cls) -> Theme:
        """A clean, professional modern theme with better defaults."""
        return cls(
            background_color="#FFFFFF",
            node_fill="#FAFAFA",
            node_stroke="#D4D4D8",
            node_text_color="#18181B",
            edge_color="#A1A1AA",
            group_stroke="#E4E4E7",
            group_fill="#F4F4F5",
            group_label_color="#71717A",
            title_font_family="Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            corner_radius=8.0,
            stroke_width=1.2,
            group_fill_opacity=0.5,
            rank_gap=80.0,
            node_gap=32.0,
        )

    @classmethod
    def dark(cls) -> Theme:
        """Create a modern deep dark theme."""
        return cls(
            background_color="#09090b",
            node_fill="#18181b",
            node_stroke="#27272a",
            node_text_color="#fafafa",
            edge_color="#52525b",
            group_stroke="#27272a",
            group_fill="#18181b",
            group_label_color="#71717a",
            detail_panel_fill="#09090b",
            detail_panel_stroke="#27272a",
            detail_panel_title_color="#a1a1aa",
            detail_panel_guide_color="#27272a",
            group_fill_opacity=0.4,
        )

    @classmethod
    def blueprint(cls) -> Theme:
        """Create a technical blueprint style theme."""
        return cls(
            background_color="#001C44",
            node_fill="#002D62",
            node_stroke="#0047AB",
            node_text_color="#FFFFFF",
            edge_color="#007FFF",
            group_stroke="#0047AB",
            group_fill="#002D62",
            group_label_color="#B9D9EB",
            detail_panel_fill="#001C44",
            detail_panel_stroke="#0047AB",
            detail_panel_title_color="#B9D9EB",
            detail_panel_guide_color="#0047AB",
            group_fill_opacity=0.2,
        )
