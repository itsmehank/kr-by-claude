from datetime import date
import pandas as pd

from kr_pipeline.ohlcv.transform import merge_raw_and_adjusted, to_price_rows


def _ohlcv_row(date_, o, h, l, c, v, val):
    return {"date": date_, "open": o, "high": h, "low": l, "close": c, "volume": v, "value": val}


def test_merge_aligns_by_date():
    raw = pd.DataFrame([
        _ohlcv_row(date(2026, 5, 12), 70000, 71000, 69500, 70500, 1000, 70_500_000),
        _ohlcv_row(date(2026, 5, 13), 70500, 72000, 70000, 71800, 1200, 86_160_000),
    ])
    adj = pd.DataFrame([
        {"date": date(2026, 5, 12), "close": 35250.0},
        {"date": date(2026, 5, 13), "close": 35900.0},
    ])
    merged = merge_raw_and_adjusted(raw, adj)
    assert list(merged["date"]) == [date(2026, 5, 12), date(2026, 5, 13)]
    assert list(merged["close"]) == [70500, 71800]
    assert list(merged["adj_close"]) == [35250.0, 35900.0]


def test_merge_handles_missing_dates_in_adjusted():
    raw = pd.DataFrame([
        _ohlcv_row(date(2026, 5, 12), 70000, 71000, 69500, 70500, 1000, 70_500_000),
    ])
    adj = pd.DataFrame(columns=["date", "close"])
    merged = merge_raw_and_adjusted(raw, adj)
    # 수정종가 누락 시 close 로 fallback
    assert merged.iloc[0]["adj_close"] == 70500


def test_to_price_rows_produces_tuples_ready_for_executemany():
    merged = pd.DataFrame([{
        "date": date(2026, 5, 12),
        "open": 70000, "high": 71000, "low": 69500, "close": 70500,
        "adj_close": 35250.0, "volume": 1000, "value": 70_500_000,
    }])
    rows = to_price_rows("005930", merged)
    assert rows == [(
        "005930", date(2026, 5, 12), 70000, 71000, 69500, 70500, 35250.0, 1000, 70_500_000
    )]
