"""미리보기 토큰 (spec §5 PreviewStore). 메모리·TTL 5분. clientOrderId 는 미리보기 시점에 생성.

서버 재시작 시 토큰 소멸 → 주문은 guard/preview-required 로 막힘(안전). 미리보기 재실행으로 복구.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import date
from typing import Callable

from kr_trading.audit import kst_today
from kr_trading.toss.errors import GuardError


def new_client_order_id(today: date | None = None) -> str:
    d = today or kst_today()
    return f"{d:%Y%m%d}-{uuid.uuid4().hex[:8]}"


def canonical_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PreviewStore:
    def __init__(self, ttl_sec: float = 300.0, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._items: dict[str, tuple[float, dict, dict]] = {}   # token -> (expires_at, payload, meta)

    def put(self, payload: dict, meta: dict) -> str:
        tok = canonical_hash(payload)
        with self._lock:
            self._evict_expired()
            self._items[tok] = (self._clock() + self._ttl, payload, meta)
        return tok

    def _evict_expired(self) -> None:
        now = self._clock()
        for tok in [t for t, (exp, _, _) in self._items.items() if now > exp]:
            del self._items[tok]

    def get(self, token: str) -> tuple[dict, dict] | None:
        with self._lock:
            item = self._items.get(token)
            if item is None:
                return None
            exp, payload, meta = item
            if self._clock() > exp:
                del self._items[token]
                return None
            return payload, meta

    def verify(self, token: str, payload: dict) -> dict:
        item = self.get(token)
        if item is None:
            raise GuardError("guard/preview-required", "미리보기가 없거나 만료됨 — 미리보기를 다시 실행하세요")
        stored, meta = item
        if canonical_hash(payload) != token or stored != payload:
            raise GuardError("guard/preview-mismatch", "미리보기한 내용과 주문 내용이 다릅니다")
        return meta

    def consume(self, token: str, payload: dict) -> dict:
        """verify 와 동일 검증을 거친 뒤 lock 안에서 pop — 동일 토큰 재제출 차단(#187 리뷰 I-3)."""
        with self._lock:
            item = self._items.get(token)
            if item is not None:
                exp, stored, meta = item
                if self._clock() > exp:
                    del self._items[token]
                    item = None
            if item is None:
                raise GuardError("guard/preview-required", "미리보기가 없거나 만료됨 — 미리보기를 다시 실행하세요")
            exp, stored, meta = item
            if canonical_hash(payload) != token or stored != payload:
                raise GuardError("guard/preview-mismatch", "미리보기한 내용과 주문 내용이 다릅니다")
            del self._items[token]
            return meta
