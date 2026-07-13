# kr_pipeline/llm_runner/compute/gate_precompute.py
"""(#22) B(evaluate_pivot_trigger) 정량 게이트 코드 선계산.

순수 함수 — DB 접근 없음. build_for_5b 가 payload 조각(변환 완료된 dict)으로
호출해 `computed_gates` 로 payload 에 싣는다. 프롬프트는 이 값을 authoritative
로 소비 (재계산 금지). 결정 규칙(go_now/wait/abort 매핑)과 비산술 재량(거래량
동반의 의미 해석, squat 회복 여지, soon-after 판단)은 LLM 잔류 — 코드는 측정만.

null 규약: 입력 결측 → 해당 게이트 None. 프롬프트 규약상 go_now 에 필요한
게이트가 None 이면 go_now 금지(보수). distribution_day_flag None(미산출)은
분배일로 세지 않는다 — 기존 §3 규약(handle_quality COALESCE)과 동일.

소스 규약: 일중값(range 위치·spread·저가)은 20d 리스트 마지막 행, close/volume/
sma 게이트는 current_metrics — halt 직후 두 소스의 날짜가 다를 수 있어(#35 리뷰)
`ohlcv_last_date` 로 노출한다.
"""
from __future__ import annotations

from datetime import date, timedelta

from kr_pipeline.common.thresholds import (
    BREAKOUT_VOL_FLOOR,
    BREAKOUT_VOL_WAIT_FLOOR,
    MARKET_DIST_DEMOTION_COUNT_25S,
    SMA50_BREACH_RATIO,
    SPREAD_AVG_MIN_ROWS,
    SPREAD_AVG_WINDOW_DAYS,
    SPREAD_WIDE_LOOSE_MULT,
    STOCK_DISTRIBUTION_ABORT_COUNT,
    STOCK_DISTRIBUTION_ABORT_WINDOW_CAL_CAP,
    STOCK_DISTRIBUTION_ABORT_WINDOW_DAYS,
    STOCK_DISTRIBUTION_CLEAN_WINDOW_CAL_CAP,
    STOCK_DISTRIBUTION_CLEAN_WINDOW_DAYS,
    TT_MARGINAL_DEMOTION_COUNT,
)
from kr_pipeline.llm_runner.compute.tt_marginal import tt_marginal_summary

_UPPER_THIRD = 2.0 / 3.0  # "상단/중단 1/3" 정의값 (임계 아님 — 밴드 정의)
_LOWER_THIRD = 1.0 / 3.0


def _dist_count(rows: list[dict], window: int, cal_cap_days: int) -> int | None:
    """최근 window 거래행의 분배일 수.

    - 행 수 < window → None (관측 창 미달 — 관측 없는 통과 금지, #37 리뷰).
    - 마지막 행 기준 cal_cap_days 캘린더보다 오래된 행은 stale 로 미계수
      (20d 리스트는 halt 행 제외라 '최근 N 거래행'이 halt 를 넘어 주 단위
      과거로 늘어질 수 있음 — #37 리뷰).
    """
    if len(rows) < window:
        return None
    last_date = date.fromisoformat(rows[-1]["date"])
    cutoff = last_date - timedelta(days=cal_cap_days)
    return sum(
        1
        for r in rows[-window:]
        if r.get("distribution_day_flag") is True
        and date.fromisoformat(r["date"]) >= cutoff
    )


def compute_gates(
    *,
    ohlcv_20d: list[dict],
    current_metrics: dict,
    prior_analysis: dict,
    market_context: dict,
    conditions_detail: dict,
) -> dict:
    """B 프롬프트 §3.1/§3.2/§3.5 정량 게이트의 결정론 선계산.

    인자는 build_for_5b 가 만드는 payload 조각과 같은 형태(직렬화 직전 dict).
    """
    close = current_metrics.get("close")
    volume_ratio = current_metrics.get("volume_ratio")
    sma_50 = current_metrics.get("sma_50")
    sma_21 = current_metrics.get("sma_21")
    pivot = prior_analysis.get("pivot_price")
    base_low = prior_analysis.get("base_low")

    last = ohlcv_20d[-1] if ohlcv_20d else None

    # --- 가격/거래량 (current_metrics 소스) ---
    price_above_pivot = (
        close > pivot if close is not None and pivot is not None else None
    )
    if volume_ratio is None:
        volume_band = None
    elif volume_ratio > BREAKOUT_VOL_FLOOR:
        volume_band = "pass"
    elif volume_ratio >= BREAKOUT_VOL_WAIT_FLOOR:
        volume_band = "wait_band"
    else:
        volume_band = "below"

    close_below_sma50_breach = (
        close < sma_50 * SMA50_BREACH_RATIO
        if close is not None and sma_50 is not None
        else None
    )
    close_below_sma21 = (
        close < sma_21 if close is not None and sma_21 is not None else None
    )

    # --- 일중 range 위치 / spread (20d 마지막 행 소스) ---
    close_range_pos = None
    close_upper_third = None
    close_middle_third = None
    if last is not None:
        rng = last["high"] - last["low"]
        if rng > 0:
            close_range_pos = (last["close"] - last["low"]) / rng
            close_upper_third = close_range_pos >= _UPPER_THIRD
            close_middle_third = _LOWER_THIRD <= close_range_pos < _UPPER_THIRD
        else:
            # range 0 = 단일가 잠금 봉 (상한가/하한가 lock, high==low==close).
            # 전일 종가 대비 방향으로 확정 — 위 잠금(상한가)만 상단 마감(1.0),
            # 아래 잠금(하한가)은 하단 마감(0.0). 무방향 상단 확정은 하한가(최약세 봉)를
            # '일중 약세 없음'으로 위장시킨다 (#37 재리뷰). 전일 부재·보합 잠금은 null 유지.
            prev_close = ohlcv_20d[-2]["close"] if len(ohlcv_20d) >= 2 else None
            if prev_close is not None and last["close"] > prev_close:
                close_range_pos = 1.0
                close_upper_third = True
                close_middle_third = False
            elif prev_close is not None and last["close"] < prev_close:
                close_range_pos = 0.0
                close_upper_third = False
                close_middle_third = False

    spread_ratio = None
    spread_wide_loose = None
    if last is not None:
        prev = ohlcv_20d[:-1][-SPREAD_AVG_WINDOW_DAYS:]
        if len(prev) >= SPREAD_AVG_MIN_ROWS:
            avg_range = sum(r["high"] - r["low"] for r in prev) / len(prev)
            if avg_range > 0:
                spread_ratio = (last["high"] - last["low"]) / avg_range
                spread_wide_loose = spread_ratio > SPREAD_WIDE_LOOSE_MULT

    # --- 분배일 창 (20d 리스트 소스, flag None=미계수) ---
    dist_3 = _dist_count(
        ohlcv_20d,
        STOCK_DISTRIBUTION_CLEAN_WINDOW_DAYS,
        STOCK_DISTRIBUTION_CLEAN_WINDOW_CAL_CAP,
    )
    dist_5 = _dist_count(
        ohlcv_20d,
        STOCK_DISTRIBUTION_ABORT_WINDOW_DAYS,
        STOCK_DISTRIBUTION_ABORT_WINDOW_CAL_CAP,
    )

    low_below_base_low = (
        last["low"] < base_low
        if last is not None and base_low is not None
        else None
    )
    close_below_base_low = (
        close < base_low
        if close is not None and base_low is not None
        else None
    )

    # --- §3.5 사유-독립 회복 게이트 (D4 거울 갭 폐쇄 — watch_reason 무관 AND) ---
    status = market_context.get("current_status")
    mkt_dist = market_context.get("distribution_day_count_last_25_sessions")
    if status is None or mkt_dist is None:
        market_recovery_ok = None
    else:
        market_recovery_ok = (
            status == "confirmed_uptrend"
            and mkt_dist < MARKET_DIST_DEMOTION_COUNT_25S
        )

    if conditions_detail:
        # 계수·결측 규약은 tt_marginal_summary 가 단일 정의 — A 측(payload_builder
        # conditions_summary)과 공용 (#38 재리뷰: 별도 구현이 규약을 갈라 A 강등 ↔
        # B 회복의 '정확한 역'을 깨뜨렸던 것의 구조적 재발 방지).
        s = tt_marginal_summary(conditions_detail)
        tt_all_passed = s["all_passed"]
        tt_marginal_count = s["marginal_count"]
        if tt_all_passed is False:
            tt_recovery_ok = False  # 탈락 확정 — margin 결측과 무관하게 회복 불가
        elif tt_all_passed is None or tt_marginal_count is None:
            tt_recovery_ok = None
        else:
            tt_recovery_ok = tt_marginal_count < TT_MARGINAL_DEMOTION_COUNT
    else:
        tt_all_passed = None
        tt_marginal_count = None
        tt_recovery_ok = None

    return {
        "ohlcv_last_date": last["date"] if last is not None else None,
        "price_above_pivot": price_above_pivot,
        "volume_ratio": volume_ratio,
        "volume_band": volume_band,
        "close_range_pos": (
            round(close_range_pos, 4) if close_range_pos is not None else None
        ),
        "close_upper_third": close_upper_third,
        "close_middle_third": close_middle_third,
        "spread_ratio_vs_avg": (
            round(spread_ratio, 4) if spread_ratio is not None else None
        ),
        "spread_wide_loose": spread_wide_loose,
        "dist_days_last_3": dist_3,
        "no_dist_3d": (dist_3 == 0) if dist_3 is not None else None,
        "dist_days_last_5": dist_5,
        "dist_3plus_5d": (
            dist_5 >= STOCK_DISTRIBUTION_ABORT_COUNT
            if dist_5 is not None
            else None
        ),
        "low_below_base_low": low_below_base_low,
        "close_below_base_low": close_below_base_low,
        "close_below_sma50_breach": close_below_sma50_breach,
        "close_below_sma21": close_below_sma21,
        "market_dist_count": mkt_dist,
        "market_recovery_ok": market_recovery_ok,
        "tt_all_passed": tt_all_passed,
        "tt_marginal_count": tt_marginal_count,
        "tt_recovery_ok": tt_recovery_ok,
    }
