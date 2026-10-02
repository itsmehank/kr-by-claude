"""(#221) 유니버스 배제 집합 변동의 3분류 — 설명 가능한 2유형은 자동 수용, 나머지는 잔여(사람 판정).

guard(snapshot)(guards.verify_universe_after_load)은 "이번 배제 집합 ≠ 직전 스냅샷" 이면 멈추도록 설계됐다(#195 커밋2).
변동의 대부분은 매달 반복되는 두 유형이라 로컬 데이터만으로 기계 판정이 된다(2026-10-01 실측: 신규 스팩 2·스팩 소멸 1):
  (1) removed ∧ 이번 원본(raw) 목록에도 없음 → 상장폐지로 배제 집합에서 자연 탈락.
  (2) added ∧ stocks 에 존재한 적 없음 ∧ 배제 축 ∈ AUTO_ACCEPT_AXES → 신규 상장 배제 대상.
그 외는 잔여 — 특히 #199 가 자동 수용을 금지한 "기존 활성 종목 → 신규 배제"(상태 컬럼·의미 정정 동반 사안)와
"원본에는 있는데 배제에서만 빠짐"(배제 축이 풀림 = 규칙/분류 변경). 잔여는 report.py 가 조사 보고서(자료)를 만들고 사람이
--accept-exclusion-diff 로 수용한다(governance 원칙 2 권한 분리 — LLM 은 결정하지 않는다).
순수 함수: DB 접근 없음(ever_in_stocks 는 호출자가 조회).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

AUTO_ACCEPT_AXES = frozenset({"spac", "preferred", "security_group"})   # transform.classify_exclusion_axis 의 축 이름
# 자동 수용 상한(리뷰 #223): KRX 부분 응답(스로틀)으로 수백 종목이 통째로 빠지면 removed 가 "원본에 없음" 조건을 전부 만족한다 —
# mark_delisted 의 2% 가드는 stocks 행이 없는 배제 축 종목을 못 본다. 월간 실측 규모(10-01: 상폐 1·신규 2)의 여유분으로 상한을 두고,
# 넘으면 그 유형 전부를 잔여로 돌린다(기존 가드처럼 fail-closed). 다음 달 재등장 왕복(removed→added 자동)도 같은 상한이 막는다.
MAX_AUTO_DELISTED = 10
MAX_AUTO_NEW_LISTING = 30


@dataclass
class ExclusionDiff:
    added_new_listing: list[str] = field(default_factory=list)      # 자동: 신규 상장 배제 대상
    removed_delisted: list[str] = field(default_factory=list)       # 자동: 상장폐지
    unexplained_added: list[dict] = field(default_factory=list)     # 잔여: {ticker, name, axis, security_group, reason}
    unexplained_removed: list[dict] = field(default_factory=list)   # 잔여: {ticker, reason}

    @property
    def unexplained(self) -> bool:
        return bool(self.unexplained_added or self.unexplained_removed)

    @property
    def changed(self) -> bool:
        return bool(self.added_new_listing or self.removed_delisted or self.unexplained)

    def summary(self) -> dict:
        """pipeline_runs.details / 로그용."""
        return {
            "added_new_listing": sorted(self.added_new_listing),
            "removed_delisted": sorted(self.removed_delisted),
            "unexplained": sorted([u["ticker"] for u in self.unexplained_added] + [u["ticker"] for u in self.unexplained_removed]),
        }


def classify_exclusion_diff(*, prev_set: set[str], excluded: pd.DataFrame, raw_tickers: set[str] | None,
                            ever_in_stocks: set[str]) -> ExclusionDiff:
    """prev_set = 직전 스냅샷의 배제 티커, excluded = 이번 배제 df(ticker,name,market,security_group,axis),
    raw_tickers = 이번 fetch_universe 원본 전량(필터 전). None 이면 removed 는 전부 잔여(보수 — 상폐 판정 불가)."""
    cur = {} if excluded is None or excluded.empty else {
        r.ticker: r for r in excluded.itertuples(index=False)}
    out = ExclusionDiff()
    for t in sorted(set(cur) - prev_set):
        r = cur[t]
        axis = getattr(r, "axis", None)
        if t in ever_in_stocks:
            out.unexplained_added.append({"ticker": t, "name": r.name, "axis": axis, "security_group": r.security_group,
                                          "reason": "기존 활성(또는 폐지 이력) 종목이 새로 배제 — #199 유형, 자동 수용 금지"})
        elif axis in AUTO_ACCEPT_AXES:
            out.added_new_listing.append(t)
        else:
            out.unexplained_added.append({"ticker": t, "name": r.name, "axis": axis, "security_group": r.security_group,
                                          "reason": f"배제 축 '{axis}' 은 자동 수용 대상 아님"})
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
    if len(out.added_new_listing) > MAX_AUTO_NEW_LISTING:
        out.unexplained_added.extend({"ticker": t, "name": cur[t].name, "axis": getattr(cur[t], "axis", None), "security_group": cur[t].security_group,
                                      "reason": f"신규 배제 후보 {len(out.added_new_listing)} > 상한 {MAX_AUTO_NEW_LISTING} — 일괄 잔여"}
                                     for t in out.added_new_listing)
        out.added_new_listing = []
    return out
