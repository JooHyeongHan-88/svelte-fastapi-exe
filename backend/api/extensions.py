"""확장(extensions) 카탈로그 라우터 — 패널 런처 드롭다운용 목록 제공."""

from fastapi import APIRouter, Depends

from api.deps import require_local_origin
from core.extensions_loader import list_available_extensions

router = APIRouter(prefix="/api", dependencies=[Depends(require_local_origin)])


@router.get("/extensions")
async def get_extensions() -> list[dict[str, str]]:
    """UI 가 있는 확장 목록을 반환한다 (패널 런처 드롭다운 카탈로그).

    각 항목은 ``{tool, name, description, icon}``. 표시 이름·설명은 확장 루트의 선택적
    ``extension.json`` 매니페스트에서 오고, 없으면 폴더명을 그대로 쓴다. 프론트는 부팅
    시 한 번 받아 캐시한다.
    """
    return list_available_extensions()
