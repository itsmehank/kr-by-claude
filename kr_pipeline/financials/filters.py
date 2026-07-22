"""(#68 4단계) 실적 필터 판정 — 잠긴 사전등록 §2·§3 의 순수 구현.

준거: docs/superpowers/specs/2026-07-22-issue68-stage3-filter-prereg.md (LOCKED).
입력은 get_financials_asof 반환 행만 받는다(look-ahead chokepoint 규약 —
직접 테이블 조회 금지). 라벨 4종: pass / fail / indeterminate / turnaround.
"""
from __future__ import annotations

from datetime import date

THRESHOLD = 0.25                     # 오닐 C 최소 기준 (LOCKED §3)
FILTERS = ("F-C1", "F-C2", "F-C3", "F-S1")

_Q_OF = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}
_REPRT_OF = {1: "11013", 2: "11012", 3: "11014", 4: "11011"}
_QUARTERS = ("11013", "11012", "11014")


def _f(v) -> float | None:
    return None if v is None else float(v)


def _label(kind: str, tags: set[str]) -> dict:
    return {"label": kind, "tags": sorted(tags)}


class _View:
    """as-of 가시 행의 조회 뷰 — (연도, 분기) 단위 값·4Q 파생·이행기 판정."""

    def __init__(self, rows: list[dict]):
        self.rows = sorted(
            rows, key=lambda r: (r.get("fiscal_end") or date.min), reverse=True)
        self.idx: dict[tuple[int, str], dict] = {}
        for r in rows:
            self.idx.setdefault((r["bsns_year"], r["reprt_code"]), r)
        # 결산기 변경 이행기: 가시 연간 행의 회계기간이 12개월 ±20일 밖 (§2)
        self.transition_years: set[int] = set()
        for (y, rc), r in self.idx.items():
            if rc != "11011":
                continue
            fs, fe = r.get("fiscal_start"), r.get("fiscal_end")
            if fs and fe and not (345 <= (fe - fs).days <= 385):
                self.transition_years.add(y)

    def latest(self) -> tuple[int, int] | None:
        if not self.rows:
            return None
        r = self.rows[0]
        return (r["bsns_year"], _Q_OF[r["reprt_code"]])

    def transition_hit(self, year: int) -> bool:
        """(year, year−1) 을 잇는 YoY 에 이행기 연도가 끼는가."""
        return bool({year, year - 1} & self.transition_years)

    def amount(self, year: int, q: int, field: str) -> tuple[float | None, set[str]]:
        """3개월 단독 금액 — 분기 행 그대로, 4Q 는 연간−(1Q+2Q+3Q) 파생 (§2)."""
        if q != 4:
            r = self.idx.get((year, _REPRT_OF[q]))
            return (_f(r.get(field)) if r else None, set())
        annual = self.idx.get((year, "11011"))
        if not annual:
            return (None, set())
        vals = [_f(annual.get(field))]
        for rc in _QUARTERS:
            r = self.idx.get((year, rc))
            if not r or r.get("fs_div") != annual.get("fs_div"):
                return (None, set())
            vals.append(_f(r.get(field)))
        if any(v is None for v in vals):
            return (None, set())
        return (vals[0] - sum(vals[1:]), {"q4_derived"})

    def shares(self, year: int, q: int) -> float | None:
        """파생 EPS 의 분모 — 해당 연도 주식수(분기 행도 연간 근사값 보유)."""
        r = self.idx.get((year, _REPRT_OF[q])) or self.idx.get((year, "11011"))
        return _f(r.get("shares_outstanding")) if r else None

    def eps_derived(self, year: int, q: int) -> tuple[float | None, set[str]]:
        if q != 4:
            r = self.idx.get((year, _REPRT_OF[q]))
            return (_f(r.get("eps_derived")) if r else None, set())
        ni, tags = self.amount(year, 4, "net_income")
        s = self.shares(year, 4)
        if ni is None or not s:
            return (None, set())
        return (ni / s, tags | {"q4_derived"})


def _yoy(cur: float | None, prev: float | None):
    """(상태, g). 상태 ∈ {g, turnaround, fail, indeterminate} (§2 흑자전환 규칙)."""
    if cur is None or prev is None:
        return ("indeterminate", None)
    if prev <= 0:
        return ("turnaround" if cur > 0 else "fail", None)
    return ("g", (cur - prev) / abs(prev))


def _eps_growth(v: _View, year: int, q: int) -> tuple[str, float | None, set[str]]:
    """EPS YoY — 공시 같은-공시 쌍 1순위, 파생 폴백 + 주식수 2단 가드 (§2)."""
    if v.transition_hit(year):
        return ("indeterminate", None, {"fiscal_transition"})
    if q != 4:
        r = v.idx.get((year, _REPRT_OF[q]))
        pub = _f(r.get("eps_published")) if r else None
        prior = _f(r.get("eps_published_prior")) if r else None
        if pub is not None and prior is not None:
            state, g = _yoy(pub, prior)
            return (state, g, {"published"})
    cur, t1 = v.eps_derived(year, q)
    prev, t2 = v.eps_derived(year - 1, q)
    tags = t1 | t2 | {"eps_fallback"}
    if cur is None or prev is None:
        return ("indeterminate", None, tags)
    s_cur, s_prev = v.shares(year, q), v.shares(year - 1, q)
    if not s_cur or not s_prev:
        return ("indeterminate", None, tags)
    r = s_cur / s_prev
    if r >= 100 or r <= 0.01:
        return ("indeterminate", None, tags | {"guard_data_error"})
    if not (0.5 <= r <= 2):
        return ("indeterminate", None, tags | {"guard_corp_action"})
    state, g = _yoy(cur, prev)
    return (state, g, tags)


def _amount_growth(v: _View, year: int, q: int, field: str):
    """영업이익·매출 YoY — 금액 기반, 주식수 가드 비적용 (§3)."""
    if v.transition_hit(year):
        return ("indeterminate", None, {"fiscal_transition"})
    cur, t1 = v.amount(year, q, field)
    prev, t2 = v.amount(year - 1, q, field)
    state, g = _yoy(cur, prev)
    return (state, g, t1 | t2)


def _to_filter(state: str, g: float | None, tags: set[str]) -> dict:
    if state == "g":
        return _label("pass" if g >= THRESHOLD else "fail", tags)
    return _label(state, tags)


def _prev_quarter(year: int, q: int) -> tuple[int, int]:
    return (year, q - 1) if q > 1 else (year - 1, 4)


def evaluate_filters(rows: list[dict]) -> dict:
    """진입일 as-of 가시 행 → 필터 4개 라벨 (LOCKED §2·§3).

    F-C2 는 F-C1 AND 가속(g_t > g_{t−1q}) — 두 g 중 하나라도 흑자전환/미정의면
    판정불가(통과 아님, 보수).
    """
    v = _View([r for r in rows if r.get("status") == "ok"])
    latest = v.latest()
    if latest is None:
        return {f: _label("indeterminate", set()) for f in FILTERS}
    year, q = latest

    c1_state, c1_g, c1_tags = _eps_growth(v, year, q)
    out = {"F-C1": _to_filter(c1_state, c1_g, c1_tags)}

    if c1_state != "g":
        out["F-C2"] = _label("indeterminate", c1_tags)
    else:
        py, pq = _prev_quarter(year, q)
        p_state, p_g, p_tags = _eps_growth(v, py, pq)
        if p_state != "g":
            out["F-C2"] = _label("indeterminate", c1_tags | p_tags)
        else:
            ok = c1_g >= THRESHOLD and c1_g > p_g
            out["F-C2"] = _label("pass" if ok else "fail", c1_tags | p_tags)

    out["F-C3"] = _to_filter(*_amount_growth(v, year, q, "operating_income"))
    out["F-S1"] = _to_filter(*_amount_growth(v, year, q, "revenue"))
    return out
