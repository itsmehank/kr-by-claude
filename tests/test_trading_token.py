"""TokenManager — 선제 갱신·동시 발급 직렬화·invalidate. 토스 접촉 0 (MockTransport)."""
import threading
import time
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


def test_invalidate_compare_and_clear():
    """다른 요청이 이미 쓴(stale) 토큰으로 invalidate 하면 no-op — 현재 토큰과 일치할 때만 비운다."""
    n = [0]

    def handler(req):
        n[0] += 1
        return httpx.Response(200, json={"access_token": f"tok{n[0]}", "token_type": "Bearer", "expires_in": 3600})

    tm = TokenManager(_client(handler), CFG)
    assert tm.get() == "tok1"
    tm.invalidate("stale")          # 현재 토큰(tok1)과 다름 → no-op
    assert tm.get() == "tok1"
    assert tm.issue_count == 1
    tm.invalidate("tok1")           # 현재 토큰과 일치 → 비움
    assert tm.get() == "tok2"


def test_get_never_returns_none_under_concurrent_invalidate():
    """get() 은 fast-path·lock-path 모두 스냅샷 한 번만 읽어 None 을 절대 반환하지 않는다."""
    n = [0]

    def handler(req):
        n[0] += 1
        return httpx.Response(200, json={"access_token": f"tok{n[0]}", "token_type": "Bearer", "expires_in": 3600})

    tm = TokenManager(_client(handler), CFG)
    tm.get()  # 초기 발급

    results = []

    def invalidator():
        for _ in range(300):
            tm.invalidate()
            time.sleep(0)

    def getter():
        for _ in range(300):
            results.append(tm.get())
            time.sleep(0)

    ti = threading.Thread(target=invalidator)
    tg = threading.Thread(target=getter)
    ti.start(); tg.start()
    ti.join(); tg.join()

    assert len(results) == 300
    for r in results:
        assert isinstance(r, str) and r.startswith("tok")
