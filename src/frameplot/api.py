"""High-level rendering API for frameplot diagrams."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from frameplot.layout import build_layout
from frameplot.model import DetailPanel, Edge, Group, Node
from frameplot.render import render_svg, save_png, svg_to_png_bytes
from frameplot.render.png import DEFAULT_PNG_SCALE
from frameplot.theme import Theme

__all__ = ["Pipeline"]


@dataclass(slots=True)
class Pipeline:
    """Describe and render a pipeline diagram.

    The constructor accepts any iterable of nodes, edges, and groups, then
    normalizes them to tuples for deterministic rendering. Passing `theme=None`
    uses the default :class:`Theme`.
    """

    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    groups: tuple[Group, ...] = ()
    detail_panel: DetailPanel | None = None
    theme: Theme | None = field(default_factory=Theme)

    def __post_init__(self) -> None:
        self.nodes = tuple(self.nodes)
        self.edges = tuple(self.edges)
        self.groups = tuple(self.groups)
        if self.theme is None:
            self.theme = Theme()

    def to_svg(self) -> str:
        """Render the pipeline as an SVG document string."""

        layout = build_layout(self)
        return render_svg(layout, self.theme)

    def save_svg(self, path: str | Path) -> None:
        """Write the rendered SVG document to `path` using UTF-8 encoding."""

        Path(path).write_text(self.to_svg(), encoding="utf-8")

    def to_png_bytes(self, *, scale: float = DEFAULT_PNG_SCALE) -> bytes:
        """Render the pipeline to PNG bytes with CairoSVG.

        Raises:
            RuntimeError: If CairoSVG is not installed in the active environment.
        """

        return svg_to_png_bytes(self.to_svg(), scale=scale)

    def save_png(self, path: str | Path, *, scale: float = DEFAULT_PNG_SCALE) -> None:
        """Render the pipeline to PNG and write it to `path`."""

        save_png(self.to_svg(), path, scale=scale)
