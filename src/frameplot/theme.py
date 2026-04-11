"""Styling defaults and resolved metrics for frameplot layout and rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ClassVar


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


@dataclass(slots=True, frozen=True)
class ThemeRegistry:
    soft_retro: Callable[[], "Theme"]
    retro: Callable[[], "Theme"]
    pastel: Callable[[], "Theme"]
    dark: Callable[[], "Theme"]
    cyberpunk: Callable[[], "Theme"]
    monochrome: Callable[[], "Theme"]

    def __iter__(self):
        return iter(("soft_retro", "retro", "pastel", "dark", "cyberpunk", "monochrome"))

    def __getitem__(self, name: str) -> Callable[[], "Theme"]:
        return getattr(self, name)


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
    arrow_size: float = 8.0
    route_track_gap: float = 20.0
    back_edge_gap: float = 30.0
    self_loop_size: float = 32.0
    
    # Shadow and effects
    shadow_blur: float = 4.0
    shadow_opacity: float = 0.05
    shadow_offset_y: float = 2.0
    show_group_accent_line: bool = True
    color_palette: tuple[str, ...] | None = None
    themes: ClassVar[ThemeRegistry]

    @classmethod
    def soft_retro(cls) -> 'Theme':
        """A pastel-tinted retro theme with monospace lettering on a white canvas."""
        theme = cls.retro()
        theme.background_color = "#FFFFFF"
        theme.node_fill = "#FAF3E7"
        theme.node_stroke = "#2E2723"
        theme.node_text_color = "#2E2723"
        theme.edge_color = "#2E2723"
        theme.group_stroke = "#2E2723"
        theme.group_fill = "#FFF8F2"
        theme.group_label_color = "#2E2723"
        theme.title_font_family = "'DejaVu Sans Mono', 'IBM Plex Mono', Menlo, Consolas, monospace"
        theme.title_font_weight = 650
        theme.detail_panel_fill = "#FFFDFC"
        theme.detail_panel_stroke = "#2E2723"
        theme.detail_panel_title_color = "#2E2723"
        theme.detail_panel_guide_color = "#D8D0C7"
        theme.detail_panel_fill_opacity = 0.88
        theme.corner_radius = 10.0
        theme.group_corner_radius = 12.0
        theme.detail_panel_corner_radius = 10.0
        theme.shadow_opacity = 0.12
        theme.show_group_accent_line = False
        theme.color_palette = (
            "#F6C8B8", "#F8DCA8", "#CFE8C6", "#BFDCEC", "#D8C9F1",
        )
        return theme

    @classmethod
    def retro(cls) -> 'Theme':
        """A nostalgic ink-and-paper theme on a white canvas."""
        return cls(
            background_color="#FFFFFF",
            node_fill="#F4EBD9",
            node_stroke="#111111",
            node_text_color="#2B1B16",
            edge_color="#111111",
            group_stroke="#111111",
            group_fill="#FFFFFF",
            group_label_color="#2B1B16",
            detail_panel_fill="#FFFFFF",
            detail_panel_stroke="#111111",
            detail_panel_stroke_width=2.5,
            detail_panel_title_color="#2B1B16",
            detail_panel_guide_color="#D1C8B4",
            detail_panel_corner_radius=0.0,
            group_fill_opacity=0.22,
            stroke_width=2.5,
            corner_radius=0.0,
            group_corner_radius=0.0,
            shadow_blur=0.0,
            shadow_opacity=0.16,
            shadow_offset_y=4.0,
            detail_panel_fill_opacity=0.82,
            color_palette=(
                "#D92938", "#F2916D", "#F1D194", "#3B5145", "#243A2E",
            )
        )

    @classmethod
    def dark(cls) -> 'Theme':
        """A white-canvas editorial slate theme with rounded cards and depth."""
        return cls(
            background_color="#FFFFFF",
            node_fill="#FFFFFF",
            node_stroke="#171A26",
            node_text_color="#0F172A",
            edge_color="#2C3540",
            group_stroke="#425059",
            group_fill="#171A26",
            group_label_color="#171A26",
            title_font_family="'DejaVu Serif', Georgia, 'Times New Roman', serif",
            title_font_weight=650,
            subtitle_font_weight=450,
            detail_panel_fill="#F7F9FB",
            detail_panel_stroke="#425059",
            detail_panel_title_color="#171A26",
            detail_panel_guide_color="#808C8B",
            detail_panel_fill_opacity=0.96,
            detail_panel_stroke_width=1.5,
            detail_panel_corner_radius=18.0,
            group_fill_opacity=0.07,
            stroke_width=1.75,
            group_stroke_width=1.25,
            corner_radius=16.0,
            group_corner_radius=22.0,
            shadow_blur=12.0,
            shadow_opacity=0.09,
            shadow_offset_y=5.0,
            show_group_accent_line=False,
            color_palette=(
                "#171A26", "#2C3540", "#425059", "#657371", "#808C8B",
            ),
        )

    @classmethod
    def cyberpunk(cls) -> 'Theme':
        """A white-canvas techno theme with sharp geometry and hard contrast."""
        return cls(
            background_color="#FFFFFF",
            node_fill="#FFFFFF",
            node_stroke="#171A26",
            node_text_color="#0F172A",
            edge_color="#F25E5E",
            group_stroke="#4A79D9",
            group_fill="#B6F2F2",
            group_label_color="#F25E5E",
            title_font_family="'DejaVu Sans Mono', 'IBM Plex Mono', Menlo, Consolas, monospace",
            title_font_weight=700,
            subtitle_font_size=11.5,
            subtitle_font_weight=500,
            detail_panel_fill="#F8FFFF",
            detail_panel_stroke="#F25E5E",
            detail_panel_stroke_width=2.5,
            detail_panel_title_color="#4A79D9",
            detail_panel_guide_color="#F2B56B",
            detail_panel_fill_opacity=0.94,
            detail_panel_corner_radius=0.0,
            group_fill_opacity=0.06,
            stroke_width=2.25,
            group_stroke_width=1.75,
            corner_radius=0.0,
            group_corner_radius=0.0,
            shadow_blur=0.0,
            shadow_opacity=0.0,
            shadow_offset_y=0.0,
            show_group_accent_line=False,
            color_palette=(
                "#4A79D9", "#B6F2F2", "#F2B56B", "#F27A5E", "#F25E5E",
            ),
        )

    @classmethod
    def pastel(cls) -> 'Theme':
        """A white-canvas soft editorial theme with pill shapes and airy shadows."""
        return cls(
            background_color="#FFFFFF",
            node_fill="#FFFFFF",
            node_stroke="#D8A7B5",
            node_text_color="#5A5568",
            edge_color="#8FB7CC",
            group_stroke="#D8A7B5",
            group_fill="#FFFFFF",
            group_label_color="#8A7188",
            title_font_family="'DejaVu Sans', 'Trebuchet MS', 'Segoe UI', sans-serif",
            title_font_weight=650,
            subtitle_font_weight=500,
            detail_panel_fill="#FFFCFB",
            detail_panel_stroke="#CFE3EC",
            detail_panel_title_color="#8A7188",
            detail_panel_guide_color="#E9F3F7",
            detail_panel_fill_opacity=0.98,
            detail_panel_corner_radius=32.0,
            group_fill_opacity=0.94,
            stroke_width=1.25,
            group_stroke_width=1.1,
            corner_radius=28.0,
            group_corner_radius=32.0,
            shadow_blur=8.0,
            shadow_opacity=0.07,
            shadow_offset_y=4.0,
            show_group_accent_line=False,
            color_palette=(
                "#A8E6CF", "#DCEDC1", "#FFE8D4", "#FFAAA5", "#FF8BA6",
            ),
        )

    @classmethod
    def monochrome(cls) -> 'Theme':
        """A crisp blueprint-like monochrome theme with restrained technical lines."""
        return cls(
            background_color="#FFFFFF",
            node_fill="#FFFFFF",
            node_stroke="#3C4A73",
            node_text_color="#111111",
            edge_color="#576BA6",
            group_stroke="#8890A6",
            group_fill="#576BA6",
            group_label_color="#3C4A73",
            title_font_family="'DejaVu Sans Mono', Menlo, Consolas, monospace",
            title_font_weight=600,
            subtitle_font_size=11.5,
            detail_panel_fill="#FAFBFF",
            detail_panel_stroke="#8890A6",
            detail_panel_title_color="#3C4A73",
            detail_panel_guide_color="#C8D3F3",
            detail_panel_fill_opacity=0.98,
            detail_panel_stroke_width=1.5,
            detail_panel_corner_radius=8.0,
            group_fill_opacity=0.1,
            stroke_width=1.25,
            group_stroke_width=1.35,
            corner_radius=8.0,
            group_corner_radius=12.0,
            shadow_blur=0.0,
            shadow_opacity=0.0,
            shadow_offset_y=0.0,
            show_group_accent_line=False,
            color_palette=(
                "#4A4E59", "#8890A6", "#3C4A73", "#576BA6", "#C8D3F3",
            ),
        )
Theme.themes = ThemeRegistry(
    soft_retro=Theme.soft_retro,
    retro=Theme.retro,
    pastel=Theme.pastel,
    dark=Theme.dark,
    cyberpunk=Theme.cyberpunk,
    monochrome=Theme.monochrome,
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
