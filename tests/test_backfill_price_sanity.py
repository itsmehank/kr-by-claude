# tests/test_backfill_price_sanity.py
# (#50) 백필 insert 경로 가격 sanity — weekly(insert_classification)와 동일하게
# HARD 위반은 저장 거부(fail-closed), SOFT 는 sanity_warnings 컬럼에 기록.
from datetime import datetime, date, timezone

import pytest

BACKFILL_TABLES = (
    "classification_backfill",
    "backtest_classification",
    "recall_audit_classification",
)


def _cls_result(**over):
    """유효한 분류 result 기본형 (HARD 통과값) — test_llm_runner_store 와 동형."""
    r = {
        "classification": "watch", "pattern": "flat_base", "confidence": 0.6,
        "reasoning": "t", "risk_flags": [], "pivot_price": 1000.0,
        "pivot_basis": "high_of_base", "base_high": 1000.0, "base_low": 900.0,
        "base_depth_pct": 10.0, "base_start_date": None,
    }
    r.update(over)
    return r


def _gates_identity(mocker):
    """게이트를 identity 로 patch — sanity 로직만 단위 테스트."""
    mocker.patch(
        "kr_pipeline.llm_runner.store.apply_phase1_gates",
        side_effect=lambda conn, s, t, r: (r, None),
    )


def _insert(db, *, symbol, result, table):
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    insert_backfill_classification(
        db, symbol=symbol, classified_at=datetime(2026, 7, 21, 1, tzinfo=timezone.utc),
        market="KOSPI", result=result, source="backfill",
        llm_meta={"duration_s": 1.0}, analyzed_for_date=date(2022, 4, 9), table=table,
    )


@pytest.mark.parametrize("table", BACKFILL_TABLES)
def test_backfill_sanity_warnings_column_exists(db, table):
    """(#50) 백필 3테이블 모두 sanity_warnings JSONB 컬럼 존재."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT data_type FROM information_schema.columns
             WHERE table_name = %s AND column_name = 'sanity_warnings'
            """,
            (table,),
        )
        row = cur.fetchone()
    assert row is not None, f"{table}.sanity_warnings 컬럼 없음 — schema.sql ALTER 미적용"
    assert row[0] == "jsonb"


def test_backfill_hard_rejects_impossible_prices(db, mocker):
    """HARD: 구조적으로 불가능한 가격은 ValueError + 행 미생성 (fail-closed).

    weekly 와 동일 기준 — 오염 pivot 은 백테스트 지표·트리거 재생의 상류 입력이라
    저장 자체를 거부한다. 워커(run_parallel_batch)가 단건 실패로 격리.
    """
    _gates_identity(mocker)
    cases = [
        {"pivot_price": -100.0},
        {"base_low": 1000.0, "base_high": 900.0},   # low >= high
        {"base_low": 950.0, "pivot_price": 900.0},  # low > pivot
        {"confidence": 1.5},
    ]
    with db.cursor() as cur:
        cur.execute("DELETE FROM classification_backfill WHERE symbol='BFH'")
    db.commit()

    for over in cases:
        with pytest.raises(ValueError, match="sanity"):
            _insert(db, symbol="BFH", result=_cls_result(**over),
                    table="classification_backfill")
        db.rollback()

    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM classification_backfill WHERE symbol='BFH'")
        assert cur.fetchone()[0] == 0, "HARD 위반 백필 분류가 저장됨 (fail-closed 깨짐)"


@pytest.mark.parametrize("table", BACKFILL_TABLES)
def test_backfill_soft_entry_without_pivot_warns(db, mocker, table):
    """SOFT: pivot 없는 entry 는 저장은 되되 sanity_warnings 에 기록 (#50 재현 케이스).

    실증: 표본 B 317870@2022-04-09 — entry + base_high 있는데 pivot_price NULL 이
    무검사 저장돼 §8.5 extended 게이트·트리거가 영원히 skip 되는 행동 불능 행.
    3테이블 공통 — insert 는 단일 경로지만 컬럼 누락은 테이블별로 깨질 수 있다.
    """
    _gates_identity(mocker)
    with db.cursor() as cur:
        cur.execute(f"DELETE FROM {table} WHERE symbol='BFS'")
    db.commit()

    _insert(
        db, symbol="BFS",
        result=_cls_result(classification="entry", pivot_price=None),
        table=table,
    )
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute(f"SELECT sanity_warnings FROM {table} WHERE symbol='BFS'")
            row = cur.fetchone()
        assert row is not None, "SOFT 경고 케이스가 저장되지 않음 (SOFT 는 저장 유지)"
        assert row[0] is not None and "sanity_missing_pivot_for_actionable" in row[0]
    finally:
        with db.cursor() as cur:
            cur.execute(f"DELETE FROM {table} WHERE symbol='BFS'")
        db.commit()


def test_backfill_clean_result_saved_without_warnings(db, mocker):
    """정상값: 저장되고 sanity_warnings 는 NULL (기본 테이블 경로)."""
    _gates_identity(mocker)
    with db.cursor() as cur:
        cur.execute("DELETE FROM classification_backfill WHERE symbol='BFOK'")
    db.commit()

    _insert(db, symbol="BFOK", result=_cls_result(), table="classification_backfill")
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT classification, sanity_warnings FROM classification_backfill "
                "WHERE symbol='BFOK'"
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "watch"
        assert row[1] is None
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='BFOK'")
        db.commit()
