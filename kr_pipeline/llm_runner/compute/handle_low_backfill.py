# kr_pipeline/llm_runner/compute/handle_low_backfill.py
"""#175 과거 행 handle_low 소급(spec §7)의 순수 부분 — 집계·PK·인자 가드(DB 없음). 스크립트 = scripts/issue175_handle_low_backfill.py.

소급은 저장 OHLC 에서 재계산 가능한 파생값 기록(governance 1-2). `--apply` 는 운영 DB 쓰기이므로 테이블 명시 + 사용자 승인 후에만.
"""
from __future__ import annotations

import sys
from collections import Counter
from typing import Iterable

PK_COLUMNS: dict[str, tuple[str, ...]] = {
    "weekly_classification": ("symbol", "classified_at"),
    "classification_backfill": ("symbol", "analyzed_for_date"),
    "backtest_classification": ("symbol", "analyzed_for_date"),
    "recall_audit_classification": ("symbol", "analyzed_for_date"),
}
ALL_TABLES = tuple(PK_COLUMNS)


def plan_rows(rows_with_detect: Iterable[tuple[dict | None, str | None]]) -> dict:
    """(검출 결과, skip 사유) 열 → {"fill": 채울 행 수, "skip": {사유: 수}}. 검출 결과가 있고 structural_low 가 있으면 fill."""
    fill, skip = 0, Counter()
    for det, reason in rows_with_detect:
        if det is not None and det.get("structural_low"):
            fill += 1
        else:
            skip[reason or "unknown"] += 1
    return {"fill": fill, "skip": dict(skip)}


def require_table_for_apply(table: str) -> str:
    """`--apply` 는 테이블 하나를 명시해야 한다('all' 금지) — 운영 DB 쓰기 범위를 좁게 고정."""
    if table not in PK_COLUMNS:
        print(f"--apply 는 테이블을 명시해야 합니다(allowlist {list(PK_COLUMNS)}), 받은 값: {table!r}", file=sys.stderr)
        sys.exit(2)
    return table
