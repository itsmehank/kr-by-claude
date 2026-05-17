from datetime import date, datetime, timedelta, timezone


def test_evaluate_pivot_dry_run(db, mocker):
    """active entry 종목 → 결정론 트리거 발동 → (5b) dry-run."""
    today = date(2026, 5, 20)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('EV1', 'E', 'KOSPI') ON CONFLICT DO NOTHING")
        prior_at = datetime(2026, 5, 17, 3, 0, tzinfo=timezone.utc)
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, pattern,
                pivot_price, pivot_basis, base_high, base_low, base_depth_pct, source)
               VALUES ('EV1', %s, 'KOSPI', 'entry', 'cup_with_handle',
                       80, 'handle_high', 80, 70, 12.5, 'weekend')
               ON CONFLICT (symbol, classified_at) DO NOTHING""",
            (prior_at,),
        )
        # Today's bar — breakout
        cur.execute(
            """INSERT INTO daily_prices
               (ticker, date, open, high, low, close, adj_close, volume, value)
               VALUES ('EV1', %s, 82, 84, 81, 83, 83, 2000000, 166000000)
               ON CONFLICT DO NOTHING""",
            (today,),
        )
        cur.execute(
            """INSERT INTO daily_indicators
               (ticker, date, adj_close, volume, sma_50, avg_volume_50d, w52_high, w52_low)
               VALUES ('EV1', %s, 83, 2000000, 78, 1000000, 90, 60)
               ON CONFLICT DO NOTHING""",
            (today,),
        )
        # 20일 history for payload_lite
        for i in range(20):
            d = today - timedelta(days=20 - i)
            if d.weekday() >= 5:
                continue
            cur.execute(
                """INSERT INTO daily_prices
                   (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES ('EV1', %s, 75, 78, 73, 76, 76, 1000000, 76000000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, volume, sma_50, avg_volume_50d, w52_high, w52_low)
                   VALUES ('EV1', %s, 76, 1000000, 78, 1000000, 90, 60)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
    db.commit()

    from kr_pipeline.llm_runner.evaluate_pivot import run

    result = run(db, dry_run=True, as_of=today)
    assert result["evaluated"] >= 1

    with db.cursor() as cur:
        cur.execute(
            "SELECT decision FROM trigger_evaluation_log WHERE symbol='EV1' ORDER BY evaluated_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] in {"go_now", "wait", "abort"}
