"""산출물 저장 도구 — LLM 이 직접 텍스트/parquet 파일을 디스크에 기록한다.

display_markdown 등 시각화 도구는 디스크에 사전 존재하는 파일만 표시할 수 있다.
LLM 이 작성한 리포트·분석 데이터를 사용자에게 영속적으로 남기려면 이 도구를
호출해 ``result/<session>/<ts>/<filename>`` 경로에 먼저 저장한 뒤, 반환된 path 를
시각화 도구에 전달하는 표준 체인을 사용한다.

같은 턴 내 여러 번 호출되면 ``core.result_store.turn_slot()`` 캐시 덕분에 같은
타임스탬프 폴더에 모이도록 설계되어 있다.

kind 별 입력:
    - markdown / text        : ``content`` 에 텍스트 직접 입력
    - json                   : ``content`` 에 JSON 문자열 또는 구조화된 객체
                               (dict/list) 모두 허용 — 객체는 자동 직렬화된다.
                               (display_chart spec 처럼 객체 형태가 자연스러운 경우 대응)
    - parquet                : ``source`` 에 namespace 변수 참조 (``"$varname"``)
                               지원 타입: polars.DataFrame, pandas.DataFrame
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Annotated, Any, Literal

from agent.models import ToolResult
from agent.registries.tools import register_tool
from agent.runtime.namespace import current_namespace
from core.config import RESULT_DIR
from core.result_store import append_manifest_entry, turn_slot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수 — kind ↔ 허용 확장자 매핑
# ---------------------------------------------------------------------------

_KIND_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "markdown": (".md", ".markdown"),
    "json": (".json",),
    "text": (".txt",),
    "parquet": (".parquet",),
    "png": (".png",),
    "svg": (".svg",),
    "pdf": (".pdf",),
    "pptx": (".pptx",),
    "xlsx": (".xlsx",),
}

# 바이너리 kind — namespace 의 bytes 변수를 그대로 디스크에 쓴다.
# (LLM 은 JSON 으로 bytes 를 전달할 수 없으므로 content 가 아닌 source 경유.)
_BINARY_KINDS: frozenset[str] = frozenset({"png", "svg", "pdf", "pptx", "xlsx"})

# content 를 사용하는 kind (텍스트 본문). 나머지는 source 사용.
_CONTENT_KINDS: frozenset[str] = frozenset({"markdown", "json", "text"})
_SOURCE_KINDS: frozenset[str] = frozenset({"parquet"}) | _BINARY_KINDS

# 디스크 절대경로를 프론트엔드/시각화 도구가 사용하는 상대 경로 형태로 환원할 때
# 사용되는 접두사. display_markdown 등은 'result/...' 형태를 받는다.
_RESULT_PREFIX = "result/"

# manifest 에 저장할 description 최대 길이 — 폭주 방지 (프롬프트 렌더 시 추가 절단).
_DESCRIPTION_MAX_CHARS = 200


# ---------------------------------------------------------------------------
# 내부 검증 헬퍼
# ---------------------------------------------------------------------------


def _validate_filename(filename: str) -> str | None:
    """filename 안전성 검사. 문제가 있으면 LLM 에 회신할 오류 메시지를 반환한다."""
    if not filename or not filename.strip():
        return "filename 이 비어 있습니다."

    if "/" in filename or "\\" in filename:
        return f"filename 에 경로 구분자가 포함되었습니다: {filename!r}. 단순 파일명만 허용합니다."

    if ".." in filename:
        return f"filename 에 '..' 가 포함되었습니다: {filename!r}. 경로 escape 는 금지됩니다."

    # Windows 절대경로(예: 'C:\\evil.txt') 방어
    if Path(filename).is_absolute() or (len(filename) >= 2 and filename[1] == ":"):
        return f"filename 은 절대 경로가 될 수 없습니다: {filename!r}."

    return None


def _validate_kind_extension(filename: str, kind: str) -> str | None:
    """filename 확장자가 kind 와 일치하는지 확인한다."""
    allowed = _KIND_EXTENSIONS.get(kind)
    if allowed is None:
        return f"지원하지 않는 kind 입니다: {kind!r}."

    lower = filename.lower()
    if not any(lower.endswith(ext) for ext in allowed):
        return (
            f"kind={kind!r} 와 filename 확장자가 일치하지 않습니다: {filename!r}. "
            f"허용 확장자: {', '.join(allowed)}. "
            f"filename 을 올바른 확장자로 바꿔서 다시 호출하세요."
        )

    return None


def _validate_kind_arguments(
    kind: str,
    content: str | dict | list | None,
    source: str | None,
) -> str | None:
    """kind 별 입력 인자 (content/source) 상호 배타성 검증."""
    if kind in _CONTENT_KINDS:
        if content is None:
            return (
                f"kind={kind!r} 는 content 가 필요합니다. "
                "텍스트 본문을 content 인자로 전달하세요."
            )
        if source is not None:
            return (
                f"kind={kind!r} 는 source 를 받지 않습니다. "
                "namespace 변수 저장은 kind='parquet' 또는 바이너리 kind 에서만 가능합니다."
            )
        return None

    if kind in _SOURCE_KINDS:
        if source is None or not source.strip():
            return (
                f"kind={kind!r} 는 source 가 필요합니다. "
                "namespace 변수 참조를 '$varname' 형식으로 전달하세요."
            )
        if content is not None:
            return (
                f"kind={kind!r} 는 content 를 받지 않습니다. "
                "텍스트 본문 저장은 kind='markdown'/'json'/'text' 에서만 가능합니다."
            )
        return None

    return f"지원하지 않는 kind: {kind!r}"


def _resolve_namespace_dataframe(source: str) -> tuple[Any, str | None]:
    """source 문자열 ('$varname') → polars DataFrame 으로 해석한다.

    pandas DataFrame 이면 polars 로 변환. 그 외 타입은 명확한 에러 메시지.

    Returns:
        (polars.DataFrame, None) 성공
        (None, 에러 메시지) 실패
    """
    name = source.strip().lstrip("$").strip()
    if not name or not name.isidentifier():
        return None, (
            f"source 가 namespace 변수 참조 형식이 아닙니다: {source!r}. "
            "예: '$samples_df'"
        )

    try:
        ns = current_namespace()
    except RuntimeError as exc:
        return None, f"namespace 사용 불가: {exc}"

    if not ns.has(name):
        return (
            None,
            f"namespace 에 '{name}' 변수가 없습니다. exec_code/call_function 으로 먼저 생성하세요.",
        )

    value = ns.load(name)

    # polars DataFrame
    try:
        import polars as pl

        if isinstance(value, pl.DataFrame):
            return value, None
        if isinstance(value, pl.Series):
            return value.to_frame(), None
    except ImportError:
        pass

    # pandas DataFrame → polars 변환
    try:
        import pandas as pd

        if isinstance(value, pd.DataFrame):
            import polars as pl

            return pl.from_pandas(value), None
        if isinstance(value, pd.Series):
            import polars as pl

            return pl.from_pandas(value.to_frame()), None
    except ImportError:
        pass

    return None, (
        f"kind='parquet' 는 DataFrame 만 저장할 수 있습니다 (변수 '{name}' 타입: {type(value).__name__}). "
        "polars/pandas DataFrame 으로 변환 후 다시 시도하세요."
    )


def _resolve_namespace_binary(source: str) -> tuple[bytes | None, str | None]:
    """source ('$varname') → bytes 로 해석한다.

    바이너리 산출물(png/pptx/xlsx 등)은 namespace 의 bytes 변수를 그대로 쓴다.
    ``io.BytesIO`` 는 ``.getvalue()`` 로 흡수한다. 그 외 타입은 LLM 이 self-correct
    할 수 있도록 표준 생성 패턴을 안내하는 에러를 반환한다.

    Args:
        source: namespace 변수 참조 ('$png_bytes' 등).

    Returns:
        (bytes, None) 성공 / (None, 에러 메시지) 실패.
    """
    name = source.strip().lstrip("$").strip()
    if not name or not name.isidentifier():
        return None, (
            f"source 가 namespace 변수 참조 형식이 아닙니다: {source!r}. 예: '$png_bytes'"
        )

    try:
        ns = current_namespace()
    except RuntimeError as exc:
        return None, f"namespace 사용 불가: {exc}"

    if not ns.has(name):
        return None, (
            f"namespace 에 '{name}' 변수가 없습니다. "
            "exec_code 에서 바이너리를 먼저 생성하세요."
        )

    value = ns.load(name)
    if isinstance(value, bytes):
        return value, None
    if isinstance(value, bytearray):
        return bytes(value), None
    if isinstance(value, io.BytesIO):
        return value.getvalue(), None

    return None, (
        f"바이너리 kind 는 bytes 만 저장할 수 있습니다 (변수 '{name}' 타입: {type(value).__name__}). "
        "exec_code 에서 다음 패턴으로 bytes 를 만든 뒤 source 로 전달하세요: "
        "buf = io.BytesIO(); fig.savefig(buf, format='png'); png_bytes = buf.getvalue() "
        "→ save_artifact(kind='png', filename='fig.png', source='$png_bytes')."
    )


def _record_manifest(slot: Path, result: ToolResult, description: str) -> None:
    """저장 성공한 산출물을 세션 manifest 에 기록한다.

    ``result.data`` 가 이미 갖춘 kind/path/size/rows/columns 를 재사용하므로,
    저장 분기별 메타를 중복 구성하지 않는다. 기록 실패는 append_manifest_entry
    내부에서 삼켜진다 (save_artifact 본체를 실패시키지 않음).

    Args:
        slot: 이번 턴의 타임스탬프 슬롯 (ts 추출용).
        result: 저장 성공한 ToolResult (data 에 kind/path/size 등 포함).
        description: 산출물 용도 1줄 설명.
    """
    data = result.data or {}
    entry: dict[str, Any] = {
        "ts": slot.name,
        "path": data.get("path", ""),
        "kind": data.get("kind", ""),
        "size": data.get("size", 0),
        "description": description.strip()[:_DESCRIPTION_MAX_CHARS],
    }
    # parquet 은 rows/columns 도 보존해 재발견 시 형태를 바로 알 수 있게 한다.
    if "rows" in data:
        entry["rows"] = data["rows"]
        entry["columns"] = data.get("columns")
    append_manifest_entry(entry)


def _to_relative_path(absolute: Path) -> str:
    """디스크 절대경로를 'result/<session>/<ts>/<file>' 상대 경로로 변환한다."""
    try:
        rel = absolute.relative_to(RESULT_DIR)
    except ValueError:
        logger.warning("save_artifact: target %s is outside RESULT_DIR", absolute)
        return absolute.name
    return _RESULT_PREFIX + str(rel).replace("\\", "/")


# ---------------------------------------------------------------------------
# 도구 등록
# ---------------------------------------------------------------------------


@register_tool(
    description=(
        "마크다운/JSON/텍스트/parquet/바이너리 산출물을 result/<session>/<ts>/<filename> 경로에 저장한다. "
        "When to use: LLM 이 작성한 보고서·분석 데이터·DataFrame·이미지/문서 파일을 사용자에게 "
        "영속적으로 남기고 싶을 때. parquet 은 차트 데이터 직렬화 용 (display_chart 의 spec 이 참조). "
        "When NOT to use: 임시 계산 결과, 한 줄 응답, 또는 사용자가 명시적으로 저장을 원하지 않을 때. "
        "Expected chaining: "
        "(1) save_artifact(kind='markdown', content=...) → display_markdown(source=반환path) "
        "(2) save_artifact(kind='parquet', source='$df', filename='data.parquet') "
        "    → save_artifact(kind='json', content=<ChartSpecV1>, filename='charts.spec.json') "
        "    → display_chart(source=spec path) "
        "(3) exec_code 에서 buf=io.BytesIO(); fig.savefig(buf, format='png'); png=buf.getvalue() "
        "    → save_artifact(kind='png', source='$png', filename='fig.png') → display_image(source=반환path). "
        "kind 별 입력 인자: "
        "markdown/json/text 는 content 필수 (텍스트 본문), "
        "parquet 및 바이너리(png/svg/pdf/pptx/xlsx)는 source 필수 (namespace 변수 참조 '$varname'; "
        "바이너리는 bytes 또는 io.BytesIO 변수). content 와 source 는 상호 배타적. "
        "filename 은 슬래시·역슬래시·'..' 없는 단순 파일명만 허용하며, kind 와 확장자가 일치해야 한다 "
        "(markdown↔.md, json↔.json, text↔.txt, parquet↔.parquet, png↔.png, pptx↔.pptx 등)."
    ),
    slot_prompts={
        "filename": "산출물 파일명을 알려 주세요 (예: report.md, data.parquet).",
        "content": "저장할 본문 텍스트를 주세요 (markdown/json/text 일 때).",
        "source": "namespace 변수 참조를 알려 주세요 (parquet 일 때, 예: '$samples_df').",
    },
    timeout_seconds=10,
)
async def save_artifact(
    filename: Annotated[
        str,
        "저장할 파일명 (확장자 포함, 경로 구분자 금지). 예: 'report.md', 'samples.parquet'.",
    ],
    kind: Annotated[
        Literal[
            "markdown", "json", "text", "parquet", "png", "svg", "pdf", "pptx", "xlsx"
        ],
        "산출물 종류 — markdown(.md), json(.json), text(.txt), parquet(.parquet), "
        "png/svg/pdf/pptx/xlsx(바이너리, namespace bytes 변수 참조).",
    ] = "markdown",
    content: Annotated[
        str | dict | list | None,
        "본문. markdown/text 는 문자열, json 은 유효한 JSON 문자열 또는 구조화된 객체"
        "(dict/list) 모두 허용(객체는 자동 직렬화). markdown/json/text 일 때 필수, parquet 일 때 금지.",
    ] = None,
    source: Annotated[
        str | None,
        "namespace 변수 참조 ('$varname'). parquet 일 때 필수, 그 외 금지. "
        "지원 타입: polars.DataFrame, pandas.DataFrame.",
    ] = None,
    description: Annotated[
        str,
        "이 산출물이 무엇인지 1줄 설명. 채워두면 이후 턴/세션에서 list_artifacts 로 "
        "재발견할 때 LLM 이 용도를 식별할 수 있다 (예: '2026 Q1 매출 원본 데이터').",
    ] = "",
) -> ToolResult:
    """LLM 산출물을 현재 세션의 타임스탬프 슬롯에 저장한다.

    같은 턴 내 다회 호출하면 ``turn_slot()`` 캐시 덕분에 동일 폴더에 모인다.
    저장에 성공하면 display_markdown / display_chart 등 후속 도구가 그대로
    받아들일 수 있는 'result/...' 상대 경로를 ``ToolResult.data['path']`` 로 반환한다.
    성공 시 세션 manifest 에도 한 줄 기록해 이후 재발견을 돕는다.

    Args:
        filename: 저장 파일명 (단순 파일명).
        kind: 산출물 종류.
        content: 저장 본문 텍스트 (kind=markdown/json/text).
        source: namespace 변수 참조 (kind=parquet).
        description: 산출물 용도 1줄 설명 (재발견용, 선택).

    Returns:
        성공: ``ToolResult(content=요약, data={kind, path, size, filename, ...})``
        실패: ``ToolResult(is_error=True, content=원인 + 재시도 유도)``
    """
    filename_error = _validate_filename(filename)
    if filename_error:
        return ToolResult(
            content=f"[save_artifact 오류] {filename_error}",
            is_error=True,
        )

    extension_error = _validate_kind_extension(filename, kind)
    if extension_error:
        return ToolResult(
            content=f"[save_artifact 오류] {extension_error}",
            is_error=True,
        )

    args_error = _validate_kind_arguments(kind, content, source)
    if args_error:
        return ToolResult(
            content=f"[save_artifact 오류] {args_error}",
            is_error=True,
        )

    slot = turn_slot()
    target = slot / filename

    if kind == "parquet":
        result = _save_parquet(target, source or "", filename)
    elif kind in _BINARY_KINDS:
        result = _save_binary(target, source or "", filename, kind)
    else:
        # _validate_kind_arguments 가 content is None 을 이미 걸렀으므로 여기선 비-None 보장.
        result = _save_text(target, kind, content, filename)

    if not result.is_error:
        _record_manifest(slot, result, description)
    return result


# ---------------------------------------------------------------------------
# kind 별 저장 분기
# ---------------------------------------------------------------------------


def _prepare_text_content(
    kind: str, content: str | dict | list | None
) -> tuple[str, str | None]:
    """kind 별 content 를 디스크에 쓸 최종 문자열로 변환·검증한다.

    LLM 은 kind='json' 산출물(차트 spec 등)을 문자열이 아닌 구조화된 객체로
    넘기는 경우가 잦다. 도구 docstring 도 ``content=<ChartSpecV1>`` 처럼 객체를
    유도하므로, 여기서 dict/list 를 받아 직접 직렬화해 타입 불일치를 흡수한다.

    Args:
        kind: 산출물 종류 (markdown/json/text).
        content: 원본 본문 (문자열 또는 json 일 때 dict/list).

    Returns:
        (직렬화된 문자열, None) 성공 / ("", 오류 메시지) 실패.
    """
    if kind == "json":
        if isinstance(content, (dict, list)):
            return json.dumps(content, ensure_ascii=False, indent=2), None
        if isinstance(content, str):
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                return "", (
                    f"kind='json' 이지만 content 가 유효한 JSON 이 아닙니다: "
                    f"{exc.msg} (line {exc.lineno}, col {exc.colno}). "
                    "JSON 형식을 수정해 다시 호출하세요."
                )
            return content, None
        return "", (
            f"kind='json' 의 content 타입이 올바르지 않습니다: {type(content).__name__}. "
            "JSON 문자열 또는 객체(dict/list)를 전달하세요."
        )

    # markdown / text 는 평문 문자열만 허용.
    if not isinstance(content, str):
        return "", (
            f"kind={kind!r} 의 content 는 문자열이어야 합니다 (받은 타입: {type(content).__name__}). "
            "텍스트 본문을 문자열로 전달하세요."
        )
    return content, None


def _save_text(
    target: Path, kind: str, content: str | dict | list | None, filename: str
) -> ToolResult:
    """markdown / json / text 텍스트 저장."""
    text, prepare_error = _prepare_text_content(kind, content)
    if prepare_error:
        return ToolResult(
            content=f"[save_artifact 오류] {prepare_error}",
            is_error=True,
        )

    encoded = text.encode("utf-8")
    target.write_bytes(encoded)

    rel_path = _to_relative_path(target)
    logger.info("save_artifact wrote %d bytes -> %s", len(encoded), target)

    next_step_hint = (
        f"다음 단계로 display_markdown(source='{rel_path}') 호출 가능."
        if kind == "markdown"
        else ""
    )
    summary = f"저장 완료: {rel_path}"
    if next_step_hint:
        summary = f"{summary}\n{next_step_hint}"

    return ToolResult(
        content=summary,
        data={
            "kind": kind,
            "path": rel_path,
            "size": len(encoded),
            "filename": filename,
        },
    )


def _save_parquet(target: Path, source: str, filename: str) -> ToolResult:
    """namespace 의 DataFrame 변수를 parquet 으로 저장."""
    df, resolve_error = _resolve_namespace_dataframe(source)
    if resolve_error or df is None:
        return ToolResult(
            content=f"[save_artifact 오류] {resolve_error}",
            is_error=True,
        )

    try:
        df.write_parquet(target)
    except OSError as exc:
        return ToolResult(
            content=f"[save_artifact 오류] parquet 저장 실패: {exc}",
            is_error=True,
        )

    size = target.stat().st_size
    rel_path = _to_relative_path(target)
    logger.info(
        "save_artifact wrote parquet (%d rows × %d cols, %d bytes) -> %s",
        df.height,
        df.width,
        size,
        target,
    )

    summary = (
        f"저장 완료: {rel_path}\n"
        f"({df.height} rows × {df.width} cols)\n"
        "다음 단계로 charts.spec.json 에서 data.source 로 이 파일명을 참조하세요."
    )

    return ToolResult(
        content=summary,
        data={
            "kind": "parquet",
            "path": rel_path,
            "size": size,
            "filename": filename,
            "rows": df.height,
            "columns": df.width,
            "schema": [
                {"name": col, "dtype": str(dt)} for col, dt in df.schema.items()
            ],
        },
    )


# 이미지로 패널에 바로 표시 가능한 바이너리 kind (display_image 가 받는 형식).
_DISPLAYABLE_BINARY_KINDS: frozenset[str] = frozenset({"png", "svg"})


def _save_binary(target: Path, source: str, filename: str, kind: str) -> ToolResult:
    """namespace 의 bytes 변수를 바이너리 파일로 저장한다 (png/pptx/xlsx 등)."""
    blob, resolve_error = _resolve_namespace_binary(source)
    if resolve_error or blob is None:
        return ToolResult(
            content=f"[save_artifact 오류] {resolve_error}",
            is_error=True,
        )

    try:
        target.write_bytes(blob)
    except OSError as exc:
        return ToolResult(
            content=f"[save_artifact 오류] 바이너리 저장 실패: {exc}",
            is_error=True,
        )

    rel_path = _to_relative_path(target)
    logger.info(
        "save_artifact wrote binary (%d bytes, %s) -> %s", len(blob), kind, target
    )

    if kind in _DISPLAYABLE_BINARY_KINDS:
        next_step_hint = f"다음 단계로 display_image(source='{rel_path}') 호출 가능."
    else:
        # pptx/xlsx/pdf 는 패널 미리보기가 없으므로 다운로드 링크로 안내한다 (/result mount).
        next_step_hint = f"사용자에게 다운로드 링크를 마크다운으로 안내 가능: [{filename}](/{rel_path})."

    return ToolResult(
        content=f"저장 완료: {rel_path}\n{next_step_hint}",
        data={
            "kind": kind,
            "path": rel_path,
            "size": len(blob),
            "filename": filename,
        },
    )
