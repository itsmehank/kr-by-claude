"""market_context_daily → payload.market_context dict."""
from datetime import date
from psycopg import Connection


INDEX_CODE_MAP = {"KOSPI": "1001", "KOSDAQ": "2001"}


def build_market_context(conn: Connection, market: str, on_date: date) -> dict:
    """주어진 (market, on_date) 의 market_context_daily 행을 dict 로 변환.

    행 없으면 모든 필드 None (null).
    날짜는 ISO 문자열로 변환.
    """
    index_code = INDEX_CODE_MAP.get(market)
    if index_code is None:
        return _empty()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT current_status, distribution_day_count_last_25,
                   last_follow_through_day, days_since_follow_through,
                   pct_stocks_above_200d_ma
              FROM market_context_daily
             WHERE date = %s AND index_code = %s
            """,
            (on_date, index_code),
        )
        row = cur.fetchone()

    if row is None:
        return _empty()

    return {
        "current_status": row[0],
        "distribution_day_count_last_25_sessions": row[1],
        "last_follow_through_day": row[2].isoformat() if row[2] else None,
        "days_since_follow_through": row[3],
        "pct_stocks_above_200d_ma": float(row[4]) if row[4] is not None else None,
    }


def _empty() -> dict:
    return {
        "current_status": None,
        "distribution_day_count_last_25_sessions": None,
        "last_follow_through_day": None,
        "days_since_follow_through": None,
        "pct_stocks_above_200d_ma": None,
    }
