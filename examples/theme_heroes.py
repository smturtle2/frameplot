from __future__ import annotations

from pathlib import Path

from hero_pipeline import THEME_HERO_ORDER, Theme, build_theme_hero_pipeline

ASSET_DIR = Path(__file__).resolve().parents[1] / "docs" / "assets"


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    for theme_name in THEME_HERO_ORDER:
        theme = getattr(Theme.themes, theme_name)()
        pipeline = build_theme_hero_pipeline(theme)
        svg_path = ASSET_DIR / f"frameplot-hero-{theme_name}.svg"
        png_path = ASSET_DIR / f"frameplot-hero-{theme_name}.png"

        pipeline.save_svg(svg_path)
        pipeline.save_png(png_path)

        print(f"Wrote {svg_path}")
        print(f"Wrote {png_path}")


if __name__ == "__main__":
    main()
