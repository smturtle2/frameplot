from __future__ import annotations

import math
import textwrap

from frameplot.layout.types import MeasuredText, ValidatedPipeline


TITLE_CHAR_WIDTH = 0.58
SUBTITLE_CHAR_WIDTH = 0.54
LINE_HEIGHT_RATIO = 1.25


def measure_text(validated: ValidatedPipeline) -> dict[str, MeasuredText]:
    theme = validated.theme
    title_char_limit = max(10, int(theme.max_text_width / (theme.title_font_size * TITLE_CHAR_WIDTH)))
    subtitle_char_limit = max(
        10, int(theme.max_text_width / (theme.subtitle_font_size * SUBTITLE_CHAR_WIDTH))
    )
    measurements: dict[str, MeasuredText] = {}

    for node in validated.nodes:
        title_lines = tuple(_wrap(node.title, title_char_limit))
        subtitle_lines = tuple(_wrap(node.subtitle, subtitle_char_limit)) if node.subtitle else ()

        title_width = _max_line_width(title_lines, theme.title_font_size, TITLE_CHAR_WIDTH)
        subtitle_width = _max_line_width(
            subtitle_lines, theme.subtitle_font_size, SUBTITLE_CHAR_WIDTH
        )
        text_width = max(title_width, subtitle_width, theme.min_node_width - theme.node_padding_x * 2)

        title_line_height = theme.title_font_size * LINE_HEIGHT_RATIO
        subtitle_line_height = theme.subtitle_font_size * LINE_HEIGHT_RATIO

        content_height = len(title_lines) * title_line_height
        if subtitle_lines:
            content_height += theme.inter_text_gap + len(subtitle_lines) * subtitle_line_height

        auto_width = theme.node_padding_x * 2 + text_width
        auto_height = theme.node_padding_y * 2 + content_height

        width = max(node.width or 0.0, auto_width, theme.min_node_width)
        height = max(node.height or 0.0, auto_height, theme.min_node_height)

        measurements[node.id] = MeasuredText(
            title_lines=title_lines,
            subtitle_lines=subtitle_lines,
            title_line_height=title_line_height,
            subtitle_line_height=subtitle_line_height,
            content_height=content_height,
            width=round(width, 2),
            height=round(height, 2),
        )

    return measurements


def _wrap(value: str | None, width: int) -> list[str]:
    if not value:
        return []
    wrapped = textwrap.wrap(
        value,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        drop_whitespace=True,
    )
    return wrapped or [value]


def _max_line_width(lines: tuple[str, ...], font_size: float, ratio: float) -> float:
    if not lines:
        return 0.0
    return math.ceil(max(len(line) for line in lines) * font_size * ratio)
