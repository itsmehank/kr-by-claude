"""trade_api 골격 — health 응답 모델(Decimal→str), accounts(계좌 헤더 없이), 에러 핸들러 2종."""
from decimal import Decimal

import httpx
from fastapi.testclient import TestClient

from kr_trading.config import TradeConfig
from kr_trading.toss.client import TossClient
from trade_api import deps
from trade_api.main import app

CFG = TradeConfig(client_id="cid", client_secret="sec", account_seq=None, base_url="https://toss.test",
                  dry_run=True, max_order_krw=Decimal("5000000"), max_daily_krw=Decimal("10000000"))
TOKEN_OK = httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})


def toss_with(handler, cfg=CFG):
    def route(req):
        return TOKEN_OK if req.url.path == "/oauth2/token" else handler(req)
    return TossClient(cfg, http=httpx.Client(transport=httpx.MockTransport(route), base_url=cfg.base_url), sleep=lambda s: None)


def setup_function():
    deps.reset_overrides()


def test_health_uses_response_model_strings():
    deps.set_test_overrides(cfg=CFG, toss=toss_with(lambda r: httpx.Response(500)))
    r = TestClient(app).get("/trade-api/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"dryRun": True, "maxOrderKrw": "5000000", "maxDailyKrw": "10000000", "accountSeq": None}
    assert isinstance(body["maxOrderKrw"], str)     # bare dict 였다면 5000000(int/float)


def test_accounts_without_account_seq():
    seen = {}
    def h(req):
        seen.update(req.headers); seen["path"] = req.url.path
        return httpx.Response(200, json={"result": [{"accountNo": "123", "accountSeq": 7, "accountType": "BROKERAGE"}]})
    deps.set_test_overrides(cfg=CFG, toss=toss_with(h))
    r = TestClient(app).get("/trade-api/accounts")
    assert r.status_code == 200 and r.json() == [{"accountNo": "123", "accountSeq": 7, "accountType": "BROKERAGE"}]
    assert seen["path"] == "/api/v1/accounts" and "x-tossinvest-account" not in seen


def test_toss_error_passthrough_handler():
    def h(req):
        return httpx.Response(403, json={"error": {"code": "edge-blocked", "message": "ip", "requestId": "r1", "data": None}})
    deps.set_test_overrides(cfg=CFG, toss=toss_with(h))
    r = TestClient(app).get("/trade-api/accounts")
    assert r.status_code == 403
    assert r.json() == {"error": {"code": "edge-blocked", "message": "ip", "data": None, "requestId": "r1"}}


def test_guard_error_handler_400():
    deps.set_test_overrides(cfg=CFG, toss=toss_with(lambda r: httpx.Response(200, json={"result": {}})))
    r = TestClient(app).get("/trade-api/buying-power")   # account_seq None → guard/account-seq-missing
    assert r.status_code == 400 and r.json()["error"]["code"] == "guard/account-seq-missing"
