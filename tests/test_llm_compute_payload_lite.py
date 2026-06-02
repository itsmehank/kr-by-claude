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
    """build_for_5b 가 analyzed_for_date 최신 행을 prior 로 선택하는지 프로덕션 경로로 검증.

    조건:
      - 행 A: analyzed_for_date=어제(최신), classified_at=2일전(오래됨), pivot=111
      - 행 B: analyzed_for_date=30일전(오래됨), classified_at=방금(최신),   pivot=999

    COALESCE(analyzed_for_date, classified_at::date) DESC → 행 A 선택 → pivot=111
    만약 ORDER BY를 classified_at DESC 로 되돌리면 행 B 선택 → pivot=999 → 테스트 실패
    """
    from datetime import date, timedelta

    from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b

    as_of = date(2026, 5, 20)
    ticker = "AXPL2"

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, 'AxTest', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )
        # 행 A: analyzed_for_date 최신(어제), classified_at 오래됨, pivot_price=111
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source,
                  pattern, pivot_price, pivot_basis, base_high, base_low, base_depth_pct)
               VALUES (%s, %s, %s, 'KOSPI', 'watch', 'weekend',
                       'flat_base', 111, 'range_high', 111, 100, 9.9)""",
            (ticker, as_of - timedelta(days=2), as_of - timedelta(days=1)),
        )
        # 행 B: analyzed_for_date 오래됨(30일전), classified_at 최신, pivot_price=999
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source,
                  pattern, pivot_price, pivot_basis, base_high, base_low, base_depth_pct)
               VALUES (%s, %s, %s, 'KOSPI', 'watch', 'weekend',
                       'flat_base', 999, 'range_high', 999, 900, 9.9)""",
            (ticker, as_of - timedelta(days=0), as_of - timedelta(days=30)),
        )
    db.commit()

    try:
        # 프로덕션 함수를 직접 호출 — 인라인 SQL 이 아니라 실제 ORDER BY 경로를 구동
        payload = build_for_5b(db, ticker, trigger_type="breakout", as_of=as_of)
        assert payload["prior_analysis"]["pivot_price"] == 111.0, (
            f"Expected pivot_price=111 (analyzed_for_date-latest row) but got "
            f"{payload['prior_analysis']['pivot_price']}. "
            "ORDER BY 가 classified_at DESC 로 되돌아갔을 가능성이 있음."
        )
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (ticker,))
            cur.execute("DELETE FROM stocks WHERE ticker=%s", (ticker,))
        db.commit()
