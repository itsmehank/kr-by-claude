# tests/test_indicators_modes.py
from datetime import date
from freezegun import freeze_time

from kr_pipeline.indicators.modes import Mode, Target, compute_date_range, LOOKBACK_DAYS, LOOKBACK_WEEKS


def test_mode_enum_values():
    assert Mode.BACKFILL.value == "backfill"
    assert Mode.INCREMENTAL.value == "incremental"
    assert Mode.FULL_REFRESH.value == "full-refresh"


def test_target_enum_values():
    assert Target.DAILY.value == "daily"
    assert Target.WEEKLY.value == "weekly"


@freeze_time("2026-05-18")
def test_daily_incremental_window_30():
    """daily incremental: end=today, start=today - 30 - 252 lookback"""
    start, end, ups_start = compute_date_range(Target.DAILY, Mode.INCREMENTAL, window=30)
    today = date(2026, 5, 18)
    assert end == today
    assert start == today - __import__("datetime").timedelta(days=30 + LOOKBACK_DAYS)
    assert ups_start == today - __import__("datetime").timedelta(days=30)


@freeze_time("2026-05-18")
def test_weekly_incremental_window_4():
    """weekly incremental: lookback 52 주"""
    start, end, ups_start = compute_date_range(Target.WEEKLY, Mode.INCREMENTAL, window=4)
    today = date(2026, 5, 18)
    assert end == today
    assert start == today - __import__("datetime").timedelta(days=(4 + LOOKBACK_WEEKS) * 7)
    assert ups_start == today - __import__("datetime").timedelta(days=4 * 7)


def test_backfill_uses_db_min(monkeypatch):
    """backfill: db 의 min date 부터, upsert 시작 = start"""
    from kr_pipeline.indicators import modes
    monkeypatch.setattr(modes, "_get_db_min_date", lambda conn, t: date(2024, 1, 2))
    with freeze_time("2026-05-18"):
        start, end, ups_start = compute_date_range(Target.DAILY, Mode.BACKFILL, conn=None)
    assert start == date(2024, 1, 2)
    assert end == date(2026, 5, 18)
    assert ups_start == date(2024, 1, 2)


def test_recompute_ticker_daily_runs_phase_a_full_range(mocker):
    """단일종목 daily Phase A 를 FULL_REFRESH 범위로 1회 실행한다(횡단면 Phase 없음)."""
    import kr_pipeline.indicators.modes as m
    from datetime import date

    mocker.patch.object(m, "_ticker_market", return_value="KOSPI")
    mocker.patch.object(
        m, "compute_date_range",
        return_value=(date(2020, 1, 1), date(2024, 12, 31), date(2020, 1, 1)),
    )
    captured = {}
    def fake_proc(conn, ticker, market, ls, le, us):
        captured.update(ticker=ticker, market=market, ls=ls, le=le, us=us)
        return 42
    proc = mocker.patch.object(m, "_process_ticker_daily", side_effect=fake_proc)
    pb = mocker.patch.object(m, "_run_phase_b_daily")

    n = m.recompute_ticker_daily(conn=None, ticker="005930")

    assert n == 42
    assert captured == {"ticker": "005930", "market": "KOSPI",
                        "ls": date(2020, 1, 1), "le": date(2024, 12, 31), "us": date(2020, 1, 1)}
    pb.assert_not_called()  # 횡단면 Phase B 는 돌지 않음


def test_recompute_ticker_daily_unknown_market_returns_zero(mocker):
    import kr_pipeline.indicators.modes as m
    mocker.patch.object(m, "_ticker_market", return_value=None)
    proc = mocker.patch.object(m, "_process_ticker_daily")
    assert m.recompute_ticker_daily(conn=None, ticker="ZZZ") == 0
    proc.assert_not_called()


def test_recompute_ticker_weekly_runs_phase_a_full_range(mocker):
    import kr_pipeline.indicators.modes as m
    from datetime import date

    mocker.patch.object(m, "_ticker_market", return_value="KOSDAQ")
    mocker.patch.object(
        m, "compute_date_range",
        return_value=(date(2020, 1, 1), date(2024, 12, 31), date(2020, 1, 1)),
    )
    captured = {}
    def fake_proc(conn, ticker, market, ls, le, us):
        captured.update(ticker=ticker, market=market, ls=ls, le=le, us=us)
        return 7
    mocker.patch.object(m, "_process_ticker_weekly", side_effect=fake_proc)
    pb = mocker.patch.object(m, "_run_phase_b_weekly")

    n = m.recompute_ticker_weekly(conn=None, ticker="035720")
    assert n == 7
    assert captured == {"ticker": "035720", "market": "KOSDAQ",
                        "ls": date(2020, 1, 1), "le": date(2024, 12, 31), "us": date(2020, 1, 1)}
    pb.assert_not_called()


def test_process_ticker_daily_distribution_flag_uses_ssot_threshold(db):
    """파이프라인 경로(_process_ticker_daily)의 distribution_day 가 SSOT
    (STOCK_DISTRIBUTION_VOL_MULT=1.0)를 써야 한다.

    호출부의 threshold=1.25 리터럴 override 가 SSOT default 를 무력화해
    volume_ratio ∈ (1.0, 1.25] 인 하락일 4,662행(5주 실측)이 미플래깅됐다.
    prompt §6(1.0×)·web thresholds.generated.ts(1.0)와 3중 불일치."""
    from datetime import date, timedelta
    from kr_pipeline.indicators.modes import _process_ticker_daily

    t = "DISTSSOT"
    start = date(2010, 1, 4)  # 과거 격리 구간 (월요일)
    # 평일 61일 생성: 60일 평탄(거래량 1000) + 마지막날 하락(-0.5%)·거래량 1100(=1.1×)
    days = []
    d = start
    while len(days) < 61:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        for i, day in enumerate(days):
            if i < 60:
                close, vol = 100.0, 1000
            else:
                close, vol = 99.5, 1100  # 하락일 + ratio 1.1 (1.0< r <=1.25)
            cur.execute(
                """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                       adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)""",
                (t, day, close, close, close, close, close, close, close, close, float(vol), vol),
            )
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close)
                   VALUES ('1001', %s, 2000, 2000, 2000, 2000)
                   ON CONFLICT (index_code, date) DO NOTHING""",
                (day,),
            )
    db.commit()

    try:
        _process_ticker_daily(db, t, "KOSPI", days[0], days[-1], days[0])
        db.commit()
        with db.cursor() as cur:
            cur.execute(
                "SELECT distribution_day_flag, volume_ratio_50d FROM daily_indicators WHERE ticker=%s AND date=%s",
                (t, days[-1]),
            )
            flag, ratio = cur.fetchone()
        assert ratio is not None and 1.0 < float(ratio) <= 1.25, f"테스트 전제 깨짐: ratio={ratio}"
        assert flag is True, (
            f"volume_ratio={ratio} 하락일은 SSOT(1.0x) 기준 distribution day — "
            "호출부 1.25 override 가 SSOT 를 무력화하고 있음"
        )
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        db.commit()
