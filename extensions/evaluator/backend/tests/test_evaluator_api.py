"""evaluator 확장 API 통합 검증 — dataset/state/export 라운드트립 + 경로 가드.

TestClient 로 확장 라우터를 직접 구동한다. 라우터 모듈은 운영과 동일하게 파일 경로로
적재(spec_from_file_location)해, 실제 마운트 경로(extensions_loader)와의 회귀를 막는다.
RESULT_DIR 은 tmp_path 로 monkeypatch 한다. dev(non-frozen)라 Origin 가드는 통과.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SESSION = "evaluator-sample-abcd1234"
_TS = "20260614-000000"
_REL = f"result/{_SESSION}/{_TS}/sample.parquet"
_ROUTER_PY = Path(__file__).resolve().parents[1] / "router.py"


def _load_router_module():
    """확장 router.py 를 파일 경로로 적재한다 (운영 로더와 동일 방식)."""
    spec = importlib.util.spec_from_file_location(
        "ext_evaluator_router_test", _ROUTER_PY
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_sample_parquet(path: Path) -> None:
    """item A(rank 1)·B(rank 2), 각 POR/NEW 2행씩 = 8행의 소형 예시."""
    pl.DataFrame(
        {
            "item_id": ["A", "A", "A", "A", "B", "B", "B", "B"],
            "item_desc": ["it is a"] * 4 + ["it is b"] * 4,
            "rank": [1, 1, 1, 1, 2, 2, 2, 2],
            "tkout_time": [
                datetime(2026, 6, 14, 0, 10),
                datetime(2026, 6, 14, 0, 20),
                datetime(2026, 6, 14, 13, 10),
                datetime(2026, 6, 14, 13, 20),
                datetime(2026, 6, 14, 0, 10),
                datetime(2026, 6, 14, 0, 20),
                datetime(2026, 6, 14, 13, 10),
                datetime(2026, 6, 14, 13, 20),
            ],
            "category": ["POR", "POR", "NEW", "NEW", "POR", "POR", "NEW", "NEW"],
            "value": [80, 82, 90, 93, 84, 88, 91, 87],
        }
    ).write_parquet(path)


@pytest.fixture
def ts_dir(tmp_path: Path) -> Path:
    """소스 parquet 이 든 타임스탬프 폴더 (tmp_path/<session>/<ts>)."""
    out = tmp_path / _SESSION / _TS
    out.mkdir(parents=True)
    _make_sample_parquet(out / "sample.parquet")
    return out


@pytest.fixture
def client(tmp_path: Path, ts_dir: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("core.result_store.RESULT_DIR", tmp_path)
    app = FastAPI()
    app.include_router(_load_router_module().get_router())
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /dataset
# ---------------------------------------------------------------------------


def test_dataset_items_sorted_by_rank(client: TestClient) -> None:
    resp = client.get("/api/ext/evaluator/dataset", params={"path": _REL})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["items"] == [
        {"key": "A", "sort": 1, "desc": "it is a"},
        {"key": "B", "sort": 2, "desc": "it is b"},
    ]
    assert data["mapping"]["select"] == "item_id"


def test_dataset_points_are_json_safe(client: TestClient) -> None:
    resp = client.get("/api/ext/evaluator/dataset", params={"path": _REL})
    points = resp.json()["points"]

    assert len(points) == 8
    first = points[0]
    assert set(first) == {"key", "x", "y", "legend"}
    assert isinstance(first["x"], str)  # datetime → 문자열
    assert first["x"].startswith("2026-06-14")
    assert {p["legend"] for p in points} == {"POR", "NEW"}
    assert {p["key"] for p in points} == {"A", "B"}


def test_dataset_desc_optional_when_column_absent(
    client: TestClient, ts_dir: Path
) -> None:
    # desc 컬럼(item_desc)이 없는 parquet 도 큐레이션 진입이 막히지 않고 desc=None 으로 동작.
    pl.DataFrame(
        {
            "item_id": ["A", "B"],
            "rank": [1, 2],
            "tkout_time": [datetime(2026, 6, 14, 0, 10), datetime(2026, 6, 14, 0, 20)],
            "category": ["POR", "NEW"],
            "value": [80, 90],
        }
    ).write_parquet(ts_dir / "nodesc.parquet")

    resp = client.get(
        "/api/ext/evaluator/dataset",
        params={"path": f"result/{_SESSION}/{_TS}/nodesc.parquet"},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert items == [
        {"key": "A", "sort": 1, "desc": None},
        {"key": "B", "sort": 2, "desc": None},
    ]


def test_dataset_missing_column_returns_422(client: TestClient) -> None:
    resp = client.get(
        "/api/ext/evaluator/dataset", params={"path": _REL, "select": "ghost"}
    )
    assert resp.status_code == 422
    assert "ghost" in resp.text


def test_dataset_missing_file_returns_404(client: TestClient) -> None:
    resp = client.get(
        "/api/ext/evaluator/dataset",
        params={"path": f"result/{_SESSION}/{_TS}/ghost.parquet"},
    )
    assert resp.status_code == 404


def test_dataset_rejects_traversal(client: TestClient) -> None:
    resp = client.get(
        "/api/ext/evaluator/dataset", params={"path": "result/../escape.parquet"}
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /sources (소스 추가 picker 카탈로그)
# ---------------------------------------------------------------------------


def test_sources_lists_manifest_parquets(client: TestClient, ts_dir: Path) -> None:
    # 세션 루트 manifest 에 두 parquet 항목 (최신 ts 가 먼저 와야 함).
    manifest = ts_dir.parent / "_artifacts.jsonl"
    later = f"result/{_SESSION}/20260614-010000/more.parquet"
    manifest.write_text(
        json.dumps(
            {"ts": _TS, "path": _REL, "kind": "parquet", "rows": 8, "columns": 6}
        )
        + "\n"
        + json.dumps(
            {"ts": "20260614-010000", "path": later, "kind": "parquet", "rows": 4}
        )
        + "\n",
        encoding="utf-8",
    )

    resp = client.get("/api/ext/evaluator/sources", params={"path": _REL})
    assert resp.status_code == 200, resp.text
    sources = resp.json()["sources"]
    paths = [s["path"] for s in sources]
    assert _REL in paths
    assert later in paths
    # ts 내림차순 — 010000 이 000000 보다 앞.
    assert sources[0]["ts"] == "20260614-010000"
    assert sources[0]["filename"] == "more.parquet"


def test_sources_disk_scan_when_no_manifest(client: TestClient) -> None:
    # manifest 가 없으면 세션 폴더를 직접 스캔해 sample.parquet 를 찾는다.
    resp = client.get("/api/ext/evaluator/sources", params={"path": _REL})
    assert resp.status_code == 200, resp.text
    sources = resp.json()["sources"]
    assert [s["path"] for s in sources] == [_REL]
    assert sources[0]["filename"] == "sample.parquet"


def test_sources_missing_file_returns_404(client: TestClient) -> None:
    resp = client.get(
        "/api/ext/evaluator/sources",
        params={"path": f"result/{_SESSION}/{_TS}/ghost.parquet"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /preview (피커 소스 미리보기)
# ---------------------------------------------------------------------------


def test_preview_returns_head_and_schema(client: TestClient) -> None:
    resp = client.get("/api/ext/evaluator/preview", params={"path": _REL, "rows": 3})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] == 8  # 전체 행 수 (head 와 무관)
    assert body["filename"] == "sample.parquet"
    assert body["head"]["columns"] == [
        "item_id",
        "item_desc",
        "rank",
        "tkout_time",
        "category",
        "value",
    ]
    assert len(body["head"]["rows"]) == 3  # head(3) 만
    # datetime 컬럼은 JSON-safe 문자열로 변환된다.
    ts_idx = body["head"]["columns"].index("tkout_time")
    assert isinstance(body["head"]["rows"][0][ts_idx], str)
    # schema 는 컬럼별 dtype 을 동반.
    assert {c["name"] for c in body["schema"]} == set(body["head"]["columns"])


def test_preview_missing_file_returns_404(client: TestClient) -> None:
    resp = client.get(
        "/api/ext/evaluator/preview",
        params={"path": f"result/{_SESSION}/{_TS}/ghost.parquet"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET/POST /state
# ---------------------------------------------------------------------------


def test_state_default_is_empty(client: TestClient) -> None:
    resp = client.get("/api/ext/evaluator/state", params={"path": _REL})
    assert resp.status_code == 200
    assert resp.json() == {"selected": [], "order": []}


def test_state_save_and_reload_roundtrip(client: TestClient, ts_dir: Path) -> None:
    save = client.post(
        "/api/ext/evaluator/state",
        json={"path": _REL, "selected": ["A"], "order": ["B", "A"]},
    )
    assert save.status_code == 200, save.text
    assert save.json()["path"].endswith("sample.evaluator-state.json")
    assert (ts_dir / "sample.evaluator-state.json").exists()

    reload = client.get("/api/ext/evaluator/state", params={"path": _REL})
    assert reload.json() == {"selected": ["A"], "order": ["B", "A"]}


def test_state_corrupt_sidecar_falls_back_to_empty(
    client: TestClient, ts_dir: Path
) -> None:
    (ts_dir / "sample.evaluator-state.json").write_text("{ broken", encoding="utf-8")
    resp = client.get("/api/ext/evaluator/state", params={"path": _REL})
    assert resp.status_code == 200
    assert resp.json() == {"selected": [], "order": []}


# ---------------------------------------------------------------------------
# POST /export
# ---------------------------------------------------------------------------


def test_export_filters_and_reranks_by_list_order(
    client: TestClient, ts_dir: Path
) -> None:
    # 리스트 순서 B, A → B 가 rank 1, A 가 rank 2 로 재계산된다.
    resp = client.post(
        "/api/ext/evaluator/export", json={"path": _REL, "selected": ["B", "A"]}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["path"].endswith("sample.curated.parquet")
    assert body["rows"] == 8  # A·B 모두 선택 → 전체 행 유지
    assert body["items"] == 2

    curated = pl.read_parquet(ts_dir / "sample.curated.parquet")
    rank_by_item = {
        row["item_id"]: row["rank"]
        for row in curated.select("item_id", "rank").unique().iter_rows(named=True)
    }
    assert rank_by_item == {"B": 1, "A": 2}


def test_export_subset_keeps_only_selected(client: TestClient, ts_dir: Path) -> None:
    resp = client.post(
        "/api/ext/evaluator/export", json={"path": _REL, "selected": ["A"]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"] == 4  # A 의 4행만

    curated = pl.read_parquet(ts_dir / "sample.curated.parquet")
    assert curated["item_id"].unique().to_list() == ["A"]
    assert curated["rank"].unique().to_list() == [1]


def test_export_records_manifest_entry(client: TestClient, ts_dir: Path) -> None:
    client.post("/api/ext/evaluator/export", json={"path": _REL, "selected": ["A"]})

    manifest = ts_dir.parent / "_artifacts.jsonl"
    assert manifest.exists()
    entries = [
        json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()
    ]
    assert len(entries) == 1
    assert entries[0]["kind"] == "parquet"
    assert entries[0]["path"].endswith("sample.curated.parquet")


def test_export_applies_point_exclusions_to_data(
    client: TestClient, ts_dir: Path
) -> None:
    # A 의 0·2번 point(소스 행 순서)를 차트 Filter 로 제외 → 실제 행이 데이터에서 빠진다.
    # A 행 순서: pos0(POR,80) pos1(POR,82) pos2(NEW,90) pos3(NEW,93). [0,2] 제외 → 82·93 만 남음.
    resp = client.post(
        "/api/ext/evaluator/export",
        json={"path": _REL, "selected": ["A", "B"], "excluded": {"A": [0, 2]}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rows"] == 6  # A 2행(제외 후) + B 4행

    curated = pl.read_parquet(ts_dir / "sample.curated.parquet")
    a_values = sorted(curated.filter(pl.col("item_id") == "A")["value"].to_list())
    assert a_values == [82, 93]  # 80·90 은 제외됨
    assert curated.filter(pl.col("item_id") == "B").height == 4  # B 는 그대로


def test_export_all_points_excluded_returns_422(client: TestClient) -> None:
    # 선택은 했지만 Filter 로 전 행을 제외하면 남는 행이 없어 422.
    resp = client.post(
        "/api/ext/evaluator/export",
        json={"path": _REL, "selected": ["A"], "excluded": {"A": [0, 1, 2, 3]}},
    )
    assert resp.status_code == 422


def test_export_empty_selected_returns_422(client: TestClient) -> None:
    resp = client.post("/api/ext/evaluator/export", json={"path": _REL, "selected": []})
    assert resp.status_code == 422
