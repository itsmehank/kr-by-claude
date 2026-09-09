"""(항목 ③ 2026-09-08) 보유 종목 climax 강세 매도 판정 — 결정론, 신규 숫자 0.

결합식(전문가 사양):
  held_climax = P1(maturity_ok) ∧ P2(p2_accel_ok) ∧ (T1∨T2∨T3∨T4∨T5∨T6) ∧ scope_active
                ∧ NOT suppressed
  suppressed  = (as_of − entry_date) < TRADE_HOLD_MIN_DAYS(56)
      — §6.1 E1(리더십 배제, LLM 전용)의 결정론 대용. HMMS 8주 규칙 재사용
        [design-judgment: book 규칙의 대용 적용].
  left_censored / no_transition / quality_flag → fired=None(미정의, 미발화).

LLM 전용이라 **미적용**되는 §6.1 판정(plan 문서 결측 목록): E1 base 서수 리더십 배제 ·
P1 후기 완화(3rd+ base → 12주) · supporting SMA200 ≥70% pass/fail · §6.2 T-C "prolonged".
null 트리거는 미평가(#157 규약) — 나머지 트리거로만 OR.

산술은 A 프롬프트 payload 와 동일 순수 함수(find_anchor·compute_climax_gates·
compute_daily_extremes)를 재사용한다. build_payload 전체 호출 금지(사양). production 은
`fetch_series` 로 DB 에서 시계열을 읽고, backtest 는 미리 적재한 전 이력을 날짜로 잘라
같은 `gates_from_series` 에 넣는다 — 판정 함수가 하나이므로 parity 는 구조로 보장된다.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date

from psycopg import Connection

from api.services.payload_builder import (
    _DAILY_OHLCV_COLS,
    _anchor_baseline_start,
    _daily_row,
    _fetch_weekly_full,
)
from kr_pipeline.common.thresholds import TRADE_HOLD_MIN_DAYS
from kr_pipeline.llm_runner.compute.climax_topping import (
    _DAILY_KEYS,
    compute_climax_gates,
    compute_daily_extremes,
    compute_topping_gates,
    find_anchor,
)

HELD_CLIMAX_TRIGGERS = (
    "t1_max_spread_now", "t2_max_volume_now", "t3_gap_up_today", "t4_ok",
    "t5_daily_max_up_now", "t6_daily_max_spread_now",
)
_DAILY_TAIL = 20  # T3/T4 입력 = 최근 20 거래일(payload_builder daily_ohlcv[-20:] 과 동일)


@dataclass(frozen=True)
class HeldClimaxDecision:
    fired: bool | None          # None = 판정 불능(결측 모드)
    suppressed: bool
    hold_days: int
    triggers: tuple[str, ...]   # True 인 트리거 키
    mode: str                   # anchored | no_transition | left_censored | quality
    anchor_week: str | None
    weeks_since: int | None
    maturity_ok: bool | None
    p2_accel_ok: bool | None
    scope_active: bool | None


def fetch_daily_flagged(conn: Connection, ticker: str, on_date: date) -> list[dict]:
    """일봉 전 이력(≤ on_date) — zero-bar 포함·표시, adj_hl 표시 (payload_builder
    _fetch_daily_since 와 같은 행 규약, 범위만 전 이력)."""
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT {_DAILY_OHLCV_COLS},
                   (open = 0 AND high = 0 AND low = 0 AND volume = 0) AS zero_bar,
                   (adj_high IS NOT NULL AND adj_low IS NOT NULL)     AS adj_hl
              FROM daily_prices
             WHERE ticker = %s AND date <= %s
             ORDER BY date ASC
        """, (ticker, on_date))
        rows = cur.fetchall()
    return [{**_daily_row(r), "zero_bar": bool(r[6]), "adj_hl": bool(r[7])} for r in rows]


def fetch_series(conn: Connection, symbol: str, as_of: date) -> tuple[list[dict], list[dict]]:
    """production 경로: (주봉 전 이력 zero-bar 제외+플래그, 일봉 전 이력 플래그 포함)."""
    return _fetch_weekly_full(conn, symbol, as_of), fetch_daily_flagged(conn, symbol, as_of)


def slice_upto(weekly: list[dict], daily: list[dict], as_of: date) -> tuple[list[dict], list[dict]]:
    """미리 적재한 전 이력을 as_of 이하로 절단(backtest 용). 두 목록 다 오름차순 가정."""
    iso = as_of.isoformat()
    wk_keys = [w["week_end"] for w in weekly]
    dl_keys = [d["date"] for d in daily]
    return weekly[:bisect_right(wk_keys, iso)], daily[:bisect_right(dl_keys, iso)]


def gates_from_series(weekly: list[dict], daily: list[dict]) -> dict:
    """§6.1 산술 전부(anchor·P1·P2·T1~T6·scope) + (#164) §6.2 주간 T-A `ta_max_decline_now`
    — payload_builder.build_payload 의 climax/topping 부분과 같은 입력 구성으로 재현.
    반환에 anchor 3모드 키 포함. T-A 는 compute_topping_gates 에서 그 키만 가져온다(분배일
    카운트 입력 None — 보유 판정은 anchor 의존 하락 극값만 소비, td_dist_ok 미사용)."""
    anchor = find_anchor(weekly)
    daily20 = [d for d in daily if not d.get("zero_bar")][-_DAILY_TAIL:]
    climax = compute_climax_gates(weekly, daily20, anchor)
    if anchor["left_censored"] or anchor["no_transition"] or climax["quality_flag"]:
        ext = dict.fromkeys(_DAILY_KEYS)
    else:
        bl = _anchor_baseline_start(anchor["anchor_week"])
        bl_iso = bl.isoformat()
        prior = [d for d in daily if d["date"] < bl_iso][-1:]
        hist = prior + [d for d in daily if d["date"] >= bl_iso]
        ext = compute_daily_extremes(hist, bl_iso, anchor, quality_flag=climax["quality_flag"])
    ta = (None if anchor["left_censored"]
          else compute_topping_gates(weekly, None, anchor)["ta_max_decline_now"])
    return {**climax, **ext, "ta_max_decline_now": ta, "anchor_week": anchor["anchor_week"],
            "left_censored": anchor["left_censored"], "no_transition": anchor["no_transition"],
            "weeks_since": anchor["weeks_since"]}


def compute_held_gates(conn: Connection, symbol: str, as_of: date) -> dict:
    """production 편의 함수: DB 조회 → gates_from_series. (#164) 러너가 하루 1회 호출해 climax·
    decline 두 결합식에 같은 gates 를 공급한다(조회 1회)."""
    weekly, daily = fetch_series(conn, symbol, as_of)
    return gates_from_series(weekly, daily)


def evaluate_held_climax(gates: dict, entry_date: date, as_of: date,
                         hold_min_days: int = TRADE_HOLD_MIN_DAYS) -> HeldClimaxDecision:
    """순수 결합식. gates = gates_from_series(...) 출력."""
    hold_days = (as_of - entry_date).days
    suppressed = hold_days < hold_min_days
    if gates.get("left_censored"):
        mode = "left_censored"
    elif gates.get("no_transition"):
        mode = "no_transition"
    elif gates.get("quality_flag"):
        mode = "quality"
    else:
        mode = "anchored"
    triggers = tuple(k for k in HELD_CLIMAX_TRIGGERS if gates.get(k) is True)
    p1, p2, scope = gates.get("maturity_ok"), gates.get("p2_accel_ok"), gates.get("scope_active")
    if mode != "anchored" or p1 is None or p2 is None or scope is None:
        fired = None
    else:
        fired = bool(p1 and p2 and triggers and scope and not suppressed)
    return HeldClimaxDecision(
        fired=fired, suppressed=suppressed, hold_days=hold_days, triggers=triggers, mode=mode,
        anchor_week=gates.get("anchor_week"), weeks_since=gates.get("weeks_since"),
        maturity_ok=p1, p2_accel_ok=p2, scope_active=scope,
    )


def compute_held_climax(conn: Connection, symbol: str, as_of: date, entry_date: date,
                        hold_min_days: int = TRADE_HOLD_MIN_DAYS) -> HeldClimaxDecision:
    """production 편의 함수: DB 조회 → 산술 → 결합식."""
    weekly, daily = fetch_series(conn, symbol, as_of)
    return evaluate_held_climax(gates_from_series(weekly, daily), entry_date, as_of, hold_min_days)
