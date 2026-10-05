"""#221 — universe 실행 경로(run_universe) 통합: KRX 전부 monkeypatch, 10-01 변동 재현(자동 수용) + 잔여(실패 run details 보존)."""
from contextlib import contextmanager
from datetime import date

import pandas as pd
import pytest

from kr_pipeline.universe import __main__ as um
from kr_pipeline.universe.guards import UniverseGuardError, write_exclusion_snapshot
from kr_pipeline.universe.store import MAX_DELIST_RATIO


def _raw(rows):
    return pd.DataFrame(rows, columns=["ticker", "name", "market"])


@pytest.fixture
def quiet_universe(db, monkeypatch):
    """활성 유니버스를 비우고(가드 a/b 전제) 외부 접촉 전부 차단. run_tracking 은 commit 하므로 db 픽스처 ROLLBACK 격리가 깨진다 —
    commit 없는 가짜로 바꿔 kr_test 를 더럽히지 않는다. 반환 = 캡처된 state(픽스처 값으로 전달, 모듈 속성 오염 없음)."""
    captured = {}

    @contextmanager
    def _fake_run_tracking(conn, *, pipeline, mode, params):
        state = {"run_id": -1, "warnings": [], "rows_affected": None, "total_count": None, "details": None}
        captured["state"] = state
        yield state

    monkeypatch.setattr(um, "run_tracking", _fake_run_tracking)
    with db.cursor() as cur:
        cur.execute("UPDATE stocks SET delisted_at = CURRENT_DATE WHERE delisted_at IS NULL")
    monkeypatch.setattr(um, "fetch_sectors", lambda d, m: pd.DataFrame(columns=["ticker", "sector"]))
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: {})
    monkeypatch.setattr(um, "mark_delisted", lambda conn, current_tickers, on_date: 0)
    return captured


def _seed_prev(db, *rows):
    prev = pd.DataFrame(list(rows), columns=["ticker", "name", "market", "security_group", "axis"])
    write_exclusion_snapshot(db, date(2026, 9, 22), prev)


def test_run_universe_reproduces_2026_10_01_and_auto_accepts(db, quiet_universe, monkeypatch):
    _seed_prev(db, ("465320", "교보15호스팩", "KOSDAQ", "주권", "spac"), ("0004Y0", "디비금융제14호스팩", "KOSDAQ", "주권", "spac"))
    raw = _raw([("U221X0", "유이이일", "KOSPI"), ("0004Y0", "디비금융제14호스팩", "KOSDAQ"),
                ("0200G0", "한국제17호스팩", "KOSDAQ"), ("0209J0", "KB제34호스팩", "KOSDAQ")])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: {t: "주권" for t in raw["ticker"]})
    info = um.run_universe(db, today=date(2026, 10, 1))
    assert info["exclusion_auto_accepted"] == {"removed_delisted": ["465320"], "added_new_listing": ["0200G0", "0209J0"]}
    assert info["exclusion_unexplained"] == {"added": [], "removed": []} and info["report_key"] == []
    with db.cursor() as cur:
        cur.execute("SELECT ticker FROM universe_exclusion_snapshot WHERE snapshot_date='2026-10-01' ORDER BY 1")
        assert [r[0] for r in cur.fetchall()] == ["0004Y0", "0200G0", "0209J0"]


def _seed_199(db, monkeypatch):
    _seed_prev(db, ("0004Y0", "디비금융제14호스팩", "KOSDAQ", "주권", "spac"))
    with db.cursor() as cur:   # 기존 종목(security_group 확정, 폐지 이력) → 이번에 배제 축에 걸림 = #199 유형(UNRESOLVED 였으면 늦은 분류)
        cur.execute("INSERT INTO stocks (ticker, name, market, security_group) VALUES ('088980','맵스리얼티','KOSPI','주권') "
                    "ON CONFLICT (ticker) DO UPDATE SET security_group = '주권'")
    raw = _raw([("U221X0", "유이이일", "KOSPI"), ("0004Y0", "디비금융제14호스팩", "KOSDAQ"), ("088980", "맵스리얼티", "KOSPI")])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "_security_groups_fail_open",
                        lambda today, warnings: {"U221X0": "주권", "0004Y0": "주권", "088980": "부동산투자회사"})


def test_run_universe_unexplained_fails_and_persists_full_judgment(db, quiet_universe, monkeypatch):
    """잔여 → 실패. details 에 성공 행과 같은 키 모양의 판정 전체 + 잔여 티커의 원본 행 사본(롤백 대비) + 직전 스냅샷 날짜. 보고서는 여기서 보내지 않는다."""
    _seed_199(db, monkeypatch)
    with pytest.raises(UniverseGuardError, match="088980"):
        um.run_universe(db, today=date(2026, 10, 1))
    d = quiet_universe["state"]["details"]
    assert d["exclusion_unexplained"] == {"added": ["088980"], "removed": []} and d["report_key"] == ["+088980"]
    assert d["exclusion_unexplained_detail"]["088980"]["reason"].startswith("기존 활성")
    assert d["exclusion_raw_now"] == {"088980": {"name": "맵스리얼티", "market": "KOSPI", "security_group": "부동산투자회사"}}
    assert d["snapshot_prev_date"] == "2026-09-22" and d["exclusion_systemic"] == [] and d["strict"] is False
    import re
    assert d["raw_file"] and re.search(r"universe_raw_20261001_\d{6}\.json$", d["raw_file"])   # 운영 규칙 5: 시각 포함(같은 날 재실행이 덮지 않음)
    with db.cursor() as cur:                                                           # preflight 가 막았으므로 어떤 쓰기도 없음
        cur.execute("SELECT count(*) FROM universe_raw_snapshot WHERE snapshot_date='2026-10-01'")
        assert cur.fetchone()[0] == 0


def test_run_universe_strict_records_details_even_for_auto_types(db, quiet_universe, monkeypatch):
    _seed_prev(db, ("465320", "교보15호스팩", "KOSDAQ", "주권", "spac"))
    raw = _raw([("U221X0", "유이이일", "KOSPI")])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: {"U221X0": "주권"})
    with pytest.raises(UniverseGuardError, match="strict"):
        um.run_universe(db, today=date(2026, 10, 1), strict=True)
    d = quiet_universe["state"]["details"]
    assert d["exclusion_auto_accepted"]["removed_delisted"] == ["465320"] and d["strict"] is True


def test_run_universe_security_group_unavailable_marks_systemic(db, quiet_universe, monkeypatch):
    """security_group 5일 조회 실패(fail-open {}) → 축 풀림 잔여는 구조적 원인 → systemic 표시(보고서는 LLM 생략)."""
    _seed_prev(db, ("R1", "리츠", "KOSPI", "부동산투자회사", "security_group"))
    raw = _raw([("U221X0", "유이이일", "KOSPI"), ("R1", "리츠", "KOSPI")])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: warnings.append("security_group_fetch_failed") or {})
    with pytest.raises(UniverseGuardError, match="R1"):
        um.run_universe(db, today=date(2026, 10, 1))
    d = quiet_universe["state"]["details"]
    assert d["exclusion_unexplained"]["removed"] == ["R1"] and d["exclusion_systemic"] == [um.SYSTEMIC_SECURITY_GROUP_UNAVAILABLE]


def test_run_universe_accept_with_unexplained_records_warning(db, quiet_universe, monkeypatch):
    """accept 로 통과한(#199 아닌) 잔여 — 예: 배제 축이 풀린 종목 — 는 pipeline_runs warnings 에 남는다."""
    _seed_prev(db, ("0004Y0", "디비금융제14호스팩", "KOSDAQ", "주권", "spac"), ("R1", "리츠", "KOSPI", "부동산투자회사", "security_group"))
    raw = _raw([("U221X0", "유이이일", "KOSPI"), ("0004Y0", "디비금융제14호스팩", "KOSDAQ"), ("R1", "리츠", "KOSPI")])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: {"U221X0": "주권", "0004Y0": "주권", "R1": "주권"})   # 축 풀림
    info = um.run_universe(db, today=date(2026, 10, 1), accept_exclusion_diff=True)
    assert info["exclusion_unexplained"]["removed"] == ["R1"]
    assert any(w.startswith("exclusion_accepted_unexplained") for w in quiet_universe["state"]["warnings"])


def test_run_universe_accept_refuses_199_type(db, quiet_universe, monkeypatch):
    _seed_199(db, monkeypatch)
    with pytest.raises(UniverseGuardError, match="#199 유형"):
        um.run_universe(db, today=date(2026, 10, 1), accept_exclusion_diff=True)


def test_run_universe_rejects_accept_with_strict_before_any_fetch(db, quiet_universe, monkeypatch):
    monkeypatch.setattr(um, "fetch_universe", lambda d: (_ for _ in ()).throw(AssertionError("KRX 접촉 금지")))
    with pytest.raises(ValueError, match="동시 지정 불가"):
        um.run_universe(db, today=date(2026, 10, 1), accept_exclusion_diff=True, strict=True)


def test_run_universe_raw_shrink_fails_closed_before_any_write(db, quiet_universe, monkeypatch):
    """직전 원본 대비 시장별 MAX_DELIST_RATIO 넘게 줄면 부분 응답 의심 — upsert·mark_delisted·스냅샷 전부 전에 중단(리뷰 #223 4차)."""
    _seed_prev(db, ("S1", "스팩1", "KOSDAQ", "주권", "spac"))
    with db.cursor() as cur:   # 직전 원본 스냅샷: KOSDAQ 100 종목
        cur.execute("DELETE FROM universe_raw_snapshot WHERE snapshot_date='2026-09-22'")
        cur.executemany("INSERT INTO universe_raw_snapshot (snapshot_date, ticker, name, market, security_group) VALUES ('2026-09-22', %s, %s, 'KOSDAQ', '주권')",
                        [(f"Q{i:05d}", f"q{i}") for i in range(100)])
    raw = _raw([(f"Q{i:05d}", f"q{i}", "KOSDAQ") for i in range(90)])            # 10% 급감 > 2%
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "upsert_stocks", lambda conn, df: (_ for _ in ()).throw(AssertionError("쓰기 금지")))
    with pytest.raises(um.UniverseRawIncomplete, match="급감"):
        um.run_universe(db, today=date(2026, 10, 1))
    assert MAX_DELIST_RATIO == 0.02


def test_report_path_does_not_import_pykrx():
    """`--report-last-failed`(및 모듈 import 자체)는 KRX 접촉 0 — pykrx 가 import 되면 로그인 POST 가 나간다(리뷰 #223 3차)."""
    import os, subprocess, sys
    env = {**os.environ, "KRX_ID": "", "KRX_PW": ""}
    code = "import sys; import kr_pipeline.universe.__main__ as m; import kr_pipeline.universe.report; print('pykrx' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip() == "False"


def test_monthly_chain_reports_before_gate_and_sweeps_after():
    """(#221, 리뷰 #223 4차) 미전송 보고서는 attempt_allowed 게이트 **앞**(KRX 접촉 0·멱등), 대량 스윕은 게이트 **뒤**(#92 안전 계약).
    보고서 전용 스크립트를 쓰는 이유 = 모듈 호출 토큰이 게이트 앞에 놓이면 test_launchd_guards.test_wrapper_gates_before_sweep 가 깨진다."""
    from pathlib import Path
    text = (Path(__file__).parent.parent / "scripts" / "launchd" / "monthly_chain.sh").read_text()
    i_report, i_gate, i_sweep = (text.find("scripts/universe_exclusion_report.py"), text.find("attempt_allowed universe"),
                                 text.find("python -m kr_pipeline.universe"))
    assert -1 < i_report < i_gate < i_sweep
    assert "--report-last-failed" not in text                      # 게이트 앞 호출은 전용 스크립트만
