from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
import logging

from psycopg import Connection

from kr_pipeline.db.runs import run_tracking
from kr_pipeline.ohlcv.fetch import fetch_many, fetch_index
from kr_pipeline.ohlcv.transform import merge_raw_and_adjusted, to_price_rows, to_index_rows
from kr_pipeline.ohlcv.store import upsert_daily_prices, update_adj_prices, upsert_index_daily


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
    exclude_today: bool = False,
) -> tuple[date, date]:
    """모드별 일봉 fetch 범위.

    exclude_today: INCREMENTAL 에서 end 를 어제로 당김 (장중 수동 실행 시 오늘 *미확정*
        부분봉 회피용 opt-in). 기본 False = end=today — 마감 후 cron 이 당일 확정봉을
        같은 날 적재하는 동작을 보존. BACKFILL/FULL_REFRESH 는 이미 end=어제라 무영향.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)
    if mode == Mode.BACKFILL:
        return today - timedelta(days=365 * years), yesterday
    if mode == Mode.INCREMENTAL:
        return today - timedelta(days=window_days), (yesterday if exclude_today else today)
    if mode == Mode.FULL_REFRESH:
        return _get_db_min_date(conn), yesterday
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
    warnings: list[str] = field(default_factory=list)


def _run_sanity_checks(conn: Connection, mode: Mode) -> list[str]:
    """OHLCV 적재 후 데이터 sanity 검증. 경고 메시지 리스트 반환 (실패 아님).

    검증 항목:
    1. 최근 영업일 커버리지: daily_prices 의 가장 최근 날짜에 들어온 종목 수가
       활성 universe 의 80% 미만이면 경고.
    2. 가격 이상치: close <= 0 또는 adj_close <= 0 인 행이 있으면 경고.

    full-refresh 모드는 새 행을 추가하지 않으므로 커버리지 검증을 건너뜀.
    """
    warnings: list[str] = []

    with conn.cursor() as cur:
        # 검증 1: 최근 영업일 커버리지 (full-refresh 제외)
        if mode != Mode.FULL_REFRESH:
            cur.execute("""
                SELECT COUNT(DISTINCT ticker)
                  FROM daily_prices
                 WHERE date = (SELECT MAX(date) FROM daily_prices)
            """)
            coverage_count = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(*) FROM stocks WHERE delisted_at IS NULL")
            active_count = cur.fetchone()[0] or 0

            if active_count > 0:
                ratio = coverage_count / active_count
                if ratio < 0.80:
                    warnings.append(
                        f"coverage_low: 최근 영업일 일봉 수신 종목 {coverage_count}/{active_count} "
                        f"({ratio*100:.1f}%, 임계 80%)"
                    )

        # 검증 2: 이상치
        cur.execute("""
            SELECT COUNT(*) FROM daily_prices
             WHERE close <= 0 OR adj_close <= 0
        """)
        bad_price_count = cur.fetchone()[0] or 0
        if bad_price_count > 0:
            warnings.append(f"bad_prices: {bad_price_count} 행이 close 또는 adj_close <= 0")

    return warnings


def run(
    conn: Connection,
    mode: Mode,
    *,
    years: int = 2,
    window_days: int = 30,
    limit_tickers: int | None = None,
    max_workers: int = 3,
    exclude_today: bool = False,
) -> RunStats:
    params = {
        "years": years if mode == Mode.BACKFILL else None,
        "window_days": window_days if mode == Mode.INCREMENTAL else None,
        "limit_tickers": limit_tickers,
        "exclude_today": exclude_today if (mode == Mode.INCREMENTAL and exclude_today) else None,
    }
    params = {k: v for k, v in params.items() if v is not None}

    start, end = compute_date_range(
        mode, years=years, window_days=window_days, conn=conn, exclude_today=exclude_today,
    )
    log.info(f"mode={mode.value} range={start}..{end}")

    tickers = _load_active_tickers(conn, limit=limit_tickers)
    log.info(f"tickers to process: {len(tickers)}")

    with run_tracking(conn, pipeline="ohlcv", mode=mode.value, params={**params, "start": str(start), "end": str(end)}) as state:
        if mode == Mode.FULL_REFRESH:
            stats = _run_full_refresh(conn, tickers, start, end, max_workers, mode)
        else:
            stats = _run_upsert(conn, tickers, start, end, max_workers, mode)
        state["warnings"].extend(stats.warnings)
        state["rows_affected"] = stats.rows_affected
        return stats


def _run_upsert(conn, tickers, start, end, max_workers, mode: Mode) -> RunStats:
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
        idx_rows = to_index_rows(index_code, idx_df)
        upsert_index_daily(conn, idx_rows)
        conn.commit()

    warnings = _run_sanity_checks(conn, mode)
    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings)


def _run_full_refresh(conn, tickers, start, end, max_workers, mode: Mode = Mode.FULL_REFRESH) -> RunStats:
    """수정 OHLCV(adj_close/adj_high/adj_low/adj_open/adj_volume) 갱신. 종목별 실패는 끝에서 1회 재시도."""
    import time
    from kr_pipeline.ohlcv.fetch import fetch_adj_only

    def _process_ticker(ticker: str) -> int:
        """한 종목의 수정 OHLCV(종가/고가/저가/시가/거래량)를 가져와 업데이트. 영향받은 행 수 반환."""
        adj = fetch_adj_only(ticker, start, end)
        if adj.empty:
            return 0
        rows = [
            (ticker, r["date"], float(r["close"]), float(r["high"]), float(r["low"]),
             float(r["open"]), float(r["volume"]))
            for _, r in adj.iterrows()
        ]
        affected = update_adj_prices(conn, rows)
        conn.commit()
        return affected

    rows_total = 0
    failures: list[tuple[str, str]] = []
    for i, ticker in enumerate(tickers, 1):
        try:
            rows_total += _process_ticker(ticker)
            time.sleep(0.1)
        except Exception as e:
            failures.append((ticker, str(e)))
        if i % 100 == 0:
            log.info(f"full-refresh progress: {i}/{len(tickers)} (failures so far: {len(failures)})")

    # 1차 실패 재시도 (fetch_many 와 같은 패턴)
    if failures:
        log.warning(f"Retrying {len(failures)} failed tickers in full-refresh")
        retry_failures: list[tuple[str, str]] = []
        for ticker, _ in failures:
            try:
                rows_total += _process_ticker(ticker)
                time.sleep(0.2)  # 살짝 더 긴 sleep 으로 부드럽게 재시도
            except Exception as e:
                retry_failures.append((ticker, str(e)))
        failures = retry_failures
        if failures:
            log.warning(f"After retry, {len(failures)} tickers still failed")

    warnings = _run_sanity_checks(conn, mode)
    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings)
