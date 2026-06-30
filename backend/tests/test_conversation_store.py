"""ConversationStore 트리밍 + tool_call 쌍 정합성 + 히스토리 truncation 회귀 테스트.

OpenAI 와이어 규약: role="tool" 메시지는 선행 assistant tool_calls 에 대응해야 하고,
assistant 의 모든 tool_call 은 매칭 tool 응답이 있어야 한다. 긴 대화 트리밍이나
배치 중단으로 이 쌍이 깨지면 다음 턴 요청이 400 으로 거부된다.

Tool truncation: 히스토리 저장 시 tool 메시지 content 를 _TOOL_HISTORY_MAX_CHARS 로
절단해 다음 턴 LLM 컨텍스트 비대화를 방지한다. 현재 턴 messages 원본은 변형하지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.harness import _balance_unresolved_tool_calls  # noqa: E402
from agent.models import Message, ToolCall  # noqa: E402
from agent.stores.conversation import (  # noqa: E402
    ConversationStore,
    _TOOL_HISTORY_ELISION,
    _TOOL_HISTORY_HEAD_CHARS,
    _TOOL_HISTORY_MAX_CHARS,
    _TOOL_HISTORY_TAIL_CHARS,
    _truncate_for_history,
)
from tests._runner import run_tests  # noqa: E402


def _msg(role: str, content: str = "", *, tool_call_id: str | None = None) -> Message:
    return Message(role=role, content=content, tool_call_id=tool_call_id)


# ---------------------------------------------------------------------------
# 트리밍 — tool_call 쌍 보존
# ---------------------------------------------------------------------------


def test_trim_does_not_leave_leading_tool_message() -> None:
    # naive cut 이 tool 메시지에 떨어지는 상황을 강제한다.
    store = ConversationStore(max_history=2)
    store.append(
        "c1",
        _msg("user", "분석해줘"),
        _msg("assistant", "", tool_call_id=None),  # tool_calls 보유 assistant 대용
        _msg("tool", "결과 A", tool_call_id="A"),
        _msg("assistant", "완료"),
    )
    history = store.get_history("c1")
    # 첫 메시지는 절대 고아 tool 이 아니어야 한다.
    assert history[0].role != "tool", [m.role for m in history]


def test_trim_clean_boundary_not_over_trimmed() -> None:
    # tool 이 없는 평범한 히스토리는 정확히 max_history 만큼만 남긴다.
    store = ConversationStore(max_history=3)
    store.append(
        "c2",
        _msg("user", "1"),
        _msg("user", "2"),
        _msg("user", "3"),
        _msg("user", "4"),
    )
    history = store.get_history("c2")
    assert [m.content for m in history] == ["2", "3", "4"]


def test_trim_keeps_full_history_under_limit() -> None:
    store = ConversationStore(max_history=10)
    store.append("c3", _msg("user", "a"), _msg("assistant", "b"))
    assert len(store.get_history("c3")) == 2


# ---------------------------------------------------------------------------
# 중단 시 미해결 tool_call 보정
# ---------------------------------------------------------------------------


def _assistant_with_calls(*ids: str) -> Message:
    return Message(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id=i, name="demo", arguments={}) for i in ids],
    )


def test_balance_fills_unresolved_tool_calls() -> None:
    assistant = _assistant_with_calls("A", "B")
    messages = [
        _msg("user", "hi"),
        assistant,
        _msg("tool", "결과 A", tool_call_id="A"),  # B 는 미해결
    ]
    turn: list[Message] = list(messages)

    _balance_unresolved_tool_calls(messages, turn, assistant)

    tool_ids = [m.tool_call_id for m in messages if m.role == "tool"]
    assert tool_ids == ["A", "B"], tool_ids
    # turn_messages 에도 동일하게 반영
    assert any(m.role == "tool" and m.tool_call_id == "B" for m in turn)


def test_balance_noop_when_all_resolved() -> None:
    assistant = _assistant_with_calls("A")
    messages = [assistant, _msg("tool", "r", tool_call_id="A")]
    _balance_unresolved_tool_calls(messages, None, assistant)
    assert sum(1 for m in messages if m.role == "tool") == 1


def test_balance_noop_without_tool_calls() -> None:
    assistant = _msg("assistant", "그냥 텍스트 응답")
    messages = [assistant]
    _balance_unresolved_tool_calls(messages, None, assistant)
    assert len(messages) == 1


# ---------------------------------------------------------------------------
# F7 — tool 결과 히스토리 truncation
# ---------------------------------------------------------------------------


def test_tool_message_truncated_on_store() -> None:
    # 임계값 초과 tool 결과는 head+tail 로 저장되어 도입부와 결론(끝)이 모두 보존된다.
    store = ConversationStore(max_history=10)
    big_result = "H" * 1000 + "TAILMARK"
    tool_msg = _msg("tool", big_result, tool_call_id="t1")
    store.append("cx", tool_msg)

    stored = store.get_history("cx")[0]
    assert _TOOL_HISTORY_ELISION in stored.content
    assert stored.content.startswith("H")  # 도입부(head) 보존
    assert stored.content.endswith("TAILMARK")  # 결론(tail) 보존
    assert len(stored.content) < len(big_result)
    assert stored.tool_call_id == "t1"


def test_tool_message_original_not_mutated() -> None:
    # 원본 Message 객체는 변형되지 않아야 한다 (현재 턴 LLM 컨텍스트 보호).
    store = ConversationStore(max_history=10)
    big_result = "y" * (_TOOL_HISTORY_MAX_CHARS + 200)
    tool_msg = _msg("tool", big_result, tool_call_id="t2")
    store.append("cx2", tool_msg)

    assert tool_msg.content == big_result  # 원본 불변


def test_short_tool_message_not_truncated() -> None:
    store = ConversationStore(max_history=10)
    short = "결과 OK"
    store.append("cx3", _msg("tool", short, tool_call_id="t3"))
    stored = store.get_history("cx3")[0]
    assert stored.content == short


def test_non_tool_messages_not_truncated() -> None:
    store = ConversationStore(max_history=10)
    long_user = "u" * 5000
    store.append("cx4", _msg("user", long_user))
    stored = store.get_history("cx4")[0]
    assert stored.content == long_user  # user 메시지는 건드리지 않음


def test_truncate_for_history_standalone() -> None:
    # 헬퍼 함수 직접 테스트
    short_msg = _msg("tool", "짧다", tool_call_id="a")
    assert _truncate_for_history(short_msg) is short_msg  # 같은 객체(변형 없음)

    long_msg = _msg("tool", "z" * 2000, tool_call_id="b")
    result = _truncate_for_history(long_msg)
    assert result is not long_msg  # 새 객체
    assert len(result.content) == (
        _TOOL_HISTORY_HEAD_CHARS + len(_TOOL_HISTORY_ELISION) + _TOOL_HISTORY_TAIL_CHARS
    )
    assert result.tool_call_id == "b"


# ---------------------------------------------------------------------------
# append() 가 트림으로 버린 메시지를 반환 (summarize-then-drop 입력)
# ---------------------------------------------------------------------------


def test_append_returns_empty_when_under_limit() -> None:
    store = ConversationStore(max_history=10)
    dropped = store.append("d1", _msg("user", "a"), _msg("assistant", "b"))
    assert dropped == []


def test_append_returns_dropped_messages_when_over_limit() -> None:
    store = ConversationStore(max_history=3)
    dropped = store.append(
        "d2",
        _msg("user", "1"),
        _msg("user", "2"),
        _msg("user", "3"),
        _msg("user", "4"),
    )
    # 가장 오래된 1건이 잘려 반환되고, 남은 히스토리와 합쳐 원본 순서가 보존된다.
    assert [m.content for m in dropped] == ["1"]
    assert [m.content for m in store.get_history("d2")] == ["2", "3", "4"]


def test_append_dropped_respects_tool_boundary() -> None:
    # cut 이 고아 tool 에 떨어지면 경계를 앞으로 밀어, 반환된 dropped 도 그 경계와 일치한다.
    store = ConversationStore(max_history=2)
    dropped = store.append(
        "d3",
        _msg("user", "분석해줘"),
        _msg("assistant", "", tool_call_id=None),
        _msg("tool", "결과 A", tool_call_id="A"),
        _msg("assistant", "완료"),
    )
    history = store.get_history("d3")
    # 경계 전진으로 tool 까지 함께 버려진다 → 남은 첫 메시지는 고아 tool 이 아니다.
    assert history[0].role != "tool"
    assert [m.content for m in dropped] == ["분석해줘", "", "결과 A"]
    assert [m.content for m in history] == ["완료"]


if __name__ == "__main__":
    run_tests(globals())
