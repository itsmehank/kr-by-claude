# tests/test_corporate_actions_modes.py
from datetime import date, timedelta
from freezegun import freeze_time

from kr_pipeline.corporate_actions.modes import Mode, compute_date_range


def test_mode_enum_values():
    assert Mode.BACKFILL.value == "backfill"
    assert Mode.INCREMENTAL.value == "incremental"
    assert Mode.REFRESH_MAPPING.value == "refresh-mapping"


@freeze_time("2026-05-17")
def test_backfill_5_years_range():
    start, end = compute_date_range(Mode.BACKFILL, years=5)
    assert end == date(2026, 5, 17)
    assert start == date(2021, 5, 18)   # today - 5y = today - 5*365 일


@freeze_time("2026-05-17")
def test_incremental_window_7_days():
    start, end = compute_date_range(Mode.INCREMENTAL, window_days=7)
    assert end == date(2026, 5, 17)
    assert start == date(2026, 5, 10)


@freeze_time("2026-05-17")
def test_refresh_mapping_mode():
    """refresh-mapping 은 날짜 범위 안 씀."""
    # compute_date_range 가 호출되지 않거나 None 반환
    # 우리 정의: refresh-mapping 일 때 (None, None) 반환
    start, end = compute_date_range(Mode.REFRESH_MAPPING)
    assert start is None and end is None
