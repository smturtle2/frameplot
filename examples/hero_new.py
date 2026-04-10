from frameplot import Node, Edge, Group, DetailPanel, Theme, Pipeline

def main():
    # 1. 커스텀 테마 설정 (세련된 다크 모드)
    # Slate/Zinc 계열의 다크 테마
    dark_theme = Theme(
        background_color="#09090b",
        node_fill="#18181b",
        node_stroke="#3f3f46",
        node_text_color="#fafafa",
        edge_color="#71717a",
        group_stroke="#52525b",
        group_fill="#27272a",
        group_label_color="#a1a1aa",
        detail_panel_fill="#111113",
        detail_panel_stroke="#3f3f46",
        detail_panel_title_color="#d4d4d8",
        detail_panel_guide_color="#3f3f46",
        # 폰트 및 간격 조정
        title_font_family="Inter, system-ui, sans-serif",
        rank_gap=120.0,
        node_gap=40.0,
        corner_radius=12.0
    )

    # 2. 메인 파이프라인 노드
    nodes = [
        # Cloud A (AWS)
        Node("s3_raw", "S3 Bucket", "Raw Data Storage"),
        Node("lambda_trigger", "Lambda", "Event Trigger"),
        
        # Cloud B (GCP)
        Node("pubsub", "Cloud Pub/Sub", "Message Queue"),
        Node("dataflow", "Dataflow", "Stream Processing"),
        Node("bigquery", "BigQuery", "Data Warehouse"),
        
        # External
        Node("bi_tool", "Tableau/Looker", "Analytics Dashboard")
    ]

    # 3. 메인 파이프라인 엣지
    edges = [
        Edge("e1", "s3_raw", "lambda_trigger"),
        Edge("e2", "lambda_trigger", "pubsub"),
        Edge("e3", "pubsub", "dataflow"),
        Edge("e4", "dataflow", "bigquery"),
        Edge("e5", "bigquery", "bi_tool")
    ]

    # 4. 논리적 영역 분리를 위한 그룹
    groups = [
        Group("aws_group", "AWS Cloud", ["s3_raw", "lambda_trigger"]),
        Group("gcp_group", "GCP Cloud", ["pubsub", "dataflow", "bigquery"])
    ]

    # 5. DetailPanel을 사용한 "Dataflow" 내부 상세 정보
    # Dataflow 노드 내부의 워커와 변환 과정을 상세히 보여줌
    detail = DetailPanel(
        id="dataflow_detail",
        focus_node_id="dataflow",
        label="Dataflow Internal: Spark Job Pipeline",
        nodes=[
            Node("clean", "Cleaning", "Null check & Type cast"),
            Node("transform", "Transform", "Business Logic"),
            Node("enrich", "Enrichment", "CRM Data Join")
        ],
        edges=[
            Edge("d_e1", "clean", "transform"),
            Edge("d_e2", "transform", "enrich")
        ]
    )

    # 6. 파이프라인 생성 및 저장
    pipeline = Pipeline(
        nodes=nodes,
        edges=edges,
        groups=groups,
        detail_panel=detail,
        theme=dark_theme
    )

    # PNG 저장 (docs/assets/frameplot-hero-new.png)
    # 만약 docs/assets 폴더가 없다면 생성이 필요할 수 있으나, 기존 구조에 있음을 확인.
    print("Rendering Multi-cloud Data Pipeline...")
    pipeline.save_png("docs/assets/frameplot-hero-new.png")
    print("Saved to docs/assets/frameplot-hero-new.png")

if __name__ == "__main__":
    main()
