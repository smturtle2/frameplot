from __future__ import annotations

from pathlib import Path


def svg_to_png_bytes(svg: str) -> bytes:
    """Convert an SVG string into PNG bytes with CairoSVG."""

    try:
        import cairosvg
    except ImportError as exc:  # pragma: no cover - dependency issue
        raise RuntimeError("CairoSVG is required for PNG export.") from exc
    return cairosvg.svg2png(bytestring=svg.encode("utf-8"))


def save_png(svg: str, path: str | Path) -> None:
    """Write PNG bytes generated from `svg` to `path`."""

    output = svg_to_png_bytes(svg)
    Path(path).write_bytes(output)
