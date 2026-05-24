"""LLM 에이전트 런타임 관련 환경 변수 / 경로.

settings.json 초기 시드값(LLM_PROVIDER 등)은 SettingsStore 가 처음 켜졌을 때
한 번만 채우는 용도로 함께 둔다. 런타임에 사용자가 바꾸는 값은 settings.json
이 진실 공급원이고 여기 시드는 더 이상 읽히지 않는다.
"""

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
# 시스템 프롬프트 — PROMPTS/ 가 비었을 때 사용할 fallback
# ---------------------------------------------------------------------------

SYSTEM_PROMPT: str = os.environ.get(
    "APP_SYSTEM_PROMPT",
    "You are a helpful AI agent. 한국어 사용자에게는 한국어로 친절히 답한다. "
    "필요하면 등록된 도구를 사용해 정확한 정보를 제공한다.",
)


# ---------------------------------------------------------------------------
# LLM 생성 파라미터 — settings.json 대신 환경 변수로 제어한다.
# UI에 노출하지 않고 배포 시 .env 또는 시스템 환경 변수로 조정.
# ---------------------------------------------------------------------------

LLM_TEMPERATURE: float = float(os.environ.get("APP_LLM_TEMPERATURE", "0.7"))
_max_tok_raw: str | None = os.environ.get("APP_LLM_MAX_TOKENS")
LLM_MAX_TOKENS: int | None = int(_max_tok_raw) if _max_tok_raw else None

# Agent harness 한 턴에서 허용하는 provider→tool→provider 반복 횟수 상한.
MAX_AGENT_ITERATIONS: int = int(os.environ.get("APP_MAX_AGENT_ITERATIONS", "5"))

# 한 사용자 turn 에서 오케스트레이터 + 모든 (재귀) 서브 에이전트 합산 provider 호출 상한.
# 무한 위임 루프와 자원 과다 소모를 차단하기 위한 budget.
MAX_AGENT_CALLS_PER_TURN: int = int(
    os.environ.get("APP_MAX_AGENT_CALLS_PER_TURN", "10")
)

# 서브 에이전트 호출 깊이 상한. 0=orchestrator, 1=sub-agent. 2 이상은 거부.
MAX_AGENT_DEPTH: int = int(os.environ.get("APP_MAX_AGENT_DEPTH", "2"))

# store 가 client 한 명당 보관하는 메시지 수 상한 (system 제외).
MAX_HISTORY_MESSAGES: int = int(os.environ.get("APP_MAX_HISTORY_MESSAGES", "40"))


# ---------------------------------------------------------------------------
# Legacy env var fallback for initial settings seed (deprecated, use settings file)
# ---------------------------------------------------------------------------

LLM_PROVIDER: str = os.environ.get("APP_LLM_PROVIDER", "mock")
LLM_BASE_URL: str | None = os.environ.get("APP_LLM_BASE_URL")
LLM_MODEL: str | None = os.environ.get("APP_LLM_MODEL")
LLM_API_KEY: str | None = os.environ.get("APP_LLM_API_KEY")
