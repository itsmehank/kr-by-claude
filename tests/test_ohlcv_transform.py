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


import math


def test_halt_row_nulls_adj_keeps_close_and_raw():
    """거래정지일(open=high=low=0 & close>0 & volume=0): adj_open/high/low/volume→NaN(NULL),
    adj_close·raw 는 보존. (w52_low rolling min·avg_volume 가 0을 흡수하지 않도록)"""
    raw = pd.DataFrame([_ohlcv_row(date(2026, 5, 12), 0, 0, 0, 5330, 0, 0)])
    adj = pd.DataFrame([{"date": date(2026, 5, 12), "open": 0.0, "high": 0.0,
                         "low": 0.0, "close": 5330.0, "volume": 0, "value": 0}])
    m = merge_raw_and_adjusted(raw, adj).iloc[0]
    assert math.isnan(m["adj_low"]) and math.isnan(m["adj_high"])
    assert math.isnan(m["adj_open"]) and math.isnan(m["adj_volume"])
    assert m["adj_close"] == 5330.0          # close 보존
    assert m["low"] == 0 and m["close"] == 5330  # raw 보존(halt 마커)


def test_halt_detector_excludes_volume_positive_misfetch():
    """low=0 인데 volume>0 = 실거래 mis-fetch → halt 아님 → adj 정규화 제외(별도 처리)."""
    raw = pd.DataFrame([_ohlcv_row(date(2026, 5, 12), 0, 0, 0, 1395, 278989, 0)])
    adj = pd.DataFrame([{"date": date(2026, 5, 12), "open": 0.0, "high": 0.0,
                         "low": 0.0, "close": 1395.0, "volume": 278989, "value": 0}])
    m = merge_raw_and_adjusted(raw, adj).iloc[0]
    assert not math.isnan(m["adj_low"])      # 정규화 안 됨


def test_to_price_rows_halt_adj_becomes_none():
    """halt 행 to_price_rows: adj_* 튜플 위치 None(NULL), raw/close 위치는 값 유지."""
    raw = pd.DataFrame([_ohlcv_row(date(2026, 5, 12), 0, 0, 0, 5330, 0, 0)])
    adj = pd.DataFrame([{"date": date(2026, 5, 12), "open": 0.0, "high": 0.0,
                         "low": 0.0, "close": 5330.0, "volume": 0, "value": 0}])
    rows = to_price_rows("009310", merge_raw_and_adjusted(raw, adj))
    t = rows[0]  # (ticker,date,open,high,low,close,adj_close,adj_high,adj_low,adj_open,adj_volume,volume,value)
    assert t[6] == 5330.0                     # adj_close 유지
    assert t[7] is None and t[8] is None      # adj_high, adj_low → None
    assert t[9] is None and t[10] is None     # adj_open, adj_volume → None
    assert t[4] == 0 and t[5] == 5330         # raw low=0, close 유지


from kr_pipeline.ohlcv.transform import nullify_halt_adj


def test_nullify_halt_adj_single_chokepoint():
    """단일 chokepoint: adj OHLV=0 & adj_vol=0 & adj_close>0 → adj_* NaN, adj_close 유지."""
    df = pd.DataFrame([{"adj_open": 0.0, "adj_high": 0.0, "adj_low": 0.0,
                        "adj_close": 5330.0, "adj_volume": 0.0}])
    out = nullify_halt_adj(df).iloc[0]
    assert math.isnan(out["adj_low"]) and math.isnan(out["adj_high"])
    assert math.isnan(out["adj_open"]) and math.isnan(out["adj_volume"])
    assert out["adj_close"] == 5330.0


def test_nullify_halt_adj_excludes_volume_positive():
    """adj_low=0 인데 adj_volume>0(실거래 mis-fetch) → halt 아님 → 정규화 제외."""
    df = pd.DataFrame([{"adj_open": 0.0, "adj_high": 0.0, "adj_low": 0.0,
                        "adj_close": 1395.0, "adj_volume": 278989.0}])
    assert not math.isnan(nullify_halt_adj(df).iloc[0]["adj_low"])
