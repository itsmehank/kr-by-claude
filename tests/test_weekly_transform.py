from datetime import date
import pandas as pd
import pytest

from kr_pipeline.weekly.transform import (
    aggregate_to_weekly,
    drop_incomplete_weeks,
    to_weekly_rows,
)


def _daily(date_, o, h, l, c, adj, v, val, adj_high=None, adj_low=None, adj_open=None, adj_volume=None):
    row = {
        "date": date_,
        "open": o, "high": h, "low": l, "close": c,
        "adj_close": adj, "volume": v, "value": val,
        "adj_high":   adj_high   if adj_high   is not None else float(h),
        "adj_low":    adj_low    if adj_low    is not None else float(l),
        "adj_open":   adj_open   if adj_open   is not None else float(o),
        "adj_volume": adj_volume if adj_volume is not None else float(v),
    }
    return row


def test_aggregate_single_full_week():
    """월~금 5일 일봉 → 1개 주봉."""
    daily = pd.DataFrame([
        _daily(date(2026, 5, 11), 100, 110, 95,  105, 105.0, 1000, 100000),   # Mon
        _daily(date(2026, 5, 12), 105, 115, 100, 108, 108.0, 1100, 113200),   # Tue
        _daily(date(2026, 5, 13), 108, 120, 102, 115, 115.0, 1200, 137400),   # Wed
        _daily(date(2026, 5, 14), 115, 125, 110, 120, 120.0, 1300, 153400),   # Thu
        _daily(date(2026, 5, 15), 120, 130, 115, 125, 125.0, 1400, 175000),   # Fri
    ])
    weekly = aggregate_to_weekly(daily)
    assert len(weekly) == 1
    row = weekly.iloc[0]
    assert row["week_end_date"] == date(2026, 5, 15)
    assert row["open"] == 100
    assert row["high"] == 130
    assert row["low"] == 95
    assert row["close"] == 125
    assert row["adj_close"] == 125.0
    assert row["volume"] == 6000
    assert row["value"] == 679000
    assert row["trading_days"] == 5


def test_aggregate_holiday_week_4_days():
    """월요일 휴장. 화~금 4일치만 → trading_days=4, week_end_date=금."""
    daily = pd.DataFrame([
        _daily(date(2026, 5, 12), 105, 115, 100, 108, 108.0, 1100, 113200),
        _daily(date(2026, 5, 13), 108, 120, 102, 115, 115.0, 1200, 137400),
        _daily(date(2026, 5, 14), 115, 125, 110, 120, 120.0, 1300, 153400),
        _daily(date(2026, 5, 15), 120, 130, 115, 125, 125.0, 1400, 175000),
    ])
    weekly = aggregate_to_weekly(daily)
    assert len(weekly) == 1
    row = weekly.iloc[0]
    assert row["week_end_date"] == date(2026, 5, 15)
    assert row["open"] == 105
    assert row["trading_days"] == 4


def test_aggregate_holiday_friday_thursday_closes_week():
    """금요일 휴장. 월~목. week_end_date=목요일."""
    daily = pd.DataFrame([
        _daily(date(2026, 5, 11), 100, 110, 95,  105, 105.0, 1000, 100000),
        _daily(date(2026, 5, 12), 105, 115, 100, 108, 108.0, 1100, 113200),
        _daily(date(2026, 5, 13), 108, 120, 102, 115, 115.0, 1200, 137400),
        _daily(date(2026, 5, 14), 115, 125, 110, 120, 120.0, 1300, 153400),
    ])
    weekly = aggregate_to_weekly(daily)
    assert len(weekly) == 1
    row = weekly.iloc[0]
    assert row["week_end_date"] == date(2026, 5, 14)
    assert row["close"] == 120
    assert row["adj_close"] == 120.0
    assert row["trading_days"] == 4


def test_aggregate_multiple_weeks_split_correctly():
    """2주치 일봉 → 2주봉. 주 경계 정확히 분리."""
    daily = pd.DataFrame([
        _daily(date(2026, 5, 4),  100, 100, 100, 100, 100.0, 100, 10000),
        _daily(date(2026, 5, 8),  100, 100, 100, 200, 200.0, 100, 20000),
        _daily(date(2026, 5, 11), 200, 200, 200, 200, 200.0, 100, 20000),
        _daily(date(2026, 5, 15), 200, 200, 200, 300, 300.0, 100, 30000),
    ])
    weekly = aggregate_to_weekly(daily)
    assert len(weekly) == 2
    week1 = weekly[weekly["week_end_date"] == date(2026, 5, 8)].iloc[0]
    week2 = weekly[weekly["week_end_date"] == date(2026, 5, 15)].iloc[0]
    assert week1["close"] == 200
    assert week2["close"] == 300


def test_adj_close_takes_last_day_value_not_max():
    """adj_close = 그 주 마지막 거래일의 adj_close (max 가 아님)."""
    daily = pd.DataFrame([
        _daily(date(2026, 5, 11), 100, 200, 100, 150, 75.0, 100, 15000),
        _daily(date(2026, 5, 15), 150, 160, 140, 155, 77.5, 100, 15500),
    ])
    weekly = aggregate_to_weekly(daily)
    assert weekly.iloc[0]["adj_close"] == 77.5


def test_empty_daily_returns_empty_weekly():
    """일봉 0행 → 주봉 0행."""
    daily = pd.DataFrame(columns=["date", "open", "high", "low", "close", "adj_close", "volume", "value"])
    weekly = aggregate_to_weekly(daily)
    assert len(weekly) == 0
    assert set(weekly.columns) >= {"week_end_date", "open", "high", "low", "close", "adj_close", "volume", "value", "trading_days"}


def test_drop_incomplete_weeks_removes_current_week():
    """today=2026-05-14 (목) 일 때 5/11~5/15 주는 미완성 → 제외."""
    weekly = pd.DataFrame([
        {"week_end_date": date(2026, 5, 8),  "close": 100},
        {"week_end_date": date(2026, 5, 15), "close": 200},
    ])
    today = date(2026, 5, 14)
    result = drop_incomplete_weeks(weekly, today)
    assert list(result["week_end_date"]) == [date(2026, 5, 8)]


def test_drop_incomplete_weeks_keeps_completed_week():
    """today=2026-05-18 (월) 일 때 5/11~5/15 주는 완료 → 포함."""
    weekly = pd.DataFrame([
        {"week_end_date": date(2026, 5, 8),  "close": 100},
        {"week_end_date": date(2026, 5, 15), "close": 200},
    ])
    today = date(2026, 5, 18)
    result = drop_incomplete_weeks(weekly, today)
    assert list(result["week_end_date"]) == [date(2026, 5, 8), date(2026, 5, 15)]


def test_drop_incomplete_weeks_with_today_on_weekend():
    """today=2026-05-16 (토) 일 때 5/11~5/15 주는 완료 → 포함."""
    weekly = pd.DataFrame([
        {"week_end_date": date(2026, 5, 15), "close": 200},
    ])
    today = date(2026, 5, 16)
    result = drop_incomplete_weeks(weekly, today)
    assert list(result["week_end_date"]) == [date(2026, 5, 15)]


def test_to_weekly_rows_tuple_format():
    """DataFrame → executemany 용 tuple 리스트."""
    weekly = pd.DataFrame([{
        "week_end_date": date(2026, 5, 15),
        "open": 100, "high": 130, "low": 95, "close": 125,
        "adj_close": 125.0, "adj_high": 130.0, "adj_low": 95.0,
        "adj_open": 100.0, "adj_volume": 6000.0,
        "volume": 6000, "value": 679000, "trading_days": 5,
    }])
    rows = to_weekly_rows("005930", weekly)
    assert rows == [(
        "005930", date(2026, 5, 15),
        100, 130, 95, 125,
        125.0, 130.0, 95.0, 100.0, 6000.0, 6000, 679000, 5,
    )]


def test_aggregate_preserves_int_types_for_db():
    """volume, value, trading_days 는 int 로 출력 가능."""
    daily = pd.DataFrame([
        _daily(date(2026, 5, 11), 100, 100, 100, 100, 100.0, 1000, 100000),
        _daily(date(2026, 5, 15), 100, 100, 100, 100, 100.0, 2000, 200000),
    ])
    weekly = aggregate_to_weekly(daily)
    row = weekly.iloc[0]
    assert isinstance(int(row["volume"]), int)
    assert isinstance(int(row["value"]), int)
    assert isinstance(int(row["trading_days"]), int)


def test_aggregate_preserves_null_volume_for_indexes():
    """volume/value 가 None 인 일봉 → 주봉 volume/value 도 None (NaN) 유지.

    index_daily 처럼 volume/value 가 nullable 인 경우 0 으로 변환되지 않아야 함."""
    daily = pd.DataFrame([
        {"date": date(2026, 5, 11), "open": 100, "high": 100, "low": 100, "close": 100,
         "adj_close": 100.0, "adj_high": 100.0, "adj_low": 100.0, "adj_open": 100.0, "adj_volume": None,
         "volume": None, "value": None},
        {"date": date(2026, 5, 15), "open": 100, "high": 100, "low": 100, "close": 100,
         "adj_close": 100.0, "adj_high": 100.0, "adj_low": 100.0, "adj_open": 100.0, "adj_volume": None,
         "volume": None, "value": None},
    ])
    weekly = aggregate_to_weekly(daily)
    row = weekly.iloc[0]
    # 모든 값이 None 이었으면 NaN 으로 유지 (0 아님)
    assert pd.isna(row["volume"])
    assert pd.isna(row["value"])


def test_aggregate_partial_null_volume_sums_non_null():
    """volume 일부가 None, 일부는 값. sum 은 값만 합산 (NaN 안 됨)."""
    daily = pd.DataFrame([
        {"date": date(2026, 5, 11), "open": 100, "high": 100, "low": 100, "close": 100,
         "adj_close": 100.0, "adj_high": 100.0, "adj_low": 100.0, "adj_open": 100.0, "adj_volume": 1000.0,
         "volume": 1000, "value": 100000},
        {"date": date(2026, 5, 15), "open": 100, "high": 100, "low": 100, "close": 100,
         "adj_close": 100.0, "adj_high": 100.0, "adj_low": 100.0, "adj_open": 100.0, "adj_volume": None,
         "volume": None, "value": None},
    ])
    weekly = aggregate_to_weekly(daily)
    row = weekly.iloc[0]
    assert row["volume"] == 1000  # 1000 + NaN = 1000 (min_count=1)
    assert row["value"] == 100000


def test_to_weekly_index_rows_handles_nan_volume():
    """to_weekly_index_rows 가 NaN volume/value 를 None 으로 변환."""
    import numpy as np
    from kr_pipeline.weekly.transform import to_weekly_index_rows
    weekly = pd.DataFrame([{
        "week_end_date": date(2026, 5, 15),
        "open": 2500, "high": 2520, "low": 2490, "close": 2510,
        "volume": np.nan, "value": np.nan, "trading_days": 5,
    }])
    rows = to_weekly_index_rows("1001", weekly)
    assert rows == [(
        "1001", date(2026, 5, 15),
        2500, 2520, 2490, 2510,
        None, None,  # ← NaN → None
        5,
    )]


def test_to_weekly_index_rows_with_real_volume():
    """to_weekly_index_rows 가 실제 volume/value 를 int 로 변환."""
    from kr_pipeline.weekly.transform import to_weekly_index_rows
    weekly = pd.DataFrame([{
        "week_end_date": date(2026, 5, 15),
        "open": 2500, "high": 2520, "low": 2490, "close": 2510,
        "volume": 1000.0, "value": 1000000.0, "trading_days": 5,
    }])
    rows = to_weekly_index_rows("1001", weekly)
    assert rows == [(
        "1001", date(2026, 5, 15),
        2500, 2520, 2490, 2510,
        1000, 1000000,
        5,
    )]


def test_aggregate_adj_high_is_week_max_adj_low_is_week_min():
    daily = pd.DataFrame([
        {"date": date(2026,5,11), "open":100,"high":110,"low":95,"close":105,
         "adj_close":52.0,"adj_high":55.0,"adj_low":47.5,"adj_open":50.0,"adj_volume":10.0,
         "volume":10,"value":1000},
        {"date": date(2026,5,12), "open":105,"high":120,"low":100,"close":118,
         "adj_close":59.0,"adj_high":60.0,"adj_low":50.0,"adj_open":52.5,"adj_volume":20.0,
         "volume":20,"value":2000},
    ])
    wk = aggregate_to_weekly(daily)
    assert wk.iloc[0]["adj_high"] == 60.0   # max(55, 60)
    assert wk.iloc[0]["adj_low"] == 47.5    # min(47.5, 50)
    assert wk.iloc[0]["adj_close"] == 59.0  # last


def test_to_weekly_rows_includes_adj_high_low():
    wk = pd.DataFrame([{
        "week_end_date": date(2026,5,15), "open":100,"high":120,"low":95,"close":118,
        "adj_close":59.0,"adj_high":60.0,"adj_low":47.5,"adj_open":100.0,"adj_volume":30.0,
        "volume":30,"value":3000,"trading_days":2,
    }])
    rows = to_weekly_rows("005930", wk)
    assert rows == [(
        "005930", date(2026,5,15), 100, 120, 95, 118, 59.0, 60.0, 47.5, 100.0, 30.0, 30, 3000, 2
    )]


def test_weekly_aggregates_adj_open_first_and_adj_volume_sum():
    import pandas as pd
    from kr_pipeline.weekly.transform import aggregate_to_weekly
    daily = pd.DataFrame({
        "date": ["2025-01-06", "2025-01-07", "2025-01-08"],  # same ISO week (Mon-Wed)
        "open": [100,101,102], "high": [110,111,112], "low": [90,91,92], "close": [105,106,107],
        "adj_close": [105.0,106.0,107.0], "adj_high": [110.0,111.0,112.0], "adj_low": [90.0,91.0,92.0],
        "adj_open": [100.0,101.0,102.0], "adj_volume": [1000.0,2000.0,3000.0],
        "volume": [1000,2000,3000], "value": [1,2,3],
    })
    w = aggregate_to_weekly(daily)
    assert float(w.loc[0, "adj_open"]) == 100.0      # week first day
    assert float(w.loc[0, "adj_volume"]) == 6000.0   # sum
