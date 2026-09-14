"""검색(로컬 stocks)·시세 묶음·매수가능금액·판매가능수량."""
from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from kr_trading.toss.client import TossClient
from kr_trading.toss.models import BuyingPowerResponse, SellableQuantityResponse
from trade_api.deps import get_conn, get_toss
from trade_api.schemas import QuoteOut, SearchHit

router = APIRouter(prefix="/trade-api", tags=["market"])


@router.get("/search", response_model=list[SearchHit])
def search(q: str = Query(..., min_length=1, max_length=30), conn: Connection = Depends(get_conn)) -> list[SearchHit]:
    like = f"%{q}%"
    rows = conn.execute(
        """
        SELECT ticker, name, market FROM stocks
         WHERE delisted_at IS NULL AND is_common
           AND (ticker ILIKE %s OR name ILIKE %s)
         ORDER BY (ticker = %s) DESC, (name ILIKE %s) DESC, name
         LIMIT 20
        """,
        (like, like, q, f"{q}%"),
    ).fetchall()
    return [SearchHit(ticker=r[0], name=r[1], market=r[2]) for r in rows]


@router.get("/quote/{symbol}", response_model=QuoteOut)
def quote(symbol: str, toss: TossClient = Depends(get_toss), conn: Connection = Depends(get_conn)) -> QuoteOut:
    row = conn.execute("SELECT name FROM stocks WHERE ticker = %s", (symbol,)).fetchone()
    prices = toss.prices([symbol])
    return QuoteOut(symbol=symbol, name=row[0] if row else None, price=prices[0],
                    orderbook=toss.orderbook(symbol), limits=toss.price_limits(symbol),
                    warnings=toss.warnings(symbol))


@router.get("/buying-power", response_model=BuyingPowerResponse)
def buying_power(toss: TossClient = Depends(get_toss)) -> BuyingPowerResponse:
    return toss.buying_power()


@router.get("/sellable/{symbol}", response_model=SellableQuantityResponse)
def sellable(symbol: str, toss: TossClient = Depends(get_toss)) -> SellableQuantityResponse:
    return toss.sellable_quantity(symbol)
