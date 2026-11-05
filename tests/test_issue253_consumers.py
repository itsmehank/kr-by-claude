"""(#253) 소비처가 COALESCE(effective_pivot, pivot_price) 를 읽는지 — 활성 조회·5b/6 payload.

게이트(get_active_monitoring)와 LLM 입력(prior_analysis.pivot_price)이 서로 다른 pivot 을
쓰면 판정이 어긋나므로 세 경로가 같은 값(effective)을 돌려줘야 한다. 레거시 행(effective NULL)
은 pivot_price 로 폴백.
"""
from datetime import date, datetime, timedelta


def _seed(cur, symbol, *, pivot, effective, today, with_market=True):
    cur.execute(
        "INSERT INTO stocks (ticker, name, market) VALUES (%s, 'E', 'KOSPI') ON CONFLICT DO NOTHING",
        (symbol,),
    )
    cur.execute("DELETE FROM weekly_classification WHERE symbol = %s", (symbol,))
    for i in range(25):
        d = today - timedelta(days=24 - i)
        if d.weekday() >= 5:
            continue
        cur.execute(
            """INSERT INTO daily_prices
               (ticker, date, open, high, low, close, adj_close, volume, value)
               VALUES (%s, %s, 100, 105, 95, 100, 100, 1000000, 100000000)
               ON CONFLICT DO NOTHING""",
            (symbol, d),
        )
        cur.execute(
            """INSERT INTO daily_indicators
               (ticker, date, adj_close, volume, sma_50, avg_volume_50d, rs_rating,
                minervini_pass, w52_high, w52_low)
               VALUES (%s, %s, 100, 1000000, 95, 950000, 85, TRUE, 120, 60)
               ON CONFLICT DO NOTHING""",
            (symbol, d),
        )
    cur.execute(
        """INSERT INTO weekly_classification
           (symbol, classified_at, market, classification, pattern, pivot_price,
            pivot_basis, base_high, base_low, base_depth_pct, source, effective_pivot)
           VALUES (%s, %s, 'KOSPI', 'entry', 'cup_with_handle',
                   %s, 'handle_high', 105.0, 95.0, 9.5, 'weekend', %s)""",
        (symbol, today - timedelta(days=3), pivot, effective),
    )
    if with_market:
        cur.execute(
            """INSERT INTO market_context_daily
               (date, index_code, current_status, distribution_day_count_last_25)
               VALUES (%s, '1001', 'confirmed_uptrend', 2)
               ON CONFLICT (date, index_code) DO UPDATE
                  SET current_status = EXCLUDED.current_status,
                      distribution_day_count_last_25 = EXCLUDED.distribution_day_count_last_25""",
            (today,),
        )


TODAY = date(2026, 5, 20)


def test_get_active_with_current_returns_effective_pivot(db):
    from kr_pipeline.llm_runner.load import get_active_with_current
    with db.cursor() as cur:
        _seed(cur, "RATC1", pivot=105.0, effective=110.0, today=TODAY)
    db.commit()
    rows = {r["symbol"]: r for r in get_active_with_current(db, as_of=TODAY)}
    assert rows["RATC1"]["pivot_price"] == 110.0


def test_get_active_with_current_legacy_null_falls_back(db):
    from kr_pipeline.llm_runner.load import get_active_with_current
    with db.cursor() as cur:
        _seed(cur, "RATC2", pivot=105.0, effective=None, today=TODAY)
    db.commit()
    rows = {r["symbol"]: r for r in get_active_with_current(db, as_of=TODAY)}
    assert rows["RATC2"]["pivot_price"] == 105.0


def test_payload_5b_prior_analysis_uses_effective(db):
    from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b
    with db.cursor() as cur:
        _seed(cur, "RATC3", pivot=105.0, effective=110.0, today=TODAY)
    db.commit()
    payload = build_for_5b(db, "RATC3", trigger_type="breakout", as_of=TODAY)
    assert payload["prior_analysis"]["pivot_price"] == 110.0


def test_payload_6_prior_analysis_uses_effective(db):
    from kr_pipeline.llm_runner.compute.payload_lite import build_for_6
    with db.cursor() as cur:
        _seed(cur, "RATC4", pivot=105.0, effective=110.0, today=TODAY)
        eval_at = datetime(TODAY.year, TODAY.month, TODAY.day, 16, 32)
        cur.execute(
            """INSERT INTO trigger_evaluation_log
               (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                decision, confidence, reasoning, prior_classification_at)
               VALUES ('RATC4', %s, 'breakout', 111, 1500000, 110,
                       'go_now', 0.85, 'breakout confirmed', %s)""",
            (eval_at, TODAY - timedelta(days=3)),
        )
    db.commit()
    payload = build_for_6(db, "RATC4", evaluation_at=eval_at)
    assert payload["prior_analysis"]["pivot_price"] == 110.0
