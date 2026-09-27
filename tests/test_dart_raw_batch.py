"""#186 B — 원본 보존 배치 러너(DART 호출 monkeypatch, 실접촉 0).
회신 ①: 상한 18,000/일·020 당일 중단 / ③: 1일차 파리티 276종목 선행·통과 게이트 / 규칙 5: 응답 파일 선보존."""
from datetime import date
import json

import pytest

from kr_pipeline.financials import raw_batch as B, raw_store as S, raw_labels as L
from kr_pipeline.financials.fetch import DartApiError

TODAY = date(2026, 10, 1)
_T = ["PL1", "PL2", "PL3", "PL4", "RN1", "RN2", "PA1", "PA2"]
_C = ["C-" + t for t in _T]


@pytest.fixture(autouse=True)
def _purge(test_db_url):
    """run() 은 셀별 commit → 시드가 kr_test 에 영속. 테스트 뒤 정리(별도 autocommit 연결)."""
    yield
    import psycopg
    with psycopg.connect(test_db_url, autocommit=True) as cn:
        cn.execute("DELETE FROM dart_fin_raw WHERE corp_code = ANY(%s)", (_C,))
        cn.execute("DELETE FROM dart_disclosure_raw WHERE corp_code = ANY(%s)", (_C,))
        cn.execute("DELETE FROM dart_batch_log WHERE batch_date BETWEEN '2026-10-01' AND '2026-10-31'")
        cn.execute("DELETE FROM dart_financials WHERE ticker = ANY(%s)", (_T,))
        cn.execute("DELETE FROM dart_corp_codes WHERE stock_code = ANY(%s)", (_T,))
        cn.execute("DELETE FROM delisted_daily_prices WHERE ticker = ANY(%s)", (_T,))
        cn.execute("DELETE FROM stocks WHERE ticker = ANY(%s)", (_T,))


def _seed_corp(db, ticker, corp, *, delisted=None, sg="주권", parity=False):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market, security_group, delisted_at) VALUES (%s, 'N', 'KOSPI', %s, %s) "
                    "ON CONFLICT (ticker) DO UPDATE SET delisted_at = EXCLUDED.delisted_at, security_group = EXCLUDED.security_group", (ticker, sg, delisted))
        if delisted is not None:   # 격리 집합 = delisted_daily_prices 보유 종목(스펙 435)
            cur.execute("INSERT INTO delisted_daily_prices (ticker, date, open, high, low, close, volume, value) VALUES (%s, %s, 1, 1, 1, 1, 1, 1) ON CONFLICT DO NOTHING", (ticker, delisted))
        cur.execute("INSERT INTO dart_corp_codes (stock_code, corp_code) VALUES (%s, %s) ON CONFLICT (stock_code) DO UPDATE SET corp_code = EXCLUDED.corp_code", (ticker, corp))
        if parity:
            cur.execute("INSERT INTO dart_financials (ticker, bsns_year, reprt_code, status, fs_div, revenue, operating_income, net_income, rcept_no) "
                        "VALUES (%s, 2024, '11011', 'ok', 'CFS', 1000, 100, 50, '20250311001085') ON CONFLICT DO NOTHING", (ticker,))


def _resp(rcept="20250311001085", rev="1,000"):
    return {"status": "000", "message": "정상", "list": [
        {"rcept_no": rcept, "fs_div": "CFS", "account_nm": "매출액", "thstrm_amount": rev, "thstrm_dt": "2024.01.01 ~ 2024.12.31"},
        {"rcept_no": rcept, "fs_div": "CFS", "account_nm": "영업이익", "thstrm_amount": "100"},
        {"rcept_no": rcept, "fs_div": "CFS", "account_nm": "당기순이익", "thstrm_amount": "50"}]}


def test_plan_targets_cells_and_parity_first(db):
    """대상 = 라이브 자격(허용 security_group·활성) + 격리(상폐) 종목의 corp_code, 셀 = 연도×4보고서 중 기간 말 ≤ today 이고
    미완료인 것. 파리티 종목(dart_financials 보유)이 먼저."""
    _seed_corp(db, "PL1", "C-PL1", parity=True); _seed_corp(db, "PL2", "C-PL2"); _seed_corp(db, "PL3", "C-PL3", delisted=date(2024, 5, 1))
    _seed_corp(db, "PL4", "C-PL4", sg="투자회사")                                 # 자격 제외 → 대상 아님
    S.upsert_fin_raw(db, dict(corp_code="C-PL2", bsns_year=2024, reprt_code="11011", ticker="PL2", status="000", rcept_no="20250311001085",
                              rcept_dt=date(2025, 3, 11), orig_rcept_dt=None, is_correction=None, no_data_reason=None, response=_resp(), batch_date=TODAY))
    plan = B.plan(db, years=(2024, 2026), today=TODAY, tickers=["PL1", "PL2", "PL3", "PL4"])
    assert [t for t, _ in plan.targets] == ["PL1", "PL2", "PL3"] and plan.parity_tickers == ["PL1"]
    cells = plan.cells
    assert cells[0][0] == "PL1"                                                   # 파리티 우선
    assert ("PL2", "C-PL2", 2024, "11011") not in cells                           # 완료 셀 제외
    assert all(not (y == 2026 and rc == "11011") for _, _, y, rc in cells)           # 2026 연간: 기간 말 12-31 > today → 호출 안 함
    assert ("PL2", "C-PL2", 2026, "11014") in cells                                   # 3Q26: 기간 말 09-30 ≤ today → 호출(기한 미도래면 013 라벨)
    assert ("PL3", "C-PL3", 2026, "11013") in cells                               # 상폐 종목도 호출(라벨은 013 응답 시)


def test_run_saves_file_before_db_stops_at_cap_and_labels_no_data(db, tmp_path, monkeypatch):
    TODAY = date(2026, 10, 2)
    _seed_corp(db, "RN1", "C-RN1")
    calls = {"n": 0}
    def fake_single(key, corp, year, rc):
        calls["n"] += 1
        return _resp() if (year, rc) == (2024, "11011") else {"status": "013", "message": "조회된 데이타가 없습니다."}
    fake_list = lambda key, corp, bgn, end: [{"rcept_no": "20250311001085", "rcept_dt": "20250311", "report_nm": "사업보고서 (2024.12)"}]
    monkeypatch.setattr(B, "fetch_single_account", fake_single); monkeypatch.setattr(B, "fetch_disclosures", fake_list)
    monkeypatch.setattr(B, "_SLEEP", 0)
    plan = B.plan(db, years=(2024, 2025), today=TODAY, tickers=["RN1"])
    st = B.run(db, plan, today=TODAY, cap=3, save_dir=tmp_path, api_key="k")          # list 1 + cells 2 = 3 → 상한 도달
    assert st["calls"] == 3 and st["stopped"] == "cap"
    lines = (tmp_path / f"{TODAY:%Y%m%d}.jsonl").read_text().splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["endpoint"] == "list"           # 파일 선보존(list + 셀 2)
    assert S.calls_today(db, TODAY) == (3, False)
    with db.cursor() as cur:
        cur.execute("SELECT bsns_year, reprt_code, status, no_data_reason, rcept_dt, orig_rcept_dt, is_correction FROM dart_fin_raw WHERE corp_code='C-RN1' ORDER BY 1, 2")
        rows = cur.fetchall()
    assert (2024, "11011", "000", None, date(2025, 3, 11), date(2025, 3, 11), False) in rows
    other = [r for r in rows if r[2] == "013"]
    assert len(other) == 1 and other[0][3] in L.LABELS and other[0][3] != L.UNEXPLAINED   # 2024 분기 미제출 → not_filed_or_exempt


def test_run_status_020_stops_day_and_marks(db, tmp_path, monkeypatch):
    TODAY = date(2026, 10, 3)
    _seed_corp(db, "RN2", "C-RN2")
    def boom(key, corp, year, rc):
        raise DartApiError("fnlttSinglAcnt", "020", "요청 제한을 초과하였습니다.")
    monkeypatch.setattr(B, "fetch_single_account", boom); monkeypatch.setattr(B, "fetch_disclosures", lambda *a: []); monkeypatch.setattr(B, "_SLEEP", 0)
    plan = B.plan(db, years=(2024, 2024), today=TODAY, tickers=["RN2"])
    st = B.run(db, plan, today=TODAY, cap=100, save_dir=tmp_path, api_key="k")
    assert st["stopped"] == "020" and S.calls_today(db, TODAY)[1] is True and S.remaining_today(db, TODAY, cap=100) == 0


def test_run_parity_gate_blocks_rest_until_pass(db, tmp_path, monkeypatch):
    """1일차: 파리티 종목 셀만 처리 → 전부 완료되면 파리티 판정 → 실패(미귀속 1건)면 잔여 종목 미착수·stopped='parity'."""
    TODAY = date(2026, 10, 4)
    _seed_corp(db, "PA1", "C-PA1", parity=True); _seed_corp(db, "PA2", "C-PA2")
    monkeypatch.setattr(B, "fetch_single_account", lambda k, c, y, rc: _resp(rev="1,001"))   # 저장값 1,000 vs 1,001 — 미귀속
    monkeypatch.setattr(B, "fetch_disclosures", lambda *a: [{"rcept_no": "20250311001085", "rcept_dt": "20250311", "report_nm": "사업보고서 (2024.12)"}])
    monkeypatch.setattr(B, "_SLEEP", 0)
    plan = B.plan(db, years=(2024, 2024), today=TODAY, tickers=["PA1", "PA2"])
    st = B.run(db, plan, today=TODAY, cap=1000, save_dir=tmp_path, api_key="k")
    assert st["stopped"] == "parity" and st["parity"]["passed"] is False and st["parity"]["unattributed"] == 1
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM dart_fin_raw WHERE corp_code='C-PA2'"); assert cur.fetchone()[0] == 0
