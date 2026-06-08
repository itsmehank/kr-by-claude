"""breakout_from_watch end-to-end 배관 (Step 1 + Step 5 통합).

기존 store/load 테스트가 baseline 에서 expires_at 스키마 드리프트로 깨져 있어
(이 변경과 무관) 새 배관(watch_reason 저장·조회 + prev_close + 게이트)을
독립적으로 검증한다.
"""
from datetime import date, datetime, timezone


def _seed_watch(cur, *, symbol, watch_reason, today, prev_close, today_close):
    cur.execute(
        "INSERT INTO stocks (ticker, name, market) VALUES (%s, 'W', 'KOSPI') "
        "ON CONFLICT DO NOTHING",
        (symbol,),
    )
    prior_at = datetime(2026, 5, 17, 3, 0, tzinfo=timezone.utc)
    cur.execute(
        """INSERT INTO weekly_classification
           (symbol, classified_at, market, classification, pattern,
            pivot_price, pivot_basis, base_high, base_low, base_depth_pct,
            source, watch_reason)
           VALUES (%s, %s, 'KOSPI', 'watch', 'cup_with_handle',
                   80, 'handle_high', 80, 70, 12.5, 'weekend', %s)
           ON CONFLICT (symbol, classified_at) DO NOTHING""",
        (symbol, prior_at, watch_reason),
    )
    # 직전 거래일 (pivot 이하)
    cur.execute(
        """INSERT INTO daily_indicators
           (ticker, date, adj_close, volume, sma_50, avg_volume_50d, w52_high, w52_low)
           VALUES (%s, %s, %s, 1000000, 75, 1000000, 90, 60)
           ON CONFLICT DO NOTHING""",
        (symbol, date(2026, 5, 19), prev_close),
    )
    # 오늘 (pivot 돌파 + 거래량)
    cur.execute(
        """INSERT INTO daily_indicators
           (ticker, date, adj_close, volume, sma_50, avg_volume_50d, w52_high, w52_low)
           VALUES (%s, %s, %s, 2000000, 75, 1000000, 90, 60)
           ON CONFLICT DO NOTHING""",
        (symbol, today, today_close),
    )


def test_get_active_with_current_exposes_prev_close_and_watch_reason(db):
    today = date(2026, 5, 20)
    with db.cursor() as cur:
        _seed_watch(cur, symbol="WAT1", watch_reason="valid_base_awaiting_breakout",
                    today=today, prev_close=79, today_close=83)
    db.commit()

    from kr_pipeline.llm_runner.load import get_active_with_current
    rows = {r["symbol"]: r for r in get_active_with_current(db, as_of=today)}
    assert "WAT1" in rows
    row = rows["WAT1"]
    assert row["watch_reason"] == "valid_base_awaiting_breakout"
    assert row["prev_close"] == 79.0
    assert row["classification"] == "watch"


def test_loaded_watch_row_yields_breakout_from_watch(db):
    """fresh cross 한 ALLOWED watch → 게이트가 breakout_from_watch."""
    today = date(2026, 5, 20)
    with db.cursor() as cur:
        _seed_watch(cur, symbol="WAT2", watch_reason="valid_base_awaiting_breakout",
                    today=today, prev_close=79, today_close=83)
    db.commit()

    from kr_pipeline.llm_runner.load import get_active_with_current
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    row = next(r for r in get_active_with_current(db, as_of=today) if r["symbol"] == "WAT2")
    trig = evaluate(
        close=row["close"], pivot_price=row["pivot_price"],
        volume=row["volume"], avg_volume_50d=row["avg_volume_50d"],
        stop_loss=row["stop_loss"], sma_50=row["sma_50"],
        classification=row["classification"],
        prev_close=row["prev_close"], watch_reason=row["watch_reason"],
    )
    assert trig == "breakout_from_watch"


def test_base_forming_watch_row_yields_promotion_not_breakout(db):
    """비-ALLOWED(base_forming) watch 는 fresh cross 여도 promotion (D2)."""
    today = date(2026, 5, 20)
    with db.cursor() as cur:
        _seed_watch(cur, symbol="WAT3", watch_reason="base_forming",
                    today=today, prev_close=79, today_close=83)
    db.commit()

    from kr_pipeline.llm_runner.load import get_active_with_current
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    row = next(r for r in get_active_with_current(db, as_of=today) if r["symbol"] == "WAT3")
    trig = evaluate(
        close=row["close"], pivot_price=row["pivot_price"],
        volume=row["volume"], avg_volume_50d=row["avg_volume_50d"],
        stop_loss=row["stop_loss"], sma_50=row["sma_50"],
        classification=row["classification"],
        prev_close=row["prev_close"], watch_reason=row["watch_reason"],
    )
    assert trig == "promotion"


def test_fetch_go_now_candidates_includes_breakout_from_watch(db):
    """entry_params 후보 SQL 이 breakout_from_watch 도 breakout 과 함께 수집 (Step 4)."""
    from kr_pipeline.llm_runner.entry_params import _fetch_go_now_candidates
    as_of = date(2027, 3, 15)  # 충돌 회피용 고유 날짜
    eval_at = datetime(2027, 3, 15, 6, 0, tzinfo=timezone.utc)
    classified = datetime(2027, 3, 10, tzinfo=timezone.utc)
    with db.cursor() as cur:
        for sym, ttype in [("BFW_A", "breakout_from_watch"), ("BFW_B", "breakout"),
                           ("BFW_C", "promotion")]:
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,%s,'KOSPI') "
                        "ON CONFLICT DO NOTHING", (sym, sym))
            cur.execute(
                "INSERT INTO weekly_classification (symbol,classified_at,market,classification,source) "
                "VALUES (%s,%s,'KOSPI','watch','test') ON CONFLICT DO NOTHING",
                (sym, classified),
            )
            decision = "wait" if ttype == "promotion" else "go_now"
            cur.execute(
                "INSERT INTO trigger_evaluation_log "
                "(symbol,evaluated_at,decision,trigger_type,prior_classification_at) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (sym, eval_at, decision, ttype, classified),
            )
    db.commit()

    got = {r[0] for r in _fetch_go_now_candidates(db, as_of)}
    assert "BFW_A" in got   # breakout_from_watch go_now → 포함
    assert "BFW_B" in got   # breakout go_now → 포함 (기존)
    assert "BFW_C" not in got  # promotion(wait) → 제외
