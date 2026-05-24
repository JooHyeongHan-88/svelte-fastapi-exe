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
# 오케스트레이터 전용 디스패치 도구 — harness 가 재귀 turn 실행으로 가로챔.
SUB_AGENT_DISPATCH = "call_sub_agent"


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

    def names(self) -> set[str]:
        """등록된 모든 도구 이름 집합 — SkillRegistry 교차검증에 사용."""
        return set(self._tools.keys())

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


class DemoSearchTool(BaseTool):
    """AskUserEvent UI 데모용 도구 — 필수 슬롯 3개를 일부러 비워 가드를 발동시킨다.

    실제 데이터 조회는 하지 않으며 슬롯 필링 흐름의 UI 검증이 목적이다.
    """

    name = "demo_search"
    description = (
        "지정한 기간과 형식으로 데이터를 검색한다. "
        "date_from, date_to, format 세 인자가 모두 필요하다."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "date_from": {
                "type": "string",
                "description": "검색 시작일 (YYYY-MM-DD)",
            },
            "date_to": {
                "type": "string",
                "description": "검색 종료일 (YYYY-MM-DD)",
            },
            "format": {
                "type": "string",
                "description": "출력 형식",
                "enum": ["표", "차트", "요약"],
            },
        },
        "required": ["date_from", "date_to", "format"],
    }
    slot_prompts: dict[str, str] = {
        "date_from": "검색 시작일을 알려 주세요 (예: 2025-01-01)",
        "date_to": "검색 종료일을 알려 주세요 (예: 2025-01-31)",
        "format": "결과를 어떤 형식으로 볼까요?",
    }

    async def run(self, args: dict[str, Any]) -> str:
        return (
            f"[demo] {args.get('date_from')} ~ {args.get('date_to')} "
            f"기간의 데이터를 '{args.get('format')}' 형식으로 검색했습니다."
        )


class CallSubAgentTool(BaseTool):
    """오케스트레이터가 서브 에이전트에게 작업을 위임할 때 호출하는 디스패치 도구.

    AddTodoTool 과 동일하게 harness 가 가로채 재귀 _run_agent_turn 을 구동하므로
    run() 자체는 도달하지 않는 placeholder. spec 만 LLM 에게 노출된다.
    서브 에이전트 호출 시에는 _filter_specs_for_sub_agent 가 이 도구를 제거해
    무한 재귀를 차단한다.
    """

    name = SUB_AGENT_DISPATCH
    description = (
        "특정 서브 에이전트에게 작업을 위임한다. agent_name 은 가용 서브 에이전트 "
        "카탈로그에 등록된 에이전트 식별자, task 는 그 에이전트가 수행할 한국어 "
        "작업 지시문 한 단락이다. 호출 즉시 서브 에이전트 turn 이 자동 실행되고 "
        "결과 요약본이 tool_result 로 반환된다."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "위임할 서브 에이전트 식별자 (예: coding_agent)",
            },
            "task": {
                "type": "string",
                "description": "에이전트가 수행할 작업 지시문 (한국어 한 단락)",
            },
        },
        "required": ["agent_name", "task"],
    }
    slot_prompts: dict[str, str] = {
        "agent_name": "어느 서브 에이전트에게 작업을 맡길까요?",
        "task": "에이전트가 수행할 작업을 한 문단으로 알려 주세요.",
    }

    async def run(self, args: dict[str, Any]) -> str:
        # harness 가 SUB_AGENT_DISPATCH 분기에서 가로채므로 도달하지 않는다.
        return "[dispatch] call_sub_agent placeholder — handled by harness"


registry = ToolRegistry()
registry.register(NowTool())
registry.register(AddTodoTool())
registry.register(CompleteTodoTool())
registry.register(DemoSearchTool())
registry.register(CallSubAgentTool())
