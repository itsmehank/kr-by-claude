"""TokenManager — 선제 갱신·동시 발급 직렬화·invalidate. 토스 접촉 0 (MockTransport)."""
import threading
from decimal import Decimal

import httpx
import pytest

from kr_trading.config import TradeConfig
from kr_trading.toss.errors import TossApiError
from kr_trading.toss.token import TokenManager

CFG = TradeConfig(client_id="cid", client_secret="sec", account_seq=None,
                  base_url="https://toss.test", dry_run=True,
                  max_order_krw=Decimal("5000000"), max_daily_krw=Decimal("10000000"))


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=CFG.base_url)


def test_issues_once_and_caches():
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        assert req.url.path == "/oauth2/token"
        assert req.headers["content-type"].startswith("application/x-www-form-urlencoded")
        body = req.content.decode()
        assert "grant_type=client_credentials" in body and "client_id=cid" in body
        return httpx.Response(200, json={"access_token": "tok1", "token_type": "Bearer", "expires_in": 3600})

    tm = TokenManager(_client(handler), CFG)
    assert tm.get() == "tok1" and tm.get() == "tok1"
    assert len(calls) == 1


def test_refreshes_60s_before_expiry():
    now = [1000.0]
    n = [0]

    def handler(req):
        n[0] += 1
        return httpx.Response(200, json={"access_token": f"tok{n[0]}", "token_type": "Bearer", "expires_in": 120})

    tm = TokenManager(_client(handler), CFG, clock=lambda: now[0])
    assert tm.get() == "tok1"
    now[0] = 1000.0 + 59        # 만료 61초 전 → 아직 유효
    assert tm.get() == "tok1"
    now[0] = 1000.0 + 61        # 만료 59초 전 → 선제 갱신
    assert tm.get() == "tok2"


def test_invalidate_forces_reissue():
    n = [0]

    def handler(req):
        n[0] += 1
        return httpx.Response(200, json={"access_token": f"tok{n[0]}", "token_type": "Bearer", "expires_in": 3600})

    tm = TokenManager(_client(handler), CFG)
    assert tm.get() == "tok1"
    tm.invalidate()
    assert tm.get() == "tok2"


def test_concurrent_get_issues_once():
    """토큰은 클라이언트당 1개 — 동시 발급은 서로를 무효화하므로 Lock 으로 직렬화."""
    n = [0]
    gate = threading.Event()

    def handler(req):
        gate.wait(1.0)
        n[0] += 1
        return httpx.Response(200, json={"access_token": f"tok{n[0]}", "token_type": "Bearer", "expires_in": 3600})

    tm = TokenManager(_client(handler), CFG)
    results = []
    threads = [threading.Thread(target=lambda: results.append(tm.get())) for _ in range(5)]
    for t in threads: t.start()
    gate.set()
    for t in threads: t.join()
    assert n[0] == 1 and set(results) == {"tok1"}


def test_auth_failure_raises_toss_api_error():
    def handler(req):
        return httpx.Response(401, json={"error": {"code": "invalid-client", "message": "bad", "requestId": "r1"}})

    tm = TokenManager(_client(handler), CFG)
    with pytest.raises(TossApiError) as ei:
        tm.get()
    assert ei.value.status == 401 and ei.value.code == "invalid-client" and ei.value.request_id == "r1"
