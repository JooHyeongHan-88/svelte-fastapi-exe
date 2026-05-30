"""/api/chart/filter 엔드포인트 통합 검증 — exclude/legend 액션 + 영속 라운드트립.

TestClient 로 라우터를 직접 구동해 요청 모델·_apply_action 분기·render·filter_store
저장이 HTTP 경계에서 올바르게 엮이는지 확인한다. dev(non-frozen)라 origin 가드는 통과.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.chart import router as chart_router

# group A=rows0,1 / B=2,3 / C=4,5 — color 채널로 A/B/C 시리즈가 생긴다.
_SPEC = {
    "version": "1",
    "charts": [
        {
            "mark": "ecdf",
            "title": "그룹 누적분포",
            "data": {"source": "grouped.parquet"},
            "encoding": {
                "x": {"field": "value", "type": "quantitative"},
                "color": {"field": "group", "type": "nominal"},
            },
        }
    ],
}

_SPEC_SOURCE = "result/sess/ts/charts.spec.json"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """tmp_path 를 RESULT_DIR 로 둔 채 spec+parquet 산출물을 만들고 클라이언트 반환."""
    monkeypatch.setattr("agent.tools.visualize.RESULT_DIR", tmp_path)

    out_dir = tmp_path / "sess" / "ts"
    out_dir.mkdir(parents=True)
    pl.DataFrame(
        {
            "group": ["A", "A", "B", "B", "C", "C"],
            "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }
    ).write_parquet(out_dir / "grouped.parquet")
    (out_dir / "charts.spec.json").write_text(json.dumps(_SPEC), encoding="utf-8")

    app = FastAPI()
    app.include_router(chart_router)
    return TestClient(app)


def _post(client: TestClient, **body) -> dict:
    resp = client.post("/api/chart/filter", json={"spec": _SPEC_SOURCE, **body})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_set_legend_order_reorders_and_persists(client: TestClient) -> None:
    data = _post(client, action="set_legend", order=["C", "A", "B"])
    assert data["items"][0]["option"]["legend"]["data"] == ["C", "A", "B"]
    assert data["can_undo"] is True


def test_set_legend_colors_inject(client: TestClient) -> None:
    data = _post(client, action="set_legend", colors={"A": "#ff0000"})
    series = data["items"][0]["option"]["series"]
    a_line = next(s for s in series if s["name"] == "A" and s["type"] == "line")
    assert a_line["itemStyle"]["color"] == "#ff0000"


def test_set_legend_hidden_sets_selected(client: TestClient) -> None:
    data = _post(client, action="set_legend", hidden=["B"])
    selected = data["items"][0]["option"]["legend"]["selected"]
    assert selected["B"] is False
    assert selected["A"] is True


def test_exclude_legend_removes_group_rows(client: TestClient) -> None:
    # B 그룹(값 3,4) 제외 → ecdf 표본 n=4 로 재집계.
    data = _post(client, action="exclude_legend", legend_values=["B"])
    line = data["items"][0]["option"]["series"][0]
    xs = [pt[0] for pt in line["data"]]
    assert 3.0 not in xs and 4.0 not in xs
    assert data["can_undo"] is True


def test_undo_reverts_last_action(client: TestClient) -> None:
    _post(client, action="set_legend", colors={"A": "#ff0000"})
    data = _post(client, action="undo")
    series = data["items"][0]["option"]["series"]
    a_line = next(s for s in series if s["name"] == "A" and s["type"] == "line")
    assert "color" not in a_line.get("itemStyle", {})
    assert data["can_undo"] is False
    assert data["can_redo"] is True


def test_filter_state_persisted_across_requests(
    client: TestClient, tmp_path: Path
) -> None:
    _post(client, action="set_legend", order=["B", "A", "C"], hidden=["C"])
    # 사이드카가 산출물 폴더에 영속됐는지 확인.
    sidecar = tmp_path / "sess" / "ts" / "charts.filter.json"
    assert sidecar.exists()
    raw = json.loads(sidecar.read_text(encoding="utf-8"))
    assert raw["version"] == 2
    top = raw["stack"][raw["cursor"]]["legend"]["0"]
    assert top["order"] == ["B", "A", "C"]
    assert top["hidden"] == ["C"]
