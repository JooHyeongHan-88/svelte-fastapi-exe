"""SKILLS/ 디렉토리 기반 작업 가이드 라우터.

부팅 시 Front Matter 만 파싱해 메모리에 캐시하고, user_message 트리거에 매칭된
스킬에 한해 그 시점에 body 를 lazy 로 읽는다. RAG 없이도 상황별 지침만 컨텍스트에
주입하는 결정론적 라우팅 계층이다.

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

from agent.config import SKILLS_DIR

logger = logging.getLogger(__name__)


class SkillMeta(BaseModel):
    """SKILLS/*.md 의 YAML Front Matter 스키마."""

    name: Annotated[str, "스킬 식별자 — active_skills 로깅에 사용"]
    description: Annotated[str, "한 줄 요약 — 디버깅 로그용"] = ""
    trigger: Annotated[list[str], "user_message 안에서 찾을 키워드 목록"] = Field(
        default_factory=list
    )
    priority: Annotated[int, "동점 매칭 시 우선순위 — 큰 값이 먼저"] = 5
    requires_tools: Annotated[list[str], "이 스킬이 호출하는 도구 이름 힌트"] = Field(
        default_factory=list
    )
    api_refs: Annotated[
        list[str],
        "라이브러리 dotted-path 목록 (예: 'sensordx.utils.load_df'). 활성화 시 "
        "introspect 로 시그니처·docstring 을 system prompt 에 자동 주입하고, "
        "infrastructure tools(call_function/eval_expression/...)을 자동 노출한다.",
    ] = Field(default_factory=list)


class Skill(BaseModel):
    meta: SkillMeta
    source_path: Annotated[str, "lazy 본문 로드를 위한 원본 경로"]
    body: Annotated[str, "마크다운 본문 — 비어 있으면 select 시 채움"] = ""


class SkillRegistry:
    """SKILLS/*.md 트리거 라우터.

    load() 는 부팅 시 1회. select() 는 매 turn 호출되며 매칭된 스킬의 body 만 lazy 로
    읽는다.
    """

    def __init__(self, skills_dir: Path | None = None) -> None:
        self._dir = skills_dir or SKILLS_DIR
        self._skills: list[Skill] = []
        # source_path -> mtime — dev 핫리로드 비교용.
        self._mtimes: dict[str, float] = {}

    def use_directory(self, path: Path) -> None:
        """스캔할 디렉터리를 교체하고 캐시를 비운다(load 전 호출).

        런타임 콘텐츠 동기화(content_sync)가 번들 대신 %APPDATA%/content 의 SKILLS 를
        쓰게 할 때 main.py 가 부팅 시점에 호출한다.
        """
        self._dir = path
        self._skills = []
        self._mtimes = {}

    def load(self) -> None:
        """부팅 시 — Front Matter 만 파싱하고 body 는 비워 둠."""
        if not self._dir.exists():
            logger.warning(
                "SKILLS dir not found: %s — running without skills", self._dir
            )
            return

        loaded: list[Skill] = []
        for md in sorted(self._dir.glob("*.md")):
            try:
                post = frontmatter.load(md)
                meta = SkillMeta(**post.metadata)
            except (ValidationError, ValueError, KeyError) as exc:
                logger.warning("skill meta invalid (%s): %s", md.name, exc)
                continue

            loaded.append(Skill(meta=meta, source_path=str(md), body=""))
            self._mtimes[str(md)] = md.stat().st_mtime

        self._skills = loaded
        logger.info("skills loaded: %d from %s", len(loaded), self._dir)

    def list_meta(self) -> list[SkillMeta]:
        """등록된 모든 skill 의 메타데이터 — 슬래시 커맨드 autocomplete 용.

        body 는 포함하지 않는다 (lazy load 정책 유지). 외부 직접 접근을 막기 위한
        얇은 read-only 헬퍼.
        """
        return [s.meta for s in self._skills]

    def get_by_names(self, names: list[str]) -> list[Skill]:
        """이름 정확 일치로 skill 들을 조회한다 — 슬래시 커맨드 강제 활성화 경로.

        trigger 매칭을 우회하므로, 본문에 trigger 키워드가 없어도 사용자가
        UI 에서 `/report` 처럼 명시한 skill 이 system prompt 에 포함된다.

        Args:
            names: skill name 목록. 등록되지 않은 이름은 조용히 무시.

        Returns:
            매칭된 Skill 리스트 (body lazy load 완료).
        """
        if not names:
            return []
        by_name = {s.meta.name: s for s in self._skills}
        out: list[Skill] = []
        for n in names:
            s = by_name.get(n)
            if s is not None:
                out.append(self._ensure_body(s))
        return out

    def select(
        self,
        user_message: str,
        max_skills: int = 3,
        available_tools: set[str] | None = None,
    ) -> list[Skill]:
        """user_message 를 trigger 키워드 및 skill 이름과 매칭 → (hit count, priority) 정렬.

        trigger 에 없는 키워드라도 사용자가 skill 이름 자체를 입력했으면 매칭한다.
        예: 'time_lookup' 을 직접 타이핑해도 해당 skill 이 활성화된다.

        Args:
            user_message: 사용자 입력 본문.
            max_skills: 반환할 최대 스킬 수.
            available_tools: 현재 ToolRegistry 에 등록된 도구 이름 집합.
                제공 시 requires_tools 에 없는 도구가 포함된 스킬의 우선순위를 낮춘다.
                None 이면 교차검증을 건너뛰어 기존 동작을 그대로 유지한다.
        """
        if not user_message or not self._skills:
            return []

        lowered = user_message.lower()
        scored: list[tuple[int, int, Skill]] = []
        for s in self._skills:
            # trigger 키워드 매칭 (우선)
            hits = sum(1 for kw in s.meta.trigger if kw.lower() in lowered)
            # trigger 매칭 없으면 skill 이름 자체를 fallback 으로 검사
            if hits == 0 and s.meta.name.lower() in lowered:
                hits = 1
            if hits == 0:
                continue

            priority = s.meta.priority
            # requires_tools 교차검증 — 미등록 도구가 있으면 우선순위를 낮춘다.
            # 완전 제거가 아닌 감점이므로, 더 나은 대안이 없으면 여전히 반환된다.
            if available_tools is not None and s.meta.requires_tools:
                missing_count = len(set(s.meta.requires_tools) - available_tools)
                if missing_count > 0:
                    priority -= missing_count * 10

            scored.append((hits, priority, s))

        scored.sort(key=lambda x: (-x[0], -x[1]))
        return [self._ensure_body(s) for _, _, s in scored[:max_skills]]

    # ------------------------------------------------------------------ #
    # 내부 헬퍼
    # ------------------------------------------------------------------ #

    def _ensure_body(self, skill: Skill) -> Skill:
        """lazy body load — frozen 은 한 번만, dev 는 mtime 검사."""
        path = Path(skill.source_path)
        if getattr(sys, "frozen", False):
            if not skill.body:
                skill.body = frontmatter.load(path).content
            return skill

        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return skill

        if not skill.body or current_mtime != self._mtimes.get(skill.source_path):
            skill.body = frontmatter.load(path).content
            self._mtimes[skill.source_path] = current_mtime
        return skill


# 모듈 전역 — main.py 가 부팅 시 .load() 호출.
registry = SkillRegistry()
