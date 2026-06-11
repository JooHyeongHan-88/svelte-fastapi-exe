"""parquet 산출물 미리보기·CSV 변환 라우터 — 데이터 칩 패널 전용.

프론트 ArtifactData 패널이 head(N) 미리보기 테이블을 그리고, 사용자가 전체
데이터를 CSV 로 내려받을 수 있게 한다. 경로 해석은 core.result_store 의
resolve_result_path (RESULT_DIR 절대 기준 + containment) 로 일원화한다.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from api.deps import require_local_origin
from core.result_store import resolve_result_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[Depends(require_local_origin)])

_PREVIEW_DEFAULT_ROWS = 10
_PREVIEW_MAX_ROWS = 100


def _resolve_parquet(path: str) -> Path:
    """'result/...' 경로를 검증된 parquet 절대 Path 로 환원한다.

    Args:
        path: 데이터 칩 payload 가 들고 있는 'result/...' 형식 경로.

    Returns:
        RESULT_DIR 하위로 검증된 parquet 파일 절대 Path.

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


def _cell_to_json(value: Any) -> Any:
    """polars 셀 값을 JSON 직렬화 안전 값으로 변환한다.

    NaN/inf 는 json.dumps 가 비표준 리터럴(NaN)로 내보내 브라우저 JSON.parse 가
    실패하므로 None 으로 강제한다. date/datetime/list 등 비원시 타입은 str().
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return str(value)


@router.get("/artifact/preview")
async def artifact_preview(
    path: Annotated[str, Query(description="parquet 산출물 경로 (result/...)")],
    rows: Annotated[
        int, Query(ge=1, le=_PREVIEW_MAX_ROWS, description="미리보기 행 수")
    ] = _PREVIEW_DEFAULT_ROWS,
) -> dict[str, Any]:
    """parquet head(N) 미리보기 + 메타데이터를 반환한다."""
    target = _resolve_parquet(path)
    try:
        # 전체 로드 없이 행 수만 집계 — 큰 중간 데이터도 메타 조회는 가볍게.
        total_rows = pl.scan_parquet(target).select(pl.len()).collect().item()
        head = pl.read_parquet(target, n_rows=rows)
    except (OSError, pl.exceptions.ComputeError) as exc:
        raise HTTPException(
            status_code=422, detail=f"parquet 읽기 실패: {exc}"
        ) from exc

    return {
        "path": path,
        "filename": target.name,
        "size": target.stat().st_size,
        "total_rows": total_rows,
        "schema": [
            {"name": col, "dtype": str(dtype)} for col, dtype in head.schema.items()
        ],
        "head": {
            "columns": head.columns,
            "rows": [[_cell_to_json(value) for value in row] for row in head.rows()],
        },
    }


@router.get("/artifact/csv")
async def artifact_csv(
    path: Annotated[str, Query(description="parquet 산출물 경로 (result/...)")],
) -> Response:
    """parquet 전체를 CSV 로 변환해 첨부파일 응답으로 반환한다."""
    target = _resolve_parquet(path)
    try:
        csv_text = pl.read_parquet(target).write_csv()
    except (OSError, pl.exceptions.ComputeError) as exc:
        raise HTTPException(
            status_code=422, detail=f"parquet 읽기 실패: {exc}"
        ) from exc

    csv_name = f"{target.stem}.csv"
    # 산출물 파일명에 한글이 올 수 있어 RFC 5987 filename* + ASCII fallback 병기.
    disposition = (
        f"attachment; filename=\"download.csv\"; filename*=UTF-8''{quote(csv_name)}"
    )
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )
