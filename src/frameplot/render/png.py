from __future__ import annotations

from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def svg_to_png_bytes(svg: str) -> bytes:
    """Convert an SVG string into PNG bytes with CairoSVG."""

    try:
        import cairosvg
    except ImportError as exc:  # pragma: no cover - dependency issue
        raise RuntimeError("CairoSVG is required for PNG export.") from exc
    output = cairosvg.svg2png(bytestring=svg.encode("utf-8"))
    if not output.startswith(PNG_SIGNATURE):
        raise RuntimeError("CairoSVG returned non-PNG bytes.")
    return output


def save_png(svg: str, path: str | Path) -> None:
    """Write PNG bytes generated from `svg` to `path`."""

    output = svg_to_png_bytes(svg)
    Path(path).write_bytes(output)
