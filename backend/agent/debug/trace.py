"""턴 디버그 트레이스 레코더 + provider 래퍼.

기록 모델: 한 턴 = JSONL 파일 한 개(``result/<session>/_trace/<turn_id>.jsonl``).
한 줄 = 한 이벤트로, 현재 ``TraceScope``(agent_id·depth·iteration·dispatch_id)를 병합해
타임라인 재구성이 가능하다. 모든 기록은 **best-effort** — 파일 IO·직렬화 오류를 내부에서
삼켜 하니스 동작을 절대 방해하지 않는다.

활성화는 ``agent.config.DEBUG_TRACE_ENABLED`` (env ``APP_DEBUG_TRACE``, frozen 강제 off).
비활성 시 ``start_turn_trace`` 가 None 을 반환하고 ``record`` 는 no-op 이므로 비용이 0 이다.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import re
import threading
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.config import DEBUG_TRACE_ENABLED
from agent.models import Message, StreamEvent, ToolSpec
from core.result_store import session_dir

logger = logging.getLogger(__name__)

_TRACE_DIRNAME = "_trace"
# base_url 쿼리에 박힌 인증 토큰 마스킹용 (예: '?token=secret', '&api-key=...').
_URL_SECRET_RE = re.compile(r"((?:token|api[-_]?key|key)=)[^&\s]+", re.IGNORECASE)


@dataclass(frozen=True)
class TraceScope:
    """기록 시점의 상관키 — 어느 에이전트·깊이·반복 회차에서 일어난 이벤트인가."""

    agent_id: str = ""
    depth: int = 0
    iteration: int | None = None
    dispatch_id: str | None = None


_active_trace: contextvars.ContextVar[TurnTrace | None] = contextvars.ContextVar(
    "_active_trace", default=None
)
_scope: contextvars.ContextVar[TraceScope] = contextvars.ContextVar(
    "_scope", default=TraceScope()
)


class TurnTrace:
    """한 턴의 트레이스 파일 핸들. ``record`` 가 JSONL 한 줄을 append 한다."""

    def __init__(self, path: Path, turn_id: str) -> None:
        self.path = path
        self.turn_id = turn_id
        # 병렬 서브에이전트가 같은 파일에 동시 append 할 수 있어 직렬화한다.
        self._lock = threading.Lock()

    def record(self, kind: str, payload: dict[str, Any]) -> None:
        """현재 scope 를 병합해 이벤트 한 줄을 기록한다 (best-effort)."""
        scope = _scope.get()
        entry = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "turn_id": self.turn_id,
            "agent_id": scope.agent_id,
            "depth": scope.depth,
            "iteration": scope.iteration,
            "dispatch_id": scope.dispatch_id,
            "kind": kind,
            "payload": payload,
        }
        try:
            line = json.dumps(entry, ensure_ascii=False, default=str)
            with self._lock, self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:  # noqa: BLE001 — 트레이스는 best-effort, 하니스를 막지 않는다
            logger.debug("debug trace 기록 실패 (무시): kind=%s", kind, exc_info=True)


def start_turn_trace() -> TurnTrace | None:
    """비활성이면 None, 활성이면 새 턴 트레이스를 만들어 contextvar 에 설정한다.

    호출 전에 ``core.result_store.set_session_context`` 가 선행돼야 세션 폴더가 정해진다.
    """
    if not DEBUG_TRACE_ENABLED:
        return None
    try:
        turn_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        trace_dir = session_dir() / _TRACE_DIRNAME
        trace_dir.mkdir(parents=True, exist_ok=True)
        trace = TurnTrace(trace_dir / f"{turn_id}.jsonl", turn_id)
    except Exception:  # noqa: BLE001 — 트레이스 시작 실패는 무시하고 정상 진행
        logger.debug("debug trace 시작 실패 (무시)", exc_info=True)
        return None
    _active_trace.set(trace)
    _scope.set(TraceScope())
    return trace


def record(kind: str, **payload: Any) -> None:
    """활성 트레이스가 있으면 이벤트를 기록한다. 없으면 no-op."""
    trace = _active_trace.get()
    if trace is None:
        return
    trace.record(kind, payload)


@contextlib.contextmanager
def scope(
    *,
    agent_id: str,
    depth: int,
    iteration: int | None = None,
    dispatch_id: str | None = None,
) -> Iterator[None]:
    """이 블록 안에서 기록되는 모든 이벤트에 상관키를 부여한다."""
    token = _scope.set(
        TraceScope(
            agent_id=agent_id,
            depth=depth,
            iteration=iteration,
            dispatch_id=dispatch_id,
        )
    )
    try:
        yield
    finally:
        _scope.reset(token)


def mask_url(base_url: str | None) -> str | None:
    """base_url 쿼리에 토큰/키가 있으면 마스킹한다 (없으면 원본 그대로)."""
    if not base_url:
        return base_url
    return _URL_SECRET_RE.sub(r"\1•••", base_url)


def _dump_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """provider 에 보내는 Message 리스트를 트레이스용 dict 로 덤프한다 (전문 보존)."""
    return [m.model_dump() for m in messages]


def _tool_names(tools: list[ToolSpec]) -> list[str]:
    """노출 도구 스펙에서 이름만 추출한다 (스키마 전문은 노이즈라 생략)."""
    return [getattr(t, "name", str(t)) for t in tools]


class TracingProvider:
    """provider 를 감싸 wire in/out 을 트레이스에 기록하는 투명 데코레이터.

    이벤트는 **변형 없이 그대로 재yield** 하므로 하니스 동작은 동일하다. provider 가
    구현한 ``astream(messages, tools)`` Protocol 만 의존한다 (mock·openai 공통).
    """

    def __init__(
        self,
        inner: Any,
        *,
        model: str,
        masked_key: str,
        base_url: str | None,
    ) -> None:
        self._inner = inner
        self._model = model
        self._masked_key = masked_key
        self._base_url = mask_url(base_url)

    async def astream(
        self, messages: list[Message], tools: list[ToolSpec]
    ) -> AsyncIterator[StreamEvent]:
        record(
            "provider_request",
            model=self._model,
            api_key=self._masked_key,
            base_url=self._base_url,
            tools=_tool_names(tools),
            messages=_dump_messages(messages),
        )
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        finish_reason: str | None = None
        async for event in self._inner.astream(messages, tools):
            etype = getattr(event, "type", None)
            if etype == "delta":
                text_parts.append(event.content)
            elif etype == "reasoning":
                reasoning_parts.append(event.content)
            elif etype == "tool_call":
                tool_calls.append(event.call.model_dump())
            elif etype == "done":
                finish_reason = getattr(event, "finish_reason", None)
            yield event
        record(
            "provider_response",
            text="".join(text_parts),
            reasoning="".join(reasoning_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )
