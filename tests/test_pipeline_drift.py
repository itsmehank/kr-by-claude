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
    """reload: 미기록 조정일 → ingest(기록; 시임 이후 행 raw×F 재유도 — 09-22 는 ADJ_NAVER_HISTORY_THROUGH 이전이라
    시임 이전 소급 없음) → daily Phase A → weekly 재집계 → weekly Phase A. Naver 호출 없음."""
    import kr_pipeline.pipeline.drift as d
    _seed(db, "DR5", [(date(2026, 9, 18), 1000, 0.0), (date(2026, 9, 21), 1000, 0.0), (date(2026, 9, 22), 8000, 0.0)])
    calls = []
    mocker.patch.object(d.indicators, "recompute_ticker_daily", side_effect=lambda conn, t: calls.append(("ind_daily", t)) or 5)
    mocker.patch.object(d.weekly, "run", side_effect=lambda *a, **k: calls.append(("weekly", k.get("only_tickers"))) or _stats())
    mocker.patch.object(d.indicators, "recompute_ticker_weekly", side_effect=lambda conn, t: calls.append(("ind_weekly", t)) or 3)
    out = d.reload_ticker(db, "DR5", as_of=date(2026, 9, 23))
    assert [c[0] for c in calls] == ["ind_daily", "weekly", "ind_weekly"] and calls[1][1] == ["DR5"]
    assert out["ticker"] == "DR5" and out["adj_events"] == 1 and out["adj_rows"] == 3   # 시임 이후 3행 재유도
    with db.cursor() as cur:
        cur.execute("SELECT date, adj_close FROM daily_prices WHERE ticker='DR5' ORDER BY 1")
        assert [(dt, float(a)) for dt, a in cur.fetchall()] == [(date(2026, 9, 18), 8000.0), (date(2026, 9, 21), 8000.0), (date(2026, 9, 22), 8000.0)]
        cur.execute("SELECT count(*) FROM adj_factor_events WHERE ticker='DR5'")
        assert cur.fetchone()[0] == 1
    # 멱등: 두 번째 reload 는 이벤트 0·소급 0
    out2 = d.reload_ticker(db, "DR5", as_of=date(2026, 9, 23))
    assert out2["adj_events"] == 0 and out2["adj_rows"] == 0
