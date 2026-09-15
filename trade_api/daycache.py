# trade_api/daycache.py
"""KST 일 단위 캐시(#187 리뷰 추가 정리) — 하루 동안 불변인 토스 응답(price_limits·commissions)을
프로세스 메모리에 캐시해 매 preview·quote 폴링마다 토스를 재호출하지 않는다.

키에 kst_today() 를 자동 포함 — 자정을 넘기면 전날 항목은 다음 get() 에서 자연히 미스된다. put() 은
호출될 때마다 오늘 날짜가 아닌 키를 lock 하에 정리한다(#187 최종 수정웨이브) — 메모리는 항상 하루치만
남는다. TossClient 교체(`deps.set_test_overrides(toss=…)`)·`deps.reset_overrides()` 시에는
`register_reset_hook` 경유로 명시적으로 비운다 — 다른 계정·환경의 응답이 새 클라이언트로 넘어가지
않게.

캐시 금지: `warnings`(장중 VI 변동)·`prices`/`orderbook`(실시간 시세) — 이들은 여기 넣지 않는다.
"""
from __future__ import annotations

import threading
from datetime import date
from typing import Any, Callable

from kr_trading.audit import kst_today
from kr_trading.toss.client import TossClient
from trade_api.deps import register_reset_hook


class DayCache:
    """KST 일 단위 캐시 — 키에 kst_today() 를 자동 포함. TossClient 교체·reset 시 비움(register_reset_hook)."""

    def __init__(self, today: Callable[[], date] = kst_today) -> None:
        self._today = today
        self._lock = threading.Lock()
        self._items: dict[tuple, Any] = {}

    def get(self, *parts: Any) -> Any | None:
        key = (self._today(), *parts)
        with self._lock:
            return self._items.get(key)

    def put(self, *parts: Any, value: Any) -> None:
        key = (self._today(), *parts)
        with self._lock:
            self._items = {k: v for k, v in self._items.items() if k[0] == key[0]}   # 전날 키 정리
            self._items[key] = value

    def reset(self) -> None:
        with self._lock:
            self._items.clear()


price_limits_cache = DayCache()
commissions_cache = DayCache()
register_reset_hook(price_limits_cache.reset)
register_reset_hook(commissions_cache.reset)


def cached_price_limits(toss: TossClient, symbol: str) -> Any:
    """price_limits(symbol) 를 일 단위 캐시 경유로 — orders.py(_guard)·market.py(quote) 공용.

    price_limits(상하한가)는 거래소 규정상 하루 동안 불변이라 일 단위 캐시에 적합. price_limits 를
    이 함수 밖에서 직접 호출하지 않는다(중복 캐시 우회 방지).
    """
    cached = price_limits_cache.get("limits", symbol)
    if cached is not None:
        return cached
    limits = toss.price_limits(symbol)
    price_limits_cache.put("limits", symbol, value=limits)
    return limits
