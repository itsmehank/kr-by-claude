from datetime import date
from freezegun import freeze_time

from kr_pipeline.ohlcv.modes import compute_date_range, Mode


@freeze_time("2026-05-15")
def test_backfill_range_for_2_years():
    start, end = compute_date_range(Mode.BACKFILL, years=2)
    assert start == date(2024, 5, 15)
    assert end == date(2026, 5, 14)


@freeze_time("2026-05-15")
def test_incremental_range_for_30_days():
    start, end = compute_date_range(Mode.INCREMENTAL, window_days=30)
    assert start == date(2026, 4, 15)
    assert end == date(2026, 5, 15)


def test_full_refresh_range_uses_db_min(monkeypatch):
    from kr_pipeline.ohlcv import modes
    monkeypatch.setattr(modes, "_get_db_min_date", lambda conn: date(2024, 1, 2))

    with freeze_time("2026-05-15"):
        start, end = compute_date_range(Mode.FULL_REFRESH, conn=None)
    assert start == date(2024, 1, 2)
    assert end == date(2026, 5, 14)
