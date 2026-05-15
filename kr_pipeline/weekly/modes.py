"""weekly 모드 분기 + 오케스트레이션."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
import logging

from psycopg import Connection

from kr_pipeline.db.runs import run_tracking
from kr_pipeline.weekly.load import (
    load_daily_for_ticker, load_index_daily, load_active_tickers, get_daily_min_date,
)
from kr_pipeline.weekly.transform import (
    aggregate_to_weekly, drop_incomplete_weeks, to_weekly_rows, to_weekly_index_rows,
)
from kr_pipeline.weekly.store import upsert_weekly_prices, upsert_weekly_index


log = logging.getLogger("kr_pipeline.weekly")


class Mode(str, Enum):
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"
    FULL_REFRESH = "full-refresh"


@dataclass
class RunStats:
    rows_affected: int
    failures: list[tuple[str, str]]
    warnings: list[str] = field(default_factory=list)


def _get_daily_min_date(conn: Connection) -> date:
    d = get_daily_min_date(conn)
    return d if d else date.today()


def compute_date_range(
    mode: Mode,
    *,
    window_weeks: int = 4,
    conn: Connection | None = None,
) -> tuple[date, date]:
    """모드별 일봉 SELECT 범위. end 는 항상 어제까지."""
    today = date.today()
    yesterday = today - timedelta(days=1)

    if mode == Mode.INCREMENTAL:
        return today - timedelta(days=window_weeks * 7), yesterday
    if mode in (Mode.BACKFILL, Mode.FULL_REFRESH):
        return _get_daily_min_date(conn), yesterday
    raise ValueError(f"Unknown mode: {mode}")


def _process_ticker(
    conn: Connection,
    ticker: str,
    start: date,
    end: date,
    today: date,
) -> int:
    """한 종목: SELECT 일봉 → 집계 → UPSERT. 영향받은 행수 반환."""
    daily = load_daily_for_ticker(conn, ticker, start, end)
    if daily.empty:
        return 0
    weekly = aggregate_to_weekly(daily)
    weekly = drop_incomplete_weeks(weekly, today)
    if weekly.empty:
        return 0
    rows = to_weekly_rows(ticker, weekly)
    affected = upsert_weekly_prices(conn, rows)
    conn.commit()
    return affected


def _process_index(
    conn: Connection,
    index_code: str,
    start: date,
    end: date,
    today: date,
) -> int:
    """한 지수: SELECT → 집계 → UPSERT."""
    daily = load_index_daily(conn, index_code, start, end)
    if daily.empty:
        return 0
    weekly = aggregate_to_weekly(daily)
    weekly = drop_incomplete_weeks(weekly, today)
    if weekly.empty:
        return 0
    rows = to_weekly_index_rows(index_code, weekly)
    affected = upsert_weekly_index(conn, rows)
    conn.commit()
    return affected


def _run_sanity_checks(conn: Connection) -> list[str]:
    """주봉 적재 후 sanity 검증."""
    warnings: list[str] = []
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(DISTINCT ticker) FROM weekly_prices
             WHERE week_end_date = (SELECT MAX(week_end_date) FROM weekly_prices)
        """)
        weekly_count = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM stocks WHERE delisted_at IS NULL")
        active_count = cur.fetchone()[0] or 0
        if active_count > 0:
            ratio = weekly_count / active_count
            if ratio < 0.90:
                warnings.append(
                    f"coverage_low: 최근 주봉 종목 {weekly_count}/{active_count} "
                    f"({ratio*100:.1f}%, 임계 90%)"
                )

        cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE close <= 0 OR adj_close <= 0")
        bad_price = cur.fetchone()[0] or 0
        if bad_price > 0:
            warnings.append(f"bad_prices: {bad_price} 행이 close 또는 adj_close <= 0")

        cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE trading_days = 0")
        zero_days = cur.fetchone()[0] or 0
        if zero_days > 0:
            warnings.append(f"zero_trading_days: {zero_days} 행이 trading_days = 0")
    return warnings


def run(
    conn: Connection,
    mode: Mode,
    *,
    window_weeks: int = 4,
    limit_tickers: int | None = None,
) -> RunStats:
    today = date.today()
    start, end = compute_date_range(mode, window_weeks=window_weeks, conn=conn)
    log.info(f"weekly mode={mode.value} range={start}..{end}")

    tickers = load_active_tickers(conn, limit=limit_tickers)
    log.info(f"weekly tickers to process: {len(tickers)}")

    params = {
        "window_weeks": window_weeks if mode == Mode.INCREMENTAL else None,
        "limit_tickers": limit_tickers,
        "start": str(start),
        "end": str(end),
    }
    params = {k: v for k, v in params.items() if v is not None}

    rows_total = 0
    failures: list[tuple[str, str]] = []

    with run_tracking(conn, pipeline="weekly", mode=mode.value, params=params) as state:
        for i, ticker in enumerate(tickers, 1):
            try:
                rows_total += _process_ticker(conn, ticker, start, end, today)
            except Exception as e:
                failures.append((ticker, str(e)))
            if i % 100 == 0:
                log.info(f"weekly progress: {i}/{len(tickers)} (failures: {len(failures)})")

        if failures:
            log.warning(f"Retrying {len(failures)} failed tickers")
            retry_failures: list[tuple[str, str]] = []
            for ticker, _ in failures:
                try:
                    rows_total += _process_ticker(conn, ticker, start, end, today)
                except Exception as e:
                    retry_failures.append((ticker, str(e)))
            failures = retry_failures

        for index_code in ("1001", "2001"):
            try:
                rows_total += _process_index(conn, index_code, start, end, today)
            except Exception as e:
                failures.append((index_code, str(e)))

        warnings = _run_sanity_checks(conn)
        state["warnings"].extend(warnings)

    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings)
