"""드리프트(기업행위 조정) 감지 + 단일종목 재적재 — #207 A안 이후: Naver 접촉 0, change_pct 기반 이벤트 검출."""
from datetime import date

import pytest


def _stats():
    class _S:
        rows_affected = 0
        failures = []
    return _S()


def _seed(db, ticker, rows):
    """rows = [(date, close, change_pct)] — raw=close, adj=close."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, 'A', 'KOSPI') ON CONFLICT DO NOTHING", (ticker,))
        for d, c, cp in rows:
            cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value, change_pct) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1000, 1000, 1, %s)", (ticker, d, c, c, c, c, c, c, c, c, cp))


def test_detect_drifted_tickers_flags_unrecorded_event_only(db):
    """창 안에 change_pct 기반 조정일이 있는데 adj_factor_events 에 없으면 드리프트. 기록된 것·정상 종목은 제외. KRX·Naver 접촉 0."""
    import kr_pipeline.pipeline.drift as d
    from kr_pipeline.ohlcv import adjust
    _seed(db, "DR1", [(date(2026, 9, 21), 10000, 0.5), (date(2026, 9, 22), 80000, 0.0)])   # ×8 미기록
    _seed(db, "DR2", [(date(2026, 9, 21), 5000, 0.5), (date(2026, 9, 22), 40000, 0.0)])    # ×8 기록됨
    adjust.record_events(db, "DR2", [(date(2026, 9, 22), 8.0)])
    _seed(db, "DR3", [(date(2026, 9, 21), 100, 0.5), (date(2026, 9, 22), 101, 1.0)])      # 정상
    out = d.detect_drifted_tickers(db, as_of=date(2026, 9, 23), tickers=["DR1", "DR2", "DR3"], recent_days=10)
    assert out == ["DR1"]


def test_detect_marks_unverified_when_window_has_no_change_pct(db):
    """창 안 행 전부 change_pct NULL(등락률 미수집) = 판정 못 함 → unverified(이상 없음 아님)."""
    import kr_pipeline.pipeline.drift as d
    _seed(db, "DR4", [(date(2026, 9, 21), 100, None), (date(2026, 9, 22), 800, None)])
    unv = []
    out = d.detect_drifted_tickers(db, as_of=date(2026, 9, 23), tickers=["DR4"], recent_days=10, unverified_out=unv)
    assert out == [] and unv == ["DR4"]


def test_detect_empty_list_checks_nothing(db):
    import kr_pipeline.pipeline.drift as d
    assert d.detect_drifted_tickers(db, as_of=date(2026, 9, 23), tickers=[]) == []


def test_reload_ticker_records_applies_then_recomputes(db, mocker):
    """reload: 미기록 조정일 기록+이력 소급(×8) → daily Phase A → weekly 재집계 → weekly Phase A. Naver 호출 없음."""
    import kr_pipeline.pipeline.drift as d
    _seed(db, "DR5", [(date(2026, 9, 18), 1000, 0.0), (date(2026, 9, 21), 1000, 0.0), (date(2026, 9, 22), 8000, 0.0)])
    calls = []
    mocker.patch.object(d.indicators, "recompute_ticker_daily", side_effect=lambda conn, t: calls.append(("ind_daily", t)) or 5)
    mocker.patch.object(d.weekly, "run", side_effect=lambda *a, **k: calls.append(("weekly", k.get("only_tickers"))) or _stats())
    mocker.patch.object(d.indicators, "recompute_ticker_weekly", side_effect=lambda conn, t: calls.append(("ind_weekly", t)) or 3)
    out = d.reload_ticker(db, "DR5", as_of=date(2026, 9, 23))
    assert [c[0] for c in calls] == ["ind_daily", "weekly", "ind_weekly"] and calls[1][1] == ["DR5"]
    assert out["ticker"] == "DR5" and out["adj_events"] == 1 and out["adj_rows"] == 2
    with db.cursor() as cur:
        cur.execute("SELECT date, adj_close FROM daily_prices WHERE ticker='DR5' ORDER BY 1")
        assert [(dt, float(a)) for dt, a in cur.fetchall()] == [(date(2026, 9, 18), 8000.0), (date(2026, 9, 21), 8000.0), (date(2026, 9, 22), 8000.0)]
        cur.execute("SELECT count(*) FROM adj_factor_events WHERE ticker='DR5'")
        assert cur.fetchone()[0] == 1
    # 멱등: 두 번째 reload 는 이벤트 0·소급 0
    out2 = d.reload_ticker(db, "DR5", as_of=date(2026, 9, 23))
    assert out2["adj_events"] == 0 and out2["adj_rows"] == 0


def test_recent_corp_action_tickers_filters(db):
    """영향 이벤트·창 내·활성 종목만 distinct 반환. 비영향/창밖/상폐 제외.

    DB 의 다른(선존) 행에 영향받지 않도록 멤버십/카운트로 검증(전역 exact-match 회피).
    충돌 적은 고유 티커(CAD*) 사용.
    """
    from datetime import timedelta
    from kr_pipeline.pipeline.drift import recent_corp_action_tickers

    as_of = date(2026, 6, 1)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker,name,market) VALUES "
            "('CAD1','a','KOSPI'),('CAD2','b','KOSPI'),('CAD3','d','KOSPI'),('CAD4','e','KOSPI')"
        )
        cur.execute("UPDATE stocks SET delisted_at=%s WHERE ticker='CAD3'", (as_of,))
        cur.execute(
            "INSERT INTO corporate_actions (ticker,event_date,event_type,dart_rcept_no) VALUES "
            "('CAD1',%s,'rights_offering','cad-r1'),"   # 창 내·영향 → 포함
            "('CAD1',%s,'bonus_issue','cad-r2'),"       # 창 내·영향(중복 종목) → distinct 로 1회
            "('CAD1',%s,'rights_offering','cad-r3'),"   # 창 밖(200일 전) → 제외
            "('CAD2',%s,'cash_dividend','cad-r4'),"     # 창 내지만 비영향 → 제외
            "('CAD3',%s,'bonus_issue','cad-r5'),"       # 창 내·영향이나 상폐 → 제외
            "('CAD4',%s,'rights_offering','cad-r6')",   # 미래(as_of+5) → 상한 밖 → 제외
            (as_of - timedelta(days=10), as_of - timedelta(days=20),
             as_of - timedelta(days=200), as_of - timedelta(days=5),
             as_of - timedelta(days=3), as_of + timedelta(days=5)),
        )
    out = recent_corp_action_tickers(db, as_of=as_of, lookback_days=90)
    assert "CAD1" in out            # 창 내 영향 이벤트
    assert out.count("CAD1") == 1   # distinct: 중복 이벤트여도 1회
    assert "CAD2" not in out        # 비영향(cash_dividend)
    assert "CAD3" not in out        # 상폐
    assert "CAD4" not in out        # 미래 event_date (상한 밖)


# ====== P1-5 Part C: '검증 못 함(unverified)' 을 '이상 없음' 과 구분 ======
