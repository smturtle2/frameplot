from frameplot import Edge, Group, Node, Pipeline, Theme

pipeline = Pipeline(
    nodes=[
        Node("start", "Start", "Receive request"),
        Node("fetch", "Fetch Data", "Load source tables"),
        Node("retry", "Retry", "Loop on transient failure", fill="#FFF2CC"),
        Node("done", "Done", "Return result", fill="#D9EAD3"),
    ],
    edges=[
        Edge("e1", "start", "fetch"),
        Edge("e2", "fetch", "retry", dashed=True),
        Edge("e3", "retry", "fetch", color="#C0504D"),
        Edge("e4", "fetch", "done"),
    ],
    groups=[
        Group("g1", "Execution", ["start", "fetch", "retry"], edge_ids=["e2"]),
    ],
    theme=Theme.pastel()
)

pipeline.save_svg("docs/assets/quickstart.svg")
pipeline.save_png("docs/assets/quickstart.png")
