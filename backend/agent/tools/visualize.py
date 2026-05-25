"""시각화 도구 — 채팅창 우측 아티팩트 패널에 이미지·차트를 표시한다.

LLM 이 이 도구를 호출하면 harness 가 ToolResultEvent.data 를 그대로 프론트엔드에
전달하고, 프론트엔드는 data.kind 로 분기해 ArtifactPanel 에 렌더링한다.
"""

from __future__ import annotations

import copy
import logging
from typing import Annotated, Any, Literal

from agent.models import ToolResult
from agent.registries.tools import register_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 경로 허용 목록 — path traversal 방지
# ---------------------------------------------------------------------------

_ALLOWED_PATH_PREFIXES: tuple[str, ...] = (
    "build/web/assets/",
    "build\\web\\assets\\",
    "assets/",
    "assets\\",
    "workspace/",
    "workspace\\",
)


def _resolve_image_source(source: str) -> tuple[str, str | None]:
    """소스 문자열을 프론트엔드가 사용할 URL 로 정규화한다.

    Args:
        source: 이미지 경로 / 절대 URL / data URI

    Returns:
        (resolved_url, error_message | None)
    """
    stripped = source.strip()

    # 1) data URI — 그대로 통과
    if stripped.startswith("data:"):
        if len(stripped) > 4_000_000:
            logger.warning("display_image: data URI 크기가 4MB 초과 — 렌더링 지연 가능")
        return stripped, None

    # 2) 절대 URL — 그대로 통과
    if stripped.startswith(("http://", "https://")):
        return stripped, None

    normalized = stripped.replace("\\", "/")

    # 3) 프로젝트 자산 경로 → /assets/<filename>
    for prefix in ("build/web/assets/", "assets/"):
        if normalized.startswith(prefix):
            rest = normalized[len(prefix) :]
            if not rest or ".." in rest:
                return "", f"허용되지 않는 자산 경로: {source!r}"
            return f"/assets/{rest}", None

    # 4) 워크스페이스 경로 → /workspace/<path>
    if normalized.startswith("workspace/"):
        rest = normalized[len("workspace/") :]
        if not rest or ".." in rest:
            return "", f"허용되지 않는 워크스페이스 경로: {source!r}"
        return f"/workspace/{rest}", None

    return "", (
        f"지원하지 않는 이미지 소스: {source!r}. "
        "data URI, http(s) URL, 'build/web/assets/'·'assets/'·'workspace/' 경로만 허용됩니다."
    )


# ---------------------------------------------------------------------------
# ECharts option 빌더
# ---------------------------------------------------------------------------

_CHART_TYPE_MAP: dict[str, str] = {
    "scatter": "scatter",
    "line": "line",
    "bar": "bar",
    "histogram": "bar",  # ECharts 에 전용 histogram 타입 없음 — bar 로 구현
    "box": "boxplot",
    "heatmap": "heatmap",
}

_TOOLBOX_FEATURE: dict[str, Any] = {
    "brush": {"type": ["rect", "polygon", "clear"]},
    "dataZoom": {},
    "restore": {},
    "saveAsImage": {},
}


def _build_echarts_option(
    chart_type: str,
    series: list[dict[str, Any]],
    title: str | None,
    x_label: str | None,
    y_label: str | None,
    extra_option: dict[str, Any] | None,
) -> dict[str, Any]:
    """간소화 스키마를 ECharts option JSON 으로 변환한다.

    Args:
        chart_type: "scatter" | "line" | "bar" | "histogram" | "box" | "heatmap"
        series: 시리즈 리스트. 각 항목: {"name": str, "data": [...]}
        title: 차트 제목
        x_label: X축 이름
        y_label: Y축 이름
        extra_option: 부분 ECharts option — 깊은 병합으로 base 에 덮어씀

    Returns:
        ECharts option 딕셔너리
    """
    echarts_type = _CHART_TYPE_MAP.get(chart_type, "scatter")
    legend_data = [s.get("name", f"시리즈{i}") for i, s in enumerate(series)]

    if echarts_type == "boxplot":
        option = _build_boxplot_option(series, legend_data, x_label, y_label)
    elif echarts_type == "heatmap":
        option = _build_heatmap_option(series, legend_data, x_label, y_label)
    else:
        option = _build_standard_option(
            echarts_type, series, legend_data, x_label, y_label
        )

    if title:
        option["title"] = {"text": title, "left": "center"}

    if extra_option:
        option = _deep_merge(option, extra_option)

    return option


def _build_standard_option(
    echarts_type: str,
    series: list[dict[str, Any]],
    legend_data: list[str],
    x_label: str | None,
    y_label: str | None,
) -> dict[str, Any]:
    """scatter / line / bar(histogram 포함) 공용 기본 option 을 생성한다."""
    option: dict[str, Any] = {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": legend_data},
        "toolbox": {"feature": _TOOLBOX_FEATURE},
        "brush": {},
        "dataZoom": [{"type": "inside"}, {"type": "slider"}],
        "xAxis": {"type": "value", "name": x_label or ""},
        "yAxis": {"type": "value", "name": y_label or ""},
        "series": [
            {
                "name": s.get("name", f"시리즈{i}"),
                "type": echarts_type,
                "data": s.get("data", []),
                **({"symbolSize": 8} if echarts_type == "scatter" else {}),
            }
            for i, s in enumerate(series)
        ],
    }

    # bar 차트(histogram 포함)는 xAxis category 타입이 자연스러움
    if echarts_type == "bar":
        option["xAxis"]["type"] = "category"

    return option


def _build_boxplot_option(
    series: list[dict[str, Any]],
    legend_data: list[str],
    x_label: str | None,
    y_label: str | None,
) -> dict[str, Any]:
    """boxplot 전용 option 을 생성한다.

    Args:
        series: 각 항목의 data 형식: [[min, Q1, median, Q3, max], ...]
                xAxis category 레이블은 extra_option 으로 덮어쓴다.
    """
    return {
        "tooltip": {"trigger": "item"},
        "legend": {"data": legend_data},
        "toolbox": {"feature": _TOOLBOX_FEATURE},
        "xAxis": {"type": "category", "name": x_label or ""},
        "yAxis": {"type": "value", "name": y_label or ""},
        "series": [
            {
                "name": s.get("name", f"시리즈{i}"),
                "type": "boxplot",
                "data": s.get("data", []),
            }
            for i, s in enumerate(series)
        ],
    }


def _build_heatmap_option(
    series: list[dict[str, Any]],
    legend_data: list[str],
    x_label: str | None,
    y_label: str | None,
) -> dict[str, Any]:
    """heatmap 전용 option 을 생성한다.

    Args:
        series: 각 항목의 data 형식: [[x_idx, y_idx, value], ...]
                xAxis / yAxis category 레이블은 extra_option 으로 덮어쓴다.
    """
    all_values: list[float] = [
        point[2]
        for s in series
        for point in s.get("data", [])
        if isinstance(point, (list, tuple)) and len(point) >= 3
    ]
    return {
        "tooltip": {"trigger": "item"},
        "legend": {"data": legend_data},
        "toolbox": {"feature": _TOOLBOX_FEATURE},
        "xAxis": {"type": "category", "name": x_label or ""},
        "yAxis": {"type": "category", "name": y_label or ""},
        "visualMap": {
            "min": min(all_values, default=0),
            "max": max(all_values, default=1),
            "calculable": True,
            "orient": "horizontal",
            "left": "center",
            "bottom": "15%",
        },
        "series": [
            {
                "name": s.get("name", f"시리즈{i}"),
                "type": "heatmap",
                "data": s.get("data", []),
            }
            for i, s in enumerate(series)
        ],
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """override 를 base 에 재귀 병합한다. list 는 override 가 교체."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# ---------------------------------------------------------------------------
# 도구 등록
# ---------------------------------------------------------------------------

_TYPE_LABEL: dict[str, str] = {
    "scatter": "산점도",
    "line": "꺾은선",
    "bar": "막대",
    "histogram": "히스토그램",
    "box": "박스플롯",
    "heatmap": "히트맵",
}


@register_tool(
    description=(
        "이미지를 채팅창 우측 아티팩트 패널에 표시한다. "
        "source 는 프로젝트 자산 경로('build/web/assets/...' 또는 'assets/...'), "
        "워크스페이스 경로('workspace/...'), "
        "http(s) URL, 또는 data URI 형식을 지원한다."
    ),
    slot_prompts={"source": "표시할 이미지의 경로 또는 URL을 알려주세요."},
    timeout_seconds=5,
)
async def display_image(
    source: Annotated[
        str,
        "이미지 경로(assets/... 또는 workspace/...), 절대 URL, 또는 data URI",
    ],
    alt: Annotated[str, "이미지 대체 텍스트 (접근성·AI 요약용)"] = "",
    caption: Annotated[str, "이미지 아래 표시할 짧은 설명"] = "",
) -> ToolResult:
    """이미지를 아티팩트 패널에 표시한다."""
    resolved, error = _resolve_image_source(source)
    if error:
        return ToolResult(content=f"[display_image 오류] {error}", is_error=True)

    label = alt or caption or source
    return ToolResult(
        content=f"이미지 표시: {label}",
        data={
            "kind": "image",
            "src": resolved,
            "alt": alt,
            "caption": caption,
        },
    )


@register_tool(
    description=(
        "분석 결과를 ECharts 인터랙티브 차트로 아티팩트 패널에 표시한다. "
        "scatter / line / bar / histogram / box / heatmap 타입을 지원하며 "
        "드래그 선택·확대·저장 도구가 자동 포함된다. "
        "extra_option 으로 ECharts option 을 직접 확장하거나, "
        "option 으로 완전한 ECharts option 을 직접 전달할 수 있다."
    ),
    slot_prompts={
        "series": "차트에 표시할 데이터 시리즈를 알려주세요. "
        '예: [{"name": "시리즈명", "data": [[x1,y1], [x2,y2]]}]',
    },
    timeout_seconds=5,
)
async def display_chart(
    series: Annotated[
        list[dict[str, Any]] | None,
        '시리즈 목록. 각 항목: {"name": str, "data": [[x,y], ...] 또는 [v, ...]}. '
        "option 을 직접 전달할 경우 생략 가능.",
    ] = None,
    chart_type: Annotated[
        Literal["scatter", "line", "bar", "histogram", "box", "heatmap"],
        "차트 유형: scatter(산점도) | line(꺾은선) | bar(막대) | histogram(히스토그램) | box(박스플롯) | heatmap(히트맵)",
    ] = "scatter",
    title: Annotated[str, "차트 제목"] = "",
    x_label: Annotated[str, "X축 레이블"] = "",
    y_label: Annotated[str, "Y축 레이블"] = "",
    extra_option: Annotated[
        dict[str, Any] | None,
        "ECharts option 추가 필드 (기본 option 에 deep-merge). 선택 사항.",
    ] = None,
    option: Annotated[
        dict[str, Any] | None,
        "완전한 ECharts option 을 직접 전달. 지정 시 series·chart_type·extra_option 등 무시.",
    ] = None,
) -> ToolResult:
    """ECharts 차트를 아티팩트 패널에 표시한다."""
    if option is not None:
        echarts_option = option
    else:
        if not series:
            return ToolResult(
                content="[display_chart 오류] series 또는 option 중 하나는 필수입니다.",
                is_error=True,
            )
        echarts_option = _build_echarts_option(
            chart_type=chart_type,
            series=series,
            title=title or None,
            x_label=x_label or None,
            y_label=y_label or None,
            extra_option=extra_option,
        )

    type_label = _TYPE_LABEL.get(chart_type, chart_type)
    series_count = len(series) if series is not None else "?"
    return ToolResult(
        content=f"{type_label} 차트 표시 — 시리즈 {series_count}개{f', {title}' if title else ''}",
        data={
            "kind": "chart",
            "chart_type": chart_type,
            "title": title,
            "option": echarts_option,
        },
    )
