"""insert_classification — analyzed_for_date 인자 동작."""
from datetime import date, datetime, timezone


def test_insert_classification_with_analyzed_for_date(db):
    """analyzed_for_date 인자가 DB 컬럼에 저장됨."""
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='STRA'")
    db.commit()

    insert_classification(
        db,
        symbol="STRA",
        classified_at=datetime.now(timezone.utc),
        market="KOSPI",
        result={
            "classification": "watch",
            "pattern": "flat_base",
            "pivot_price": 1000.0,
            "pivot_basis": "high_of_base",
            "base_high": 1000.0,
            "base_low": 900.0,
            "base_depth_pct": 10.0,
            "base_start_date": "2026-03-01",
            "risk_flags": [],
            "confidence": 0.5,
            "reasoning": "test",
        },
        source="weekend",
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
        analyzed_for_date=date(2026, 5, 18),
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT analyzed_for_date FROM weekly_classification WHERE symbol='STRA'"
        )
        row = cur.fetchone()
    assert row[0] == date(2026, 5, 18)


def test_insert_classification_default_analyzed_for_date_is_null(db):
    """analyzed_for_date 인자 안 주면 컬럼 NULL."""
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='STRB'")
    db.commit()

    insert_classification(
        db,
        symbol="STRB",
        classified_at=datetime.now(timezone.utc),
        market="KOSDAQ",
        result={
            "classification": "ignore",
            "pattern": "none",
            "pivot_price": None,
            "pivot_basis": None,
            "base_high": None,
            "base_low": None,
            "base_depth_pct": None,
            "base_start_date": None,
            "risk_flags": [],
            "confidence": 0.8,
            "reasoning": "test",
        },
        source="daily_delta",
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT analyzed_for_date FROM weekly_classification WHERE symbol='STRB'"
        )
        row = cur.fetchone()
    assert row[0] is None


def test_measurements_column_exists_and_stores(db):
    """measurements JSONB 컬럼에 LLM 측정 블록 저장."""
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='MEAS'")
    db.commit()

    insert_classification(
        db, symbol="MEAS", classified_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
        market="KOSPI",
        result={
            "classification": "watch", "pattern": "cup_with_handle", "confidence": 0.6,
            "reasoning": "x", "risk_flags": [], "pivot_price": None, "pivot_basis": None,
            "base_high": None, "base_low": None, "base_depth_pct": None, "base_start_date": None,
            "measurements": {"cup_depth_pct": 30.0, "prior_uptrend_pct": 40.0, "cup_shape": "U"},
        },
        source="weekend", llm_meta={},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute("SELECT measurements FROM weekly_classification WHERE symbol='MEAS'")
        row = cur.fetchone()
    assert row[0]["cup_shape"] == "U"
    assert row[0]["cup_depth_pct"] == 30.0


def _s9_result(**over):
    r = {
        "entry_mode": "pivot_breakout", "pivot_price": 192.50, "trigger_price": 192.69,
        "current_price": 192.30, "stop_loss_price": 178.96,
        "stop_loss_pct_from_pivot": -7.0, "stop_loss_pct_from_current_price": -6.9,
        "suggested_weight_pct": 10.0, "expected_target_price": 231.00, "expected_target_pct": 20.0,
        "pattern_basis": "flat_base", "entry_window_days": 3, "max_chase_pct_from_pivot": 5.0,
        "breakout_volume_requirement": "ge_1.4x_50day_avg", "observed_breakout_volume_ratio": None,
        "known_warnings": [], "other_warnings": "", "notes": "n",
    }
    r.update(over)
    return r


def test_normalize_entry_params_maps_and_derives():
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    n = _normalize_entry_params(_s9_result())
    assert n["stop_loss"] == 178.96
    assert n["position_size_pct"] == 10.0
    assert n["entry_price"] == 192.69
    assert round(n["risk_reward_ratio"], 2) == round(20.0 / 6.9, 2)
    assert n["stop_loss_basis"] is None and n["position_size_basis"] is None
    assert n["pivot_price"] == 192.50 and n["current_price"] == 192.30
    assert n["pattern_basis"] == "flat_base" and n["entry_window_days"] == 3
    assert n["max_chase_pct_from_pivot"] == 5.0
    assert n["observed_breakout_volume_ratio"] is None


def test_normalize_entry_params_missing_field_raises():
    import pytest
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    bad = _s9_result()
    del bad["stop_loss_price"]
    with pytest.raises(ValueError, match="schema drift"):
        _normalize_entry_params(bad)


def test_normalize_entry_params_rr_zero_and_overflow():
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    assert _normalize_entry_params(_s9_result(stop_loss_pct_from_current_price=0))["risk_reward_ratio"] is None
    assert _normalize_entry_params(_s9_result(stop_loss_pct_from_current_price=-0.01))["risk_reward_ratio"] is None


def test_insert_disqualification(db):
    """시스템 강등 행 — classification='disqualified', source='system_disqualify'."""
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_disqualification
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='DQ1'")
    insert_disqualification(db, symbol="DQ1", classified_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
                            market="KOSPI")
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT classification, source, reasoning FROM weekly_classification WHERE symbol='DQ1'")
        row = cur.fetchone()
    assert row[0] == "disqualified"
    assert row[1] == "system_disqualify"
    assert row[2] is not None
