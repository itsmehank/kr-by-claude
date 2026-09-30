"""#207 회신 21 Q-5c 1 — 경계일(정의가 다른 전일) 거래량 비교 무효화(분배일·정체일·FTD)."""
from datetime import date, timedelta

import pandas as pd

from kr_pipeline.market_context.compute.distribution_day import count_distribution_days
from kr_pipeline.market_context.compute.follow_through import detect_last_ftd
from kr_pipeline.market_context.compute.regime import regime_comparable


def _df(rows):
    return pd.DataFrame(rows, columns=["date", "close", "volume", "high", "low", "volume_regime"]).reset_index(drop=True)


def test_regime_comparable_rules():
    assert regime_comparable({"volume_regime": "regular"}, {"volume_regime": "regular"})
    assert not regime_comparable({"volume_regime": "extended"}, {"volume_regime": "regular"})
    assert regime_comparable({"close": 1}, {"close": 2})                       # 컬럼 없음 → 허용(구 호출처)
    assert regime_comparable({"volume_regime": None}, {"volume_regime": "regular"})


def test_distribution_day_skipped_when_regime_differs():
    base = [(date(2026, 9, 25), 100.0, 1000.0, 101.0, 99.0, "regular")]
    diff = _df(base + [(date(2026, 9, 28), 99.0, 1500.0, 100.0, 98.5, "extended")])
    same = _df(base + [(date(2026, 9, 28), 99.0, 1500.0, 100.0, 98.5, "regular")])
    assert count_distribution_days(same, end_idx=1, lookback=25) == 1
    assert count_distribution_days(diff, end_idx=1, lookback=25) == 0


def test_distribution_day_without_regime_column_unchanged():
    df = pd.DataFrame([(100.0, 1000.0, 101.0, 99.0), (99.0, 1500.0, 100.0, 98.5)], columns=["close", "volume", "high", "low"])
    assert count_distribution_days(df, end_idx=1, lookback=25) == 1


def test_follow_through_skipped_when_regime_differs():
    rows = []
    d = date(2026, 9, 1)
    for i in range(12):                                   # 하락 후 저점
        rows.append((d + timedelta(days=i), 100.0 - i, 1000.0, 101.0 - i, 99.0 - i, "regular"))
    low_day = d + timedelta(days=11)
    for i in range(1, 4):                                 # 저점 뒤 3일 횡보
        rows.append((low_day + timedelta(days=i), 89.5 + i * 0.1, 900.0, 90.0, 89.0, "regular"))
    ftd_day = low_day + timedelta(days=4)                 # 4일째 급등 + 거래량 증가 = FTD 후보
    same = _df(rows + [(ftd_day, 92.0, 1200.0, 92.5, 90.0, "regular")])
    diff = _df(rows + [(ftd_day, 92.0, 1200.0, 92.5, 90.0, "extended")])
    n = len(same) - 1
    assert detect_last_ftd(same, n, pct_threshold=1.0, lookback_days=25) == ftd_day
    assert detect_last_ftd(diff, n, pct_threshold=1.0, lookback_days=25) is None
