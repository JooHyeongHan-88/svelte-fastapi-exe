"""확장 테스트가 호스트 백엔드 패키지(core.*/api.*)를 import 할 수 있게 한다.

확장 ``router.py`` 는 ``from core.result_store import ...`` 같은 절대 import 를 쓰므로,
이 테스트들을 격리 실행(`pytest extensions/evaluator/backend/tests`)할 때 호스트
``backend/`` 가 sys.path 에 있어야 한다. 운영 시엔 extensions_loader 가 같은 역할을 한다.
"""

import sys
from pathlib import Path

# .../extensions/evaluator/backend/tests/conftest.py → parents[4] = project_root
_HOST_BACKEND = Path(__file__).resolve().parents[4] / "backend"
if str(_HOST_BACKEND) not in sys.path:
    sys.path.insert(0, str(_HOST_BACKEND))
