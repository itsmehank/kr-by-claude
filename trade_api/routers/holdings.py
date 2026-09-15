"""GET /trade-api/holdings — 토스 잔고 + positions(open) 읽기전용 대조 (spec D2·§6).
positions 조회는 get_open_positions(conn) 재사용(store.py, import 만·수정 금지). quantity
NULL(전량 모델)은 존재만 확인."""
from decimal import Decimal

from fastapi import APIRouter, Depends
from psycopg import Connection

from kr_pipeline.trade_management.store import get_open_positions
from kr_trading.toss.client import TossClient
from trade_api.deps import get_conn, get_toss
from trade_api.schemas import HoldingsOut, MismatchOut, kr_int_str

router = APIRouter(prefix="/trade-api", tags=["holdings"])


@router.get("/holdings", response_model=HoldingsOut)
def holdings(toss: TossClient = Depends(get_toss), conn: Connection = Depends(get_conn)) -> HoldingsOut:
    overview = toss.holdings()
    overview = overview.model_copy(update={"items": [
        it.model_copy(update={"quantity": kr_int_str(it.quantity), "lastPrice": kr_int_str(it.lastPrice),
                              "averagePurchasePrice": kr_int_str(it.averagePurchasePrice)})
        if it.marketCountry == "KR" else it
        for it in overview.items
    ]})
    pos: dict[str, Decimal | None] = {
        r["symbol"]: (Decimal(r["quantity"]) if r["quantity"] is not None else None)
        for r in get_open_positions(conn)
    }
    mismatch: list[MismatchOut] = []
    for it in overview.items:
        if it.marketCountry != "KR":
            continue
        if it.symbol not in pos:
            mismatch.append(MismatchOut(symbol=it.symbol, name=it.name, tossQty=it.quantity, positionQty=None, kind="missing"))
        elif pos[it.symbol] is not None and pos[it.symbol] != it.quantity:
            mismatch.append(MismatchOut(symbol=it.symbol, name=it.name, tossQty=it.quantity, positionQty=pos[it.symbol], kind="qty_diff"))
    return HoldingsOut(overview=overview, mismatch=mismatch)
