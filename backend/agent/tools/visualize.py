"""시각화 도구 — 채팅창 우측 아티팩트 패널에 이미지·차트·마크다운을 표시한다.

LLM 이 이 도구를 호출하면 harness 가 ToolResultEvent.data 를 그대로 프론트엔드에
전달하고, 프론트엔드는 data.kind 로 분기해 ArtifactPanel 에 렌더링한다.

display_chart 는 ``charts.spec.json`` (ChartSpecV1) 을 읽어 같은 폴더의 parquet
데이터를 로드해 ECharts option 리스트를 생성한 뒤 ``charts.json`` 로 저장한다.
프론트엔드는 ``charts.json`` 만 fetch 하므로 spec 원본은 향후 인터랙티브 재처리를
위해 보존된다.

display_image 는 한 번의 호출로 여러 이미지를 list 로 전달받는다.
display_markdown 은 사전 저장된 .md 파일 한 개를 표시한다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ValidationError

from agent.models import ToolResult
from agent.registries.tools import register_tool
from agent.charts.chart_renderer import render_spec_to_echarts
from agent.charts.chart_spec import ChartSpecV1
from core.config import RESULT_DIR
from core.result_store import current_client_id, read_manifest_entries

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic 입력 항목 모델
# ---------------------------------------------------------------------------


class ImageItem(BaseModel):
    """display_image 의 단일 이미지 항목."""

    source: Annotated[
        str,
        "이미지 경로(assets/... 또는 workspace/... 또는 result/...), 절대 URL, 또는 data URI",
    ]
    alt: Annotated[str, "이미지 대체 텍스트 (접근성·AI 요약용)"] = ""
    caption: Annotated[str, "이미지 아래 표시할 짧은 설명"] = ""


# ---------------------------------------------------------------------------
# 경로 허용 목록 — path traversal 방지
# ---------------------------------------------------------------------------

_DATA_URI_SIZE_WARN_BYTES = 4_000_000

# data.source 미발견 시 안내할 parquet 후보 수와 manifest 조회 폭.
_PARQUET_HINT_LIMIT = 5
_MANIFEST_SCAN_LIMIT = 30

# spec ValidationError 회신에 포함할 상세 오류 수 — 첫 건만 보여주면 LLM 이
# 오류를 하나 고칠 때마다 재호출을 반복한다 (반복 예산 낭비).
_SPEC_ERROR_DETAIL_LIMIT = 3


def _resolve_image_source(source: str) -> tuple[str, str | None]:
    """소스 문자열을 프론트엔드가 사용할 URL 로 정규화한다.

    Args:
        source: 이미지 경로 / 절대 URL / data URI

    Returns:
        (resolved_url, error_message | None)
    """
    stripped = source.strip()

    # data URI — 그대로 통과 (크기만 경고).
    if stripped.startswith("data:"):
        if len(stripped) > _DATA_URI_SIZE_WARN_BYTES:
            logger.warning("display_image: data URI 크기가 4MB 초과 — 렌더링 지연 가능")
        return stripped, None

    # 절대 URL — 그대로 통과.
    if stripped.startswith(("http://", "https://")):
        return stripped, None

    normalized = stripped.replace("\\", "/")

    # 프로젝트 자산 경로 → /assets/<filename>
    for prefix in ("build/web/assets/", "assets/"):
        if normalized.startswith(prefix):
            rest = normalized[len(prefix) :]
            if not rest or ".." in rest:
                return "", f"허용되지 않는 자산 경로: {source!r}"
            return f"/assets/{rest}", None

    # 워크스페이스 경로 → /workspace/<path>
    if normalized.startswith("workspace/"):
        rest = normalized[len("workspace/") :]
        if not rest or ".." in rest:
            return "", f"허용되지 않는 워크스페이스 경로: {source!r}"
        return f"/workspace/{rest}", None

    # 산출물 경로 → /result/<path>
    if normalized.startswith("result/"):
        rest = normalized[len("result/") :]
        if not rest or ".." in rest:
            return "", f"허용되지 않는 산출물 경로: {source!r}"
        return f"/result/{rest}", None

    return "", (
        f"지원하지 않는 이미지 소스: {source!r}. "
        "data URI, http(s) URL, "
        "'build/web/assets/'·'assets/'·'workspace/'·'result/' 경로만 허용됩니다."
    )


def _resolve_image_item(item: ImageItem) -> tuple[dict[str, Any] | None, str | None]:
    """ImageItem → 프론트엔드 payload dict 로 정규화."""
    resolved, error = _resolve_image_source(item.source)
    if error:
        return None, error
    return (
        {"src": resolved, "alt": item.alt, "caption": item.caption},
        None,
    )


def resolve_spec_path(source: str) -> tuple[Path | None, str | None]:
    """display_chart source ('result/...charts.spec.json') → 검증된 절대 Path.

    경로 escape·접두사·확장자·존재 여부를 모두 검사한다. 인터랙티브 필터
    엔드포인트(api/chart.py)도 동일 검증을 재사용하므로 여기서 한 곳에 모은다.

    Args:
        source: save_artifact 가 반환한 'result/...' 형식 spec 파일 경로.

    Returns:
        (spec_path, None) 성공 / (None, 에러 메시지) 실패.
    """
    resolved_url, resolve_error = _resolve_image_source(source)
    if resolve_error:
        return None, resolve_error

    if not resolved_url.startswith("/result/"):
        return None, (
            f"source 는 'result/...' 경로만 허용됩니다: {source!r}. "
            "save_artifact 가 반환한 spec 경로를 그대로 전달하세요."
        )

    rel = resolved_url[len("/result/") :]
    spec_path = RESULT_DIR / rel

    if not spec_path.name.endswith(".spec.json"):
        return None, (
            f"source 파일명은 '.spec.json' 으로 끝나야 합니다: {source!r}. "
            "save_artifact(kind='json', filename='charts.spec.json', content=...) 흐름을 사용하세요."
        )

    if not spec_path.exists():
        return None, f"spec 파일을 찾을 수 없습니다: {source!r}"

    return spec_path, None


def _session_parquet_hint() -> str:
    """data.source 미발견 시 세션 manifest 의 parquet 후보를 안내 문구로 만든다.

    LLM 이 과거 턴 parquet 경로를 추측하다 반복 실패하는 대신, 실제 존재하는
    경로 목록을 받아 한 번에 self-correct 하도록 돕는다.

    Returns:
        "\\n세션에서 사용 가능한 parquet: ..." 형식 힌트. 후보가 없으면 빈 문자열.
    """
    client_id = current_client_id()
    if not client_id:
        return ""
    candidates = [
        str(entry.get("path", ""))
        for entry in read_manifest_entries(client_id, _MANIFEST_SCAN_LIMIT)
        if str(entry.get("path", "")).endswith(".parquet")
    ][:_PARQUET_HINT_LIMIT]
    if not candidates:
        return ""
    joined = ", ".join(candidates)
    return f"\n세션에서 사용 가능한 parquet: {joined}"


# ---------------------------------------------------------------------------
# 도구 등록
# ---------------------------------------------------------------------------


@register_tool(
    description=(
        "이미지(들)를 채팅창 우측 아티팩트 패널에 표시한다. "
        "When to use: 디스크에 존재하는 이미지(스크린샷·차트 이미지·아이콘 등) 또는 "
        "공개 URL 이미지를 사용자에게 보여줄 때. 한 번의 호출로 여러 이미지를 함께 "
        "전달하면 패널이 갤러리 형태(소셜미디어 피드 + lazy load) 로 렌더링한다. "
        "When NOT to use: 파일이 아직 디스크에 없을 때(저장 도구로 먼저 생성), "
        "또는 동적 데이터를 시각화할 때(그 경우 display_chart 사용). "
        "각 item.source 는 프로젝트 자산 경로('build/web/assets/...' 또는 'assets/...'), "
        "워크스페이스 경로('workspace/...'), 산출물 경로('result/<session>/...'), "
        "http(s) URL, 또는 data URI 형식을 지원한다."
    ),
    slot_prompts={
        "images": "표시할 이미지 항목 리스트를 알려주세요. "
        '예: [{"source": "...", "alt": "...", "caption": "..."}]',
    },
    timeout_seconds=5,
)
async def display_image(
    images: Annotated[
        list[ImageItem],
        '표시할 이미지 항목 리스트. 각 항목: {"source": 경로, "alt": 대체텍스트, "caption": 캡션}.',
    ],
) -> ToolResult:
    """이미지를 아티팩트 패널에 표시한다."""
    if not images:
        return ToolResult(
            content="[display_image 오류] images 가 비어 있습니다.",
            is_error=True,
        )

    resolved_items: list[dict[str, Any]] = []
    for idx, item in enumerate(images):
        payload, error = _resolve_image_item(item)
        if error:
            return ToolResult(
                content=f"[display_image 오류] images[{idx}] — {error}",
                is_error=True,
            )
        resolved_items.append(payload)

    return ToolResult(
        content=f"{len(resolved_items)}장 이미지를 패널에 표시했습니다.",
        data={"kind": "image", "items": resolved_items},
    )


@register_tool(
    description=(
        "save_artifact 로 저장한 ChartSpecV1 JSON 파일을 읽어 같은 폴더의 parquet 데이터를 "
        "로드해 ECharts 인터랙티브 차트(들)를 아티팩트 패널에 표시한다. "
        "Expected chaining: "
        "(1) save_artifact(kind='parquet', filename='data.parquet', source='$df'), "
        "(2) save_artifact(kind='json', filename='charts.spec.json', content=<ChartSpecV1>), "
        "(3) display_chart(source='result/.../charts.spec.json'). "
        "ChartSpecV1 스키마: "
        "{version:'1', charts:[{mark, title, data:{source:'<parquet 파일명>'}, "
        "encoding:{x:{field,type,bin?},y:{field,type},color?:{field,type}}, extra_option?}]}. "
        "mark: bar | line | scatter | box | histogram | heatmap | ecdf "
        "(ecdf=경험적 누적분포: quantitative x 만 필요, y 는 자동 누적비율, color 로 그룹별 곡선). "
        "mark별 필수 조건: histogram 은 quantitative x 만 필요(x.bin 은 자동 적용), "
        "box 는 y 필수, heatmap 은 x·y·color 모두 필수(color.type=quantitative), "
        "ecdf 는 quantitative x. "
        "encoding.type: quantitative (수치축) | nominal (범주축) | temporal (시간축). "
        "encoding.color 로 그룹(legend)을 나누려면 데이터가 long 형식이어야 한다 — "
        "그룹 컬럼 1개 + 값 컬럼 1개 (예: columns=[group, value]). 그룹별 wide 컬럼"
        "(group_a/group_b/... 식 컬럼 분리)은 parquet 저장 전에 unpivot 으로 변환하라. "
        "histogram·ecdf·bar·line·scatter 모두 color 를 주면 그룹별 시리즈가 자동 분리되고 "
        "레전드 이름은 color.field 컬럼의 실제 값에서 생성된다 (extra_option 으로 legend.data "
        "를 따로 적지 말 것). "
        "data.source 는 같은 폴더의 parquet 파일명(상대) 또는 이전 턴 parquet 을 재사용할 때 "
        "'result/...' 전체 상대 경로. "
        "When NOT to use: 데이터가 텍스트/표 형태일 때(그 경우 save_artifact + display_markdown)."
    ),
    slot_prompts={
        "source": "표시할 차트 spec 파일 경로를 알려주세요 (예: result/<session>/<ts>/charts.spec.json).",
    },
    timeout_seconds=15,
)
async def display_chart(
    source: Annotated[
        str,
        "save_artifact 가 반환한 'result/...' 형식 charts.spec.json 파일 경로.",
    ],
    title: Annotated[str, "아티팩트 패널 헤더에 표시할 제목"] = "",
) -> ToolResult:
    """ChartSpecV1 spec 파일을 ECharts option 리스트로 렌더링해 아티팩트 패널에 표시한다.

    spec 파일은 보존하고, 같은 폴더에 렌더된 ``charts.json`` 을 생성한다.
    프론트엔드는 ``charts.json`` 만 fetch 한다.
    """
    spec_path, resolve_error = resolve_spec_path(source)
    if resolve_error or spec_path is None:
        return ToolResult(
            content=f"[display_chart 오류] {resolve_error}",
            is_error=True,
        )

    try:
        raw_text = spec_path.read_text(encoding="utf-8")
        raw_spec = json.loads(raw_text)
    except (OSError, json.JSONDecodeError) as exc:
        return ToolResult(
            content=f"[display_chart 오류] spec 파일 읽기/파싱 실패: {exc}",
            is_error=True,
        )

    try:
        spec = ChartSpecV1.model_validate(raw_spec)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()[:_SPEC_ERROR_DETAIL_LIMIT]
        )
        return ToolResult(
            content=(
                f"[display_chart 오류] ChartSpecV1 검증 실패 ({exc.error_count()}건): "
                f"{details}"
            ),
            is_error=True,
        )

    try:
        rendered = render_spec_to_echarts(spec, base_dir=spec_path.parent)
    except FileNotFoundError as exc:
        # data.source 미발견 — 추측 재시도 대신 실존 경로 후보를 함께 회신한다.
        return ToolResult(
            content=f"[display_chart 오류] 렌더링 실패: {exc}{_session_parquet_hint()}",
            is_error=True,
        )
    except ValueError as exc:
        return ToolResult(
            content=f"[display_chart 오류] 렌더링 실패: {exc}",
            is_error=True,
        )

    # 렌더된 결과를 sibling charts.json 으로 저장
    rendered_name = spec_path.name.replace(".spec.json", ".json")
    rendered_path = spec_path.with_name(rendered_name)
    try:
        rendered_path.write_text(
            json.dumps(rendered, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as exc:
        return ToolResult(
            content=f"[display_chart 오류] rendered 파일 저장 실패: {exc}",
            is_error=True,
        )

    rendered_url = "/result/" + str(rendered_path.relative_to(RESULT_DIR)).replace(
        "\\", "/"
    )
    # 인터랙티브 필터(api/chart.py)가 재렌더할 때 참조할 spec 경로. 프론트 칩 payload
    # 는 이 data 통째라 spec 이 localStorage 에 영속 → 재진입 후에도 필터 가능.
    spec_rel = "result/" + str(spec_path.relative_to(RESULT_DIR)).replace("\\", "/")
    logger.info("display_chart rendered %d charts -> %s", len(rendered), rendered_path)

    return ToolResult(
        content=f"{len(rendered)}개 차트를 아티팩트 패널에 표시했습니다.",
        data={
            "kind": "chart",
            "src": rendered_url,
            "spec": spec_rel,
            "title": title,
        },
    )


@register_tool(
    description=(
        "Markdown 산출물 파일을 채팅창 우측 아티팩트 패널에 렌더링한다. "
        "When to use: 사전 저장된 .md 파일(보고서·요약·체크리스트 등)을 사용자에게 보여줄 때. "
        "When NOT to use: 파일이 디스크에 아직 없을 때 — 반드시 save_artifact 로 먼저 저장하고 "
        "반환된 path 를 source 로 전달하라. 짧은 텍스트 한두 줄은 도구 호출 없이 그냥 응답에 쓰면 된다. "
        "Expected chaining: 표준 체인은 save_artifact(kind='markdown') → display_markdown(source=반환path). "
        "source 는 산출물 경로('result/<session>/<file>.md'), "
        "워크스페이스 경로('workspace/...'), 또는 자산 경로('assets/...') 를 지원한다."
    ),
    slot_prompts={
        "source": "표시할 markdown 파일 경로를 알려주세요 (예: result/<session>/report.md)."
    },
    timeout_seconds=5,
)
async def display_markdown(
    source: Annotated[
        str,
        "마크다운 파일 경로 (result/... 또는 workspace/... 또는 assets/...).",
    ],
    title: Annotated[str, "패널 헤더에 표시할 제목"] = "",
) -> ToolResult:
    """Markdown 파일을 아티팩트 패널에 렌더링한다."""
    resolved, error = _resolve_image_source(source)
    if error:
        return ToolResult(content=f"[display_markdown 오류] {error}", is_error=True)

    # 확장자 검증 — markdown 파일만 허용 (다른 텍스트 파일은 별도 도구 권장).
    if not resolved.lower().endswith((".md", ".markdown")):
        return ToolResult(
            content=f"[display_markdown 오류] .md / .markdown 확장자만 허용: {source!r}",
            is_error=True,
        )

    label = title or source
    return ToolResult(
        content=f"마크다운 문서: {label}",
        data={
            "kind": "markdown",
            "src": resolved,
            "title": title,
        },
    )
