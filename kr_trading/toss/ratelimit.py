"""API 그룹별 토큰버킷 (요약 문서 §8). 초기값은 문서 표, X-RateLimit-Limit 로 런타임 보정."""
from __future__ import annotations

import re
import threading
import time
from typing import Callable, Mapping

GROUP_LIMITS: dict[str, int] = {
    "AUTH": 5, "ACCOUNT": 1, "ASSET": 5, "STOCK": 5, "STOCK_ALL": 1,
    "MARKET_INFO": 3, "MARKET_DATA": 15, "MARKET_DATA_CHART": 20,
    "ORDER": 10, "ORDER_HISTORY": 5, "ORDER_INFO": 6,
}

_ORDER_ACTION = re.compile(r"^/api/v1/orders/[^/]+/(cancel|modify)$")
_ORDER_DETAIL = re.compile(r"^/api/v1/orders/[^/]+$")


def group_for_path(path: str) -> str:
    if path == "/oauth2/token":
        return "AUTH"
    if path == "/api/v1/accounts":
        return "ACCOUNT"
    if path == "/api/v1/holdings":
        return "ASSET"
    if path in ("/api/v1/prices", "/api/v1/orderbook", "/api/v1/trades", "/api/v1/price-limits"):
        return "MARKET_DATA"
    if path == "/api/v1/candles":
        return "MARKET_DATA_CHART"
    if path == "/api/v1/stocks/all":
        return "STOCK_ALL"
    if path.startswith("/api/v1/stocks"):
        return "STOCK"
    if path in ("/api/v1/buying-power", "/api/v1/sellable-quantity", "/api/v1/commissions"):
        return "ORDER_INFO"
    if path == "/api/v1/orders" or _ORDER_ACTION.match(path):
        return "ORDER"
    if _ORDER_DETAIL.match(path):
        return "ORDER_HISTORY"
    return "MARKET_INFO"


class _Bucket:
    def __init__(self, capacity: int, now: float):
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.updated = now


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}

    def _bucket(self, group: str) -> _Bucket:
        b = self._buckets.get(group)
        if b is None:
            b = self._buckets[group] = _Bucket(GROUP_LIMITS.get(group, 3), self._clock())
        return b

    def _refill(self, b: _Bucket) -> None:
        now = self._clock()
        b.tokens = min(b.capacity, b.tokens + (now - b.updated) * b.capacity)  # 초당 capacity 개 재충전
        b.updated = now

    def acquire(self, group: str) -> None:
        while True:
            with self._lock:
                b = self._bucket(group)
                self._refill(b)
                if b.tokens >= 1.0:
                    b.tokens -= 1.0
                    return
                wait = (1.0 - b.tokens) / b.capacity
            self._sleep(wait)

    def update_from_headers(self, group: str, headers: Mapping[str, str]) -> None:
        raw = headers.get("X-RateLimit-Limit") or headers.get("x-ratelimit-limit")
        if not raw:
            return
        try:
            cap = int(raw)
        except ValueError:
            return
        with self._lock:
            b = self._bucket(group)
            if cap > 0 and cap != int(b.capacity):
                b.capacity = float(cap)
                b.tokens = min(b.tokens, b.capacity)

    @staticmethod
    def retry_after_seconds(headers: Mapping[str, str]) -> float | None:
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None
