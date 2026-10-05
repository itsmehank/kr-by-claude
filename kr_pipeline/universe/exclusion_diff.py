"""(#221) 유니버스 배제 집합 변동의 3분류 — 설명 가능한 2유형은 자동 수용, 나머지는 잔여(사람 판정).

guard(snapshot)(guards.verify_universe_after_load)은 "이번 배제 집합 ≠ 직전 스냅샷" 이면 멈추도록 설계됐다(#195 커밋2).
변동의 대부분은 매달 반복되는 두 유형이라 로컬 데이터만으로 기계 판정이 된다(2026-10-01 실측: 신규 스팩 2·스팩 소멸 1):
  (1) removed ∧ 이번 원본(raw) 목록에도 없음 → 상장폐지로 배제 집합에서 자연 탈락(원본 완전성은 __main__._raw_complete 가 먼저 fail-closed).
  (2) added ∧ 어디에도 본 적 없음(stocks·이전 배제 스냅샷·이전 원본 스냅샷) ∧ 배제 축 ∈ AUTO_ACCEPT_AXES → 신규 상장 배제 대상.
그 외는 잔여 — 특히 #199 가 자동 수용을 금지한 "기존 활성 종목(security_group 이 확정돼 있던) → 신규 배제"(kind='199': --accept 로도
수용 불가, 상태 컬럼·의미 정정 동반 사안), "UNRESOLVED 로 들어와 있던 행의 늦은 분류"(kind='late_resolution': 원인은 조회 지연이지만 결과가 #199 와 같아 — 행 있는 종목을
배제하면 mark_delisted 가 상장폐지로 오기록 — --accept 로도 수용 불가, 첫 발생 = #199 착수 신호, 회신 23 Q-G), "원본에는 있는데 배제에서만 빠짐"(배제 축이 풀림 = 규칙/분류 변경), "이전에 본 종목의 재등장"(왕복 — 부분 응답 의심).
잔여는 report.py 가 조사 보고서(자료)를 만들고 사람이 --accept-exclusion-diff 로 수용한다(governance 2-1/2-2 권한 분리 — LLM 은
결정하지 않는다). 원인이 이미 알려진 일괄 잔여는 systemic 에 쌓인다(복수 가능). 순수 함수: DB 접근 없음.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from kr_pipeline.common.security_group import UNRESOLVED

AUTO_ACCEPT_AXES = frozenset({"spac", "preferred", "security_group"})   # transform.classify_exclusion_axis 의 축 이름
# 자동 수용 상한 — **잠정, 2026-10-01 실측 1회(상폐 1·신규 2) 기반**. 회신 22 Q-C 로 A(10/30, report.MAX_LLM_ITEMS=20) 채택, 책 근거 없음
# (design-judgment). 월간 유형별 실측 건수(pipeline_runs universe details.exclusion_auto_accepted)를 6회 누적(≈2027-04)한 뒤 실측 최댓값
# 기준으로 재설정(threshold-change-checklist 절차). KRX 부분 응답(스로틀)으로 수백 종목이 통째로 빠지면 removed 가
# "원본에 없음" 조건을 전부 만족한다 — mark_delisted 의 2% 가드는 stocks 행이 없는 배제 축 종목을 못 본다. 월간 실측 규모(10-01: 상폐 1·
# 신규 2)의 여유분으로 상한을 두고, 넘으면 그 유형 전부를 잔여로 돌린다(fail-closed). 상한 이하의 부분 응답은 __main__._raw_complete
# (직전 원본 대비 시장별 급감 → 쓰기 전 fail-closed)가 2차 신호, 재등장 왕복은 ever_seen 이 막는다.
MAX_AUTO_DELISTED = 10
MAX_AUTO_NEW_LISTING = 30
SYSTEMIC_CAP_DELISTED = "cap_delisted"
SYSTEMIC_CAP_NEW_LISTING = "cap_new_listing"
KIND_199 = "199"
KIND_LATE_RESOLUTION = "late_resolution"
# --accept-exclusion-diff 로도 수용 불가한 잔여 유형 — 둘 다 "stocks 행이 있는 종목 → 신규 배제"라 수용하면 적재 대상(kept)에서 빠진 그
# 종목을 mark_delisted 가 delisted_at=오늘로 기록한다(상장 중인데 폐지). 회신 10·12(#199)·23 Q-G: 금지 사유는 원인이 아니라 결과.
ACCEPT_REFUSED_KINDS = frozenset({KIND_199, KIND_LATE_RESOLUTION})


@dataclass
class ExclusionDiff:
    added_new_listing: list[str] = field(default_factory=list)      # 자동: 신규 상장 배제 대상
    removed_delisted: list[str] = field(default_factory=list)       # 자동: 상장폐지
    unexplained_added: list[dict] = field(default_factory=list)     # 잔여: {ticker, name, axis, security_group, reason, kind}
    unexplained_removed: list[dict] = field(default_factory=list)   # 잔여: {ticker, reason}
    systemic: list[str] = field(default_factory=list)               # 원인이 이미 알려진 일괄 잔여(복수) — LLM 조사 불요

    @property
    def unexplained(self) -> bool:
        return bool(self.unexplained_added or self.unexplained_removed)

    @property
    def changed(self) -> bool:
        return bool(self.added_new_listing or self.removed_delisted or self.unexplained)

    @property
    def unexplained_tickers(self) -> set[str]:
        return {u["ticker"] for u in self.unexplained_added} | {u["ticker"] for u in self.unexplained_removed}

    @property
    def accept_refused_tickers(self) -> list[str]:
        """--accept-exclusion-diff 로도 수용 불가한 잔여(#199 유형 + 늦은 분류) 티커 — 해소 경로는 #199(의미 정정 + 상태 컬럼)."""
        return sorted(u["ticker"] for u in self.unexplained_added if u.get("kind") in ACCEPT_REFUSED_KINDS)

    @property
    def has_accept_refused(self) -> bool:
        return bool(self.accept_refused_tickers)

    def report_key(self) -> list[str]:
        """방향 포함 잔여 키(보고서 dedup 용): ['+088980', '-R9']."""
        return sorted([f"+{u['ticker']}" for u in self.unexplained_added] + [f"-{u['ticker']}" for u in self.unexplained_removed])

    def summary(self) -> dict:
        """pipeline_runs.details / 로그용 — 성공·실패 행이 같은 키 모양을 쓴다(guards.info 와 동일)."""
        return {
            "exclusion_auto_accepted": {"removed_delisted": sorted(self.removed_delisted), "added_new_listing": sorted(self.added_new_listing)},
            "exclusion_unexplained": {"added": [u["ticker"] for u in self.unexplained_added],
                                      "removed": [u["ticker"] for u in self.unexplained_removed]},
            "exclusion_unexplained_detail": {**{u["ticker"]: u for u in self.unexplained_added}, **{u["ticker"]: u for u in self.unexplained_removed}},
            "exclusion_systemic": list(self.systemic),
            "report_key": self.report_key(),
        }


def _added(r, reason: str, kind: str | None = None) -> dict:
    return {"ticker": r.ticker, "name": r.name, "axis": getattr(r, "axis", None), "security_group": r.security_group,
            "reason": reason, "kind": kind}


def classify_exclusion_diff(*, prev_set: set[str], excluded: pd.DataFrame, raw_tickers: set[str] | None,
                            ever_in_stocks: set[str] | dict[str, str | None], ever_seen: set[str] | None = None) -> ExclusionDiff:
    """prev_set = 직전 스냅샷의 배제 티커, excluded = 이번 배제 df(ticker,name,market,security_group,axis),
    raw_tickers = 이번 fetch_universe 원본 전량(필터 전; None 이면 removed 전부 잔여 — 상폐 판정 불가),
    ever_in_stocks = stocks 에 존재한 적 있는 티커 → 그 행의 security_group(dict; set 이면 전부 확정 취급). UNRESOLVED 였던 행은
    kind='late_resolution'(늦은 분류), 확정 그룹이었던 행은 kind='199' — 둘 다 accept 불가(ACCEPT_REFUSED_KINDS).
    ever_seen = 이전 배제/원본 스냅샷에 등장한 티커(재등장 = 왕복 의심)."""
    cur = {} if excluded is None or excluded.empty else {r.ticker: r for r in excluded.itertuples(index=False)}
    seen = ever_seen or set()
    in_stocks = ever_in_stocks if isinstance(ever_in_stocks, dict) else {t: "resolved" for t in ever_in_stocks}
    out = ExclusionDiff()
    for t in sorted(set(cur) - prev_set):
        r = cur[t]
        axis = getattr(r, "axis", None)
        if t in in_stocks:
            if (in_stocks[t] or UNRESOLVED) == UNRESOLVED:
                out.unexplained_added.append(_added(r, f"UNRESOLVED 로 적재돼 있던 종목이 배제 축 '{r.axis}' 에 걸림(늦은 분류) — 수용 시 상장폐지 오기록, accept 불가(#199 선행)",
                                                    KIND_LATE_RESOLUTION))
            else:
                out.unexplained_added.append(_added(r, "기존 활성(또는 폐지 이력, security_group 확정) 종목이 새로 배제 — #199 유형, 자동·accept 수용 금지", KIND_199))
        elif t in seen:
            out.unexplained_added.append(_added(r, "이전 스냅샷에 있던 종목의 재등장 — 신규 상장 아님(부분 응답 왕복 의심)"))
        elif axis in AUTO_ACCEPT_AXES:
            out.added_new_listing.append(t)
        else:
            out.unexplained_added.append(_added(r, f"배제 축 '{axis}' 은 자동 수용 대상 아님"))
    for t in sorted(prev_set - set(cur)):
        if raw_tickers is not None and t not in raw_tickers:
            out.removed_delisted.append(t)
        else:
            out.unexplained_removed.append({"ticker": t, "reason": ("원본 목록에 남아 있는데 배제 집합에서 빠짐 — 배제 축이 풀린 것(규칙/분류 변경)"
                                                               if raw_tickers is not None else "원본 목록 미제공 — 상폐 여부 판정 불가")})
    if len(out.removed_delisted) > MAX_AUTO_DELISTED:
        out.unexplained_removed.extend({"ticker": t, "reason": f"상폐 후보 {len(out.removed_delisted)} > 상한 {MAX_AUTO_DELISTED} — KRX 부분 응답 의심, 일괄 잔여"}
                                       for t in out.removed_delisted)
        out.removed_delisted = []
        out.systemic.append(SYSTEMIC_CAP_DELISTED)
    if len(out.added_new_listing) > MAX_AUTO_NEW_LISTING:
        out.unexplained_added.extend(_added(cur[t], f"신규 배제 후보 {len(out.added_new_listing)} > 상한 {MAX_AUTO_NEW_LISTING} — 일괄 잔여")
                                     for t in out.added_new_listing)
        out.added_new_listing = []
        out.systemic.append(SYSTEMIC_CAP_NEW_LISTING)
    return out
