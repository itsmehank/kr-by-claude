"""#186 B — 원본 보존 저장(dart_fin_raw·dart_disclosure_raw)·일별 호출 계정(dart_batch_log). 멱등 재개."""
from datetime import date

from kr_pipeline.financials import raw_store as S

RESP = {"status": "000", "message": "정상", "list": [{"rcept_no": "20250311001085", "fs_div": "CFS", "account_nm": "매출액", "thstrm_amount": "1,000"}]}


def test_upsert_fin_raw_round_trip_and_idempotent(db):
    rec = dict(corp_code="C1", bsns_year=2024, reprt_code="11011", ticker="005930", status="000", rcept_no="20250311001085",
               rcept_dt=date(2025, 3, 11), orig_rcept_dt=date(2025, 3, 11), is_correction=False, no_data_reason=None,
               response=RESP, batch_date=date(2026, 10, 1))
    S.upsert_fin_raw(db, rec)
    S.upsert_fin_raw(db, {**rec, "batch_date": date(2026, 10, 2)})   # 재적재 = 갱신(중복 없음)
    with db.cursor() as cur:
        cur.execute("SELECT count(*), max(batch_date), (array_agg(response))[1]->'list'->0->>'account_nm' FROM dart_fin_raw WHERE corp_code='C1'")
        n, bd, acct = cur.fetchone()
    assert (n, bd, acct) == (1, date(2026, 10, 2), "매출액")


def test_no_data_cell_requires_reason(db):
    import pytest
    rec = dict(corp_code="C2", bsns_year=2014, reprt_code="11011", ticker="X", status="013", rcept_no=None, rcept_dt=None,
               orig_rcept_dt=None, is_correction=None, no_data_reason=None, response={"status": "013"}, batch_date=date(2026, 10, 1))
    with pytest.raises(ValueError, match="no_data_reason"):
        S.upsert_fin_raw(db, rec)


def test_disclosures_upsert_and_load(db):
    items = [{"rcept_no": "20210325000111", "rcept_dt": "20210325", "report_nm": "사업보고서 (2020.12)", "corp_cls": "Y"},
             {"rcept_no": "20210501000222", "rcept_dt": "20210501", "report_nm": "[기재정정]사업보고서 (2020.12)"}]
    assert S.upsert_disclosures(db, "C3", items, batch_date=date(2026, 10, 1)) == 2
    assert S.upsert_disclosures(db, "C3", items, batch_date=date(2026, 10, 1)) == 0    # 멱등
    got = S.load_disclosures(db, "C3")
    assert [(g["rcept_no"], g["rcept_dt"]) for g in got] == [("20210325000111", date(2021, 3, 25)), ("20210501000222", date(2021, 5, 1))]
    assert S.first_filing_dt(db, "C3") == date(2021, 3, 25)


def test_done_cells_for_resume(db):
    for y in (2023, 2024):
        S.upsert_fin_raw(db, dict(corp_code="C4", bsns_year=y, reprt_code="11011", ticker="X", status="000", rcept_no="2025031100108%d" % (y % 10),
                                  rcept_dt=date(2025, 3, 11), orig_rcept_dt=None, is_correction=None, no_data_reason=None, response=RESP, batch_date=date(2026, 10, 1)))
    assert S.done_cells(db, ["C4", "C9"]) == {("C4", 2023, "11011"), ("C4", 2024, "11011")}


def test_batch_log_accounting_and_cap(db):
    d = date(2031, 5, 5)
    assert S.calls_today(db, d) == (0, False)
    S.add_calls(db, d, 17_990, cap=18_000)
    assert S.calls_today(db, d) == (17_990, False)
    assert S.remaining_today(db, d, cap=18_000) == 10
    S.mark_stopped_020(db, d, cap=18_000)
    assert S.calls_today(db, d) == (17_990, True) and S.remaining_today(db, d, cap=18_000) == 0
