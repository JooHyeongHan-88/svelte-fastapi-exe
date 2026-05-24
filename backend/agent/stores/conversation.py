"""client_id 별 대화 히스토리 인메모리 저장소.

browser.py 의 _lock + dict 패턴을 따라간다. uvicorn event-loop 단일 스레드에서만
접근하지만, 미래에 background task / watchdog 에서 reset 호출 가능성이 있어
threading.Lock 으로 일관성 유지.
"""

import threading

from agent.models import Message


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

    def append(self, client_id: str, *messages: Message) -> None:
        """히스토리 끝에 메시지 여러 개를 추가하고, 오래된 항목을 트리밍한다."""
        with self._lock:
            history = self._data.setdefault(client_id, [])
            history.extend(messages)

            if len(history) > self._max_history:
                # 오래된 system/user/assistant/tool 메시지를 앞에서 잘라낸다.
                # system prompt 는 harness 가 매 턴 다시 머리에 붙이므로 여기서 보존할 필요 없음.
                del history[: len(history) - self._max_history]

    def reset(self, client_id: str) -> None:
        with self._lock:
            self._data.pop(client_id, None)
