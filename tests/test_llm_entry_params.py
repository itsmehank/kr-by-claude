from datetime import date, datetime, timezone, timedelta


def test_entry_params_processes_go_now_only(db, mocker):
    today = date(2026, 5, 20)
    eval_time = datetime(2026, 5, 20, 16, 32, tzinfo=timezone.utc)
    prior_at = datetime(2026, 5, 17, 3, 0, tzinfo=timezone.utc)

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('EP1', 'E', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('EP2', 'E', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, pattern, pivot_price, pivot_basis,
                base_high, base_low, base_depth_pct, source)
               VALUES
               ('EP1', %s, 'KOSPI', 'entry', 'cup_with_handle', 80, 'handle_high', 80, 70, 12.5, 'weekend'),
               ('EP2', %s, 'KOSPI', 'entry', 'flat_base', 60, 'range_high', 60, 55, 8.3, 'weekend')
               ON CONFLICT (symbol, classified_at) DO NOTHING""",
            (prior_at, prior_at),
        )
        cur.execute(
            """INSERT INTO trigger_evaluation_log
               (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                decision, prior_classification_at)
               VALUES
               ('EP1', %s, 'breakout', 82, 2000000, 80, 'go_now', %s),
               ('EP2', %s, 'breakout', 61, 1500000, 60, 'wait', %s)
               ON CONFLICT (symbol, evaluated_at) DO NOTHING""",
            (eval_time, prior_at, eval_time, prior_at),
        )
        # daily_indicators + daily_prices for current_state
        for sym in ("EP1", "EP2"):
            cur.execute(
                """INSERT INTO daily_prices
                   (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES (%s, %s, 80, 82, 79, 81, 81, 1500000, 121500000)
                   ON CONFLICT DO NOTHING""",
                (sym, today),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                   (ticker, date, adj_close, volume, avg_volume_50d, rs_rating,
                    minervini_pass, w52_high, w52_low, pct_from_52w_high)
                   VALUES (%s, %s, 81, 1500000, 1000000, 85, TRUE, 95, 60, 14.7)
                   ON CONFLICT DO NOTHING""",
                (sym, today),
            )
    db.commit()

    from kr_pipeline.llm_runner.entry_params import run

    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM entry_params WHERE symbol='EP1'")
        before_ep1 = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM entry_params WHERE symbol='EP2'")
        before_ep2 = cur.fetchone()[0]

    result = run(db, dry_run=True, as_of=today)

    # EP1 만 go_now → 1 새 entry_params row, EP2 는 wait → 추가 없음
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM entry_params WHERE symbol='EP1'")
        after_ep1 = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM entry_params WHERE symbol='EP2'")
        after_ep2 = cur.fetchone()[0]

    assert after_ep1 - before_ep1 == 1
    assert after_ep2 - before_ep2 == 0
