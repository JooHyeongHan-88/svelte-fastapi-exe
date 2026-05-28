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
# 오케스트레이터)는 단일 턴에서 6회 반복이 필요하다. 5 는 여유가 0 이라 한 번만
# 라운드트립이 추가돼도 [max_iterations] 로 중단됐다 — headroom 확보를 위해 8.
MAX_AGENT_ITERATIONS: int = int(os.environ.get("APP_MAX_AGENT_ITERATIONS", "8"))

# 한 사용자 turn 에서 오케스트레이터 + 모든 (재귀) 서브 에이전트 합산 provider 호출 상한.
# 무한 위임 루프와 자원 과다 소모를 차단하기 위한 budget.
# 2단 위임 복합 작업(오케스트레이터 6 + analyst 5 + writer 3 ≈ 14)을 수용하려면
# 10 으로는 부족하다. loop-guard·depth-guard 가 별도로 무한루프를 막으므로 20 으로 상향.
MAX_AGENT_CALLS_PER_TURN: int = int(
    os.environ.get("APP_MAX_AGENT_CALLS_PER_TURN", "20")
)

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

# Tool 1회 실행 timeout (초). 데코레이터에서 도구별로 override 가능.
TOOL_DEFAULT_TIMEOUT: float = float(os.environ.get("APP_TOOL_DEFAULT_TIMEOUT", "30"))


# ---------------------------------------------------------------------------
# Legacy env var fallback for initial settings seed (deprecated, use settings file)
# ---------------------------------------------------------------------------

LLM_PROVIDER: str = os.environ.get("APP_LLM_PROVIDER", "mock")
DTGPT_BASE_URL: str | None = os.environ.get("APP_DTGPT_BASE_URL") or None
DTGPT_MODEL: str | None = os.environ.get("APP_DTGPT_MODEL") or None
