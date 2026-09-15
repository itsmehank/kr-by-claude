"""읽기 라우트 — holdings mismatch 3규칙, search 상폐 필터, quote 묶음."""
from decimal import Decimal

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from kr_trading.config import TradeConfig
from kr_trading.toss.client import TossClient
from trade_api import deps
from trade_api.main import app

CFG = TradeConfig(client_id="c", client_secret="s", account_seq=7, base_url="https://toss.test",
                  dry_run=True, max_order_krw=Decimal("5000000"), max_daily_krw=Decimal("10000000"))
TOKEN_OK = httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
M = lambda krw: {"krw": krw, "usd": None}


def item(sym, name, qty):
    return {"symbol": sym, "name": name, "marketCountry": "KR", "currency": "KRW", "quantity": qty,
            "lastPrice": "1000", "averagePurchasePrice": "900", "marketValue": M("1"), "profitLoss": M("1"),
            "dailyProfitLoss": M("0"), "cost": M("1")}


def toss_with(routes: dict):
    def route(req):
        if req.url.path == "/oauth2/token": return TOKEN_OK
        fn = routes.get(req.url.path)
        return fn(req) if fn else httpx.Response(404, json={"error": {"code": "not-found", "message": ""}})
    return TossClient(CFG, http=httpx.Client(transport=httpx.MockTransport(route), base_url=CFG.base_url), sleep=lambda s: None)


@pytest.fixture
def db(test_db_url):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        c.execute("DELETE FROM positions")
        c.execute("INSERT INTO stocks (ticker, name, market) VALUES ('005930','삼성전자','KOSPI'),('000660','SK하이닉스','KOSPI'),('035420','NAVER','KOSPI') ON CONFLICT (ticker) DO UPDATE SET name=EXCLUDED.name, delisted_at=NULL, is_common=TRUE")
        # 검색 테스트 전용 시드 — 고유 마커(TRDT%). 다른 모듈이 '삼성전자' 이름으로 테스트 티커(RVSP·OLD·ADJ1…)를
        # 남기므로 실명(삼성/0059)으로 정확 일치 단언하면 전체 suite 에서 순서 의존 실패(리포 관례 TRGTEST%/EXCTEST%).
        c.execute("DELETE FROM stocks WHERE ticker LIKE 'TRDT%'")
        c.execute("INSERT INTO stocks (ticker, name, market) VALUES ('TRDT01','트레이드검색A','KOSPI'),('TRDT02','트레이드검색B상폐','KOSDAQ')")
        c.execute("UPDATE stocks SET delisted_at='2025-01-01' WHERE ticker='TRDT02'")
        c.execute("INSERT INTO positions (symbol, entry_date, entry_price, quantity) VALUES ('005930','2026-09-01',70000,10)")
        c.execute("INSERT INTO positions (symbol, entry_date, entry_price, quantity) VALUES ('000660','2026-09-01',200000,NULL)")
        # 앱의 get_conn 을 이 kr_test 연결로 — 미오버라이드 시 Config.load().database_url(운영) 로 감
        # (리포 관례 tests/test_api_triggers.py:17). autocommit 연결이라 라우터의 conn.commit() 은 no-op.
        def _override():
            yield c
        app.dependency_overrides[deps.get_conn] = _override
        yield c
        app.dependency_overrides.pop(deps.get_conn, None)
        c.execute("DELETE FROM positions WHERE symbol IN ('005930','000660')")
        c.execute("DELETE FROM stocks WHERE ticker LIKE 'TRDT%'")


def setup_function():
    deps.reset_overrides()


def test_holdings_mismatch_rules(db):
    holdings = {"totalPurchaseAmount": M("1"), "marketValue": M("1"), "profitLoss": M("0"), "dailyProfitLoss": M("0"),
                "items": [item("005930", "삼성전자", "12"),      # positions qty 10 → qty_diff
                          item("000660", "SK하이닉스", "3"),     # positions qty NULL → 판정 생략
                          item("035420", "NAVER", "1")]}       # positions 없음 → missing
    deps.set_test_overrides(cfg=CFG, toss=toss_with({"/api/v1/holdings": lambda r: httpx.Response(200, json={"result": holdings})}))
    r = TestClient(app).get("/trade-api/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body["overview"]["items"][0]["quantity"] == "12"
    assert sorted((m["symbol"], m["kind"]) for m in body["mismatch"]) == [("005930", "qty_diff"), ("035420", "missing")]
    assert next(m for m in body["mismatch"] if m["symbol"] == "005930")["positionQty"] == "10"


def test_search_excludes_delisted(db):
    deps.set_test_overrides(cfg=CFG, toss=toss_with({}))
    c = TestClient(app)
    assert [h["ticker"] for h in c.get("/trade-api/search?q=트레이드검색").json()] == ["TRDT01"]   # 상폐 TRDT02 제외
    assert c.get("/trade-api/search?q=B상폐").json() == []
    assert c.get("/trade-api/search?q=TRDT01").json()[0]["ticker"] == "TRDT01"                      # 정확 티커 우선
    assert c.get("/trade-api/search?q=TRDT0").json()[0]["name"] == "트레이드검색A"


def test_quote_bundle(db):
    routes = {
        "/api/v1/prices": lambda r: httpx.Response(200, json={"result": [{"symbol": "005930", "timestamp": None, "lastPrice": "70000", "currency": "KRW"}]}),
        "/api/v1/orderbook": lambda r: httpx.Response(200, json={"result": {"timestamp": None, "currency": "KRW", "asks": [{"price": "70100", "volume": "5"}], "bids": [{"price": "70000", "volume": "7"}]}}),
        "/api/v1/price-limits": lambda r: httpx.Response(200, json={"result": {"timestamp": "t", "currency": "KRW", "upperLimitPrice": "91000", "lowerLimitPrice": "49000"}}),
        "/api/v1/stocks/005930/warnings": lambda r: httpx.Response(200, json={"result": [{"warningType": "OVERHEATED", "exchange": "KRX", "startDate": None, "endDate": None}]}),
    }
    deps.set_test_overrides(cfg=CFG, toss=toss_with(routes))
    body = TestClient(app).get("/trade-api/quote/005930").json()
    assert body["name"] == "삼성전자" and body["price"]["lastPrice"] == "70000"
    assert body["limits"]["upperLimitPrice"] == "91000" and body["warnings"][0]["warningType"] == "OVERHEATED"
    assert body["orderbook"]["asks"][0]["price"] == "70100"


def test_buying_power_and_sellable():
    routes = {
        "/api/v1/buying-power": lambda r: httpx.Response(200, json={"result": {"currency": "KRW", "cashBuyingPower": "1234567"}}),
        "/api/v1/sellable-quantity": lambda r: httpx.Response(200, json={"result": {"sellableQuantity": "8"}}),
    }
    deps.set_test_overrides(cfg=CFG, toss=toss_with(routes))
    c = TestClient(app)
    assert c.get("/trade-api/buying-power").json() == {"currency": "KRW", "cashBuyingPower": "1234567"}
    assert c.get("/trade-api/sellable/005930").json() == {"sellableQuantity": "8"}
