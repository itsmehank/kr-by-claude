"""#221 — universe 실행 경로(run_universe) 통합: KRX 전부 monkeypatch, 10-01 변동 재현(자동 수용) + 잔여(실패 run details 보존)."""
from contextlib import contextmanager
from datetime import date
import glob
import json
import os

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
    i_report, i_lock, i_gate, i_sweep = (text.find("scripts/universe_exclusion_report.py"), text.find("acquire_lock data"),
                                         text.find("attempt_allowed universe"), text.find("python -m kr_pipeline.universe"))
    assert -1 < i_report < i_lock < i_gate < i_sweep          # 사전 보고서는 data 락 획득 전(리뷰 #223 5차)
    assert "--report-last-failed" not in text                      # 게이트 앞 호출은 전용 스크립트만


# ---------- #204 업종 조회 기준일 = DB 최신 일봉 날짜(비거래 시점 '오늘' 조회 → 빈 응답 재발 방지) ----------

def _seed_daily(db, ticker, *days):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, 'x', 'KOSPI') ON CONFLICT (ticker) DO NOTHING", (ticker,))
        for d in days:
            cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) "
                        "VALUES (%s, %s, 1, 1, 1, 1, 1, 1, 1)", (ticker, d))


def test_as_of_trading_day_is_latest_daily_bar_not_after_today(db):
    # kr_test 의 다른 일봉과 겹치지 않는 1990 창으로 격리(DELETE 금지 — 전표 행 잠금·교차 세션 경합, 리뷰 3차)
    _seed_daily(db, "204T00", date(1990, 1, 2), date(1990, 1, 3), date(1990, 1, 5))
    assert um._as_of_trading_day(db, date(1990, 1, 4)) == date(1990, 1, 3)   # 매월 1일 06:30 — 전일 종가 기준
    assert um._as_of_trading_day(db, date(1990, 1, 5)) == date(1990, 1, 5)   # 당일 일봉이 이미 있으면 당일


def test_as_of_trading_day_is_none_without_daily_bars(db):
    assert um._as_of_trading_day(db, date(1989, 1, 1)) is None   # 그 날짜 이하 일봉 없음 — 폴백(today)·경고는 호출부(리뷰 4차)


def test_run_universe_warns_when_attribute_as_of_falls_back_to_today(db, quiet_universe, monkeypatch):
    raw = _raw([("U221X0", "유이이일", "KOSPI")])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: {"U221X0": "주권"})
    monkeypatch.setattr(um, "_as_of_trading_day", lambda conn, today: None)
    asked = []
    monkeypatch.setattr(um, "fetch_sectors", lambda d, m: asked.append(d) or pd.DataFrame(columns=["ticker", "sector"]))

    um.run_universe(db, today=date(2026, 10, 1))

    assert asked == [date(2026, 10, 1), date(2026, 10, 1)]
    assert any(w.startswith("attribute_as_of_fallback: 2026-10-01") for w in quiet_universe["state"]["warnings"])


def test_run_universe_fetches_sectors_as_of_latest_bar(db, quiet_universe, monkeypatch):
    raw = _raw([("U221X0", "유이이일", "KOSPI")])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    sg_from = []
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: sg_from.append(today) or {"U221X0": "주권"})
    monkeypatch.setattr(um, "_as_of_trading_day", lambda conn, today: date(2026, 9, 30))
    asked = []
    monkeypatch.setattr(um, "fetch_sectors", lambda d, m: asked.append((d, m)) or pd.DataFrame(columns=["ticker", "sector"]))

    um.run_universe(db, today=date(2026, 10, 1))

    assert asked == [(date(2026, 9, 30), "KOSPI"), (date(2026, 9, 30), "KOSDAQ")]
    assert sg_from == [date(2026, 9, 30)]   # 증권구분 걸어내리기도 같은 기준일에서 시작(리뷰 2차: '오늘' 비거래 시점 3회 재시도 낭비 제거)
    # 증거 파일(운영 규칙 5)에 업종 기준일 기록 — fetched_for(today) 와 다르므로 감사 시 재구성 가능해야 한다(리뷰 1차)
    files = sorted(glob.glob(os.path.join(os.environ["KR_VERIFICATION_DIR"], "universe_raw_20261001_*.json")))
    assert files, "universe_raw 증거 파일이 저장되지 않았다"
    with open(files[-1], encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["fetched_for"] == "2026-10-01" and doc["attribute_as_of"] == "2026-09-30"


def test_run_universe_warns_when_kept_tickers_lack_sector(db, quiet_universe, monkeypatch):
    """기준일(최신 일봉) 이후 상장된 종목은 업종 응답에 없어 NULL 로 적재된다 — 조용히 넘기지 않고 run warning 으로 수를 남긴다(리뷰 1차)."""
    raw = _raw([("U221X0", "유이이일", "KOSPI"), ("U221Y0", "유이이이", "KOSPI"), ("U221Z0", "유이이삼", "KOSDAQ")])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: {"U221X0": "주권", "U221Y0": "주권", "U221Z0": "주권"})
    monkeypatch.setattr(um, "_as_of_trading_day", lambda conn, today: date(2026, 9, 30))

    def _sectors(d, m):
        if m == "KOSDAQ":
            raise ValueError("empty sector response for KOSDAQ")   # 한 시장 실패 — 그 시장 전 종목을 '누락' 으로 세면 오귀속(리뷰 2차)
        return pd.DataFrame([("U221X0", "서비스업")], columns=["ticker", "sector"])

    monkeypatch.setattr(um, "fetch_sectors", _sectors)

    um.run_universe(db, today=date(2026, 10, 1))

    w = quiet_universe["state"]["warnings"]
    assert "sector_missing: 1종목 (as_of=2026-09-30) U221Y0" in w          # 응답이 온 KOSPI 안에서만 센다
    assert any(x.startswith("sector_fetch_failed: KOSDAQ (as_of=2026-09-30)") for x in w)   # 실패는 로그만이 아니라 run warning
    with db.cursor() as cur:
        cur.execute("SELECT ticker, sector FROM stocks WHERE ticker IN ('U221X0','U221Y0','U221Z0') ORDER BY 1")
        assert cur.fetchall() == [("U221X0", "서비스업"), ("U221Y0", None), ("U221Z0", None)]


def test_run_universe_records_attribute_as_of_even_when_all_sector_fetches_fail(db, quiet_universe, monkeypatch):
    raw = _raw([("U221X0", "유이이일", "KOSPI")])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: {"U221X0": "주권"})
    monkeypatch.setattr(um, "_as_of_trading_day", lambda conn, today: date(2026, 9, 30))
    monkeypatch.setattr(um, "fetch_sectors", lambda d, m: (_ for _ in ()).throw(ValueError("empty")))

    um.run_universe(db, today=date(2026, 10, 1))

    files = sorted(glob.glob(os.path.join(os.environ["KR_VERIFICATION_DIR"], "universe_raw_20261001_*.json")))
    with open(files[-1], encoding="utf-8") as f:
        doc = json.load(f)
    assert doc["attribute_as_of"] == "2026-09-30" and "sectors" not in doc   # 증거 파일만으로 '어느 날짜를 물었는지' 재구성 가능(운영 규칙 5)


def test_latest_daily_bar_date_helper(db):
    from kr_pipeline.common.daily_bars import latest_daily_bar_date
    assert latest_daily_bar_date(db, upto=date(1989, 1, 1)) is None
    _seed_daily(db, "204T01", date(1990, 1, 2), date(1990, 1, 5))
    assert latest_daily_bar_date(db, upto=date(1990, 1, 5)) == date(1990, 1, 5)
    assert latest_daily_bar_date(db, upto=date(1990, 1, 4)) == date(1990, 1, 2)
    assert latest_daily_bar_date(db) >= date(1990, 1, 5)   # upto 없음 = 전표 최신(다른 일봉이 있을 수 있어 하한만)


def test_run_universe_fails_closed_on_unresolved_name_after_saving_raw(db, quiet_universe, monkeypatch):
    """종목명 미해결(name None) → 어떤 쓰기보다 앞에서 실패하되, 받은 응답은 먼저 파일로 보존(운영 규칙 5, 리뷰 3차)."""
    raw = pd.DataFrame([("U221X0", "유이이일", "KOSPI"), ("U221N0", None, "KOSPI")], columns=["ticker", "name", "market"])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: (_ for _ in ()).throw(AssertionError("미해결이면 여기 오면 안 됨")))

    with pytest.raises(ValueError, match="U221N0"):
        um.run_universe(db, today=date(2026, 10, 1))

    files = sorted(glob.glob(os.path.join(os.environ["KR_VERIFICATION_DIR"], "universe_raw_20261001_*.json")))
    with open(files[-1], encoding="utf-8") as f:
        doc = json.load(f)
    assert {r["ticker"]: r["name"] for r in doc["universe"]} == {"U221X0": "유이이일", "U221N0": None}
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM stocks WHERE ticker IN ('U221X0','U221N0') AND delisted_at IS NULL")
        assert cur.fetchone()[0] == 0


def test_run_universe_keeps_existing_name_for_active_ticker_when_unresolved(db, quiet_universe, monkeypatch):
    """이미 **활성** stocks 에 있는 종목의 이름이 이번 응답에서 결측이면 기존 이름 유지 + 경고 — 신규 종목만 fail-closed(리뷰 4차, sector COALESCE 와 같은 깊이)."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market, security_group) VALUES ('U221K0','기존이름','KOSPI','주권')")
    raw = pd.DataFrame([("U221X0", "유이이일", "KOSPI"), ("U221K0", None, "KOSPI")], columns=["ticker", "name", "market"])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: {"U221X0": "주권", "U221K0": "주권"})

    um.run_universe(db, today=date(2026, 10, 1))

    assert "name_unresolved_kept: 1종목 U221K0" in quiet_universe["state"]["warnings"]
    with db.cursor() as cur:
        cur.execute("SELECT name, delisted_at FROM stocks WHERE ticker='U221K0'")
        assert cur.fetchone() == ("기존이름", None)


def test_run_universe_does_not_revive_delisted_name_for_unresolved_ticker(db, quiet_universe, monkeypatch):
    """상폐 이력만 있는 코드(재사용 가능)는 '아는 종목' 이 아니다 — 옛 회사 이름으로 부활시키지 않고 신규처럼 fail-closed(리뷰 5차)."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market, security_group, delisted_at) VALUES ('U221R0','옛회사','KOSPI','주권','2024-01-05')")
    raw = pd.DataFrame([("U221X0", "유이이일", "KOSPI"), ("U221R0", None, "KOSPI")], columns=["ticker", "name", "market"])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())

    with pytest.raises(ValueError, match="U221R0"):
        um.run_universe(db, today=date(2026, 10, 1))
    with db.cursor() as cur:
        cur.execute("SELECT name, delisted_at FROM stocks WHERE ticker='U221R0'")
        assert cur.fetchone() == ("옛회사", date(2024, 1, 5))


def test_run_universe_warns_names_taken_from_delisted_table(db, quiet_universe, monkeypatch):
    raw = pd.DataFrame([("U221X0", "유이이일", "KOSPI", "listed"), ("U221D0", "옛회사", "KOSPI", "delisted")],
                       columns=["ticker", "name", "market", "name_source"])
    monkeypatch.setattr(um, "fetch_universe", lambda d: raw.copy())
    monkeypatch.setattr(um, "_security_groups_fail_open", lambda today, warnings: {"U221X0": "주권", "U221D0": "주권"})

    um.run_universe(db, today=date(2026, 10, 1))

    assert "name_from_delisted: 1종목 U221D0" in quiet_universe["state"]["warnings"]


def test_security_groups_fail_open_records_walk_back_date(monkeypatch):
    """증권구분 응답을 준 날짜가 시작일과 다르면 run warning 으로 남긴다 — 증거 파일의 attribute_as_of 만으론 재구성 불가(리뷰 3차)."""
    def _groups(d):
        if d == date(2026, 10, 30):
            raise ValueError("suspiciously small")
        return {"U221X0": "주권"}

    monkeypatch.setattr(um, "fetch_security_groups", _groups)
    warnings = []

    assert um._security_groups_fail_open(date(2026, 10, 30), warnings) == {"U221X0": "주권"}
    assert warnings == ["security_group_as_of: 2026-10-29 (start 2026-10-30, 1 failed, 0 skipped weekend)"]

    warnings = []
    assert um._security_groups_fail_open(date(2026, 10, 29), warnings) == {"U221X0": "주권"}
    assert warnings == []   # 시작일에 바로 응답 → 기록 없음(= attribute_as_of)

    warnings = []   # 폴백(as_of=today) 경로에서 시작일이 주말이면 '실패 0' 이 아니라 '건너뜀' 으로 읽혀야 한다(리뷰 5차)
    assert um._security_groups_fail_open(date(2026, 11, 1), warnings) == {"U221X0": "주권"}   # 11-01 일요일 → 10-31 토 건너뜀 → 10-30 실패 → 10-29
    assert warnings == ["security_group_as_of: 2026-10-29 (start 2026-11-01, 1 failed, 2 skipped weekend)"]
