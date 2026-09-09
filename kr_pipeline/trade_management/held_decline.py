"""(#164 2026-09-09) 보유 종목 약세 매도 신호 — 결정론, 신규 숫자 0.

결합식(전문가 사양, book-mandated — TTLC Ch.9 / TLSMW Ch.5 / HMMS Ch.10 p.268 #2):
  held_decline = P1(maturity_ok) ∧ (T-A ta_max_decline_now ∨ TA-d ta_d_daily_max_decline_now)
  - P1 재사용 사유: baseline 부재 시 첫 하락이 자동으로 최대가 된다 — "상승 이래(since the
    advance began)" 는 확립된 상승을 전제 [design-judgment, 기록].
  - 8주 억제 **미적용**: 하락 신호에 리더십 예외 없음(Minervini "실적 직후라도") [book-mandated].
  - G0(10주선 아래) **미적용**: 책 전제 아님 — 신호 취지가 "선 위에서도 나가라".
  - left_censored / no_transition / quality_flag → fired=None(미정의, 미발화 — #169 동조).
  - null 트리거는 미평가(#157 규약) — 나머지로만 OR. 둘 다 미평가면 False(자격 없음).

우선순위(러너·백테스트 공통): 스탑 > 약세(decline) > 강세(climax) > 절반매도(5B). 같은 날 복수
성립 시 reason 라벨은 앞선 것, 나머지는 기록에 병기(climax_also_fired / exits[].also).

산술은 held_climax.gates_from_series 가 낸 같은 gates 를 소비한다(판정 함수 하나 — production
러너와 backtest portfolio 가 같은 `evaluate_held_decline` 호출, 파리티는 구조로 보장).
`decline_metrics` 는 Slack 권고문용 **echo 값**(당일·당주 하락률과 baseline 최대)이며 판정에
관여하지 않는다 — 판정은 compute_daily_extremes / compute_topping_gates 의 불리언만.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from psycopg import Connection

from api.services.payload_builder import _anchor_baseline_start
from kr_pipeline.trade_management.held_climax import fetch_series, gates_from_series

HELD_DECLINE_SIGNALS = ("ta_max_decline_now", "ta_d_daily_max_decline_now")


@dataclass(frozen=True)
class HeldDeclineDecision:
    fired: bool | None          # None = 판정 불능(결측 모드)
    hold_days: int
    signals: tuple[str, ...]    # True 인 신호 키(T-A / TA-d)
    mode: str                   # anchored | no_transition | left_censored | quality
    anchor_week: str | None
    weeks_since: int | None
    maturity_ok: bool | None
    ta_max_decline_now: bool | None
    ta_d_daily_max_decline_now: bool | None


@dataclass(frozen=True)
class DeclineMetrics:
    """권고문 echo(판정 비관여). None = 해당 값 산출 불가(상승일/상승주·결측)."""
    today_decline_pct: float | None
    baseline_max_daily_decline_pct: float | None
    week_decline_pct: float | None
    baseline_max_weekly_decline_pct: float | None


def evaluate_held_decline(gates: dict, entry_date: date, as_of: date) -> HeldDeclineDecision:
    """순수 결합식. gates = held_climax.gates_from_series(...) 출력."""
    hold_days = (as_of - entry_date).days
    if gates.get("left_censored"):
        mode = "left_censored"
    elif gates.get("no_transition"):
        mode = "no_transition"
    elif gates.get("quality_flag"):
        mode = "quality"
    else:
        mode = "anchored"
    p1 = gates.get("maturity_ok")
    ta, tad = gates.get("ta_max_decline_now"), gates.get("ta_d_daily_max_decline_now")
    signals = tuple(k for k in HELD_DECLINE_SIGNALS if gates.get(k) is True)
    if mode != "anchored" or p1 is None:
        fired = None
    else:
        fired = bool(p1 and signals)
    return HeldDeclineDecision(
        fired=fired, hold_days=hold_days, signals=signals, mode=mode,
        anchor_week=gates.get("anchor_week"), weeks_since=gates.get("weeks_since"),
        maturity_ok=p1, ta_max_decline_now=ta, ta_d_daily_max_decline_now=tad,
    )


def decline_metrics(weekly: list[dict], daily: list[dict], anchor_week: str | None) -> DeclineMetrics:
    """echo 전용 — 당일/당주 하락률(prev_close 분모)과 baseline(anchor 주 첫 거래일 / anchor 주 이후)
    내 하락일·하락주 최대. compute_daily_extremes 의 연속 세션(zero-bar 갭 제외) 규약을 따르되
    판정 값은 내지 않는다. anchor 부재면 전부 None."""
    if anchor_week is None:
        return DeclineMetrics(None, None, None, None)
    bl_iso = _anchor_baseline_start(anchor_week).isoformat()
    # 일간
    downs: list[float] = []
    today_down: float | None = None
    prev_close: float | None = None
    gap = False
    last_idx = len(daily) - 1
    for i, row in enumerate(daily):
        if row.get("zero_bar"):
            gap = True
            continue
        close = row["close"]
        if (prev_close is not None and prev_close > 0 and close is not None
                and row["date"] >= bl_iso and not gap):
            chg = (prev_close - close) / prev_close * 100
            if chg > 0:
                downs.append(chg)
                if i == last_idx:
                    today_down = chg
        prev_close = close
        gap = False
    # 주간(zero-bar 제외 입력, 직전 주 = 직전 행 — compute_topping_gates T-A 와 동일)
    closes = [w["close"] for w in weekly]
    n = len(weekly)
    start = next((i for i, w in enumerate(weekly) if w["week_end"] >= anchor_week), n)
    wdowns: list[float] = []
    week_down: float | None = None
    for i in range(max(start, 1), n):
        prev = closes[i - 1]
        if prev is None or prev <= 0 or closes[i] is None or closes[i] >= prev:
            continue
        chg = (prev - closes[i]) / prev * 100
        wdowns.append(chg)
        if i == n - 1:
            week_down = chg
    return DeclineMetrics(
        today_decline_pct=today_down,
        baseline_max_daily_decline_pct=max(downs) if downs else None,
        week_decline_pct=week_down,
        baseline_max_weekly_decline_pct=max(wdowns) if wdowns else None,
    )


def compute_held_decline(conn: Connection, symbol: str, as_of: date, entry_date: date
                         ) -> tuple[HeldDeclineDecision, DeclineMetrics]:
    """production 편의 함수: DB 조회 → 산술 → 결합식 + echo."""
    weekly, daily = fetch_series(conn, symbol, as_of)
    gates = gates_from_series(weekly, daily)
    return evaluate_held_decline(gates, entry_date, as_of), decline_metrics(weekly, daily, gates["anchor_week"])
