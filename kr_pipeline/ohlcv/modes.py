from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
import logging

from psycopg import Connection

from kr_pipeline.db.runs import run_tracking
from kr_pipeline.ohlcv.fetch import fetch_many, fetch_index
from kr_pipeline.ohlcv.transform import merge_raw_and_adjusted, to_price_rows
from kr_pipeline.ohlcv.store import upsert_daily_prices, update_adj_close_only, upsert_index_daily


log = logging.getLogger("kr_pipeline.ohlcv")


def pd_isna(x):
    import pandas as pd
    try:
        return pd.isna(x)
    except Exception:
        return x is None


class Mode(str, Enum):
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"
    FULL_REFRESH = "full-refresh"


def _get_db_min_date(conn: Connection) -> date:
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(date) FROM daily_prices")
        row = cur.fetchone()
        return row[0] if row and row[0] else date.today()


def compute_date_range(
    mode: Mode,
    *,
    years: int = 2,
    window_days: int = 30,
    conn: Connection | None = None,
) -> tuple[date, date]:
    today = date.today()
    if mode == Mode.BACKFILL:
        return today - timedelta(days=365 * years), today - timedelta(days=1)
    if mode == Mode.INCREMENTAL:
        return today - timedelta(days=window_days), today
    if mode == Mode.FULL_REFRESH:
        return _get_db_min_date(conn), today - timedelta(days=1)
    raise ValueError(f"Unknown mode: {mode}")


def _load_active_tickers(conn: Connection, limit: int | None = None) -> list[str]:
    with conn.cursor() as cur:
        sql = "SELECT ticker FROM stocks WHERE delisted_at IS NULL ORDER BY ticker"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]


@dataclass
class RunStats:
    rows_affected: int
    failures: list[tuple[str, str]]


def run(
    conn: Connection,
    mode: Mode,
    *,
    years: int = 2,
    window_days: int = 30,
    limit_tickers: int | None = None,
    max_workers: int = 3,
) -> RunStats:
    params = {
        "years": years if mode == Mode.BACKFILL else None,
        "window_days": window_days if mode == Mode.INCREMENTAL else None,
        "limit_tickers": limit_tickers,
    }
    params = {k: v for k, v in params.items() if v is not None}

    start, end = compute_date_range(mode, years=years, window_days=window_days, conn=conn)
    log.info(f"mode={mode.value} range={start}..{end}")

    tickers = _load_active_tickers(conn, limit=limit_tickers)
    log.info(f"tickers to process: {len(tickers)}")

    with run_tracking(conn, pipeline="ohlcv", mode=mode.value, params={**params, "start": str(start), "end": str(end)}):
        if mode == Mode.FULL_REFRESH:
            return _run_full_refresh(conn, tickers, start, end, max_workers)
        return _run_upsert(conn, tickers, start, end, max_workers)


def _run_upsert(conn, tickers, start, end, max_workers) -> RunStats:
    successes, failures = fetch_many(tickers, start, end, max_workers=max_workers)
    rows_total = 0
    for ticker, (raw, adj) in successes.items():
        if raw.empty:
            continue
        merged = merge_raw_and_adjusted(raw, adj)
        rows = to_price_rows(ticker, merged)
        rows_total += upsert_daily_prices(conn, rows)
        conn.commit()

    # 지수
    for index_code in ("1001", "2001"):
        idx_df = fetch_index(index_code, start, end)
        if idx_df.empty:
            continue
        idx_rows = [
            (index_code, r["date"], int(r["open"]), int(r["high"]), int(r["low"]),
             int(r["close"]),
             int(r["volume"]) if not pd_isna(r.get("volume")) else None,
             int(r["value"]) if not pd_isna(r.get("value")) else None)
            for _, r in idx_df.iterrows()
        ]
        upsert_index_daily(conn, idx_rows)
        conn.commit()

    return RunStats(rows_affected=rows_total, failures=failures)


def _run_full_refresh(conn, tickers, start, end, max_workers) -> RunStats:
    """수정종가만 갱신."""
    from kr_pipeline.ohlcv.fetch import _fetch_one
    import time

    rows_total = 0
    failures = []
    for ticker in tickers:
        try:
            adj = _fetch_one(ticker, start, end, adjusted=True)
            if adj.empty:
                continue
            rows = [(ticker, r["date"], float(r["close"])) for _, r in adj.iterrows()]
            rows_total += update_adj_close_only(conn, rows)
            conn.commit()
            time.sleep(0.1)
        except Exception as e:
            failures.append((ticker, str(e)))

    return RunStats(rows_affected=rows_total, failures=failures)
