"""Styling defaults and resolved metrics for frameplot layout and rendering."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class FilterShadowLayer:
    blur: float
    offset_y: float
    opacity: float


@dataclass(slots=True, frozen=True)
class PaintShadowLayer:
    offset_y: float
    spread: float
    opacity: float


@dataclass(slots=True, frozen=True)
class ResolvedThemeMetrics:
    title_char_width_ratio: float
    subtitle_char_width_ratio: float
    line_height_ratio: float
    title_baseline_ratio: float
    subtitle_baseline_ratio: float
    subtitle_opacity: float
    group_dasharray: tuple[float, float]
    edge_dasharray: tuple[float, float]
    group_label_padding: float
    group_label_baseline_offset: float
    detail_panel_title_baseline_offset: float
    accent_line_inset_start: float
    accent_line_length: float
    accent_line_width: float
    shadow_filter_margin_percent: float
    filter_shadow_layers: tuple[FilterShadowLayer, ...]
    paint_shadow_layers: tuple[PaintShadowLayer, ...]
    marker_viewbox_size: float
    marker_ref_x: float
    marker_ref_y: float
    marker_width: float
    marker_height: float
    marker_tip_x: float
    marker_tip_y: float
    marker_body_inset_y: float
    marker_opacity: float
    compact_rank_gap: float
    short_stub_extent: float
    guide_anchor_ratio: float
    guide_shoulder_inset_cap: float
    guide_shoulder_inset_ratio: float
    guide_flare_ratio: float
    guide_flare_min_factor: float
    guide_bend_ratio: float
    guide_min_bend_drop: float


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
    rank_gap: float = 72.0
    node_gap: float = 32.0
    component_gap: float = 48.0
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
    
    # Shadow and effects
    shadow_blur: float = 4.0
    shadow_opacity: float = 0.05
    shadow_offset_y: float = 2.0
    show_group_accent_line: bool = True
    color_palette: tuple[str, ...] | None = None

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
            corner_radius=10.0,
            stroke_width=1.2,
            group_fill_opacity=0.5,
            rank_gap=80.0,
            node_gap=32.0,
            shadow_blur=8.0,
            shadow_opacity=0.04,
            shadow_offset_y=3.0,
            show_group_accent_line=False,
        )

    @classmethod
    def presentation(cls) -> Theme:
        """High contrast, clean lines, maximum readability for presentations."""
        return cls(
            background_color="#FFFFFF",
            node_fill="#FFFFFF",
            node_stroke="#CBD5E1",
            node_text_color="#0F172A",
            edge_color="#94A3B8",
            group_stroke="#E2E8F0",
            group_fill="#F8FAFC",
            group_label_color="#64748B",
            title_font_family="Inter, -apple-system, 'SF Pro Display', system-ui, sans-serif",
            title_font_size=16.0,
            subtitle_font_size=13.0,
            title_font_weight=700,
            subtitle_font_weight=500,
            corner_radius=12.0,
            group_corner_radius=20.0,
            stroke_width=1.5,
            group_stroke_width=1.0,
            group_fill_opacity=1.0,
            rank_gap=80.0,
            node_gap=32.0,
            shadow_blur=12.0,
            shadow_opacity=0.08,
            shadow_offset_y=6.0,
            show_group_accent_line=False,
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


    @classmethod
    def pastel(cls) -> 'Theme':
        """A soft, calming pastel theme with rounded shapes and crisp white borders."""
        return cls(
            background_color="transparent",
            node_fill="#FCE7F3",
            node_stroke="#FFFFFF",
            node_text_color="#57534E",
            edge_color="#A8A29E",
            group_stroke="#E5E7EB",
            group_fill="#F3F4F6",
            group_label_color="#9CA3AF",
            detail_panel_fill="#FAFAF9",
            detail_panel_stroke="#FFFFFF",
            detail_panel_title_color="#A8A29E",
            detail_panel_guide_color="#E5E7EB",
            group_fill_opacity=0.4,
            stroke_width=4.0,
            corner_radius=16.0,
            group_corner_radius=24.0,
            shadow_blur=6.0,
            shadow_opacity=0.15,
            shadow_offset_y=10.0,
            color_palette=(
                "#FEE2E2", "#FFEDD5", "#FEF3C7", "#ECFCCB",
                "#D1FAE5", "#CCFBF1", "#E0F2FE", "#E0E7FF",
                "#F3E8FF", "#FAE8FF", "#FCE7F3"
            ),
        )

    @classmethod
    def glass(cls) -> 'Theme':
        """Clean modern glassmorphism simulating frosted surfaces."""
        return cls(
            background_color="transparent",
            node_fill="rgba(255, 255, 255, 0.65)",
            node_stroke="rgba(255, 255, 255, 0.95)",
            node_text_color="#1E293B",
            edge_color="#94A3B8",
            group_stroke="rgba(255, 255, 255, 0.5)",
            group_fill="rgba(241, 245, 249, 0.4)",
            group_label_color="#64748B",
            detail_panel_fill="rgba(255, 255, 255, 0.85)",
            detail_panel_stroke="rgba(255, 255, 255, 0.95)",
            detail_panel_title_color="#1E293B",
            detail_panel_guide_color="rgba(148, 163, 184, 0.4)",
            group_fill_opacity=1.0,
            stroke_width=2.0,
            corner_radius=16.0,
            group_corner_radius=24.0,
            shadow_blur=24.0,
            shadow_opacity=0.1,
            shadow_offset_y=8.0,
            color_palette=(),
        )


    @classmethod
    def retro(cls) -> 'Theme':
        """A nostalgic retro theme with warm, vintage colors and strong borders."""
        return cls(
            background_color="transparent",
            node_fill="#F4EBD9",
            node_stroke="#111111",
            node_text_color="#111111",
            edge_color="#111111",
            group_stroke="#111111",
            group_fill="#E8E1CD",
            group_label_color="#111111",
            detail_panel_fill="#FAF8F5",
            detail_panel_stroke="#111111",
            detail_panel_title_color="#111111",
            detail_panel_guide_color="#D1C8B4",
            group_fill_opacity=0.6,
            stroke_width=2.5,
            corner_radius=0.0,
            group_corner_radius=0.0,
            shadow_blur=0.0,
            shadow_opacity=1.0,
            shadow_offset_y=6.0,
            color_palette=(
                "#FF6B6B", "#FCA5A5", "#FDE047", "#86EFAC",
                "#93C5FD", "#A78BFA", "#F472B6", "#FDBA74"
            )
        )

    @classmethod
    def ocean(cls) -> 'Theme':
        """A light, airy oceanic theme with soft cyan and seafoam tones."""
        return cls(
            background_color="transparent",
            node_fill="#E0F2FE",
            node_stroke="#0284C7",
            node_text_color="#0C4A6E",
            edge_color="#38BDF8",
            group_stroke="#7DD3FC",
            group_fill="#F0F9FF",
            group_label_color="#0369A1",
            detail_panel_fill="#FFFFFF",
            detail_panel_stroke="#7DD3FC",
            detail_panel_title_color="#0C4A6E",
            detail_panel_guide_color="#BAE6FD",
            group_fill_opacity=0.5,
            stroke_width=2.0,
            corner_radius=12.0,
            group_corner_radius=20.0,
            shadow_blur=8.0,
            shadow_opacity=0.1,
            shadow_offset_y=4.0,
            color_palette=(
                "#E0F2FE", "#BAE6FD", "#7DD3FC", "#38BDF8",
                "#0EA5E9", "#0284C7", "#0369A1", "#075985"
            )
        )

def resolve_theme_metrics(theme: Theme) -> ResolvedThemeMetrics:
    """Resolve derived metrics so layout and rendering share the same ratios."""

    group_dash_on = max(theme.group_stroke_width * 6.0, theme.group_padding * 0.25)
    group_dash_off = max(theme.group_stroke_width * 4.0, group_dash_on * 0.66)
    edge_dash_on = max(theme.stroke_width * 5.0, theme.route_track_gap * 0.4)
    edge_dash_off = max(theme.stroke_width * 4.0, theme.route_track_gap * 0.3)

    marker_viewbox_size = max(theme.arrow_size * 1.67, theme.arrow_size * 1.25)
    marker_tip_x = marker_viewbox_size * 0.9
    marker_tip_y = marker_viewbox_size * 0.5
    marker_body_inset_y = marker_viewbox_size * 0.15
    compact_rank_gap = max(
        theme.route_track_gap,
        theme.arrow_size * 1.75,
        theme.stroke_width * 4.0,
        theme.corner_radius * 0.75,
    )
    short_stub_extent = max(
        theme.arrow_size * 1.25,
        theme.stroke_width * 3.0,
        compact_rank_gap * 0.5,
    )

    return ResolvedThemeMetrics(
        title_char_width_ratio=0.6,
        subtitle_char_width_ratio=0.56,
        line_height_ratio=1.25,
        title_baseline_ratio=0.76,
        subtitle_baseline_ratio=0.76,
        subtitle_opacity=0.85,
        group_dasharray=(round(group_dash_on, 2), round(group_dash_off, 2)),
        edge_dasharray=(round(edge_dash_on, 2), round(edge_dash_off, 2)),
        group_label_padding=round(theme.subtitle_font_size + theme.node_padding_y, 2),
        group_label_baseline_offset=round(
            theme.subtitle_font_size + max(theme.node_padding_y * 0.35, theme.group_padding * 0.2),
            2,
        ),
        detail_panel_title_baseline_offset=round(
            theme.subtitle_font_size
            + max(theme.detail_panel_padding * 0.35, theme.detail_panel_header_height * 0.22),
            2,
        ),
        accent_line_inset_start=round(max(theme.group_padding * 0.4, theme.group_corner_radius * 0.5), 2),
        accent_line_length=round(max(theme.group_padding * 2.1, theme.min_node_width * 0.28), 2),
        accent_line_width=round(max(theme.group_stroke_width * 2.5, theme.group_stroke_width + theme.stroke_width), 2),
        shadow_filter_margin_percent=20.0,
        filter_shadow_layers=(
            FilterShadowLayer(
                blur=round(theme.shadow_blur, 2),
                offset_y=round(theme.shadow_offset_y * 1.5, 2),
                opacity=round(theme.shadow_opacity * 0.6, 4),
            ),
            FilterShadowLayer(
                blur=round(max(theme.shadow_blur * 0.3, theme.stroke_width * 0.6), 2),
                offset_y=round(max(theme.shadow_offset_y * 0.4, theme.stroke_width * 0.4), 2),
                opacity=round(theme.shadow_opacity * 1.2, 4),
            ),
        ),
        paint_shadow_layers=(
            PaintShadowLayer(offset_y=round(theme.shadow_offset_y * 1.0, 2), spread=round(theme.shadow_blur * 1.0, 2), opacity=round(theme.shadow_opacity * 0.05, 4)),
            PaintShadowLayer(offset_y=round(theme.shadow_offset_y * 0.8, 2), spread=round(theme.shadow_blur * 0.8, 2), opacity=round(theme.shadow_opacity * 0.1, 4)),
            PaintShadowLayer(offset_y=round(theme.shadow_offset_y * 0.6, 2), spread=round(theme.shadow_blur * 0.6, 2), opacity=round(theme.shadow_opacity * 0.2, 4)),
            PaintShadowLayer(offset_y=round(theme.shadow_offset_y * 0.4, 2), spread=round(theme.shadow_blur * 0.4, 2), opacity=round(theme.shadow_opacity * 0.3, 4)),
            PaintShadowLayer(offset_y=round(theme.shadow_offset_y * 0.2, 2), spread=round(theme.shadow_blur * 0.2, 2), opacity=round(theme.shadow_opacity * 0.35, 4)),
            PaintShadowLayer(offset_y=round(theme.shadow_offset_y * 0.0, 2), spread=round(theme.shadow_blur * 0.0, 2), opacity=round(theme.shadow_opacity * 0.4, 4)),
        ),
        marker_viewbox_size=round(marker_viewbox_size, 2),
        marker_ref_x=round(marker_tip_x, 2),
        marker_ref_y=round(marker_tip_y, 2),
        marker_width=round(theme.arrow_size, 2),
        marker_height=round(theme.arrow_size, 2),
        marker_tip_x=round(marker_tip_x, 2),
        marker_tip_y=round(marker_tip_y, 2),
        marker_body_inset_y=round(marker_body_inset_y, 2),
        marker_opacity=0.9,
        compact_rank_gap=round(compact_rank_gap, 2),
        short_stub_extent=round(short_stub_extent, 2),
        guide_anchor_ratio=0.2,
        guide_shoulder_inset_cap=round(max(theme.detail_panel_padding * 1.5, theme.group_padding * 1.6), 2),
        guide_shoulder_inset_ratio=0.18,
        guide_flare_ratio=0.18,
        guide_flare_min_factor=1.5,
        guide_bend_ratio=0.45,
        guide_min_bend_drop=round(
            max(theme.subtitle_font_size * 1.4, theme.detail_panel_guide_width * 12.0),
            2,
        ),
    )
