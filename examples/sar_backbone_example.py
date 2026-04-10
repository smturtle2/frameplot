from __future__ import annotations

import sys
from pathlib import Path

# Add src to path for direct execution
if __package__ is None or __package__ == "":
    repo_root = Path(__file__).resolve().parents[1]
    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

from frameplot import DetailPanel, Edge, Group, Node, Pipeline, Theme

OUTPUT_DIR = Path(__file__).resolve().parent / "output"

def build_pipeline() -> Pipeline:
    """Build a SAR backbone architecture diagram."""
    # Define nodes for the main pipeline
    nodes = (
        Node("sar_input", "SAR Input", width=160),
        Node("cloudy_input", "Cloudy HSI Input", width=160),
        Node("sar_stem", "SAR Stem", "Latent z0", width=180),
        Node("cloudy_stem", "Cloudy HSI Stem", "Conditioning h", width=180),
        Node("backbone", "SAR Backbone", "N-repeated Blocks", width=200),
        Node("candidate_head", "Candidate Head", "Candidate Branch", width=180),
        Node("mask_head", "Mask Head", "Mask Branch", width=180),
        Node(
            "fusion",
            "Fusion Layer",
            "Blend with Mask m",
            width=180,
        ),
        Node("output", "Cloud-free Output", width=180),
    )

    # Define connectivity
    edges = (
        Edge("e1", "sar_input", "sar_stem"),
        Edge("e2", "cloudy_input", "cloudy_stem"),
        Edge("e3", "sar_stem", "backbone"),
        Edge("e4", "cloudy_stem", "backbone", dashed=True),
        Edge("e5", "backbone", "candidate_head"),
        Edge("e6", "backbone", "mask_head"),
        Edge("e7", "candidate_head", "fusion"),
        Edge("e8", "mask_head", "fusion"),
        Edge("e9", "fusion", "output"),
    )

    # Define internal structure of the backbone
    detail_panel = DetailPanel(
        id="backbone_detail",
        focus_node_id="backbone",
        label="Inside SAR Backbone Block",
        nodes=(
            Node("block_z_prev", "Input State", "z(i-1)", width=160),
            Node("block_h", "Condition", "h", width=160),
            Node("nca", "Neighborhood Cross-Attn", "z + NCA(z, h, h)", width=220),
            Node("local_ffn", "Local FFN", "FFN(RMSNorm(z))", width=180),
            Node("global_attn", "Global Attention", "Up(Attn(Down(z)))", width=200),
            Node("global_ffn", "Global FFN", "FFN(RMSNorm(z))", width=180),
            Node("block_z", "Output State", "z(i)", width=160),
        ),
        edges=(
            Edge("d1", "block_z_prev", "nca"),
            Edge("d2", "block_h", "nca", dashed=True),
            Edge("d3", "nca", "local_ffn"),
            Edge("d4", "local_ffn", "global_attn"),
            Edge("d5", "global_attn", "global_ffn"),
            Edge("d6", "global_ffn", "block_z"),
        ),
        groups=(
            Group("g_local", "Local Processing", ("nca", "local_ffn")),
            Group("g_global", "Global Processing", ("global_attn", "global_ffn")),
        ),
    )

    return Pipeline(
        nodes=nodes,
        edges=edges,
        detail_panel=detail_panel,
        theme=Theme.modern()
    )

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
