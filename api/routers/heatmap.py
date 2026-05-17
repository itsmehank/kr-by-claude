from datetime import date
from fastapi import APIRouter, Depends
from psycopg import Connection

from api.deps import get_conn
from api.schemas.heatmap import SectorHeatmapOut


router = APIRouter(prefix="/api/heatmap", tags=["heatmap"])


@router.get("/sectors", response_model=list[SectorHeatmapOut])
def get_sectors(date_: date | None = None, conn: Connection = Depends(get_conn)):
    if date_ is None:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM daily_indicators")
            row = cur.fetchone()
        date_ = row[0] if row and row[0] else date.today()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.sector, COUNT(*) AS stock_count,
                   AVG(i.rs_rating)::FLOAT AS avg_rs,
                   COUNT(*) FILTER (WHERE i.minervini_pass = TRUE) AS pass_count
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.date = %s AND s.sector IS NOT NULL AND s.delisted_at IS NULL
             GROUP BY s.sector
             ORDER BY avg_rs DESC NULLS LAST
        """, (date_,))
        rows = cur.fetchall()
    return [SectorHeatmapOut(
        sector=r[0], stock_count=r[1],
        avg_rs_rating=r[2], minervini_pass_count=r[3],
        minervini_pass_rate=(r[3] / r[1]) if r[1] > 0 else 0.0,
    ) for r in rows]
