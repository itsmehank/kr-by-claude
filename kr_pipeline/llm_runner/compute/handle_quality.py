# kr_pipeline/llm_runner/compute/handle_quality.py
"""handle_quality 결정론적 계산 — 후처리 (prompt 갱신 X).

spec §3. 핵심 잣대 = 변동성 수축·거래량 마름 (위치 아님). low cheat 보호.
경계 불명확 → 적용 안 함 + log (silent false-negative 방지).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from psycopg import Connection

log = logging.getLogger(__name__)

# 임계 (spec §3-2). 0.33 = O'Neil HMMS p.116 예외(고정), 0.80 = 재조정 대상.
DEEP_HANDLE_RATIO = 0.33
VOLUME_NOT_CONTRACTING_RATIO = 0.80
MIN_HANDLE_DAYS = 3
MIN_BASE_DAYS = 5
WEIGHT_POSITION_LOW_RATIO = 0.33


def _to_date(d) -> date:
    return d.date() if isinstance(d, datetime) else d


def compute_handle_quality(
    conn: Connection, symbol: str, classified_at, cls: dict,
) -> Optional[dict]:
    """handle_quality 발화 여부 결정론적 계산.

    Returns dict(fired, reasons, weights, metrics) 또는 None (미발화/적용불가).
    경계 불명확으로 적용 불가 시 log.info 로 reason 남김.
    """
    def skip(reason: str) -> None:
        log.info("[handle_quality] skipped symbol=%s reason=%s", symbol, reason)
        return None

    if cls.get("pattern") != "cup_with_handle":
        return skip(f"pattern={cls.get('pattern')}")
    if cls.get("pivot_basis") != "handle_high":
        return skip(f"pivot_basis={cls.get('pivot_basis')}")
    if cls.get("base_start_date") is None:
        return skip("base_start_date is None")
    if cls.get("pivot_price") is None or cls.get("base_depth_pct") is None:
        return skip("pivot_price or base_depth_pct missing")

    base_depth_pct = float(cls["base_depth_pct"])
    if base_depth_pct <= 0:
        return skip(f"base_depth_pct={base_depth_pct} <= 0")

    handle_high = float(cls["pivot_price"])
    base_start = _to_date(cls["base_start_date"])
    classified_date = _to_date(classified_at)

    # daily_prices + daily_indicators 조인해 base_start ~ classified_at 범위.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.date, p.high, p.low, p.close, p.volume,
                   i.sma_50, COALESCE(i.distribution_day_flag, FALSE)
              FROM daily_prices p
              LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = %s AND p.date >= %s AND p.date < %s
             ORDER BY p.date
            """,
            (symbol, base_start, classified_date),
        )
        rows = cur.fetchall()

    if len(rows) < MIN_BASE_DAYS + MIN_HANDLE_DAYS:
        return skip(f"window too short ({len(rows)} rows)")

    # 컵 바닥 (low 최소) → 그 이후 오른쪽 림 (high >= handle_high 첫 거래일).
    # 단순 "첫 high>=handle_high" 는 컵 왼쪽 림을 잡으므로 cup_bottom 이후로 탐색.
    cup_bottom_idx = min(range(len(rows)), key=lambda i: float(rows[i][2]))  # rows[i][2] = low
    right_rim_idx = None
    for idx in range(cup_bottom_idx, len(rows)):
        if float(rows[idx][1]) >= handle_high:  # rows[idx][1] = high
            right_rim_idx = idx
            break
    if right_rim_idx is None:
        return skip("right rim not recovered after cup bottom")

    base_rows = rows[:right_rim_idx]
    handle_rows = rows[right_rim_idx:]
    if len(handle_rows) < MIN_HANDLE_DAYS:
        return skip(f"handle window too short ({len(handle_rows)} days)")
    if len(base_rows) < MIN_BASE_DAYS:
        return skip(f"base window too short ({len(base_rows)} days)")

    handle_low = min(float(r[2]) for r in handle_rows)
    base_low = float(cls["base_low"]) if cls.get("base_low") is not None else \
        min(float(r[2]) for r in base_rows)
    base_high = float(cls["base_high"]) if cls.get("base_high") is not None else \
        max(float(r[1]) for r in base_rows)

    # (A) deep handle — 깊이-퍼센트 비 (통일 공식 §3-2)
    handle_depth_pct = (handle_high - handle_low) / handle_high * 100.0
    ratio_a = handle_depth_pct / base_depth_pct
    fired_a = ratio_a > DEEP_HANDLE_RATIO

    # (B) volume not contracting
    avg_base_vol = sum(float(r[4]) for r in base_rows) / len(base_rows)
    avg_handle_vol = sum(float(r[4]) for r in handle_rows) / len(handle_rows)
    ratio_b = (avg_handle_vol / avg_base_vol) if avg_base_vol else 0.0
    fired_b = ratio_b > VOLUME_NOT_CONTRACTING_RATIO

    # (분배) handle 구간 distribution day
    dist_days = sum(1 for r in handle_rows if r[6])
    fired_dist = dist_days >= 1

    fired = fired_a or fired_b or fired_dist
    if not fired:
        log.info(
            "[handle_quality] checked-not-fired symbol=%s ratio_a=%.3f ratio_b=%.3f dist=%d",
            symbol, ratio_a, ratio_b, dist_days,
        )
        return None

    # 가중치 (E) 위치 / (F) MA50 — 단독 트리거 아님, reasons 와 함께 기록만.
    denom = (base_high - base_low)
    handle_position_low = denom > 0 and ((handle_low - base_low) / denom) < WEIGHT_POSITION_LOW_RATIO
    last = handle_rows[-1]
    last_close, last_ma50 = float(last[3]), last[5]
    handle_below_ma50 = last_ma50 is not None and last_close < float(last_ma50)

    reasons = []
    if fired_a: reasons.append("deep_handle")
    if fired_b: reasons.append("volume_not_contracting")
    if fired_dist: reasons.append("distribution_in_handle")
    weights = []
    if handle_position_low: weights.append("handle_position_low")
    if handle_below_ma50: weights.append("handle_below_ma50")

    return {
        "fired": True,
        "reasons": reasons,
        "weights": weights,
        "metrics": {
            "ratio_a": round(ratio_a, 3),
            "ratio_b": round(ratio_b, 3),
            "distribution_days": dist_days,
            "handle_start": _to_date(handle_rows[0][0]).isoformat(),
            "handle_end": _to_date(handle_rows[-1][0]).isoformat(),
            "handle_high": round(handle_high, 2),
            "handle_low": round(handle_low, 2),
        },
    }
