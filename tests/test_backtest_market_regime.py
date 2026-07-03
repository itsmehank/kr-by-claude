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


def test_bottoming_series_episode_lifecycle():
    """v4.1: 15세션 신저가 → 첫 상승마감부터 활성, 저점 종가이탈 시 리셋,
    신저가 갱신 시 에피소드 교체."""
    from kr_pipeline.backtest.market_regime import bottoming_series
    dates = [date(2024, 1, i) for i in range(2, 12)]
    #        저점    하락    반등(활성)         이탈     신저가   반등(새 에피소드)
    lows =  [95, 90, 91, 92, 93, 94, 89.5, 88, 87, 88]
    closes = [96, 91, 90.5, 93, 94, 95, 89.8, 88.5, 88, 90]
    b = bottoming_series(dates, closes, lows)
    assert b[dates[2]] == (False, None) or b[dates[2]][0] is False  # 하락마감 — 미활성
    assert b[dates[3]][0] is True and b[dates[3]][1] == dates[1]   # 93>90.5 상승마감, 에피소드=1/3 저점일
    assert b[dates[5]][0] is True
    # 1/8: low 89.5 는 직전 15세션 min(90) 미만 → 신저가 → 리셋 (새 레그, 미활성)
    assert b[dates[6]][0] is False
    # 1/9·1/10 연속 신저가 → 계속 미활성, 1/11 상승마감(90>88) → 새 에피소드(저점일=1/10)
    assert b[dates[9]][0] is True and b[dates[9]][1] == dates[8]
