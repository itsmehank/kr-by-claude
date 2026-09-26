"""#207 A안 — KRX 정규장 raw + 기업행위 조정계수 자체 산출(회신 15·16).

계수 정의: 기준가 = close/(1+등락률/100), 조정일 = 기준가 ≠ 전일 종가, 계수 = 기준가/전일 종가.
판정 정밀도: KRX 등락률은 소수 2자리 반올림 → 기준가 = 전일 종가이면 |r_impl − r| ≤ 0.005(반올림 반폭,
half-even 경계 포함 0.005 정확히). 실측(09-14~23 20,714행): ≤0.005 18,753 · (0.005,0.006] 21(경계) ·
(0.006, 1.0] 0 · >1.0 21 → 빈 구간이 판정을 가른다. 코다코 09-10(close 410, −99.50%)은 |diff| 0.0018 → 비이벤트
(회신 15 잔차 = 반올림 역산 인공물). adj_volume = volume / 계수(Naver 구정의 관례 실측 k=1/coef²).
"""
from datetime import date

import pandas as pd
import pytest

from kr_pipeline.ohlcv import adjust

# 조정일 10건(검증 완료, Naver 구정의와 정합) — (close, prev_close, change_pct, 기대 계수)
EVENTS = [
    ("006490", date(2026, 9, 10), 1416.0, 898.0, 0.0, 1.5769),      # 정지 중 기준가 반영(등락률 0, 종가 점프)
    ("046070", date(2026, 9, 4), 82300.0, 10280.0, 0.0, 8.0058),
    ("175250", date(2026, 9, 3), 2870.0, 2170.0, 0.0, 1.3226),
    ("247540", date(2026, 9, 3), 108500.0, 108000.0, 2.07, 0.9842),
    ("290650", date(2026, 9, 3), 53100.0, 54000.0, 1.53, 0.9685),
    ("042940", date(2026, 9, 22), 5670.0, 5900.0, -0.18, 0.9627),   # 유상증자 권리락
    ("220100", date(2026, 9, 17), 6300.0, 8100.0, -6.67, 0.8334),   # 무상증자 20%
    ("475460", date(2026, 9, 16), 2610.0, 8290.0, -5.61, 0.3335),   # 무상증자 200%
    ("009620", date(2026, 9, 17), 4350.0, 870.0, 0.0, 5.0),         # 감자 후 거래재개
    ("900110", date(2026, 9, 18), 6010.0, 1201.0, 0.0, 5.004),
]


@pytest.mark.parametrize("ticker,d,close,prev,r,coef", EVENTS)
def test_coefficient_on_adjustment_days_matches_naver_old_definition(ticker, d, close, prev, r, coef):
    assert adjust.is_adjustment(close, prev, r)
    assert adjust.coefficient(close, prev, r) == pytest.approx(coef, abs=2e-3)


def test_kodaco_resume_day_is_not_adjustment_rounding_artifact():
    """046070 09-10: 82,300 → 410 = −99.5018% → KRX −99.50 (반올림). 기준가 82,000 역산은 인공물 → 비이벤트."""
    assert not adjust.is_adjustment(410.0, 82300.0, -99.50)
    assert not adjust.is_adjustment(452.0, 410.0, 10.24)          # 09-11 정상일


def test_half_even_boundary_is_not_adjustment():
    """389500 09-18: 40,000→40,850 = 2.125% → KRX 2.13(half-up). |diff| = 0.005 정확히 → 비이벤트."""
    assert not adjust.is_adjustment(40850.0, 40000.0, 2.13)
    assert not adjust.is_adjustment(7870.0, 8000.0, -1.63)


def test_missing_inputs_are_not_adjustment():
    assert not adjust.is_adjustment(100.0, None, 1.0)
    assert not adjust.is_adjustment(100.0, 0.0, 1.0)
    assert not adjust.is_adjustment(100.0, 99.0, None)


def test_factor_curve_is_product_of_later_coefficients():
    """F(t) = Π_{e > t} coef_e — 최신일 1, 조정일 당일은 포함 안 함(당일 이후 행은 새 기준)."""
    ds = [date(2026, 9, 1), date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 10)]
    ev = [(date(2026, 9, 4), 8.0), (date(2026, 9, 10), 0.5)]
    f = adjust.factor_curve(ds, ev)
    assert f == {date(2026, 9, 1): 4.0, date(2026, 9, 3): 4.0, date(2026, 9, 4): 0.5, date(2026, 9, 10): 1.0}


def test_derive_adj_scales_ohlc_and_inverse_volume_and_nullifies_halt():
    raw = pd.DataFrame([
        {"date": date(2026, 9, 1), "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000, "value": 1},
        {"date": date(2026, 9, 2), "open": 0, "high": 0, "low": 0, "close": 105, "volume": 0, "value": 0},   # halt
        {"date": date(2026, 9, 4), "open": 800, "high": 880, "low": 720, "close": 840, "volume": 100, "value": 1},
    ])
    out = adjust.derive_adj(raw, [(date(2026, 9, 4), 8.0)])
    r0 = out.iloc[0]
    assert (r0.adj_close, r0.adj_high, r0.adj_low, r0.adj_open, r0.adj_volume) == (840.0, 880.0, 720.0, 800.0, 125.0)
    assert pd.isna(out.iloc[1].adj_high) and out.iloc[1].adj_close == 840.0     # halt: OHLV NULL, close 유지(×F)
    assert out.iloc[2].adj_close == 840.0 and out.iloc[2].adj_volume == 100.0   # 조정일 당일 F=1


# ---------- DB ----------

def _seed(db, ticker, rows):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, 'A', 'KOSPI') ON CONFLICT DO NOTHING", (ticker,))
        for d, close, cp in rows:
            cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value, change_pct) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1000, 1000, 1, %s)",
                        (ticker, d, close, close, close, close, close, close, close, close, cp))


def test_detect_new_events_from_change_pct_and_record(db):
    """09-21 정상, 09-22 감자(×8, 정지 중 종가 점프·등락률 0), 09-23 정상 → 이벤트 1건 기록(종목·날짜·계수). (시임 이후 날짜)"""
    _seed(db, "AJ1", [(date(2026, 9, 21), 10280, 0.5), (date(2026, 9, 22), 82300, 0.0), (date(2026, 9, 23), 82000, -0.36)])
    ev = adjust.detect_events(db, "AJ1", since=date(2026, 9, 20))
    assert [(d, round(c, 4)) for d, c in ev] == [(date(2026, 9, 22), 8.0058)]
    n = adjust.record_events(db, "AJ1", ev)
    assert n == 1
    assert adjust.record_events(db, "AJ1", ev) == 0          # 멱등(이미 기록)
    with db.cursor() as cur:
        cur.execute("SELECT ticker, date, coef FROM adj_factor_events WHERE ticker='AJ1'")
        t, d, c = cur.fetchone(); assert (t, d) == ("AJ1", date(2026, 9, 22)) and float(c) == pytest.approx(8.0058, abs=1e-4)


def test_apply_event_rescales_history_before_event_only(db):
    """이벤트 소급: date < e 행 adj_* × coef, adj_volume ÷ coef. 당일·이후 행 불변. NULL(halt) 은 NULL 유지."""
    _seed(db, "AJ2", [(date(2026, 9, 3), 100, 0.0), (date(2026, 9, 4), 800, 0.0), (date(2026, 9, 7), 810, 1.25)])
    n = adjust.apply_event(db, "AJ2", date(2026, 9, 4), 8.0)
    assert n == 1
    with db.cursor() as cur:
        cur.execute("SELECT date, adj_close, adj_high, adj_volume FROM daily_prices WHERE ticker='AJ2' ORDER BY 1")
        rows = cur.fetchall()
    assert [(d, float(c), float(h), float(v)) for d, c, h, v in rows] == [
        (date(2026, 9, 3), 800.0, 800.0, 125.0), (date(2026, 9, 4), 800.0, 800.0, 1000.0), (date(2026, 9, 7), 810.0, 810.0, 1000.0)]


def test_events_in_frame_uses_db_prev_close_for_first_row():
    """증분 배치(raw 프레임)에서 조정일 검출 — 첫 행의 전일 종가는 DB 직전 종가(인자). 결측 change_pct 행은 건너뜀."""
    raw = pd.DataFrame([
        {"date": date(2026, 9, 14), "close": 82300, "change_pct": 0.0},
        {"date": date(2026, 9, 15), "close": 410, "change_pct": -99.50},      # 반올림 인공물 → 비이벤트
        {"date": date(2026, 9, 16), "close": 452, "change_pct": None},
        {"date": date(2026, 9, 17), "close": 2260, "change_pct": 0.0},        # 452→2260 ×5 (감자)
    ])
    ev = adjust.events_in_frame(raw, prev_close=10280.0)
    assert [(d, round(c, 4)) for d, c in ev] == [(date(2026, 9, 14), 8.0058), (date(2026, 9, 17), 5.0)]
    assert adjust.events_in_frame(raw.iloc[:1], prev_close=None) == []          # 전일 종가 없음 → 판정 안 함


def test_apply_event_until_excludes_rows_already_derived(db):
    """증분 배치 행(until 이후)은 derive_adj 로 이미 F 적용 → 소급은 until 이전 행에만."""
    _seed(db, "AJ3", [(date(2026, 9, 1), 100, 0.0), (date(2026, 9, 3), 100, 0.0), (date(2026, 9, 4), 800, 0.0)])
    n = adjust.apply_event(db, "AJ3", date(2026, 9, 4), 8.0, until=date(2026, 9, 3))
    assert n == 1
    with db.cursor() as cur:
        cur.execute("SELECT date, adj_close FROM daily_prices WHERE ticker='AJ3' ORDER BY 1")
        assert [(d, float(c)) for d, c in cur.fetchall()] == [(date(2026, 9, 1), 800.0), (date(2026, 9, 3), 100.0), (date(2026, 9, 4), 800.0)]


def test_detect_events_ignores_dates_before_self_start(db):
    """시임(ADJ_SELF_START) 이전 조정일은 Naver 이력에 내재 → 검출 대상 아님(검증 표본용 change_pct 가 있어도)."""
    _seed(db, "AJ4", [(date(2026, 9, 2), 1000, 0.0), (date(2026, 9, 3), 8000, 0.0), (date(2026, 9, 14), 8000, 0.0), (date(2026, 9, 15), 16000, 0.0)])
    ev = adjust.detect_events(db, "AJ4", since=date(2026, 9, 1))
    assert [(d, round(c, 2)) for d, c in ev] == [(date(2026, 9, 15), 2.0)]
