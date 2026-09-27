"""#186 B — no_data 라벨 결정(순수, 결정론). 회신(09-27) ②: '기타' 금지, 미설명 = unexplained 단일, 상호배타,
근거 = 첫 정기공시 접수일(상장일 대체)·상폐일·제출기한(사업보고서 90일·분/반기 45일)·공시 목록."""
from datetime import date

import pytest

from kr_pipeline.financials import raw_labels as L


def _f(**kw):
    """decide_no_data 인자 기본값."""
    base = dict(bsns_year=2020, reprt_code="11011", today=date(2026, 9, 27), first_filing_dt=date(2016, 3, 30),
                delisted_at=None, filings=[], fiscal_end=None)
    base.update(kw)
    return L.decide_no_data(**base)


def test_period_end_and_due_date_for_each_report_code():
    assert L.period_end(2020, "11011") == date(2020, 12, 31)
    assert L.period_end(2020, "11013") == date(2020, 3, 31)
    assert L.period_end(2020, "11012") == date(2020, 6, 30)
    assert L.period_end(2020, "11014") == date(2020, 9, 30)
    assert L.due_date(date(2020, 12, 31), "11011") == date(2021, 3, 31)     # +90일
    assert L.due_date(date(2020, 3, 31), "11013") == date(2020, 5, 15)      # +45일


def test_not_yet_due_when_deadline_in_future():
    assert _f(bsns_year=2026, reprt_code="11014", today=date(2026, 9, 27)) == L.NOT_YET_DUE   # 3Q26 기한 11-14


def test_after_delisting_when_period_end_past_delisting():
    assert _f(bsns_year=2022, reprt_code="11011", delisted_at=date(2022, 6, 1)) == L.AFTER_DELISTING


def test_before_first_filing_when_due_before_first_periodic_filing():
    assert _f(bsns_year=2014, reprt_code="11011", first_filing_dt=date(2016, 3, 30)) == L.BEFORE_FIRST_FILING


def test_filed_but_api_missing_when_matching_filing_exists():
    filings = [{"report_nm": "사업보고서 (2020.12)", "rcept_dt": date(2021, 3, 25)}]
    assert _f(bsns_year=2020, reprt_code="11011", filings=filings) == L.FILED_BUT_API_MISSING


def test_not_filed_when_due_passed_and_no_matching_filing_but_other_filings_exist():
    filings = [{"report_nm": "사업보고서 (2019.12)", "rcept_dt": date(2020, 3, 25)},
               {"report_nm": "사업보고서 (2021.12)", "rcept_dt": date(2022, 3, 25)}]
    assert _f(bsns_year=2020, reprt_code="11013", filings=filings) == L.NOT_FILED_OR_EXEMPT


def test_correction_only_filings_do_not_count_as_original():
    filings = [{"report_nm": "[기재정정]사업보고서 (2020.12)", "rcept_dt": date(2021, 5, 1)}]
    # 정정만 있고 원공시 없음 → 원공시 매칭 실패지만 '접수는 됨' → FILED_BUT_API_MISSING 이 아니라 원본 부재 → 접수 여부는 정정도 접수이므로 filed
    assert _f(bsns_year=2020, reprt_code="11011", filings=filings) == L.FILED_BUT_API_MISSING


def test_unexplained_when_no_rule_applies():
    assert _f(bsns_year=2020, reprt_code="11011", first_filing_dt=None, filings=[]) == L.UNEXPLAINED


def test_labels_are_mutually_exclusive_priority_order():
    """규칙 우선순위 고정: 기한 미도래 > 상폐 이후 > 첫 공시 이전 > 접수됨 > 미제출 > unexplained."""
    assert L.LABELS == (L.NOT_YET_DUE, L.AFTER_DELISTING, L.BEFORE_FIRST_FILING, L.FILED_BUT_API_MISSING, L.NOT_FILED_OR_EXEMPT, L.UNEXPLAINED)
    assert "etc" not in L.LABELS and "기타" not in L.LABELS
