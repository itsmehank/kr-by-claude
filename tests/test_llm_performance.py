from datetime import date, datetime, timedelta, timezone


def test_performance_backfill_1w(db):
    today = date(2026, 5, 20)
    signal_date = today - timedelta(days=10)

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('PF1', 'P', 'KOSPI') ON CONFLICT DO NOTHING")
        # 이전 테스트 실행 잔여 데이터 정리 (db.commit 사용 테스트는 롤백 격리 불가)
        cur.execute("DELETE FROM signal_performance WHERE symbol='PF1'")
        # entry_params 시드
        signal_at = datetime(signal_date.year, signal_date.month, signal_date.day, 16, 30, tzinfo=timezone.utc)
        cur.execute(
            """INSERT INTO entry_params
               (symbol, signal_at, entry_mode, trigger_price, entry_price, stop_loss,
                stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, stop_loss_basis,
                expected_target_price, expected_target_pct, risk_reward_ratio,
                position_size_pct, position_size_basis, breakout_volume_requirement,
                observed_breakout_volume_ratio, known_warnings, other_warnings, notes,
                trigger_evaluation_at, prior_classification_at)
               VALUES ('PF1', %s, 'pivot_breakout', 100.1, 100, 95,
                       -5, -5, 'logical_pct',
                       115, 15, 3.0,
                       5, 'test', '1.4x', 1.5, '[]', '', 'test',
                       %s, %s)
               ON CONFLICT DO NOTHING""",
            (signal_at, signal_at, signal_at),
        )
        # daily_prices — 1주 후 가격
        for d_offset in [0, 7]:
            d = signal_date + timedelta(days=d_offset)
            cur.execute(
                """INSERT INTO daily_prices
                   (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES ('PF1', %s, 100, 105, 95, 100, 100, 1000, 100000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
            cur.execute(
                """INSERT INTO index_daily
                   (index_code, date, open, high, low, close, volume, value)
                   VALUES ('1001', %s, 3000, 3050, 2980, 3020, 100000000, 1000000000000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
        # 종목 1주 후 +10%
        cur.execute(
            """UPDATE daily_prices SET adj_close = 110 WHERE ticker='PF1' AND date=%s""",
            (signal_date + timedelta(days=7),),
        )
        # 시장 1주 후 +2%
        cur.execute(
            """UPDATE index_daily SET close = 3060 WHERE index_code='1001' AND date=%s""",
            (signal_date + timedelta(days=7),),
        )
    db.commit()

    from kr_pipeline.llm_runner.performance import run

    result = run(db, as_of=today)
    assert result["backfilled"] >= 1

    with db.cursor() as cur:
        cur.execute(
            "SELECT return_1w_pct, market_return_1w_pct FROM signal_performance WHERE symbol='PF1'"
        )
        row = cur.fetchone()
    assert row is not None
    assert abs(float(row[0]) - 10.0) < 0.5
    assert abs(float(row[1]) - 1.32) < 0.5  # 시장 (3020 → 3060): (3060-3020)/3020 ≈ 1.32%


def test_performance_return_uses_adjusted_consistently(db):
    """entry_price(adj) vs future adj_close → 수익률 산술적으로 정확 (눈금 정합)."""
    today = date(2026, 5, 20)
    signal_date = today - timedelta(days=10)

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('PF2', 'P2', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM signal_performance WHERE symbol='PF2'")
        signal_at = datetime(signal_date.year, signal_date.month, signal_date.day, 16, 30, tzinfo=timezone.utc)
        # entry_price = 2000 (adj-scale)
        cur.execute(
            """INSERT INTO entry_params
               (symbol, signal_at, entry_mode, trigger_price, entry_price, stop_loss,
                stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, stop_loss_basis,
                expected_target_price, expected_target_pct, risk_reward_ratio,
                position_size_pct, position_size_basis, breakout_volume_requirement,
                observed_breakout_volume_ratio, known_warnings, other_warnings, notes,
                trigger_evaluation_at, prior_classification_at)
               VALUES ('PF2', %s, 'pivot_breakout', 2100.0, 2000, 1900,
                       -5, -5, 'logical_pct',
                       2300, 15, 3.0,
                       5, 'test', '1.4x', 1.5, '[]', '', 'test',
                       %s, %s)
               ON CONFLICT DO NOTHING""",
            (signal_at, signal_at, signal_at),
        )
        # daily_prices — signal_date 및 1주 후 (adj_close=2000, 2200)
        for d_offset, adj_val in [(0, 2000), (7, 2200)]:
            d = signal_date + timedelta(days=d_offset)
            cur.execute(
                """INSERT INTO daily_prices
                   (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES ('PF2', %s, 2000, 2100, 1950, 2000, %s, 1000, 2000000)
                   ON CONFLICT DO NOTHING""",
                (d, adj_val),
            )
            cur.execute(
                """INSERT INTO index_daily
                   (index_code, date, open, high, low, close, volume, value)
                   VALUES ('1001', %s, 3000, 3050, 2980, 3020, 100000000, 1000000000000)
                   ON CONFLICT DO NOTHING""",
                (d,),
            )
    db.commit()

    from kr_pipeline.llm_runner.performance import run

    result = run(db, as_of=today)
    assert result["backfilled"] >= 1

    with db.cursor() as cur:
        cur.execute(
            "SELECT return_1w_pct FROM signal_performance WHERE symbol='PF2'"
        )
        row = cur.fetchone()
    assert row is not None
    # (2200 - 2000) / 2000 * 100 = 10.0 — adj 눈금 정합 산술 검증
    assert abs(float(row[0]) - 10.0) < 0.01
