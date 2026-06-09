from datetime import date, datetime, timezone


def test_insert_trigger_log_stores_analyzed_for_date(db):
    from kr_pipeline.llm_runner.store import insert_trigger_log
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('WAFD1','x','KOSPI') ON CONFLICT DO NOTHING")
    ev = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    insert_trigger_log(
        db, symbol="WAFD1", evaluated_at=ev, trigger_type="breakout",
        close=100, volume=1000, pivot_price=99,
        result={"decision": "wait", "confidence": 0.5, "reasoning": "x", "abort_reason": None},
        prior_classification_at=ev, llm_meta={"duration_s": 0.1, "input_tokens": None, "output_tokens": None},
        analyzed_for_date=date(2026, 6, 8),
    )
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT analyzed_for_date FROM trigger_evaluation_log WHERE symbol='WAFD1'")
        assert cur.fetchone()[0] == date(2026, 6, 8)


def test_insert_entry_params_stores_analyzed_for_date(db):
    from kr_pipeline.llm_runner.store import insert_entry_params
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('WAFD2','x','KOSPI') ON CONFLICT DO NOTHING")
    sig = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    result = {
        "entry_mode": "pivot_breakout", "pivot_price": 100, "trigger_price": 100, "current_price": 101,
        "stop_loss_price": 92, "stop_loss_pct_from_pivot": -8, "stop_loss_pct_from_current_price": -9,
        "suggested_weight_pct": 5, "expected_target_price": 120, "expected_target_pct": 20,
        "pattern_basis": "flat_base", "entry_window_days": 3, "max_chase_pct_from_pivot": 5,
        "breakout_volume_requirement": "ge_1.4x_50day_avg", "observed_breakout_volume_ratio": 1.6,
        "known_warnings": [], "other_warnings": [], "notes": "x",
    }
    insert_entry_params(
        db, symbol="WAFD2", signal_at=sig, result=result,
        trigger_evaluation_at=sig, prior_classification_at=sig,
        llm_meta={"duration_s": 0.1, "input_tokens": None, "output_tokens": None},
        analyzed_for_date=date(2026, 6, 8),
    )
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT analyzed_for_date FROM entry_params WHERE symbol='WAFD2'")
        assert cur.fetchone()[0] == date(2026, 6, 8)


def test_insert_trigger_log_default_analyzed_for_date_is_null(db):
    from kr_pipeline.llm_runner.store import insert_trigger_log
    from datetime import datetime, timezone
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('WAFD3','x','KOSPI') ON CONFLICT DO NOTHING")
    ev = datetime(2026, 6, 9, 2, 0, tzinfo=timezone.utc)
    insert_trigger_log(
        db, symbol="WAFD3", evaluated_at=ev, trigger_type="breakout",
        close=100, volume=1000, pivot_price=99,
        result={"decision": "wait", "confidence": 0.5, "reasoning": "x", "abort_reason": None},
        prior_classification_at=ev, llm_meta={"duration_s": 0.1, "input_tokens": None, "output_tokens": None},
    )  # analyzed_for_date omitted
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT analyzed_for_date FROM trigger_evaluation_log WHERE symbol='WAFD3'")
        assert cur.fetchone()[0] is None
