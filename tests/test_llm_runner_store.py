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


def test_insert_entry_params_roundtrip_s9(db):
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_entry_params
    now = datetime(2026, 6, 7, 1, 0, tzinfo=timezone.utc)
    insert_entry_params(
        db, symbol="RTRIP", signal_at=now, result=_s9_result(),
        trigger_evaluation_at=now, prior_classification_at=now,
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
    )
    # No db.commit(): same-connection INSERT is visible to the SELECT below; committing would break auto-rollback isolation.
    with db.cursor() as cur:
        cur.execute("""SELECT entry_price, stop_loss, position_size_pct, risk_reward_ratio,
                              pivot_price, current_price, pattern_basis, entry_window_days, max_chase_pct_from_pivot
                         FROM entry_params WHERE symbol='RTRIP' AND signal_at=%s""", (now,))
        row = cur.fetchone()
    assert row is not None
    assert float(row[0]) == 192.69
    assert float(row[1]) == 178.96
    assert float(row[2]) == 10.0
    assert round(float(row[3]), 2) == round(20.0/6.9, 2)
    assert float(row[4]) == 192.50 and float(row[5]) == 192.30
    assert row[6] == "flat_base" and row[7] == 3 and float(row[8]) == 5.0


def test_mock_calculate_entry_params_passes_normalize():
    from kr_pipeline.llm_runner.llm.claude_cli import _mock_calculate_entry_params
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    m = _mock_calculate_entry_params()
    n = _normalize_entry_params(m)            # §9 keys present → no ValueError
    assert n["entry_price"] == m["trigger_price"]
    assert n["stop_loss"] == m["stop_loss_price"]
    assert "stop_loss" not in m and "suggested_weight_pct" in m  # §9 keys, not code keys


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


def test_normalize_entry_params_other_warnings_list_serialized():
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    n = _normalize_entry_params(_s9_result(other_warnings=["climax_run", "wide_spread"]))
    assert n["other_warnings"] == '["climax_run", "wide_spread"]'   # list → JSON 문자열(TEXT 컬럼)
    s = _normalize_entry_params(_s9_result(other_warnings="plain"))
    assert s["other_warnings"] == "plain"                            # 문자열은 그대로


def test_risk_flags_taxonomy_has_14():
    from kr_pipeline.llm_runner.risk_flags import RISK_FLAGS_TAXONOMY
    assert len(RISK_FLAGS_TAXONOMY) == 14
    assert "climax_run" in RISK_FLAGS_TAXONOMY and "handle_quality" in RISK_FLAGS_TAXONOMY


def test_validate_classification():
    from kr_pipeline.llm_runner.store import _validate_classification
    import pytest
    assert _validate_classification({"classification": "entry"}) == "entry"
    assert _validate_classification({"classification": "watch"}) == "watch"
    for bad in ({"classification": "buy"}, {}, {"classification": None}):
        with pytest.raises(ValueError, match="invalid classification"):
            _validate_classification(bad)


def test_validate_decision():
    from kr_pipeline.llm_runner.store import _validate_decision
    import pytest
    assert _validate_decision({"decision": "go_now"}) == "go_now"
    for bad in ({"decision": "maybe"}, {}, {"decision": None}):
        with pytest.raises(ValueError, match="invalid decision"):
            _validate_decision(bad)


def test_clean_risk_flags():
    from kr_pipeline.llm_runner.store import _clean_risk_flags
    assert _clean_risk_flags(["climax_run", "bogus", "narrow_base"]) == ["climax_run", "narrow_base"]
    assert _clean_risk_flags([]) == []
    assert _clean_risk_flags(None) == []
    assert _clean_risk_flags("climax_run") == []


def test_insert_classification_rejects_invalid(mocker):
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_classification
    import pytest
    conn = mocker.MagicMock()
    with pytest.raises(ValueError, match="invalid classification"):
        insert_classification(
            conn, symbol="X", classified_at=datetime(2026,6,7,tzinfo=timezone.utc),
            market="KOSPI", result={"classification": "buy"},
            source="daily_delta", llm_meta={},
        )
    conn.cursor.assert_not_called()


def test_insert_backfill_classification_rejects_invalid(mocker):
    from datetime import datetime, timezone, date
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    import pytest
    conn = mocker.MagicMock()
    now = datetime(2026,6,7,tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="invalid classification"):
        insert_backfill_classification(
            conn, symbol="X", classified_at=now, market="KOSPI",
            result={"classification": "buy"}, source="backfill", llm_meta={},
            analyzed_for_date=date(2026,6,7),
        )
    conn.cursor.assert_not_called()


def test_insert_trigger_log_rejects_invalid_decision(mocker):
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_trigger_log
    import pytest
    conn = mocker.MagicMock()
    now = datetime(2026,6,7,tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="invalid decision"):
        insert_trigger_log(
            conn, symbol="X", evaluated_at=now, trigger_type="breakout",
            close=100.0, volume=1000, pivot_price=99.0,
            result={}, prior_classification_at=now, llm_meta={},
        )
    conn.cursor.assert_not_called()


def test_measurements_json_merges_contraction():
    import json
    from kr_pipeline.llm_runner.store import _measurements_json
    out = json.loads(_measurements_json({
        "measurements": {"cup_depth_pct": 30.0},
        "contraction_count": 4,
        "contraction_depths_pct": [25.0, 14.0, 8.0, 4.0],
    }))
    assert out["cup_depth_pct"] == 30.0
    assert out["contraction_count"] == 4
    assert out["contraction_depths_pct"] == [25.0, 14.0, 8.0, 4.0]


def test_measurements_json_measurements_only_unchanged():
    import json
    from kr_pipeline.llm_runner.store import _measurements_json
    out = json.loads(_measurements_json({"measurements": {"cup_depth_pct": 30.0}}))
    assert out == {"cup_depth_pct": 30.0}


def test_measurements_json_none_when_empty():
    from kr_pipeline.llm_runner.store import _measurements_json
    assert _measurements_json({}) is None
    assert _measurements_json({"measurements": None}) is None


def test_measurements_json_contraction_only():
    import json
    from kr_pipeline.llm_runner.store import _measurements_json
    out = json.loads(_measurements_json({"contraction_count": 3, "contraction_depths_pct": [20.0, 10.0, 5.0]}))
    assert out == {"contraction_count": 3, "contraction_depths_pct": [20.0, 10.0, 5.0]}


def test_measurements_json_non_dict_measurements():
    import json
    from kr_pipeline.llm_runner.store import _measurements_json
    out = json.loads(_measurements_json({"measurements": "oops", "contraction_count": 2}))
    assert out == {"contraction_count": 2}
