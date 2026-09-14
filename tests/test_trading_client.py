# tests/test_trading_client.py
"""TossClient — 헤더 자동 부착·envelope 언랩·401 1회 재시도·429 Retry-After·에러 무가공."""
from decimal import Decimal

import httpx
import pytest

from kr_trading.config import TradeConfig
from kr_trading.toss.client import TossClient
from kr_trading.toss.errors import GuardError, TossApiError
from kr_trading.toss.models import OrderCreateRequest

CFG = TradeConfig(client_id="cid", client_secret="sec", account_seq=7,
                  base_url="https://toss.test", dry_run=True,
                  max_order_krw=Decimal("5000000"), max_daily_krw=Decimal("10000000"))
TOKEN_OK = httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})


def make(handler, cfg=CFG, sleeps=None):
    def route(req: httpx.Request):
        if req.url.path == "/oauth2/token":
            return TOKEN_OK
        return handler(req)
    http = httpx.Client(transport=httpx.MockTransport(route), base_url=cfg.base_url)
    return TossClient(cfg, http=http, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def test_headers_and_unwrap():
    seen = {}

    def h(req):
        seen.update(req.headers)
        seen["path"] = req.url.path
        seen["q"] = str(req.url.query, "utf-8")
        return httpx.Response(200, json={"result": [{"symbol": "005930", "timestamp": None, "lastPrice": "70000", "currency": "KRW"}]})

    c = make(h)
    out = c.prices(["005930"])
    assert seen["authorization"] == "Bearer tok" and "x-tossinvest-account" not in seen
    assert seen["path"] == "/api/v1/prices" and seen["q"] == "symbols=005930"
    assert out[0].lastPrice == Decimal("70000")


def test_account_header_on_account_paths():
    seen = {}

    def h(req):
        seen.update(req.headers)
        return httpx.Response(200, json={"result": {"currency": "KRW", "cashBuyingPower": "1000000"}})

    assert make(h).buying_power().cashBuyingPower == Decimal("1000000")
    assert seen["x-tossinvest-account"] == "7"


def test_account_path_without_seq_is_guard_error():
    cfg = TradeConfig(**{**CFG.__dict__, "account_seq": None})
    with pytest.raises(GuardError) as ei:
        make(lambda r: httpx.Response(200, json={"result": {}}), cfg=cfg).buying_power()
    assert ei.value.code == "guard/account-seq-missing"


def test_401_expired_token_retries_once_then_raises():
    n = [0]

    def h(req):
        n[0] += 1
        return httpx.Response(401, json={"error": {"code": "expired-token", "message": "", "requestId": "r"}})

    with pytest.raises(TossApiError) as ei:
        make(h).holdings()
    assert n[0] == 2 and ei.value.code == "expired-token"   # 재발급 후 딱 1회 재시도


def test_401_then_success():
    n = [0]

    def h(req):
        n[0] += 1
        if n[0] == 1:
            return httpx.Response(401, json={"error": {"code": "token-revoked", "message": ""}})
        return httpx.Response(200, json={"result": [{"accountNo": "1", "accountSeq": 7, "accountType": "BROKERAGE"}]})

    assert make(h).accounts()[0].accountSeq == 7 and n[0] == 2


def test_429_waits_retry_after_then_retries():
    n = [0]; sleeps = []

    def h(req):
        n[0] += 1
        if n[0] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {"code": "rate-limit-exceeded", "message": ""}})
        return httpx.Response(200, json={"result": {"sellableQuantity": "5"}})

    assert make(h, sleeps=sleeps).sellable_quantity("005930").sellableQuantity == Decimal("5")
    assert sleeps == [2.0] and n[0] == 2


def test_error_envelope_passthrough():
    def h(req):
        return httpx.Response(400, headers={"X-Request-Id": "req-9"}, json={"error": {
            "requestId": "req-9", "code": "invalid-request", "message": "호가 단위",
            "data": {"field": "price", "tickSize": "100"}}})

    with pytest.raises(TossApiError) as ei:
        make(h).create_order(OrderCreateRequest(symbol="005930", side="BUY", orderType="LIMIT",
                                                quantity=Decimal("1"), price=Decimal("70050")))
    e = ei.value
    assert (e.status, e.code, e.message, e.data, e.request_id) == (400, "invalid-request", "호가 단위", {"field": "price", "tickSize": "100"}, "req-9")


def test_create_order_sends_string_decimals():
    seen = {}

    def h(req):
        import json
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"result": {"orderId": "ord_1", "clientOrderId": "c1"}})

    r = make(h).create_order(OrderCreateRequest(symbol="005930", side="BUY", orderType="LIMIT",
                                                quantity=Decimal("10"), price=Decimal("70000"), clientOrderId="c1"))
    assert r.orderId == "ord_1" and seen["price"] == "70000" and seen["quantity"] == "10"
