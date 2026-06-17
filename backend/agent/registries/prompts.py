"""PROMPTS/ 디렉토리 기반 시스템 베이스 지침 합성기.

PROMPTS/base.md (페르소나) 와 PROMPTS/safety.md (가드레일) 는 모든 턴의
system prompt 머리에 항상 부착된다. 환경 변수 한 줄로 관리하던 SYSTEM_PROMPT
대신 파일을 분리해 두면 빌드 없이 페르소나/가드레일을 갱신할 수 있다.

캐싱 정책:
    - frozen EXE: MEIPASS 가 read-only 이므로 1회 로드 후 영구 캐시.
    - dev: 매 호출마다 mtime 을 확인해 변경되었으면 즉시 재로드 (핫리로드).
"""

import logging
import sys
from pathlib import Path

from agent.config import PROMPTS_DIR

logger = logging.getLogger(__name__)


class PromptRegistry:
    """PROMPTS/*.md 를 합성해 system prompt 베이스를 만든다."""

    # 합성 순서 — base(페르소나) → safety(가드레일) → tools_guide(도구 사용 철학) → orchestrator(라우팅 규칙).
    # tools_guide.md 는 오케스트레이터·서브 에이전트 양쪽에 모두 적용되도록 orchestrator 보다 앞에 둔다.
    # orchestrator.md 는 오케스트레이터 호출 시에만 포함 (서브 에이전트에는 제외).
    # 이 네 파일 외에 PROMPTS/ 에 추가된 .md 파일은 동적으로 뒤에 이어 붙는다.
    _ORDERED_FILES: tuple[str, ...] = (
        "base.md",
        "safety.md",
        "tools_guide.md",
        "orchestrator.md",
    )
    _ORCHESTRATOR_ONLY: frozenset[str] = frozenset({"orchestrator.md"})

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self._dir = prompts_dir or PROMPTS_DIR
        # path -> (mtime, text) — frozen 에선 mtime=0.0 (의미 없음).
        self._cache: dict[Path, tuple[float, str]] = {}

    def use_directory(self, path: Path) -> None:
        """읽을 디렉터리를 교체하고 캐시를 비운다(load 전 호출).

        런타임 콘텐츠 동기화(content_sync)가 번들 대신 %APPDATA%/content 의 PROMPTS 를
        쓰게 할 때 main.py 가 부팅 시점에 호출한다.
        """
        self._dir = path
        self._cache.clear()

    def load(self) -> None:
        """부팅 시 명시 호출용. dev 에서도 첫 1회는 미리 캐시해 두면 좋다."""
        fixed_count = 0
        for name in self._ORDERED_FILES:
            self._read(self._dir / name)
            if (self._dir / name).exists():
                fixed_count += 1

        dynamic = self._dynamic_files()
        for path in dynamic:
            self._read(path)

        logger.info(
            "prompts loaded from %s (%d fixed + %d dynamic files)",
            self._dir,
            fixed_count,
            len(dynamic),
        )

    def compose(self, fallback: str = "", include_orchestrator: bool = True) -> str:
        """합성된 베이스 텍스트. 모두 비어 있으면 fallback 을 반환.

        고정 순서(base → safety → orchestrator) 뒤에 PROMPTS/ 의 나머지 .md 파일을
        파일명 오름차순으로 동적 삽입한다. 도메인 배경 지식·용어 문서 등을 파일만
        추가해 주입할 때 활용한다.

        Args:
            fallback: 모든 파일이 비어 있을 때 반환할 폴백 문자열.
            include_orchestrator: False 면 orchestrator.md 를 제외한다 — 서브 에이전트는
                4단계 라우팅 규칙을 받지 않아야 한다 (자신이 또 위임을 시도하는 것을 방지).
        """
        parts: list[str] = []

        for name in self._ORDERED_FILES:
            if not include_orchestrator and name in self._ORCHESTRATOR_ONLY:
                continue
            text = self._read(self._dir / name)
            if text:
                parts.append(text)

        for path in self._dynamic_files():
            text = self._read(path)
            if text:
                parts.append(text)

        return "\n\n".join(parts) or fallback

    def _dynamic_files(self) -> list[Path]:
        """고정 파일 외의 .md 파일을 파일명 오름차순으로 반환한다."""
        if not self._dir.exists():
            return []
        fixed = set(self._ORDERED_FILES)
        return sorted(p for p in self._dir.glob("*.md") if p.name not in fixed)

    # ------------------------------------------------------------------ #
    # 내부 헬퍼
    # ------------------------------------------------------------------ #

    def _read(self, path: Path) -> str:
        if not path.exists():
            return ""

        if getattr(sys, "frozen", False):
            cached = self._cache.get(path)
            if cached is not None:
                return cached[1]
            text = path.read_text(encoding="utf-8").strip()
            self._cache[path] = (0.0, text)
            return text

        # dev 핫리로드: mtime 비교 후 변경된 경우만 다시 읽음.
        mtime = path.stat().st_mtime
        cached = self._cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        text = path.read_text(encoding="utf-8").strip()
        self._cache[path] = (mtime, text)
        return text


# 모듈 전역 — main.py 가 부팅 시 .load() 호출, router 가 .compose() 사용.
registry = PromptRegistry()
