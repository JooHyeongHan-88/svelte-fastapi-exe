"""세션별 변수 저장소 — memory hot tier + disk cold tier.

설계:
    - client_id 별로 격리된 ``SessionNamespace`` 를 모듈 전역 dict 에 보관.
    - 변수 크기가 ``APP_NAMESPACE_MEMORY_THRESHOLD`` 이상이면 디스크에 spill,
      미만이면 in-memory.
    - LRU 강등: ``APP_NAMESPACE_MAX_VARS`` 초과 시 가장 오래된 memory 변수를
      디스크로 강등.
    - 세션 종료 시 :func:`cleanup_namespace` 가 memory dict 와 disk 파일을 모두 제거.

디스크 경로::

    {RESULT_DIR} / {sanitized_title}-{client_id[:8]} / _namespace / {var_name}{ext}

``result_store.session_dir_name()`` 을 그대로 재사용 — artifact 와 같은 세션
루트 아래에 ``_namespace`` 서브폴더로 분리한다.
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from core.config import RESULT_DIR
from core.result_store import current_client_id, current_session_title, session_dir_name

from agent.runtime import serialization as ser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 환경변수 기반 튜닝값 — 호출 시점에 읽어 테스트 친화
# ---------------------------------------------------------------------------


def _memory_threshold_bytes() -> int:
    raw = os.environ.get("APP_NAMESPACE_MEMORY_THRESHOLD", str(10 * 1024 * 1024))
    return int(raw)


def _max_vars_per_session() -> int:
    return int(os.environ.get("APP_NAMESPACE_MAX_VARS", "20"))


Tier = Literal["memory", "disk"]


# ---------------------------------------------------------------------------
# Public dataclass — LLM/UI 에 노출되는 변수 메타
# ---------------------------------------------------------------------------


@dataclass
class VariableRef:
    """namespace 변수 한 건의 외부 노출용 요약."""

    name: str
    type_name: str
    size_bytes: int
    tier: Tier
    preview: str


@dataclass
class _Entry:
    """내부 entry. tier=memory 면 value, tier=disk 면 disk_path/disk_format 사용."""

    name: str
    type_name: str
    size_bytes: int
    tier: Tier
    value: Any | None
    disk_path: Path | None
    disk_format: ser.Format | None
    preview: str


# ---------------------------------------------------------------------------
# 세션별 namespace
# ---------------------------------------------------------------------------


class SessionNamespace:
    """단일 세션의 변수 저장소. OrderedDict 로 LRU 순서를 유지한다.

    가장 최근에 접근/생성된 변수가 끝쪽, 가장 오래된 것이 앞쪽. 강등 시 앞쪽부터.
    """

    def __init__(self, client_id: str, session_title: str = "") -> None:
        if not client_id:
            raise ValueError("client_id 가 비어 있습니다.")
        self._client_id = client_id
        self._session_title = session_title
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    @property
    def disk_dir(self) -> Path:
        """이 세션의 namespace disk 디렉터리. 호출만으로는 생성하지 않는다."""
        return (
            RESULT_DIR
            / session_dir_name(self._client_id, self._session_title)
            / "_namespace"
        )

    def store(self, name: str, value: Any) -> VariableRef:
        """변수를 저장한다. 크기에 따라 memory/disk tier 자동 결정.

        같은 이름의 기존 변수는 덮어쓰기 (disk 파일도 정리).
        """
        if not name or not name.isidentifier():
            raise ValueError(
                f"변수 이름은 Python identifier 형식이어야 합니다: {name!r}"
            )

        size = ser.estimate_size(value)
        type_name = type(value).__name__
        preview = _make_preview(value)

        with self._lock:
            # 기존 entry 가 있으면 disk 파일도 정리.
            self._remove_entry_files(self._entries.pop(name, None))

            threshold = _memory_threshold_bytes()
            if size < threshold:
                entry = _Entry(
                    name=name,
                    type_name=type_name,
                    size_bytes=size,
                    tier="memory",
                    value=value,
                    disk_path=None,
                    disk_format=None,
                    preview=preview,
                )
            else:
                fmt = ser.pick_format(value)
                path = self._allocate_disk_path(name, fmt)
                ser.dump_to_disk(value, path, fmt)
                entry = _Entry(
                    name=name,
                    type_name=type_name,
                    size_bytes=size,
                    tier="disk",
                    value=None,
                    disk_path=path,
                    disk_format=fmt,
                    preview=preview,
                )

            self._entries[name] = entry
            self._evict_if_needed()
            return _to_ref(entry)

    def load(self, name: str) -> Any:
        """변수를 반환한다. disk tier 면 즉시 역직렬화해 반환 (tier 는 유지).

        LRU 갱신: 접근한 변수를 OrderedDict 끝쪽으로 이동.
        """
        with self._lock:
            entry = self._entries.get(name)
            if entry is None:
                raise KeyError(f"namespace 에 '{name}' 변수가 없습니다.")

            self._entries.move_to_end(name)

            if entry.tier == "memory":
                return entry.value

            if not entry.disk_path or not entry.disk_path.exists():
                raise FileNotFoundError(
                    f"namespace 변수 '{name}' 의 디스크 파일이 없습니다: "
                    f"{entry.disk_path}"
                )
            return ser.load_from_disk(entry.disk_path, entry.disk_format or "pickle")

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._entries

    def get_ref(self, name: str) -> VariableRef:
        """변수의 메타데이터만 반환 (값은 로드하지 않음)."""
        with self._lock:
            entry = self._entries.get(name)
            if entry is None:
                raise KeyError(f"namespace 에 '{name}' 변수가 없습니다.")
            return _to_ref(entry)

    def list_refs(self) -> list[VariableRef]:
        """모든 변수의 메타 (LRU 순서대로, 가장 오래된 것이 먼저)."""
        with self._lock:
            return [_to_ref(e) for e in self._entries.values()]

    def delete(self, name: str) -> bool:
        """변수 삭제. memory + disk 모두. 존재 여부 반환."""
        with self._lock:
            entry = self._entries.pop(name, None)
            if entry is None:
                return False
            self._remove_entry_files(entry)
            return True

    def cleanup(self) -> None:
        """세션 종료 시 호출 — 모든 변수와 disk 파일 삭제."""
        with self._lock:
            for entry in self._entries.values():
                self._remove_entry_files(entry)
            self._entries.clear()

            # _namespace 디렉터리도 비어 있으면 정리.
            try:
                if self.disk_dir.exists():
                    self.disk_dir.rmdir()
            except OSError:
                # 다른 파일이 남아있으면 OSError — 그대로 두는 게 안전.
                pass

    def summarize(self) -> str:
        """LLM context 용 한 줄씩 요약. 빈 namespace 면 안내 문자열."""
        refs = self.list_refs()
        if not refs:
            return "(namespace 비어있음)"
        lines: list[str] = []
        for r in refs:
            size_kb = r.size_bytes / 1024
            size_str = (
                f"{size_kb:.1f}KB" if size_kb < 1024 else f"{size_kb / 1024:.2f}MB"
            )
            lines.append(
                f"- {r.name}: {r.type_name} ({size_str}, tier={r.tier}) — {r.preview}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # internal
    # ------------------------------------------------------------------ #

    def _allocate_disk_path(self, name: str, fmt: ser.Format) -> Path:
        self.disk_dir.mkdir(parents=True, exist_ok=True)
        return self.disk_dir / f"{name}{ser.extension_for(fmt)}"

    def _remove_entry_files(self, entry: _Entry | None) -> None:
        if entry is None:
            return
        if entry.disk_path and entry.disk_path.exists():
            try:
                entry.disk_path.unlink()
            except OSError as exc:
                logger.warning(
                    "namespace 파일 삭제 실패: %s (%s)", entry.disk_path, exc
                )

    def _evict_if_needed(self) -> None:
        """변수 총 개수가 max 초과면 가장 오래된 변수를 제거한다.

        설계 결정: '강등(memory→disk)' 만으로는 count 가 줄지 않아 무한루프 위험.
        총량 제한은 LLM 컨텍스트 안정성 (list_namespace summary 폭증 방지) 이 목적이며,
        메모리 압력은 size 기반 disk spillover 로 store() 안에서 따로 처리된다.
        """
        max_vars = _max_vars_per_session()
        while len(self._entries) > max_vars:
            oldest_key = next(iter(self._entries))
            oldest_entry = self._entries.pop(oldest_key)
            self._remove_entry_files(oldest_entry)
            logger.info("namespace LRU 제거(max=%d): %s", max_vars, oldest_key)


# ---------------------------------------------------------------------------
# 모듈 전역 — process-local 세션 namespace 레지스트리
# ---------------------------------------------------------------------------


_namespaces: dict[str, SessionNamespace] = {}
_registry_lock = threading.Lock()


def get_namespace(client_id: str, session_title: str = "") -> SessionNamespace:
    """client_id 의 namespace 를 반환. 없으면 생성.

    같은 client_id 로 재호출 시 기존 namespace 가 반환되므로 session_title 은
    최초 생성 시점의 값만 적용된다.
    """
    if not client_id:
        raise ValueError("client_id 가 비어 있습니다.")
    with _registry_lock:
        ns = _namespaces.get(client_id)
        if ns is None:
            ns = SessionNamespace(client_id, session_title)
            _namespaces[client_id] = ns
    return ns


def cleanup_namespace(client_id: str) -> None:
    """세션 종료 시 호출 — namespace 정리 + 레지스트리에서 제거.

    cleanup 중 디스크 IO 는 우리 락 밖에서 실행되도록 두 단계로 분리.
    """
    with _registry_lock:
        ns = _namespaces.pop(client_id, None)
    if ns is not None:
        ns.cleanup()


def current_namespace() -> SessionNamespace:
    """contextvars 의 현재 client_id 로 namespace 를 가져온다.

    Raises:
        RuntimeError: harness.run_turn 진입 전에 호출된 경우.
    """
    cid = current_client_id()
    if not cid:
        raise RuntimeError(
            "session context 가 설정되지 않았습니다. "
            "harness.run_turn 진입 후에만 호출 가능합니다."
        )
    return get_namespace(cid, current_session_title())


# ---------------------------------------------------------------------------
# 모듈 내 헬퍼
# ---------------------------------------------------------------------------


def _to_ref(entry: _Entry) -> VariableRef:
    return VariableRef(
        name=entry.name,
        type_name=entry.type_name,
        size_bytes=entry.size_bytes,
        tier=entry.tier,
        preview=entry.preview,
    )


def _make_preview(value: Any, max_len: int = 200) -> str:
    """값의 한 줄 repr (개행 제거, 길이 제한). repr 자체가 실패하면 placeholder."""
    try:
        r = repr(value)
    except Exception as exc:
        return f"<repr 실패: {exc}>"
    r = r.replace("\n", " ").replace("\r", " ")
    if len(r) > max_len:
        r = r[: max_len - 3] + "..."
    return r


def _reset_for_tests() -> None:
    """테스트용 — 모듈 전역 namespace 레지스트리 초기화."""
    with _registry_lock:
        for ns in list(_namespaces.values()):
            ns.cleanup()
        _namespaces.clear()
