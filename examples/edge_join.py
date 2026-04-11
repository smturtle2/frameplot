from frameplot import Edge, Node, Pipeline, Theme

pipeline = Pipeline(
    nodes=[
        Node("source", "Source", "Primary request"),
        Node("worker", "Worker", "Prepare response"),
        Node("audit", "Audit", "Write side log", fill="#DBEAFE"),
        Node("done", "Done", "Return result", fill="#D9EAD3"),
    ],
    edges=[
        Edge("e1", "source", "worker"),
        Edge("e2", "worker", "done"),
        Edge("e3", "audit", "e2", merge_symbol="+", color="#2563EB"),
    ],
    theme=Theme.soft_retro(),
)

pipeline.save_svg("docs/assets/edge-join.svg")
pipeline.save_png("docs/assets/edge-join.png")
