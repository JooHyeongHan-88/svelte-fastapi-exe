"""AGENTS/ 디렉토리 기반 서브 에이전트 카탈로그.

오케스트레이터가 위임 결정에 사용할 에이전트 프로필 목록을 관리한다.
부팅 시 Front Matter 만 파싱하고, 본문(에이전트 페르소나)은 실제 위임 시점에
lazy load 한다 — SkillRegistry 와 동일한 패턴.

캐싱 정책:
    - frozen EXE: 1회 읽으면 body 도 영구 캐시.
    - dev: 매 호출 mtime 검사 → 변경되었으면 본문도 재로드 (핫리로드).
"""

import logging
import sys
from pathlib import Path
from typing import Annotated

import frontmatter
from pydantic import BaseModel, Field, ValidationError

from agent.config import AGENTS_DIR

logger = logging.getLogger(__name__)


class AgentMeta(BaseModel):
    """AGENTS/*.md 의 YAML Front Matter 스키마.

    role/goal/when_to_delegate 는 CrewAI 스타일 페르소나 메타데이터로, 오케스트레이터가
    위임 판단을 더 정확히 할 수 있도록 추가됐다. 모두 Optional 이므로 기존 .md 파일은
    변경 없이 그대로 파싱된다.
    """

    name: Annotated[str, "에이전트 식별자 — call_sub_agent 의 agent_name 인자"]
    description: Annotated[str, "오케스트레이터가 위임 결정에 참고할 한 줄 요약"]
    skills: Annotated[
        list[str], "이 에이전트가 전담하는 SKILLS 이름 목록 (Case 3 라우팅)"
    ] = Field(default_factory=list)
    tools: Annotated[
        list[str], "이 에이전트가 노출받을 도구 화이트리스트 — 빈 리스트면 전체"
    ] = Field(default_factory=list)
    priority: Annotated[int, "여러 에이전트가 동일 스킬을 등록했을 때 우선순위"] = 5
    role: Annotated[
        str | None, "에이전트 직무 정체성 한 줄 (예: '시니어 소프트웨어 엔지니어')"
    ] = None
    goal: Annotated[str | None, "에이전트가 달성하려는 궁극 목표 한 줄"] = None
    when_to_delegate: Annotated[
        str | None,
        "오케스트레이터가 이 에이전트에게 위임해야 하는 신호 — 어떤 입력 패턴이 들어오면 위임할지",
    ] = None
    api_refs: Annotated[
        list[str],
        "이 에이전트가 사용하는 라이브러리 dotted-path 목록. 위임 시 introspect 로 "
        "system prompt 에 자동 주입되고, infrastructure tools 가 자동 노출된다.",
    ] = Field(default_factory=list)


class Agent(BaseModel):
    """런타임 에이전트 인스턴스 — meta + lazy load 된 본문 텍스트."""

    meta: AgentMeta
    source_path: Annotated[str, "lazy 본문 로드를 위한 원본 경로"]
    body: Annotated[str, "마크다운 본문 — 비어 있으면 dispatch 시 채움"] = ""


class AgentRegistry:
    """AGENTS/*.md 카탈로그.

    load() 는 부팅 시 1회. 본문은 _ensure_body() 에서 lazy 로드.
    """

    def __init__(self, agents_dir: Path | None = None) -> None:
        self._dir = agents_dir or AGENTS_DIR
        self._agents: list[Agent] = []
        # source_path -> mtime — dev 핫리로드 비교용.
        self._mtimes: dict[str, float] = {}

    def use_directory(self, path: Path) -> None:
        """스캔할 디렉터리를 교체하고 캐시를 비운다(load 전 호출).

        런타임 콘텐츠 동기화(content_sync)가 번들 대신 %APPDATA%/content 의 AGENTS 를
        쓰게 할 때 main.py 가 부팅 시점에 호출한다.
        """
        self._dir = path
        self._agents = []
        self._mtimes = {}

    def load(self) -> None:
        """부팅 시 — Front Matter 만 파싱하고 body 는 비워 둠."""
        if not self._dir.exists():
            logger.warning(
                "AGENTS dir not found: %s — running without sub agents", self._dir
            )
            return

        loaded: list[Agent] = []
        for md in sorted(self._dir.glob("*.md")):
            try:
                post = frontmatter.load(md)
                meta = AgentMeta(**post.metadata)
            except (ValidationError, ValueError, KeyError) as exc:
                logger.warning("agent meta invalid (%s): %s", md.name, exc)
                continue

            loaded.append(Agent(meta=meta, source_path=str(md), body=""))
            self._mtimes[str(md)] = md.stat().st_mtime

        self._agents = loaded
        logger.info("agents loaded: %d from %s", len(loaded), self._dir)

    def list_meta(self) -> list[AgentMeta]:
        """등록된 모든 agent 의 메타데이터 — priority 내림차순(동점은 파일명 순).

        오케스트레이터 카탈로그·Case 3 역매핑이 이 순서를 그대로 신뢰한다. 여러
        에이전트가 같은 스킬을 등록하면 priority 가 높은 에이전트가 전담자로 확정된다.

        Returns:
            list[AgentMeta]: priority 높은 순으로 정렬된 메타데이터. 동일 priority 는
                파일명 순(로드 순)을 유지한다.
        """
        # Why: priority 를 실제 tie-breaker 로 쓰기 위해 정렬. stable sort 라 동점은
        # self._agents(파일명 순) 순서를 보존해 결정론을 유지한다.
        return sorted((a.meta for a in self._agents), key=lambda m: -m.priority)

    def get_by_name(self, name: str) -> Agent | None:
        """call_sub_agent 디스패치 — 정확한 이름 매칭."""
        for a in self._agents:
            if a.meta.name == name:
                return a
        return None

    def cross_check_skills(self, known_skill_names: set[str]) -> None:
        """등록된 에이전트의 skills 가 실제 SKILLS 에 존재하는지 확인 (J-7).

        부팅 시 1회 호출되어 개발자 오타 등을 콘솔 경고로 알린다.
        """
        for a in self._agents:
            missing = [s for s in a.meta.skills if s not in known_skill_names]
            if missing:
                logger.warning(
                    "agent '%s' references unknown skills: %s", a.meta.name, missing
                )

    # ------------------------------------------------------------------ #
    # 내부 헬퍼
    # ------------------------------------------------------------------ #

    def _ensure_body(self, agent: Agent) -> Agent:
        """lazy body load — frozen 은 한 번만, dev 는 mtime 검사."""
        path = Path(agent.source_path)
        if getattr(sys, "frozen", False):
            if not agent.body:
                agent.body = frontmatter.load(path).content
            return agent

        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return agent

        if not agent.body or current_mtime != self._mtimes.get(agent.source_path):
            agent.body = frontmatter.load(path).content
            self._mtimes[agent.source_path] = current_mtime
        return agent


# 모듈 전역 — main.py 가 부팅 시 .load() 호출.
registry = AgentRegistry()
