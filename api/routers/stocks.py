from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from api.deps import get_conn
from api.schemas.stock import StockOut


router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("", response_model=list[StockOut])
def list_stocks(market: str | None = None, sector: str | None = None,
                limit: int = 100, q: str | None = None,
                conn: Connection = Depends(get_conn)):
    sql = "SELECT ticker, name, market, sector, delisted_at FROM stocks WHERE 1=1"
    params = []
    if market:
        sql += " AND market = %s"
        params.append(market)
    if sector:
        sql += " AND sector = %s"
        params.append(sector)
    if q:
        sql += " AND (ticker ILIKE %s OR name ILIKE %s)"
        params.extend([f"%{q}%", f"%{q}%"])
    sql += " ORDER BY ticker LIMIT %s"
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [StockOut(ticker=r[0], name=r[1], market=r[2], sector=r[3], delisted_at=r[4]) for r in rows]


@router.get("/{ticker}", response_model=StockOut)
def get_stock(ticker: str, conn: Connection = Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, name, market, sector, delisted_at FROM stocks WHERE ticker = %s", (ticker,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, "Stock not found")
    return StockOut(ticker=row[0], name=row[1], market=row[2], sector=row[3], delisted_at=row[4])
