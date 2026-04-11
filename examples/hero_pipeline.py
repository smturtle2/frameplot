from __future__ import annotations

import sys
from pathlib import Path

# Add src to path for direct execution from the repository checkout.
if __package__ is None or __package__ == "":
    repo_root = Path(__file__).resolve().parents[1]
    src_path = repo_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

from frameplot import DetailPanel, Edge, Group, Node, Pipeline, Theme

THEME_HERO_ORDER = ("retro", "pastel", "dark", "cyberpunk", "monochrome")


def build_theme_hero_pipeline(theme: Theme) -> Pipeline:
    return Pipeline(
        nodes=[
            Node("s3_raw", "S3 Bucket", "Raw Data Storage"),
            Node("lambda_trigger", "Lambda", "Event Trigger"),
            Node("pubsub", "Cloud Pub/Sub", "Message Queue"),
            Node("dataflow", "Dataflow", "Stream Processing"),
            Node("bigquery", "BigQuery", "Data Warehouse"),
            Node("bi_tool", "Tableau/Looker", "Analytics Dashboard"),
        ],
        edges=[
            Edge("e1", "s3_raw", "lambda_trigger"),
            Edge("e2", "lambda_trigger", "pubsub"),
            Edge("e3", "pubsub", "dataflow"),
            Edge("e4", "dataflow", "bigquery"),
            Edge("e5", "bigquery", "bi_tool"),
        ],
        groups=[
            Group("aws_group", "AWS Cloud", ["s3_raw", "lambda_trigger"]),
            Group("gcp_group", "GCP Cloud", ["pubsub", "dataflow", "bigquery"]),
        ],
        detail_panel=DetailPanel(
            id="dataflow_detail",
            focus_node_id="dataflow",
            label="Dataflow Internal: Spark Job Pipeline",
            nodes=[
                Node("clean", "Cleaning", "Null check & Type cast"),
                Node("transform", "Transform", "Business Logic"),
                Node("enrich", "Enrichment", "CRM Data Join"),
            ],
            edges=[
                Edge("d_e1", "clean", "transform"),
                Edge("d_e2", "transform", "enrich"),
            ],
        ),
        theme=theme,
    )
