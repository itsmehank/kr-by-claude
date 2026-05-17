from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from api.deps import get_conn
from api.schemas.heatmap import SectorHeatmapOut


router = APIRouter(prefix="/api/heatmap", tags=["heatmap"])


PERIOD_DAYS: dict[str, int] = {
    "1d": 1,
    "1w": 7,
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "12m": 365,
}


@router.get("/sectors", response_model=list[SectorHeatmapOut])
def get_sectors(
    date_: date | None = None,
    period: str = "1m",
    conn: Connection = Depends(get_conn),
):
    if period not in PERIOD_DAYS:
        raise HTTPException(400, f"Unknown period: {period}")
    days = PERIOD_DAYS[period]

    if date_ is None:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM daily_indicators")
            row = cur.fetchone()
        date_ = row[0] if row and row[0] else date.today()

    with conn.cursor() as cur:
        cur.execute(
            """
            WITH
              latest AS (SELECT %s::date AS d),
              past AS (
                SELECT i.ticker, i.adj_close AS close_past
                  FROM daily_indicators i, latest l
                 WHERE i.date = (
                    SELECT MAX(d2.date)
                      FROM daily_indicators d2
                     WHERE d2.ticker = i.ticker
                       AND d2.date <= l.d - (%s || ' days')::interval
                 )
              )
            SELECT
              s.sector,
              COUNT(*)                                        AS stock_count,
              AVG(i.rs_rating)::FLOAT                         AS avg_rs,
              COUNT(*) FILTER (WHERE i.minervini_pass = TRUE) AS pass_count,
              AVG(
                CASE WHEN p.close_past IS NOT NULL AND p.close_past > 0
                  THEN (i.adj_close - p.close_past) / p.close_past * 100
                  ELSE NULL
                END
              )::FLOAT                                        AS avg_return_pct
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
              LEFT JOIN past p ON p.ticker = i.ticker
              JOIN latest l ON i.date = l.d
             WHERE s.sector IS NOT NULL
               AND s.delisted_at IS NULL
             GROUP BY s.sector
             ORDER BY avg_rs DESC NULLS LAST
            """,
            (date_, days),
        )
        rows = cur.fetchall()
    return [
        SectorHeatmapOut(
            sector=r[0],
            stock_count=r[1],
            avg_rs_rating=r[2],
            minervini_pass_count=r[3],
            minervini_pass_rate=(r[3] / r[1]) if r[1] > 0 else 0.0,
            avg_return_pct=r[4],
        )
        for r in rows
    ]
