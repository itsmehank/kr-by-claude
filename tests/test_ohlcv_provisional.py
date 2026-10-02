"""#207 회신 21 Q-5a ③ — 당일 스냅샷 잠정값 방어(커밋 전 검사·10분 대기·재조회 1회·저장 0)."""
import pathlib
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


def test_guard_today_empty_refetch_raises_instead_of_dropping_today(monkeypatch):
    """재조회가 빈 스냅샷(KRX 차단/빈 응답)이면 오늘 행을 전부 지우고 '위반 0' 으로 통과시키면 안 된다 — 예외(저장 0)."""
    monkeypatch.setattr(provisional, "_sleep", lambda s: None)
    frames = {"A": _frame([(YDAY, 10, 12, 9, 11, 100), (TODAY, 10, 12, 9, 13, 50)]),
              "B": _frame([(TODAY, 20, 22, 19, 21, 10)])}
    empty = _snap([]); empty.attrs["snapshot_status"] = "blocked"
    with pytest.raises(AdjustmentTripwireError, match="재조회 스냅샷 비어 있음"):
        provisional.guard_today(frames, TODAY, refetch=lambda d: empty, wait_s=1)


def test_guard_today_refetch_missing_ticker_is_counted_not_silently_dropped(monkeypatch, caplog):
    """재조회 스냅샷에 없는 종목의 오늘 행 제거는 유지하되 건수를 로그에 남긴다(무음 소멸 금지)."""
    import logging
    monkeypatch.setattr(provisional, "_sleep", lambda s: None)
    frames = {"A": _frame([(TODAY, 10, 12, 9, 13, 50)]), "B": _frame([(TODAY, 20, 22, 19, 21, 10)])}
    with caplog.at_level(logging.WARNING, logger="kr_pipeline.ohlcv.provisional"):
        out = provisional.guard_today(frames, TODAY, refetch=lambda d: _snap([("A", TODAY, 10, 12, 9, 11, 60)]), wait_s=1)
    assert out["B"].empty and "provisional_dropped_today: 1 종목" in caplog.text and "'B'" in caplog.text


def test_guard_today_dropped_tickers_promoted_to_run_warnings(monkeypatch):
    """스냅샷에 없어 오늘 행이 제거된 종목 수는 로그만이 아니라 run warnings 에도 남는다(pipeline_runs 영속, 2차 리뷰)."""
    monkeypatch.setattr(provisional, "_sleep", lambda s: None)
    frames = {"A": _frame([(TODAY, 10, 12, 9, 13, 50)]), "B": _frame([(YDAY, 20, 22, 19, 21, 10), (TODAY, 20, 22, 19, 21, 10)])}
    warnings: list[str] = []
    out = provisional.guard_today(frames, TODAY, refetch=lambda d: _snap([("A", TODAY, 10, 12, 9, 11, 60)]), wait_s=1, warnings=warnings)
    assert list(out["B"]["date"]) == [YDAY]
    assert len(warnings) == 1 and warnings[0].startswith("provisional_dropped_today: 1") and "B" in warnings[0]


def test_guard_today_refetch_transport_error_becomes_tripwire(monkeypatch):
    """재조회 전송 예외(with_retry reraise)는 날 traceback 이 아니라 provisional_snapshot 트립와이어로 수렴(두 계수 로그 포함)."""
    monkeypatch.setattr(provisional, "_sleep", lambda s: None)
    frames = {"A": _frame([(TODAY, 10, 12, 9, 13, 50)])}
    def boom(d): raise TimeoutError("read timed out")
    with pytest.raises(AdjustmentTripwireError, match="재조회 실패.*read timed out"):
        provisional.guard_today(frames, TODAY, refetch=boom, wait_s=1)


def test_replace_today_rows_fills_ticker_absent_from_first_snapshot():
    """초회 스냅샷에 없던 종목(빈 프레임)이 재조회에 있으면 그 오늘 행을 받는다."""
    frames = {"X": pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "value", "change_pct"])}
    out = provisional.replace_today_rows(frames, _snap([("X", TODAY, 1, 2, 1, 1.5, 10)]), TODAY)
    assert len(out["X"]) == 1 and out["X"]["date"].iloc[0] == TODAY


def test_guard_today_persists_evidence_before_raising(monkeypatch):
    """저장 0 경로에서도 KRX 응답은 파일로 남긴다(운영 규칙 5) — 초회 오늘 행 + 재조회 스냅샷."""
    monkeypatch.setattr(provisional, "_sleep", lambda s: None)
    saved = []
    monkeypatch.setattr(provisional, "_persist_evidence", lambda today, first, snap, reason: saved.append((today, len(first), 0 if snap is None else len(snap), reason)))
    frames = {"A": _frame([(YDAY, 10, 12, 9, 11, 100), (TODAY, 10, 12, 9, 13, 50)]), "B": _frame([(TODAY, 20, 22, 19, 21, 10)])}
    with pytest.raises(AdjustmentTripwireError):
        provisional.guard_today(frames, TODAY, refetch=lambda d: _snap([("A", TODAY, 10, 12, 9, 12.5, 60)]), wait_s=1)
    assert saved == [(TODAY, 2, 1, "still_provisional")]      # first = 오늘 행 2개(A·B), snap 1행


def test_persist_evidence_writes_json(tmp_path, monkeypatch):
    monkeypatch.setenv("KR_VERIFICATION_DIR", str(tmp_path))
    first = _snap([("A", TODAY, 10, 12, 9, 13, 50)]); snap = _snap([("A", TODAY, 10, 12, 9, 12.5, 60)])
    path = provisional._persist_evidence(TODAY, first, snap, "still_provisional")
    import json
    doc = json.loads(pathlib.Path(path).read_text())
    assert doc["reason"] == "still_provisional" and len(doc["first_today_rows"]) == 1 and len(doc["refetch_rows"]) == 1
    assert str(tmp_path) in path and "20260930" in path


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
    monkeypatch.setattr(provisional, "_persist_evidence", lambda *a, **k: None)
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
