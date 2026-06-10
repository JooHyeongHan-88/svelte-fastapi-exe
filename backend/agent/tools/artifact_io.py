"""산출물 재발견·재사용 도구 — 디스크의 과거 artifact 를 다시 작업 입력으로 가져온다.

``save_artifact`` 가 쓰기 방향(namespace → disk)이라면 이 모듈은 읽기 방향이다:

* ``list_artifacts``: 현재 세션의 산출물 목록 조회 (재발견)
* ``load_artifact``: 'result/...' 경로의 파일을 세션 namespace 로 로드 (역방향 브리지)

설계 핵심:
    - 모든 경로 해석은 ``core.result_store.resolve_result_path`` 로 일원화 —
      frozen EXE 에서 CWD 가 프로젝트 루트가 아니어도 RESULT_DIR 절대 기준으로 동작.
    - 세션 rename 으로 ``{title}-{cid8}`` 폴더가 여러 개여도 ``iter_session_dirs``
      가 cid8 접미사로 전부 수집한다.
    - parquet 메타데이터는 pyarrow footer 만 읽어 데이터 본문 로드 비용을 피한다.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Annotated, Any, Literal

from agent.models import ToolResult
from agent.registries.tools import register_tool
from agent.runtime.namespace import current_namespace
from core.result_store import (
    current_client_id,
    iter_session_dirs,
    resolve_result_path,
    to_result_relative,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

# harness 가 서브 에이전트 도구 화이트리스트 우회 시 참조하는 이름 집합.
LIST_ARTIFACTS = "list_artifacts"
LOAD_ARTIFACT = "load_artifact"
ARTIFACT_IO_TOOL_NAMES: frozenset[str] = frozenset({LIST_ARTIFACTS, LOAD_ARTIFACT})

# 산출물 타임스탬프 폴더 규칙 (result_store.artifact_slot 의 strftime 포맷).
_TS_DIR_PATTERN = re.compile(r"^\d{8}-\d{6}$")

# display_chart 가 spec 으로부터 재생성하는 파생 파일 — 목록에서 제외.
_DERIVED_FILENAMES: frozenset[str] = frozenset({"charts.json", "charts.filter.json"})

_EXTENSION_KINDS: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "json",
    ".txt": "text",
    ".parquet": "parquet",
    ".png": "binary",
    ".svg": "binary",
    ".pdf": "binary",
    ".pptx": "binary",
    ".xlsx": "binary",
}

_TEXT_EXTENSIONS: frozenset[str] = frozenset({".md", ".markdown", ".txt"})
_BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".svg", ".pdf", ".pptx", ".xlsx"}
)

_TEXT_PREVIEW_MAX_CHARS = 1500
_LIST_LIMIT_MAX = 100


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------


def _classify_kind(filename: str) -> str:
    """파일명 확장자 → 산출물 kind. 미지의 확장자는 'other'."""
    return _EXTENSION_KINDS.get(Path(filename).suffix.lower(), "other")


def _format_size(size_bytes: int) -> str:
    """바이트 크기를 사람이 읽기 좋은 단위 문자열로 변환한다."""
    kb = size_bytes / 1024
    if kb < 1:
        return f"{size_bytes}B"
    if kb < 1024:
        return f"{kb:.1f}KB"
    return f"{kb / 1024:.2f}MB"


def _read_parquet_shape(path: Path) -> tuple[int, int] | None:
    """parquet footer 메타데이터만 읽어 (rows, cols) 를 반환한다.

    데이터 본문을 로드하지 않으므로 대용량 파일에도 안전하다. 실패 시 None.
    """
    try:
        import pyarrow.parquet as pq

        meta = pq.ParquetFile(path).metadata
        return meta.num_rows, meta.num_columns
    except Exception as exc:  # noqa: BLE001 — 손상 파일 등 어떤 실패든 목록은 계속
        logger.warning("parquet 메타 읽기 실패: %s (%s)", path, exc)
        return None


def _collect_session_files(client_id: str) -> list[Path]:
    """현재 세션의 모든 타임스탬프 슬롯에서 산출물 파일을 수집한다."""
    files: list[Path] = []
    for session_dir in iter_session_dirs(client_id):
        for ts_dir in session_dir.iterdir():
            # _namespace / _artifacts.jsonl 등 내부 관리 항목은 ts 패턴에서 걸러진다.
            if not ts_dir.is_dir() or not _TS_DIR_PATTERN.match(ts_dir.name):
                continue
            files.extend(
                f
                for f in ts_dir.iterdir()
                if f.is_file() and f.name not in _DERIVED_FILENAMES
            )
    return files


def _truncate_preview(text: str) -> str:
    if len(text) <= _TEXT_PREVIEW_MAX_CHARS:
        return text
    return text[: _TEXT_PREVIEW_MAX_CHARS - 3] + "..."


# ---------------------------------------------------------------------------
# 도구 — list_artifacts
# ---------------------------------------------------------------------------


@register_tool(
    description=(
        "현재 세션에서 저장된 산출물(artifact) 파일 목록을 조회한다. "
        "When to use: 과거 턴에 저장한 산출물의 경로를 모르거나 잊었을 때, "
        "사용자가 '아까 그 데이터/보고서' 처럼 과거 산출물을 지칭할 때. "
        "When NOT to use: 방금 save_artifact 가 반환한 경로를 이미 알고 있을 때. "
        "Expected chaining: list_artifacts → load_artifact(path=..., store_as=...) "
        "또는 display_markdown/display_chart(source=...) 재표시. "
        "Returns: 'result/...' 경로·종류·크기 (parquet 은 rows×cols 포함) 목록, 최신순."
    ),
    timeout_seconds=10,
)
async def list_artifacts(
    kind: Annotated[
        Literal["all", "markdown", "json", "text", "parquet", "binary"],
        "필터링할 산출물 종류. 'all' 이면 전체.",
    ] = "all",
    limit: Annotated[int, "반환할 최대 항목 수 (최신순)."] = 20,
) -> ToolResult:
    """현재 세션의 산출물 파일을 최신순으로 나열한다."""
    client_id = current_client_id()
    if not client_id:
        return ToolResult(
            content="[list_artifacts 오류] 세션 컨텍스트가 설정되지 않았습니다.",
            is_error=True,
        )

    limit = max(1, min(limit, _LIST_LIMIT_MAX))

    candidates = _collect_session_files(client_id)
    if kind != "all":
        candidates = [f for f in candidates if _classify_kind(f.name) == kind]

    candidates.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    selected = candidates[:limit]

    if not selected:
        scope = "산출물이" if kind == "all" else f"kind={kind!r} 산출물이"
        return ToolResult(
            content=(
                f"현재 세션에 저장된 {scope} 없습니다. "
                "save_artifact 로 먼저 산출물을 저장하세요."
            ),
        )

    lines: list[str] = [f"현재 세션 산출물 {len(selected)}개 (최신순):"]
    items: list[dict[str, Any]] = []
    for f in selected:
        rel_path = to_result_relative(f)
        file_kind = _classify_kind(f.name)
        size = f.stat().st_size
        detail = f"{file_kind}, {_format_size(size)}"

        item: dict[str, Any] = {
            "path": rel_path,
            "kind": file_kind,
            "size": size,
            "filename": f.name,
            "ts": f.parent.name,
        }
        if file_kind == "parquet":
            shape = _read_parquet_shape(f)
            if shape is not None:
                detail = f"{detail}, {shape[0]}×{shape[1]}"
                item["rows"], item["columns"] = shape

        lines.append(f"- {rel_path} ({detail})")
        items.append(item)

    lines.append(
        "재계산이 필요하면 load_artifact, 단순 재표시는 display_markdown/"
        "display_chart/display_image 에 경로를 그대로 전달하세요."
    )
    return ToolResult(content="\n".join(lines), data={"artifacts": items})


# ---------------------------------------------------------------------------
# 도구 — load_artifact
# ---------------------------------------------------------------------------


@register_tool(
    description=(
        "저장된 산출물 파일을 세션 namespace 변수로 로드한다 (save_artifact 의 역방향). "
        "When to use: 과거 턴/세션에서 저장한 parquet·json 데이터를 후속 분석의 "
        "입력으로 재사용할 때. 예: 이전 분석의 parquet 을 로드해 추가 전처리. "
        "When NOT to use: 단순 재표시(차트·마크다운·이미지) — display_* 도구에 "
        "경로를 직접 전달하면 로드 불필요. "
        "Expected chaining: list_artifacts → load_artifact(path, store_as='df') → "
        "exec_code/eval_expression/call_function 에서 'df' 참조. "
        "확장자별 동작: .parquet→polars DataFrame (store_as 필수), .json→파싱된 객체, "
        ".md/.txt→문자열, .png/.svg/.pdf/.pptx/.xlsx→bytes (store_as 필수)."
    ),
    slot_prompts={
        "path": "로드할 산출물 경로를 알려주세요 (예: result/<session>/<ts>/data.parquet).",
    },
    timeout_seconds=30,
)
async def load_artifact(
    path: Annotated[
        str,
        "산출물 파일 경로 ('result/...' 형식). list_artifacts 또는 save_artifact 가 "
        "반환한 경로를 그대로 사용.",
    ],
    store_as: Annotated[
        str,
        "결과를 저장할 namespace 변수 이름 (Python identifier). "
        "parquet/바이너리는 필수, json/텍스트는 생략 시 내용만 반환.",
    ] = "",
) -> ToolResult:
    """'result/...' 경로의 산출물을 읽어 namespace 에 저장하거나 내용을 반환한다."""
    target, resolve_error = resolve_result_path(path)
    if resolve_error or target is None:
        return ToolResult(
            content=(
                f"[load_artifact 오류] {resolve_error} "
                "list_artifacts 로 현재 세션의 산출물 경로를 확인하세요."
            ),
            is_error=True,
        )

    if not target.is_file():
        return ToolResult(
            content=(
                f"[load_artifact 오류] 파일이 아닙니다: {path!r}. "
                "list_artifacts 로 파일 경로를 확인하세요."
            ),
            is_error=True,
        )

    suffix = target.suffix.lower()

    if suffix == ".parquet":
        return _load_parquet(target, path, store_as)
    if suffix == ".json":
        return _load_json(target, path, store_as)
    if suffix in _TEXT_EXTENSIONS:
        return _load_text(target, path, store_as)
    if suffix in _BINARY_EXTENSIONS:
        return _load_binary(target, path, store_as)

    supported = ".parquet, .json, " + ", ".join(
        sorted(_TEXT_EXTENSIONS | _BINARY_EXTENSIONS)
    )
    return ToolResult(
        content=(
            f"[load_artifact 오류] 지원하지 않는 확장자입니다: {path!r}. "
            f"지원 확장자: {supported}"
        ),
        is_error=True,
    )


# ---------------------------------------------------------------------------
# 확장자별 로더
# ---------------------------------------------------------------------------


def _store_to_namespace(store_as: str, value: Any) -> tuple[Any, str | None]:
    """값을 namespace 에 저장한다. 실패 시 LLM 회신용 오류 메시지를 반환한다."""
    try:
        ns = current_namespace()
    except RuntimeError as exc:
        return None, f"namespace 사용 불가: {exc}"
    try:
        return ns.store(store_as, value), None
    except ValueError as exc:
        return None, str(exc)


def _load_parquet(target: Path, path: str, store_as: str) -> ToolResult:
    """.parquet → polars DataFrame 으로 로드해 namespace 에 저장한다."""
    if not store_as:
        return ToolResult(
            content=(
                "[load_artifact 오류] parquet 로드는 store_as 가 필수입니다. "
                "결과를 저장할 변수 이름을 지정하세요 (예: store_as='df')."
            ),
            is_error=True,
        )

    import polars as pl

    try:
        df = pl.read_parquet(target)
    except (OSError, pl.exceptions.ComputeError) as exc:
        return ToolResult(
            content=f"[load_artifact 오류] parquet 읽기 실패: {exc}",
            is_error=True,
        )

    _, store_error = _store_to_namespace(store_as, df)
    if store_error:
        return ToolResult(content=f"[load_artifact 오류] {store_error}", is_error=True)

    summary = (
        f"로드 완료: {path} → namespace '{store_as}'\n"
        f"({df.height} rows × {df.width} cols)\n"
        f"다음 단계: eval_expression / describe_variable / exec_code 에서 "
        f"'{store_as}' 로 참조 가능."
    )
    return ToolResult(
        content=summary,
        data={
            "kind": "parquet",
            "path": path,
            "name": store_as,
            "rows": df.height,
            "columns": df.width,
            "schema": [
                {"name": col, "dtype": str(dt)} for col, dt in df.schema.items()
            ],
        },
    )


def _load_json(target: Path, path: str, store_as: str) -> ToolResult:
    """.json → 파싱된 객체. store_as 가 있으면 namespace 저장."""
    try:
        text = target.read_text(encoding="utf-8")
        value = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        return ToolResult(
            content=f"[load_artifact 오류] JSON 읽기 실패: {exc}", is_error=True
        )

    if store_as:
        _, store_error = _store_to_namespace(store_as, value)
        if store_error:
            return ToolResult(
                content=f"[load_artifact 오류] {store_error}", is_error=True
            )

    header = (
        f"로드 완료: {path}"
        + (f" → namespace '{store_as}'" if store_as else "")
        + f" ({type(value).__name__})"
    )
    return ToolResult(
        content=f"{header}\n{_truncate_preview(text)}",
        data={"kind": "json", "path": path, "name": store_as or None},
    )


def _load_text(target: Path, path: str, store_as: str) -> ToolResult:
    """.md/.markdown/.txt → 문자열. store_as 가 있으면 namespace 저장."""
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return ToolResult(
            content=f"[load_artifact 오류] 텍스트 읽기 실패: {exc}", is_error=True
        )

    if store_as:
        _, store_error = _store_to_namespace(store_as, text)
        if store_error:
            return ToolResult(
                content=f"[load_artifact 오류] {store_error}", is_error=True
            )

    header = (
        f"로드 완료: {path}"
        + (f" → namespace '{store_as}'" if store_as else "")
        + f" ({len(text)}자)"
    )
    return ToolResult(
        content=f"{header}\n{_truncate_preview(text)}",
        data={"kind": "text", "path": path, "name": store_as or None},
    )


def _load_binary(target: Path, path: str, store_as: str) -> ToolResult:
    """바이너리 산출물 → bytes 로 namespace 에 저장한다."""
    if not store_as:
        return ToolResult(
            content=(
                "[load_artifact 오류] 바이너리 로드는 store_as 가 필수입니다. "
                "단순 재표시라면 load 없이 display_image(source=경로) 를 사용하세요."
            ),
            is_error=True,
        )

    try:
        blob = target.read_bytes()
    except OSError as exc:
        return ToolResult(
            content=f"[load_artifact 오류] 파일 읽기 실패: {exc}", is_error=True
        )

    _, store_error = _store_to_namespace(store_as, blob)
    if store_error:
        return ToolResult(content=f"[load_artifact 오류] {store_error}", is_error=True)

    return ToolResult(
        content=(
            f"로드 완료: {path} → namespace '{store_as}' "
            f"(bytes, {_format_size(len(blob))})"
        ),
        data={
            "kind": "binary",
            "path": path,
            "name": store_as,
            "size": len(blob),
        },
    )
