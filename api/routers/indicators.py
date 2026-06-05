from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from api.deps import get_conn
from api.schemas.indicator import (
    DailyIndicatorOut,
    MinerviniPassedOut,
    SectorStockOut,
    WeeklyIndicatorOut,
)
from api.services.minervini_detail_builder import build_minervini_detail


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
            SELECT i.date, i.adj_close,
                   p.open, p.high, p.low, p.close, p.volume,
                   i.avg_volume_50d,
                   i.sma_10, i.sma_21, i.sma_50, i.sma_150, i.sma_200,
                   i.w52_high, i.w52_low, i.rs_line, i.rs_rating, i.minervini_pass,
                   i.volume_ratio_50d, i.pocket_pivot_flag, i.distribution_day_flag,
               COALESCE(p.adj_open,   p.open)   AS adj_open,
               COALESCE(p.adj_high,   p.high)   AS adj_high,
               COALESCE(p.adj_low,    p.low)    AS adj_low,
               COALESCE(p.adj_volume, p.volume) AS adj_volume
              FROM daily_indicators i
              LEFT JOIN daily_prices p
                ON p.ticker = i.ticker AND p.date = i.date
             WHERE i.ticker = %s AND i.date BETWEEN %s AND %s
             ORDER BY i.date
        """, (ticker, start, end))
        rows = cur.fetchall()
    return [DailyIndicatorOut(
        date=r[0], adj_close=float(r[1]),
        open=float(r[2]) if r[2] is not None else None,
        high=float(r[3]) if r[3] is not None else None,
        low=float(r[4]) if r[4] is not None else None,
        close=float(r[5]) if r[5] is not None else None,
        volume=int(r[6]) if r[6] is not None else None,
        avg_volume_50d=float(r[7]) if r[7] is not None else None,
        sma_10=float(r[8]) if r[8] is not None else None,
        sma_21=float(r[9]) if r[9] is not None else None,
        sma_50=float(r[10]) if r[10] is not None else None,
        sma_150=float(r[11]) if r[11] is not None else None,
        sma_200=float(r[12]) if r[12] is not None else None,
        w52_high=float(r[13]) if r[13] is not None else None,
        w52_low=float(r[14]) if r[14] is not None else None,
        rs_line=float(r[15]) if r[15] is not None else None,
        rs_rating=r[16],
        minervini_pass=r[17],
        volume_ratio_50d=float(r[18]) if r[18] is not None else None,
        pocket_pivot_flag=r[19],
        distribution_day_flag=r[20],
        adj_open=float(r[21]) if r[21] is not None else None,
        adj_high=float(r[22]) if r[22] is not None else None,
        adj_low=float(r[23]) if r[23] is not None else None,
        adj_volume=float(r[24]) if r[24] is not None else None,
    ) for r in rows]


@router.get("/weekly/{ticker}", response_model=list[WeeklyIndicatorOut])
def get_weekly(
    ticker: str,
    start: date | None = None,
    end: date | None = None,
    conn: Connection = Depends(get_conn),
):
    if start is None:
        start = date.today() - timedelta(days=365 * 2)
    if end is None:
        end = date.today()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.week_end_date, i.adj_close,
                   p.open, p.high, p.low, p.close, p.volume,
                   i.avg_volume_10w,
                   i.sma_10w, i.sma_30w, i.sma_40w,
                   i.w52_high, i.w52_low,
                   i.rs_line, i.rs_rating, i.minervini_pass,
               COALESCE(p.adj_open,   p.open)   AS adj_open,
               COALESCE(p.adj_high,   p.high)   AS adj_high,
               COALESCE(p.adj_low,    p.low)    AS adj_low,
               COALESCE(p.adj_volume, p.volume) AS adj_volume
              FROM weekly_indicators i
              LEFT JOIN weekly_prices p
                ON p.ticker = i.ticker AND p.week_end_date = i.week_end_date
             WHERE i.ticker = %s AND i.week_end_date BETWEEN %s AND %s
             ORDER BY i.week_end_date
            """,
            (ticker, start, end),
        )
        rows = cur.fetchall()
    return [
        WeeklyIndicatorOut(
            date=r[0],
            adj_close=float(r[1]),
            open=float(r[2]) if r[2] is not None else None,
            high=float(r[3]) if r[3] is not None else None,
            low=float(r[4]) if r[4] is not None else None,
            close=float(r[5]) if r[5] is not None else None,
            volume=int(r[6]) if r[6] is not None else None,
            avg_volume_10w=float(r[7]) if r[7] is not None else None,
            sma_10w=float(r[8]) if r[8] is not None else None,
            sma_30w=float(r[9]) if r[9] is not None else None,
            sma_40w=float(r[10]) if r[10] is not None else None,
            w52_high=float(r[11]) if r[11] is not None else None,
            w52_low=float(r[12]) if r[12] is not None else None,
            rs_line=float(r[13]) if r[13] is not None else None,
            rs_rating=r[14],
            minervini_pass=r[15],
            adj_open=float(r[16]) if r[16] is not None else None,
            adj_high=float(r[17]) if r[17] is not None else None,
            adj_low=float(r[18]) if r[18] is not None else None,
            adj_volume=float(r[19]) if r[19] is not None else None,
        )
        for r in rows
    ]


@router.get("/minervini-detail/{ticker}")
def get_minervini_detail(
    ticker: str,
    date_: date | None = None,
    conn: Connection = Depends(get_conn),
):
    """8조건 detail (passed, description, values, margin_pct)."""
    if date_ is None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(date) FROM daily_indicators WHERE ticker = %s",
                (ticker,),
            )
            row = cur.fetchone()
        if not row or not row[0]:
            raise HTTPException(404, f"No data for ticker: {ticker}")
        date_ = row[0]

    detail = build_minervini_detail(conn, ticker, date_)
    return {
        "ticker": ticker,
        "date": date_.isoformat(),
        "detail": detail,
    }


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


@router.get("/by-sector", response_model=list[SectorStockOut])
def get_by_sector(
    sector: str,
    date_: date | None = None,
    limit: int = 20,
    conn: Connection = Depends(get_conn),
):
    """섹터 안의 전체 종목 (RS rating 내림차순, 상위 N개)."""
    if date_ is None:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM daily_indicators")
            row = cur.fetchone()
        date_ = row[0] if row and row[0] else date.today()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT i.ticker, s.name, s.sector, s.market, i.rs_rating, i.adj_close,
                   i.volume_ratio_50d, i.pocket_pivot_flag, i.minervini_pass
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.date = %s AND s.sector = %s AND s.delisted_at IS NULL
             ORDER BY i.rs_rating DESC NULLS LAST
             LIMIT %s
        """, (date_, sector, limit))
        rows = cur.fetchall()
    return [SectorStockOut(
        ticker=r[0], name=r[1], sector=r[2], market=r[3], rs_rating=r[4], adj_close=float(r[5]),
        volume_ratio_50d=float(r[6]) if r[6] else None,
        pocket_pivot_flag=r[7],
        minervini_pass=bool(r[8]) if r[8] is not None else False,
    ) for r in rows]
