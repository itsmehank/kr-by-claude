"""store / load DB I/O."""
from datetime import datetime, date, timezone


def test_insert_classification_basic(db):
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('CLS1', 'C', 'KOSPI') ON CONFLICT DO NOTHING")
    db.commit()

    insert_classification(
        db,
        symbol="CLS1",
        classified_at=datetime(2026, 5, 17, 3, 15, tzinfo=timezone.utc),
        market="KOSPI",
        result={
            "classification": "entry",
            "pattern": "cup_with_handle",
            "pivot_price": 80000,
            "pivot_basis": "handle_high",
            "base_high": 80000,
            "base_low": 72000,
            "base_depth_pct": 10.0,
            "base_start_date": "2026-03-01",
            "risk_flags": [],
            "confidence": 0.85,
            "reasoning": "test",
        },
        source="weekend",
        llm_meta={"duration_s": 45.0, "input_tokens": 5000, "output_tokens": 200},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT classification, pattern, pivot_price, expires_at FROM weekly_classification WHERE symbol='CLS1'"
        )
        row = cur.fetchone()
    assert row[0] == "entry"
    assert row[1] == "cup_with_handle"
    assert row[2] == 80000
    # entry 는 expires_at NULL
    assert row[3] is None


def test_insert_watch_sets_expires_at(db):
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('CLS2', 'C', 'KOSPI') ON CONFLICT DO NOTHING")
    db.commit()

    classified_at = datetime(2026, 5, 17, 3, 15, tzinfo=timezone.utc)
    insert_classification(
        db,
        symbol="CLS2",
        classified_at=classified_at,
        market="KOSPI",
        result={
            "classification": "watch",
            "pattern": "flat_base",
            "pivot_price": 50000,
            "pivot_basis": "range_high",
            "base_high": 50000,
            "base_low": 47000,
            "base_depth_pct": 6.0,
            "base_start_date": "2026-04-01",
            "risk_flags": [],
            "confidence": 0.7,
            "reasoning": "test watch",
        },
        source="weekend",
        llm_meta={"duration_s": 30.0, "input_tokens": 4000, "output_tokens": 150},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute("SELECT expires_at FROM weekly_classification WHERE symbol='CLS2'")
        expires_at = cur.fetchone()[0]
    # watch 는 8주 후 만료
    expected_diff = (expires_at - classified_at).days
    assert 55 <= expected_diff <= 57  # 56 ± 1


def test_load_active_monitoring(db):
    """active entry/watch 종목 조회."""
    from datetime import timedelta
    from kr_pipeline.llm_runner.load import get_active_monitoring

    today = date(2026, 5, 20)
    with db.cursor() as cur:
        for t in ["AC1", "AC2", "AC3"]:
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES (%s, 'A', 'KOSPI') ON CONFLICT DO NOTHING",
                (t,),
            )
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, source, pivot_price, base_low)
               VALUES
               ('AC1', %s, 'KOSPI', 'entry', 'weekend', 100, 90),
               ('AC2', %s, 'KOSPI', 'watch', 'weekend', 50, 45),
               ('AC3', %s, 'KOSPI', 'ignore', 'weekend', NULL, NULL)""",
            (today - timedelta(days=2),) * 3,
        )
    db.commit()

    active = get_active_monitoring(db)
    symbols = [a["symbol"] for a in active]
    assert "AC1" in symbols
    assert "AC2" in symbols
    assert "AC3" not in symbols  # ignore 제외


def test_insert_trigger_log(db):
    from datetime import timezone
    from kr_pipeline.llm_runner.store import insert_trigger_log

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('TRG1', 'T', 'KOSPI') ON CONFLICT DO NOTHING")
        prior_at = datetime(2026, 5, 17, 3, 0, tzinfo=timezone.utc)
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, source, pivot_price)
               VALUES ('TRG1', %s, 'KOSPI', 'entry', 'weekend', 100)""",
            (prior_at,),
        )
    db.commit()

    eval_at = datetime(2026, 5, 19, 16, 32, tzinfo=timezone.utc)
    insert_trigger_log(
        db,
        symbol="TRG1",
        evaluated_at=eval_at,
        trigger_type="breakout",
        close=102.0,
        volume=1_500_000,
        pivot_price=100.0,
        result={"decision": "go_now", "confidence": 0.85, "reasoning": "test", "abort_reason": None},
        prior_classification_at=prior_at,
        llm_meta={"duration_s": 12, "input_tokens": 1500, "output_tokens": 80},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute("SELECT decision FROM trigger_evaluation_log WHERE symbol='TRG1'")
        assert cur.fetchone()[0] == "go_now"


def test_insert_entry_params(db):
    from datetime import timezone
    from kr_pipeline.llm_runner.store import insert_entry_params

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('EP1', 'E', 'KOSPI') ON CONFLICT DO NOTHING")
    db.commit()

    signal_at = datetime(2026, 5, 19, 16, 35, tzinfo=timezone.utc)
    insert_entry_params(
        db,
        symbol="EP1",
        signal_at=signal_at,
        result={
            "entry_mode": "pivot_breakout",
            "trigger_price": 80.08,
            "entry_price": 80.5,
            "stop_loss": 75.0,
            "stop_loss_pct_from_pivot": -6.25,
            "stop_loss_pct_from_current_price": -6.83,
            "stop_loss_basis": "logical_pct",
            "expected_target_price": 95.0,
            "expected_target_pct": 18.0,
            "risk_reward_ratio": 2.6,
            "position_size_pct": 5.0,
            "position_size_basis": "test",
            "breakout_volume_requirement": "1.4x",
            "observed_breakout_volume_ratio": 1.55,
            "known_warnings": [],
            "other_warnings": "",
            "notes": "test",
        },
        trigger_evaluation_at=signal_at,
        prior_classification_at=datetime(2026, 5, 17, 3, 0, tzinfo=timezone.utc),
        llm_meta={"duration_s": 30, "input_tokens": 2500, "output_tokens": 200},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute("SELECT entry_mode, entry_price FROM entry_params WHERE symbol='EP1'")
        row = cur.fetchone()
    assert row[0] == "pivot_breakout"
    assert float(row[1]) == 80.5


def test_active_monitoring_latest_by_analyzed_for_date(db):
    """analyzed_for_date 최신 행이 active 판정 기준이 된다."""
    from kr_pipeline.llm_runner.load import get_active_monitoring
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='AXMON1'")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('AXMON1','A','KOSPI') ON CONFLICT DO NOTHING")
        # 데이터 최신 = ignore (어제), 실행은 2일 전
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source)
               VALUES ('AXMON1', NOW() - INTERVAL '2 day', CURRENT_DATE - 1, 'KOSPI', 'ignore', 'weekend')"""
        )
        # 백필성 watch (30일전 데이터), 실행은 방금
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source, pivot_price, base_low)
               VALUES ('AXMON1', NOW(), CURRENT_DATE - 30, 'KOSPI', 'watch', 'weekend', 100, 90)"""
        )
    db.commit()
    try:
        syms = [a["symbol"] for a in get_active_monitoring(db)]
        # 최신은 ignore → active(entry/watch) 목록에서 제외돼야 함
        assert "AXMON1" not in syms
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='AXMON1'")
        db.commit()
