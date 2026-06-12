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


def test_entry_params_sends_slack_signal_on_insert(db, mocker):
    """매수 시그널 적재 성공 시 Slack 알림(notify_signal)이 나가야 한다 —
    함수만 있고 호출이 없어 '시그널이 떠도 아무도 모르는' dead code 였다.
    dry-run 은 알림 금지."""
    from datetime import datetime, timezone
    import kr_pipeline.llm_runner.entry_params as ep

    canned = {
        "entry_mode": "pivot_breakout", "pivot_price": 100.0, "trigger_price": 100.1,
        "current_price": 100.0, "stop_loss_price": 95.0,
        "stop_loss_pct_from_pivot": -5.0, "stop_loss_pct_from_current_price": -5.1,
        "suggested_weight_pct": 5.0, "expected_target_price": 120.0,
        "expected_target_pct": 20.0, "pattern_basis": "flat_base",
        "entry_window_days": 3, "max_chase_pct_from_pivot": 5.0,
        "breakout_volume_requirement": "ge_1.4x_50day_avg",
        "observed_breakout_volume_ratio": None,
        "known_warnings": [], "other_warnings": "", "notes": "t",
    }
    mocker.patch.object(ep, "build_for_6", return_value={"symbol": "NTFY1", "name": "알림테스트"})
    mocker.patch.object(ep, "call_claude", return_value=dict(canned))
    mocker.patch.object(ep, "insert_entry_params")
    notify = mocker.patch.object(ep, "notify_signal")

    now = datetime.now(timezone.utc)
    ep._process_one(db, "NTFY1", now, now, dry_run=False, as_of=now.date())
    assert notify.call_count == 1
    kwargs = notify.call_args.kwargs
    assert kwargs["symbol"] == "NTFY1"
    assert kwargs["entry_price"] == 100.1   # §9 trigger_price = 실제 진입 트리거가
    assert kwargs["stop_loss"] == 95.0

    notify.reset_mock()
    ep._process_one(db, "NTFY1", now, now, dry_run=True, as_of=now.date())
    assert notify.call_count == 0, "dry-run 에서 알림 발송 금지"
