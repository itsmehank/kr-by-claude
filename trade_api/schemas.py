"""프론트용 응답 모델. 모든 라우트는 이 모듈(또는 kr_trading.toss.models)의 모델을 response_model 로 선언.
bare dict 반환 금지 — FastAPI 는 dict 의 Decimal 을 float 로 내보낸다(spec §5 실측)."""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from kr_trading.toss.models import (
    Account, HoldingsOverview, OrderbookResponse, OrderCreateRequest, OrderModifyRequest,
    PriceLimitResponse, PriceResponse, StockWarning,
)

AccountOut = Account  # 재사용 — 브리프 인터페이스 계약(schemas.py 소비처용 별칭)


class HealthOut(BaseModel):
    dryRun: bool
    maxOrderKrw: Decimal
    maxDailyKrw: Decimal
    accountSeq: int | None


class ErrorDetail(BaseModel):
    code: str
    message: str
    data: dict | None = None
    requestId: str | None = None


class ErrorBody(BaseModel):
    error: ErrorDetail


class MismatchOut(BaseModel):
    symbol: str
    name: str
    tossQty: Decimal
    positionQty: Decimal | None
    kind: str          # missing | qty_diff


class HoldingsOut(BaseModel):
    overview: HoldingsOverview
    mismatch: list[MismatchOut]


class SearchHit(BaseModel):
    ticker: str
    name: str
    market: str


class QuoteOut(BaseModel):
    symbol: str
    name: str | None
    price: PriceResponse
    orderbook: OrderbookResponse
    limits: PriceLimitResponse
    warnings: list[StockWarning]


class PreviewIn(BaseModel):
    symbol: str
    side: str
    orderType: str
    quantity: Decimal
    price: Decimal | None = None
    confirmHighValueOrder: bool = False


class EstimateOut(BaseModel):
    amount: Decimal
    amountBasis: str
    commission: Decimal | None
    total: Decimal


class PreviewOut(BaseModel):
    previewToken: str
    clientOrderId: str | None
    request: dict
    estimate: EstimateOut
    warnings: list[str]
    dryRun: bool
    expiresInSec: int


class OrderSubmitIn(BaseModel):
    previewToken: str
    request: OrderCreateRequest


class OrderSubmitOut(BaseModel):
    dryRun: bool
    orderId: str | None
    clientOrderId: str | None
    auditId: int
    request: dict


class ModifyPreviewIn(BaseModel):
    orderId: str
    orderType: str
    quantity: Decimal
    price: Decimal | None = None
    confirmHighValueOrder: bool = False


class ModifySubmitIn(BaseModel):
    previewToken: str
    orderId: str
    request: OrderModifyRequest


class OperationOut(BaseModel):
    dryRun: bool
    orderId: str | None
    auditId: int
