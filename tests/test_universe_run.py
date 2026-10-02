"""#221 — universe 실행 경로(run_universe) 통합: KRX 전부 monkeypatch, 10-01 변동 재현(자동 수용) + 잔여(보고서 1회·실패)."""
from datetime import date

import pandas as pd
import pytest

from kr_pipeline.universe import __main__ as um
from kr_pipeline.universe.guards import UniverseGuardError, write_exclusion_snapshot


def _raw(rows):
    return pd.DataFrame(rows, columns=["ticker", "name", "market"])


@pytest.fixture
def quiet_universe(db, monkeypatch):
    """활성 유니버스를 비우고(가드 a/b 전제) 외부 접촉 전부 차단. run_tracking 은 commit 하므로 db 픽스처 ROLLBACK 격리가 깨진다 —
    commit 없는 가짜로 바꿔 kr_test 를 더럽히지 않는다(실측: 1차 실행이 stocks·스냅샷 행을 영구 커밋해 다른 테스트 2건 오염)."""
    from contextlib import contextmanager

    @contextmanager
    def _fake_run_tracking(conn, *, pipeline, mode, params):
        yield {"run_id": -1, "warnings": [], "rows_affected": None, "total_count": None, "details": None}

    monkeypatch.setattr(um, "run_tracking", _fake_run_tracking)
    with db.cursor() as cur:
        cur.execute("UPDATE stocks SET delisted_at = CURRENT_DATE WHERE delisted_at IS NULL")
    monkeypatch.setattr(um, "fetch_sectors", lambda d, m: pd.DataFrame(columns=["ticker", "sector"]))
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: {})
    monkeypatch.setattr(um, "mark_delisted", lambda conn, current_tickers, on_date: 0)


def test_run_universe_reproduces_2026_10_01_and_auto_accepts(db, quiet_universe, monkeypatch):
    prev = pd.DataFrame([("465320", "교보15호스팩", "KOSDAQ", "주권", "spac"), ("0004Y0", "디비금융제14호스팩", "KOSDAQ", "주권", "spac")],
                        columns=["ticker", "name", "market", "security_group", "axis"])
    write_exclusion_snapshot(db, date(2026, 9, 22), prev)
    raw = _raw([("U221X0", "유이이일", "KOSPI"), ("0004Y0", "디비금융제14호스팩", "KOSDAQ"),
                ("0200G0", "한국제17호스팩", "KOSDAQ"), ("0209J0", "KB제34호스팩", "KOSDAQ")])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: {t: "주권" for t in raw["ticker"]})
    reports = []
    info = um.run_universe(db, today=date(2026, 10, 1), accept_exclusion_diff=False, strict=False,
                           report=lambda conn, diff, **kw: reports.append(diff))
    assert info["exclusion_auto_accepted"] == {"removed_delisted": ["465320"], "added_new_listing": ["0200G0", "0209J0"]}
    assert info["exclusion_unexplained"] == {"added": [], "removed": []} and reports == []
    with db.cursor() as cur:
        cur.execute("SELECT ticker FROM universe_exclusion_snapshot WHERE snapshot_date='2026-10-01' ORDER BY 1")
        assert [r[0] for r in cur.fetchall()] == ["0004Y0", "0200G0", "0209J0"]


def test_run_universe_unexplained_sends_report_once_and_fails(db, quiet_universe, monkeypatch):
    prev = pd.DataFrame([("0004Y0", "디비금융제14호스팩", "KOSDAQ", "주권", "spac")], columns=["ticker", "name", "market", "security_group", "axis"])
    write_exclusion_snapshot(db, date(2026, 9, 22), prev)
    with db.cursor() as cur:   # 기존 종목(폐지 이력) → 이번에 배제 축에 걸림 = #199 유형
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('088980','맵스리얼티','KOSPI') ON CONFLICT (ticker) DO NOTHING")
    raw = _raw([("U221X0", "유이이일", "KOSPI"), ("0004Y0", "디비금융제14호스팩", "KOSDAQ"), ("088980", "맵스리얼티", "KOSPI")])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "_security_groups_fail_open",
                        lambda today, warnings: {"U221X0": "주권", "0004Y0": "주권", "088980": "부동산투자회사"})
    reports = []
    with pytest.raises(UniverseGuardError, match="088980"):
        um.run_universe(db, today=date(2026, 10, 1), accept_exclusion_diff=False, strict=False,
                        report=lambda conn, diff, **kw: reports.append((diff, kw.get("snapshot_date"))))
    assert len(reports) == 1 and [u["ticker"] for u in reports[0][0].unexplained_added] == ["088980"]
    assert reports[0][1] == date(2026, 10, 1)
