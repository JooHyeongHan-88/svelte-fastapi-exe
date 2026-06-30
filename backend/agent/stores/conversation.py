"""client_id 별 대화 히스토리 인메모리 저장소.

browser.py 의 _lock + dict 패턴을 따라간다. uvicorn event-loop 단일 스레드에서만
접근하지만, 미래에 background task / watchdog 에서 reset 호출 가능성이 있어
threading.Lock 으로 일관성 유지.

Tool 결과 truncation 설계:
    - 현재 턴 LLM 컨텍스트(messages)에는 full 내용이 필요하다 — 방금 실행한 결과를
      에이전트가 그 턴 안에 읽어야 하기 때문.
    - 히스토리(ConversationStore)에는 요약만 있어도 된다 — 미래 턴에서 LLM 은 "이전에
      실행했고 결과는 대략 이랬다"는 정도면 충분하다.
    - 따라서 append() 시점에 tool 메시지를 절단해 저장함으로써 두 요구를 분리한다.
      `exec_code` stdout 4000자·`describe_variable` 상세 dump 등 대용량 결과가
      매 턴 LLM 컨텍스트에 쌓이는 것을 방지한다.
"""

import threading

from agent.models import Message

# 히스토리에 저장할 tool 결과 절단 파라미터.
# 현재 턴 LLM 컨텍스트(messages)는 제한 없음 — truncation 은 storage 시점에만 적용.
# head 만 남기면 exec_code 결론(print 는 stdout 끝)·에러 타입(끝)이 다음 턴에서 소실되므로
# head+tail 을 모두 보존한다. head+tail(750) < 트리거 임계(800) 이라 항상 축소되고 중첩 없음.
_TOOL_HISTORY_MAX_CHARS: int = 800
_TOOL_HISTORY_HEAD_CHARS: int = 550
_TOOL_HISTORY_TAIL_CHARS: int = 200
_TOOL_HISTORY_ELISION: str = "\n... [중략] ...\n"


def _truncate_for_history(msg: Message) -> Message:
    """role='tool' 메시지의 content 를 head+tail 로 절단한다.

    "무엇을 실행했는지"(head)와 "무엇이 나왔는지·에러 타입"(tail)을 모두 보존한다.
    절단 시 새 Message 객체를 생성하므로 현재 턴 messages 리스트의 원본 객체를
    변형하지 않는다. 다른 role 은 그대로 반환한다.
    """
    if msg.role != "tool":
        return msg
    if len(msg.content) <= _TOOL_HISTORY_MAX_CHARS:
        return msg
    head = msg.content[:_TOOL_HISTORY_HEAD_CHARS]
    tail = msg.content[-_TOOL_HISTORY_TAIL_CHARS:]
    truncated = f"{head}{_TOOL_HISTORY_ELISION}{tail}"
    return Message(role=msg.role, content=truncated, tool_call_id=msg.tool_call_id)


class ConversationStore:
    def __init__(self, max_history: int) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, list[Message]] = {}
        self._max_history = max_history

    def get_history(self, client_id: str) -> list[Message]:
        """현재 히스토리 스냅샷을 복사해 반환.

        호출자가 자유롭게 조작해도 내부 상태에 영향이 없도록 list 복사.
        """
        with self._lock:
            return list(self._data.get(client_id, []))

    def append(self, client_id: str, *messages: Message) -> list[Message]:
        """히스토리 끝에 메시지 여러 개를 추가하고, 오래된 항목을 트리밍한다.

        저장 전 tool 메시지 content 를 ``_TOOL_HISTORY_MAX_CHARS`` 로 절단한다.
        현재 턴 LLM 컨텍스트(messages 리스트)는 full 내용을 유지한 채 별도로 사용되고,
        다음 턴부터 히스토리로 읽혀질 때만 절단본이 쓰인다.

        트리밍은 tool_call 쌍을 끊지 않는다. OpenAI 와이어 규약상 ``role="tool"``
        메시지는 반드시 선행 assistant 의 ``tool_calls`` 에 대응해야 하므로, 단순
        앞자르기로 선행 assistant 가 잘려 나가면 고아 tool 메시지가 첫 메시지로 남아
        다음 턴 요청이 400 으로 거부된다. 잘린 직후 첫 메시지가 tool 이면 비-tool
        메시지가 나올 때까지 cut 을 앞으로 더 밀어 항상 유효한 경계에서 자른다.

        Returns:
            트림으로 **버려진** 메시지 리스트(시간순, 절단본 형태). 버린 게 없으면
            빈 리스트. 하니스가 이를 받아 summarize-then-drop 압축(progress_summary)에
            쓴다 — store 는 provider 무접근 순수 저장소라 요약은 하니스 책임이다.
        """
        with self._lock:
            history = self._data.setdefault(client_id, [])
            history.extend(_truncate_for_history(m) for m in messages)

            if len(history) <= self._max_history:
                return []

            # system prompt 는 harness 가 매 턴 다시 머리에 붙이므로 여기서 보존 불필요.
            cut = len(history) - self._max_history
            # 경계 보정: 고아 tool 메시지가 첫 항목이 되지 않도록 cut 을 전진시킨다.
            while cut < len(history) and history[cut].role == "tool":
                cut += 1
            dropped = history[:cut]
            del history[:cut]
            return dropped

    def reset(self, client_id: str) -> None:
        with self._lock:
            self._data.pop(client_id, None)
