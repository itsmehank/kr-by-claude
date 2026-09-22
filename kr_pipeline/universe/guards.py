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
from kr_pipeline.universe.transform import classify_exclusion_axis


class UniverseGuardError(ValueError):
    pass


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


def verify_universe_after_load(conn: Connection, *, snapshot_date: date, excluded: pd.DataFrame,
                               accept_exclusion_diff: bool = False) -> dict:
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
    prev_date, prev_set = _latest_snapshot(conn, snapshot_date)
    cur_set = set(excluded["ticker"]) if not excluded.empty else set()
    added, removed = sorted(cur_set - prev_set), sorted(prev_set - cur_set)
    if prev_date is not None and (added or removed) and not accept_exclusion_diff:
        raise UniverseGuardError(
            f"guard(snapshot) 배제 집합 변동 미설명 (기준 {prev_date}): +{added[:20]} -{removed[:20]} "
            f"— 원인 확인 후 --accept-exclusion-diff 로 재실행")
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
    }
