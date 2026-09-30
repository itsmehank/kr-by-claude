"""#207 회신 21 Q-5a ③ — 당일 스냅샷 잠정값 방어(커밋 전 검사·10분 대기·재조회 1회·저장 0)."""
from datetime import date, timedelta

import pandas as pd
import pytest

from kr_pipeline.ohlcv import provisional
from kr_pipeline.ohlcv.tripwires import AdjustmentTripwireError

TODAY = date(2026, 9, 30)
YDAY = TODAY - timedelta(days=1)


def _frame(rows):
    """rows = [(date, open, high, low, close, volume)]."""
    return pd.DataFrame([{"date": d, "open": o, "high": h, "low": l, "close": c, "volume": v, "value": v * c, "change_pct": 0.0}
                         for d, o, h, l, c, v in rows])


def _snap(rows):
    """재조회 스냅샷: ticker 컬럼 포함."""
    return pd.DataFrame([{"ticker": t, "date": d, "open": o, "high": h, "low": l, "close": c, "volume": v, "value": v * c, "change_pct": 0.0}
                         for t, d, o, h, l, c, v in rows])


def test_count_today_violations_only_today_and_non_halt():
    frames = {
        "A": _frame([(YDAY, 10, 12, 9, 13, 100), (TODAY, 10, 12, 9, 13, 100)]),   # 어제 위반(무시)·오늘 위반
        "B": _frame([(TODAY, 10, 12, 9, 11, 100)]),                              # 정상
        "C": _frame([(TODAY, 0, 0, 0, 5, 0)]),                                    # 할트(high=0) 제외
        "D": pd.DataFrame(),
    }
    n, sample = provisional.count_today_violations(frames, TODAY)
    assert (n, sample) == (1, ["A"])


def test_guard_today_passes_when_clean(monkeypatch):
    calls = []
    monkeypatch.setattr(provisional, "_sleep", lambda s: calls.append(("sleep", s)))
    frames = {"A": _frame([(TODAY, 10, 12, 9, 11, 100)])}
    out = provisional.guard_today(frames, TODAY, refetch=lambda d: calls.append(("refetch", d)) or _snap([]))
    assert out is frames and calls == []


def test_guard_today_refetch_fixes_rows(monkeypatch):
    calls = []
    monkeypatch.setattr(provisional, "_sleep", lambda s: calls.append(("sleep", s)))
    frames = {"A": _frame([(YDAY, 10, 12, 9, 11, 100), (TODAY, 10, 12, 9, 13, 50)]),
              "B": _frame([(TODAY, 20, 22, 19, 21, 10)])}

    def refetch(d):
        calls.append(("refetch", d))
        return _snap([("A", TODAY, 10, 12, 9, 11, 120), ("B", TODAY, 20, 22, 19, 20, 12)])

    out = provisional.guard_today(frames, TODAY, refetch=refetch, wait_s=600)
    assert calls == [("sleep", 600), ("refetch", TODAY)]
    a = out["A"]; assert list(a["date"]) == [YDAY, TODAY]
    assert float(a[a["date"] == TODAY]["close"].iloc[0]) == 11 and int(a[a["date"] == TODAY]["volume"].iloc[0]) == 120
    assert float(out["B"]["close"].iloc[0]) == 20                          # 위반 아니던 종목도 재조회 값으로 교체


def test_guard_today_still_provisional_raises_without_saving(monkeypatch):
    monkeypatch.setattr(provisional, "_sleep", lambda s: None)
    frames = {"A": _frame([(TODAY, 10, 12, 9, 13, 50)])}
    with pytest.raises(AdjustmentTripwireError, match="provisional_snapshot"):
        provisional.guard_today(frames, TODAY, refetch=lambda d: _snap([("A", TODAY, 10, 12, 9, 12.5, 60)]), wait_s=1)


def test_run_upsert_step0_blocks_provisional_today(monkeypatch, db):
    """통합: 오늘 봉 잠정값이면 ① 커밋 전에 예외 — daily_prices 에 0행."""
    from kr_pipeline.ohlcv import modes
    today = date.today()
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('PRV1','PRV1','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM daily_prices WHERE ticker='PRV1'")
    db.commit()
    prov = {"PRV1": _frame([(today, 100, 110, 95, 120, 1000)])}
    monkeypatch.setattr(modes, "fetch_raw_datewise", lambda tickers, s, e: (prov, []))
    monkeypatch.setattr(modes, "fetch_market_snapshot", lambda d: _snap([("PRV1", today, 100, 110, 95, 118, 1100)]))
    monkeypatch.setattr(provisional, "_sleep", lambda s: None)
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])
    with pytest.raises(AdjustmentTripwireError, match="provisional_snapshot"):
        modes._run_upsert(db, ["PRV1"], today - timedelta(days=5), today, 1, modes.Mode.INCREMENTAL)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM daily_prices WHERE ticker='PRV1'")
        assert cur.fetchone()[0] == 0
    with db.cursor() as cur:
        cur.execute("DELETE FROM stocks WHERE ticker='PRV1'")
    db.commit()


def test_run_upsert_step0_skipped_when_end_is_not_today(monkeypatch, db):
    """end 가 어제(20:25 전 기본값)면 ⓪ 검사 자체를 하지 않는다 — 과거 봉은 회신 17 순서."""
    from kr_pipeline.ohlcv import modes
    yday = date.today() - timedelta(days=1)
    called = []
    monkeypatch.setattr(modes, "fetch_raw_datewise", lambda tickers, s, e: ({}, []))
    monkeypatch.setattr(modes.provisional, "guard_today", lambda *a, **k: called.append(1))
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])
    modes._run_upsert(db, [], yday - timedelta(days=5), yday, 1, modes.Mode.INCREMENTAL)
    assert called == []
