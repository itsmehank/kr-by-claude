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


# ---------- 회신 17 조건: 예외 위치 = raw 적재 완료 후 · adj(이벤트) 유도·지표 전 ----------

def _raw(dates_closes, cp):
    import pandas as pd
    return pd.DataFrame({"date": [d for d, _ in dates_closes], "open": [c for _, c in dates_closes], "high": [c for _, c in dates_closes],
                         "low": [c for _, c in dates_closes], "close": [c for _, c in dates_closes],
                         "volume": [100] * len(dates_closes), "value": [1] * len(dates_closes), "change_pct": cp})


def test_run_upsert_mass_false_events_stores_raw_then_fails_before_ingest(monkeypatch, db):
    """(1′) 위반(한 날짜 조정 종목 17): raw 행은 전부 적재(수집 fail-open)되고, 이벤트 기록·소급·재유도 **전**에
    AdjustmentTripwireError → ohlcv run failed → 체인 중단 → 지표 미계산."""
    from kr_pipeline.ohlcv import modes
    from kr_pipeline.ohlcv.adjust import ADJ_NAVER_HISTORY_THROUGH
    d0, d1 = date(2031, 3, 3), date(2031, 3, 4)
    tickers = [f"MF{i:03d}" for i in range(tw.ADJ_DAILY_EVENTS_MAX + 1)]
    for t in tickers:
        _row(db, t, d0, o=1000, h=1000, l=1000, c=1000)
    raws = {t: _raw([(d1, 8000)], [0.0]) for t in tickers}          # 1,000→8,000 with r=0 → 전 종목 '조정일'
    monkeypatch.setattr(modes, "fetch_raw_datewise", lambda tk, s, e: (raws, []))
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: __import__("pandas").DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])
    try:   # _run_upsert 는 종목별 commit → 시드가 kr_test 에 영속되므로 finally 정리(다른 sanity 테스트 오염 방지)
        with pytest.raises(tw.AdjustmentTripwireError, match="daily_event_count"):
            modes._run_upsert(db, tickers, d1, d1, 2, modes.Mode.INCREMENTAL)
        with db.cursor() as cur:
            cur.execute("SELECT count(*) FROM daily_prices WHERE ticker = ANY(%s) AND date = %s", (tickers, d1))
            assert cur.fetchone()[0] == len(tickers)                     # raw 적재됨(fail-open)
            cur.execute("SELECT count(*) FROM adj_factor_events WHERE ticker = ANY(%s)", (tickers,))
            assert cur.fetchone()[0] == 0                                # 이벤트 기록 0(소급·재유도 전 중단)
            cur.execute("SELECT adj_close FROM daily_prices WHERE ticker = %s AND date = %s", (tickers[0], d0))
            assert float(cur.fetchone()[0]) == 1000.0                    # 이력 불변
    finally:
        db.rollback()
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker = ANY(%s)", (tickers,))
            cur.execute("DELETE FROM stocks WHERE ticker = ANY(%s)", (tickers,))
        db.commit()


def test_run_upsert_raw_bar_violation_stores_raw_then_fails(monkeypatch, db):
    """(3) KRX raw 봉 자체 결함(close > high): 봉은 그대로 적재(수집 fail-open), 이벤트 유도 전에 중단."""
    from kr_pipeline.ohlcv import modes
    import pandas as pd
    d1 = date(2031, 3, 5)
    _stock(db, "RB1")
    raw = pd.DataFrame({"date": [d1], "open": [100], "high": [100], "low": [90], "close": [105], "volume": [100], "value": [1], "change_pct": [5.0]})
    monkeypatch.setattr(modes, "fetch_raw_datewise", lambda tk, s, e: ({"RB1": raw}, []))
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])
    try:
        with pytest.raises(tw.AdjustmentTripwireError, match="raw_bar"):
            modes._run_upsert(db, ["RB1"], d1, d1, 2, modes.Mode.INCREMENTAL)
        with db.cursor() as cur:
            cur.execute("SELECT close FROM daily_prices WHERE ticker='RB1' AND date=%s", (d1,)); assert cur.fetchone()[0] == 105
    finally:
        db.rollback()
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker='RB1'"); cur.execute("DELETE FROM stocks WHERE ticker='RB1'")
        db.commit()
