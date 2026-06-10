"""/api/chat 동시 턴 가드(R2) — 같은 client_id 두 번째 POST 즉시 거부.

탭 복제(같은 세션 공유)에서 양쪽이 동시에 전송하면 두 run_turn 이 병주해
히스토리 교차 저장·state 오염이 발생한다. 백엔드가 두 번째 요청을
ErrorEvent + DoneEvent 로 즉시 종결하는지, 턴 종료 후 가드가 해제되는지 검증.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

import api.chat as chat_module
from api.chat import router as chat_router


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """느린 stub run_turn 으로 교체한 chat 라우터 앱."""

    async def _slow_run_turn(client_id, user_message, **kwargs):  # noqa: ANN001
        from agent.models import DeltaEvent, DoneEvent

        yield DeltaEvent(content="시작")
        await asyncio.sleep(0.4)
        yield DeltaEvent(content="끝")
        yield DoneEvent()

    monkeypatch.setattr(chat_module.harness, "run_turn", _slow_run_turn)
    # 잔여 상태 격리 — 다른 테스트가 가드를 오염시키지 않도록.
    chat_module._active_turn_clients.clear()

    app = FastAPI()
    app.include_router(chat_router)
    return app


async def _read_sse_events(client: httpx.AsyncClient, client_id: str) -> list[dict]:
    events: list[dict] = []
    async with client.stream(
        "POST",
        "/api/chat",
        params={"client_id": client_id},
        json={"message": "hi"},
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


async def test_second_concurrent_post_rejected_immediately(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        first = asyncio.create_task(_read_sse_events(c, "dup"))
        await asyncio.sleep(0.1)  # 첫 스트림이 가드를 등록할 시간

        second = await _read_sse_events(c, "dup")
        first_events = await first

    # 두 번째 — run_turn 미진입, ErrorEvent + DoneEvent 만.
    assert [e["type"] for e in second] == ["error", "done"]
    assert "이미 응답을 생성 중" in second[0]["message"]
    # 첫 번째 — 정상 완료 (거부의 영향 없음).
    assert first_events[-1]["type"] == "done"
    assert any(e["type"] == "delta" for e in first_events)


async def test_different_client_ids_run_concurrently(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        first = asyncio.create_task(_read_sse_events(c, "tab-a"))
        await asyncio.sleep(0.1)
        second = await _read_sse_events(c, "tab-b")
        first_events = await first

    assert first_events[-1]["type"] == "done"
    assert second[-1]["type"] == "done"
    assert all(e["type"] != "error" for e in second)


async def test_guard_released_after_turn_completes(app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        first = await _read_sse_events(c, "serial")
        second = await _read_sse_events(c, "serial")

    assert first[-1]["type"] == "done"
    # 순차 재요청은 정상 처리 — finally 의 가드 해제 검증.
    assert all(e["type"] != "error" for e in second)
    assert second[-1]["type"] == "done"
