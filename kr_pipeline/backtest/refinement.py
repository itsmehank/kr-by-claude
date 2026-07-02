"""결정론 보정 패키지 + 플라시보 — 사전등록 2026-07-02 §2·§3. 읽기전용.

보정: 5% 추격 룰(max_chase_pct=5.0) + 거래비용(매도연도 세율+수수료) +
청산가 밴드(종가/낙관) + 2025 절단 제외 민감도 + 종목 클러스터 부트스트랩 CI +
§6 미이행 지표(payoff ratio, MDD, promotion 수).
플라시보: 같은 종목·같은 보유 거래일수, 진입일만 무작위(2021-2024) N=1,000.

  python -m kr_pipeline.backtest.refinement          # 보정 리포트 + 플라시보 JSON
"""
from __future__ import annotations

import json
import random
import sys
from datetime import date

from psycopg import Connection

from kr_pipeline.backtest import phases as ph
from kr_pipeline.backtest.backfill import BT_TABLE
from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.profitability_run import DOWN_PHASES, POWER_MIN, _market_of
from kr_pipeline.backtest.trigger_sim import (
    load_watchlist, load_daily_series, load_index_series, classify_rows,
    simulate, market_relative,
)

MAX_CHASE_PCT = 5.0      # prereg §2.1 (백테스트 로컬 — thresholds.py 무접촉)
COMMISSION_RT = 0.03     # prereg §2.2 왕복 수수료 %p
_SELL_TAX = {2021: 0.23, 2022: 0.23, 2023: 0.20, 2024: 0.18, 2025: 0.15}
SEED = 20260702          # prereg §2.5·§3
BOOT_B = 10_000
PLACEBO_N = 1_000
START, END = date(2021, 1, 1), date(2024, 12, 31)
PX_START, PX_END = date(2020, 7, 1), date(2025, 6, 30)


def cost_pct(exit_date: date) -> float:
    """왕복 비용 %p = 매도연도 증권거래세(농특 포함) + 수수료 0.03 (prereg §2.2)."""
    return _SELL_TAX[exit_date.year] + COMMISSION_RT


def aggregate_refined(trades: list[dict]) -> dict[str, dict]:
    """국면별 집계 (excess_net 기준) — §2.6 payoff ratio·MDD 포함."""
    buckets: dict[str, list] = {}
    for t in trades:
        if t.get("phase") is None or t.get("excess_net") is None:
            continue
        buckets.setdefault(t["phase"], []).append(t)
    out: dict[str, dict] = {}
    for phase, ts in buckets.items():
        ex = [t["excess_net"] for t in ts]
        ex_hi = [t["excess_net_hi"] for t in ts]
        wins = [x for x in ex if x > 0]
        losses = [x for x in ex if x <= 0]
        mdds = [t["mdd_pct"] for t in ts if t.get("mdd_pct") is not None]
        out[phase] = {
            "n": len(ts),
            "mean_excess_net": round(sum(ex) / len(ex), 3),
            "mean_excess_net_hi": round(sum(ex_hi) / len(ex_hi), 3),
            "win_rate": round(len(wins) / len(ts), 3),
            "payoff_ratio": (
                round((sum(wins) / len(wins)) / abs(sum(losses) / len(losses)), 3)
                if wins and losses and sum(losses) != 0 else None
            ),
            "mean_pnl_net": round(sum(t["pnl_net"] for t in ts) / len(ts), 3),
            "mean_mdd_pct": round(sum(mdds) / len(mdds), 3) if mdds else None,
            "power": "ok" if len(ts) >= POWER_MIN else "underpowered",
        }
    return out


def cluster_bootstrap_ci(trades: list[dict], *, b: int = BOOT_B,
                         seed: int = SEED, key: str = "excess_net") -> tuple[float, float]:
    """종목 클러스터 부트스트랩 95% percentile CI (prereg §2.5).

    종목 단위 복원추출 → 뽑힌 종목의 트레이드 전부 포함 → mean(key).
    """
    by_ticker: dict[str, list[float]] = {}
    for t in trades:
        if t.get(key) is None:
            continue
        by_ticker.setdefault(t["ticker"], []).append(t[key])
    tickers = sorted(by_ticker)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(b):
        vals: list[float] = []
        for _ in range(len(tickers)):
            vals.extend(by_ticker[rng.choice(tickers)])
        means.append(sum(vals) / len(vals))
    means.sort()
    lo = means[int(0.025 * b)]
    hi = means[min(int(0.975 * b), b - 1)]
    return (round(lo, 3), round(hi, 3))


def _mdd_pct(bars, entry_i: int, exit_i: int, entry_close: float) -> float:
    """보유 중 최대낙폭: entry_close 대비 최저 종가 % (prereg §2.6)."""
    lowest = min(bars[i].close for i in range(entry_i, exit_i + 1))
    return round((lowest / entry_close - 1) * 100, 2)


def build_refined_trades(conn: Connection) -> tuple[list[dict], int]:
    """보정 트레이드 셋(5% 룰 + 비용 + 밴드 + MDD) + promotion 총수."""
    pmaps: dict[str, list] = {}
    idx_cache: dict[str, dict] = {}
    out: list[dict] = []
    promotions = 0
    for ticker in FROZEN_SAMPLE:
        market = _market_of(conn, ticker)
        code = ph.INDEX_OF.get(market, "1001")
        if code not in pmaps:
            pmaps[code] = ph.load_phase_map(conn, code)
        if market not in idx_cache:
            idx_cache[market] = load_index_series(conn, market, PX_START, PX_END)
        wr = load_watchlist(conn, ticker, START, END, table=BT_TABLE)
        bars = load_daily_series(conn, ticker, PX_START, PX_END)
        date_i = {b.d: i for i, b in enumerate(bars)}
        cls = classify_rows(wr)
        trades, promo = simulate(ticker, cls["production"], bars,
                                 mode="production", max_chase_pct=MAX_CHASE_PCT)
        promotions += promo
        for t in trades:
            if t.pnl_pct is None or t.exit_date is None:
                continue
            excess = market_relative(t, idx_cache[market])
            if excess is None:
                continue
            cost = cost_pct(t.exit_date)
            pnl_hi = (t.exit_close_optimistic / t.entry_close - 1) * 100
            index_pct = t.pnl_pct - excess
            out.append({
                "ticker": ticker, "market": market,
                "entry_date": t.entry_date, "exit_date": t.exit_date,
                "phase": ph.phase_at(pmaps[code], t.entry_date),
                "binding_exit": t.binding_exit,
                "hold_days": date_i[t.exit_date] - date_i[t.entry_date],
                "pnl_net": round(t.pnl_pct - cost, 2),
                "excess_net": round(t.pnl_pct - cost - index_pct, 2),
                "excess_net_hi": round(pnl_hi - cost - index_pct, 2),
                "mdd_pct": _mdd_pct(bars, date_i[t.entry_date],
                                    date_i[t.exit_date], t.entry_close),
            })
    return out, promotions


def run_placebo(conn: Connection, trades: list[dict], *,
                n_sets: int = PLACEBO_N, seed: int = SEED) -> dict:
    """보유기간-매칭 무작위 진입 플라시보 (prereg §3)."""
    rng = random.Random(seed)
    bars_cache: dict[str, list] = {}
    idx_cache: dict[str, dict] = {}
    candidates: list[tuple] = []      # (ticker, market, hold, [유효 진입 인덱스])
    for t in trades:
        tk = t["ticker"]
        if tk not in bars_cache:
            bars_cache[tk] = load_daily_series(conn, tk, PX_START, PX_END)
        if t["market"] not in idx_cache:
            idx_cache[t["market"]] = load_index_series(conn, t["market"], PX_START, PX_END)
        bars = bars_cache[tk]
        hold = t["hold_days"]
        valid = [i for i, b in enumerate(bars)
                 if START <= b.d <= END and i + hold < len(bars)]
        if valid:
            candidates.append((tk, t["market"], hold, valid))

    def _nearest(series: dict, d: date):
        ks = [k for k in series if k <= d]
        return series[max(ks)] if ks else None

    set_means: list[float] = []
    for _ in range(n_sets):
        exs: list[float] = []
        for tk, mkt, hold, valid in candidates:
            bars = bars_cache[tk]
            i = rng.choice(valid)
            j = i + hold
            pnl = (bars[j].close / bars[i].close - 1) * 100 - cost_pct(bars[j].d)
            base = _nearest(idx_cache[mkt], bars[i].d)
            end_v = _nearest(idx_cache[mkt], bars[j].d)
            if base and end_v:
                exs.append(pnl - (end_v / base - 1) * 100)
        if exs:
            set_means.append(sum(exs) / len(exs))
    actual = sum(t["excess_net"] for t in trades) / len(trades)
    ge = sum(1 for m in set_means if m >= actual)
    return {
        "n_sets": len(set_means), "n_paired_trades": len(candidates),
        "actual_mean_excess_net": round(actual, 3),
        "placebo_mean_of_means": round(sum(set_means) / len(set_means), 3),
        "placebo_p95": round(sorted(set_means)[int(0.95 * len(set_means))], 3),
        "p_value_one_sided": round((ge + 1) / (len(set_means) + 1), 4),
    }


def run_refinement(conn: Connection) -> dict:
    trades, promotions = build_refined_trades(conn)
    in_window = [t for t in trades if t["entry_date"] <= END]
    ci_all = cluster_bootstrap_ci(trades)
    ci_phase = {p: cluster_bootstrap_ci([t for t in trades if t["phase"] == p])
                for p in {t["phase"] for t in trades if t["phase"]}}
    placebo = run_placebo(conn, trades)
    mean_all = round(sum(t["excess_net"] for t in trades) / len(trades), 3)
    return {
        "prereg": "2026-07-02-backtest-refinement-prereg.md §2·§3",
        "params": {"max_chase_pct": MAX_CHASE_PCT, "commission_rt": COMMISSION_RT,
                   "sell_tax": _SELL_TAX, "seed": SEED, "bootstrap_b": BOOT_B,
                   "placebo_n": PLACEBO_N},
        "n_trades": len(trades),
        "promotions": promotions,
        "mean_excess_net_all": mean_all,
        "ci95_mean_excess_net_all": ci_all,
        "ci95_contains_zero": ci_all[0] <= 0.0 <= ci_all[1],
        "by_phase": aggregate_refined(trades),
        "ci95_by_phase": ci_phase,
        "sensitivity_excl_2025_entries": {
            "n": len(in_window),
            "mean_excess_net": round(
                sum(t["excess_net"] for t in in_window) / len(in_window), 3)
            if in_window else None,
            "by_phase": aggregate_refined(in_window),
        },
        "placebo": placebo,
        "trades": [{**t, "entry_date": str(t["entry_date"]),
                    "exit_date": str(t["exit_date"])} for t in trades],
    }


def main() -> int:
    from kr_pipeline.db.connection import connect
    with connect() as conn:
        out = run_refinement(conn)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
