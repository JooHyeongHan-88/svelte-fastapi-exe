"""evaluator 큐레이션 툴 검증용 예시 parquet 을 생성한다 (dev 전용).

사용자 예시 표를 재현하되, 예시 표에서 생략됐던 [Sort 기준] 컬럼 ``rank`` 를
item_id 별로 합성해 채운다(A=1, B=2, C=3, D=4 — 상위 노출 순위 가정).

산출물은 dev RESULT_DIR(``<project_root>/result``) 하위에 쓰며, 큐레이션 툴 URL 에
붙일 ``result/...`` 경로를 출력한다. backend 임포트에 의존하지 않도록 경로를 직접
계산한다.

실행::

    uv run python extensions/evaluator/scripts/make_sample.py
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

# extensions/evaluator/scripts/make_sample.py → project_root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RESULT_DIR = _PROJECT_ROOT / "result"
_SESSION = "evaluator-sample"
_LINE_ID = "KFBY"
_STEP = timedelta(minutes=10)

# item_id → (part_id, item_desc, rank). rank 는 예시 표에 없어 합성한 [Sort 기준].
_ITEM_META = {
    "A": ("S5KJN1SQ03-YD0", "it is a", 1),
    "B": ("S5KJN1SQ03-YD0", "it is b", 2),
    "C": ("S5KJN1SQ04-YD0", "it is c", 3),
    "D": ("S5KJN1SQ04-YD0", "it is d", 4),
}

# item_id → [(category, roo_lot_id, base_time, [values...]), ...]
# wafer_id 는 1..n, tkout_time 은 base_time 부터 10분 간격.
_ITEM_GROUPS: dict[str, list[tuple[str, str, datetime, list[int]]]] = {
    "A": [
        ("POR", "XXXX1", datetime(2026, 6, 14, 0, 10), [80, 82, 89, 83]),
        ("NEW", "YYYY1", datetime(2026, 6, 14, 13, 10), [90, 93, 87, 89]),
    ],
    "B": [
        ("POR", "XXXX1", datetime(2026, 6, 14, 0, 10), [82, 89, 89, 80, 84, 90]),
        ("NEW", "YYYY1", datetime(2026, 6, 14, 13, 10), [93, 87, 91, 87, 92]),
    ],
    "C": [
        ("POR", "XXXX1", datetime(2026, 6, 14, 0, 10), [86, 86, 85, 86, 80, 90, 84]),
        ("NEW", "YYYY1", datetime(2026, 6, 14, 13, 10), [91, 89, 91, 89, 88]),
    ],
    "D": [
        ("POR", "XXXX1", datetime(2026, 6, 14, 0, 10), [85, 83, 90, 89, 85]),
        ("NEW", "YYYY1", datetime(2026, 6, 14, 13, 10), [93, 87, 89, 92]),
    ],
}


def _build_rows() -> list[dict]:
    """예시 표를 평탄한 행 딕셔너리 리스트로 전개한다."""
    rows: list[dict] = []
    for item_id, groups in _ITEM_GROUPS.items():
        part_id, item_desc, rank = _ITEM_META[item_id]
        for category, lot_id, base_time, values in groups:
            for offset, value in enumerate(values):
                rows.append(
                    {
                        "line_id": _LINE_ID,
                        "part_id": part_id,
                        "item_id": item_id,
                        "item_desc": item_desc,
                        "rank": rank,
                        "roo_lot_id": lot_id,
                        "wafer_id": offset + 1,
                        "tkout_time": base_time + _STEP * offset,
                        "category": category,
                        "value": value,
                    }
                )
    return rows


def main() -> None:
    """예시 parquet 을 생성하고 큐레이션 URL 에 붙일 경로를 출력한다."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = _RESULT_DIR / _SESSION / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "sample.parquet"

    df = pl.DataFrame(_build_rows())
    df.write_parquet(out)

    rel = f"result/{_SESSION}/{ts}/sample.parquet"
    print(f"[make_sample] {df.height} rows → {out}")
    print(f"[make_sample] 큐레이션 URL 경로: {rel}")
    print(f"[make_sample] 예: http://127.0.0.1:8765/ext/evaluator/?path={rel}")


if __name__ == "__main__":
    main()
