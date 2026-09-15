# kr_trading/toss/client.py
"""토스 Open API 동기 클라이언트 (spec §5 TossClient).

- Authorization 자동, 계좌 필요 경로만 X-Tossinvest-Account.
- 성공 envelope {result: …} 언랩. 에러 envelope 은 TossApiError 로 무가공 전달.
- 401 expired-token/token-revoked/invalid-token → 재발급 후 1회만 재시도.
- 429 → Retry-After(없으면 1s) 대기 후 1회 재시도.
"""
from __future__ import annotations

import threading
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
        # X-Request-Id 는 스레드별로 보관 — TossClient 는 프로세스 싱글톤이고 sync 라우트가 스레드풀에서
        # 동시에 request() 를 부를 수 있어, 인스턴스 속성이면 겹친 주문의 감사 request_id 가 뒤바뀐다.
        self._tl = threading.local()

    @property
    def last_request_id(self) -> str | None:
        """직전 request() 의 토스 X-Request-Id — **호출한 스레드** 기준. 다른 스레드의 값은 보이지 않는다."""
        return getattr(self._tl, "last_request_id", None)

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
        # 재시도는 원인별로 각 1회, 최대 3회 시도(최초 + 인증 1 + 레이트 1). 두 조건을
        # 순차 if 로 두면 "429 재시도 응답이 401 token-revoked" 인 경우가 재발급을 못 타므로
        # 원인별 플래그를 쓰는 유한 루프로 둔다 — Retry-After 대기 중 외부 재발급으로 토큰이
        # 무효화되는 것은 문서가 경고하는 실제 시나리오다.
        retried_auth = False
        retried_rate = False
        while True:
            resp, used_token = self._send(method, path, params, json, headers, group)
            if (resp.status_code == 401 and not retried_auth
                    and _error_code(resp) in _REISSUE_CODES):
                retried_auth = True
                # 이 요청이 실제로 쓴 토큰만 넘긴다 — compare-and-clear: 다른 스레드가 이미
                # 재발급했다면(현재 토큰이 달라졌다면) no-op, 방금 나온 새 토큰을 지우지 않는다.
                self._token.invalidate(used_token)
                continue
            if resp.status_code == 429 and not retried_rate:
                retried_rate = True
                self._sleep(self._limiter.retry_after_seconds(resp.headers) or 1.0)
                continue
            break
        self._tl.last_request_id = resp.headers.get("X-Request-Id")
        raise_for_envelope(resp)
        body = resp.json()
        return body.get("result") if isinstance(body, dict) else body

    def _send(self, method, path, params, json, headers, group) -> tuple[httpx.Response, str]:
        self._limiter.acquire(group)
        h = dict(headers)
        used_token = self._token.get()
        h["Authorization"] = f"Bearer {used_token}"
        resp = self._http.request(method, path, params=params, json=json, headers=h)
        self._limiter.update_from_headers(group, resp.headers)
        return resp, used_token

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
