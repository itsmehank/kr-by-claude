"""포트폴리오 단위 시뮬레이션 — 사전등록 2026-07-02 portfolio-sim. 읽기전용·결정론.

규칙 출처: Minervini/O'Neil 에이전트 v1.1 + 구현측 보완 §4 (사전등록 문서 참조).
DB-free 코어(run_portfolio) + DB 로더(load_ticker_data) 분리.

  python -m kr_pipeline.backtest.portfolio    # 6 시나리오(S1~S3 × incl/excl) 실행
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
from kr_pipeline.llm_runner.compute.trigger_gate import evaluate as gate_evaluate

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


@dataclass
class PortfolioConfig:
    initial_capital: float = 100_000_000.0
    max_positions: int = 5
    pyramiding: bool = False        # S2·S3
    sell_half: bool = False         # S3
    exclude_down_phases: bool = False   # v2 레거시 별칭 (= gate_mode "legacy")
    gate_mode: str | None = None    # v3.1: None|"legacy"|"prod"|"variant"
    pilot_mode: bool = False        # v4: bottoming 파일럿 경로 (gate=prod 전제)
    pilot_frac: float = 0.5         # 파일럿 = 정상 목표의 50% (prereg v4.2)
    pilot_stop_pct: float = 0.06    # 파일럿 초기 스톱 6%
    pilot_retry_cap: int = 2        # (종목, 에피소드)당 최대 진입
    risk_pct: float = 0.0125        # 계좌 리스크/건 (TTLC §8)
    max_position_pct: float = 0.25
    fixed_stop_pct: float = 0.08    # v2: 매수가 기준 초기 스톱 (O'Neil 7-8% 상단)
    max_stop_pct: float = 0.10      # uncle point — 불변식으로만 사용 (v2.2)
    armed_gain_cap: float = 0.20    # armed = min(3R, +20%) (HMMS 20% 룰)
    max_chase_pct: float = 5.0
    tranche_fracs: tuple = (0.5, 0.3, 0.2)   # T1/T2/T3
    tranche_mults: tuple = (1.02, 1.04)       # T2/T3 트리거 (T1가 대비)


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
                        if START <= b.d <= END})
    cash = cfg.initial_capital
    positions: dict[str, Position] = {}
    entered_pivots: set[tuple] = set()
    last_close: dict[str, float] = {}
    assert cfg.fixed_stop_pct <= cfg.max_stop_pct, \
        "uncle point 불변식 위반: 초기 스톱 > 10% (TTLC §8)"   # v2.2
    stats = {"n_entries": 0, "n_replacements": 0, "n_tranche_fills": 0,
             "n_half_sells": 0, "n_skipped_chase": 0,
             "n_skipped_down_phase": 0, "n_skipped_no_cash": 0,
             "n_skipped_slots_full": 0, "entry_amounts": [],
             "exit_reasons": {}, "exits": [], "tranche_expiry": {},
             "n_pilot_entries": 0, "n_scaled_entries": 0,
             "n_skipped_retry_cap": 0, "scaleup_triggers": {}}
    episode_entries: dict[tuple, int] = {}   # (ticker, episode) -> 진입 수
    curve: list[tuple] = []

    def _full_exit(pos: Position, close: float, d: date, reason: str):
        nonlocal cash
        cash += _sell_value(pos.qty, close, d)
        stats["exit_reasons"][reason] = stats["exit_reasons"].get(reason, 0) + 1
        stats["exits"].append({"ticker": pos.ticker, "date": str(d),
                               "t1_date": str(pos.t1_date),
                               "reason": reason,
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
            # +20% 최초 도달: 8주 면제 판정(전 시나리오) + 5B 분기(S3)
            if pos.hit20_date is None and bar.close >= avg * 1.20:
                pos.hit20_date = d
                within3w = (d - pos.t1_date).days <= 21
                if within3w:
                    pos.exempt_until = pos.t1_date + timedelta(days=56)
                if cfg.sell_half and not pos.sold_half:
                    if within3w:
                        pos.half_pending_w8 = True
                    else:
                        _sell_half(pos, bar.close, d)
            # 5B 8주차 처분 (진입+56일 후 첫 거래일)
            if (cfg.sell_half and pos.half_pending_w8 and not pos.half_expired
                    and (d - pos.t1_date).days > 56):
                if bar.close >= pos.avg_price * 1.20:
                    _sell_half(pos, bar.close, d)
                else:
                    pos.half_pending_w8 = False
                    pos.half_expired = True

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
            if gate in ("prod", "variant"):
                # v3.1: §3.5 코드화 분기 재현 — unfavorable_market 은 confirmed 필수
                phases = (td.phase_variant_by_date if gate == "variant"
                          else td.phase_by_date)
                if (active.watch_reason == "unfavorable_market"
                        and phases.get(d) != "confirmed_uptrend"):
                    # v4 파일럿 경로: down 국면 ∧ bottoming 활성 ∧ 재시도 캡 내
                    bott_active, bott_ep = td.bottoming_by_date.get(d, (False, None))
                    if not (cfg.pilot_mode and phases.get(d) in DOWN_PHASES
                            and bott_active):
                        stats["n_skipped_down_phase"] += 1
                        continue
                    episode_id = str(bott_ep)
                    if episode_entries.get((t, episode_id), 0) >= cfg.pilot_retry_cap:
                        stats["n_skipped_retry_cap"] += 1
                        continue
                    # 증액 트리거 (일별 평가): (i) FTD 유효 OR (ii) 활성 파일럿≥2 ∧ 합산 미실현>0
                    pilots = [p for p in positions.values() if p.entry_kind == "pilot"]
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

def load_ticker_data(conn) -> dict[str, TickerData]:
    from kr_pipeline.backtest.market_regime import (
        compute_variant_status, compute_market_extras)
    pmaps: dict[str, list] = {}
    vmaps: dict[str, dict] = {}
    xmaps: dict[str, dict] = {}
    out: dict[str, TickerData] = {}
    for ticker in FROZEN_SAMPLE:
        market = _market_of(conn, ticker)
        code = ph.INDEX_OF.get(market, "1001")
        bars = load_daily_series(conn, ticker, START, END)
        if code not in pmaps:
            pmaps[code] = ph.load_phase_map(conn, code)
            vmaps[code] = compute_variant_status(conn, code, START, END)
            xmaps[code] = compute_market_extras(conn, code, END)
        phase_by_date = {b.d: ph.phase_at(pmaps[code], b.d) for b in bars}
        phase_variant_by_date = {b.d: vmaps[code].get(b.d) for b in bars}
        bottoming_by_date = {b.d: xmaps[code].get(b.d, {}).get("bottoming",
                                                              (False, None))
                             for b in bars}
        ftd_valid_by_date = {b.d: xmaps[code].get(b.d, {}).get("ftd_valid", False)
                             for b in bars}
        with conn.cursor() as cur:
            cur.execute(
                "SELECT date, rs_rating FROM daily_indicators "
                "WHERE ticker = %s AND date BETWEEN %s AND %s",
                (ticker, START, END))
            rs = {r[0]: r[1] for r in cur.fetchall()}
        out[ticker] = TickerData(
            market=market, bars=bars,
            watch_rows=load_watchlist(conn, ticker, WATCH_START, WATCH_END,
                                      table=BT_TABLE),
            rs_by_date=rs, phase_by_date=phase_by_date,
            phase_variant_by_date=phase_variant_by_date,
            bottoming_by_date=bottoming_by_date,
            ftd_valid_by_date=ftd_valid_by_date)
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
}


def main() -> int:
    from kr_pipeline.db.connection import connect
    with connect() as conn:
        data = load_ticker_data(conn)
        out = {"prereg": "2026-07-02-portfolio-sim-prereg.md v4", "arms": {}}
        curves = {}
        for key, flags in ARMS.items():
            r = run_portfolio(data, PortfolioConfig(**flags))
            curves[key] = r.pop("curve")
            if flags.get("pilot_mode"):
                out["pilot_report"] = pilot_report(r["stats"]["exits"])
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
    with open("data/backtest/portfolio_curves_v4_20260703.json", "w",
              encoding="utf-8") as f:
        json.dump(curves, f, ensure_ascii=False)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
