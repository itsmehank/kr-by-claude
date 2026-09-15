"""검색(로컬 stocks)·시세 묶음·매수가능금액·판매가능수량."""
from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from kr_trading.toss.client import TossClient
from kr_trading.toss.errors import GuardError
from kr_trading.toss.models import BuyingPowerResponse, SellableQuantityResponse
from trade_api.deps import get_conn, get_toss
from trade_api.schemas import QuoteOut, SearchHit, kr_int_str

router = APIRouter(prefix="/trade-api", tags=["market"])


def _escape_ilike(q: str) -> str:
    """ILIKE 와일드카드(`\\ % _`)를 리터럴로 이스케이프 — `ESCAPE '\\'` 와 짝지어 사용."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/search", response_model=list[SearchHit])
def search(q: str = Query(..., min_length=1, max_length=30), conn: Connection = Depends(get_conn)) -> list[SearchHit]:
    esc = _escape_ilike(q)
    like = f"%{esc}%"
    rows = conn.execute(
        """
        SELECT ticker, name, market FROM stocks
         WHERE delisted_at IS NULL AND is_common
           AND (ticker ILIKE %s ESCAPE '\\' OR name ILIKE %s ESCAPE '\\')
         ORDER BY (ticker = %s) DESC, (name ILIKE %s ESCAPE '\\') DESC, name
         LIMIT 20
        """,
        (like, like, q, f"{esc}%"),
    ).fetchall()
    return [SearchHit(ticker=r[0], name=r[1], market=r[2]) for r in rows]


@router.get("/quote/{symbol}", response_model=QuoteOut)
def quote(symbol: str, toss: TossClient = Depends(get_toss), conn: Connection = Depends(get_conn)) -> QuoteOut:
    row = conn.execute("SELECT name FROM stocks WHERE ticker = %s AND delisted_at IS NULL", (symbol,)).fetchone()
    if row is None:
        raise GuardError("guard/symbol-unpriced", "시세 없음(상폐·미거래·미상장)", {"symbol": symbol})
    prices = toss.prices([symbol])
    if not prices:
        raise GuardError("guard/symbol-unpriced", "시세 없음(상폐·미거래·미상장)", {"symbol": symbol})
    price = prices[0].model_copy(update={"lastPrice": kr_int_str(prices[0].lastPrice)})
    limits = toss.price_limits(symbol)
    limits = limits.model_copy(update={"upperLimitPrice": kr_int_str(limits.upperLimitPrice),
                                       "lowerLimitPrice": kr_int_str(limits.lowerLimitPrice)})
    orderbook = toss.orderbook(symbol)
    orderbook = orderbook.model_copy(update={
        "asks": [e.model_copy(update={"price": kr_int_str(e.price), "volume": kr_int_str(e.volume)}) for e in orderbook.asks],
        "bids": [e.model_copy(update={"price": kr_int_str(e.price), "volume": kr_int_str(e.volume)}) for e in orderbook.bids],
    })
    return QuoteOut(symbol=symbol, name=row[0], price=price, orderbook=orderbook, limits=limits,
                    warnings=toss.warnings(symbol))


@router.get("/buying-power", response_model=BuyingPowerResponse)
def buying_power(toss: TossClient = Depends(get_toss)) -> BuyingPowerResponse:
    return toss.buying_power()


@router.get("/sellable/{symbol}", response_model=SellableQuantityResponse)
def sellable(symbol: str, toss: TossClient = Depends(get_toss)) -> SellableQuantityResponse:
    res = toss.sellable_quantity(symbol)
    return res.model_copy(update={"sellableQuantity": kr_int_str(res.sellableQuantity)})
