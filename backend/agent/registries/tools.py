"""Agent harness 가 호출할 도구(Tool) 정의 및 레지스트리.

설계 노트:
    - 기존에는 `Tool` Protocol(구조적 타이핑)이었으나, 슬롯 가드 / 플래너 메타데이터를
      앞으로 계속 늘릴 가능성이 커서 `BaseTool` 추상 베이스 클래스로 전환했다.
      새 메타 필드가 추가돼도 자식 클래스가 자동 상속하므로 호환성 부담이 작다.
    - AddTodoTool / CompleteTodoTool 의 `run()` 은 sentinel 문자열만 돌려준다.
      실제 AgentState 갱신은 harness 가 tool_call 분기에서 가로채 처리한다 —
      LLM 에는 일반 도구처럼 보이지만 provider 재호출 없이 한 턴에 종결된다.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from agent.models import ToolSpec

# Harness 가 이름으로 분기하므로 외부 상수로 노출.
PLANNER_ADD_TODO = "add_todo"
PLANNER_COMPLETE_TODO = "complete_todo"


class BaseTool(ABC):
    """모든 도구의 베이스. 새 메타 필드는 여기 클래스 변수로 추가하면 된다."""

    name: str
    description: str
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    # 필수 인자 누락 시 사용자에게 보일 질문 문구. 키는 parameters.required 항목.
    # 미지정 시 guard 가 properties[key].description 기반 기본 문구를 생성.
    slot_prompts: dict[str, str] = {}

    @abstractmethod
    async def run(self, args: dict[str, Any]) -> str:
        """도구 실행. 결과는 그대로 tool 메시지 content 로 LLM 에 전달되므로
        직렬화된 문자열이어야 한다.
        """


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        """provider 에게 노출할 도구 스펙 목록."""
        return [
            ToolSpec(
                name=t.name,
                description=t.description,
                parameters=t.parameters,
            )
            for t in self._tools.values()
        ]


# ---------------------------------------------------------------------------
# 기본 도구 — 실시간 정보 조회
# ---------------------------------------------------------------------------


class NowTool(BaseTool):
    """현재 시각을 ISO 8601 문자열로 반환하는 데모 도구."""

    name = "now"
    description = "현재 시각(로컬 타임존)을 ISO 8601 문자열로 반환한다."
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    async def run(self, args: dict[str, Any]) -> str:
        return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 플래너 도구 — LLM 이 직접 todo_list 를 채우고 닫는다
# ---------------------------------------------------------------------------


class AddTodoTool(BaseTool):
    """LLM 이 큰 task 를 단계로 분해하기 위해 호출.

    실제 AgentState 갱신은 harness 가 가로채 처리하므로 run() 은 placeholder.
    """

    name = PLANNER_ADD_TODO
    description = (
        "두 단계 이상이 필요한 작업을 시작할 때 항상 먼저 호출한다. "
        "각 item 은 description(필수)과 tool_name(선택, 사용할 도구 힌트)을 가진다. "
        "호출 즉시 todo_list 에 PENDING 상태로 추가된다."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "추가할 sub-task 목록",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "사용자에게 보일 한국어 단계 설명",
                        },
                        "tool_name": {
                            "type": "string",
                            "description": "이 단계에서 호출할 도구 이름 (선택)",
                        },
                    },
                    "required": ["description"],
                },
            }
        },
        "required": ["items"],
    }
    slot_prompts: dict[str, str] = {
        "items": "어떤 단계들로 작업을 분해하면 좋을까요?",
    }

    async def run(self, args: dict[str, Any]) -> str:
        # harness 가 이 호출을 가로채므로 실제로는 도달하지 않는다.
        return "[planner] add_todo placeholder"


class CompleteTodoTool(BaseTool):
    """한 단계를 마쳤을 때 호출. task_id 와 짧은 요약을 함께 전달."""

    name = PLANNER_COMPLETE_TODO
    description = (
        "todo_list 의 한 단계를 완료 처리한다. task_id 는 add_todo 또는 직전 "
        "todo_update 이벤트에서 얻은 식별자를 사용한다."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "완료 처리할 단계의 id"},
            "summary": {
                "type": "string",
                "description": "완료 결과 요약 (선택, 한국어 한 줄)",
            },
        },
        "required": ["task_id"],
    }
    slot_prompts: dict[str, str] = {
        "task_id": "어느 단계를 완료 처리하시겠습니까?",
    }

    async def run(self, args: dict[str, Any]) -> str:
        return "[planner] complete_todo placeholder"


registry = ToolRegistry()
registry.register(NowTool())
registry.register(AddTodoTool())
registry.register(CompleteTodoTool())
