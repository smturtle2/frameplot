from pathlib import Path

from frameplot import DetailPanel, Edge, Group, Node, Pipeline, Theme

ROOT = Path(__file__).resolve().parent
PNG_PATH = ROOT / "example_pipeline.png"
SVG_PATH = ROOT / "example_pipeline.svg"

# Palette
INPUT_FILL = "#F8FAFC"
INPUT_STROKE = "#475569"

SPLIT_FILL = "#FFFBEB"
SPLIT_STROKE = "#D97706"

H_FILL = "#ECFDF5"
H_STROKE = "#059669"

C_FILL = "#F0F9FF"
C_STROKE = "#0284C7"

M_FILL = "#FFF1F2"
M_STROKE = "#E11D48"

FUSION_FILL = "#F5F3FF"
FUSION_STROKE = "#7C3AED"

OUTPUT_FILL = "#F1F5F9"
OUTPUT_STROKE = "#334155"


def build_theme() -> Theme:
    theme = Theme.research()
    theme.title_font_family = "'Pretendard', 'Inter', sans-serif"
    theme.title_font_size = 22.0
    theme.subtitle_font_size = 16.0
    theme.background_color = "#FFFFFF"
    
    theme.corner_radius = 12.0
    theme.stroke_width = 1.8
    theme.shadow_opacity = 0.05
    theme.edge_color = "#64748B"
    theme.show_group_accent_line = False
    theme.route_track_gap = 24.0
    theme.rank_gap = 60.0
    theme.node_gap = 40.0
    return theme


def build_pipeline() -> Pipeline:
    theme = build_theme()

    # Re-adding feature_split to Main Pipeline so the structure makes logical sense horizontally
    nodes = (
        Node("sar_input", "SAR Encoder", fill=INPUT_FILL, stroke=INPUT_STROKE),
        Node("hsi_input", "HSI Encoder", fill=INPUT_FILL, stroke=INPUT_STROKE),
        Node("feature_split", "Feature Split", fill=SPLIT_FILL, stroke=SPLIT_STROKE),
        Node("h_feature", "HSI Feature", fill=H_FILL, stroke=H_STROKE),
        Node(
            "main_blocks",
            "Main Processing",
            "N x Dual-Stream Blocks",
            fill="#F8FAFC",
            stroke="#64748B",
            width=280.0,
        ),
        Node("candidate_decoder", "Candidate Decoder", fill=C_FILL, stroke=C_STROKE),
        Node("mask_decoder", "Mask Decoder", fill=M_FILL, stroke=M_STROKE),
        Node(
            "fusion",
            "Masked Blending",
            fill=FUSION_FILL,
            stroke=FUSION_STROKE,
        ),
        Node("output", "Cloud-free Output", fill=OUTPUT_FILL, stroke=OUTPUT_STROKE),
    )

    edges = (
        Edge("sar_to_split", "sar_input", "feature_split"),
        Edge("hsi_to_h", "hsi_input", "h_feature"),
        
        Edge("split_to_main_c", "feature_split", "main_blocks", color=C_STROKE, metadata={"label": "c"}),
        Edge("split_to_main_m", "feature_split", "main_blocks", color=M_STROKE, dashed=True, metadata={"label": "m"}),
        Edge("h_to_main", "h_feature", "main_blocks", color=H_STROKE, dashed=True, metadata={"label": "guidance"}),
        
        Edge("main_to_candidate", "main_blocks", "candidate_decoder", color=C_STROKE),
        Edge("main_to_mask", "main_blocks", "mask_decoder", color=M_STROKE),
        
        Edge("candidate_to_fusion", "candidate_decoder", "fusion", color=C_STROKE),
        Edge("mask_to_fusion", "mask_decoder", "fusion", color=M_STROKE),
        
        Edge("skip_to_fusion", "hsi_input", "fusion", color="#94A3B8", dashed=True, metadata={"label": "skip"}),
        Edge("fusion_to_output", "fusion", "output", color=OUTPUT_STROKE),
    )

    detail_panel = DetailPanel(
        id="main_blocks_panel",
        focus_node_id="main_blocks",
        label="Inside Dual-Stream Block",
        nodes=(
            Node("panel_h", "HSI Feature", fill=H_FILL, stroke=H_STROKE),
            Node("panel_local_c", "Local Context Block", "NCA + L-FFN", fill=C_FILL, stroke=C_STROKE),
            Node("panel_local_m", "Local Context Block", "NCA + L-FFN", fill=M_FILL, stroke=M_STROKE),
            Node("panel_global_c", "Global Context Block", "GSA + G-FFN", fill=C_FILL, stroke=C_STROKE),
            Node("panel_global_m", "Global Context Block", "GSA + G-FFN", fill=M_FILL, stroke=M_STROKE),
        ),
        edges=(
            Edge("panel_h_to_local_c", "panel_h", "panel_local_c", color=H_STROKE, dashed=True),
            Edge("panel_h_to_local_m", "panel_h", "panel_local_m", color=H_STROKE, dashed=True),
            Edge("panel_local_to_global_c", "panel_local_c", "panel_global_c", color=C_STROKE),
            Edge("panel_local_to_global_m", "panel_local_m", "panel_global_m", color=M_STROKE),
        ),
        # Groups implicitly force Dagre layout to maintain strict horizontal "Rows" (행)
        groups=(
            Group("panel_c_group", "Candidate", ("panel_local_c", "panel_global_c"), fill=C_FILL, stroke=C_STROKE),
            Group("panel_m_group", "Mask", ("panel_local_m", "panel_global_m"), fill=M_FILL, stroke=M_STROKE),
        ),
    )

    return Pipeline(
        nodes=nodes,
        edges=edges,
        detail_panel=detail_panel,
        theme=theme,
    )

if __name__ == "__main__":
    pipeline = build_pipeline()
    pipeline.save_svg(SVG_PATH)
    pipeline.save_png(PNG_PATH, scale=2.0)
    print("Fixed layout generated.")
