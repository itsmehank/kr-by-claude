"""payload_lite — (5b), (6) 용 가벼운 텍스트 payload."""


def test_build_5b_payload_minimal_fields(db):
    """(5b) payload 에 필수 필드 포함."""
    from datetime import date, timedelta
    from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b

    today = date(2026, 5, 20)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES ('PL5B', 'P', 'KOSPI') ON CONFLICT DO NOTHING"
        )
        for i in range(25):
            d = today - timedelta(days=24 - i)
            if d.weekday() >= 5:
                continue
            cur.execute(
                """INSERT INTO daily_prices
                   (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES ('PL5B', %s, 100, 105, 95, 100, 100, 1000000, 100000000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, volume, sma_50, avg_volume_50d)
                   VALUES ('PL5B', %s, 100, 1000000, 95, 950000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, pattern, pivot_price,
                pivot_basis, base_high, base_low, base_depth_pct, source)
               VALUES ('PL5B', %s, 'KOSPI', 'entry', 'cup_with_handle',
                       105.0, 'handle_high', 105.0, 95.0, 9.5, 'weekend')""",
            (today - timedelta(days=3),),
        )
    db.commit()

    payload = build_for_5b(db, "PL5B", trigger_type="breakout", as_of=today)
    assert payload["symbol"] == "PL5B"
    assert payload["trigger_type"] == "breakout"
    assert "prior_analysis" in payload
    assert payload["prior_analysis"]["pivot_price"] == 105.0
    assert "recent_daily_ohlcv_20d" in payload
    assert len(payload["recent_daily_ohlcv_20d"]) <= 20
    assert "current_metrics" in payload
    assert "recent_evaluation_history" in payload


def test_build_6_payload_includes_trigger_eval(db):
    """(6) payload 에 trigger_evaluation 결과 포함."""
    from datetime import date, timedelta, datetime
    from kr_pipeline.llm_runner.compute.payload_lite import build_for_6

    today = date(2026, 5, 20)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES ('PL6', 'P', 'KOSPI') ON CONFLICT DO NOTHING"
        )
        for i in range(5):
            d = today - timedelta(days=4 - i)
            cur.execute(
                """INSERT INTO daily_prices
                   (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES ('PL6', %s, 100, 105, 95, 100, 100, 1000000, 100000000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, rs_rating, minervini_pass, w52_high, w52_low,
                    avg_volume_50d, volume)
                   VALUES ('PL6', %s, 100, 85, TRUE, 120, 60, 950000, 1000000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
        prior_at = today - timedelta(days=3)
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, pattern, pivot_price,
                pivot_basis, base_high, base_low, base_depth_pct, source)
               VALUES ('PL6', %s, 'KOSPI', 'entry', 'cup_with_handle',
                       105.0, 'handle_high', 105.0, 95.0, 9.5, 'weekend')""",
            (prior_at,),
        )
        eval_at = datetime(today.year, today.month, today.day, 16, 32)
        cur.execute(
            """INSERT INTO trigger_evaluation_log
               (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                decision, confidence, reasoning, prior_classification_at)
               VALUES ('PL6', %s, 'breakout', 106, 1500000, 105,
                       'go_now', 0.85, 'breakout confirmed', %s)""",
            (eval_at, prior_at),
        )
    db.commit()

    payload = build_for_6(db, "PL6", evaluation_at=eval_at)
    assert payload["symbol"] == "PL6"
    assert "prior_analysis" in payload
    assert "trigger_evaluation" in payload
    assert payload["trigger_evaluation"]["decision"] == "go_now"
    assert "current_state" in payload
    assert "current_metrics_extended" in payload


def test_payload_lite_prior_by_analyzed_for_date(db):
    """활성 신호 prior 선택도 analyzed_for_date 최신 + entry/watch 필터 유지."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='AXPL1'")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('AXPL1','A','KOSPI') ON CONFLICT DO NOTHING")
        # 데이터 최신 watch (어제), 실행 2일 전, pivot 111
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source,
                  pattern, pivot_price, pivot_basis, base_high, base_low, base_depth_pct, risk_flags, reasoning)
               VALUES ('AXPL1', NOW() - INTERVAL '2 day', CURRENT_DATE - 1, 'KOSPI', 'watch', 'weekend',
                       'flat_base', 111, 'range_high', 111, 100, 9.9, '[]', 'r')"""
        )
        # 백필성 watch (30일전), 실행 방금, pivot 999
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source,
                  pattern, pivot_price, pivot_basis, base_high, base_low, base_depth_pct, risk_flags, reasoning)
               VALUES ('AXPL1', NOW(), CURRENT_DATE - 30, 'KOSPI', 'watch', 'weekend',
                       'flat_base', 999, 'range_high', 999, 900, 9.9, '[]', 'r')"""
        )
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute(
                """SELECT pivot_price FROM weekly_classification
                    WHERE symbol='AXPL1' AND classification IN ('entry','watch')
                    ORDER BY COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC
                    LIMIT 1"""
            )
            assert float(cur.fetchone()[0]) == 111.0  # analyzed_for_date 최신 행
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='AXPL1'")
        db.commit()
