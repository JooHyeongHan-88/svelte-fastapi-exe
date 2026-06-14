"""evaluator 확장 — parquet 큐레이션 툴의 API 라우터.

AI Agent 가 만든 parquet 산출물을 사람이 시각적으로 검토·선별·재정렬해 최종
리포트용 데이터로 만든다. 이 모듈은 ``extensions/`` 컨벤션에 따라 호스트의
extensions_loader 가 파일 경로로 적재하므로, **패키지-상대 import 없이** 호스트가
이미 번들한 절대 import(``core.*``·``api.*``·polars·fastapi)만 사용한다.

엔드포인트(prefix ``/api/ext/evaluator``):

- ``GET  /dataset`` : 소스 parquet → 선택 항목 리스트 + scatter 포인트(JSON)
- ``GET  /state``   : 저장된 큐레이션 상태(선택·순서) 로드
- ``POST /state``   : 큐레이션 상태 저장 (저장하기)
- ``POST /export``  : 선택 항목만 필터 + [Sort 기준] 정수 재계산 → 새 parquet (내보내기)

경로 해석은 전부 ``core.result_store.resolve_result_path`` (RESULT_DIR 절대 기준 +
containment) 로 일원화한다. 보안 포스처는 호스트 Origin 가드를 재사용한다.
"""

import json
import logging
import math
from pathlib import Path
from typing import Annotated, Any

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import require_local_origin
from core.result_store import resolve_result_path, to_result_relative

logger = logging.getLogger(__name__)

# 큐레이션 산출물 명명 규약. 소스 parquet 과 같은 폴더에 형제로 쓴다.
_CURATED_SUFFIX = ".curated.parquet"
_STATE_SUFFIX = ".evaluator-state.json"
# 소스 선택 피커의 미리보기 행 수 (호스트 ArtifactData 패널과 동일 기본값).
_PREVIEW_DEFAULT_ROWS = 10
_PREVIEW_MAX_ROWS = 50
# core.result_store._MANIFEST_FILENAME 과 동일 — 확장이 호스트 private 상수에 의존하지
# 않도록 의도적으로 복제한다(호스트 리팩토링에 격리). 세션 루트에 위치해 채팅
# 에이전트의 산출물 재발견(read_manifest_entries)이 큐레이션 결과도 보게 한다.
_MANIFEST_FILENAME = "_artifacts.jsonl"


# ---------------------------------------------------------------------------
# Pydantic 모델
# ---------------------------------------------------------------------------


class ColumnMapping(BaseModel):
    """parquet 컬럼 → 큐레이션 역할 매핑. 미지정 시 예시 데이터 컬럼명을 기본값으로 쓴다."""

    select: Annotated[str, "선택 기준 컬럼(예: item_id)"] = "item_id"
    sort: Annotated[str, "Sort 기준 컬럼(예: rank) — 내보내기 시 정수 재계산 대상"] = (
        "rank"
    )
    x: Annotated[str, "차트 x 기준 컬럼(예: tkout_time)"] = "tkout_time"
    y: Annotated[str, "차트 y 기준 컬럼(예: value)"] = "value"
    legend: Annotated[str, "레전드 기준 컬럼(예: category)"] = "category"
    desc: Annotated[str, "선택 기준 설명 컬럼(예: item_desc)"] = "item_desc"

    def required_columns(self) -> list[str]:
        """존재해야 하는 컬럼 전체 목록."""
        return [self.select, self.sort, self.x, self.y, self.legend, self.desc]


class CurationState(BaseModel):
    """저장/복원되는 큐레이션 상태 — 선택된 키와 리스트 순서."""

    selected: Annotated[list[str], "최종 선택(체크)된 선택키 목록"] = Field(
        default_factory=list
    )
    order: Annotated[list[str], "사용자가 재정렬한 전체 선택키 순서"] = Field(
        default_factory=list
    )


class StateSaveRequest(BaseModel):
    """POST /state 본문 — 저장할 상태와 대상 parquet 경로."""

    path: Annotated[str, "소스 parquet 경로 (result/...)"]
    selected: Annotated[list[str], "체크된 선택키 목록"] = Field(default_factory=list)
    order: Annotated[list[str], "재정렬된 전체 선택키 순서"] = Field(
        default_factory=list
    )


class ExportRequest(BaseModel):
    """POST /export 본문 — 선택키(최종 리스트 순서대로)와 컬럼 매핑."""

    path: Annotated[str, "소스 parquet 경로 (result/...)"]
    selected: Annotated[
        list[str], "내보낼 선택키 목록 — 최종 리스트 순서대로(= 재계산될 rank 순서)"
    ]
    mapping: ColumnMapping = Field(default_factory=ColumnMapping)


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _cell_to_json(value: Any) -> Any:
    """polars 셀 값을 JSON 직렬화 안전 값으로 변환한다.

    NaN/inf 는 브라우저 JSON.parse 가 실패하므로 None 으로 강제하고, datetime/date/
    list 등 비원시 타입은 str() 한다. (api.artifact._cell_to_json 과 동일 규약 —
    확장 격리를 위해 의도적으로 복제.)
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return str(value)


def _resolve_parquet_or_404(path: str) -> Path:
    """'result/...' 경로를 검증된 parquet 절대 Path 로 환원한다.

    Raises:
        HTTPException: 경로 해석 실패(404) 또는 parquet 이 아닌 파일(400).
    """
    target, error = resolve_result_path(path)
    if error or target is None:
        raise HTTPException(
            status_code=404, detail=error or "산출물을 찾을 수 없습니다."
        )
    if target.suffix.lower() != ".parquet":
        raise HTTPException(
            status_code=400, detail=f"parquet 산출물만 지원합니다: {path!r}"
        )
    return target


def _read_parquet(target: Path) -> pl.DataFrame:
    """parquet 을 전체 로드한다. 읽기 실패는 422 로 회신한다."""
    try:
        return pl.read_parquet(target)
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise HTTPException(
            status_code=422, detail=f"parquet 읽기 실패: {exc}"
        ) from exc


def _require_columns(df: pl.DataFrame, columns: list[str]) -> None:
    """매핑된 컬럼이 모두 존재하는지 확인한다. 누락 시 422.

    Raises:
        HTTPException: 누락 컬럼이 있을 때(422) — 누락 목록을 메시지에 담는다.
    """
    missing = [col for col in columns if col not in df.columns]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"parquet 에 없는 컬럼: {missing} (보유 컬럼: {df.columns})",
        )


def _state_sidecar_path(target: Path) -> Path:
    """소스 parquet 과 같은 폴더의 상태 사이드카 경로."""
    return target.with_name(f"{target.stem}{_STATE_SUFFIX}")


def _append_session_manifest(curated: Path, *, rows: int, columns: int) -> None:
    """큐레이션 산출물을 세션 루트 manifest 에 best-effort 로 기록한다.

    채팅 에이전트의 read_manifest_entries 가 세션 루트(``<session>/_artifacts.jsonl``)
    를 읽으므로, 큐레이션 결과도 다음 턴 산출물 재발견에 보이도록 거기에 append 한다.
    소스 경로가 ``<session>/<ts>/<file>`` 구조라는 전제하에 ``curated.parent.parent``
    가 세션 루트다. 기록 실패는 export 본체를 실패시키지 않는다(best-effort).
    """
    session_root = curated.parent.parent
    manifest = session_root / _MANIFEST_FILENAME
    entry = {
        "ts": curated.parent.name,
        "path": to_result_relative(curated),
        "kind": "parquet",
        "size": curated.stat().st_size,
        "description": "evaluator 큐레이션 산출물",
        "rows": rows,
        "columns": columns,
    }
    try:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("manifest 기록 실패: %s (%s)", manifest, exc)


def _read_manifest_parquets(session_root: Path) -> list[dict[str, Any]]:
    """세션 manifest 에서 parquet 항목만 추려 후보 목록으로 만든다.

    손상된 JSON 라인은 건너뛴다. manifest 가 없으면 빈 리스트.

    Args:
        session_root: 세션 루트 디렉터리 (manifest 의 부모).

    Returns:
        ``{path, filename, rows, columns, ts, description}`` 목록.
    """
    manifest = session_root / _MANIFEST_FILENAME
    if not manifest.exists():
        return []

    out: list[dict[str, Any]] = []
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("manifest 읽기 실패: %s (%s)", manifest, exc)
        return []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # 손상 라인 무시 — 나머지는 살린다.
        path = str(entry.get("path", ""))
        if not path.endswith(".parquet"):
            continue
        out.append(
            {
                "path": path,
                "filename": path.rsplit("/", 1)[-1],
                "rows": entry.get("rows"),
                "columns": entry.get("columns"),
                "ts": entry.get("ts", ""),
                "description": entry.get("description", ""),
            }
        )
    return out


def _scan_session_parquets(session_root: Path) -> list[dict[str, Any]]:
    """manifest 가 없을 때 세션 폴더를 직접 스캔한 parquet 후보 목록 (fallback).

    parquet 메타데이터는 읽지 않는다 (비용 통제 — rows/columns 는 패널 진입 시 확정).

    Args:
        session_root: 세션 루트 디렉터리.

    Returns:
        ``{path, filename, rows, columns, ts, description}`` 목록.
    """
    if not session_root.is_dir():
        return []

    out: list[dict[str, Any]] = []
    for ts_dir in session_root.iterdir():
        if not ts_dir.is_dir():
            continue
        for parquet in ts_dir.glob("*.parquet"):
            out.append(
                {
                    "path": to_result_relative(parquet),
                    "filename": parquet.name,
                    "rows": None,
                    "columns": None,
                    "ts": ts_dir.name,
                    "description": "",
                }
            )
    return out


# ---------------------------------------------------------------------------
# 라우터
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/ext/evaluator",
    dependencies=[Depends(require_local_origin)],
    tags=["ext:evaluator"],
)


@router.get("/dataset")
async def get_dataset(
    path: Annotated[str, Query(description="소스 parquet 경로 (result/...)")],
    select: Annotated[str, Query(description="선택 기준 컬럼")] = "item_id",
    sort: Annotated[str, Query(description="Sort 기준 컬럼")] = "rank",
    x: Annotated[str, Query(description="차트 x 기준 컬럼")] = "tkout_time",
    y: Annotated[str, Query(description="차트 y 기준 컬럼")] = "value",
    legend: Annotated[str, Query(description="레전드 기준 컬럼")] = "category",
    desc: Annotated[str, Query(description="선택 기준 설명 컬럼")] = "item_desc",
) -> dict[str, Any]:
    """소스 parquet → 선택 항목 리스트 + scatter 포인트(JSON)를 반환한다.

    - ``items``: distinct 선택키별 ``{key, sort, desc}`` (sort 오름차순, key 보조정렬).
    - ``points``: ``{key, x, y, legend}`` 전체 행 (프론트가 key 로 필터해 차트 구성).

    소형 데이터(아이템 수십~수백, 행 수천) 전제로 전체를 1회 내려준다.
    """
    mapping = ColumnMapping(
        select=select, sort=sort, x=x, y=y, legend=legend, desc=desc
    )
    target = _resolve_parquet_or_404(path)
    df = _read_parquet(target)
    _require_columns(df, mapping.required_columns())

    items_df = (
        df.select(
            pl.col(mapping.select).cast(pl.String).alias("key"),
            pl.col(mapping.sort).alias("sort"),
            pl.col(mapping.desc).alias("desc"),
        )
        .group_by("key")
        .agg(
            pl.col("sort").min().alias("sort"),
            pl.col("desc").first().alias("desc"),
        )
        .sort("sort", "key")
    )
    items = [
        {"key": key, "sort": _cell_to_json(srt), "desc": _cell_to_json(dsc)}
        for key, srt, dsc in items_df.iter_rows()
    ]

    points_df = df.select(
        pl.col(mapping.select).cast(pl.String).alias("key"),
        pl.col(mapping.x).alias("x"),
        pl.col(mapping.y).alias("y"),
        pl.col(mapping.legend).cast(pl.String).alias("legend"),
    )
    points = [
        {
            "key": key,
            "x": _cell_to_json(px),
            "y": _cell_to_json(py),
            "legend": leg,
        }
        for key, px, py, leg in points_df.iter_rows()
    ]

    return {
        "path": path,
        "mapping": mapping.model_dump(),
        "items": items,
        "points": points,
    }


@router.get("/sources")
async def list_sources(
    path: Annotated[str, Query(description="현재 소스 parquet 경로 (result/...)")],
) -> dict[str, Any]:
    """현재 소스가 속한 세션의 parquet 후보 목록을 반환한다 (소스 추가 picker 용).

    소스 경로가 ``<session>/<ts>/<file>`` 구조라는 전제하에 ``target.parent.parent``
    가 세션 루트다. 세션 manifest(``_artifacts.jsonl``)의 parquet 항목을 최신순으로
    돌려준다. manifest 가 없거나 비면 세션 폴더를 직접 스캔한다 (best-effort fallback).

    Returns:
        ``{"sources": [{path, filename, rows, columns, ts, description}, ...]}``
        경로 기준 중복 제거 · ts 내림차순.
    """
    target = _resolve_parquet_or_404(path)
    session_root = target.parent.parent

    candidates = _read_manifest_parquets(session_root)
    if not candidates:
        candidates = _scan_session_parquets(session_root)

    # 경로 기준 중복 제거(최신 항목 우선) 후 ts 내림차순 정렬.
    by_path: dict[str, dict[str, Any]] = {}
    for entry in candidates:
        by_path.setdefault(entry["path"], entry)
    ordered = sorted(by_path.values(), key=lambda e: str(e.get("ts", "")), reverse=True)
    return {"sources": ordered}


@router.get("/preview")
async def preview_parquet(
    path: Annotated[str, Query(description="미리볼 parquet 경로 (result/...)")],
    rows: Annotated[
        int, Query(ge=1, le=_PREVIEW_MAX_ROWS, description="미리보기 행 수")
    ] = _PREVIEW_DEFAULT_ROWS,
) -> dict[str, Any]:
    """parquet head(N) 미리보기 + 스키마를 반환한다 (소스 선택 판단용).

    호스트 ArtifactData 패널(``/api/artifact/preview``)과 동일한 응답 형태
    (``schema`` + ``head.columns/rows`` + ``total_rows``)로, 피커가 같은 미리보기
    테이블을 그려 사용자가 어떤 소스를 고를지 판단하게 한다. 전체 로드 없이 행 수만
    집계하고 head(N)만 읽어 큰 중간 데이터도 가볍게 미리본다.

    Returns:
        ``{path, filename, total_rows, schema:[{name,dtype}], head:{columns,rows}}``.
    """
    target = _resolve_parquet_or_404(path)
    try:
        total_rows = pl.scan_parquet(target).select(pl.len()).collect().item()
        head = pl.read_parquet(target, n_rows=rows)
    except (OSError, pl.exceptions.PolarsError) as exc:
        raise HTTPException(
            status_code=422, detail=f"parquet 읽기 실패: {exc}"
        ) from exc

    return {
        "path": path,
        "filename": target.name,
        "total_rows": total_rows,
        "schema": [
            {"name": col, "dtype": str(dtype)} for col, dtype in head.schema.items()
        ],
        "head": {
            "columns": head.columns,
            "rows": [[_cell_to_json(value) for value in row] for row in head.rows()],
        },
    }


@router.get("/state")
async def get_state(
    path: Annotated[str, Query(description="소스 parquet 경로 (result/...)")],
) -> dict[str, Any]:
    """저장된 큐레이션 상태(선택·순서)를 로드한다. 없거나 손상 시 빈 상태를 반환한다."""
    target = _resolve_parquet_or_404(path)
    sidecar = _state_sidecar_path(target)

    if not sidecar.exists():
        return CurationState().model_dump()

    try:
        raw = json.loads(sidecar.read_text(encoding="utf-8"))
        return CurationState(**raw).model_dump()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        # 손상된 사이드카는 빈 상태로 폴백 — 큐레이션 진입 자체를 막지 않는다.
        logger.warning("상태 사이드카 읽기 실패: %s (%s)", sidecar, exc)
        return CurationState().model_dump()


@router.post("/state")
async def save_state(req: StateSaveRequest) -> dict[str, Any]:
    """큐레이션 상태(선택·순서)를 소스 parquet 옆 사이드카에 저장한다 (저장하기)."""
    target = _resolve_parquet_or_404(req.path)
    sidecar = _state_sidecar_path(target)
    state = CurationState(selected=req.selected, order=req.order)

    try:
        sidecar.write_text(
            json.dumps(state.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"상태 저장 실패: {exc}") from exc

    return {"ok": True, "path": to_result_relative(sidecar)}


@router.post("/export")
async def export_curated(req: ExportRequest) -> dict[str, Any]:
    """선택 항목만 필터 + [Sort 기준] 정수 재계산 → 새 parquet 으로 저장한다 (내보내기).

    ``selected`` 는 최종 리스트 순서대로의 선택키이며, 그 순서대로 sort 컬럼을 1..N
    정수로 덮어쓴다(같은 선택키의 모든 행이 동일 정수). 결과는 소스와 같은 폴더의
    ``<stem>.curated.parquet`` 으로 쓰고 세션 manifest 에 기록한다.
    """
    if not req.selected:
        raise HTTPException(status_code=422, detail="선택된 항목이 없습니다.")

    mapping = req.mapping
    target = _resolve_parquet_or_404(req.path)
    df = _read_parquet(target)
    _require_columns(df, [mapping.select, mapping.sort])

    # 선택키 → 새 정수 rank. 리스트 순서가 곧 rank 순서.
    rank_map = {key: index + 1 for index, key in enumerate(req.selected)}
    curated = (
        df.with_columns(pl.col(mapping.select).cast(pl.String).alias("__key__"))
        .filter(pl.col("__key__").is_in(req.selected))
        .with_columns(
            pl.col("__key__")
            .replace_strict(rank_map, return_dtype=pl.Int64)
            .alias(mapping.sort)
        )
        .drop("__key__")
        .sort(mapping.sort)
    )

    if curated.is_empty():
        raise HTTPException(
            status_code=422,
            detail="선택키와 일치하는 행이 없습니다 — 매핑/선택을 확인하세요.",
        )

    out = target.with_name(f"{target.stem}{_CURATED_SUFFIX}")
    try:
        curated.write_parquet(out)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"parquet 쓰기 실패: {exc}"
        ) from exc

    _append_session_manifest(out, rows=curated.height, columns=curated.width)

    return {
        "ok": True,
        "path": to_result_relative(out),
        "filename": out.name,
        "rows": curated.height,
        "columns": curated.width,
        "items": len(req.selected),
    }


def get_router() -> APIRouter:
    """extensions_loader 가 호출하는 라우터 팩토리."""
    return router
