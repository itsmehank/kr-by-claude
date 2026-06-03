from datetime import date
import pandas as pd

from kr_pipeline.ohlcv.transform import merge_raw_and_adjusted, to_price_rows


def _ohlcv_row(date_, o, h, l, c, v, val):
    return {"date": date_, "open": o, "high": h, "low": l, "close": c, "volume": v, "value": val}


def test_merge_keeps_adjusted_high_low():
    raw = pd.DataFrame([
        _ohlcv_row(date(2026, 5, 12), 70000, 71000, 69500, 70500, 1000, 70_500_000),
    ])
    adj = pd.DataFrame([
        {"date": date(2026, 5, 12), "open": 35000.0, "high": 35500.0,
         "low": 34750.0, "close": 35250.0, "volume": 2000, "value": 70_500_000},
    ])
    merged = merge_raw_and_adjusted(raw, adj)
    assert merged.iloc[0]["adj_close"] == 35250.0
    assert merged.iloc[0]["adj_high"] == 35500.0
    assert merged.iloc[0]["adj_low"] == 34750.0
    assert merged.iloc[0]["high"] == 71000
    assert merged.iloc[0]["low"] == 69500


def test_merge_falls_back_to_raw_when_adjusted_missing():
    raw = pd.DataFrame([
        _ohlcv_row(date(2026, 5, 12), 70000, 71000, 69500, 70500, 1000, 70_500_000),
    ])
    adj = pd.DataFrame(columns=["date", "close"])
    merged = merge_raw_and_adjusted(raw, adj)
    assert merged.iloc[0]["adj_close"] == 70500
    assert merged.iloc[0]["adj_high"] == 71000
    assert merged.iloc[0]["adj_low"] == 69500


def test_to_price_rows_includes_adj_high_low():
    merged = pd.DataFrame([{
        "date": date(2026, 5, 12),
        "open": 70000, "high": 71000, "low": 69500, "close": 70500,
        "adj_close": 35250.0, "adj_high": 35500.0, "adj_low": 34750.0,
        "volume": 1000, "value": 70_500_000,
    }])
    rows = to_price_rows("005930", merged)
    assert rows == [(
        "005930", date(2026, 5, 12), 70000, 71000, 69500, 70500,
        35250.0, 35500.0, 34750.0, 1000, 70_500_000
    )]
