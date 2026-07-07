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
    assert load_end == today
    assert upsert_start == today - timedelta(days=30)
    assert load_start == today - timedelta(days=30 + LOOKBACK_DAYS)


@freeze_time("2026-07-08")
def test_incremental_load_end_is_today():
    """P1-4: incremental load_end 는 어제가 아니라 오늘이어야 한다.

    ohlcv 체인(평일 18:30)이 index_daily 에 당일 확정봉을 적재하므로,
    market_context(19:30)가 어제까지만 계산하면 20:00 LLM 이 stale status 를
    소비한다 (주말 경로는 T-2). 당일 행이 없으면 로드 결과에 그 날짜가
    없어 자연 skip 되므로 today 가 안전하다.
    """
    _, load_end, _ = compute_date_range(Mode.INCREMENTAL, window_days=30)
    assert load_end == date(2026, 7, 8)


def test_backfill_uses_db_min(monkeypatch):
    from kr_pipeline.market_context import modes
    monkeypatch.setattr(modes, "_get_min_date", lambda conn: date(2024, 1, 2))
    with freeze_time("2026-05-18"):
        load_start, load_end, upsert_start = compute_date_range(Mode.BACKFILL, conn=None)
    assert load_start == date(2024, 1, 2)
    assert upsert_start == date(2024, 1, 2)
