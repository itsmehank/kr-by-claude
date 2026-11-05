"""#129 pivot_continuity 판독의 순수 계수 함수(DB·I/O 없음).

입력 행 형식(스크립트가 SELECT 로 만든 dict): symbol, classified_at(tz-aware),
analyzed_for_date, pattern, pivot_price, classification, pc(= pivot_continuity JSON).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

_NONE_PATTERNS = (None, "none")
_LOG_RE = re.compile(rb"\[pivot-continuity\] same-base pivot reread (\d+): .*?\(([-+]?\d+\.\d+)%\)")


def _effective(r):
    return (r["analyzed_for_date"] or r["classified_at"].date(), r["classified_at"])


def _by_symbol(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["symbol"]].append(r)
    for rs in by.values():
        rs.sort(key=_effective)
    return by


def downward_chains(rows):
    """하향 재판독 행마다 '내려간 pivot 이 유지되는 동안'의 후속 행을 묶는다(리뷰 R1-1).

    시작 = same/near 이고 pivot_change_pct < 0 인 행. old_pivot = 그 행의 직전 활성 pivot.
    후속 행은 same/near 이고 pivot_change_pct ≤ 0(내려간 pivot 을 그대로 유지하거나 더 내림)이며
    pivot < old_pivot 인 동안 포함 — 상향 재판독(새 판단)이나 베이스 변경이 나오면 중단. 중첩 시작(체인 안의 또 다른 하향)은 각자 체인을 갖는다 — 평가
    조회는 호출자가 (symbol, classified_at) 로 중복 제거한다.
    Returns: list of (start_row, old_pivot, members[start 포함, 유효일 순]).
    """
    chains = []
    for rs in _by_symbol(rows).values():
        for i, r in enumerate(rs):
            pc = r["pc"]
            chg = pc.get("pivot_change_pct")
            if pc.get("base_continuity") not in ("same", "near") or chg is None or chg >= 0:
                continue
            old = pc.get("prev_pivot_price")
            members = [r]
            for nxt in rs[i + 1:]:
                npv, nchg = nxt["pivot_price"], nxt["pc"].get("pivot_change_pct")
                if (nxt["pc"].get("base_continuity") not in ("same", "near")
                        or nchg is None or nchg > 0
                        or npv is None or old is None or float(npv) >= float(old)):
                    break
                members.append(nxt)
            chains.append((r, old, members))
    return chains


def pattern_round_trips(rows):
    """A→B→A 왕복 — 실제 연속 3행(각 행의 prev_classified_at 로 연결)만, none 제외(리뷰 R1-2)."""
    by_key = {(r["symbol"], r["classified_at"].isoformat()): r for r in rows}
    n = 0
    for r in rows:
        p0, p1 = r["pattern"], r["pc"].get("prev_pattern")
        prev = by_key.get((r["symbol"], r["pc"].get("prev_classified_at") or ""))
        if prev is None:
            continue
        p2 = prev["pc"].get("prev_pattern")
        if any(p in _NONE_PATTERNS for p in (p0, p1, p2)):
            continue
        if p0 == p2 and p0 != p1:
            n += 1
    return n


def parse_log_events(lines):
    """로그 바이트 줄들에서 same-base 경고를 (symbol, 변화율 소수 2자리) Counter 로(리뷰 R1-7)."""
    c = Counter()
    for line in lines:
        m = _LOG_RE.search(line)
        if m:
            c[(m.group(1).decode(), round(float(m.group(2)), 2))] += 1
    return c


def stored_events(rows):
    """저장본 same-base pivot 변경 행을 로그와 같은 키로."""
    c = Counter()
    for r in rows:
        chg = r["pc"].get("pivot_change_pct")
        if r["pc"].get("base_continuity") == "same" and chg not in (None, 0):
            c[(r["symbol"], round(float(chg), 2))] += 1
    return c
