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
    phase_by_date: dict         # date -> phase str (excl 판정용)


@dataclass
class PortfolioConfig:
    initial_capital: float = 100_000_000.0
    max_positions: int = 5
    pyramiding: bool = False        # S2·S3
    sell_half: bool = False         # S3
    exclude_down_phases: bool = False
    risk_pct: float = 0.0125        # 계좌 리스크/건 (TTLC §8)
    max_position_pct: float = 0.25
    max_stop_pct: float = 0.10
    max_chase_pct: float = 5.0
    tranche_fracs: tuple = (0.5, 0.3, 0.2)   # T1/T2/T3
    tranche_mults: tuple = (1.02, 1.04)       # T2/T3 트리거 (T1가 대비)


@dataclass
class Position:
    ticker: str
    t1_date: date
    t1_price: float
    stop_pct: float
    base_low: float | None
    pivot: float
    pivot_sat: date
    target_krw: float
    qty: float
    cost_krw: float                 # 총 매입원가(수수료 제외) — avg = cost/qty
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
    stats = {"n_entries": 0, "n_replacements": 0, "n_tranche_fills": 0,
             "n_half_sells": 0, "n_skipped_wide_stop": 0, "n_skipped_chase": 0,
             "n_skipped_down_phase": 0, "n_skipped_no_cash": 0,
             "n_skipped_slots_full": 0, "entry_amounts": [], "wide_stop_pcts": [],
             "exit_reasons": {}, "exits": [], "tranche_expiry": {}}
    curve: list[tuple] = []

    def _full_exit(pos: Position, close: float, d: date, reason: str):
        nonlocal cash
        cash += _sell_value(pos.qty, close, d)
        stats["exit_reasons"][reason] = stats["exit_reasons"].get(reason, 0) + 1
        stats["exits"].append({"ticker": pos.ticker, "date": str(d),
                               "reason": reason,
                               "pnl_pct": round((close / pos.avg_price - 1) * 100, 2)})
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
            if pos.base_low is not None and bar.close < pos.base_low:
                _full_exit(pos, bar.close, d, "base_low")
                continue
            if bar.sma_50 is not None and bar.close < bar.sma_50:
                _full_exit(pos, bar.close, d, "sma_50")
                continue
            if bar.close >= avg * (1 + 3 * pos.stop_pct):
                pos.armed = True
            if pos.armed and bar.close < avg:
                _full_exit(pos, bar.close, d, "floor")
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
            if active is None or (t, active.sat) in entered_pivots:
                continue
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
            if cfg.exclude_down_phases and td.phase_by_date.get(d) in DOWN_PHASES:
                stats["n_skipped_down_phase"] += 1
                continue
            stop_ref = max(x for x in (active.base_low, bar.sma_50) if x is not None)
            stop_pct = (bar.close - stop_ref) / bar.close
            if stop_pct > cfg.max_stop_pct:
                stats["n_skipped_wide_stop"] += 1
                stats["wide_stop_pcts"].append(round(stop_pct * 100, 1))
                continue
            stop_pct = max(stop_pct, 1e-9)
            signals.append({"ticker": t, "bar": bar, "active": active,
                            "stop_pct": stop_pct,
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
            pos_pct = min(cfg.risk_pct / s["stop_pct"], cfg.max_position_pct)
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
                pending_tranches=(list(zip(cfg.tranche_mults, cfg.tranche_fracs[1:]))
                                  if cfg.pyramiding else []),
            )
            entered_pivots.add((s["ticker"], active.sat))
            stats["n_entries"] += 1
            stats["entry_amounts"].append(amt)

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
    return {"metrics": metrics, "stats": stats,
            "curve": [(str(d), e, inv) for d, e, inv in curve]}


# ── DB 로더 + 시나리오 러너 ─────────────────────────────────────────────────

def load_ticker_data(conn) -> dict[str, TickerData]:
    pmaps: dict[str, list] = {}
    out: dict[str, TickerData] = {}
    for ticker in FROZEN_SAMPLE:
        market = _market_of(conn, ticker)
        code = ph.INDEX_OF.get(market, "1001")
        bars = load_daily_series(conn, ticker, START, END)
        if code not in pmaps:
            pmaps[code] = ph.load_phase_map(conn, code)
        phase_by_date = {b.d: ph.phase_at(pmaps[code], b.d) for b in bars}
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
            rs_by_date=rs, phase_by_date=phase_by_date)
    return out


def _benchmark(conn, code_market: str, d0: date, d1: date) -> dict:
    series = load_index_series(conn, code_market, d0, d1)
    ds = sorted(series)
    mult = series[ds[-1]] / series[ds[0]]
    years = (ds[-1] - ds[0]).days / 365.25
    return {"multiple": round(mult, 4),
            "cagr_pct": round((mult ** (1 / years) - 1) * 100, 2)}


SCENARIOS = {
    "S1": {"pyramiding": False, "sell_half": False},
    "S2": {"pyramiding": True, "sell_half": False},
    "S3": {"pyramiding": True, "sell_half": True},
}


def main() -> int:
    from kr_pipeline.db.connection import connect
    with connect() as conn:
        data = load_ticker_data(conn)
        out = {"prereg": "2026-07-02-portfolio-sim-prereg.md", "scenarios": {}}
        curves = {}
        for name, flags in SCENARIOS.items():
            for mode, excl in (("incl", False), ("excl", True)):
                key = f"{name}-{mode}"
                r = run_portfolio(data, PortfolioConfig(
                    exclude_down_phases=excl, **flags))
                curves[key] = r.pop("curve")
                r["stats"].pop("entry_amounts")
                r["stats"].pop("exits")
                out["scenarios"][key] = r
        d0 = date(2021, 1, 4)
        out["benchmark"] = {"KOSPI": _benchmark(conn, "KOSPI", d0, END),
                            "KOSDAQ": _benchmark(conn, "KOSDAQ", d0, END)}
    with open("data/backtest/portfolio_curves_20260702.json", "w",
              encoding="utf-8") as f:
        json.dump(curves, f, ensure_ascii=False)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
