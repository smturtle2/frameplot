# frameplot

[![PyPI version](https://img.shields.io/pypi/v/frameplot.svg)](https://pypi.org/project/frameplot/)
[![Python versions](https://img.shields.io/pypi/pyversions/frameplot.svg)](https://pypi.org/project/frameplot/)
[![CI](https://github.com/smturtle2/frameplot/actions/workflows/workflow.yml/badge.svg?branch=main)](https://github.com/smturtle2/frameplot/actions/workflows/workflow.yml)
[![License](https://img.shields.io/github/license/smturtle2/frameplot)](https://github.com/smturtle2/frameplot/blob/main/LICENSE)

Turn Python-defined pipeline graphs into presentation-ready SVG and PNG diagrams.

[한국어 README](https://github.com/smturtle2/frameplot/blob/main/README.ko.md)

![frameplot hero image](https://raw.githubusercontent.com/smturtle2/frameplot/main/docs/assets/frameplot-hero.png)

`frameplot` is a compact Python library for rendering left-to-right pipeline diagrams with clean defaults. Define nodes, edges, groups, and optional detail panels in plain Python, then export polished SVG for documentation or PNG for slides and papers.

## Why frameplot?

- Clean left-to-right layout for architecture diagrams, data pipelines, and model overviews
- SVG-first output with optional PNG export through CairoSVG
- Detail panels for expanding a summary node into a lower inset mini-graph
- Themeable typography, spacing, colors, and routing defaults
- Deterministic rendering from simple dataclass-based inputs

## Install

```bash
python -m pip install frameplot
```

PNG export depends on CairoSVG and may require Cairo or libffi packages from the host OS.

## Quickstart

```python
from frameplot import Edge, Group, Node, Pipeline

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
)

svg = pipeline.to_svg()
pipeline.save_svg("pipeline.svg")
pipeline.save_png("pipeline.png")
```

## Public API

Top-level imports are the supported public API:

- `Node(id, title, subtitle=None, fill=None, stroke=None, text_color=None, metadata=None, width=None, height=None)`
- `Edge(id, source, target, color=None, dashed=False, metadata=None)`
- `Group(id, label, node_ids, edge_ids=(), stroke=None, fill=None, metadata=None)`
- `DetailPanel(id, focus_node_id, label, nodes, edges, groups=(), stroke=None, fill=None, metadata=None)`
- `Theme(...)`
- `Pipeline(nodes, edges, groups=(), detail_panel=None, theme=None)`

`Pipeline` exposes:

- `to_svg() -> str`
- `save_svg(path) -> None`
- `to_png_bytes() -> bytes`
- `save_png(path) -> None`

## Advanced Example

The hero image above is generated from [`examples/sar_backbone_example.py`](https://github.com/smturtle2/frameplot/blob/main/examples/sar_backbone_example.py), which demonstrates:

- custom `Theme` values
- split decoder branches
- grouped overlays
- a `DetailPanel` attached to a summary node

## Design Notes

- Layout is intentionally left-to-right in v0.x.
- Edge labels are not supported yet.
- Groups are visual overlays and do not constrain layout.
- Detail panels render as separate lower insets attached to a focus node in the main flow.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

Release publishing is automated through GitHub Actions and PyPI Trusted Publishing. Bump the version in `pyproject.toml`, create a tag like `v0.1.0`, and push the tag to trigger a release from `.github/workflows/workflow.yml`.
