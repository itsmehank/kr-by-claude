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


# ─── 회신 24 Q-I(B + 가드): 정기공시 이력 없음 → 첫 일봉으로 상장일 대체 ───────────

def _fb(**kw):
    base = dict(bsns_year=2020, reprt_code="11011", today=date(2026, 10, 6), first_filing_dt=None,
                delisted_at=None, filings=[], fiscal_end=None)
    base.update(kw)
    return L.decide_no_data_with_basis(**base)


def test_no_filings_uses_first_daily_bar_as_listing_proxy():
    """0010S0(첫 일봉 2026-09-23, 공시 목록 빈 응답) — 기한 < 첫 일봉이면 상장 전(BEFORE_FIRST_FILING), 근거 기록."""
    assert _fb(first_daily_bar=date(2026, 9, 23)) == (L.BEFORE_FIRST_FILING, L.BASIS_LISTING_PROXY_FIRST_DAILY_BAR)
    assert L.BASIS_LISTING_PROXY_FIRST_DAILY_BAR == "listing_proxy=first_daily_bar"


def test_no_filings_after_listing_due_passed_stays_unexplained():
    """상장(첫 일봉) 이후 기한이 지났는데 공시가 없으면 진짜 이상 신호 — UNEXPLAINED 유지."""
    assert _fb(bsns_year=2025, reprt_code="11011", first_daily_bar=date(2025, 1, 10)) == (L.UNEXPLAINED, None)


def test_first_daily_bar_at_collection_start_is_left_censored_no_proxy():
    """첫 일봉 = 수집 시작일(2016-06-13)이면 좌측 절단 가능 — 대체 금지(가드). 그 이전 날짜(격리 테이블 2015-06-15 시작)도 금지."""
    assert L.DATA_COLLECTION_START == date(2016, 6, 13)
    assert _fb(bsns_year=2015, first_daily_bar=date(2016, 6, 13)) == (L.UNEXPLAINED, None)
    assert _fb(bsns_year=2015, first_daily_bar=date(2015, 6, 15)) == (L.UNEXPLAINED, None)
    assert _fb(bsns_year=2015, first_daily_bar=date(2016, 6, 14))[0] == L.BEFORE_FIRST_FILING


def test_proxy_not_used_when_filings_exist_or_bar_unknown():
    """공시 이력이 있으면 기존 규칙(첫 정기공시일) 그대로, 첫 일봉 모르면 대체 없음 — 기존 라벨 불변."""
    assert _fb(first_daily_bar=None) == (L.UNEXPLAINED, None)
    assert _fb(first_filing_dt=date(2022, 3, 30), first_daily_bar=date(2026, 9, 23)) == (L.BEFORE_FIRST_FILING, None)   # 기존 규칙(첫 정기공시일) 경로 — 근거 없음
    assert _f(bsns_year=2020, reprt_code="11011", first_filing_dt=None, filings=[]) == L.UNEXPLAINED   # 구 시그니처 호환


# ---- (회신 2026-11-05, #186 네오뷰) 기간 부존재 · 자본시장법 제160조 제2항(2025-07-22 시행) ----

def _fx(**kw):
    base = dict(bsns_year=2026, reprt_code="11012", today=date(2026, 10, 8), first_filing_dt=None,
                delisted_at=None, filings=[], fiscal_end=None, first_daily_bar=date(2026, 7, 27))
    base.update(kw)
    return L.decide_no_data_with_basis(**base)


def test_prior_period_end_is_latest_quarter_end_strictly_before():
    assert L.prior_period_end(date(2026, 7, 27)) == date(2026, 6, 30)
    assert L.prior_period_end(date(2026, 6, 30)) == date(2026, 3, 31)     # 당일은 포함 안 함
    assert L.prior_period_end(date(2026, 1, 1)) == date(2025, 12, 31)
    assert L.prior_period_end(date(2025, 10, 15)) == date(2025, 9, 30)


def test_period_before_incorporation_is_before_first_filing_with_basis():
    """네오뷰: 인적분할 신설(분할기일 2026-07-01) — 2026 반기(06-30)는 법인이 없던 기간(제160조 1항 '사업연도 개시일부터')."""
    assert _fx(incorporated_at=date(2026, 7, 1)) == (L.BEFORE_FIRST_FILING, "incorporated_after_period_end=2026-07-01")
    # 설립이 기간 말보다 앞서면 이 근거는 쓰지 않는다 → ② 로 흐른다
    assert _fx(incorporated_at=date(2026, 5, 1)) == (L.NOT_FILED_OR_EXEMPT, "law_160_2_prior_report(D=2026-07-27)")


def test_incorporation_rule_yields_to_an_existing_matching_filing():
    """분할 신설법인이 그래도 직전 반기보고서를 냈다면(접수 사실) — 기간 부존재가 아니라 API 부재(리뷰 R1 ①)."""
    fil = [{"report_nm": "반기보고서 (2026.06)", "rcept_dt": date(2026, 8, 10)}]
    lab, _ = _fx(incorporated_at=date(2026, 7, 1), filings=fil, first_filing_dt=date(2026, 8, 10))
    assert lab == L.FILED_BUT_API_MISSING


def test_law_160_2_straddle_listing_right_after_quarter_end_with_no_filings_stays_unexplained():
    """D 대체(상장일)가 분기 말 직후면 진짜 D(납입기일 다음 날)는 분기 말 이전일 수 있어 그 기간은 정기 의무 —
    공시 이력이 전무하면 '면제'로 덮지 않고 unexplained 유지(리뷰 R1 ②, 통상 납입→상장 1~2주 → 14일 [design-judgment])."""
    assert _fx(first_daily_bar=date(2026, 7, 3)) == (L.UNEXPLAINED, None)
    assert _fx(first_daily_bar=date(2026, 7, 14)) == (L.UNEXPLAINED, None)
    assert _fx(first_daily_bar=date(2026, 7, 15)) == (L.NOT_FILED_OR_EXEMPT, "law_160_2_prior_report(D=2026-07-15)")
    # 공시 이력이 있으면(다른 정기공시) 걸치기 창이라도 ② 그대로
    fil = [{"report_nm": "분기보고서 (2026.09)", "rcept_dt": date(2026, 11, 14)}]
    assert _fx(first_daily_bar=date(2026, 7, 3), filings=fil, first_filing_dt=date(2026, 11, 14), today=date(2026, 11, 20)) == (L.NOT_FILED_OR_EXEMPT, "law_160_2_prior_report(D=2026-07-03)")


def test_law_160_2_prior_report_expected_for_listings_on_or_after_2025_07_22():
    """D(상장일 대체 = 첫 일봉) 2026-07-27 ≥ 시행일 → 직전 반기(06-30)는 제출 대상(갈음 가능). 공시 없음 → 미제출·면제 + 근거."""
    assert _fx() == (L.NOT_FILED_OR_EXEMPT, "law_160_2_prior_report(D=2026-07-27)")
    # 더 앞선 기간(1분기)은 종전대로 첫 일봉 대체 규칙
    assert _fx(reprt_code="11013") == (L.BEFORE_FIRST_FILING, L.BASIS_LISTING_PROXY_FIRST_DAILY_BAR)
    # 직전 보고서가 접수돼 있으면 API 부재
    fil = [{"report_nm": "반기보고서 (2026.06)", "rcept_dt": date(2026, 8, 1)}]
    assert _fx(filings=fil, first_filing_dt=date(2026, 8, 1)) == (L.FILED_BUT_API_MISSING, "law_160_2_prior_report(D=2026-07-27)")


def test_law_160_2_deadline_is_later_of_regular_due_and_D_plus_5():
    """금융위 사례 3: D 2025-08-20(기한 08-14 뒤) → 직전 반기 기한 D+5 = 08-25."""
    kw = dict(bsns_year=2025, first_daily_bar=date(2025, 8, 20))
    assert _fx(today=date(2025, 8, 22), **kw) == (L.NOT_YET_DUE, "law_160_2_prior_report(D=2025-08-20)")
    assert _fx(today=date(2025, 8, 26), **kw) == (L.NOT_FILED_OR_EXEMPT, "law_160_2_prior_report(D=2025-08-20)")


def test_law_160_2_not_applied_before_effective_date_or_with_old_listings():
    # D 2025-07-01 < 2025-07-22 → 종전 규칙(1Q25 기한 05-15 < D → 첫 일봉 대체)
    assert _fx(bsns_year=2025, reprt_code="11013", first_daily_bar=date(2025, 7, 1)) == (L.BEFORE_FIRST_FILING, L.BASIS_LISTING_PROXY_FIRST_DAILY_BAR)
    # 수집 시작일 첫 일봉(좌측 절단) + 옛 첫 정기공시 → D 는 첫 정기공시일(2016) → 미적용, 기존 라벨 불변
    assert _fx(bsns_year=2016, reprt_code="11013", first_daily_bar=date(2016, 6, 13), first_filing_dt=date(2016, 8, 16)) == (L.BEFORE_FIRST_FILING, None)


def test_law_160_2_D_is_earliest_of_listing_proxy_and_first_filing():
    """공모 납입 뒤 상장 전 정기공시가 먼저 있으면 그 접수일이 D 보다 앞설 수 있다 — 둘 중 이른 날."""
    fil = [{"report_nm": "분기보고서 (2026.03)", "rcept_dt": date(2026, 5, 10)}]
    # D = 2026-05-10(첫 공시) → 직전 = 1분기(03-31) → 제출됨 → API 부재; 반기(06-30)는 D 이후 끝나는 기간 → 정기 규칙(기한 08-14 < today, 공시 있음 → 미제출·면제, 근거 없음)
    assert _fx(reprt_code="11013", filings=fil, first_filing_dt=date(2026, 5, 10), first_daily_bar=date(2026, 7, 27)) == (L.FILED_BUT_API_MISSING, "law_160_2_prior_report(D=2026-05-10)")
    assert _fx(reprt_code="11012", filings=fil, first_filing_dt=date(2026, 5, 10), first_daily_bar=date(2026, 7, 27)) == (L.NOT_FILED_OR_EXEMPT, None)
