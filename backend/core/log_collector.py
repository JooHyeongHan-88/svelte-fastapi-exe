"""사용자 사용 로그를 Grafana Loki 로 전송하는 수집기.

설계 원칙:
    - **턴을 절대 블로킹/실패시키지 않는다.** ``emit()`` 은 큐에 넣기만 하는 O(1) 연산이며
      절대 raise 하지 않는다. 실제 HTTP 전송은 백그라운드 워커가 배치로 처리한다.
    - **죽은 엔드포인트가 메모리를 새게 하지 않는다.** 큐는 bounded — 가득 차면 조용히 드롭.
    - **미설정 시 오버헤드 0.** ``APP_LOKI_BASE_URL`` 이 비면 워커도 안 띄우고 emit 도 no-op.

Loki 데이터 모델:
    - ``stream``(라벨) = 저-카디널리티만: app / user / env / event. Grafana 필터 축.
    - ``values``(로그 라인) = 고-카디널리티·가변 내용(session UUID·tool args·질의문 등)을
      JSON 문자열로. LogQL ``| json`` 으로 파싱한다. session 을 라벨로 올리면 스트림이
      폭발하므로 반드시 라인에 둔다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 로그 라인 하나의 개별 문자열 필드 상한. exec_code stdout·대형 코드 args 가 통째로
# 들어가 라인이 비대해지는 것을 막는다. JSON 유효성을 지키려고 dump 전에 필드별로 자른다.
_MAX_FIELD_CHARS = 8_000
# 최종 assistant 응답 전문은 조금 더 넉넉히 허용한다.
_MAX_REPLY_CHARS = 16_000

_PUSH_PATH = "/loki/api/v1/push"
_FLUSH_INTERVAL_SECONDS = 1.0
_MAX_BATCH = 200
_QUEUE_MAXSIZE = 5_000


def _truncate(value: str, limit: int = _MAX_FIELD_CHARS) -> str:
    """긴 문자열을 상한으로 자른다(로그 라인 비대화 방지)."""
    if len(value) <= limit:
        return value
    return value[:limit] + "…(truncated)"


def _as_line_field(value: Any) -> Any:
    """로그 라인 JSON 에 넣기 전 문자열 필드를 상한으로 자른다(비-문자열은 통과)."""
    if isinstance(value, str):
        return _truncate(value)
    return value


@dataclass
class _LogEntry:
    """큐에 쌓이는 로그 1건. ts_ns 는 emit 시각(나노초 epoch)."""

    event: str
    fields: dict[str, Any]
    ts_ns: int = field(default_factory=time.time_ns)


class LokiLogCollector:
    """Loki push API 로 사용 로그를 배치 전송하는 백그라운드 수집기."""

    def __init__(
        self,
        base_url: str,
        *,
        user: str,
        app: str,
        env: str,
        ssl_verify: bool | ssl.SSLContext,
        timeout: float,
    ) -> None:
        self._base_url = base_url
        self._push_url = f"{base_url}{_PUSH_PATH}" if base_url else ""
        # user/app/env 는 프로세스 전역 라벨 — 매 emit 마다 넘기지 않는다.
        self._labels = {"app": app, "user": user, "env": env}
        self._ssl_verify = ssl_verify
        self._timeout = timeout
        self._queue: asyncio.Queue[_LogEntry] | None = None
        self._client: httpx.AsyncClient | None = None
        self._worker: asyncio.Task[None] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._base_url)

    def start(self) -> None:
        """백그라운드 워커·HTTP 클라이언트를 기동한다. 비활성 시 no-op.

        FastAPI lifespan startup 에서 실행 중인 event loop 안에서 호출해야 한다.
        """
        if not self.enabled or self._worker is not None:
            return
        self._queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._client = httpx.AsyncClient(timeout=self._timeout, verify=self._ssl_verify)
        self._worker = asyncio.create_task(self._run_worker())
        logger.info("Loki 로그 수집기 시작: %s", self._push_url)

    async def aclose(self) -> None:
        """남은 로그를 flush 하고 워커·클라이언트를 정리한다. lifespan shutdown 용."""
        if self._worker is None:
            return
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
        if self._queue is not None:
            await self._drain_and_push()
        if self._client is not None:
            await self._client.aclose()
        self._worker = None

    def emit(self, event: str, **fields: Any) -> None:
        """로그 1건을 큐에 넣는다. 절대 블로킹/raise 하지 않는다.

        Args:
            event: 이벤트 종류(=Loki event 라벨). 바운드된 소수 집합이어야 한다
                (user_query / tool_call / tool_result / assistant_reply / turn_end 등).
            **fields: 로그 라인 JSON 에 담을 임의 필드(session·tool·args·text 등).
        """
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(_LogEntry(event=event, fields=fields))
        except asyncio.QueueFull:
            # 로깅은 앱 동작보다 후순위 — 큐가 꽉 차면 조용히 버린다.
            logger.debug("Loki 큐 포화 — 로그 1건 드롭 (event=%s)", event)

    def new_turn(self, session: str) -> TurnLogTap:
        """한 턴 동안 이벤트를 관찰·집계하는 tap 을 만든다."""
        return TurnLogTap(self, session)

    async def _run_worker(self) -> None:
        """큐에서 배치를 모아 Loki 로 밀어넣는 루프."""
        while True:
            batch = await self._collect_batch()
            if batch:
                await self._push(batch)

    async def _collect_batch(self) -> list[_LogEntry]:
        """첫 항목이 올 때까지 대기한 뒤 flush 창 동안 추가 항목을 모은다."""
        assert self._queue is not None
        loop = asyncio.get_running_loop()
        batch = [await self._queue.get()]
        deadline = loop.time() + _FLUSH_INTERVAL_SECONDS
        while len(batch) < _MAX_BATCH:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                batch.append(
                    await asyncio.wait_for(self._queue.get(), timeout=remaining)
                )
            except asyncio.TimeoutError:
                break
        return batch

    async def _drain_and_push(self) -> None:
        """종료 시 큐에 남은 항목을 모두 비워 마지막으로 전송한다."""
        assert self._queue is not None
        batch: list[_LogEntry] = []
        while not self._queue.empty():
            batch.append(self._queue.get_nowait())
        if batch:
            await self._push(batch)

    def _to_body(self, batch: list[_LogEntry]) -> dict[str, Any]:
        """배치를 event 라벨별 stream 으로 그룹핑해 Loki push body 로 만든다."""
        streams: dict[str, dict[str, Any]] = {}
        for entry in batch:
            stream = streams.get(entry.event)
            if stream is None:
                stream = {
                    "stream": {**self._labels, "event": entry.event},
                    "values": [],
                }
                streams[entry.event] = stream
            safe_fields = {k: _as_line_field(v) for k, v in entry.fields.items()}
            line = json.dumps(safe_fields, ensure_ascii=False, default=str)
            stream["values"].append([str(entry.ts_ns), line])
        return {"streams": list(streams.values())}

    async def _push(self, batch: list[_LogEntry]) -> None:
        """배치를 Loki 로 POST 한다. best-effort — 실패는 삼키고 debug 로만 남긴다."""
        if self._client is None:
            return
        try:
            response = await self._client.post(
                self._push_url, json=self._to_body(batch)
            )
            response.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            # 로깅 실패가 앱을 방해하면 안 된다(print 금지 — 표준출력 오염 방지).
            logger.debug("Loki push 실패(%d건): %s", len(batch), exc)


class TurnLogTap:
    """한 턴의 StreamEvent 흐름을 관찰해 사용 로그로 변환한다.

    delta/reasoning 청크는 개별 로깅하지 않고(한 응답에 수천 건) 누적했다가
    turn 종료 시 assistant_reply 로 1회만 남긴다.
    """

    def __init__(self, collector: LokiLogCollector, session: str) -> None:
        self._collector = collector
        self._session = session
        self._reply_parts: list[str] = []
        self._tool_calls = 0
        self._errors = 0
        self._started = time.monotonic()

    def query(self, text: str, *, title: str = "") -> None:
        """턴 시작 — 사용자 질의를 남긴다."""
        self._collector.emit(
            "user_query", session=self._session, text=text, title=title
        )

    def observe(self, event: Any) -> None:
        """run_turn 이 yield 한 이벤트 1건을 관찰한다."""
        event_type = event.type
        if event_type == "delta":
            self._reply_parts.append(event.content)
        elif event_type == "tool_call":
            self._emit_tool_call(event.call.name, event.call.arguments)
        elif event_type == "tool_result":
            self._emit_tool_result(event.name, event.is_error, event.result)
        elif event_type == "error":
            self._collector.emit(
                "error",
                session=self._session,
                message=event.message,
                is_fallback=event.is_fallback,
            )
        elif event_type == "agent:switch":
            self._collector.emit(
                "subagent",
                session=self._session,
                from_agent=event.from_agent,
                to_agent=event.to_agent,
                reason=event.reason,
            )
        elif event_type == "agent:progress":
            self._observe_subagent(event)

    def finish(self, *, cancelled: bool) -> None:
        """턴 종료 — 누적 응답과 요약 지표를 남긴다. finally 에서 호출."""
        reply = "".join(self._reply_parts).strip()
        if reply:
            self._collector.emit(
                "assistant_reply",
                session=self._session,
                text=_truncate(reply, _MAX_REPLY_CHARS),
            )
        self._collector.emit(
            "turn_end",
            session=self._session,
            cancelled=cancelled,
            tool_calls=self._tool_calls,
            errors=self._errors,
            duration_ms=int((time.monotonic() - self._started) * 1000),
        )

    def _emit_tool_call(
        self, tool: str, arguments: dict[str, Any], agent: str | None = None
    ) -> None:
        self._tool_calls += 1
        self._collector.emit(
            "tool_call",
            session=self._session,
            agent=agent,
            tool=tool,
            args=_truncate(json.dumps(arguments, ensure_ascii=False, default=str)),
        )

    def _emit_tool_result(
        self, tool: str, is_error: bool, result: str, agent: str | None = None
    ) -> None:
        if is_error:
            self._errors += 1
        self._collector.emit(
            "tool_result",
            session=self._session,
            agent=agent,
            tool=tool,
            is_error=is_error,
            result=result,
        )

    def _observe_subagent(self, event: Any) -> None:
        """서브 에이전트의 래핑된 tool_call/tool_result 를 풀어 집계에 포함한다."""
        payload = event.inner_payload
        if event.inner_type == "tool_call":
            call = payload.get("call", {})
            self._emit_tool_call(
                call.get("name", ""), call.get("arguments", {}), agent=event.agent_id
            )
        elif event.inner_type == "tool_result":
            self._emit_tool_result(
                payload.get("name", ""),
                payload.get("is_error", False),
                payload.get("result", ""),
                agent=event.agent_id,
            )


def _build_collector() -> LokiLogCollector:
    """설정을 읽어 프로세스 단일 수집기를 만든다.

    BUILD_CHANNEL 을 env 라벨로 쓴다(qa/prod, dev 는 비-frozen 기본 qa). frozen 여부는
    config 가 이미 반영하므로 여기서는 그대로 라벨화한다.
    """
    from core import config

    return LokiLogCollector(
        config.LOKI_BASE_URL,
        user=config.OS_USER,
        app=config.APP_NAME,
        env=config.BUILD_CHANNEL,
        ssl_verify=config.LOKI_SSL_VERIFY,
        timeout=config.LOKI_TIMEOUT,
    )


# 프로세스 단일 인스턴스 — main.py lifespan 이 start()/aclose(), chat.py 가 emit 한다.
collector: LokiLogCollector = _build_collector()
