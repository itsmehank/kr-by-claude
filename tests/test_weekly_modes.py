from datetime import date, timedelta
from freezegun import freeze_time

from kr_pipeline.weekly.modes import Mode, compute_date_range


def test_mode_enum_values():
    assert Mode.BACKFILL.value == "backfill"
    assert Mode.INCREMENTAL.value == "incremental"
    assert Mode.FULL_REFRESH.value == "full-refresh"


@freeze_time("2026-05-18")  # Monday
def test_incremental_range_4_weeks():
    """today=Mon 5/18 → start=5/18 - 28일 = 4/20, end=today-1 = 5/17"""
    start, end = compute_date_range(Mode.INCREMENTAL, window_weeks=4)
    assert start == date(2026, 4, 20)
    assert end == date(2026, 5, 17)


@freeze_time("2026-05-18")
def test_incremental_default_window_is_4():
    start, end = compute_date_range(Mode.INCREMENTAL)
    assert (date(2026, 5, 18) - start).days == 28


def test_backfill_uses_db_min(monkeypatch):
    """backfill 은 DB 의 MIN(date) 를 시작점으로."""
    from kr_pipeline.weekly import modes
    monkeypatch.setattr(modes, "_get_daily_min_date", lambda conn: date(2024, 1, 2))
    with freeze_time("2026-05-18"):
        start, end = compute_date_range(Mode.BACKFILL, conn=None)
    assert start == date(2024, 1, 2)
    assert end == date(2026, 5, 17)


def test_full_refresh_uses_db_min(monkeypatch):
    from kr_pipeline.weekly import modes
    monkeypatch.setattr(modes, "_get_daily_min_date", lambda conn: date(2024, 1, 2))
    with freeze_time("2026-05-18"):
        start, end = compute_date_range(Mode.FULL_REFRESH, conn=None)
    assert start == date(2024, 1, 2)
    assert end == date(2026, 5, 17)


def test_unknown_mode_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown mode"):
        compute_date_range("oops")  # type: ignore
