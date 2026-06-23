"""CLI: 8종목 2024 결정론 트리거+P&L 시뮬 (production + shadow). 읽기전용."""
from __future__ import annotations

import json
from datetime import date

from kr_pipeline.db.connection import connect
from kr_pipeline.backtest.trigger_sim import (
    load_watchlist, load_daily_series, load_index_series, classify_rows,
    simulate, market_relative,
)

TICKERS = ["003230", "101930", "399720", "200470", "257720", "000320", "900340", "267260"]
START, END = date(2024, 1, 6), date(2024, 12, 28)
PX_START, PX_END = date(2024, 1, 1), date(2025, 6, 30)  # forward 가격 포함


def _market_of(conn, ticker: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT market FROM stocks WHERE ticker = %s", (ticker,))
        return cur.fetchone()[0]


def _trade_row(t, idx):
    return {
        "ticker": t.ticker, "watch_reason": t.watch_reason, "pivot_sat": str(t.pivot_sat),
        "entry_date": str(t.entry_date), "entry_close": t.entry_close,
        "exit_date": str(t.exit_date), "exit_close": t.exit_close,
        "pnl_pct": round(t.pnl_pct, 1) if t.pnl_pct is not None else None,
        "excess_pct": round(market_relative(t, idx), 1) if market_relative(t, idx) is not None else None,
        "binding_exit": t.binding_exit,
    }


def main() -> int:
    out = {"production": [], "shadow": [], "census": {"no_pivot": 0, "promotion_fires": 0},
           "counts": {"production": 0, "shadow": 0, "census": 0}}
    with connect() as conn:
        for ticker in TICKERS:
            market = _market_of(conn, ticker)
            wr = load_watchlist(conn, ticker, START, END)
            bars = load_daily_series(conn, ticker, PX_START, PX_END)
            idx = load_index_series(conn, market, PX_START, PX_END)
            cls = classify_rows(wr)
            out["counts"]["production"] += len(cls["production"])
            out["counts"]["shadow"] += len(cls["shadow"])
            out["counts"]["census"] += len(cls["census"])
            out["census"]["no_pivot"] += len(cls["census"])
            # production: 적격 행만 active pivot 으로 (실제 시스템 행동)
            prod_trades, promo = simulate(ticker, cls["production"], bars, mode="production")
            out["census"]["promotion_fires"] += promo
            for t in prod_trades:
                out["production"].append(_trade_row(t, idx))
            # shadow: 비적격(pivot有) 행을 게이트 우회로. promotion 반환값(_)은 의도적으로 버림 —
            # census 의 promotion_fires 는 production(적격 watch) 한정 지표이므로 shadow promotion 은 세지 않는다.
            shadow_trades, _ = simulate(ticker, cls["shadow"], bars, mode="shadow")
            for t in shadow_trades:
                out["shadow"].append(_trade_row(t, idx))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
