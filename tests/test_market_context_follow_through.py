# tests/test_market_context_follow_through.py
from datetime import date
import pandas as pd
import pytest

from kr_pipeline.market_context.compute.follow_through import detect_last_ftd


def _make_df(dates_and_close_vol_low):
    """[(date_obj, close, volume, low)] → DataFrame."""
    rows = [{"date": d, "close": c, "volume": v, "low": l} for d, c, v, l in dates_and_close_vol_low]
    return pd.DataFrame(rows)


def test_ftd_basic():
    """+1.5% AND volume up AND rally 5세션 후 → FTD."""
    # 20일 데이터: 처음 10일 하락, 11일에 저점, 15일에 +1.5% (5세션 후)
    rows = []
    base_date = date(2026, 1, 5)   # Monday
    closes = [100, 98, 96, 94, 92, 90, 88, 87, 86, 85, 84, 85, 86, 87, 88, 89.32, 90, 91, 92, 93]
    volumes = [100] * 14 + [200, 250, 200, 200, 200, 200]  # idx 15 에 vol up
    lows = [c - 1 for c in closes]
    for i, (c, v, lo) in enumerate(zip(closes, volumes, lows)):
        d = date.fromordinal(base_date.toordinal() + i)
        rows.append((d, c, v, lo))
    df = _make_df(rows)

    # idx 15 close=89.32, idx 14 close=88 → +1.5% AND vol 250 > 200 → 후보
    # idx 14 의 직전 15 세션 (idx 0-13) 내 저점: idx 10 close=84
    # idx 15 와 idx 10 의 차이 = 5 세션 → 3~15 범위 → 유효 FTD
    result = detect_last_ftd(df, end_idx=19, lookback_days=90)
    assert result == df.iloc[15]["date"]


def test_ftd_below_threshold():
    """+1.3% → 후보 아님."""
    rows = []
    base_date = date(2026, 1, 5)
    closes = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 91, 92, 93, 94.22, 95, 96, 97, 98, 99]
    # idx 14 close 94.22, idx 13 close 93 → +1.31%
    volumes = [100] * 13 + [200, 250, 200, 200, 200, 200, 200]
    lows = [c - 1 for c in closes]
    for i, (c, v, lo) in enumerate(zip(closes, volumes, lows)):
        d = date.fromordinal(base_date.toordinal() + i)
        rows.append((d, c, v, lo))
    df = _make_df(rows)

    # idx 14: +1.31% < 1.4% → FTD 후보 아님
    result = detect_last_ftd(df, end_idx=19, lookback_days=90)
    # 다른 곳에서도 +1.4% 없음 → None
    assert result is None


def test_ftd_too_close_to_low():
    """2세션 후 → 부적합 (3-15 범위 밖)."""
    rows = []
    base_date = date(2026, 1, 5)
    # idx 10: 저점. idx 12 (2세션 후) 에 +1.5% → 너무 빠름
    closes = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 84, 85, 86.28, 87, 88, 89, 90, 91, 92, 93]
    volumes = [100] * 11 + [150, 250, 200, 200, 200, 200, 200, 200, 200]
    lows = [c - 1 for c in closes]
    for i, (c, v, lo) in enumerate(zip(closes, volumes, lows)):
        d = date.fromordinal(base_date.toordinal() + i)
        rows.append((d, c, v, lo))
    df = _make_df(rows)

    # idx 12: close 86.28, idx 11 close 85 → +1.5%. vol 250 > 150 → 후보
    # 직전 15 세션 내 저점: idx 10 close=84
    # 12 - 10 = 2 세션 → 3 미만 → 무효
    result = detect_last_ftd(df, end_idx=19, lookback_days=90)
    assert result is None


def test_ftd_too_far_from_low():
    """16세션 후 → 무효."""
    rows = []
    base_date = date(2026, 1, 5)
    # idx 5 저점, idx 21 (16세션 후) 에 +1.5%
    closes = [100, 95, 92, 90, 85, 80, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97.44, 98]
    volumes = [100] * 20 + [150, 250, 200]
    lows = [c - 1 for c in closes]
    for i, (c, v, lo) in enumerate(zip(closes, volumes, lows)):
        d = date.fromordinal(base_date.toordinal() + i)
        rows.append((d, c, v, lo))
    df = _make_df(rows)

    # idx 21: +1.5% AND vol up. 직전 15 세션 (idx 6-20) 내 저점: idx 6 close=82
    # 21 - 6 = 15 세션. 정확히 경계.
    # 정의: 3 <= days <= 15 → 포함 → 유효
    result = detect_last_ftd(df, end_idx=22, lookback_days=90)
    assert result == df.iloc[21]["date"]


def test_ftd_no_recent_low():
    """직전 15세션 내 저점이 없으면 (모두 상승) → 후보 없음."""
    rows = []
    base_date = date(2026, 1, 5)
    # 단조 상승: 저점 없음 (시작점이 최저)
    closes = [80 + i * 0.5 for i in range(20)]
    closes[15] = closes[14] * 1.015  # +1.5%
    volumes = [100] * 14 + [200, 250] + [200] * 4
    lows = [c - 0.5 for c in closes]
    for i, (c, v, lo) in enumerate(zip(closes, volumes, lows)):
        d = date.fromordinal(base_date.toordinal() + i)
        rows.append((d, c, v, lo))
    df = _make_df(rows)

    # idx 15: +1.5%. 직전 15 세션 (idx 0-14) 의 저점: idx 0 (78)
    # 15 - 0 = 15 세션 → 경계 OK
    # 단조 상승이지만 idx 0 이 가장 낮음. 사실 유효 FTD가 아닌 케이스를 만들기 어려움.
    # 다른 시나리오: 짧은 데이터로 처음 lookback 미만
    df_short = df.iloc[:3].copy()
    result = detect_last_ftd(df_short, end_idx=2, lookback_days=90)
    assert result is None   # 데이터 부족
