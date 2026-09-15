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


def test_429_then_401_reissues_and_retries():
    """Retry-After 대기 중 토큰이 무효화돼도 재발급 경로를 타야 한다(원인별 1회)."""
    seen = []; sleeps = []

    def h(req):
        seen.append(1)
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={"error": {"code": "rate-limit-exceeded", "message": ""}})
        if len(seen) == 2:
            return httpx.Response(401, json={"error": {"code": "token-revoked", "message": ""}})
        return httpx.Response(200, json={"result": {"currency": "KRW", "cashBuyingPower": "1"}})

    assert make(h, sleeps=sleeps).buying_power().cashBuyingPower == Decimal("1")
    assert len(seen) == 3 and sleeps == [1.0]   # 최초 + 레이트 재시도 + 인증 재시도 = 상한 3


def test_429_persisting_retries_once_then_raises():
    n = [0]; sleeps = []

    def h(req):
        n[0] += 1
        return httpx.Response(429, headers={"Retry-After": "1"}, json={"error": {"code": "rate-limit-exceeded", "message": ""}})

    with pytest.raises(TossApiError) as ei:
        make(h, sleeps=sleeps).holdings()
    assert n[0] == 2 and ei.value.code == "rate-limit-exceeded"   # 루프 금지


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


def test_last_request_id_is_thread_local():
    """싱글톤 TossClient 를 스레드풀 라우트가 공유해도 request_id 가 스레드 간에 새지 않는다."""
    import threading

    def h(req):
        rid = req.headers.get("x-test-rid", "main")
        return httpx.Response(200, headers={"X-Request-Id": f"rid-{rid}"},
                              json={"result": [{"symbol": "005930", "timestamp": None, "lastPrice": "1", "currency": "KRW"}]})

    c = make(h)
    seen = {}

    def worker(name):
        # 각 스레드가 자기 요청을 보내고 곧바로 자기 값을 읽는다 — 라우트 핸들러와 동일한 사용 패턴
        c._http.headers["x-test-rid"] = name          # 이 스레드의 요청을 식별하는 표식 (테스트용)
        c.prices(["005930"])
        seen[name] = c.last_request_id

    # 메인 스레드는 아직 아무 요청도 안 했다 → None
    assert c.last_request_id is None
    t = threading.Thread(target=worker, args=("t1",))
    t.start(); t.join()
    # 다른 스레드가 설정한 값은 메인 스레드에서 보이지 않는다(thread-local)
    assert c.last_request_id is None
    assert seen["t1"] == "rid-t1"


def test_two_threads_401_reissue_once():
    """두 스레드가 동시에 같은(T0) 토큰으로 401 token-revoked 를 받아도 재발급은 정확히
    1회만 일어난다 — compare-and-clear 없이는 두 번째 스레드의 invalidate() 가 첫 스레드가
    막 재발급한 토큰까지 지워 연쇄 재발급(및 최종 재시도 실패)을 유발한다."""
    import threading

    token_n = [0]
    token_lock = threading.Lock()

    def token_handler(req):
        with token_lock:
            token_n[0] += 1
            n = token_n[0]
        return httpx.Response(200, json={"access_token": f"tok{n}", "token_type": "Bearer", "expires_in": 3600})

    barrier = threading.Barrier(2)

    def api_handler(req):
        auth = req.headers.get("authorization")
        if auth == "Bearer tok1":
            barrier.wait(timeout=2)   # 두 스레드 모두 tok1 로 요청을 보낸 시점에 맞춰 401 을 함께 받게 한다
            return httpx.Response(401, json={"error": {"code": "token-revoked", "message": ""}})
        return httpx.Response(200, json={"result": {"currency": "KRW", "cashBuyingPower": "1"}})

    def route(req: httpx.Request):
        if req.url.path == "/oauth2/token":
            return token_handler(req)
        return api_handler(req)

    http = httpx.Client(transport=httpx.MockTransport(route), base_url=CFG.base_url)
    c = TossClient(CFG, http=http, sleep=lambda s: None)

    results = []
    results_lock = threading.Lock()

    def worker():
        r = c.buying_power().cashBuyingPower
        with results_lock:
            results.append(r)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start()
    t1.join(timeout=5); t2.join(timeout=5)

    assert sorted(results) == [Decimal("1"), Decimal("1")]
    assert c._token.issue_count == 2   # tok1(최초 발급) + tok2(정확히 1회 재발급) — tok3 연쇄 없음
