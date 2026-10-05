"""유니버스 적재 후 회귀 가드 [3-b] — 위반 시 UniverseGuardError → run_tracking 이 rollback·failed 처리.

(a) 활성 stocks 의 security_group ⊆ QUALIFYING ∪ {UNRESOLVED} ∪ ROW_KEPT_EXCLUDED(행 생성 대상 = 명시 예외).
(b) 비-SECUGRP 2축(우선주 코드 규칙·스팩 이름) 활성 카운트 0. (ETF 축은 #195 커밋2 에서 제거 — governance 1-1)
(c) 전기 대비 활성 종목 수 기록 — 경고 임계 없음(별도 판정 사안).
(신규) 적재 전 배제 집합 스냅샷을 저장하고 직전 스냅샷과 집합 대조 — 원소 변동은 accept 플래그 없이 실패.

plan: docs/superpowers/plans/2026-09-15-secugrp-universe-filter.md Task 4.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from psycopg import Connection

from kr_pipeline.common.security_group import (
    QUALIFYING_SECURITY_GROUPS, ROW_KEPT_EXCLUDED_SECURITY_GROUPS, UNRESOLVED,
)
from kr_pipeline.universe.exclusion_diff import ExclusionDiff, classify_exclusion_diff
from kr_pipeline.universe.transform import classify_exclusion_axis


class UniverseGuardError(ValueError):
    """(#221) guard(snapshot) 실패 시 `diff`(ExclusionDiff)가 붙는다 — __main__ 이 조사 보고서 입력으로 쓴다."""

    def __init__(self, msg: str, diff: "ExclusionDiff | None" = None, prev_date: date | None = None):
        super().__init__(msg)
        self.diff = diff
        self.prev_date = prev_date       # 가드가 비교한 직전 스냅샷 날짜(호출자가 재조회하지 않는다 — 리뷰 #223 2차)


_ALLOWED_ACTIVE_GROUPS = QUALIFYING_SECURITY_GROUPS | ROW_KEPT_EXCLUDED_SECURITY_GROUPS | {UNRESOLVED}


def count_active(conn: Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM stocks WHERE delisted_at IS NULL")
        return cur.fetchone()[0]


def write_exclusion_snapshot(conn: Connection, snapshot_date: date, excluded: pd.DataFrame) -> int:
    if excluded.empty:
        return 0
    rows = [(snapshot_date, r.ticker, r.name, r.market, r.security_group or UNRESOLVED, r.axis)
            for r in excluded.itertuples(index=False)]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM universe_exclusion_snapshot WHERE snapshot_date = %s", (snapshot_date,))
        cur.executemany(
            "INSERT INTO universe_exclusion_snapshot (snapshot_date, ticker, name, market, security_group, axis) "
            "VALUES (%s, %s, %s, %s, %s, %s)", rows)
    return len(rows)


def _latest_snapshot(conn: Connection, before: date) -> tuple[date | None, set[str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT max(snapshot_date) FROM universe_exclusion_snapshot WHERE snapshot_date < %s", (before,))
        d = cur.fetchone()[0]
        if d is None:
            return None, set()
        cur.execute("SELECT ticker FROM universe_exclusion_snapshot WHERE snapshot_date = %s", (d,))
        return d, {r[0] for r in cur.fetchall()}


def _ever_in_stocks(conn: Connection, tickers: set[str]) -> dict[str, str | None]:
    """stocks 에 존재한 적 있는 티커 → security_group. UNRESOLVED 였던 행은 #199 유형이 아니라 '늦은 분류'(exclusion_diff)."""
    if not tickers:
        return {}
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, security_group FROM stocks WHERE ticker = ANY(%s)", (sorted(tickers),))
        return {r[0]: r[1] for r in cur.fetchall()}


def _ever_seen(conn: Connection, tickers: set[str], before: date) -> set[str]:
    """이전(before 미만) 배제/원본 스냅샷에 등장한 적 있는 티커 — '신규 상장' 은 어디에도 없던 종목만(재등장 왕복 차단, 리뷰 #223 2차)."""
    if not tickers:
        return set()
    with conn.cursor() as cur:
        cur.execute("SELECT ticker FROM universe_exclusion_snapshot WHERE snapshot_date < %s AND ticker = ANY(%s) "
                    "UNION SELECT ticker FROM universe_raw_snapshot WHERE snapshot_date < %s AND ticker = ANY(%s)",
                    (before, sorted(tickers), before, sorted(tickers)))
        return {r[0] for r in cur.fetchall()}


def _snapshot_diff(conn: Connection, *, snapshot_date: date, excluded: pd.DataFrame, raw_tickers: set[str] | None,
                   accept_exclusion_diff: bool, auto_accept: bool) -> tuple[date | None, list[str], list[str], ExclusionDiff]:
    """스냅샷 대조 + 3분류 + 거부 판정(공통). 반환 (prev_date, added, removed, diff). 거부면 UniverseGuardError(diff, prev_date)."""
    if accept_exclusion_diff and not auto_accept:
        raise ValueError("--accept-exclusion-diff 와 --strict-exclusion-diff 는 동시 지정 불가(의미 충돌)")
    prev_date, prev_set = _latest_snapshot(conn, snapshot_date)
    cur_set = set(excluded["ticker"]) if not excluded.empty else set()
    added, removed = sorted(cur_set - prev_set), sorted(prev_set - cur_set)
    diff = ExclusionDiff()
    if prev_date is not None and (added or removed):
        diff = classify_exclusion_diff(prev_set=prev_set, excluded=excluded, raw_tickers=raw_tickers,
                                       ever_in_stocks=_ever_in_stocks(conn, set(added)),
                                       ever_seen=_ever_seen(conn, set(added), snapshot_date))
        if accept_exclusion_diff and diff.has_199:
            t199 = [u["ticker"] for u in diff.unexplained_added if u.get("kind") == "199"]
            raise UniverseGuardError(
                f"guard(snapshot) #199 유형(security_group 확정 상태였던 기존 종목 → 신규 배제) {t199[:20]} 은 --accept-exclusion-diff 로 수용 불가 — "
                f"배제 의미 정정 + 상태 컬럼(#199) 선행", diff, prev_date)
        if not accept_exclusion_diff:
            if not auto_accept:
                raise UniverseGuardError(
                    f"guard(snapshot) 배제 집합 변동 (기준 {prev_date}, strict): +{added[:20]} -{removed[:20]} "
                    f"— --strict-exclusion-diff 해제 또는 원인 확인 후 --accept-exclusion-diff", diff, prev_date)
            if diff.unexplained:
                ua = [u["ticker"] for u in diff.unexplained_added]; ur = [u["ticker"] for u in diff.unexplained_removed]
                raise UniverseGuardError(
                    f"guard(snapshot) 배제 집합 변동 미설명 (기준 {prev_date}): +{ua[:20]} -{ur[:20]} "
                    f"(자동 수용 +{len(diff.added_new_listing)} -{len(diff.removed_delisted)}) "
                    f"— 조사 보고서(Slack) 확인 후 --accept-exclusion-diff 로 재실행", diff, prev_date)
    return prev_date, added, removed, diff


def preflight_exclusion_diff(conn: Connection, *, snapshot_date: date, excluded: pd.DataFrame, raw_tickers: set[str] | None,
                             accept_exclusion_diff: bool = False, auto_accept: bool = True) -> ExclusionDiff:
    """(#221, 리뷰 #223 4차) 어떤 쓰기(upsert·mark_delisted·스냅샷)보다 **먼저** 스냅샷 판정만 수행 — 잔여/strict 변동/#199 accept 는 여기서
    실패해 오폐지가 커밋될 경로를 없앤다. 스냅샷은 쓰지 않는다(verify_universe_after_load 가 적재 후 재확인·기록)."""
    return _snapshot_diff(conn, snapshot_date=snapshot_date, excluded=excluded, raw_tickers=raw_tickers,
                          accept_exclusion_diff=accept_exclusion_diff, auto_accept=auto_accept)[3]


def verify_universe_after_load(conn: Connection, *, snapshot_date: date, excluded: pd.DataFrame,
                               accept_exclusion_diff: bool = False, raw_tickers: set[str] | None = None,
                               auto_accept: bool = True) -> dict:
    """(#221) 스냅샷 대조: 변동을 exclusion_diff 로 3분류 — 상폐·신규 상장 배제는 자동 수용(auto_accept, 기본), 잔여가 있으면
    UniverseGuardError(diff 첨부). accept_exclusion_diff=True 는 사람이 원인 확인 후 수용 — 단 #199 유형(security_group 확정 상태였던
    기존 종목 → 신규 배제)은 accept 로도 거부(의미 정정·상태 컬럼 선행, #199 wake 절; UNRESOLVED 였던 행의 늦은 분류는 accept 가능).
    raw_tickers 미제공이면 removed 는 전부 잔여(보수). 원본 완전성(급감)은 __main__._raw_complete 가 쓰기 전에 fail-closed."""
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, name, security_group FROM stocks WHERE delisted_at IS NULL")
        active = cur.fetchall()

    # (a)
    groups = {g for _, _, g in active}
    bad = sorted(groups - _ALLOWED_ACTIVE_GROUPS)
    if bad:
        raise UniverseGuardError(f"guard(a) 활성 유니버스에 비허용 security_group 유입: {bad}")

    # (b)
    hits = [(t, n, ax) for t, n, g in active if (ax := classify_exclusion_axis(t, n, g)) is not None]
    if hits:
        raise UniverseGuardError(f"guard(b) 활성 유니버스에 적재 전 배제 축 종목 잔존 {len(hits)}건: {hits[:10]}")

    # (신규) 스냅샷 대조
    prev_date, added, removed, diff = _snapshot_diff(conn, snapshot_date=snapshot_date, excluded=excluded, raw_tickers=raw_tickers,
                                                     accept_exclusion_diff=accept_exclusion_diff, auto_accept=auto_accept)
    write_exclusion_snapshot(conn, snapshot_date, excluded)

    unresolved = sum(1 for _, _, g in active if g == UNRESOLVED)
    row_kept = sum(1 for _, _, g in active if g in ROW_KEPT_EXCLUDED_SECURITY_GROUPS)
    return {
        "active_after": len(active),
        "unresolved": unresolved,
        "row_kept_excluded": row_kept,
        "qualifying_pool": len(active) - unresolved - row_kept,
        "exclusion_added": added if prev_date is not None else [],
        "exclusion_removed": removed if prev_date is not None else [],
        "snapshot_prev_date": prev_date.isoformat() if prev_date else None,
        # (#221) 자동 수용 내역·잔여(성공·실패 행이 같은 키 모양 — ExclusionDiff.summary). accept 로 통과한 잔여(사람 수용)는
        # exclusion_accepted_unexplained=True 로 표시 — 호출자가 warnings 로 승격해 pipeline_runs 에 남긴다(리뷰 #223)
        **diff.summary(),
        "exclusion_accepted_unexplained": bool(diff.unexplained and accept_exclusion_diff),
    }
