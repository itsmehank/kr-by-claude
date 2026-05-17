from datetime import date
from fastapi import APIRouter, Depends
from psycopg import Connection

from api.deps import get_conn


router = APIRouter(prefix="/api/market-context", tags=["market_context"])


@router.get("")
def get_market_context(date_: date | None = None, conn: Connection = Depends(get_conn)):
    if date_ is None:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM market_context_daily")
            row = cur.fetchone()
        date_ = row[0] if row and row[0] else date.today()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT date, index_code, current_status, distribution_day_count_last_25,
                   last_follow_through_day, days_since_follow_through, pct_stocks_above_200d_ma
              FROM market_context_daily
             WHERE date = %s
             ORDER BY index_code
        """, (date_,))
        rows = cur.fetchall()
    return [{
        "date": r[0].isoformat(), "index_code": r[1], "current_status": r[2],
        "distribution_day_count_last_25_sessions": r[3],
        "last_follow_through_day": r[4].isoformat() if r[4] else None,
        "days_since_follow_through": r[5],
        "pct_stocks_above_200d_ma": float(r[6]) if r[6] is not None else None,
    } for r in rows]
