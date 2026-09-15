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

    def _valid_token(self, tok: str | None) -> bool:
        return tok is not None and self._clock() < self._expires_at - REFRESH_MARGIN_SEC

    def get(self) -> str:
        # 스냅샷을 한 번만 읽어 검사·반환 모두에 쓴다 — _valid() 와 반환을 별도로 self._token 을
        # 두 번 읽으면, 그 사이에 다른 스레드의 invalidate() 가 끼어들 때 None 이 반환될 수 있다.
        tok = self._token
        if self._valid_token(tok):
            return tok  # type: ignore[return-value]
        with self._lock:
            tok = self._token
            if self._valid_token(tok):  # 다른 스레드가 방금 갱신
                return tok  # type: ignore[return-value]
            resp = self._http.post(
                "/oauth2/token",
                data={"grant_type": "client_credentials",
                      "client_id": self._cfg.client_id,
                      "client_secret": self._cfg.client_secret},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            raise_for_envelope(resp)
            body = resp.json()
            issued = body["access_token"]
            self._token = issued
            self._expires_at = self._clock() + float(body.get("expires_in", 0))
            self.issue_count += 1
            return issued

    def invalidate(self, used: str | None = None) -> None:
        """토큰을 무효화한다. `used` 를 주면 **현재 토큰과 일치할 때만** 비운다(compare-and-clear) —
        요청을 보낸 뒤 다른 스레드가 이미 재발급했다면(현재 토큰이 달라졌다면) no-op: 방금 발급된
        새 토큰까지 지워 연쇄 재발급을 일으키는 것을 막는다. `used=None`(기본값)이면 기존처럼
        무조건 비운다."""
        with self._lock:
            if used is None or self._token == used:
                self._token = None
                self._expires_at = 0.0
