"""수익성·강건성 백테스트 분석 드라이버 — 국면별 집계 + §7 사전등록 기준 판정. 읽기전용.

입력 분류 = backtest_classification(전용 테이블). 트리거·청산 = 기존 결정론 엔진.
산출 = 트레이드별 (P&L·시장대비 초과수익·진입일 국면) + 국면별 집계 + §7 판정.
"""
from __future__ import annotations

from datetime import date

from psycopg import Connection

from kr_pipeline.backtest import phases as ph
from kr_pipeline.backtest.backfill import BT_TABLE
from kr_pipeline.backtest.trigger_sim import (
    load_watchlist, load_daily_series, load_index_series, classify_rows,
    simulate, market_relative,
)

DOWN_PHASES = ("downtrend", "correction")
POWER_MIN = 10   # §7.5: 국면별 트레이드 < 10 → underpowered


def _market_of(conn: Connection, ticker: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT market FROM stocks WHERE ticker = %s", (ticker,))
        return cur.fetchone()[0]


def entry_rate_by_phase(conn: Connection, tickers: list[str]) -> dict[str, dict]:
    """분류점(BT_TABLE 행) 기준 국면별 entry-rate. 국면 = analyzed_for_date 의 시장상태."""
    pmaps: dict[str, list] = {}
    counts: dict[str, dict] = {}
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT b.symbol, b.analyzed_for_date, b.classification, s.market "
            f"FROM {BT_TABLE} b JOIN stocks s ON s.ticker = b.symbol "
            f"WHERE b.symbol = ANY(%s)",
            (tickers,),
        )
        rows = cur.fetchall()
    for symbol, afd, cls, market in rows:
        code = ph.INDEX_OF.get(market, "1001")
        if code not in pmaps:
            pmaps[code] = ph.load_phase_map(conn, code)
        phase = ph.phase_at(pmaps[code], afd)
        if phase is None:
            continue
        c = counts.setdefault(phase, {"entry": 0, "total": 0})
        c["total"] += 1
        if cls == "entry":
            c["entry"] += 1
    for phase, c in counts.items():
        c["rate"] = (c["entry"] / c["total"]) if c["total"] else 0.0
    return counts


def aggregate_trades(trades: list[dict]) -> dict[str, dict]:
    """국면별 트레이드 집계. phase=None(라벨 없음) 제외. excess_pct None 도 제외."""
    buckets: dict[str, list] = {}
    for t in trades:
        if t.get("phase") is None or t.get("excess_pct") is None:
            continue
        buckets.setdefault(t["phase"], []).append(t)
    out: dict[str, dict] = {}
    for phase, ts in buckets.items():
        ex = [t["excess_pct"] for t in ts]
        wins = sum(1 for t in ts if t["excess_pct"] > 0)
        out[phase] = {
            "n": len(ts),
            "mean_excess": round(sum(ex) / len(ex), 3),
            "win_rate": round(wins / len(ts), 3),
            "mean_pnl": round(sum(t["pnl_pct"] for t in ts) / len(ts), 3),
        }
    return out


def evaluate_criteria(entry_rates: dict[str, dict], trade_aggs: dict[str, dict]) -> dict:
    """§7.1(분류층 게이트 방어, 1차) + §7.2(초과수익, 보조) + §7.5(검정력 가드)."""
    down_entry = sum(entry_rates.get(p, {}).get("entry", 0) for p in DOWN_PHASES)
    down_total = sum(entry_rates.get(p, {}).get("total", 0) for p in DOWN_PHASES)
    r_down = (down_entry / down_total) if down_total else 0.0
    r_up = entry_rates.get("confirmed_uptrend", {}).get("rate", 0.0)
    ratio = (r_down / r_up) if r_up else None
    gate_71 = {
        "r_down": round(r_down, 3), "r_up": round(r_up, 3),
        "ratio": round(ratio, 3) if ratio is not None else None,
        "pass": (ratio is not None and ratio <= 0.5),
        "note": "R_up=0 이면 ratio 미정의 — 수동 해석" if ratio is None else "",
    }
    down_excess = [trade_aggs.get(p, {}).get("mean_excess") for p in DOWN_PHASES
                   if p in trade_aggs]
    excess_72 = {
        "down_mean_excess": down_excess,
        "supportive": all(x is not None and x >= 0 for x in down_excess) if down_excess else None,
        "note": "보조 지표 — §4 트리거 누수 영향. 음수≠게이트 실패(§7.1로 판정).",
    }
    power = {p: ("ok" if trade_aggs.get(p, {}).get("n", 0) >= POWER_MIN else "underpowered")
             for p in set(list(trade_aggs) + list(DOWN_PHASES) + ["confirmed_uptrend", "rally_attempt"])}
    return {"gate_defense_71": gate_71, "excess_72": excess_72, "power_guard": power}


def run_analysis(conn: Connection, tickers: list[str], px_start: date, px_end: date,
                 watch_start: date, watch_end: date) -> dict:
    """전체 산출: 트레이드(production)별 진입일 국면 라벨 + 국면별 집계 + §7 판정."""
    pmaps: dict[str, list] = {}
    all_trades: list[dict] = []
    for ticker in tickers:
        market = _market_of(conn, ticker)
        code = ph.INDEX_OF.get(market, "1001")
        if code not in pmaps:
            pmaps[code] = ph.load_phase_map(conn, code)
        wr = load_watchlist(conn, ticker, watch_start, watch_end, table=BT_TABLE)
        bars = load_daily_series(conn, ticker, px_start, px_end)
        idx = load_index_series(conn, market, px_start, px_end)
        cls = classify_rows(wr)
        prod_trades, _ = simulate(ticker, cls["production"], bars, mode="production")
        for t in prod_trades:
            excess = market_relative(t, idx)
            all_trades.append({
                "ticker": t.ticker, "entry_date": str(t.entry_date),
                "exit_date": str(t.exit_date) if t.exit_date else None,
                "pnl_pct": round(t.pnl_pct, 2) if t.pnl_pct is not None else None,
                "excess_pct": round(excess, 2) if excess is not None else None,
                "binding_exit": t.binding_exit,
                "phase": ph.phase_at(pmaps[code], t.entry_date),
            })
    entry_rates = entry_rate_by_phase(conn, tickers)
    trade_aggs = aggregate_trades(all_trades)
    criteria = evaluate_criteria(entry_rates, trade_aggs)
    return {"n_tickers": len(tickers), "n_trades": len(all_trades),
            "entry_rates": entry_rates, "trade_aggs": trade_aggs,
            "criteria": criteria, "trades": all_trades}
