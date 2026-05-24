"""SKILLS 카탈로그 + 디버그 라우팅 라우터."""

from fastapi import APIRouter, Depends, Query

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
        for meta in skill_registry.list_meta()
    ]


@router.get("/debug/skill-route")
async def debug_skill_route(message: str = Query(...)) -> dict:
    """입력 메시지에 대해 어떤 SKILL 이 매칭되는지 반환한다 (개발·검증용).

    LLM 연결 없이 SKILLS/ 라우팅 동작을 확인할 수 있다.
    예: GET /api/debug/skill-route?message=지금 몇 시야
    """
    matched = skill_registry.select(message)
    return {
        "message": message,
        "matched_skills": [
            {
                "name": s.meta.name,
                "description": s.meta.description,
                "trigger": s.meta.trigger,
                "priority": s.meta.priority,
                "requires_tools": s.meta.requires_tools,
            }
            for s in matched
        ],
    }
