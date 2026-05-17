# tests/test_market_context_modes.py
from datetime import date, timedelta
from freezegun import freeze_time

from kr_pipeline.market_context.modes import (
    Mode, compute_date_range, LOOKBACK_DAYS,
)


def test_mode_enum_values():
    assert Mode.BACKFILL.value == "backfill"
    assert Mode.INCREMENTAL.value == "incremental"
    assert Mode.FULL_REFRESH.value == "full-refresh"


@freeze_time("2026-05-18")
def test_incremental_window_30():
    """load_start = today - 30 - LOOKBACK_DAYS, upsert_start = today - 30."""
    load_start, load_end, upsert_start = compute_date_range(Mode.INCREMENTAL, window_days=30)
    today = date(2026, 5, 18)
    assert load_end == today - timedelta(days=1)
    assert upsert_start == today - timedelta(days=30)
    assert load_start == today - timedelta(days=30 + LOOKBACK_DAYS)


def test_backfill_uses_db_min(monkeypatch):
    from kr_pipeline.market_context import modes
    monkeypatch.setattr(modes, "_get_min_date", lambda conn: date(2024, 1, 2))
    with freeze_time("2026-05-18"):
        load_start, load_end, upsert_start = compute_date_range(Mode.BACKFILL, conn=None)
    assert load_start == date(2024, 1, 2)
    assert upsert_start == date(2024, 1, 2)
