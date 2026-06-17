from datetime import date

from api.services.minervini_detail_builder import (
    margin_pct_c1, margin_pct_c2, margin_pct_c3, margin_pct_c5, margin_pct_c6,
    margin_pct_c7, margin_pct_c8, build_minervini_detail,
)


def test_margin_pct_c1_basic():
    """close > sma_150 > sma_200 의 최소 chain margin."""
    values = {"close": 110, "sma_150": 105, "sma_200": 100}
    # close vs sma_150: (110-105)/105*100 = 4.76
    # sma_150 vs sma_200: (105-100)/100*100 = 5.0
    # min → 4.76
    result = margin_pct_c1(values)
    assert abs(result - 4.76) < 0.01


def test_margin_pct_c2_basic():
    """sma_150 > sma_200."""
    values = {"sma_150": 105, "sma_200": 100}
    assert margin_pct_c2(values) == 5.0


def test_margin_pct_c3_basic():
    """sma_200 today > 22일 전 sma_200 의 상승률."""
    values = {"sma_200_today": 105, "sma_200_22d_ago": 100}
    # (105 - 100) / 100 * 100 = 5.0
    assert margin_pct_c3(values) == 5.0


def test_margin_pct_c3_missing_value_returns_none():
    """sma_200_22d_ago 가 None 이면 margin = None."""
    assert margin_pct_c3({"sma_200_today": 105, "sma_200_22d_ago": None}) is None
    assert margin_pct_c3({"sma_200_today": None, "sma_200_22d_ago": 100}) is None
    assert margin_pct_c3({"sma_200_today": 105, "sma_200_22d_ago": 0}) is None


def test_margin_pct_c5_basic():
    """close > sma_50."""
    values = {"close": 110, "sma_50": 100}
    assert margin_pct_c5(values) == 10.0


def test_margin_pct_c6_basic():
    """close >= w52_low * 1.25. 임계 = 125."""
    values = {"close": 130, "w52_low": 100}
    # threshold = 125, (130-125)/125*100 = 4.0
    assert margin_pct_c6(values) == 4.0


def test_margin_pct_c7_basic():
    """close >= w52_high * 0.75. 임계 = 75."""
    values = {"close": 80, "w52_high": 100}
    # threshold = 75, (80-75)/75*100 = 6.67
    result = margin_pct_c7(values)
    assert abs(result - 6.67) < 0.01


def test_margin_pct_c8_basic():
    """rs_rating - 70."""
    values = {"rs_rating": 95}
    assert margin_pct_c8(values) == 25.0


def test_build_minervini_detail_full(db):
    """daily_indicators 에서 최근 행 조회 → 8 조건 detail dict."""
    from datetime import date as _date
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('MIN1', 'M', 'KOSPI') ON CONFLICT DO NOTHING")
        cur.execute(
            """INSERT INTO daily_indicators
              (ticker, date, adj_close, sma_50, sma_150, sma_200, w52_high, w52_low,
               rs_rating, minervini_c1, minervini_c2, minervini_c3, minervini_c4, minervini_c5,
               minervini_c6, minervini_c7, minervini_c8, minervini_pass)
              VALUES ('MIN1', '2026-05-17', 110, 100, 95, 90, 130, 60, 95,
                      TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE, TRUE)
              ON CONFLICT DO NOTHING"""
        )
    db.commit()

    detail = build_minervini_detail(db, "MIN1", on_date=_date(2026, 5, 17))
    assert "c1" in detail
    assert detail["c1"]["passed"] is True
    assert detail["c1"]["description"]
    assert "margin_pct" in detail["c1"]


def test_margin_pct_c6_w52low_zero_returns_none():
    """w52_low=0 (데이터 결함) → ÷0 방지, None (no crash)."""
    assert margin_pct_c6({"close": 5330, "w52_low": 0}) is None


def test_margin_pct_c5_sma50_zero_returns_none():
    """sma_50=0 → ÷0 방지, None."""
    assert margin_pct_c5({"close": 100, "sma_50": 0}) is None


def test_margin_pct_c7_w52high_zero_returns_none():
    """w52_high=0 → ÷0 방지, None."""
    assert margin_pct_c7({"close": 100, "w52_high": 0}) is None
