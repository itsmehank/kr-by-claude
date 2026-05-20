from datetime import date as _date, timedelta
from fastapi import APIRouter, Depends
from psycopg import Connection

from api.deps import get_conn
from api.schemas.index import IndexDailyOut


router = APIRouter(prefix="/api/index", tags=["index"])


@router.get("/daily/{index_code}", response_model=list[IndexDailyOut])
def get_index_daily(
    index_code: str,
    start: _date | None = None,
    end: _date | None = None,
    conn: Connection = Depends(get_conn),
):
    if end is None:
        end = _date.today()
    if start is None:
        start = end - timedelta(days=365)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, open, high, low, close, volume
              FROM index_daily
             WHERE index_code = %s AND date BETWEEN %s AND %s
             ORDER BY date
            """,
            (index_code, start, end),
        )
        rows = cur.fetchall()

    return [
        IndexDailyOut(
            date=r[0],
            open=float(r[1]),
            high=float(r[2]),
            low=float(r[3]),
            close=float(r[4]),
            volume=int(r[5]) if r[5] is not None else None,
        )
        for r in rows
    ]
