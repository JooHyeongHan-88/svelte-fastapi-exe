"""LLM 에이전트 런타임 관련 환경 변수 / 경로.

settings.json 초기 시드값(LLM_PROVIDER 등)은 SettingsStore 가 처음 켜졌을 때
한 번만 채우는 용도로 함께 둔다. 런타임에 사용자가 바꾸는 값은 settings.json
이 진실 공급원이고 여기 시드는 더 이상 읽히지 않는다.
"""

import logging
import os
import sys
from pathlib import Path

from core.config import APP_NAME, _project_root


# ---------------------------------------------------------------------------
# Agent state (todo/pending slot) 영속 경로.
# 사용자별 진행 상황을 EXE 재기동/세션 전환 후에도 유지하기 위함.
# ---------------------------------------------------------------------------


def _get_agent_state_path() -> Path:
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME / "agent_states.json"
    return _project_root() / "backend" / ".runtime" / "agent_states.json"


AGENT_STATE_PATH: Path = _get_agent_state_path()


# ---------------------------------------------------------------------------
# PROMPTS/ · SKILLS/ 디렉토리 — frozen 은 MEIPASS 임베드, dev 는 프로젝트 루트.
# ---------------------------------------------------------------------------

if getattr(sys, "frozen", False):
    PROMPTS_DIR: Path = _project_root() / "PROMPTS"
    SKILLS_DIR: Path = _project_root() / "SKILLS"
    AGENTS_DIR: Path = _project_root() / "AGENTS"
else:
    PROMPTS_DIR = _project_root() / "PROMPTS"
    SKILLS_DIR = _project_root() / "SKILLS"
    AGENTS_DIR = _project_root() / "AGENTS"


# ---------------------------------------------------------------------------
# LLM 생성 파라미터 — settings.json 대신 환경 변수로 제어한다.
# UI에 노출하지 않고 배포 시 .env 또는 시스템 환경 변수로 조정.
# ---------------------------------------------------------------------------

LLM_TEMPERATURE: float = float(os.environ.get("APP_LLM_TEMPERATURE", "0.7"))
_max_tok_raw: str | None = os.environ.get("APP_LLM_MAX_TOKENS")
LLM_MAX_TOKENS: int | None = int(_max_tok_raw) if _max_tok_raw else None

# Agent harness 한 턴에서 허용하는 provider→tool→provider 반복 횟수 상한.
# parquet→spec→chart 3-레이어 파이프라인을 쓰는 에이전트(예: 복합 시나리오 E 의
# 오케스트레이터)는 단일 턴에서 6회 반복이 필요하다. 실 LLM 은 여기에 중간 산출물
# 재구성(wide→long unpivot)·spec self-correct 같은 우회 라운드트립이 2~4회 더
# 끼어드는 것이 관측됐고, 8 은 마지막 사용자 노출 단계(display_*) 직전에 소진됐다
# — 12 로 상향. 남은 2회 시점에 harness 가 wind-down 지시를 주입하므로(R7) 상한에
# 닿기 전에 마무리 유도가 먼저 발동한다.
MAX_AGENT_ITERATIONS: int = int(os.environ.get("APP_MAX_AGENT_ITERATIONS", "12"))

# 한 사용자 turn 에서 오케스트레이터 + 모든 (재귀) 서브 에이전트 합산 provider 호출 상한.
# 무한 위임 루프와 자원 과다 소모를 차단하기 위한 budget.
# 2단 위임 복합 작업(오케스트레이터 6 + analyst 5 + writer 3 ≈ 14)을 수용하려면
# 10 으로는 부족하다. loop-guard·depth-guard 가 별도로 무한루프를 막으므로 20 으로 상향.
MAX_AGENT_CALLS_PER_TURN: int = int(
    os.environ.get("APP_MAX_AGENT_CALLS_PER_TURN", "20")
)

# 한 번의 call_sub_agents_parallel 에서 동시에 실행할 서브 에이전트 수 상한.
# asyncio.Semaphore 로 강제 — 무제한 동시 실행에 따른 자원 폭주(provider 동시 호출·
# 메모리)를 막는다. 상한을 넘는 task 는 슬롯이 빌 때까지 대기한다(취소 아님).
MAX_PARALLEL_SUBAGENTS: int = int(os.environ.get("APP_MAX_PARALLEL_SUBAGENTS", "3"))

# 서브 에이전트 호출 깊이 상한. 0=orchestrator, 1=sub-agent. 2 이상은 거부.
MAX_AGENT_DEPTH: int = int(os.environ.get("APP_MAX_AGENT_DEPTH", "1"))
if MAX_AGENT_DEPTH > 1:
    logging.getLogger(__name__).warning(
        "APP_MAX_AGENT_DEPTH=%d exceeds the recommended limit of 1 — "
        "nested subagent delegation is not officially supported and may cause "
        "unexpected behavior.",
        MAX_AGENT_DEPTH,
    )

# store 가 client 한 명당 보관하는 메시지 수 상한 (system 제외).
MAX_HISTORY_MESSAGES: int = int(os.environ.get("APP_MAX_HISTORY_MESSAGES", "40"))

# summarize-then-drop 압축 토글. 히스토리 슬라이딩 윈도우가 메시지를 버리기 직전
# 그 내용을 LLM 으로 요약해 state.progress_summary 에 접어 망각을 방지한다. 기본 ON.
# best-effort — 요약 콜이 실패해도 기존 요약을 유지하고 턴은 그대로 진행한다.
COMPACTION_ENABLED: bool = os.environ.get(
    "APP_COMPACTION_ENABLED", "true"
).lower() not in ("0", "false", "")

# 세션 첫 턴 사용자 메시지를 state.objective 로 박제할 때의 길이 상한.
OBJECTIVE_MAX_CHARS: int = int(os.environ.get("APP_OBJECTIVE_MAX_CHARS", "500"))

# Tool 1회 실행 timeout (초). 데코레이터에서 도구별로 override 가능.
TOOL_DEFAULT_TIMEOUT: float = float(os.environ.get("APP_TOOL_DEFAULT_TIMEOUT", "30"))

# Dev 전용 디버그 트레이스 토글. frozen EXE 에서는 env 가 있어도 강제 비활성 —
# 운영 빌드에 wire 페이로드(프롬프트 전문)·결정 트레이스가 새어나가지 않게 한다.
DEBUG_TRACE_ENABLED: bool = not getattr(sys, "frozen", False) and os.environ.get(
    "APP_DEBUG_TRACE", "false"
).lower() not in ("0", "false", "")

# 오케스트레이터 baseline api_refs (CSV) — SKILL/서브에이전트 없이도 오케스트레이터가
# 상시 노출받을 라이브러리 dotted-path 목록. 빈 값이면 기존 동작(활성 SKILL 의 api_refs
# 가 있을 때만 라이브러리 API 노출·런타임 도구 주입)과 100% 동일하다. 잘못된 경로는
# collect_api_docs 가 경고 후 skip 하므로 어떤 값이어도 부팅/턴이 깨지지 않는다.
_orch_refs_raw: str = os.environ.get("APP_ORCHESTRATOR_API_REFS", "")
ORCHESTRATOR_API_REFS: list[str] = [
    r.strip() for r in _orch_refs_raw.split(",") if r.strip()
]


# ---------------------------------------------------------------------------
# Legacy env var fallback for initial settings seed (deprecated, use settings file)
# ---------------------------------------------------------------------------

LLM_PROVIDER: str = os.environ.get("APP_LLM_PROVIDER", "mock")
DTGPT_BASE_URL: str | None = os.environ.get("APP_DTGPT_BASE_URL") or None
DTGPT_MODEL: str | None = os.environ.get("APP_DTGPT_MODEL") or None
