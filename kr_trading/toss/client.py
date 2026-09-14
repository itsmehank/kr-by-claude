# kr_trading/toss/client.py
"""토스 Open API 동기 클라이언트 (spec §5 TossClient).

- Authorization 자동, 계좌 필요 경로만 X-Tossinvest-Account.
- 성공 envelope {result: …} 언랩. 에러 envelope 은 TossApiError 로 무가공 전달.
- 401 expired-token/token-revoked/invalid-token → 재발급 후 1회만 재시도.
- 429 → Retry-After(없으면 1s) 대기 후 1회 재시도.
"""
from __future__ import annotations

import time
from typing import Any, Callable

import httpx

from kr_trading.config import TradeConfig
from kr_trading.toss.errors import GuardError, TossApiError
from kr_trading.toss.models import (
    Account, BuyingPowerResponse, Commission, HoldingsOverview, Order, OrderbookResponse,
    OrderCreateRequest, OrderModifyRequest, OrderOperationResponse, OrderResponse,
    PaginatedOrderResponse, PriceLimitResponse, PriceResponse, SellableQuantityResponse,
    StockWarning,
)
from kr_trading.toss.ratelimit import RateLimiter, group_for_path
from kr_trading.toss.token import TokenManager, raise_for_envelope

_REISSUE_CODES = {"expired-token", "token-revoked", "invalid-token"}


class TossClient:
    def __init__(self, cfg: TradeConfig, http: httpx.Client | None = None,
                 token: TokenManager | None = None, limiter: RateLimiter | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.cfg = cfg
        self._http = http or httpx.Client(base_url=cfg.base_url, timeout=httpx.Timeout(10.0, connect=5.0))
        self._token = token or TokenManager(self._http, cfg)
        self._limiter = limiter or RateLimiter()
        self._sleep = sleep

    # ── 저수준 ─────────────────────────────────────────────────────
    def request(self, method: str, path: str, *, params: dict | None = None,
                json: Any = None, account: bool = False) -> Any:
        headers = {"Accept": "application/json"}
        if account:
            if self.cfg.account_seq is None:
                raise GuardError("guard/account-seq-missing",
                                 "TOSS_ACCOUNT_SEQ 미설정 — GET /trade-api/accounts 로 확인 후 .env 에 고정")
            headers["X-Tossinvest-Account"] = str(self.cfg.account_seq)
        group = group_for_path(path)
        resp = self._send(method, path, params, json, headers, group)
        if resp.status_code == 401:
            code = _error_code(resp)
            if code in _REISSUE_CODES:
                self._token.invalidate()
                resp = self._send(method, path, params, json, headers, group)
        if resp.status_code == 429:
            wait = self._limiter.retry_after_seconds(resp.headers) or 1.0
            self._sleep(wait)
            resp = self._send(method, path, params, json, headers, group)
        raise_for_envelope(resp)
        body = resp.json()
        return body.get("result") if isinstance(body, dict) else body

    def _send(self, method, path, params, json, headers, group) -> httpx.Response:
        self._limiter.acquire(group)
        h = dict(headers)
        h["Authorization"] = f"Bearer {self._token.get()}"
        resp = self._http.request(method, path, params=params, json=json, headers=h)
        self._limiter.update_from_headers(group, resp.headers)
        return resp

    # ── 고수준 ─────────────────────────────────────────────────────
    def accounts(self) -> list[Account]:
        return [Account.model_validate(a) for a in self.request("GET", "/api/v1/accounts")]

    def holdings(self) -> HoldingsOverview:
        return HoldingsOverview.model_validate(self.request("GET", "/api/v1/holdings", account=True))

    def prices(self, symbols: list[str]) -> list[PriceResponse]:
        r = self.request("GET", "/api/v1/prices", params={"symbols": ",".join(symbols)})
        return [PriceResponse.model_validate(p) for p in r]

    def orderbook(self, symbol: str) -> OrderbookResponse:
        return OrderbookResponse.model_validate(self.request("GET", "/api/v1/orderbook", params={"symbol": symbol}))

    def price_limits(self, symbol: str) -> PriceLimitResponse:
        return PriceLimitResponse.model_validate(self.request("GET", "/api/v1/price-limits", params={"symbol": symbol}))

    def warnings(self, symbol: str) -> list[StockWarning]:
        return [StockWarning.model_validate(w) for w in self.request("GET", f"/api/v1/stocks/{symbol}/warnings")]

    def buying_power(self) -> BuyingPowerResponse:
        return BuyingPowerResponse.model_validate(
            self.request("GET", "/api/v1/buying-power", params={"currency": "KRW"}, account=True))

    def sellable_quantity(self, symbol: str) -> SellableQuantityResponse:
        return SellableQuantityResponse.model_validate(
            self.request("GET", "/api/v1/sellable-quantity", params={"symbol": symbol}, account=True))

    def commissions(self) -> list[Commission]:
        return [Commission.model_validate(c) for c in self.request("GET", "/api/v1/commissions", account=True)]

    def create_order(self, req: OrderCreateRequest) -> OrderResponse:
        return OrderResponse.model_validate(self.request("POST", "/api/v1/orders", json=req.to_toss_json(), account=True))

    def modify_order(self, order_id: str, req: OrderModifyRequest) -> OrderOperationResponse:
        return OrderOperationResponse.model_validate(
            self.request("POST", f"/api/v1/orders/{order_id}/modify", json=req.to_toss_json(), account=True))

    def cancel_order(self, order_id: str) -> OrderOperationResponse:
        return OrderOperationResponse.model_validate(
            self.request("POST", f"/api/v1/orders/{order_id}/cancel", json={}, account=True))

    def list_orders(self, status: str, cursor: str | None = None, limit: int | None = None) -> PaginatedOrderResponse:
        params: dict[str, Any] = {"status": status}
        if cursor: params["cursor"] = cursor
        if limit: params["limit"] = limit
        return PaginatedOrderResponse.model_validate(self.request("GET", "/api/v1/orders", params=params, account=True))

    def get_order(self, order_id: str) -> Order:
        return Order.model_validate(self.request("GET", f"/api/v1/orders/{order_id}", account=True))


def _error_code(resp: httpx.Response) -> str:
    try:
        return (resp.json().get("error") or {}).get("code") or ""
    except ValueError:
        return ""
