"""2-F failed_breakout 계산 — K=5 + 지속성 (spec §5).

재조정 대상: K=5, 연속 2일. 사례 1건 기반 시작값.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from psycopg import Connection

log = logging.getLogger(__name__)

K_DAYS = 5
CONSECUTIVE_BELOW = 2


def _to_date(d) -> date:
    return d.date() if isinstance(d, datetime) else d


def compute_failed_breakout(
    conn: Connection, symbol: str, classified_at, pivot_price, base_start_date,
) -> Optional[dict]:
    """pivot 돌파 (close >= pivot) 후 K=5 거래일 내 실패 여부.

    탐색 범위 = [base_start_date, classified_at) — *이번 base 구간으로 한정*.
    전체 역사에서 D0 를 찾으면 과거의 무관한 돌파를 잡으므로 (버그) base_start 필수.

    (P1) 연속 2일 이상 close < pivot, OR
    (P2) D1~D5 전체에서 close >= pivot 인 거래일 0회.
    Returns dict(fired, K_days, trigger, D0_date, consecutive_below,
                 max_close_in_window, pivot) 또는 None.
    """
    if pivot_price is None:
        log.info("[failed_breakout] skipped symbol=%s reason=pivot_price is None", symbol)
        return None
    if base_start_date is None:
        log.info("[failed_breakout] skipped symbol=%s reason=base_start_date is None", symbol)
        return None
    pivot = float(pivot_price)
    classified_date = _to_date(classified_at)
    base_start = _to_date(base_start_date)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, close FROM daily_prices
             WHERE ticker = %s AND date >= %s AND date < %s
             ORDER BY date
            """,
            (symbol, base_start, classified_date),
        )
        rows = cur.fetchall()

    if not rows:
        return None

    # D0 = close >= pivot 인 최초 거래일.
    d0_idx = None
    for idx, (_, close) in enumerate(rows):
        if float(close) >= pivot:
            d0_idx = idx
            break
    if d0_idx is None:
        return None  # 돌파 없음

    window = rows[d0_idx + 1: d0_idx + 1 + K_DAYS]  # D1~D5
    # window 가 K=5 미만 (D0 가 데이터 끝 근처) 이면 P2 가 민감해질 수 있음 — Phase 2 재조정 대상
    if not window:
        return None

    closes = [float(c) for _, c in window]

    # (P1) 연속 below
    max_consecutive = 0
    cur_run = 0
    for c in closes:
        if c < pivot:
            cur_run += 1
            max_consecutive = max(max_consecutive, cur_run)
        else:
            cur_run = 0
    fired_p1 = max_consecutive >= CONSECUTIVE_BELOW

    # (P2) 회복 0회
    recoveries = sum(1 for c in closes if c >= pivot)
    fired_p2 = recoveries == 0

    if not (fired_p1 or fired_p2):
        return None

    if fired_p1 and fired_p2:
        trigger = "both"
    elif fired_p1:
        trigger = "P1"
    else:
        trigger = "P2"

    return {
        "fired": True,
        "K_days": K_DAYS,
        "trigger": trigger,
        "D0_date": _to_date(rows[d0_idx][0]).isoformat(),
        "consecutive_below": max_consecutive,
        "max_close_in_window": round(max(closes), 2),
        "pivot": round(pivot, 2),
    }
