# tests/test_financials_ingest.py
# (#68 2단계) DART 실적 적재 — 정규화 파싱·저장·as-of 조회 (look-ahead 방지 핵심).
# 준거: docs/superpowers/specs/2026-07-22-issue68-stage2-ingest.md
from datetime import date

import pytest


def test_dart_financials_table_exists(db):
    with db.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='dart_financials'")
        have = {r[0] for r in cur.fetchall()}
    need = {"ticker", "bsns_year", "reprt_code", "status", "fiscal_end",
            "net_income", "shares_outstanding", "eps_derived", "disclosed_at"}
    assert not (need - have), f"누락: {need - have} — schema.sql 미적용?"


def test_normalize_accounts_cfs_first_and_alias():
    """계정 정규화: CFS 우선, '당기순이익(손실)' 별칭 매칭, 동명 중복 첫 행 (스펙 §3)."""
    from kr_pipeline.financials.parse import normalize_accounts
    rows = [
        {"fs_div": "OFS", "account_nm": "매출액", "thstrm_amount": "1,000"},
        {"fs_div": "CFS", "account_nm": "매출액", "thstrm_amount": "2,000"},
        {"fs_div": "CFS", "account_nm": "영업이익", "thstrm_amount": "300"},
        {"fs_div": "CFS", "account_nm": "당기순이익(손실)", "thstrm_amount": "200"},
        {"fs_div": "CFS", "account_nm": "당기순이익(손실)", "thstrm_amount": "150"},  # 지배주주 중복
        {"fs_div": "CFS", "account_nm": "법인세차감전 순이익", "thstrm_amount": "250"},
    ]
    out = normalize_accounts(rows)
    assert out["fs_div"] == "CFS"
    assert out["revenue"] == 2000 and out["operating_income"] == 300
    assert out["net_income"] == 200, "동명 중복은 첫 행"


def test_normalize_accounts_ofs_fallback_and_negative():
    """CFS 부재 시 OFS 폴백 + 음수 표기('-1,234') 파싱."""
    from kr_pipeline.financials.parse import normalize_accounts
    rows = [
        {"fs_div": "OFS", "account_nm": "매출액", "thstrm_amount": "500"},
        {"fs_div": "OFS", "account_nm": "당기순이익", "thstrm_amount": "-1,234"},
    ]
    out = normalize_accounts(rows)
    assert out["fs_div"] == "OFS" and out["net_income"] == -1234
    assert out["operating_income"] is None


def test_parse_thstrm_period():
    """thstrm_dt 회계기간 파싱 — 비12월 결산 대응 (1단계 발견 B)."""
    from kr_pipeline.financials.parse import parse_thstrm
    assert parse_thstrm("2023.01.01 ~ 2023.12.31") == (date(2023, 1, 1), date(2023, 12, 31))
    assert parse_thstrm("2023.12.31 현재") == (None, date(2023, 12, 31))
    assert parse_thstrm(None) == (None, None)
    assert parse_thstrm("garbage") == (None, None)


def test_match_disclosure_original_only():
    """원공시 매칭: 정정 prefix 제외 + 보고서명 기간 토큰 매핑 (1단계 발견 A)."""
    from kr_pipeline.financials.parse import match_disclosure
    items = [
        {"report_nm": "[기재정정]사업보고서 (2023.12)", "rcept_dt": "20240610"},
        {"report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240320"},
        {"report_nm": "분기보고서 (2023.03)", "rcept_dt": "20230515"},
        {"report_nm": "반기보고서 (2023.06)", "rcept_dt": "20230814"},
    ]
    assert match_disclosure(items, 2023, "11011", fiscal_end=date(2023, 12, 31)) == date(2024, 3, 20)
    assert match_disclosure(items, 2023, "11013", fiscal_end=date(2023, 3, 31)) == date(2023, 5, 15)
    assert match_disclosure(items, 2023, "11012", fiscal_end=date(2023, 6, 30)) == date(2023, 8, 14)
    assert match_disclosure(items, 2023, "11014", fiscal_end=date(2023, 9, 30)) is None


def _cleanup(db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM dart_financials WHERE ticker LIKE 'FINT%'")
    db.commit()


def test_upsert_and_asof_lookahead_guard(db):
    """as-of 유틸: disclosed_at <= as_of 만 반환, NULL disclosed_at 제외 (스펙 §5)."""
    from kr_pipeline.financials.store import upsert_financial, get_financials_asof
    _cleanup(db)
    base = {"ticker": "FINT1", "status": "ok", "fs_div": "CFS",
            "revenue": 100, "operating_income": 10, "net_income": 5,
            "shares_outstanding": 100, "eps_derived": 0.05, "rcept_no": "20240320000001"}
    upsert_financial(db, {**base, "bsns_year": 2023, "reprt_code": "11011",
                          "fiscal_start": date(2023, 1, 1), "fiscal_end": date(2023, 12, 31),
                          "disclosed_at": date(2024, 3, 20)})
    upsert_financial(db, {**base, "bsns_year": 2024, "reprt_code": "11013",
                          "fiscal_start": date(2024, 1, 1), "fiscal_end": date(2024, 3, 31),
                          "disclosed_at": date(2024, 5, 14)})
    upsert_financial(db, {**base, "bsns_year": 2024, "reprt_code": "11012",
                          "fiscal_start": date(2024, 1, 1), "fiscal_end": date(2024, 6, 30),
                          "disclosed_at": None})  # 원공시 매칭 실패 — as-of 제외 대상
    db.commit()
    try:
        rows = get_financials_asof(db, "FINT1", as_of=date(2024, 6, 1))
        ends = [r["fiscal_end"] for r in rows]
        assert ends == [date(2024, 3, 31), date(2023, 12, 31)], \
            f"look-ahead/정렬 오류: {ends}"
        # 공시 전 시점 — Q1(5/14 공시)은 안 보여야 함
        rows2 = get_financials_asof(db, "FINT1", as_of=date(2024, 5, 13))
        assert [r["fiscal_end"] for r in rows2] == [date(2023, 12, 31)]
        # 경계: 공시 **당일**도 미노출 (strict < — T+1 가용 규약, 리뷰 반영)
        rows2b = get_financials_asof(db, "FINT1", as_of=date(2024, 5, 14))
        assert [r["fiscal_end"] for r in rows2b] == [date(2023, 12, 31)], \
            "공시 당일 노출 — same-day look-ahead"
        # disclosed_at NULL(반기)은 어떤 as_of 에서도 미노출
        rows3 = get_financials_asof(db, "FINT1", as_of=date(2026, 1, 1))
        assert date(2024, 6, 30) not in [r["fiscal_end"] for r in rows3]
    finally:
        _cleanup(db)


def test_upsert_idempotent_update(db):
    """같은 PK 재적재 시 갱신(멱등 재개) — 중복 행 없이 최신값."""
    from kr_pipeline.financials.store import upsert_financial
    _cleanup(db)
    rec = {"ticker": "FINT2", "bsns_year": 2023, "reprt_code": "11011",
           "status": "no_data", "fs_div": None, "fiscal_start": None,
           "fiscal_end": None, "revenue": None, "operating_income": None,
           "net_income": None, "shares_outstanding": None, "eps_derived": None,
           "rcept_no": None, "disclosed_at": None}
    upsert_financial(db, rec)
    upsert_financial(db, {**rec, "status": "ok", "revenue": 777})
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*), MAX(status), MAX(revenue) FROM dart_financials "
                        "WHERE ticker='FINT2'")
            n, st, rev = cur.fetchone()
        assert (n, st, float(rev)) == (1, "ok", 777.0)
    finally:
        _cleanup(db)
