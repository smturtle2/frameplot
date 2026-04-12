import os
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
src_path = repo_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from frameplot import DetailPanel, Edge, Group, Node, Pipeline, Theme

def build_pipeline() -> Pipeline:
    # Keep the main graph at the stage-flow level. The modulation internals live
    # in a detail panel so they do not stretch the primary auto-layout.
    nodes = (
        Node(id="sar", title="SAR Input"),
        Node(id="opt", title="Opt Input"),
        Node(id="conv1", title="1x1 Conv"),
        Node(id="cosine", title="Cosine Similarity"),
        Node(id="refine", title="Refine", subtitle="Conv -> GELU -> Conv -> Sigmoid"),
        Node(id="density", title="Density Map", subtitle="0(맑음) ~ 1(두꺼운)", fill="#E1F5FE"),
        Node(id="feat", title="Input Feature", subtitle="feat"),
        Node(
            id="modulation",
            title="AdaIN-style Modulation",
            subtitle="feat × (1 + γ) + β",
            fill="#E8F5E9",
            width=220,
        ),
        Node(
            id="out",
            title="Output Feature",
            subtitle="맑은(d≈0): 보존\n두꺼운(d≈1): SAR 재구성",
            width=240,
        ),
    )

    edges = (
        Edge(id="e1", source="sar", target="conv1"),
        Edge(id="e2", source="opt", target="conv1"),
        Edge(id="e3", source="conv1", target="cosine"),
        Edge(id="e4", source="cosine", target="refine"),
        Edge(id="e5", source="refine", target="density"),
        Edge(id="e6", source="feat", target="modulation"),
        Edge(id="e7", source="density", target="modulation", dashed=True),
        Edge(id="e8", source="modulation", target="out"),
    )

    groups = (
        Group(
            id="g_density",
            label="Density Estimation",
            node_ids=("sar", "opt", "conv1", "cosine", "refine", "density"),
        ),
    )

    detail_panel = DetailPanel(
        id="modulation_detail",
        focus_node_id="modulation",
        label="Conditioning heads per block",
        nodes=(
            Node(id="panel_feat", title="feat"),
            Node(id="panel_gap_feat", title="GAP (feat)"),
            Node(id="panel_gap_den", title="GAP (density)"),
            Node(id="panel_fusion", title="Add / Concat"),
            Node(id="panel_gamma", title="Linear -> γ", subtitle="zero-init", fill="#FFF3E0"),
            Node(id="panel_beta", title="Linear -> β", subtitle="zero-init", fill="#FFF3E0"),
            Node(
                id="panel_apply",
                title="Apply modulation",
                subtitle="feat × (1 + γ) + β",
                fill="#E8F5E9",
                width=220,
            ),
        ),
        edges=(
            Edge(id="d1", source="panel_feat", target="panel_gap_feat"),
            Edge(id="d2", source="panel_gap_feat", target="panel_fusion"),
            Edge(id="d3", source="panel_gap_den", target="panel_fusion"),
            Edge(id="d4", source="panel_fusion", target="panel_gamma"),
            Edge(id="d5", source="panel_fusion", target="panel_beta"),
            Edge(id="d6", source="panel_feat", target="panel_apply"),
            Edge(id="d7", source="panel_gamma", target="panel_apply", dashed=True),
            Edge(id="d8", source="panel_beta", target="panel_apply", dashed=True),
        ),
        groups=(
            Group(
                id="g_conditioning",
                label="Conditioning stats",
                node_ids=("panel_gap_feat", "panel_gap_den", "panel_fusion", "panel_gamma", "panel_beta"),
            ),
        ),
    )

    return Pipeline(
        nodes=nodes,
        edges=edges,
        groups=groups,
        detail_panel=detail_panel,
        theme=Theme.research(),
    )


def main():
    pipeline = build_pipeline()
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flowchart_logic.png")
    pipeline.save_png(output_path, scale=2.0)
    print(f"Logic flowchart successfully saved to: {output_path}")

if __name__ == "__main__":
    main()
