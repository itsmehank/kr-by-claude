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
