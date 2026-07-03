"""변형 시장 사다리 (prereg v3.2) — 규칙 우선순위·FTD 유효성 단위 테스트."""
from datetime import date


def _ladder(**kw):
    from kr_pipeline.backtest.market_regime import variant_ladder
    base = dict(close=100.0, sma_50=95.0, sma_200=90.0, off_high_pct=-5.0,
                dist_count=2, ftd_valid=True, days_since_ftd=30)
    base.update(kw)
    return variant_ladder(**base)


def test_priority_preserved_deep_bottom_still_downtrend():
    """규칙1이 4' 보다 상위 — 깊은 하락에선 유효 FTD 가 있어도 downtrend."""
    assert _ladder(close=80, sma_50=85, sma_200=90, off_high_pct=-30,
                   ftd_valid=True) == "downtrend"


def test_shallow_pullback_with_valid_ftd_is_confirmed():
    """핵심 변경: 얕은 조정(off>-10)에서 close<SMA50 이어도 유효 FTD+dist<6 → confirmed.
    (현행 사다리는 close>SMA50 대기 때문에 correction/rally 로 떨어뜨림)"""
    assert _ladder(close=94, sma_50=95, sma_200=90, off_high_pct=-8.0,
                   ftd_valid=True, dist_count=2) == "confirmed_uptrend"


def test_no_time_expiry():
    """90일 시간창 제거 — FTD 120일 경과여도 유효하면 confirmed 유지."""
    assert _ladder(days_since_ftd=120, ftd_valid=True) == "confirmed_uptrend"


def test_dist6_blocks_confirmed():
    """규칙3 상위 유지 — dist≥6 + FTD 10일 경과면 correction (FTD 무효화)."""
    assert _ladder(dist_count=6, days_since_ftd=30) == "correction"


def test_invalidated_ftd_falls_to_rally_attempt():
    assert _ladder(ftd_valid=False) == "rally_attempt"          # close>sma50
    assert _ladder(ftd_valid=False, close=94, sma_50=95,
                   off_high_pct=-8.0) == "correction"           # fallback


def test_rally_low_invalidation_series():
    """FTD 유효성: 랠리 저점(FTD 포함 직전 15세션 최저 low) 종가 이탈 시 무효."""
    from kr_pipeline.backtest.market_regime import ftd_validity_series
    # 세션: 저점 90(랠리 저점) → FTD(+1.4% 급등일) → 이후 종가 89 로 저점 이탈
    dates = [date(2024, 1, i) for i in (2, 3, 4, 5, 8, 9)]
    lows = [92, 90, 91, 93, 94, 88]
    closes = [93, 91, 92, 95, 96, 89]
    ftd_dates = {dates[3]}          # 1/5 를 FTD 로 가정
    v = ftd_validity_series(dates, closes, lows, ftd_dates)
    assert v[dates[3]] is True      # FTD 당일 유효
    assert v[dates[4]] is True      # 96 > 랠리저점 90
    assert v[dates[5]] is False     # 종가 89 < 90 → 무효
