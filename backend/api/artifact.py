"""아티팩트 패널 HTTP 경계 — parquet 미리보기·CSV 변환 + 산출물 폴더 열기.

프론트 ArtifactData 패널이 head(N) 미리보기 테이블을 그리고, 사용자가 전체
데이터를 CSV 로 내려받을 수 있게 한다. 또한 패널 헤더의 '폴더 열기' 버튼이
산출물이 저장된 폴더를 OS 파일 탐색기로 연다. 모든 경로 해석은 core.result_store
의 resolve_result_path (RESULT_DIR 절대 기준 + containment) 로 일원화한다.
"""

from __future__ import annotations

import logging
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from api.deps import require_local_origin
from core.result_store import (
    delete_session_artifacts,
    resolve_result_path,
    session_usage_by_client,
    to_result_relative,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[Depends(require_local_origin)])

_PREVIEW_DEFAULT_ROWS = 10
_PREVIEW_MAX_ROWS = 100


def _resolve_artifact_or_404(path: str) -> Path:
    """'result/...' 경로를 RESULT_DIR 하위로 검증된 절대 Path 로 환원한다.

    preview/csv/reveal 이 같은 해석·404 규약을 공유하는 단일 지점.
    reveal 은 확장자 무관(markdown·spec·이미지 칩 포함)이므로 parquet 제약은
    여기가 아니라 _resolve_parquet 이 얹는다.

    Args:
        path: 칩 payload 가 들고 있는 'result/...' 형식 경로.

    Returns:
        RESULT_DIR 하위로 검증된 절대 Path.

    Raises:
        HTTPException: 경로 해석 실패(404).
    """
    target, error = resolve_result_path(path)
    if error or target is None:
        raise HTTPException(
            status_code=404, detail=error or "산출물을 찾을 수 없습니다."
        )
    return target


def _resolve_parquet(path: str) -> Path:
    """'result/...' 경로를 검증된 parquet 절대 Path 로 환원한다.

    Args:
        path: 데이터 칩 payload 가 들고 있는 'result/...' 형식 경로.

    Returns:
        RESULT_DIR 하위로 검증된 parquet 파일 절대 Path.

    Raises:
        HTTPException: 경로 해석 실패(404) 또는 parquet 이 아닌 파일(400).
    """
    target = _resolve_artifact_or_404(path)
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


class RevealRequest(BaseModel):
    """산출물 폴더 열기 요청 — 칩이 가리키는 'result/...' 경로 한 건."""

    path: Annotated[str, "산출물 파일 경로 (result/...). 그 파일이 든 폴더를 연다."]


def _open_folder(folder: Path) -> None:
    """OS 파일 탐색기에서 폴더를 연다.

    배포 대상은 Windows EXE 이므로 os.startfile 이 정상 경로다. macOS/Linux 분기는
    dev 편의용 폴백이며, 테스트는 이 함수를 monkeypatch 해 실제 탐색기를 띄우지 않는다.

    Args:
        folder: 열 폴더의 절대 Path. 호출자가 RESULT_DIR 하위로 검증 후 전달한다.

    Raises:
        OSError: 탐색기 기동에 실패할 때 (경로 부재·권한 등).
    """
    if sys.platform == "win32":
        os.startfile(str(folder))  # type: ignore[attr-defined]
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(folder)])


@router.post("/artifact/reveal")
async def artifact_reveal(req: RevealRequest) -> dict[str, str]:
    """산출물이 저장된 폴더를 OS 파일 탐색기에서 연다.

    프론트 아티팩트 패널의 '폴더 열기' 버튼 전용. 경로는 칩이 들고 있는 파일
    'result/...' 이며, 그 파일이 속한 타임스탬프 폴더를 연다.
    """
    target = _resolve_artifact_or_404(req.path)

    folder = target if target.is_dir() else target.parent
    try:
        _open_folder(folder)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"폴더 열기 실패: {exc}") from exc

    return {"path": to_result_relative(folder)}


@router.get("/artifact/usage")
async def artifact_usage() -> dict[str, dict[str, int]]:
    """세션(client_id[:8]) → 산출물 총 bytes 맵을 반환한다.

    좌측 사이드바가 세션별 디스크 사용량을 표시하는 데 쓴다. 프론트는 세션 id 의
    앞 8자로 이 맵을 조회한다 (세션 폴더명 접미사와 동일 규약).
    """
    return {"usage": session_usage_by_client()}


@router.delete("/artifact/session")
async def delete_artifact_session(
    client_id: Annotated[str, Query(min_length=1, description="세션 식별자(UUID)")],
) -> dict[str, Any]:
    """client_id 에 속한 모든 산출물 폴더를 삭제한다 (세션 삭제 시 동반 호출).

    대화 히스토리 삭제(DELETE /api/conversation)와 분리된 산출물 정리 경계다.
    """
    removed, freed = delete_session_artifacts(client_id)
    return {"ok": True, "removed_dirs": removed, "freed_bytes": freed}
