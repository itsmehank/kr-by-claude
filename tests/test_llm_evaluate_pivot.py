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

    # 이전 테스트 실행에서 남은 EV1 abort 행이 _aborted_since_classification 을 오염할 수 있으므로 사전 제거
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EV1' AND decision='abort'")
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


def test_get_active_with_current_preserves_null_as_none(db):
    """daily_indicators 의 NULL(avg_volume_50d/sma_50/volume)은 0 이 아니라 None 으로
    유지되어야 한다 — 0 강제 시 evaluate_pivot 의 None 가드가 무력화되어
    (i) volume >= 0×mult 가 항상 참 → 거래량 확인 없이 트리거 발화(실 LLM 비용),
    (ii) close < sma_50(=0) invalidation 영구 미발동."""
    from datetime import date
    from kr_pipeline.llm_runner.load import get_active_with_current

    t = "NULGD1"
    as_of = date(2099, 3, 5)  # sentinel 격리
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (t,))
        cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
        # active 모니터링 대상 (entry)
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, pivot_price, source)
               VALUES (%s, NOW(), %s, 'KOSPI', 'entry', 100, 'weekend')""",
            (t, as_of),
        )
        # 지표 행: avg_volume_50d / sma_50 / volume 모두 NULL
        cur.execute(
            "INSERT INTO daily_indicators (ticker, date, adj_close) VALUES (%s, %s, 105)",
            (t, as_of),
        )
    db.commit()

    try:
        rows = get_active_with_current(db, as_of=as_of)
        mine = next(r for r in rows if r["symbol"] == t)
        assert mine["avg_volume_50d"] is None, f"NULL→{mine['avg_volume_50d']!r} 강제됨"
        assert mine["sma_50"] is None, f"NULL→{mine['sma_50']!r} 강제됨"
        assert mine["volume"] is None, f"NULL→{mine['volume']!r} 강제됨"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (t,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
        db.commit()
