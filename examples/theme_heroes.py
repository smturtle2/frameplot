from __future__ import annotations

from pathlib import Path

from hero_pipeline import THEME_HEROES, Theme, build_theme_hero_pipeline

ASSET_DIR = Path(__file__).resolve().parents[1] / "docs" / "assets"


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    for hero in THEME_HEROES:
        theme = getattr(Theme.themes, hero.key)()
        pipeline = build_theme_hero_pipeline(theme)
        svg_path = ASSET_DIR / f"frameplot-hero-{hero.slug}.svg"
        png_path = ASSET_DIR / f"frameplot-hero-{hero.slug}.png"

        pipeline.save_svg(svg_path)
        pipeline.save_png(png_path)

        print(f"Wrote {svg_path}")
        print(f"Wrote {png_path}")


if __name__ == "__main__":
    main()
