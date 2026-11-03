# kr_pipeline/ohlcv/adj_missing_audit.py
"""#122 — pykrx 참조 adj_close 가 DART 조정 이벤트를 누락했는지 대조 (순수 함수).

방향은 #114 와 반대다. #114 는 "참조에 점프가 있는데 재구성이 설명 못 하는 건"을
찾았고, 여기서는 "DART 상세(corp_action_details)에 기준일이 있는데 참조 factor
점프가 없는 건"을 찾는다. 알려진 양성 3건(221800·232830·388610 무상증자)이
대조군 — 이 함수들이 그 3건을 missing 으로 내지 못하면 러너가 실패한다.

권리락일 규칙은 adj_reconstruct.v3_events_prov 와 동형(기준일 직전 거래일,
정지 스팬 → 재개일, 연말 주식배당 → 폐장일 직전 거래일, 기준일 후 접수 제외,
±14일 정정 클러스터 = 최신 접수 1건). 차이점: 대형 가격 갭과 겹쳐도 **억제하지
않는다** — 무상증자 1:3(배율 0.25)은 권리락일 raw 갭 자체가 대형이라 v3 의
겹침 가드를 쓰면 바로 그 누락 사례가 검사 대상에서 빠진다.
"""
from __future__ import annotations

import bisect
import math
import re
from datetime import date, timedelta

SIZE_TOL = 1.15          # 배율 허용 |log 차| ≤ log(1.15) — #114 v4.1 체인 고정값
TOL_DAYS = 5             # 권리락일 ↔ 참조 점프일 허용 달력일(±3 거래일 근사)
CR_WINDOW = (-7, 90)     # 감자: 기준일 후 구주권 제출·정지 → 재개일 조정(#114 9차 ④ p95 84일)
WINDOW_DAYS = 380        # 오염 창 = 권리락일 ~ +380일(52주 룩백이 이벤트를 교차)
EXACT_KINDS = ("fric", "stkdp", "cr")
CR_SIZE_TOL = 1.5        # 감자 배율(cr_rt_ostk)은 단주·차등 탓 근사 — 실측 p75 1.17·p90 1.83
CR_JUMP_MIN = 1.10       # 감자 조정으로 인정할 참조 점프 최소 크기(자사주 소각 ~1% 잔점프 제외)
HALT_MAX = 90            # 거래정지 창 연장 상한(일)
_CR_CONSOLIDATION = re.compile(r"병합|\d+\s*:\s*1|\d+\s*주를.{0,40}?1\s*주로")
# 소액·일반·기존주주 명시 제외 → 가격 무영향(002780·073010·007280)
_CR_MINORITY_EXEMPT = re.compile(r"(일반|소액|기존)\s*주주[^.\n]{0,30}(제외|해당\s*없음)")
# 차등감자인데 기타주주도 병합 — 참조는 조정하나 소액주주 비율 미파싱(000040·009410·119650·241820)
_CR_DIFFERENTIAL = re.compile(r"(그\s*외|기타|일반|소액)\s*주주")
# 전체 주주 명시 — 단서 조항에 최대주주/특수관계가 나와도 전체(054220·219750·080720, R2 ①)
_CR_ALL = re.compile(r"전체|기존\s*주식|잔여\s*주식|모든\s*주")
# 일부 주주 한정(최대주주·대주주·채권단·차등) 또는 주식수 불변 병합(리뷰 R1 ④)
_CR_PARTIAL = re.compile(r"최대주주|대주주|채권단|특수관계|차등|주식수\s*변동\s*없음")
# 출자전환 주식만 병합(000300·078130)
_CR_CONVERTED_ONLY = re.compile(r"출자전환(된|으로\s*발행)[^.]{0,40}?(에\s*대하여|대상)")
GAP_MIN = 1.25           # raw 갭 확인 가능 최소 배율(|log r| ≥ log 1.25 — 일중 잡음 밖)
GAP_TOL = 1.4            # raw 갭 ↔ 기대 배율 허용(v2 match_tol 동형 — 당일 수익률 잔차)


def _match_window(kind: str, tol_days: int = TOL_DAYS,
                  extra_days: int = 0) -> tuple[int, int]:
    lo, hi = CR_WINDOW if kind.startswith("cr") else (-tol_days, tol_days)
    return lo, hi + max(0, min(extra_days, HALT_MAX))


def resume_offset(closes: list[tuple[date, float]], ex: date) -> int:
    """권리락일이 거래정지 중이면(종가 고정) 가격이 처음 움직이는 날까지의 일수.
    정상 거래(권리락일 당일 변동)면 0. 정지 중 조정은 재개일에 반영된다(F2 동형)
    — 025620·187790·215380 실측: 감자×무상 복합이 재개일(+2주)에 한 번에 조정."""
    dates = [d for d, _ in closes]
    k = bisect.bisect_left(dates, ex)
    if k == 0 or k >= len(dates):
        return 0
    for i in range(k, len(closes)):
        if closes[i][1] != closes[i - 1][1]:
            return (closes[i][0] - ex).days
    return 0


def cr_class(method: str | None) -> str | None:
    """감자 method 분류 — "all"(전체 주주 주식병합: 배율 1/(1−r) 로 크기까지 검사) /
    "diff"(차등감자인데 기타주주도 병합: 참조는 조정하나 소액주주 비율 미파싱 →
    존재만 검사) / None(가격 무영향 또는 검사 범위 밖).

    None: 자기주식 소각(회사 보유분)·액면금액 감액(주식수 불변)·최대주주/대주주/채권단
    한정 병합·소액주주 명시 제외·출자전환 주식만 병합·주식수 변동 없는 분할 병합.
    검사 범위 밖(본 설계로 검사 불가): 전 주주 비례 유상/무상 소각 — 배율이
    1/(1−r) 이 아니라 환급액 반영식(097780·017810·138360·217820 실측).
    휴리스틱 분류기 — DB 원문을 테스트에 고정(리뷰 R1 ④·R2 ①②)."""
    if not method or _CR_CONSOLIDATION.search(method) is None:
        return None
    if _CR_MINORITY_EXEMPT.search(method):
        return None
    if _CR_DIFFERENTIAL.search(method):
        return "diff"
    if _CR_ALL.search(method):
        return "all"
    if _CR_PARTIAL.search(method) or _CR_CONVERTED_ONLY.search(method):
        return None
    return "all"


def cr_is_consolidation(method: str | None) -> bool:
    """전체 주주 주식병합 여부(cr_class == "all")."""
    return cr_class(method) == "all"


def expected_events(dates: list[date], details: list[dict], *,
                    market_dates: list[date] | None = None,
                    ) -> list[tuple[date, float | None, str, str]]:
    """DART 상세 → [(권리락일, 기대 배율 | None, kind, rcept_no)] 정렬.

    kind ∈ fric(무상·유무상 무상분) / stkdp(주식배당) / cr(전체 주주 병합 감자) /
    cr_diff(차등감자 중 기타주주 병합 — 배율 None) / piic(주주배정 유상 — 배율 None =
    존재만 검사). dates 는 해당 종목 거래일 오름차순.
    market_dates(시장 전체 거래일)가 있으면 기준일 직전 공백을 휴장(시장도 닫힘 →
    k−1 유지)과 정지(시장은 열림, 종목만 결측 → 재개일)로 구분한다. 없으면 v3 동형
    7일 규칙(2017 추석 10일 휴장을 정지로 오인 — 049080, 리뷰 R1 ②).
    기준일이 마지막 가격일 이후면 제외(pending — 창 자체가 미완, 리뷰 R1 ③).
    """
    if not dates:
        return []
    mk = sorted(market_dates) if market_dates else None
    cands: list[tuple[str, date, str, dict]] = []
    for det in details:
        rd = det.get("record_date")
        ep = det.get("endpoint", "")
        rc = det.get("rcept_no") or ""
        if rd is None:
            continue
        if ep == "crDecsn":
            ratio = det.get("ratio")
            if ratio is None or not (0 < ratio < 1):
                continue
            cc = cr_class(det.get("method"))
            if cc is None:
                continue                    # 자사주 소각·액면감액·일부 주주 한정 = 가격 무영향
            cands.append(("cr" if cc == "all" else "cr_diff", rd, rc, det))
        elif ep == "stkdpDecsn":
            ratio = det.get("ratio")
            if ratio is None or ratio <= 0:
                continue
            if rc[:8] > rd.strftime("%Y%m%d"):
                continue                    # 기준일 후 접수 — 참조는 원공시로 기조정
            cands.append(("stkdp", rd, rc, det))
        elif ep == "piicDecsn":
            if "주주" not in (det.get("method") or ""):
                continue                    # 3자배정·일반공모 = 권리락 없음
            cands.append(("piic", rd, rc, det))
        elif ep in ("fricDecsn", "pifricDecsn"):
            if det.get("ratio") is None or det["ratio"] <= 0:
                continue                    # pifric 은 배정수 미파싱 — 검사 불가
            cands.append(("fric", rd, rc, det))
    cands.sort(key=lambda x: (x[0], x[1]))
    picked: list[tuple[str, date, str, dict]] = []
    for c in cands:
        if picked and picked[-1][0] == c[0] and (c[1] - picked[-1][1]).days <= 14:
            if c[2] >= picked[-1][2]:
                picked[-1] = c
            continue
        picked.append(c)

    out: list[tuple[date, float | None, str, str]] = []
    for kind, rd, rc, det in picked:
        k = bisect.bisect_left(dates, rd)
        if k == 0 or rd > dates[-1]:
            continue                        # 가격 범위 밖(과거) / 미래 기준일 = pending
        ex = dates[k - 1]
        if mk is not None:
            i0, i1 = bisect.bisect_right(mk, ex), bisect.bisect_left(mk, rd)
            halted = i1 > i0                # (ex, rd) 사이 시장 거래일 존재 = 종목만 결측
        else:
            halted = (rd - ex).days > 7
        if halted:                          # 정지 스팬 — 조정 반영은 재개일
            if k > len(dates) - 1:
                continue
            ex = dates[k]
        elif kind == "stkdp" and rd.month == 12 and rd.day >= 28:
            if k < 2:
                continue
            ex = dates[k - 2]               # 연말 결산: 폐장일 직전 거래일
        if kind == "cr":
            r = 1.0 / (1.0 - float(det["ratio"]))
        elif kind == "cr_diff":
            r = None                        # 소액주주 비율 미파싱 — 존재만
        elif kind in ("fric", "stkdp"):
            r = 1.0 / (1.0 + float(det["ratio"]))
        else:
            r = None
        out.append((ex, r, kind, rc))
    out.sort(key=lambda e: (e[0], e[3]))
    return out


def match_expected(ex: date, r_exp: float | None, kind: str,
                   jumps: list[tuple[date, float]], *, tol_days: int = TOL_DAYS,
                   size_tol: float = SIZE_TOL, extra_days: int = 0) -> str:
    """기대 이벤트 1건 vs 참조 점프 목록 → matched / size_mismatch / missing.

    창 = ±tol_days(무상·주식배당·유상), 감자는 [−7, +90]일(지연 조정).
    extra_days(거래정지 재개까지 일수)만큼 앞쪽 창을 더 연장한다."""
    lo, hi = _match_window(kind, tol_days, extra_days)
    near = [(d, r) for d, r in jumps if lo <= (d - ex).days <= hi and r > 0]
    if kind.startswith("cr"):
        near = [(d, r) for d, r in near if abs(math.log(r)) >= math.log(CR_JUMP_MIN)]
        size_tol = CR_SIZE_TOL
    if not near:
        return "missing"
    if kind not in EXACT_KINDS or r_exp is None:
        return "matched"
    if any(abs(math.log(r) - math.log(r_exp)) <= math.log(size_tol) for _, r in near):
        return "matched"
    return "size_mismatch"


def is_pending(ex: date, kind: str, last_date: date, *, extra_days: int = 0) -> bool:
    """대조 창의 끝이 마지막 가격일을 넘으면 판정 보류(missing 으로 세지 않음)."""
    _, hi = _match_window(kind, extra_days=extra_days)
    return last_date < ex + timedelta(days=hi)


def raw_gap_evidence(closes: list[tuple[date, float]], ex: date,
                     r_exp: float | None, kind: str, *,
                     gap_min: float = GAP_MIN, gap_tol: float = GAP_TOL,
                     extra_days: int = 0) -> dict:
    """참조 점프가 없을 때 raw 종가 갭으로 이벤트 실재를 확인(#114 share_matched_gap
    동형 — 주식수 대신 가격 갭). 대형 정확 이벤트만 가능(|log r| ≥ log gap_min):
    무상 1:1(0.5)·감자 등. 주식배당(≈0.98)·유상(배율 미지)은 n/a.

    반환 {evidence: raw_gap_confirmed | raw_gap_absent | n/a, gap_date, raw_gap}.
    """
    if kind not in EXACT_KINDS or r_exp is None or r_exp <= 0 \
            or abs(math.log(r_exp)) < math.log(gap_min):
        return {"evidence": "n/a", "gap_date": None, "raw_gap": None}
    lo, hi = _match_window(kind, extra_days=extra_days)
    best: tuple[float, date, float] | None = None
    for i in range(1, len(closes)):
        d, c = closes[i]
        off = (d - ex).days
        if off < lo or off > hi:
            continue
        c_prev = closes[i - 1][1]
        if c_prev <= 0 or c <= 0:
            continue
        g = c / c_prev
        if abs(math.log(g)) < math.log(gap_min):
            continue                        # 갭 자체가 일중 잡음 수준
        dist = abs(math.log(g) - math.log(r_exp))
        if dist <= math.log(gap_tol) and (best is None or dist < best[0]):
            best = (dist, d, g)
    if best is None:
        return {"evidence": "raw_gap_absent", "gap_date": None, "raw_gap": None}
    return {"evidence": "raw_gap_confirmed", "gap_date": best[1].isoformat(),
            "raw_gap": best[2]}


def contamination_window(ex: date, passes: dict[date, bool],
                         window_days: int = WINDOW_DAYS) -> dict:
    """오염 창 [ex, ex+window_days] 내 minervini_pass 일수 — 소급 표기용."""
    end = ex + timedelta(days=window_days)
    in_w = [v for d, v in passes.items() if ex <= d <= end]
    return {"window_end": end, "window_days": len(in_w),
            "window_pass_days": sum(1 for v in in_w if v),
            "total_pass_days": sum(1 for v in passes.values() if v)}
