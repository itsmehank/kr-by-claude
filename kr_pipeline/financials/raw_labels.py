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


def decide_no_data(*, bsns_year: int, reprt_code: str, today: date, first_filing_dt: date | None,
                   delisted_at: date | None, filings: list[dict], fiscal_end: date | None = None,
                   first_daily_bar: date | None = None) -> str:
    """status 013 셀의 라벨. filings = 공시 목록 항목 [{report_nm, rcept_dt(date)}] (정정 포함 — 접수 사실 판별용)."""
    return decide_no_data_with_basis(bsns_year=bsns_year, reprt_code=reprt_code, today=today, first_filing_dt=first_filing_dt,
                                     delisted_at=delisted_at, filings=filings, fiscal_end=fiscal_end,
                                     first_daily_bar=first_daily_bar)[0]


def decide_no_data_with_basis(*, bsns_year: int, reprt_code: str, today: date, first_filing_dt: date | None,
                              delisted_at: date | None, filings: list[dict], fiscal_end: date | None = None,
                              first_daily_bar: date | None = None) -> tuple[str, str | None]:
    """(라벨, 근거). 근거는 대체 규칙을 쓴 경우만(BASIS_LISTING_PROXY_FIRST_DAILY_BAR), 그 외 None. 우선순위·라벨 집합 불변(회신 24 C 반려)."""
    p_end = fiscal_end or period_end(bsns_year, reprt_code)
    due = due_date(p_end, reprt_code)
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
