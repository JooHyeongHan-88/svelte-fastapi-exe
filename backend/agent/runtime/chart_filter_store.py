"""``charts.filter.json`` 사이드카 — display_chart 인터랙티브 필터의 undo/redo 스택.

산출물 폴더(parquet/spec 과 동일 폴더)에 영속되는 필터 상태의 단일 진실 공급원이다.
FastAPI/harness 에 비의존하는 순수 로직 — 단독 테스트 가능.

스택 모델:
    각 항목은 "그 시점의 **절대** 제외 집합"(델타 아님)이라 undo/redo 는 cursor 이동만으로
    끝난다. ``exclude`` 는 ``{차트 인덱스(str): 정렬된 제외 원본 행 인덱스}``.

    cursor 가 가리키는 항목이 현재 상태다. 새 필터/리셋은 redo tail 을 잘라내고
    새 절대 상태를 push 한다. reset 은 빈 제외 집합을 push 하므로 undo 로 복구 가능.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_FILTER_FILENAME = "charts.filter.json"
_VERSION = 1

# 차트 인덱스(str) → 제외할 원본 parquet 행 인덱스(정렬).
ExcludeMap = dict[str, list[int]]
Scope = Literal["single", "all"]


@dataclass
class FilterState:
    """필터 undo/redo 스택과 현재 cursor."""

    cursor: int = 0
    stack: list[ExcludeMap] = field(default_factory=lambda: [{}])

    def current(self) -> ExcludeMap:
        """cursor 가 가리키는 현재 절대 제외 집합."""
        return self.stack[self.cursor]

    @property
    def can_undo(self) -> bool:
        return self.cursor > 0

    @property
    def can_redo(self) -> bool:
        return self.cursor < len(self.stack) - 1

    def to_dict(self) -> dict:
        """디스크/응답 직렬화 형태. 스택 항목은 ``{"exclude": {...}}`` 로 감싼다."""
        return {
            "version": _VERSION,
            "cursor": self.cursor,
            "stack": [{"exclude": entry} for entry in self.stack],
        }


# ---------------------------------------------------------------------------
# 디스크 입출력
# ---------------------------------------------------------------------------


def filter_path(base_dir: Path) -> Path:
    """산출물 폴더의 charts.filter.json 경로."""
    return base_dir / _FILTER_FILENAME


def load(base_dir: Path) -> FilterState:
    """필터 상태를 로드한다. 파일이 없거나 손상되면 빈 초기 상태를 반환한다.

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
    """필터 상태를 BOM 없는 UTF-8 JSON 으로 저장한다."""
    path = filter_path(base_dir)
    path.write_text(json.dumps(state.to_dict(), ensure_ascii=False), encoding="utf-8")


def _state_from_dict(raw: object) -> FilterState:
    """디스크 dict → FilterState. 모양이 어긋나면 빈 상태로 폴백한다."""
    if not isinstance(raw, dict):
        return FilterState()

    stack_raw = raw.get("stack")
    if not isinstance(stack_raw, list) or not stack_raw:
        return FilterState()

    stack: list[ExcludeMap] = []
    for entry in stack_raw:
        exclude = entry.get("exclude") if isinstance(entry, dict) else None
        stack.append(_normalize_exclude(exclude))

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
    """선택 행을 현재 제외 집합에 더한 새 상태를 push 한다.

    Args:
        state: 현재 상태.
        chart_index: brush 가 일어난 차트 인덱스.
        row_ids: 제외할 원본 행 인덱스 (해당 차트 data.source 기준).
        scope: ``single`` 이면 해당 차트만, ``all`` 이면 동일 source 차트 전부.
        chart_sources: 차트 인덱스 → data.source 파일명 (scope=all 그룹 판정용).

    Returns:
        새 FilterState (redo tail 제거 후 새 절대 상태 append).
    """
    new_exclude: ExcludeMap = {k: list(v) for k, v in state.current().items()}
    additions = {int(r) for r in row_ids}
    for target in _target_charts(chart_index, scope, chart_sources):
        key = str(target)
        new_exclude[key] = sorted(set(new_exclude.get(key, [])) | additions)
    return _push(state, new_exclude)


def reset(state: FilterState) -> FilterState:
    """빈 제외 집합을 push 한다 (undo 로 직전 필터 복구 가능)."""
    return _push(state, {})


def undo(state: FilterState) -> FilterState:
    cursor = max(0, state.cursor - 1)
    return FilterState(cursor=cursor, stack=state.stack)


def redo(state: FilterState) -> FilterState:
    cursor = min(len(state.stack) - 1, state.cursor + 1)
    return FilterState(cursor=cursor, stack=state.stack)


def _push(state: FilterState, exclude: ExcludeMap) -> FilterState:
    """redo tail 을 잘라내고 새 절대 상태를 추가해 cursor 를 top 으로."""
    stack = [dict(entry) for entry in state.stack[: state.cursor + 1]]
    stack.append(exclude)
    return FilterState(cursor=len(stack) - 1, stack=stack)


def _target_charts(
    chart_index: int, scope: Scope, chart_sources: list[str]
) -> list[int]:
    """scope 에 따라 제외를 적용할 차트 인덱스 목록."""
    if scope == "single":
        return [chart_index]
    if not (0 <= chart_index < len(chart_sources)):
        return [chart_index]
    source = chart_sources[chart_index]
    return [i for i, s in enumerate(chart_sources) if s == source]
