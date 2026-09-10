"""포트폴리오 단위 시뮬레이션 — 사전등록 2026-07-02 portfolio-sim. 읽기전용·결정론.

규칙 출처: Minervini/O'Neil 에이전트 v1.1 + 구현측 보완 §4 (사전등록 문서 참조).
DB-free 코어(run_portfolio) + DB 로더(load_ticker_data) 분리.

  python -m kr_pipeline.backtest.portfolio    # 기본: 표본 A, 2021~2025 윈도 (불변)
  # 독립 검증 구간(이슈 #52, 표본 C 동결 후 — prereg 승인 전 실행 금지):
  python -m kr_pipeline.backtest.portfolio --sample=c \
      --start=2017-01-01 --end=2021-06-30 \
      --watch-start=2017-07-01 --watch-end=2020-12-31
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from math import inf

from kr_pipeline.backtest import phases as ph
from kr_pipeline.backtest.backfill import BT_TABLE
from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.profitability_run import DOWN_PHASES, _market_of
from kr_pipeline.backtest.refinement import cost_pct, COMMISSION_RT
from kr_pipeline.backtest.trigger_sim import (
    DayBar, WatchRow, load_watchlist, load_daily_series, load_index_series,
    _active_row,
)
from kr_pipeline.common.thresholds import (
    PILOT_CONSEC_STOP_LOCK, PILOT_OFF_HIGH_MAX_PCT, PILOT_OFF_HIGH_MIN_PCT,
    STATUS_DIST_COUNT_FOR_FTD_INVALIDATION,
    ENTRY_WEIGHT_PCT_MAX,
    SIZING_PILOT_FRAC,
    SIZING_RISK_PER_TRADE,
    TRADE_STOP_INITIAL_PCT,
    TRADE_HOLD_MIN_DAYS,
    SELL_HALF_ENABLED,
)
from kr_pipeline.llm_runner.compute.trigger_gate import evaluate as gate_evaluate
from kr_pipeline.trade_management.held_climax import (
    evaluate_held_climax, fetch_daily_flagged, gates_from_series, slice_upto,
)
from kr_pipeline.common.price_source import price_source
from kr_pipeline.ohlcv.delisted_adj import LIQ_WINDOW_DAYS
from kr_pipeline.trade_management.held_decline import evaluate_held_decline
from kr_pipeline.trade_management.sell_half import SellHalfState, evaluate_sell_half

START, END = date(2021, 1, 1), date(2025, 6, 30)   # 매매 윈도(신호는 ~2024 분류)
WATCH_START, WATCH_END = date(2021, 1, 1), date(2024, 12, 31)
_COMM = COMMISSION_RT / 2   # 편도 수수료 %p (왕복 0.03 의 절반)


@dataclass
class TickerData:
    market: str
    bars: list[DayBar]
    watch_rows: list[WatchRow]
    rs_by_date: dict            # date -> rs_rating | None
    phase_by_date: dict         # date -> phase str (현행 사다리)
    phase_variant_by_date: dict = field(default_factory=dict)  # v3.2 변형 사다리
    bottoming_by_date: dict = field(default_factory=dict)      # v4.1 (active, episode)
    ftd_valid_by_date: dict = field(default_factory=dict)      # v4.2 증액 (i)
    phase_a53_by_date: dict = field(default_factory=dict)      # Arm-53 사다리 (LOCKED)
    pilot54_ok_by_date: dict = field(default_factory=dict)     # Arm-54 3중 필터 (E2)
    pilot54_flags_by_date: dict = field(default_factory=dict)  # (mp, rs, band) 성분별
    mkt_dist_by_date: dict = field(default_factory=dict)       # 시장 분배일 카운트 (E1)
    ftd_event_by_date: dict = field(default_factory=dict)      # FTD 이벤트 당일 (E5 해제)
    # (항목 ③) 보유 climax 매도용 전 이력 — 주봉(zero-bar 제외+플래그)·일봉(플래그 포함),
    # 날짜별 절단은 held_climax.slice_upto. 비어 있으면 left_censored → 미발화(합성 테스트 호환).
    weekly_full: list = field(default_factory=list)
    daily_flagged: list = field(default_factory=list)
    # (#181 B5) 상폐 격리 종목: 마지막 봉(= delisted_at − 1일 = liq_window 끝)에 전량 강제청산.
    delisted: bool = False
    last_bar: date | None = None            # 마지막 거래일(격리 종목만)
    liq_start: date | None = None           # 정리매매 창 시작(마지막 봉 − LIQ_WINDOW_DAYS 달력일)


@dataclass
class PortfolioConfig:
    initial_capital: float = 100_000_000.0
    max_positions: int = 5
    pyramiding: bool = False        # S2·S3
    sell_half: bool = SELL_HALF_ENABLED   # S3 — (#166) SSOT 플래그가 기본값(production 과 동일 출처)
    climax_sell: bool = True        # (항목 ③) 보유 climax 강세 매도 — production 과 동일 동작, 기본 ON
    decline_sell: bool = True       # (#164) 보유 약세 매도(P1 ∧ (T-A ∨ TA-d), 억제 없음) — 기본 ON
    hold_min_days: int = TRADE_HOLD_MIN_DAYS   # 8주 면제 + climax 억제 공유 상수(SSOT)
    exclude_down_phases: bool = False   # v2 레거시 별칭 (= gate_mode "legacy")
    gate_mode: str | None = None    # v3.1: None|"legacy"|"prod"|"variant"
    pilot_mode: bool = False        # v4: bottoming 파일럿 경로 (gate=prod 전제)
    pilot_frac: float = SIZING_PILOT_FRAC   # 파일럿 = 정상 목표의 50% (prereg v4.2; SSOT #153)
    pilot_stop_pct: float = 0.06    # 파일럿 초기 스톱 6%
    pilot_retry_cap: int = 2        # (종목, 에피소드)당 최대 진입
    pilot54_mode: bool = False      # Arm-54: rally_attempt 3중 필터 파일럿 (gate=a53 전제)
    pilot_consec_lock: int = PILOT_CONSEC_STOP_LOCK   # E5 전역 잠금 임계
    risk_pct: float = SIZING_RISK_PER_TRADE          # 계좌 리스크/건 (TTLC §8; SSOT #153)
    max_position_pct: float = ENTRY_WEIGHT_PCT_MAX / 100.0   # 0.25 (SSOT #153)
    fixed_stop_pct: float = TRADE_STOP_INITIAL_PCT   # v2: 매수가 기준 초기 스톱 (O'Neil 7-8% 상단; SSOT #153)
    max_stop_pct: float = 0.10      # uncle point — 불변식으로만 사용 (v2.2)
    armed_gain_cap: float = 0.20    # armed = min(3R, +20%) (HMMS 20% 룰)
    max_chase_pct: float = 5.0
    tranche_fracs: tuple = (0.5, 0.3, 0.2)   # T1/T2/T3
    tranche_mults: tuple = (1.02, 1.04)       # T2/T3 트리거 (T1가 대비)
    start: date = START             # 매매 윈도 (이슈 #52: 기간 주입 — 기본 = 현행)
    end: date = END


@dataclass
class Position:
    ticker: str
    t1_date: date
    t1_price: float
    stop_pct: float
    base_low: float | None          # 기록용 — v2 에서 포지션 청산에는 미사용
    pivot: float
    pivot_sat: date
    target_krw: float
    qty: float
    cost_krw: float                 # 총 매입원가(수수료 제외) — avg = cost/qty
    premium_pct: float = 0.0        # 진입 프리미엄 (T1종가/pivot − 1)×100, 계측용
    n_fills: int = 1                # 체결 트랜치 수 (피라미딩 분리 계측)
    entry_kind: str = "normal"      # v4: normal | pilot | scaled
    episode_id: str | None = None   # v4: bottoming 에피소드 (레그 저점일)
    pending_tranches: list = field(default_factory=list)  # [(mult, frac), ...]
    armed: bool = False
    exempt_until: date | None = None
    hit20_date: date | None = None
    sold_half: bool = False
    half_pending_w8: bool = False   # 5B: 21일 내 +20% → 8주차 처분 대기
    half_expired: bool = False

    @property
    def avg_price(self) -> float:
        return self.cost_krw / self.qty


def _sell_value(qty: float, close: float, d: date) -> float:
    """매도 순수령액: 수수료 + 매도연도 증권거래세 차감."""
    gross = qty * close
    return gross * (1 - (_COMM + (cost_pct(d) - COMMISSION_RT)) / 100)


def run_portfolio(data: dict[str, TickerData], cfg: PortfolioConfig) -> dict:
    bar_idx = {t: {b.d: b for b in td.bars} for t, td in data.items()}
    all_dates = sorted({b.d for td in data.values() for b in td.bars
                        if cfg.start <= b.d <= cfg.end})
    cash = cfg.initial_capital
    positions: dict[str, Position] = {}
    entered_pivots: set[tuple] = set()
    last_close: dict[str, float] = {}
    assert cfg.fixed_stop_pct <= cfg.max_stop_pct, \
        "uncle point 불변식 위반: 초기 스톱 > 10% (TTLC §8)"   # v2.2
    stats = {"n_entries": 0, "n_replacements": 0, "n_tranche_fills": 0,
             "n_half_sells": 0, "n_skipped_chase": 0,
             "n_entries_in_liq_window": 0,   # (#181 B5 관측) 정리매매 창 내 신규 진입(차단 없음)
             "n_skipped_down_phase": 0, "n_skipped_no_cash": 0,
             "n_skipped_slots_full": 0, "entry_amounts": [],
             "exit_reasons": {}, "exits": [], "tranche_expiry": {},
             "n_pilot_entries": 0, "n_scaled_entries": 0,
             "n_skipped_retry_cap": 0, "scaleup_triggers": {}}
    episode_entries: dict[tuple, int] = {}   # (ticker, episode) -> 진입 수
    curve: list[tuple] = []

    # (Arm-54 E5) 파일럿 전역 잠금 상태 — 연속 손실 청산 카운트, 해제 = 새 FTD 단독.
    # 잠금은 시장 무구분 전역(설계 문언 '전역'), 해제 이벤트는 어느 시장의 FTD 든 인정.
    pilot54_lock = {"locked": False, "consec": 0, "date": None}
    ftd_events_all = sorted({dd for td_ in data.values()
                             for dd, ev in td_.ftd_event_by_date.items() if ev})

    def _full_exit(pos: Position, close: float, d: date, reason: str, also: tuple = ()):
        """also: 같은 날 함께 성립한 하위 우선순위 사유(#164 병기 — 라벨은 앞선 것)."""
        nonlocal cash
        cash += _sell_value(pos.qty, close, d)
        pnl_pct_ = round((close / pos.avg_price - 1) * 100, 2)
        if cfg.pilot54_mode and pos.entry_kind == "pilot":
            if pnl_pct_ < 0:
                pilot54_lock["consec"] += 1
                if pilot54_lock["consec"] >= cfg.pilot_consec_lock:
                    pilot54_lock["locked"] = True
                    pilot54_lock["date"] = d
                    stats["pilot54_lock_events"] = (
                        stats.get("pilot54_lock_events", 0) + 1)
            else:
                pilot54_lock["consec"] = 0
        stats["exit_reasons"][reason] = stats["exit_reasons"].get(reason, 0) + 1
        stats["exits"].append({"ticker": pos.ticker, "date": str(d),
                               "t1_date": str(pos.t1_date),
                               "reason": reason,
                               "also": list(also),
                               "pnl_pct": round((close / pos.avg_price - 1) * 100, 2),
                               "premium_pct": round(pos.premium_pct, 2),
                               "n_fills": pos.n_fills,
                               "entry_kind": pos.entry_kind,
                               "episode": pos.episode_id})
        del positions[pos.ticker]

    def _sell_half(pos: Position, close: float, d: date):
        nonlocal cash
        half = pos.qty / 2
        cash += _sell_value(half, close, d)
        pos.qty -= half
        pos.cost_krw /= 2           # 평균단가 불변
        pos.sold_half = True
        pos.half_pending_w8 = False
        stats["n_half_sells"] += 1

    for d in all_dates:
        # ── ① 청산·상태 갱신 (스톱·플로어·5B — 전량/부분 매도) ──
        for t in list(positions):
            bar = bar_idx[t].get(d)
            if bar is None:
                continue
            last_close[t] = bar.close
            pos = positions[t]
            avg = pos.avg_price
            # v2.1 armed: min(3R, +20%) — 장전 먼저(같은 날 종가가 장전+이탈 동시는 불가능)
            if bar.close >= avg * (1 + min(3 * pos.stop_pct, cfg.armed_gain_cap)):
                pos.armed = True
            # v2.1 3층 스택: 유효 스톱 = max(초기 8%, armed 본전, Breakeven-or-Better sma50)
            floors = [(avg * (1 - pos.stop_pct), "stop8")]
            if pos.armed:
                floors.append((avg, "floor"))
            if bar.sma_50 is not None and bar.sma_50 >= avg:
                floors.append((bar.sma_50, "sma50_trail"))
            stop_level, stop_reason = max(floors)
            if bar.close < stop_level:
                _full_exit(pos, bar.close, d, stop_reason)
                continue
            # (#181 B5) 상폐 강제청산 — 마지막 봉 도달 시 종가 전량, reason=delisted
            # [design-judgment — 책 근거 없음, 보수 선택]. 우선순위 스탑 > delisted > 약세 > 강세.
            td_d = data[t]
            if td_d.delisted and td_d.last_bar is not None and d >= td_d.last_bar:
                _full_exit(pos, bar.close, d, "delisted")
                continue
            # (항목 ③·#164) 보유 약세/강세 매도 — 스탑 이후·미청산 포지션. production 러너와
            # 같은 판정 함수(held_decline·held_climax), 같은 gates(절단 1회). 우선순위 스탑 >
            # 약세(decline) > 강세(climax): 발화 시 당일 종가 전량 청산, 같은 날 복수 성립은
            # 라벨=앞선 것 + also 병기.
            if cfg.decline_sell or cfg.climax_sell:
                td_ = data[t]
                wk_, dl_ = slice_upto(td_.weekly_full, td_.daily_flagged, d)
                gates_ = gates_from_series(wk_, dl_)
                hd = evaluate_held_decline(gates_, pos.t1_date, d) if cfg.decline_sell else None
                hc = (evaluate_held_climax(gates_, pos.t1_date, d, cfg.hold_min_days)
                      if cfg.climax_sell else None)
                if hd is not None and hd.fired:
                    _full_exit(pos, bar.close, d, "decline",
                               also=("climax",) if (hc is not None and hc.fired) else ())
                    continue
                if hc is not None and hc.fired:
                    _full_exit(pos, bar.close, d, "climax")
                    continue
            # +20% 최초 도달(8주 면제 판정, 전 시나리오) + 5B 절반매도(S3) — (#166) production 과
            # 같은 순수 함수 sell_half.evaluate_sell_half 로 판정. hit20/면제는 플래그와 무관하게 갱신,
            # 절반 매도 집행·대기·소멸 상태는 cfg.sell_half 일 때만 반영(구 동작과 동일).
            sh = evaluate_sell_half(
                entry_date=pos.t1_date, entry_price=avg, close=bar.close, as_of=d,
                state=SellHalfState(pos.hit20_date, pos.half_pending_w8, pos.sold_half, pos.half_expired),
                hold_min_days=cfg.hold_min_days)
            if sh.hit20_new:
                pos.hit20_date = d
                if sh.within_early:
                    pos.exempt_until = pos.t1_date + timedelta(days=cfg.hold_min_days)
            if cfg.sell_half:
                if sh.fire:
                    _sell_half(pos, bar.close, d)
                pos.half_pending_w8 = sh.state.half_pending
                pos.half_expired = sh.state.half_expired

        # 당일 시세 기준 계좌가치 (매수 전 — 매수는 구성만 바꿈)
        equity = cash + sum(p.qty * last_close.get(p.ticker, p.avg_price)
                            for p in positions.values())

        # ── ②·③ 매수: 피라미딩 트랜치 우선(보완 ①), 그다음 신규(우선순위순) ──
        if cfg.pyramiding:
            for t, pos in list(positions.items()):
                bar = bar_idx[t].get(d)
                if bar is None or not pos.pending_tranches:
                    continue
                remaining = []
                for mult, frac in pos.pending_tranches:
                    if bar.close < pos.t1_price * mult:
                        remaining.append((mult, frac))      # 미트리거 — 유지
                        continue
                    if bar.close > pos.pivot * (1 + cfg.max_chase_pct / 100):
                        stats["tranche_expiry"]["chase"] = (
                            stats["tranche_expiry"].get("chase", 0) + 1)
                        continue                            # (a) 소멸
                    amt = pos.target_krw * frac
                    if cash < amt * (1 + _COMM / 100):
                        stats["tranche_expiry"]["cash"] = (
                            stats["tranche_expiry"].get("cash", 0) + 1)
                        continue                            # (c) 소멸
                    cash -= amt * (1 + _COMM / 100)
                    pos.qty += amt / bar.close
                    pos.cost_krw += amt
                    pos.n_fills += 1
                    stats["n_tranche_fills"] += 1
                pos.pending_tranches = remaining

        # 신호 수집
        signals = []
        for t, td in data.items():
            if t in positions:
                continue
            bar = bar_idx[t].get(d)
            if bar is None or bar.sma_50 is None or bar.avg_volume_50d is None:
                continue
            last_close[t] = bar.close
            active = _active_row(
                sorted([r for r in td.watch_rows if r.pivot_price is not None],
                       key=lambda r: r.sat), d)
            if active is None:
                continue
            pivot_reentered = (t, active.sat) in entered_pivots
            sig = gate_evaluate(
                close=bar.close, pivot_price=active.pivot_price,
                volume=bar.volume, avg_volume_50d=bar.avg_volume_50d,
                stop_loss=active.base_low, sma_50=bar.sma_50,
                classification="watch", prev_close=bar.prev_close,
                watch_reason=active.watch_reason)
            if sig != "breakout_from_watch":
                continue
            if bar.close > active.pivot_price * (1 + cfg.max_chase_pct / 100):
                stats["n_skipped_chase"] += 1
                continue
            gate = cfg.gate_mode or ("legacy" if cfg.exclude_down_phases else None)
            entry_kind, episode_id = "normal", None
            if gate == "legacy" and td.phase_by_date.get(d) in DOWN_PHASES:
                stats["n_skipped_down_phase"] += 1      # v2 excl 그대로 (Arm C)
                continue
            if gate in ("prod", "variant", "a53"):
                # v3.1: §3.5 코드화 분기 재현 — unfavorable_market 은 confirmed 필수
                phases = (td.phase_variant_by_date if gate == "variant"
                          else td.phase_a53_by_date if gate == "a53"
                          else td.phase_by_date)
                if (active.watch_reason == "unfavorable_market"
                        and phases.get(d) != "confirmed_uptrend"):
                    if cfg.pilot54_mode:
                        # (Arm-54, LOCKED) 파일럿 v2: rally_attempt ∧ dist<6 ∧
                        # 3중 필터(E2) ∧ 전역 비잠금(E5). 증액 트리거 없음(E4 —
                        # v4 와 달리 파일럿 고정), 추격 상한은 위 공통 검사 상속(#45).
                        if not (phases.get(d) == "rally_attempt"
                                and td.mkt_dist_by_date.get(d, 99)
                                < STATUS_DIST_COUNT_FOR_FTD_INVALIDATION
                                and td.pilot54_ok_by_date.get(d, False)):
                            stats["n_skipped_pilot54_filter"] = (
                                stats.get("n_skipped_pilot54_filter", 0) + 1)
                            # (§4 산출물) 탈락 기여 분해 — 비배타 카운트
                            brk = stats.setdefault("pilot54_skip_breakdown", {})
                            if phases.get(d) != "rally_attempt":
                                brk[f"phase_{phases.get(d)}"] = (
                                    brk.get(f"phase_{phases.get(d)}", 0) + 1)
                            elif (td.mkt_dist_by_date.get(d, 99)
                                  >= STATUS_DIST_COUNT_FOR_FTD_INVALIDATION):
                                brk["dist_ge_6"] = brk.get("dist_ge_6", 0) + 1
                            else:
                                mp, rs, band = td.pilot54_flags_by_date.get(
                                    d, (None, None, None))
                                for name, v in (("mp", mp), ("rs", rs),
                                                ("band", band)):
                                    if v is False:
                                        brk[f"filter_{name}_fail"] = (
                                            brk.get(f"filter_{name}_fail", 0) + 1)
                            continue
                        if pilot54_lock["locked"]:
                            # 해제 = 잠금 이후 새 FTD 이벤트 단독 (E5)
                            if any(pilot54_lock["date"] < e <= d
                                   for e in ftd_events_all):
                                pilot54_lock.update(
                                    locked=False, consec=0, date=None)
                            else:
                                stats["n_skipped_pilot_lock"] = (
                                    stats.get("n_skipped_pilot_lock", 0) + 1)
                                continue
                        # E5 구체화: 에피소드 = watch 베이스(주간 분류 행) 단위 —
                        # 같은 베이스 파일럿 재진입 상한 = pilot_retry_cap.
                        episode_id = f"base-{active.sat}"
                        if (episode_entries.get((t, episode_id), 0)
                                >= cfg.pilot_retry_cap):
                            stats["n_skipped_retry_cap"] += 1
                            continue
                        entry_kind = "pilot"
                    else:
                        # v4 파일럿 경로: down 국면 ∧ bottoming 활성 ∧ 재시도 캡 내
                        bott_active, bott_ep = td.bottoming_by_date.get(
                            d, (False, None))
                        if not (cfg.pilot_mode and phases.get(d) in DOWN_PHASES
                                and bott_active):
                            stats["n_skipped_down_phase"] += 1
                            continue
                        episode_id = str(bott_ep)
                        if (episode_entries.get((t, episode_id), 0)
                                >= cfg.pilot_retry_cap):
                            stats["n_skipped_retry_cap"] += 1
                            continue
                        # 증액 트리거 (일별 평가): (i) FTD 유효 OR (ii) 활성 파일럿≥2 ∧ 합산 미실현>0
                        pilots = [p for p in positions.values()
                                  if p.entry_kind == "pilot"]
                        unreal = sum(p.qty * last_close.get(p.ticker, p.avg_price)
                                     - p.cost_krw for p in pilots)
                        if td.ftd_valid_by_date.get(d, False):
                            entry_kind = "scaled"
                            stats["scaleup_triggers"]["i_ftd"] = (
                                stats["scaleup_triggers"].get("i_ftd", 0) + 1)
                        elif len(pilots) >= 2 and unreal > 0:
                            entry_kind = "scaled"
                            stats["scaleup_triggers"]["ii_feedback"] = (
                                stats["scaleup_triggers"].get("ii_feedback", 0) + 1)
                        else:
                            entry_kind = "pilot"
            # 같은 pivot 재진입 금지 — 단 파일럿 경로는 에피소드 캡(2회)이 관장
            # (prereg v4.2 재시도 허용의 구현 귀결)
            if pivot_reentered and episode_id is None:
                continue
            # v2.2: 스톱 = 매수가 기준 고정 8% (파일럿은 6% — prereg v4.2)
            signals.append({"ticker": t, "bar": bar, "active": active,
                            "stop_pct": (cfg.pilot_stop_pct if entry_kind == "pilot"
                                         else cfg.fixed_stop_pct),
                            "entry_kind": entry_kind, "episode_id": episode_id,
                            "rs": td.rs_by_date.get(d),
                            "volmult": bar.volume / bar.avg_volume_50d})
        signals.sort(key=lambda s: (-(s["rs"] if s["rs"] is not None else -inf),
                                    -s["volmult"]))

        for s in signals:
            if len(positions) >= cfg.max_positions:
                # 교체: 당일진입·8주면제 제외한 최약이 ≤ 0% 일 때만
                elig = [p for p in positions.values()
                        if p.t1_date != d
                        and not (p.exempt_until and d <= p.exempt_until)]
                weakest = min(elig, key=lambda p: last_close.get(p.ticker, p.avg_price)
                              / p.avg_price) if elig else None
                if (weakest is None
                        or last_close.get(weakest.ticker, weakest.avg_price)
                        / weakest.avg_price - 1 > 0):
                    stats["n_skipped_slots_full"] += len(
                        [x for x in signals if signals.index(x) >= signals.index(s)])
                    break   # 잔여 신호 전부 무시 (prereg Q8)
                _full_exit(weakest, last_close[weakest.ticker], d, "replaced")
                stats["n_replacements"] += 1
            # 사이징: 정상·증액 = 1.25%/8% = 15.625%. 파일럿 = 그 50% (prereg v4.2)
            pos_pct = min(cfg.risk_pct / cfg.fixed_stop_pct, cfg.max_position_pct)
            if s["entry_kind"] == "pilot":
                pos_pct *= cfg.pilot_frac
            target = pos_pct * equity                      # 보완 ②: T1일 동결
            t1_frac = cfg.tranche_fracs[0] if cfg.pyramiding else 1.0
            amt = target * t1_frac
            if cash < amt * (1 + _COMM / 100):
                stats["n_skipped_no_cash"] += 1            # 보완 ④
                continue
            cash -= amt * (1 + _COMM / 100)
            bar, active = s["bar"], s["active"]
            positions[s["ticker"]] = Position(
                ticker=s["ticker"], t1_date=d, t1_price=bar.close,
                stop_pct=s["stop_pct"], base_low=active.base_low,
                pivot=active.pivot_price, pivot_sat=active.sat,
                target_krw=target, qty=amt / bar.close, cost_krw=amt,
                premium_pct=(bar.close / active.pivot_price - 1) * 100,
                entry_kind=s["entry_kind"], episode_id=s["episode_id"],
                pending_tranches=(list(zip(cfg.tranche_mults, cfg.tranche_fracs[1:]))
                                  if cfg.pyramiding else []),
            )
            entered_pivots.add((s["ticker"], active.sat))
            stats["n_entries"] += 1
            td_e = data[s["ticker"]]
            if td_e.delisted and td_e.liq_start is not None and d >= td_e.liq_start:
                stats["n_entries_in_liq_window"] += 1   # (#181 B5 관측) 차단 없음
            stats["entry_amounts"].append(amt)
            if s["entry_kind"] == "pilot":
                stats["n_pilot_entries"] += 1
            elif s["entry_kind"] == "scaled":
                stats["n_scaled_entries"] += 1
            if s["episode_id"] is not None:     # 캡은 파일럿·증액 모두 카운트
                key = (s["ticker"], s["episode_id"])
                episode_entries[key] = episode_entries.get(key, 0) + 1

        equity_eod = cash + sum(p.qty * last_close.get(p.ticker, p.avg_price)
                                for p in positions.values())
        curve.append((d, round(equity_eod, 0), round(equity_eod - cash, 0)))

    # ── 지표 ──
    eq = [e for _, e, _ in curve]
    peak, mdd = -inf, 0.0
    for e in eq:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    years = (all_dates[-1] - all_dates[0]).days / 365.25 if all_dates else 0
    final_mult = eq[-1] / cfg.initial_capital if eq else 1.0
    exposure = (sum(inv / e for _, e, inv in curve if e > 0) / len(curve)
                if curve else 0.0)
    metrics = {
        "final_multiple": round(final_mult, 4),
        "cagr_pct": round((final_mult ** (1 / years) - 1) * 100, 2) if years else 0,
        "max_drawdown_pct": round(mdd * 100, 2),
        "avg_exposure_pct": round(exposure * 100, 1),
        "open_positions_at_end": len(positions),
    }
    return {"metrics": metrics, "validation": _validation(stats["exits"]),
            "stats": stats, "curve": [(str(d), e, inv) for d, e, inv in curve]}


def _validation(exits: list[dict]) -> dict:
    """prereg v2.3 검증 기준 + 모니터링 지표 (실현 트레이드 = 청산분만)."""
    losses = sorted(-e["pnl_pct"] for e in exits if e["pnl_pct"] < 0)
    gains = [e["pnl_pct"] for e in exits if e["pnl_pct"] > 0]
    mean_loss = sum(losses) / len(losses) if losses else None
    med_loss = losses[len(losses) // 2] if losses else None
    mean_gain = sum(gains) / len(gains) if gains else None
    gap_over8 = [x - 8.0 for x in losses if x > 8.0]
    buckets = {}
    for lo, hi, label in ((0, 1, "0-1%"), (1, 3, "1-3%"), (3, 5.01, "3-5%")):
        es = [e for e in exits if lo <= e["premium_pct"] < hi]
        n = len(es)
        buckets[label] = {
            "n": n,
            "stopout_rate": round(sum(1 for e in es if e["reason"] == "stop8") / n, 3)
            if n else None,
            "mean_pnl": round(sum(e["pnl_pct"] for e in es) / n, 2) if n else None,
        }
    pyr = [e for e in exits if e["n_fills"] > 1]
    single = [e for e in exits if e["n_fills"] == 1]
    realized = [e["pnl_pct"] for e in exits]
    return {
        "expectancy_pct": round(sum(realized) / len(realized), 2) if realized else None,
        "n_realized": len(realized),
        "criteria": {
            "i_mean_loss_le_9": {"value": round(mean_loss, 2) if mean_loss else None,
                                 "pass": (mean_loss <= 9.0) if mean_loss else None},
            "ii_median_loss_lt_10": {"value": round(med_loss, 2) if med_loss else None,
                                     "pass": (med_loss < 10.0) if med_loss else None},
            "iii_mean_loss_lt_mean_gain": {
                "mean_loss": round(mean_loss, 2) if mean_loss else None,
                "mean_gain": round(mean_gain, 2) if mean_gain else None,
                "pass": (mean_loss < mean_gain)
                if (mean_loss and mean_gain) else None},
        },
        "monitoring": {
            "gap_vs_5_6_target": round(mean_loss - 5.5, 2) if mean_loss else None,
            "gap_over_8_n": len(gap_over8),
            "gap_over_8_mean": round(sum(gap_over8) / len(gap_over8), 2)
            if gap_over8 else None,
            "entry_premium_buckets": buckets,
            "stopout_rate_pyramided": round(
                sum(1 for e in pyr if e["reason"] == "stop8") / len(pyr), 3)
            if pyr else None,
            "stopout_rate_single": round(
                sum(1 for e in single if e["reason"] == "stop8") / len(single), 3)
            if single else None,
        },
    }


# ── DB 로더 + 시나리오 러너 ─────────────────────────────────────────────────

def load_ticker_data(conn, tickers: list[str] | None = None, *,
                     start: date = START, end: date = END,
                     watch_start: date = WATCH_START,
                     watch_end: date = WATCH_END) -> dict[str, TickerData]:
    """기본(인자 없음) = 표본 A · 2021~2025 윈도 — 현행 동작 불변 (이슈 #52 파라미터화)."""
    from kr_pipeline.backtest.market_regime import (
        compute_variant_status, compute_variant_status_a53, compute_market_extras)
    pmaps: dict[str, list] = {}
    vmaps: dict[str, dict] = {}
    amaps: dict[str, dict] = {}
    xmaps: dict[str, dict] = {}
    out: dict[str, TickerData] = {}
    for ticker in (FROZEN_SAMPLE if tickers is None else tickers):
        market = _market_of(conn, ticker)
        code = ph.INDEX_OF.get(market, "1001")
        bars = load_daily_series(conn, ticker, start, end)
        if code not in pmaps:
            pmaps[code] = ph.load_phase_map(conn, code)
            vmaps[code] = compute_variant_status(conn, code, start, end)
            amaps[code] = compute_variant_status_a53(conn, code, start, end)
            xmaps[code] = compute_market_extras(conn, code, end)
        phase_by_date = {b.d: ph.phase_at(pmaps[code], b.d) for b in bars}
        phase_variant_by_date = {b.d: vmaps[code].get(b.d) for b in bars}
        phase_a53_by_date = {b.d: amaps[code].get(b.d) for b in bars}
        bottoming_by_date = {b.d: xmaps[code].get(b.d, {}).get("bottoming",
                                                              (False, None))
                             for b in bars}
        ftd_valid_by_date = {b.d: xmaps[code].get(b.d, {}).get("ftd_valid", False)
                             for b in bars}
        mkt_dist_by_date = {b.d: xmaps[code].get(b.d, {}).get("dist", 0)
                            for b in bars}
        ftd_event_by_date = {b.d: xmaps[code].get(b.d, {}).get("is_ftd_event",
                                                               False)
                             for b in bars}
        src = price_source(conn, ticker)  # (#181 B4) 라이브/격리 분기
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT date, rs_rating, minervini_pass, rs_line_at_52w_high, "
                f"pct_from_52w_high FROM {src.indicators} "
                "WHERE ticker = %s AND date BETWEEN %s AND %s",
                (ticker, start, end))
            rows = cur.fetchall()
        delisted_last_bar = None
        if src.delisted:
            with conn.cursor() as cur:
                cur.execute(f"SELECT MAX(date) FROM {src.daily} WHERE ticker = %s", (ticker,))
                delisted_last_bar = cur.fetchone()[0]
        rs = {r[0]: r[1] for r in rows}
        # (Arm-54 E2) 3중 하드 필터 — 전부 as-of 저장 지표, AND 결합
        pilot54_flags = {
            r[0]: (bool(r[2]), bool(r[3]),
                   r[4] is not None
                   and PILOT_OFF_HIGH_MIN_PCT <= float(r[4])
                   <= PILOT_OFF_HIGH_MAX_PCT)
            for r in rows}
        pilot54_ok = {d: all(f) for d, f in pilot54_flags.items()}
        # (항목 ③) climax 매도용 전 이력(≤ end) — 날짜별 절단은 시뮬 루프에서
        from api.services.payload_builder import _fetch_weekly_full
        weekly_full = _fetch_weekly_full(conn, ticker, end)
        daily_flagged = fetch_daily_flagged(conn, ticker, end)
        out[ticker] = TickerData(
            market=market, bars=bars, weekly_full=weekly_full, daily_flagged=daily_flagged,
            delisted=src.delisted, last_bar=delisted_last_bar,
            liq_start=(delisted_last_bar - timedelta(days=LIQ_WINDOW_DAYS)
                       if delisted_last_bar is not None else None),
            watch_rows=load_watchlist(conn, ticker, watch_start, watch_end,
                                      table=BT_TABLE),
            rs_by_date=rs, phase_by_date=phase_by_date,
            phase_variant_by_date=phase_variant_by_date,
            bottoming_by_date=bottoming_by_date,
            ftd_valid_by_date=ftd_valid_by_date,
            phase_a53_by_date=phase_a53_by_date,
            pilot54_ok_by_date=pilot54_ok,
            pilot54_flags_by_date=pilot54_flags,
            mkt_dist_by_date=mkt_dist_by_date,
            ftd_event_by_date=ftd_event_by_date)
    return out


PILOT_ANCHORS = {"004360", "053350"}   # prereg v4.4 — 종목 단위 제외


def pilot_report(exits: list[dict]) -> dict:
    """prereg v4.4 — 종목-에피소드 집계(파일럿 사이즈 진입만), 앵커 종목 제외 1차."""
    pilots = [e for e in exits if e["entry_kind"] == "pilot"]
    scaled = [e for e in exits if e["entry_kind"] == "scaled"]
    episodes: dict[tuple, list] = {}
    for e in pilots:
        episodes.setdefault((e["ticker"], e["episode"]), []).append(e["pnl_pct"])
    table = [{"ticker": t, "episode": ep, "n_entries": len(v),
              "net_pnl_pct": round(sum(v), 2)}
             for (t, ep), v in sorted(episodes.items())]
    def _mean(rows):
        return round(sum(r["net_pnl_pct"] for r in rows) / len(rows), 2) if rows else None
    excl = [r for r in table if r["ticker"] not in PILOT_ANCHORS]
    excl_drop_best = (sorted(excl, key=lambda r: -r["net_pnl_pct"])[1:]
                      if len(excl) > 1 else [])
    mean_excl = _mean(excl)
    return {
        "episodes": table,
        "n_episodes": len(table),
        "mean_net_incl_anchor": _mean(table),
        "mean_net_excl_anchor": mean_excl,
        "n_episodes_excl_anchor": len(excl),
        "mean_excl_anchor_drop_best": _mean(excl_drop_best),   # 꼬리 가시화 전용
        "primary_pass": (mean_excl is not None and mean_excl > 0),
        "scaled_pnl": [{"ticker": e["ticker"], "pnl_pct": e["pnl_pct"]}
                       for e in scaled],
    }


def _benchmark(conn, code_market: str, d0: date, d1: date) -> dict:
    series = load_index_series(conn, code_market, d0, d1)
    ds = sorted(series)
    mult = series[ds[-1]] / series[ds[0]]
    years = (ds[-1] - ds[0]).days / 365.25
    return {"multiple": round(mult, 4),
            "cagr_pct": round((mult ** (1 / years) - 1) * 100, 2)}


# v4 (S1 구성): A=정밀 production 재현(기준선), P=A+bottoming 파일럿 경로
ARMS = {
    "armA-prod": {"gate_mode": "prod"},
    "armP-pilot": {"gate_mode": "prod", "pilot_mode": True},
    # (LOCKED prereg §9.2) 독립 구간 판정용 — Arm-53 사다리 / +Arm-54 파일럿
    "arm53": {"gate_mode": "a53"},
    "arm53-pilot54": {"gate_mode": "a53", "pilot54_mode": True},
}


def _parse_args(argv: list[str]) -> dict:
    """플래그 없으면 현행 상수 그대로 — 기본 실행 불변 (이슈 #52 기간 파라미터화)."""
    def flag(name: str, default: str) -> str:
        prefix = f"--{name}="
        for a in argv:
            if a.startswith(prefix):
                return a.split("=", 1)[1]
        return default
    return {
        "kind": flag("sample", "a"),
        "start": date.fromisoformat(flag("start", str(START))),
        "end": date.fromisoformat(flag("end", str(END))),
        "watch_start": date.fromisoformat(flag("watch-start", str(WATCH_START))),
        "watch_end": date.fromisoformat(flag("watch-end", str(WATCH_END))),
    }


def _resolve_sample(kind: str) -> list[str]:
    """a = 동결 표본 A. ab = A+B 200종목(prereg 2026-07-21 I1).
    c = 동결 표본 C(미동결이면 거부 — 이슈 #52 준비 상태 가드)."""
    if kind == "a":
        return list(FROZEN_SAMPLE)
    if kind == "ab":
        from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
        return list(FROZEN_SAMPLE) + list(FROZEN_SAMPLE_B)   # 잉여 14 제외
    if kind == "c":
        import kr_pipeline.backtest.frozen_sample_c as fc
        if not fc.FROZEN_SAMPLE_C:
            raise SystemExit(
                "표본 C 미동결(pending_draw) — 사전등록 "
                "(2026-07-21-independent-window-backtest-prereg.md) 승인 후 "
                "scripts/draw_sample_c.py --draw 1회 실행으로 동결하라")
        return list(fc.FROZEN_SAMPLE_C)
    raise SystemExit(f"unknown --sample: {kind!r} (a|ab|c)")


def main() -> int:
    import sys
    from kr_pipeline.db.connection import connect
    from kr_pipeline.backtest.premium_bins import premium_bins
    args = _parse_args(sys.argv[1:])
    kind = args["kind"]
    tickers = _resolve_sample(kind)
    curves_path = ("data/backtest/portfolio_curves_sample_ab_20260721.json"
                   if kind == "ab" else "data/backtest/portfolio_curves_v4_20260703.json")
    with connect() as conn:
        data = load_ticker_data(conn, tickers,
                                start=args["start"], end=args["end"],
                                watch_start=args["watch_start"],
                                watch_end=args["watch_end"])
        out = {"prereg": ("2026-07-21-sample-b-analysis-prereg.md I1·P4" if kind == "ab"
                          else "2026-07-02-portfolio-sim-prereg.md v4"),
               "sample": kind, "arms": {}}
        curves = {}
        for key, flags in ARMS.items():
            r = run_portfolio(data, PortfolioConfig(
                **flags, start=args["start"], end=args["end"]))
            curves[key] = r.pop("curve")
            if flags.get("pilot_mode"):
                out["pilot_report"] = pilot_report(r["stats"]["exits"])
            if kind == "ab":
                r["premium_bins"] = premium_bins(r["stats"]["exits"])
            r["stats"].pop("entry_amounts")
            r["stats"].pop("exits")
            out["arms"][key] = r
        d0 = date(2021, 1, 4)
        out["benchmark"] = {"KOSPI": _benchmark(conn, "KOSPI", d0, END),
                            "KOSDAQ": _benchmark(conn, "KOSDAQ", d0, END)}
        a, p = out["arms"]["armA-prod"]["metrics"], out["arms"]["armP-pilot"]["metrics"]
        out["guardrail_mdd_P_minus_A_le_5pp"] = {
            "value_pp": round(a["max_drawdown_pct"] - p["max_drawdown_pct"], 2),
            "pass": (a["max_drawdown_pct"] - p["max_drawdown_pct"]) <= 5.0,
        }
    with open(curves_path, "w",
              encoding="utf-8") as f:
        json.dump(curves, f, ensure_ascii=False)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
