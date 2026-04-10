from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    repo_root = Path(__file__).resolve().parents[1]
    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

from frameplot import DetailPanel, Edge, Group, Node, Pipeline, Theme


OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def build_pipeline() -> Pipeline:
    theme = Theme(
        background_color="#FFFFFF",
        node_fill="#F8F9F7",
        node_stroke="#5A6773",
        node_text_color="#16202A",
        edge_color="#516273",
        group_stroke="#D8DEE7",
        group_fill="#FBFCFD",
        group_label_color="#64707C",
        title_font_family="IBM Plex Sans, Avenir Next, Helvetica Neue, Helvetica, Arial, sans-serif",
        title_font_size=14.0,
        subtitle_font_size=12.0,
        title_font_weight=650,
        subtitle_font_weight=420,
        node_padding_x=20.0,
        node_padding_y=15.0,
        rank_gap=70.0,
        node_gap=24.0,
        component_gap=46.0,
        group_padding=16.0,
        corner_radius=16.0,
        group_corner_radius=20.0,
        stroke_width=1.4,
        group_stroke_width=1.1,
        group_fill_opacity=0.12,
        detail_panel_gap=48.0,
        detail_panel_padding=24.0,
        detail_panel_header_height=32.0,
        detail_panel_fill="#FFFFFF",
        detail_panel_stroke="#D6DDE4",
        detail_panel_title_color="#5C6772",
        detail_panel_guide_color="#D8DEE4",
        detail_panel_guide_width=1.0,
        route_track_gap=16.0,
        back_edge_gap=24.0,
        min_node_width=160.0,
        min_node_height=56.0,
        max_text_width=208.0,
    )

    nodes = (
        Node("sar_input", "SAR input", fill="#F7F2E7", stroke="#7C6D5A", width=168.0),
        Node("cloudy_input", "Cloudy HSI input", fill="#F7F2E7", stroke="#7C6D5A", width=168.0),
        Node("sar_stem", "SAR stem", "latent z0", fill="#EAF1F8", stroke="#5F7F97", width=184.0),
        Node(
            "cloudy_stem",
            "Cloudy HSI stem",
            "conditioning h",
            fill="#F7EEE8",
            stroke="#8C7262",
            width=184.0,
        ),
        Node(
            "backbone",
            "SAR backbone",
            "N repeated blocks",
            fill="#F4F6F9",
            stroke="#5B6673",
            width=196.0,
        ),
        Node(
            "candidate_decoder",
            "Candidate head",
            "candidate branch",
            fill="#EEF6F0",
            stroke="#63806E",
            width=176.0,
        ),
        Node(
            "mask_decoder",
            "Mask head",
            "mask branch",
            fill="#EEF6F0",
            stroke="#63806E",
            width=176.0,
        ),
        Node(
            "fusion",
            "Fusion",
            "blend cloudy input with candidate using mask m",
            fill="#F8F2E7",
            stroke="#8C745D",
            width=278.0,
        ),
        Node("output", "Cloud-free output", fill="#F3F7F2", stroke="#677368", width=178.0),
    )

    edges = (
        Edge("e1", "sar_input", "sar_stem"),
        Edge("e2", "cloudy_input", "cloudy_stem"),
        Edge("e3", "sar_stem", "backbone"),
        Edge("e4", "cloudy_stem", "backbone", color="#97A1AB", dashed=True),
        Edge("e5", "backbone", "candidate_decoder"),
        Edge("e6", "backbone", "mask_decoder"),
        Edge("e7", "candidate_decoder", "fusion"),
        Edge("e8", "mask_decoder", "fusion"),
        Edge("e9", "fusion", "output"),
    )

    detail_panel = DetailPanel(
        id="backbone-detail",
        focus_node_id="backbone",
        label="Inside SAR backbone block",
        nodes=(
            Node("block_z_prev", "Block state", "z(i-1)", fill="#F6F7F5", stroke="#66717A", width=170.0),
            Node("block_h", "Condition state", "h", fill="#F6F7F5", stroke="#66717A", width=170.0),
            Node(
                "nca",
                "Neighborhood cross-attn",
                "z <- z + NCA(z, h, h)",
                fill="#EAF0F8",
                stroke="#657694",
                width=226.0,
            ),
            Node(
                "local_ffn",
                "Local FFN",
                "FFN(RMSNorm(z))",
                fill="#F8F2E8",
                stroke="#8E7860",
                width=162.0,
            ),
            Node(
                "global_attn",
                "Global self-attention",
                "up(Attn(down(z)))",
                fill="#EAF0F8",
                stroke="#657694",
                width=198.0,
            ),
            Node(
                "global_ffn",
                "Global FFN",
                "FFN(RMSNorm(z))",
                fill="#F8F2E8",
                stroke="#8E7860",
                width=162.0,
            ),
            Node("block_z", "Block output", "z(i)", fill="#F6F7F5", stroke="#66717A", width=170.0),
        ),
        edges=(
            Edge("d1", "block_z_prev", "nca"),
            Edge("d2", "block_h", "nca", color="#97A1AB", dashed=True),
            Edge("d3", "nca", "local_ffn"),
            Edge("d4", "local_ffn", "global_attn"),
            Edge("d5", "global_attn", "global_ffn"),
            Edge("d6", "global_ffn", "block_z"),
        ),
        groups=(
            Group(
                "g_local",
                "local_count",
                ("nca", "local_ffn"),
                ("d3",),
                stroke="#D4DCE6",
                fill="#FAFCFE",
            ),
            Group(
                "g_global",
                "global_count",
                ("global_attn", "global_ffn"),
                ("d5",),
                stroke="#D4DCE6",
                fill="#FAFCFE",
            ),
        ),
    )

    return Pipeline(nodes=nodes, edges=edges, detail_panel=detail_panel, theme=theme)


def main() -> None:
    pipeline = build_pipeline()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    svg_path = OUTPUT_DIR / "sar_backbone_example.svg"
    png_path = OUTPUT_DIR / "sar_backbone_example.png"

    pipeline.save_svg(svg_path)
    pipeline.save_png(png_path)

    print(f"Wrote {svg_path}")
    print(f"Wrote {png_path}")


if __name__ == "__main__":
    main()
