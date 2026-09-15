"""토스 Open API 모델 (openapi.json v1.2.17 기준).

- 숫자 필드는 스펙상 `type: string, format: decimal` → 전부 Decimal. float 경유 금지.
- enum 필드는 str — 스펙이 "unknown code 허용" 을 요구.
- 요청 모델은 to_toss_json() 으로 Decimal→str, None 필드 제외.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ── 요청 ────────────────────────────────────────────────────────────
class OrderCreateRequest(_Base):
    symbol: str
    side: str            # BUY | SELL
    orderType: str       # LIMIT | MARKET
    quantity: Decimal
    price: Decimal | None = None
    timeInForce: str = "DAY"
    clientOrderId: str | None = None
    confirmHighValueOrder: bool = False

    def to_toss_json(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


class OrderModifyRequest(_Base):
    orderType: str
    quantity: Decimal | None = None
    price: Decimal | None = None
    confirmHighValueOrder: bool = False

    def to_toss_json(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


# ── 응답 ────────────────────────────────────────────────────────────
class Account(_Base):
    accountNo: str
    accountSeq: int
    accountType: str


class PriceResponse(_Base):
    symbol: str
    timestamp: str | None = None
    lastPrice: Decimal
    currency: str


class PriceLimitResponse(_Base):
    timestamp: str
    currency: str
    upperLimitPrice: Decimal | None = None
    lowerLimitPrice: Decimal | None = None


class OrderbookEntry(_Base):
    price: Decimal
    volume: Decimal


class OrderbookResponse(_Base):
    timestamp: str | None = None
    currency: str
    asks: list[OrderbookEntry]
    bids: list[OrderbookEntry]


class StockWarning(_Base):
    warningType: str
    exchange: str | None = None
    startDate: str | None = None
    endDate: str | None = None


class BuyingPowerResponse(_Base):
    currency: str
    cashBuyingPower: Decimal


class SellableQuantityResponse(_Base):
    sellableQuantity: Decimal


class Commission(_Base):
    marketCountry: str
    commissionRate: Decimal
    startDate: str | None = None
    endDate: str | None = None


class Money(_Base):
    krw: Decimal
    usd: Decimal | None = None


class HoldingsItem(_Base):
    symbol: str
    name: str
    marketCountry: str
    currency: str
    quantity: Decimal
    lastPrice: Decimal
    averagePurchasePrice: Decimal
    marketValue: Money
    profitLoss: Money
    dailyProfitLoss: Money
    cost: Money


class HoldingsOverview(_Base):
    totalPurchaseAmount: Money
    marketValue: Money
    profitLoss: Money
    dailyProfitLoss: Money
    items: list[HoldingsItem]


class OrderExecution(_Base):
    filledQuantity: Decimal
    averageFilledPrice: Decimal | None = None
    filledAmount: Decimal | None = None
    commission: Decimal | None = None
    tax: Decimal | None = None
    filledAt: str | None = None
    settlementDate: str | None = None


class Order(_Base):
    orderId: str
    symbol: str
    side: str
    orderType: str
    timeInForce: str
    status: str
    price: Decimal | None = None
    quantity: Decimal
    orderAmount: Decimal | None = None
    currency: str
    orderedAt: str
    canceledAt: str | None = None
    execution: OrderExecution


class PaginatedOrderResponse(_Base):
    orders: list[Order]
    nextCursor: str | None = None
    hasNext: bool = False


class OrderResponse(_Base):
    orderId: str
    clientOrderId: str | None = None


class OrderOperationResponse(_Base):
    orderId: str
