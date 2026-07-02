"""SKILLS 카탈로그 라우터."""

from fastapi import APIRouter, Depends

from agent.registries.skills import registry as skill_registry
from api.deps import require_local_origin

router = APIRouter(prefix="/api", dependencies=[Depends(require_local_origin)])


@router.get("/skills")
async def list_skills() -> list[dict]:
    """등록된 모든 skill 의 메타데이터 — 슬래시 커맨드 autocomplete 용.

    body 는 포함하지 않는다 (응답 크기 + lazy 정책). 프론트는 이 목록을 부팅 시
    한 번 받아 캐시한다.
    """
    return [
        {
            "name": meta.name,
            "description": meta.description,
            "trigger": meta.trigger,
            "priority": meta.priority,
        }
        for meta in skill_registry.list_meta(exposed_only=True)
    ]
