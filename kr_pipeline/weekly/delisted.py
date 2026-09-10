"""(#181 B2) 상폐 주봉 — delisted_daily_prices_adj(B1 결과) → aggregate_to_weekly(순수 함수) →
delisted_weekly_prices. weekly_prices 무접촉(격리 원칙, #114 스펙 §3).

라이브 주봉과의 차이(사실): 라이브는 daily_prices.adj_close 가 NOT NULL(정지일 carry)이라 주봉
adj_close 도 항상 존재하지만, B1 은 zero-bar 행의 adj_close 를 NULL 로 두므로 한 주 전체가
zero-bar 인 주는 adj_close 가 NULL 이다(last() 는 NaN 건너뛰지 않음 → 그 주 마지막 행 기준).
"""
from __future__ import annotations

import pandas as pd
from psycopg import Connection

from kr_pipeline.weekly.transform import WEEKLY_COLUMNS, aggregate_to_weekly

_DAILY_COLS = ("date", "open", "high", "low", "close", "adj_close", "adj_high", "adj_low",
               "adj_open", "adj_volume", "volume", "value")


def load_delisted_daily(conn: Connection, ticker: str) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(_DAILY_COLS)} FROM delisted_daily_prices_adj "
            "WHERE ticker = %s ORDER BY date", (ticker,))
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=list(_DAILY_COLS))
    for c in _DAILY_COLS[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _v(x):
    return None if x is None or (isinstance(x, float) and pd.isna(x)) or pd.isna(x) else x


def build_delisted_weekly(conn: Connection, tickers: list[str] | None = None) -> dict:
    """종목 단위 DELETE→COPY(멱등). 반환 {tickers, rows}."""
    stats = {"tickers": 0, "rows": 0}
    with conn.cursor() as cur:
        if tickers is None:
            cur.execute("SELECT DISTINCT ticker FROM delisted_daily_prices ORDER BY 1")
            tickers = [r[0] for r in cur.fetchall()]
        for t in tickers:
            daily = load_delisted_daily(conn, t)
            if daily.empty:
                continue
            wk = aggregate_to_weekly(daily)
            cur.execute("DELETE FROM delisted_weekly_prices WHERE ticker = %s", (t,))
            cols = ["ticker", *WEEKLY_COLUMNS]
            with cur.copy(f"COPY delisted_weekly_prices ({', '.join(cols)}) FROM STDIN") as cp:
                for _, r in wk.iterrows():
                    cp.write_row((t, r["week_end_date"], _v(r["open"]), _v(r["high"]), _v(r["low"]),
                                  _v(r["close"]), _v(r["adj_close"]), _v(r["adj_high"]), _v(r["adj_low"]),
                                  _v(r["adj_open"]), _v(r["adj_volume"]), int(r["volume"]) if _v(r["volume"]) is not None else 0,
                                  int(r["value"]) if _v(r["value"]) is not None else 0, int(r["trading_days"])))
            stats["rows"] += len(wk)
            stats["tickers"] += 1
            conn.commit()
    return stats
