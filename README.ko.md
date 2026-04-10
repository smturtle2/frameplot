# frameplot

[![PyPI version](https://img.shields.io/pypi/v/frameplot.svg)](https://pypi.org/project/frameplot/)
[![Python versions](https://img.shields.io/pypi/pyversions/frameplot.svg)](https://pypi.org/project/frameplot/)
[![CI](https://github.com/smturtle2/frameplot/actions/workflows/workflow.yml/badge.svg?branch=main)](https://github.com/smturtle2/frameplot/actions/workflows/workflow.yml)
[![License](https://img.shields.io/github/license/smturtle2/frameplot)](https://github.com/smturtle2/frameplot/blob/main/LICENSE)

파이썬 코드로 정의한 파이프라인 그래프를 발표용 SVG와 PNG 다이어그램으로 변환합니다.

[English README](https://github.com/smturtle2/frameplot/blob/main/README.md)

![frameplot hero image](https://raw.githubusercontent.com/smturtle2/frameplot/main/docs/assets/frameplot-hero.png)

`frameplot`은 왼쪽에서 오른쪽으로 흐르는 파이프라인 다이어그램을 깔끔한 기본값으로 렌더링하는 경량 파이썬 라이브러리입니다. 노드, 엣지, 그룹, 그리고 선택적인 detail panel을 파이썬 데이터 구조로 정의한 뒤, 문서용 SVG나 발표 자료용 PNG로 바로 내보낼 수 있습니다.

## 특징

- 아키텍처 다이어그램, 데이터 파이프라인, 모델 개요에 맞는 좌에서 우 레이아웃
- SVG 우선 출력과 CairoSVG 기반 PNG 내보내기
- 요약 노드를 하단 inset 미니 그래프로 확장하는 detail panel 지원
- 타이포그래피, 간격, 색상, 라우팅 기본값을 조정하는 `Theme`
- 단순한 dataclass 기반 입력과 결정적인 렌더링 결과

## 설치

```bash
python -m pip install frameplot
```

PNG 출력은 CairoSVG에 의존하며, 환경에 따라 Cairo 또는 libffi 시스템 패키지가 필요할 수 있습니다.

## 빠른 시작

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

## 공개 API

공식적으로 지원하는 공개 API는 top-level import 기준입니다.

- `Node(id, title, subtitle=None, fill=None, stroke=None, text_color=None, metadata=None, width=None, height=None)`
- `Edge(id, source, target, color=None, dashed=False, metadata=None)`
- `Group(id, label, node_ids, edge_ids=(), stroke=None, fill=None, metadata=None)`
- `DetailPanel(id, focus_node_id, label, nodes, edges, groups=(), stroke=None, fill=None, metadata=None)`
- `Theme(...)`
- `Pipeline(nodes, edges, groups=(), detail_panel=None, theme=None)`

`Pipeline` 메서드:

- `to_svg() -> str`
- `save_svg(path) -> None`
- `to_png_bytes() -> bytes`
- `save_png(path) -> None`

## 고급 예제

상단 hero 이미지는 [`examples/sar_backbone_example.py`](https://github.com/smturtle2/frameplot/blob/main/examples/sar_backbone_example.py)에서 생성한 결과이며, 다음 내용을 포함합니다.

- 커스텀 `Theme`
- 분기되는 decoder head
- 그룹 오버레이
- 요약 노드에 연결된 `DetailPanel`

## 참고 사항

- v0.x에서는 좌에서 우 레이아웃만 지원합니다.
- edge label은 아직 지원하지 않습니다.
- 그룹은 시각적 오버레이이며 레이아웃 제약을 만들지 않습니다.
- detail panel은 메인 플로우 아래쪽의 별도 inset 블록으로 렌더링됩니다.

## 개발

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

배포는 GitHub Actions와 PyPI Trusted Publishing으로 자동화합니다. `pyproject.toml`의 버전을 올린 뒤 `v0.1.0` 같은 태그를 푸시하면 `.github/workflows/workflow.yml`에서 릴리스가 시작됩니다.
