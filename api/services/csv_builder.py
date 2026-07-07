"""indicators → CSV bytes."""
import csv
import io
from datetime import date

from psycopg import Connection


# 가격·거래량은 daily_prices 권위 소스. 지표는 daily_indicators.
# Phase 0 fix — partial intraday snapshot 오염 방지 (검증자 v2 §4).

DAILY_INDICATOR_COLUMNS = [
    "sma_10", "sma_21", "sma_50", "sma_150", "sma_200",
    "w52_high", "w52_low",
    "rs_line", "rs_rating",
    "minervini_pass",
    "avg_volume_50d", "volume_ratio_50d",
    "pocket_pivot_flag", "distribution_day_flag",
]


def build_daily_csv(conn: Connection, ticker: str, days: int = 60, on_date: date | None = None) -> bytes:
    """daily_prices(가격·거래량) + daily_indicators(지표) JOIN → CSV bytes.

    on_date 제공 시 그 날짜 이하 최신 days 개. None이면 최신 days 개.
    """
    indicator_cols_sql = ", ".join(f"i.{c}" for c in DAILY_INDICATOR_COLUMNS)
    date_filter = "AND p.date <= %(on_date)s" if on_date is not None else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            -- volume 은 adj 우선 (payload_builder 와 동일 도메인 — 같은 LLM 입력에서
            -- payload(adj)와 daily.csv(raw)가 갈리면 기업행위 종목의 같은 날 거래량이
            -- 두 숫자로 노출됨). adj_volume NULL(거래정지 등)이면 raw 폴백.
            SELECT p.date, p.adj_close,
                   ROUND(COALESCE(p.adj_volume, p.volume))::bigint AS volume,
                   {indicator_cols_sql}
              FROM daily_prices p
              LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = %(ticker)s {date_filter}
             ORDER BY p.date DESC
             LIMIT %(days)s
            """,
            {"ticker": ticker, "days": days, "on_date": on_date},
        )
        rows = cur.fetchall()
    rows = list(reversed(rows))

    buf = io.StringIO()
    writer = csv.writer(buf)
    header = ["date", "adj_close", "volume"] + DAILY_INDICATOR_COLUMNS
    writer.writerow(header)
    for row in rows:
        writer.writerow([_fmt(v) for v in row])
    return buf.getvalue().encode("utf-8")


WEEKLY_COLUMNS = [
    "week_end_date", "adj_close", "volume",
    "sma_10w", "sma_30w", "sma_40w",
    "w52_high", "w52_low",
    "rs_line", "rs_rating", "minervini_pass",
]


def build_weekly_csv(conn: Connection, ticker: str, weeks: int = 104, on_date: date | None = None) -> bytes:
    cols_sql = ", ".join(WEEKLY_COLUMNS)
    date_filter = "AND week_end_date <= %(on_date)s" if on_date is not None else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {cols_sql}
              FROM weekly_indicators
             WHERE ticker = %(ticker)s {date_filter}
             ORDER BY week_end_date DESC
             LIMIT %(weeks)s
            """,
            {"ticker": ticker, "weeks": weeks, "on_date": on_date},
        )
        rows = cur.fetchall()
    rows = list(reversed(rows))

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(WEEKLY_COLUMNS)
    for row in rows:
        writer.writerow([_fmt(v) for v in row])
    return buf.getvalue().encode("utf-8")


INDEX_COLUMNS_DAILY = ["date", "open", "high", "low", "close", "volume", "value"]


def build_index_csv(conn: Connection, index_code: str, timeframe: str, lookback: int = 60,
                    on_date: date | None = None) -> bytes:
    """index_daily 또는 weekly_index 의 가격 시계열. on_date 제공 시 그 날짜 이하 최신 lookback 개."""
    if timeframe == "daily":
        cols_sql = ", ".join(INDEX_COLUMNS_DAILY)
        date_filter = "AND date <= %(on_date)s" if on_date is not None else ""
        sql = (f"SELECT {cols_sql} FROM index_daily "
               f"WHERE index_code = %(code)s {date_filter} ORDER BY date DESC LIMIT %(lookback)s")
    elif timeframe == "weekly":
        cols = ["week_end_date AS date", "open", "high", "low", "close", "volume", "value"]
        cols_sql = ", ".join(cols)
        date_filter = "AND week_end_date <= %(on_date)s" if on_date is not None else ""
        sql = (f"SELECT {cols_sql} FROM weekly_index "
               f"WHERE index_code = %(code)s {date_filter} ORDER BY week_end_date DESC LIMIT %(lookback)s")
    else:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    with conn.cursor() as cur:
        cur.execute(sql, {"code": index_code, "lookback": lookback, "on_date": on_date})
        rows = cur.fetchall()
    rows = list(reversed(rows))

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(INDEX_COLUMNS_DAILY)
    for row in rows:
        writer.writerow([_fmt(v) for v in row])
    return buf.getvalue().encode("utf-8")


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return str(v)
