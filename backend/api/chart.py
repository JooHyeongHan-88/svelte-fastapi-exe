"""display_chart 인터랙티브 필터 라우터 — brush 선택 행 제외 + undo/redo/reset.

프론트 라이트박스가 brush 로 선택한 원본 parquet 행 인덱스를 받아, 보존된 spec+parquet
으로 차트를 재집계 렌더한다. 필터 상태는 ``charts.filter.json`` 에 영속하고 ``charts.json``
을 덮어써 세션 재진입/새로고침 후에도 동일 상태로 복원된다.

Filter All 은 brush 한 차트와 동일 ``data.source`` 를 공유하는 모든 차트(히스토그램·
박스플롯 등 집계 차트 포함)를 같은 제외 행으로 재집계한다.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from agent.charts import chart_filter_store as filter_store
from agent.charts.chart_renderer import render_spec_to_echarts, resolve_legend_row_ids
from agent.charts.chart_spec import ChartSpecV1
from agent.tools.visualize import resolve_spec_path
from api.deps import require_local_origin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[Depends(require_local_origin)])

# 산출물 파일(charts.filter.json / charts.json) 쓰기 직렬화. 단일 사용자라 충돌은
# 드물지만 undo 연타 등 빠른 연속 요청의 read-modify-write 경합을 막는다.
_write_lock = threading.Lock()


class ChartFilterRequest(BaseModel):
    """뷰 상태 액션 요청 (필터 + 레전드 통합).

    action 별로 사용하는 필드가 다르다:
        exclude        → scope / chart_index / row_ids
        exclude_legend → scope / chart_index / legend_values
        set_legend     → scope / chart_index / order / colors / hidden
        undo/redo/reset → 없음
    """

    spec: Annotated[str, "save_artifact 가 반환한 charts.spec.json 경로 (result/...)"]
    action: Annotated[
        Literal["exclude", "exclude_legend", "set_legend", "undo", "redo", "reset"],
        "수행할 뷰 상태 액션",
    ]
    scope: Annotated[
        Literal["single", "all"], "적용 범위 — 단일 차트 / 동일 데이터 전체"
    ] = "single"
    chart_index: Annotated[int, "동작이 일어난 차트 인덱스"] = 0
    row_ids: Annotated[list[int], "제외할 원본 parquet 행 인덱스 (exclude 시)"] = Field(
        default_factory=list
    )
    legend_values: Annotated[
        list[str], "제외할 레전드 이름 리스트 (exclude_legend 시)"
    ] = Field(default_factory=list)
    order: Annotated[list[str] | None, "레전드 표시 순서 (set_legend 시)"] = None
    colors: Annotated[
        dict[str, str] | None, "레전드 색상 오버라이드 {name: hex} (set_legend 시)"
    ] = None
    hidden: Annotated[list[str] | None, "숨길 레전드 이름 리스트 (set_legend 시)"] = (
        None
    )


@router.post("/chart/filter")
async def chart_filter(req: ChartFilterRequest) -> dict[str, Any]:
    """필터 액션을 적용해 재렌더된 차트 목록 + undo/redo 가용성을 반환한다."""
    spec_path, spec = _load_spec(req.spec)
    base_dir = spec_path.parent
    chart_sources = [chart.data.source for chart in spec.charts]

    with _write_lock:
        state = filter_store.load(base_dir)
        state = _apply_action(state, req, spec, base_dir, chart_sources)
        filter_store.save(base_dir, state)

        try:
            items = render_spec_to_echarts(
                spec,
                base_dir,
                exclude_by_chart=state.current_exclude(),
                legend_by_chart=state.current_legend(),
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"렌더 실패: {exc}") from exc

        _overwrite_rendered(spec_path, items)

    return {"items": items, "can_undo": state.can_undo, "can_redo": state.can_redo}


@router.get("/chart/filter-state")
async def chart_filter_state(
    spec: Annotated[str, Query(description="charts.spec.json 경로 (result/...)")],
) -> dict[str, bool]:
    """라이트박스 오픈 시 undo/redo 버튼 초기 상태 복원용 — 재렌더 없이 가용성만."""
    spec_path, error = resolve_spec_path(spec)
    if error or spec_path is None:
        raise HTTPException(status_code=400, detail=error or "invalid spec path")
    state = filter_store.load(spec_path.parent)
    return {"can_undo": state.can_undo, "can_redo": state.can_redo}


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _load_spec(source: str) -> tuple[Path, ChartSpecV1]:
    """source 경로 검증 + spec 파싱. 실패 시 400 HTTPException."""
    spec_path, error = resolve_spec_path(source)
    if error or spec_path is None:
        raise HTTPException(status_code=400, detail=error or "invalid spec path")

    try:
        raw_spec = json.loads(spec_path.read_text(encoding="utf-8"))
        spec = ChartSpecV1.model_validate(raw_spec)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"spec 읽기 실패: {exc}") from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=400, detail=f"spec 검증 실패: {exc.error_count()} 건"
        ) from exc

    return spec_path, spec


def _apply_action(
    state: filter_store.FilterState,
    req: ChartFilterRequest,
    spec: ChartSpecV1,
    base_dir: Path,
    chart_sources: list[str],
) -> filter_store.FilterState:
    """action 분기. 선택/변경이 비어 있으면 no-op."""
    if req.action == "exclude":
        if not req.row_ids:
            return state
        return filter_store.apply_exclude(
            state, req.chart_index, req.row_ids, req.scope, chart_sources
        )
    if req.action == "exclude_legend":
        if not req.legend_values or not (0 <= req.chart_index < len(spec.charts)):
            return state
        # 레전드 이름 → 원본 행 인덱스로 환원해 기존 exclude 메커니즘으로 funnel.
        row_ids = resolve_legend_row_ids(
            spec.charts[req.chart_index], base_dir, req.legend_values
        )
        if not row_ids:
            return state
        return filter_store.apply_exclude(
            state, req.chart_index, row_ids, req.scope, chart_sources
        )
    if req.action == "set_legend":
        return filter_store.apply_legend(
            state,
            req.chart_index,
            order=req.order,
            colors=req.colors,
            hidden=req.hidden,
            scope=req.scope,
            chart_sources=chart_sources,
        )
    if req.action == "undo":
        return filter_store.undo(state)
    if req.action == "redo":
        return filter_store.redo(state)
    return filter_store.reset(state)


def _overwrite_rendered(spec_path: Path, items: list[dict[str, Any]]) -> None:
    """현재 필터 상태의 렌더 결과로 charts.json 을 덮어쓴다 (재진입 일관성)."""
    rendered_path = spec_path.with_name(spec_path.name.replace(".spec.json", ".json"))
    rendered_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
