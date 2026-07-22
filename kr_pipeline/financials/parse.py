"""(#68 2단계) DART 응답 정규화 — 순수 함수 (스펙 §3·§4).

1단계 실측 발견 대응:
- C: 계정명 별칭('당기순이익(손실)')·동명 중복(지배주주 구분) → 첫 행 채택
- B: thstrm_dt 파싱으로 비12월 결산 회계기간 확보
- A: 원공시 접수일은 list.json 에서 — 정정 prefix([기재정정] 등) 행 제외
"""
from __future__ import annotations

import re
from datetime import date

_ACCOUNT_MAP = {
    "매출액": "revenue",
    "영업수익": "revenue",       # 서비스업 변형 (리뷰 Important-5: 094850 등 실측)
    "수익(매출액)": "revenue",
    "영업이익": "operating_income",
    "당기순이익": "net_income",
    "당기순이익(손실)": "net_income",
}

# reprt_code → list.json report_nm 의 (보고서명, 기간 월) — 기간 토큰은 fiscal_end 로 산출
_REPRT_NAME = {
    "11011": "사업보고서",
    "11013": "분기보고서",
    "11012": "반기보고서",
    "11014": "분기보고서",
}


def _num(s) -> float | None:
    if s is None:
        return None
    t = str(s).replace(",", "").strip()
    if not t or t == "-":
        return None
    try:
        return float(t)
    except ValueError:
        return None


def normalize_accounts(rows: list[dict]) -> dict:
    """fnlttSinglAcnt list → {fs_div, revenue, operating_income, net_income}.

    CFS 에 매칭 계정이 1개라도 있으면 CFS, 아니면 OFS. 동명 중복은 첫 행.
    """
    out = {"fs_div": None, "revenue": None, "operating_income": None,
           "net_income": None}
    for fs in ("CFS", "OFS"):
        sub = [r for r in rows if r.get("fs_div") == fs]
        vals: dict[str, float] = {}
        for r in sub:
            key = _ACCOUNT_MAP.get((r.get("account_nm") or "").strip())
            if key and key not in vals:  # 동명 중복 첫 행 (스펙 §3)
                v = _num(r.get("thstrm_amount"))
                if v is not None:
                    vals[key] = v
        if vals:
            out.update(vals)
            out["fs_div"] = fs
            break
    return out


def extract_eps_pair(rows: list[dict], fs_div: str) -> tuple[float | None, float | None]:
    """fnlttSinglAcntAll list → (당기 EPS, 같은 공시의 전년 동기 EPS) — 원 단위.

    손익계산서(IS/CIS) 의 주당이익 계정 중 '희석' 제외, '기본' 표기 우선.
    fs_div: 응답에 fs_div 필드가 있으면 일치 요구, 없으면(실측 —
    fnlttSinglAcntAll 은 요청 파라미터로 스코프돼 필드 미포함) 수용.
    전년 동기 = 분기·반기 frmtrm_q_amount(3개월 단독), 연간 frmtrm_amount
    (실측 016800). 같은 공시의 비교값은 소급 재작성돼 무상증자/분할·지배/전체
    혼재에 면역 — F-C1/C2 의 1순위 YoY 입력.
    """
    cand = [r for r in rows
            if r.get("fs_div") in (fs_div, None) and r.get("sj_div") in ("IS", "CIS")
            and "주당" in (r.get("account_nm") or "")
            and "희석" not in (r.get("account_nm") or "")]
    if not cand:
        return (None, None)
    pick = next((r for r in cand if "기본" in (r.get("account_nm") or "")), cand[0])
    prior = _num(pick.get("frmtrm_q_amount"))
    if prior is None:
        prior = _num(pick.get("frmtrm_amount"))
    return (_num(pick.get("thstrm_amount")), prior)


def extract_eps(rows: list[dict], fs_div: str) -> float | None:
    """당기 공시 EPS 만 — extract_eps_pair 의 축약(대조 스크립트용)."""
    return extract_eps_pair(rows, fs_div)[0]


_PERIOD_RE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")


def parse_thstrm(s) -> tuple[date | None, date | None]:
    """'2023.01.01 ~ 2023.12.31' → (start, end) / '2023.12.31 현재' → (None, end)."""
    if not s:
        return (None, None)
    dates = [date(int(y), int(m), int(d)) for y, m, d in _PERIOD_RE.findall(str(s))]
    if not dates:
        return (None, None)
    if len(dates) == 1:
        return (None, dates[0])
    return (dates[0], dates[-1])


_CORRECTION_RE = re.compile(r"^\s*\[")  # [기재정정], [첨부정정] 등 prefix 행 = 정정


def match_disclosure(items: list[dict], bsns_year: int, reprt_code: str,
                     *, fiscal_end: date) -> date | None:
    """list.json 항목에서 (bsns_year, reprt_code) 보고서의 **원공시** 접수일.

    매칭 = 정정 prefix 없는 행 중 report_nm 이 "<보고서명> (YYYY.MM)" 토큰과 일치.
    복수 매칭 시 가장 이른 접수일(원공시). 실패 → None (as-of 제외 — 보수).
    """
    name = _REPRT_NAME.get(reprt_code)
    if name is None or fiscal_end is None:
        return None
    token = f"({fiscal_end.year}.{fiscal_end.month:02d})"
    hits = []
    for it in items:
        rn = (it.get("report_nm") or "").strip()
        if _CORRECTION_RE.match(rn):
            continue
        if rn.startswith(name) and token in rn:
            rd = (it.get("rcept_dt") or "").strip()
            if len(rd) == 8 and rd.isdigit():
                hits.append(date(int(rd[:4]), int(rd[4:6]), int(rd[6:8])))
    return min(hits) if hits else None
