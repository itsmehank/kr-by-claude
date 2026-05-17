from datetime import date, timedelta
from fastapi import APIRouter, Depends
from psycopg import Connection

from api.deps import get_conn
from api.schemas.indicator import DailyIndicatorOut, MinerviniPassedOut


router = APIRouter(prefix="/api/indicators", tags=["indicators"])


@router.get("/daily/{ticker}", response_model=list[DailyIndicatorOut])
def get_daily(ticker: str, start: date | None = None, end: date | None = None,
              conn: Connection = Depends(get_conn)):
    if start is None:
        start = date.today() - timedelta(days=365)
    if end is None:
        end = date.today()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT date, adj_close, sma_10, sma_21, sma_50, sma_150, sma_200,
                   w52_high, w52_low, rs_line, rs_rating, minervini_pass,
                   volume_ratio_50d, pocket_pivot_flag, distribution_day_flag
              FROM daily_indicators
             WHERE ticker = %s AND date BETWEEN %s AND %s
             ORDER BY date
        """, (ticker, start, end))
        rows = cur.fetchall()
    return [DailyIndicatorOut(
        date=r[0], adj_close=float(r[1]),
        sma_10=float(r[2]) if r[2] else None,
        sma_21=float(r[3]) if r[3] else None,
        sma_50=float(r[4]) if r[4] else None,
        sma_150=float(r[5]) if r[5] else None,
        sma_200=float(r[6]) if r[6] else None,
        w52_high=float(r[7]) if r[7] else None,
        w52_low=float(r[8]) if r[8] else None,
        rs_line=float(r[9]) if r[9] else None,
        rs_rating=r[10],
        minervini_pass=r[11],
        volume_ratio_50d=float(r[12]) if r[12] else None,
        pocket_pivot_flag=r[13],
        distribution_day_flag=r[14],
    ) for r in rows]


@router.get("/minervini-passed", response_model=list[MinerviniPassedOut])
def get_minervini_passed(date_: date | None = None, min_rs: int = 70, limit: int = 100,
                         conn: Connection = Depends(get_conn)):
    if date_ is None:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM daily_indicators WHERE minervini_pass = TRUE")
            row = cur.fetchone()
        date_ = row[0] if row and row[0] else date.today()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT i.ticker, s.name, s.sector, i.rs_rating, i.adj_close, i.volume_ratio_50d, i.pocket_pivot_flag
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.date = %s AND i.minervini_pass = TRUE AND i.rs_rating >= %s
             ORDER BY i.rs_rating DESC
             LIMIT %s
        """, (date_, min_rs, limit))
        rows = cur.fetchall()
    return [MinerviniPassedOut(
        ticker=r[0], name=r[1], sector=r[2], rs_rating=r[3], adj_close=float(r[4]),
        volume_ratio_50d=float(r[5]) if r[5] else None,
        pocket_pivot_flag=r[6],
    ) for r in rows]
