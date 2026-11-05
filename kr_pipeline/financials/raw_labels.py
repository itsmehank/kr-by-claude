"""#186 B — no_data(status 013) 사유 라벨, 결정론·상호배타 (2026-09-27 전문가 회신 ②, design-judgment / governance 4).

근거만 사용: 제출기한(자본시장법 — 사업보고서 사업연도 경과 후 90일, 분·반기보고서 45일), 상폐일(stocks.delisted_at),
첫 정기공시 접수일(상장일 대체 — stocks.listed_at 전무), 공시 목록(dart_disclosure_raw, pblntf_ty=A).
'기타' 없음: 어느 규칙에도 안 걸리면 UNEXPLAINED 단일 라벨이며 ≠0 이면 배치 미완료. 라벨 무관 하류는 NULL 동일 취급.
우선순위(먼저 걸리는 규칙이 라벨): NOT_YET_DUE → AFTER_DELISTING → BEFORE_FIRST_FILING → FILED_BUT_API_MISSING
→ NOT_FILED_OR_EXEMPT → UNEXPLAINED. (해당 시) 업종 제외 라벨은 이번 범위에 대상 없음(전 유니버스 적재).
"""
from __future__ import annotations

import re
from datetime import date, timedelta

NOT_YET_DUE = "not_yet_due"                      # 제출기한 미도래
AFTER_DELISTING = "after_delisting"              # 상폐 이후 기간
BEFORE_FIRST_FILING = "before_first_filing"      # 첫 정기공시 이전(상장 이전 대체)
FILED_BUT_API_MISSING = "filed_but_api_missing"  # 접수됐으나 API 부재
NOT_FILED_OR_EXEMPT = "not_filed_or_exempt"      # 미제출·면제
UNEXPLAINED = "unexplained"
# (회신 24 Q-I, 2026-10-06) 정기공시 이력이 전혀 없는 종목(신규 상장 — 0010S0 사례)은 첫 정기공시일로 상장일을 대체할 수 없다.
# 그때만 첫 일봉(daily_prices ∪ delisted_daily_prices MIN(date))으로 대체하고, 그 라벨 행에 근거를 기록한다.
# 가드: 첫 일봉 > DATA_COLLECTION_START 일 때만 — 첫 일봉이 수집 시작일(이하)이면 그 전부터 상장했을 수 있어(좌측 절단) 대체 금지.
DATA_COLLECTION_START = date(2016, 6, 13)        # MIN(daily_prices.date) 실측(격리 테이블은 2015-06-15 시작 — 그 이전 날짜도 대체 금지)
BASIS_LISTING_PROXY_FIRST_DAILY_BAR = "listing_proxy=first_daily_bar"
# (회신 2026-11-05, #186 네오뷰 0218L0 — 라벨 집합 불변, 근거(basis)만 추가)
# ① 기간 부존재: 제160조 제1항 "사업연도 개시일부터 6개월간" — 법인 설립(분할기일 포함) 전에 끝난 기간은 대상 아님.
#    설립일 = dart_corp_codes.est_dt(DART company.json, 명시 채움). 네오뷰 = 토비스 인적분할 신설(분할기일 2026-07-01).
# ② 제160조 제2항(2025-01-21 신설, 2025-07-22 시행 — 금융위 보도자료): 최초 사업보고서 제출대상법인이 된 날(D)부터 5일
#    (정기 제출기간 중이면 그 기한) 안에 "직전" 반기·분기보고서 1개를 제출. 단서: 증권신고서 등으로 준하는 사항을 공시했으면
#    제출하지 않을 수 있음(갈음) → 미제출은 NOT_FILED_OR_EXEMPT 로 두고 근거에 D 를 남긴다. D 의 대체 = 첫 일봉(상장일)과
#    첫 정기공시 접수일 중 이른 날(공모 납입기일 다음 날은 미보유). 5일은 역일로 계산(금융위 사례 1·3 — 영업일 여부 미확인).
LAW_160_2_EFFECTIVE = date(2025, 7, 22)
LAW_160_2_GRACE_DAYS = 5
BASIS_INCORPORATED_AFTER_PERIOD = "incorporated_after_period_end"
BASIS_LAW_160_2_PRIOR_REPORT = "law_160_2_prior_report"
LABELS = (NOT_YET_DUE, AFTER_DELISTING, BEFORE_FIRST_FILING, FILED_BUT_API_MISSING, NOT_FILED_OR_EXEMPT, UNEXPLAINED)

_PERIOD_END_MONTH = {"11013": 3, "11012": 6, "11014": 9, "11011": 12}
_DUE_DAYS = {"11011": 90, "11013": 45, "11012": 45, "11014": 45}
_REPRT_NAME = {"11011": "사업보고서", "11013": "분기보고서", "11012": "반기보고서", "11014": "분기보고서"}


def _month_end(y: int, m: int) -> date:
    return (date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1))


def period_end(bsns_year: int, reprt_code: str) -> date:
    """12월 결산 가정의 보고 기간 말(비12월 결산은 응답 thstrm_dt 가 있을 때 fiscal_end 인자로 대체)."""
    return _month_end(bsns_year, _PERIOD_END_MONTH[reprt_code])


def due_date(p_end: date, reprt_code: str) -> date:
    return p_end + timedelta(days=_DUE_DAYS[reprt_code])


def _matches_report(report_nm: str, reprt_code: str, p_end: date) -> bool:
    name = _REPRT_NAME[reprt_code]
    body = re.sub(r"^\s*\[[^\]]*\]\s*", "", report_nm or "").strip()   # [기재정정] 등 prefix 제거 후 비교(접수 사실은 인정)
    return body.startswith(name) and f"({p_end.year}.{p_end.month:02d})" in body


def prior_period_end(d: date) -> date:
    """d 직전(당일 제외)에 끝난 분기 말 — 제160조 제2항의 '직전 반기보고서 또는 분기보고서' 대상 기간."""
    x = d - timedelta(days=1)
    for y in (x.year, x.year - 1):
        for m in (12, 9, 6, 3):
            e = _month_end(y, m)
            if e <= x:
                return e
    raise AssertionError("unreachable")


def _subject_date(first_filing_dt: date | None, first_daily_bar: date | None) -> date | None:
    """D(사업보고서 제출대상법인이 된 날)의 대체 — 첫 일봉(좌측 절단 아닌 경우)과 첫 정기공시 접수일 중 이른 날."""
    cands = [d for d in (first_filing_dt,) if d is not None]
    if first_daily_bar is not None and first_daily_bar > DATA_COLLECTION_START:
        cands.append(first_daily_bar)
    return min(cands) if cands else None


def decide_no_data(*, bsns_year: int, reprt_code: str, today: date, first_filing_dt: date | None,
                   delisted_at: date | None, filings: list[dict], fiscal_end: date | None = None,
                   first_daily_bar: date | None = None, incorporated_at: date | None = None) -> str:
    """status 013 셀의 라벨. filings = 공시 목록 항목 [{report_nm, rcept_dt(date)}] (정정 포함 — 접수 사실 판별용)."""
    return decide_no_data_with_basis(bsns_year=bsns_year, reprt_code=reprt_code, today=today, first_filing_dt=first_filing_dt,
                                     delisted_at=delisted_at, filings=filings, fiscal_end=fiscal_end,
                                     first_daily_bar=first_daily_bar, incorporated_at=incorporated_at)[0]


def decide_no_data_with_basis(*, bsns_year: int, reprt_code: str, today: date, first_filing_dt: date | None,
                              delisted_at: date | None, filings: list[dict], fiscal_end: date | None = None,
                              first_daily_bar: date | None = None,
                              incorporated_at: date | None = None) -> tuple[str, str | None]:
    """(라벨, 근거). 근거는 대체·특례 규칙을 쓴 경우만(BASIS_*), 그 외 None. 우선순위·라벨 집합 불변(회신 24 C 반려).

    추가 순서(회신 2026-11-05): ① 기간 부존재(설립일 > 기간 말) → BEFORE_FIRST_FILING + 근거 ② 제160조 제2항 직전 보고서
    (D ≥ 2025-07-22, 기간 말 = D 직전 분기 말) → 기한 = max(정기 기한, D+5): 미도래 NOT_YET_DUE / 접수 FILED_BUT_API_MISSING /
    없음 NOT_FILED_OR_EXEMPT(갈음 가능) — 전부 근거에 D 기록. 그 외는 종전 규칙 그대로.
    """
    p_end = fiscal_end or period_end(bsns_year, reprt_code)
    due = due_date(p_end, reprt_code)
    if incorporated_at is not None and p_end < incorporated_at:
        return BEFORE_FIRST_FILING, f"{BASIS_INCORPORATED_AFTER_PERIOD}={incorporated_at.isoformat()}"
    subject = _subject_date(first_filing_dt, first_daily_bar)
    if subject is not None and subject >= LAW_160_2_EFFECTIVE and p_end == prior_period_end(subject):
        basis = f"{BASIS_LAW_160_2_PRIOR_REPORT}(D={subject.isoformat()})"
        deadline = max(due, subject + timedelta(days=LAW_160_2_GRACE_DAYS))
        if deadline > today:
            return NOT_YET_DUE, basis
        if delisted_at is not None and p_end > delisted_at:
            return AFTER_DELISTING, None
        if any(_matches_report(f.get("report_nm", ""), reprt_code, p_end) for f in filings):
            return FILED_BUT_API_MISSING, basis
        return NOT_FILED_OR_EXEMPT, basis
    if due > today:
        return NOT_YET_DUE, None
    if delisted_at is not None and p_end > delisted_at:
        return AFTER_DELISTING, None
    if first_filing_dt is not None and due < first_filing_dt:
        return BEFORE_FIRST_FILING, None
    if (first_filing_dt is None and not filings and first_daily_bar is not None
            and first_daily_bar > DATA_COLLECTION_START and due < first_daily_bar):
        return BEFORE_FIRST_FILING, BASIS_LISTING_PROXY_FIRST_DAILY_BAR   # 회신 24 Q-I B — 기한 경과 후 무공시는 아래로(UNEXPLAINED 유지)
    if any(_matches_report(f.get("report_nm", ""), reprt_code, p_end) for f in filings):
        return FILED_BUT_API_MISSING, None
    if filings:   # 다른 정기공시는 있으나 이 보고서는 없음 → 미제출·면제(예: 분기보고서 면제 대상)
        return NOT_FILED_OR_EXEMPT, None
    return UNEXPLAINED, None
