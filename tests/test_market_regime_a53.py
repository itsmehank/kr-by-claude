# (#53) Arm-53 사다리 — LOCKED 설계 §4 단위 검증 (DB-free).
from datetime import date

from kr_pipeline.backtest.market_regime import variant_ladder_a53
from kr_pipeline.market_context.compute.status import determine_status

DEEP = dict(close=80.0, sma_50=85.0, sma_200=100.0, off_high_pct=-30.0)


def test_a53_confirmed_fires_in_deep_bottom_with_valid_ftd():
    """선점 해소 핵심: 깊은 바닥 + 유효 FTD + close>SMA50 → confirmed.
    (현행 사다리는 같은 입력에서 downtrend — 규칙 1 선점.)"""
    st = variant_ladder_a53(close=86.0, sma_50=85.0, sma_200=100.0,
                            off_high_pct=-30.0, dist_count=2,
                            ftd_valid=True, days_since_ftd=5)
    assert st == "confirmed_uptrend"
    cur = determine_status(close=86.0, sma_50=85.0, sma_200=100.0,
                           pct_off_yearly_high=-30.0, dist_count=2,
                           last_ftd_date=date(2020, 4, 1),
                           today_date=date(2020, 4, 6))
    assert cur == "downtrend"    # 대조: 현행은 선점으로 무시


def test_a53_no_time_expiry():
    """만료 제거: FTD 200일 경과라도 가격 유효하면 confirmed (D3/D4)."""
    st = variant_ladder_a53(close=86.0, sma_50=85.0, sma_200=100.0,
                            off_high_pct=-30.0, dist_count=2,
                            ftd_valid=True, days_since_ftd=200)
    assert st == "confirmed_uptrend"


def test_a53_close_below_sma50_waits():
    """D2: close>SMA50 대기 유지 — 유효 FTD 라도 50일선 아래면 confirmed 불가."""
    st = variant_ladder_a53(**DEEP, dist_count=2, ftd_valid=True,
                            days_since_ftd=3)
    assert st == "downtrend"     # 2′ 불성립 → 3′ 로 낙하


def test_a53_price_invalidated_falls_through():
    """§4 영향 범위 ③: 가격 무효화된 FTD 는 1′·2′ 미발화 — 구규칙 동작."""
    st = variant_ladder_a53(close=96.0, sma_50=95.0, sma_200=100.0,
                            off_high_pct=-8.0, dist_count=2,
                            ftd_valid=False, days_since_ftd=5)
    assert st == "rally_attempt"


def test_a53_distribution_invalidation_precedes_confirmed():
    """1′: dist≥6 ∧ 유효 FTD ∧ >10일 → correction (confirmed·downtrend 보다 앞)."""
    st = variant_ladder_a53(close=86.0, sma_50=85.0, sma_200=100.0,
                            off_high_pct=-30.0, dist_count=6,
                            ftd_valid=True, days_since_ftd=15)
    assert st == "correction"


def test_a53_dist_blocks_confirmed_within_10d():
    """dist≥6 이지만 ≤10일이면 1′ 미발화·2′ 도 차단(dist<6 요구) → 하위 규칙."""
    st = variant_ladder_a53(close=96.0, sma_50=95.0, sma_200=100.0,
                            off_high_pct=-8.0, dist_count=6,
                            ftd_valid=True, days_since_ftd=5)
    assert st == "rally_attempt"   # E1 분배 경고 국면 — #54 는 dist<6 로 별도 배제


def test_a53_equals_current_ladder_without_ftd():
    """유효 FTD 부재 시 현행 사다리(1→2→5→6)와 완전 동일 (§4 영향 범위 ①)."""
    grid = [
        dict(close=80.0, sma_50=85.0, sma_200=100.0, off=-30.0, dist=0),
        dict(close=88.0, sma_50=90.0, sma_200=100.0, off=-12.0, dist=3),
        dict(close=96.0, sma_50=95.0, sma_200=100.0, off=-8.0, dist=7),
        dict(close=90.0, sma_50=95.0, sma_200=88.0, off=-9.0, dist=0),
        dict(close=100.0, sma_50=95.0, sma_200=90.0, off=0.0, dist=2),
        dict(close=80.0, sma_50=None, sma_200=None, off=-30.0, dist=0),
    ]
    for g in grid:
        a53 = variant_ladder_a53(close=g["close"], sma_50=g["sma_50"],
                                 sma_200=g["sma_200"], off_high_pct=g["off"],
                                 dist_count=g["dist"], ftd_valid=False,
                                 days_since_ftd=None)
        cur = determine_status(close=g["close"], sma_50=g["sma_50"],
                               sma_200=g["sma_200"],
                               pct_off_yearly_high=g["off"],
                               dist_count=g["dist"], last_ftd_date=None,
                               today_date=date(2020, 6, 1))
        assert a53 == cur, g
