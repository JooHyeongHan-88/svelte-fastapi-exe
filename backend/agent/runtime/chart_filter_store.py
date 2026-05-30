"""``charts.filter.json`` 사이드카 — display_chart 인터랙티브 뷰 상태의 undo/redo 스택.

산출물 폴더(parquet/spec 과 동일 폴더)에 영속되는 뷰 상태의 단일 진실 공급원이다.
FastAPI/harness 에 비의존하는 순수 로직 — 단독 테스트 가능.

뷰 상태는 두 축으로 구성된다:
    - exclude : brush 선택·레전드 Filter 로 제외된 원본 parquet 행 (데이터 제거 → 재집계).
    - legend  : 레전드 순서·색상·Hide 오버라이드 (시각적, 재집계 없음).

스택 모델:
    각 스냅샷은 "그 시점의 **절대** 뷰 상태"(델타 아님)라 undo/redo 는 cursor 이동만으로
    끝난다. 필터(exclude)와 레전드(legend)를 **하나의 스택**에 통합해, Undo 버튼 하나가
    동작 종류와 무관하게 마지막 변경을 되감는다(UX 일관성).

    cursor 가 가리키는 스냅샷이 현재 상태다. 새 변경/리셋은 redo tail 을 잘라내고
    새 절대 스냅샷을 push 한다. reset 은 빈 스냅샷을 push 하므로 undo 로 복구 가능.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_FILTER_FILENAME = "charts.filter.json"
_VERSION = 2  # v1: exclude 만. v2: exclude + legend 통합.

# 차트 인덱스(str) → 제외할 원본 parquet 행 인덱스(정렬).
ExcludeMap = dict[str, list[int]]
# 차트 인덱스(str) → {"order": [name], "colors": {name: hex}, "hidden": [name]}.
LegendMap = dict[str, dict]
Scope = Literal["single", "all"]


@dataclass
class ViewSnapshot:
    """한 시점의 절대 뷰 상태 (exclude + legend)."""

    exclude: ExcludeMap = field(default_factory=dict)
    legend: LegendMap = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"exclude": self.exclude, "legend": self.legend}


@dataclass
class FilterState:
    """뷰 상태 undo/redo 스택과 현재 cursor.

    이름은 하위호환을 위해 ``FilterState`` 로 유지하지만 exclude·legend 를 함께 담는다.
    """

    cursor: int = 0
    stack: list[ViewSnapshot] = field(default_factory=lambda: [ViewSnapshot()])

    def current(self) -> ViewSnapshot:
        """cursor 가 가리키는 현재 스냅샷."""
        return self.stack[self.cursor]

    def current_exclude(self) -> ExcludeMap:
        """현재 절대 제외 집합."""
        return self.current().exclude

    def current_legend(self) -> LegendMap:
        """현재 절대 레전드 오버라이드."""
        return self.current().legend

    @property
    def can_undo(self) -> bool:
        return self.cursor > 0

    @property
    def can_redo(self) -> bool:
        return self.cursor < len(self.stack) - 1

    def to_dict(self) -> dict:
        """디스크/응답 직렬화 형태."""
        return {
            "version": _VERSION,
            "cursor": self.cursor,
            "stack": [snap.to_dict() for snap in self.stack],
        }


# ---------------------------------------------------------------------------
# 디스크 입출력
# ---------------------------------------------------------------------------


def filter_path(base_dir: Path) -> Path:
    """산출물 폴더의 charts.filter.json 경로."""
    return base_dir / _FILTER_FILENAME


def load(base_dir: Path) -> FilterState:
    """뷰 상태를 로드한다. 파일이 없거나 손상되면 빈 초기 상태를 반환한다.

    손상 파일에 막혀 기능이 죽지 않도록 방어적으로 초기화한다 (단일 사용자 앱).
    """
    path = filter_path(base_dir)
    if not path.exists():
        return FilterState()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("charts.filter.json 읽기/파싱 실패 — 초기화: %s", exc)
        return FilterState()

    return _state_from_dict(raw)


def save(base_dir: Path, state: FilterState) -> None:
    """뷰 상태를 BOM 없는 UTF-8 JSON 으로 저장한다."""
    path = filter_path(base_dir)
    path.write_text(json.dumps(state.to_dict(), ensure_ascii=False), encoding="utf-8")


def _state_from_dict(raw: object) -> FilterState:
    """디스크 dict → FilterState. 모양이 어긋나면 빈 상태로 폴백한다.

    v1(legend 키 없음) 파일도 legend={} 기본으로 자연 로드된다.
    """
    if not isinstance(raw, dict):
        return FilterState()

    stack_raw = raw.get("stack")
    if not isinstance(stack_raw, list) or not stack_raw:
        return FilterState()

    stack: list[ViewSnapshot] = []
    for entry in stack_raw:
        if not isinstance(entry, dict):
            stack.append(ViewSnapshot())
            continue
        stack.append(
            ViewSnapshot(
                exclude=_normalize_exclude(entry.get("exclude")),
                legend=_normalize_legend(entry.get("legend")),
            )
        )

    cursor = raw.get("cursor", 0)
    if not isinstance(cursor, int) or not (0 <= cursor < len(stack)):
        cursor = len(stack) - 1
    return FilterState(cursor=cursor, stack=stack)


def _normalize_exclude(exclude: object) -> ExcludeMap:
    """제외 맵을 {str: 정렬된 int 리스트} 형태로 정규화한다."""
    if not isinstance(exclude, dict):
        return {}
    out: ExcludeMap = {}
    for key, values in exclude.items():
        if not isinstance(values, list):
            continue
        out[str(key)] = sorted({int(v) for v in values})
    return out


def _normalize_legend(legend: object) -> LegendMap:
    """레전드 맵을 {str: {order, colors, hidden}} 형태로 정규화한다."""
    if not isinstance(legend, dict):
        return {}
    out: LegendMap = {}
    for key, cfg in legend.items():
        if not isinstance(cfg, dict):
            continue
        out[str(key)] = _normalize_legend_cfg(cfg)
    return out


def _normalize_legend_cfg(cfg: dict) -> dict:
    """단일 차트의 레전드 오버라이드를 정규화한다 (빈 필드는 생략)."""
    normalized: dict = {}
    order = cfg.get("order")
    if isinstance(order, list):
        normalized["order"] = [str(v) for v in order]
    colors = cfg.get("colors")
    if isinstance(colors, dict):
        normalized["colors"] = {str(k): str(v) for k, v in colors.items()}
    hidden = cfg.get("hidden")
    if isinstance(hidden, list):
        normalized["hidden"] = [str(v) for v in hidden]
    return normalized


# ---------------------------------------------------------------------------
# 스택 전이 (모두 새 FilterState 반환 — 원본 불변)
# ---------------------------------------------------------------------------


def apply_exclude(
    state: FilterState,
    chart_index: int,
    row_ids: list[int],
    scope: Scope,
    chart_sources: list[str],
) -> FilterState:
    """선택 행을 현재 제외 집합에 더한 새 스냅샷을 push 한다 (legend 는 carry).

    Args:
        state: 현재 상태.
        chart_index: brush/레전드 Filter 가 일어난 차트 인덱스.
        row_ids: 제외할 원본 행 인덱스 (해당 차트 data.source 기준).
        scope: ``single`` 이면 해당 차트만, ``all`` 이면 동일 source 차트 전부.
        chart_sources: 차트 인덱스 → data.source 파일명 (scope=all 그룹 판정용).

    Returns:
        새 FilterState (redo tail 제거 후 새 절대 스냅샷 append).
    """
    snap = state.current()
    new_exclude: ExcludeMap = {k: list(v) for k, v in snap.exclude.items()}
    additions = {int(r) for r in row_ids}
    for target in _target_charts(chart_index, scope, chart_sources):
        key = str(target)
        new_exclude[key] = sorted(set(new_exclude.get(key, [])) | additions)
    return _push(
        state, ViewSnapshot(exclude=new_exclude, legend=_copy_legend(snap.legend))
    )


def apply_legend(
    state: FilterState,
    chart_index: int,
    *,
    order: list[str] | None,
    colors: dict[str, str] | None,
    hidden: list[str] | None,
    scope: Scope,
    chart_sources: list[str],
) -> FilterState:
    """레전드 오버라이드를 갱신한 새 스냅샷을 push 한다 (exclude 는 carry).

    order/hidden 은 제공 시 통째 교체, colors 는 제공 키만 병합한다.
    None 인 필드는 기존 값을 유지한다.

    Args:
        state: 현재 상태.
        chart_index: 편집 대상 차트 인덱스.
        order: 레전드 표시 순서 (시리즈 name 배열). None 이면 변경 없음.
        colors: ``{name: hex}`` 색상 오버라이드 (부분 병합). None 이면 변경 없음.
        hidden: 숨길 시리즈 name 배열. None 이면 변경 없음.
        scope: ``single`` 이면 해당 차트만, ``all`` 이면 동일 source 차트 전부.
        chart_sources: 차트 인덱스 → data.source 파일명 (scope=all 그룹 판정용).

    Returns:
        새 FilterState.
    """
    snap = state.current()
    new_legend = _copy_legend(snap.legend)
    for target in _target_charts(chart_index, scope, chart_sources):
        key = str(target)
        new_legend[key] = _merge_legend_cfg(
            new_legend.get(key, {}), order, colors, hidden
        )
    return _push(
        state,
        ViewSnapshot(
            exclude={k: list(v) for k, v in snap.exclude.items()}, legend=new_legend
        ),
    )


def reset(state: FilterState) -> FilterState:
    """빈 스냅샷을 push 한다 (undo 로 직전 상태 복구 가능)."""
    return _push(state, ViewSnapshot())


def undo(state: FilterState) -> FilterState:
    cursor = max(0, state.cursor - 1)
    return FilterState(cursor=cursor, stack=state.stack)


def redo(state: FilterState) -> FilterState:
    cursor = min(len(state.stack) - 1, state.cursor + 1)
    return FilterState(cursor=cursor, stack=state.stack)


def _push(state: FilterState, snapshot: ViewSnapshot) -> FilterState:
    """redo tail 을 잘라내고 새 절대 스냅샷을 추가해 cursor 를 top 으로."""
    stack = [_copy_snapshot(snap) for snap in state.stack[: state.cursor + 1]]
    stack.append(snapshot)
    return FilterState(cursor=len(stack) - 1, stack=stack)


def _merge_legend_cfg(
    base: dict,
    order: list[str] | None,
    colors: dict[str, str] | None,
    hidden: list[str] | None,
) -> dict:
    """단일 차트 레전드 오버라이드 병합 — order/hidden 교체, colors 병합."""
    merged = _normalize_legend_cfg(base)
    if order is not None:
        merged["order"] = [str(v) for v in order]
    if colors is not None:
        existing = dict(merged.get("colors", {}))
        existing.update({str(k): str(v) for k, v in colors.items()})
        merged["colors"] = existing
    if hidden is not None:
        merged["hidden"] = [str(v) for v in hidden]
    return merged


def _copy_legend(legend: LegendMap) -> LegendMap:
    return {k: _normalize_legend_cfg(v) for k, v in legend.items()}


def _copy_snapshot(snap: ViewSnapshot) -> ViewSnapshot:
    return ViewSnapshot(
        exclude={k: list(v) for k, v in snap.exclude.items()},
        legend=_copy_legend(snap.legend),
    )


def _target_charts(
    chart_index: int, scope: Scope, chart_sources: list[str]
) -> list[int]:
    """scope 에 따라 변경을 적용할 차트 인덱스 목록."""
    if scope == "single":
        return [chart_index]
    if not (0 <= chart_index < len(chart_sources)):
        return [chart_index]
    source = chart_sources[chart_index]
    return [i for i, s in enumerate(chart_sources) if s == source]
