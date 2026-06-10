"""pytest 경로 부트스트랩 — backend/ 를 sys.path 에 선주입.

테스트 모듈은 `agent.*`/`api.*`/`core.*` 를 절대 import 하므로 backend/ 가
sys.path 에 있어야 한다. 전체 스위트 실행은 일부 모듈의 sys.path.insert 가
collection 순서 덕에 우연히 통과시켰지만, CLAUDE.md 가 문서화한 단독 파일
실행(`pytest backend/tests/test_x.py -v`)은 ModuleNotFoundError 로 깨졌다.
conftest 는 모든 테스트 모듈 import 전에 로드되므로 단일 진입점으로 해결한다.
"""

import sys
from pathlib import Path

_BACKEND_DIR = str(Path(__file__).resolve().parents[1])
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
