"""OAuth2 client_credentials 토큰 매니저.

제약(요약 문서 §3): 클라이언트당 유효 토큰 1개 — 재발급 시 이전 토큰 즉시 무효.
→ 프로세스 내 싱글톤 + Lock 직렬화, 만료 60초 전 선제 갱신, 디스크 저장 금지.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

import httpx

from kr_trading.config import TradeConfig
from kr_trading.toss.errors import TossApiError

REFRESH_MARGIN_SEC = 60.0


def raise_for_envelope(resp: httpx.Response) -> None:
    """4xx/5xx 면 에러 envelope 을 TossApiError 로. 본문이 envelope 이 아니면 code='http-error'."""
    if resp.status_code < 400:
        return
    try:
        err = resp.json().get("error", {}) or {}
    except ValueError:
        err = {}
    raise TossApiError(
        status=resp.status_code,
        code=err.get("code") or "http-error",
        message=err.get("message") or "",
        data=err.get("data"),
        request_id=err.get("requestId") or resp.headers.get("X-Request-Id"),
    )


class TokenManager:
    def __init__(self, http: httpx.Client, cfg: TradeConfig,
                 clock: Callable[[], float] = time.monotonic):
        self._http = http
        self._cfg = cfg
        self._clock = clock
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0
        self.issue_count = 0

    def _valid(self) -> bool:
        return self._token is not None and self._clock() < self._expires_at - REFRESH_MARGIN_SEC

    def get(self) -> str:
        if self._valid():
            return self._token  # type: ignore[return-value]
        with self._lock:
            if self._valid():           # 다른 스레드가 방금 갱신
                return self._token  # type: ignore[return-value]
            resp = self._http.post(
                "/oauth2/token",
                data={"grant_type": "client_credentials",
                      "client_id": self._cfg.client_id,
                      "client_secret": self._cfg.client_secret},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            raise_for_envelope(resp)
            body = resp.json()
            self._token = body["access_token"]
            self._expires_at = self._clock() + float(body.get("expires_in", 0))
            self.issue_count += 1
            return self._token

    def invalidate(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0
