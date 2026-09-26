"""#207 회신 16 — 수정주가 내부 정합성 트립와이어(지표 단계 fail-closed, 수집은 fail-open).

(1′) 일별 조정 종목 수 ≤ 사전등록 분포(2026-01-02~09-11 171거래일 Naver 구정의 R 점프 0.5%↑: p50 1·p90 6·p99 13·**max 16**)
(2)  시임 이후 행: adj_high ≤ raw_high×계수, adj_low ≥ raw_low×계수 (계수 = adj_close/close, 허용 0.5% — 기준선 1/176,076)
(3)  raw: low ≤ close ≤ high (비할트, 기준선 0/5,284,501)
임계는 실측 분포에서 사전등록(새 숫자 창작 없음). 위반 → AdjustmentTripwireError → indicators run failed(run_tracking).
"""
from datetime import date

import pytest

from kr_pipeline.ohlcv import tripwires as tw


def _stock(db, t):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, 'T', 'KOSPI') ON CONFLICT DO NOTHING", (t,))


def _row(db, t, d, *, o=100, h=110, l=90, c=105, ac=None, ah=None, al=None, ao=None):
    _stock(db, t)
    ac = c if ac is None else ac; ah = h if ah is None else ah; al = l if al is None else al; ao = o if ao is None else ao
    with db.cursor() as cur:
        cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1000, 1000, 1)", (t, d, o, h, l, c, ac, ah, al, ao))


D = date(2031, 2, 3)   # 다른 테스트 데이터와 겹치지 않는 시임 이후 날짜


def test_daily_event_count_within_baseline_passes(db):
    for i in range(tw.ADJ_DAILY_EVENTS_MAX):
        t = f"TW{i:03d}"; _stock(db, t)
        with db.cursor() as cur:
            cur.execute("INSERT INTO adj_factor_events (ticker, date, coef) VALUES (%s, %s, 2.0)", (t, D))
    assert tw.check_adjustment_tripwires(db, start=D, end=D) == []


def test_daily_event_count_over_baseline_is_violation(db):
    for i in range(tw.ADJ_DAILY_EVENTS_MAX + 1):
        t = f"TX{i:03d}"; _stock(db, t)
        with db.cursor() as cur:
            cur.execute("INSERT INTO adj_factor_events (ticker, date, coef) VALUES (%s, %s, 2.0)", (t, D))
    v = tw.check_adjustment_tripwires(db, start=D, end=D)
    assert len(v) == 1 and "daily_event_count" in v[0] and str(D) in v[0]


def test_adj_envelope_violation_post_seam(db):
    """adj_high 가 raw_high×계수 를 0.5% 넘게 초과(연장시간 봉 유입 신호) → 위반. 정확한 배수는 통과. 시임 이전 행은 검사 안 함."""
    _row(db, "TWE1", D, ac=210, ah=232, al=180, ao=200)          # 계수 2: high 110→220 기대, 232 = +5.5%
    _row(db, "TWE2", D, ac=210, ah=220, al=180, ao=200)          # 정확
    _row(db, "TWE3", date(2026, 9, 11), ac=105, ah=130)          # 시임 이전 — 무시
    v = tw.check_adjustment_tripwires(db, start=date(2026, 9, 11), end=D)
    assert len(v) == 1 and "adj_envelope" in v[0] and "TWE1" in v[0] and "TWE3" not in v[0]


def test_raw_bar_violation(db):
    _row(db, "TWR1", D, h=100, c=105)          # close > high
    _row(db, "TWR2", D, o=0, h=0, l=0, c=105)  # 할트 마커 — 무시
    v = tw.check_adjustment_tripwires(db, start=D, end=D)
    assert len(v) == 1 and "raw_bar" in v[0] and "TWR1" in v[0]


def test_run_daily_fails_closed_on_tripwire(monkeypatch, db):
    """지표 단계: 위반이 있으면 AdjustmentTripwireError 전파(run_tracking 이 failed 기록) — 지표 미계산."""
    from kr_pipeline.indicators import modes
    monkeypatch.setattr(modes, "check_daily_ohlcv_complete", lambda conn, active_count: None)
    monkeypatch.setattr(modes, "check_adjustment_tripwires", lambda conn, start, end: ["raw_bar: X"])
    monkeypatch.setattr(modes, "load_active_tickers_with_market", lambda conn, limit=None: [("X", "KOSPI")])
    with pytest.raises(tw.AdjustmentTripwireError, match="raw_bar"):
        modes.run_daily(db, modes.Mode.INCREMENTAL)
