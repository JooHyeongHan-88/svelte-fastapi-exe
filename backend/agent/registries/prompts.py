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

    # 합성 순서 — base 가 먼저, safety 가 그 뒤. 파일 부재 시 조용히 건너뜀.
    _ORDERED_FILES: tuple[str, ...] = ("base.md", "safety.md")

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self._dir = prompts_dir or PROMPTS_DIR
        # path -> (mtime, text) — frozen 에선 mtime=0.0 (의미 없음).
        self._cache: dict[Path, tuple[float, str]] = {}

    def load(self) -> None:
        """부팅 시 명시 호출용. dev 에서도 첫 1회는 미리 캐시해 두면 좋다."""
        for name in self._ORDERED_FILES:
            self._read(self._dir / name)
        logger.info(
            "prompts loaded from %s (%d files)",
            self._dir,
            sum(1 for n in self._ORDERED_FILES if (self._dir / n).exists()),
        )

    def compose(self, fallback: str = "") -> str:
        """합성된 베이스 텍스트. 모두 비어 있으면 fallback 을 반환."""
        parts: list[str] = []
        for name in self._ORDERED_FILES:
            text = self._read(self._dir / name)
            if text:
                parts.append(text)
        return "\n\n".join(parts) or fallback

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
