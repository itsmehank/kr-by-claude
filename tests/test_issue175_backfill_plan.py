# tests/test_issue175_backfill_plan.py
"""#175 과거 행 handle_low 소급 스크립트의 순수 집계·인자 가드(DB 없음)."""
import pytest

from kr_pipeline.llm_runner.compute.handle_low_backfill import PK_COLUMNS, plan_rows, require_table_for_apply


def test_plan_rows_counts_fill_and_skip_reasons():
    sl = {"kind": "handle_low", "price": 96.0, "start": "2026-03-09", "end": "2026-03-13", "days": 5}
    rows = [
        ({"fired": False, "structural_low": sl}, None),
        (None, "handle_above_pivot"),
        (None, "right rim not recovered after cup bottom"),
    ]
    assert plan_rows(rows) == {"fill": 1, "skip": {"handle_above_pivot": 1, "right rim not recovered after cup bottom": 1}}


def test_pk_columns_per_table():
    assert PK_COLUMNS["weekly_classification"] == ("symbol", "classified_at")
    for t in ("classification_backfill", "backtest_classification", "recall_audit_classification"):
        assert PK_COLUMNS[t] == ("symbol", "analyzed_for_date")


def test_apply_requires_explicit_table():
    with pytest.raises(SystemExit) as e:
        require_table_for_apply("all")
    assert e.value.code == 2
    assert require_table_for_apply("weekly_classification") == "weekly_classification"
