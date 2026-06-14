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
from pydantic import BaseModel, ConfigDict, Field

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
    """parquet 컬럼 → 큐레이션 역할 매핑. 미지정 시 예시 데이터 컬럼명을 기본값으로 쓴다.

    역할 구분:
        - 공통(차트 무관): select·sort·legend·desc — 어느 차트 종류든 필요.
        - 차트별(mark 가변): x·y — 차트 종류에 따라 필요 여부가 달라진다.

    legend 는 **다중 컬럼**을 허용한다(Tableau 의 Color 셸프처럼 여러 차원을 합성).
    x/y 는 차트 종류에 따라 비어 있을 수 있으므로(예: histogram 은 x 만, box 는 y 만)
    빈 문자열을 '미매핑'으로 취급해 required_columns 에서 제외한다.

    프론트엔드는 차트별 옵션(mark·집계함수 등)을 같은 매핑 객체에 실어 보낼 수 있으므로
    ``extra="ignore"`` 로 미지의 키를 조용히 흘려보낸다(export 검증을 깨지 않기 위함).
    """

    model_config = ConfigDict(extra="ignore")

    select: Annotated[str, "선택 기준 컬럼(예: item_id)"] = "item_id"
    sort: Annotated[str, "Sort 기준 컬럼(예: rank) — 내보내기 시 정수 재계산 대상"] = (
        "rank"
    )
    x: Annotated[str, "차트 x 기준 컬럼(예: tkout_time) — 차트 종류에 따라 선택적"] = (
        "tkout_time"
    )
    y: Annotated[str, "차트 y 기준 컬럼(예: value) — 차트 종류에 따라 선택적"] = "value"
    legend: Annotated[
        list[str],
        "레전드(시리즈 그룹) 기준 컬럼 목록 — 다중 컬럼 합성 허용(예: category)",
    ] = Field(default_factory=lambda: ["category"])
    # desc 는 선택적 — 데이터에 설명 컬럼이 없을 수 있으므로 required_columns 에서 제외하고
    # 부재 시 desc=None 으로 폴백한다(_resolve_desc_expr).
    desc: Annotated[str, "선택 기준 설명 컬럼(예: item_desc) — 없어도 됨"] = "item_desc"

    def legend_columns(self) -> list[str]:
        """비어 있지 않은 legend 컬럼명 목록 (합성·검증 대상)."""
        return [col for col in self.legend if col]

    def required_columns(self) -> list[str]:
        """반드시 존재해야 하는 컬럼 목록.

        select·sort 는 항상 필수. x·y 는 매핑된(빈 문자열이 아닌) 경우에만 검증한다
        (차트 종류별로 한쪽만 쓰는 경우 대응). legend 는 합성 컬럼들을 모두 포함.
        desc 는 선택적이라 제외.
        """
        cols = [self.select, self.sort]
        if self.x:
            cols.append(self.x)
        if self.y:
            cols.append(self.y)
        cols.extend(self.legend_columns())
        return cols


class CurationState(BaseModel):
    """저장/복원되는 큐레이션 상태 — 선택·순서 + 차트 설정(mark·mapping).

    mark·mapping 은 사용자가 도구 안에서 바꾼 차트 종류·컬럼 매핑을 영속해 재진입 시
    그대로 복원하기 위한 것이다(빈 값이면 번들/쿼리 기본값을 쓴다).
    """

    selected: Annotated[list[str], "최종 선택(체크)된 선택키 목록"] = Field(
        default_factory=list
    )
    order: Annotated[list[str], "사용자가 재정렬한 전체 선택키 순서"] = Field(
        default_factory=list
    )
    mark: Annotated[str, "차트 종류(scatter/line/bar/...) — 빈 값이면 기본값"] = ""
    mapping: Annotated[
        dict[str, Any], "사용자가 변경한 컬럼 매핑 오버라이드 — 빈 dict 면 기본값"
    ] = Field(default_factory=dict)


class StateSaveRequest(BaseModel):
    """POST /state 본문 — 저장할 상태와 대상 parquet 경로."""

    path: Annotated[str, "소스 parquet 경로 (result/...)"]
    selected: Annotated[list[str], "체크된 선택키 목록"] = Field(default_factory=list)
    order: Annotated[list[str], "재정렬된 전체 선택키 순서"] = Field(
        default_factory=list
    )
    mark: Annotated[str, "차트 종류 — 빈 값이면 미저장"] = ""
    mapping: Annotated[dict[str, Any], "컬럼 매핑 오버라이드 — 빈 dict 면 미저장"] = (
        Field(default_factory=dict)
    )


class ExportRequest(BaseModel):
    """POST /export 본문 — 선택키(최종 리스트 순서대로)·컬럼 매핑·차트 Filter 제외."""

    path: Annotated[str, "소스 parquet 경로 (result/...)"]
    selected: Annotated[
        list[str], "내보낼 선택키 목록 — 최종 리스트 순서대로(= 재계산될 rank 순서)"
    ]
    mapping: ColumnMapping = Field(default_factory=ColumnMapping)
    excluded: Annotated[
        dict[str, list[int]],
        "차트 Filter 로 제외한 행 — 선택키별 0-based point 인덱스(소스 행 순서 기준)."
        " 분석용 최종 데이터에서 실제로 행을 제거한다(시각 전용 레전드 설정은 미반영).",
    ] = Field(default_factory=dict)
    note: Annotated[
        str, "사람이 남긴 큐레이션 메모 — 결정 맥락으로 메인 앱 칩 요약에 표시된다."
    ] = ""


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


def _resolve_desc_expr(df: pl.DataFrame, desc_column: str) -> pl.Expr:
    """desc 컬럼 expr 을 만든다 — 컬럼이 없으면 null 리터럴로 폴백한다.

    desc 는 선택적 역할이라 매핑이 비었거나 그 컬럼이 데이터에 없을 수 있다. 그럴 때
    422 로 막지 않고 모든 항목의 desc 를 None 으로 처리해 큐레이션 진입을 보장한다.

    Args:
        df: 소스 DataFrame.
        desc_column: 매핑된 desc 컬럼명(빈 문자열일 수 있음).

    Returns:
        ``desc`` alias 가 붙은 polars Expr (실 컬럼 또는 null 리터럴).
    """
    if desc_column and desc_column in df.columns:
        return pl.col(desc_column).alias("desc")
    return pl.lit(None).alias("desc")


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


def _legend_expr(legend_columns: list[str]) -> pl.Expr:
    """legend 컬럼(들)을 단일 문자열 시리즈 그룹으로 합성하는 expr 을 만든다.

    다중 컬럼이면 ``" | "`` 로 합성해 복합 차원(예: ``POR | XXXX1``)을 만든다.
    컬럼이 하나면 그 값 그대로, 0개면 null(그룹 없음)로 폴백한다.

    Args:
        legend_columns: 비어 있지 않은 legend 컬럼명 목록.

    Returns:
        ``legend`` alias 가 붙은 polars Expr.
    """
    if not legend_columns:
        return pl.lit(None).cast(pl.String).alias("legend")
    parts = [pl.col(col).cast(pl.String) for col in legend_columns]
    if len(parts) == 1:
        return parts[0].alias("legend")
    return pl.concat_str(parts, separator=" | ", ignore_nulls=False).alias("legend")


@router.get("/dataset")
async def get_dataset(
    path: Annotated[str, Query(description="소스 parquet 경로 (result/...)")],
    select: Annotated[str, Query(description="선택 기준 컬럼")] = "item_id",
    sort: Annotated[str, Query(description="Sort 기준 컬럼")] = "rank",
    x: Annotated[
        str, Query(description="차트 x 기준 컬럼(빈 값=미매핑)")
    ] = "tkout_time",
    y: Annotated[str, Query(description="차트 y 기준 컬럼(빈 값=미매핑)")] = "value",
    legend: Annotated[list[str], Query(description="레전드 기준 컬럼(다중 가능)")] = [
        "category"
    ],
    desc: Annotated[str, Query(description="선택 기준 설명 컬럼")] = "item_desc",
) -> dict[str, Any]:
    """소스 parquet → 선택 항목 리스트 + 차트 포인트 + 스키마(JSON)를 반환한다.

    - ``items``: distinct 선택키별 ``{key, sort, desc}`` (sort 오름차순, key 보조정렬).
    - ``points``: ``{key, x, y, legend}`` 전체 행 (프론트가 key 로 필터해 차트 구성).
      x/y 가 미매핑(빈 값)이면 해당 필드는 null. legend 가 다중 컬럼이면 합성 문자열.
    - ``schema``: ``{name, dtype}`` 컬럼 목록 — 프론트 매핑 UI 의 드롭다운 채움용.

    소형 데이터(아이템 수십~수백, 행 수천) 전제로 전체를 1회 내려준다. 차트 종류가
    바뀌어도 포인트는 동일하므로(렌더만 다름) 매핑 컬럼이 바뀔 때만 재요청하면 된다.
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
            _resolve_desc_expr(df, mapping.desc),
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

    # x/y 는 미매핑이면 null 리터럴로 폴백 — 차트 종류에 따라 한쪽만 쓰는 경우 대응.
    x_expr = pl.col(mapping.x).alias("x") if mapping.x else pl.lit(None).alias("x")
    y_expr = pl.col(mapping.y).alias("y") if mapping.y else pl.lit(None).alias("y")
    points_df = df.select(
        pl.col(mapping.select).cast(pl.String).alias("key"),
        x_expr,
        y_expr,
        _legend_expr(mapping.legend_columns()),
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
        "schema": [
            {"name": col, "dtype": str(dtype)} for col, dtype in df.schema.items()
        ],
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
    """큐레이션 상태(선택·순서·차트 설정)를 소스 parquet 옆 사이드카에 저장한다."""
    target = _resolve_parquet_or_404(req.path)
    sidecar = _state_sidecar_path(target)
    state = CurationState(
        selected=req.selected,
        order=req.order,
        mark=req.mark,
        mapping=req.mapping,
    )

    try:
        sidecar.write_text(
            json.dumps(state.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"상태 저장 실패: {exc}") from exc

    return {"ok": True, "path": to_result_relative(sidecar)}


def _apply_point_exclusions(
    df: pl.DataFrame, key_alias: str, excluded: dict[str, list[int]]
) -> pl.DataFrame:
    """차트 Filter 로 제외한 행(선택키별 0-based point 인덱스)을 데이터에서 제거한다.

    프론트의 ``pointsByKey`` 인덱스는 '소스 행 순서로 같은 선택키 내 누적 위치'다. 그와
    정확히 대응하도록 ``__pos__`` 를 키별 행 순번으로 계산한 뒤 anti-join 으로 빼낸다.
    차트 Filter 는 '이 행을 최종 분석 데이터에서 뺀다'는 결정이므로(시각 전용 레전드
    설정과 달리) 메타데이터가 아니라 실제 행을 삭제해 결과 parquet 에 반영한다.

    Args:
        df: ``key_alias`` · ``__pos__`` 컬럼이 부착된 DataFrame.
        key_alias: 선택키 문자열 컬럼명.
        excluded: 선택키 → 제외할 0-based 위치 목록.

    Returns:
        제외가 적용된 DataFrame (보조 컬럼은 호출부가 정리).
    """
    pairs = [(key, pos) for key, positions in excluded.items() for pos in positions]
    if not pairs:
        return df
    drop_df = pl.DataFrame(
        {
            key_alias: [key for key, _ in pairs],
            "__pos__": [int(pos) for _, pos in pairs],
        },
        schema={key_alias: pl.String, "__pos__": pl.Int64},
    )
    return df.join(drop_df, on=[key_alias, "__pos__"], how="anti")


@router.post("/export")
async def export_curated(req: ExportRequest) -> dict[str, Any]:
    """선택 항목만 필터 + 차트 Filter 제외 반영 + [Sort 기준] 재계산 → 새 parquet (내보내기).

    ``selected`` 는 최종 리스트 순서대로의 선택키이며, 그 순서대로 sort 컬럼을 1..N
    정수로 덮어쓴다(같은 선택키의 모든 행이 동일 정수). ``excluded`` 의 행은 분석용
    최종 데이터에서 **실제로 제거**한다(차트 Filter = 데이터 결정). 결과는 소스와 같은
    폴더의 ``<stem>.curated.parquet`` 으로 쓰고 세션 manifest 에 기록한다.
    """
    if not req.selected:
        raise HTTPException(status_code=422, detail="선택된 항목이 없습니다.")

    mapping = req.mapping
    target = _resolve_parquet_or_404(req.path)
    df = _read_parquet(target)
    _require_columns(df, [mapping.select, mapping.sort])

    # 큐레이션 요약 수치 — 사람의 결정을 에이전트가 읽도록 메인 앱 칩에 환류한다.
    # total 은 필터 전 소스의 후보(선택키) 수 = '몇 개 중 몇 개를 골랐는가'의 분모.
    total_items = df.select(pl.col(mapping.select).cast(pl.String)).n_unique()

    # 선택키 문자열 + 키별 행 순번(프론트 pointsByKey 인덱스와 정합)을 부착한다.
    df = df.with_columns(
        pl.col(mapping.select).cast(pl.String).alias("__key__")
    ).with_columns(
        pl.int_range(0, pl.len()).over("__key__").cast(pl.Int64).alias("__pos__")
    )

    # 선택키 → 새 정수 rank. 리스트 순서가 곧 rank 순서.
    rank_map = {key: index + 1 for index, key in enumerate(req.selected)}
    selected_df = df.filter(pl.col("__key__").is_in(req.selected))
    filtered_df = _apply_point_exclusions(selected_df, "__key__", req.excluded)
    curated = (
        filtered_df.with_columns(
            pl.col("__key__")
            .replace_strict(rank_map, return_dtype=pl.Int64)
            .alias(mapping.sort)
        )
        .drop("__key__", "__pos__")
        .sort(mapping.sort)
    )

    if curated.is_empty():
        raise HTTPException(
            status_code=422,
            detail="남는 행이 없습니다 — 선택/Filter 제외를 확인하세요.",
        )

    out = target.with_name(f"{target.stem}{_CURATED_SUFFIX}")
    try:
        curated.write_parquet(out)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"parquet 쓰기 실패: {exc}"
        ) from exc

    _append_session_manifest(out, rows=curated.height, columns=curated.width)

    excluded_rows = sum(len(positions) for positions in req.excluded.values())
    summary = {
        "total": total_items,
        "selected": len(req.selected),
        "dropped": max(0, total_items - len(req.selected)),
        "excluded_rows": excluded_rows,
        "note": req.note,
    }

    return {
        "ok": True,
        "path": to_result_relative(out),
        "filename": out.name,
        "rows": curated.height,
        "columns": curated.width,
        "items": len(req.selected),
        "summary": summary,
    }


def get_router() -> APIRouter:
    """extensions_loader 가 호출하는 라우터 팩토리."""
    return router
