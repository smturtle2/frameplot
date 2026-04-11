from frameplot import Node, Edge, Group, Pipeline, Theme

pipeline = Pipeline(
    nodes=[
        Node("start", "Start"),
        Node("fetch", "Fetch Data"),
        Node("retry", "Retry", "Wait 5s", fill="#FDEFEF", stroke="#C0504D"),
        Node("done", "Done"),
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
    theme=Theme.dark()
)

pipeline.save_svg("docs/assets/quickstart.svg")
pipeline.save_png("docs/assets/quickstart.png")
