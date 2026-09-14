"""토스 모델 — Decimal 왕복(float 미개입), unknown enum 허용, None 제외 직렬화."""
from decimal import Decimal

from kr_trading.toss.errors import GuardError, TossApiError
from kr_trading.toss.models import (
    HoldingsOverview, Order, OrderCreateRequest, OrderModifyRequest,
)


def test_order_create_to_toss_json_uses_strings_and_drops_none():
    req = OrderCreateRequest(symbol="005930", side="BUY", orderType="LIMIT",
                             quantity=Decimal("10"), price=Decimal("70000"),
                             clientOrderId="20260914-abcd1234")
    j = req.to_toss_json()
    assert j == {"symbol": "005930", "side": "BUY", "orderType": "LIMIT",
                 "quantity": "10", "price": "70000", "timeInForce": "DAY",
                 "clientOrderId": "20260914-abcd1234", "confirmHighValueOrder": False}
    assert isinstance(j["price"], str)


def test_market_order_has_no_price_key():
    req = OrderCreateRequest(symbol="005930", side="BUY", orderType="MARKET", quantity=Decimal("3"))
    assert "price" not in req.to_toss_json()


def test_modify_to_toss_json():
    j = OrderModifyRequest(orderType="LIMIT", quantity=Decimal("15"), price=Decimal("71000")).to_toss_json()
    assert j == {"orderType": "LIMIT", "quantity": "15", "price": "71000", "confirmHighValueOrder": False}


def test_order_parses_string_decimals_and_unknown_enum():
    o = Order.model_validate({
        "orderId": "ord_1", "symbol": "005930", "side": "BUY", "orderType": "WEIRD_NEW_TYPE",
        "timeInForce": "DAY", "status": "PENDING", "price": "70000", "quantity": "10",
        "orderAmount": None, "currency": "KRW", "orderedAt": "2026-09-14T09:00:00+09:00",
        "canceledAt": None,
        "execution": {"filledQuantity": "0", "averageFilledPrice": None, "filledAmount": None,
                      "commission": None, "tax": None, "filledAt": None, "settlementDate": None},
    })
    assert o.price == Decimal("70000") and o.orderType == "WEIRD_NEW_TYPE"
    assert o.model_dump(mode="json")["price"] == "70000"


def test_holdings_overview_money():
    h = HoldingsOverview.model_validate({
        "totalPurchaseAmount": {"krw": "1000000", "usd": None},
        "marketValue": {"krw": "1100000", "usd": None},
        "profitLoss": {"krw": "100000", "usd": None},
        "dailyProfitLoss": {"krw": "-5000", "usd": None},
        "items": [{"symbol": "005930", "name": "삼성전자", "marketCountry": "KR", "currency": "KRW",
                   "quantity": "10", "lastPrice": "110000", "averagePurchasePrice": "100000",
                   "marketValue": {"krw": "1100000", "usd": None}, "profitLoss": {"krw": "100000", "usd": None},
                   "dailyProfitLoss": {"krw": "-5000", "usd": None}, "cost": {"krw": "1000000", "usd": None}}],
    })
    assert h.items[0].quantity == Decimal("10") and h.profitLoss.krw == Decimal("100000")


def test_error_types():
    e = TossApiError(status=422, code="insufficient-buying-power", message="", data={"x": 1}, request_id="r1")
    assert e.status == 422 and e.code == "insufficient-buying-power" and "insufficient" in str(e)
    g = GuardError("guard/tick-size", "호가 단위 불일치", {"tick": 100})
    assert g.code.startswith("guard/") and g.data == {"tick": 100}
