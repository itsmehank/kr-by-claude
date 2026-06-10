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
        "adj_open": 35000.0, "adj_volume": 2000.0,
        "volume": 1000, "value": 70_500_000,
    }])
    rows = to_price_rows("005930", merged)
    assert rows == [(
        "005930", date(2026, 5, 12), 70000, 71000, 69500, 70500,
        35250.0, 35500.0, 34750.0, 35000.0, 2000.0, 1000, 70_500_000
    )]


def test_merge_picks_adj_open_and_adj_volume():
    import pandas as pd
    from kr_pipeline.ohlcv.transform import merge_raw_and_adjusted
    raw = pd.DataFrame({"date": ["2025-01-02"], "open": [100], "high": [110], "low": [90],
                        "close": [105], "volume": [1000], "value": [105000]})
    adj = pd.DataFrame({"date": ["2025-01-02"], "open": [20], "high": [22], "low": [18],
                        "close": [21], "volume": [5000]})
    m = merge_raw_and_adjusted(raw, adj)
    assert float(m.loc[0, "adj_open"]) == 20.0
    assert float(m.loc[0, "adj_volume"]) == 5000.0


def test_merge_adj_open_volume_fallback_to_raw_when_missing():
    import pandas as pd
    from kr_pipeline.ohlcv.transform import merge_raw_and_adjusted
    raw = pd.DataFrame({"date": ["2025-01-02"], "open": [100], "high": [110], "low": [90],
                        "close": [105], "volume": [1000], "value": [105000]})
    adj = pd.DataFrame({"date": ["2025-01-02"], "close": [105]})
    m = merge_raw_and_adjusted(raw, adj)
    assert float(m.loc[0, "adj_open"]) == 100.0
    assert float(m.loc[0, "adj_volume"]) == 1000.0


def test_to_index_rows_preserves_decimals():
    """지수 OHLC 는 소수 2자리(NUMERIC(12,2)). int() 절단 시 KOSDAQ(~900pt)에서
    일일 등락률 오차 ±0.2%p — distribution day(-0.2%)/FTD 임계 판정이 플립된다.
    (실측: index_daily 4,900행 전수 소수부 0 — 절단 버그)"""
    import pandas as pd
    from datetime import date
    from kr_pipeline.ohlcv.transform import to_index_rows

    df = pd.DataFrame([
        {"date": date(2026, 6, 10), "open": 901.23, "high": 905.67,
         "low": 898.41, "close": 903.89, "volume": 1000.0, "value": 5000.0},
    ])
    rows = to_index_rows("2001", df)
    assert rows == [("2001", date(2026, 6, 10), 901.23, 905.67, 898.41, 903.89, 1000, 5000)]


def test_to_index_rows_null_volume_value():
    """volume/value NaN → None (nullable bigint)."""
    import pandas as pd
    import numpy as np
    from datetime import date
    from kr_pipeline.ohlcv.transform import to_index_rows

    df = pd.DataFrame([
        {"date": date(2026, 6, 10), "open": 901.23, "high": 905.67,
         "low": 898.41, "close": 903.89, "volume": np.nan, "value": np.nan},
    ])
    rows = to_index_rows("2001", df)
    assert rows == [("2001", date(2026, 6, 10), 901.23, 905.67, 898.41, 903.89, None, None)]
