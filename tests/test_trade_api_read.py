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


_REAL_TICKERS = ('005930', '000660', '035420')


@pytest.fixture
def db(test_db_url):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        c.execute("DELETE FROM positions WHERE symbol IN ('005930','000660')")
        # 실 종목 3개는 fixture 종료 시 원상복구 대상 — upsert 전 스냅샷(없으면 fixture 가 만든 신규 행으로 취급)
        prev = c.execute(
            "SELECT ticker, name, market, delisted_at, is_common FROM stocks WHERE ticker = ANY(%s)",
            (list(_REAL_TICKERS),),
        ).fetchall()
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
        # stocks 를 fixture 진입 전 상태로 원상복구
        prev_tickers = {row[0] for row in prev}
        for ticker, name, market, delisted_at, is_common in prev:
            c.execute(
                "UPDATE stocks SET name=%s, market=%s, delisted_at=%s, is_common=%s WHERE ticker=%s",
                (name, market, delisted_at, is_common, ticker),
            )
        created = [t for t in _REAL_TICKERS if t not in prev_tickers]
        if created:
            c.execute("DELETE FROM stocks WHERE ticker = ANY(%s)", (created,))


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


def test_holdings_uses_store_get_open_positions(db, monkeypatch):
    """holdings.py 가 store.get_open_positions(conn) 을 재사용하는지 — 원시 SELECT 로 되돌아가지 않게 고정(#187 리뷰 추가 정리)."""
    calls = []

    def stub(conn):
        calls.append(conn)
        return [{"symbol": "035420", "quantity": 1}]

    monkeypatch.setattr("trade_api.routers.holdings.get_open_positions", stub)
    holdings = {"totalPurchaseAmount": M("1"), "marketValue": M("1"), "profitLoss": M("0"), "dailyProfitLoss": M("0"),
                "items": [item("005930", "삼성전자", "12"),      # 스텁 결과에 없음 → missing
                          item("000660", "SK하이닉스", "3"),     # 스텁 결과에 없음 → missing
                          item("035420", "NAVER", "1")]}         # 스텁 qty 1 == toss qty 1 → mismatch 없음
    deps.set_test_overrides(cfg=CFG, toss=toss_with({"/api/v1/holdings": lambda r: httpx.Response(200, json={"result": holdings})}))
    r = TestClient(app).get("/trade-api/holdings")
    assert r.status_code == 200, r.text
    assert calls, "get_open_positions(conn) 이 호출되지 않음"
    body = r.json()
    assert sorted((m["symbol"], m["kind"]) for m in body["mismatch"]) == [("000660", "missing"), ("005930", "missing")]


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


# ── Task 4(#187 리뷰): Decimal 정수 정규화·prices 빈 응답 guard·ILIKE 이스케이프 ──

def test_quote_normalizes_kr_decimals(db):
    routes = {
        "/api/v1/prices": lambda r: httpx.Response(200, json={"result": [{"symbol": "005930", "timestamp": None, "lastPrice": "70000.0", "currency": "KRW"}]}),
        "/api/v1/orderbook": lambda r: httpx.Response(200, json={"result": {"timestamp": None, "currency": "KRW", "asks": [{"price": "70100.0", "volume": "5.0"}], "bids": []}}),
        "/api/v1/price-limits": lambda r: httpx.Response(200, json={"result": {"timestamp": "t", "currency": "KRW", "upperLimitPrice": "91000.00", "lowerLimitPrice": "49000.0"}}),
        "/api/v1/stocks/005930/warnings": lambda r: httpx.Response(200, json={"result": []}),
    }
    deps.set_test_overrides(cfg=CFG, toss=toss_with(routes))
    body = TestClient(app).get("/trade-api/quote/005930").json()
    assert body["price"]["lastPrice"] == "70000"
    assert body["limits"]["upperLimitPrice"] == "91000" and body["limits"]["lowerLimitPrice"] == "49000"
    assert body["orderbook"]["asks"][0]["price"] == "70100" and body["orderbook"]["asks"][0]["volume"] == "5"


def test_sellable_normalizes():
    routes = {"/api/v1/sellable-quantity": lambda r: httpx.Response(200, json={"result": {"sellableQuantity": "10.0"}})}
    deps.set_test_overrides(cfg=CFG, toss=toss_with(routes))
    assert TestClient(app).get("/trade-api/sellable/005930").json() == {"sellableQuantity": "10"}


def test_holdings_normalizes_kr_quantities(db):
    holdings = {"totalPurchaseAmount": M("1"), "marketValue": M("1"), "profitLoss": M("0"), "dailyProfitLoss": M("0"),
                "items": [item("000660", "SK하이닉스", "12.0")]}   # positions qty NULL → 판정 생략, 정규화만 확인
    deps.set_test_overrides(cfg=CFG, toss=toss_with({"/api/v1/holdings": lambda r: httpx.Response(200, json={"result": holdings})}))
    body = TestClient(app).get("/trade-api/holdings").json()
    assert body["overview"]["items"][0]["quantity"] == "12"
    assert body["mismatch"] == []   # positions.quantity 는 NULL → 대조 생략(기존 규칙 불변)


def test_quote_empty_prices_is_guard_error(db):
    routes = {"/api/v1/prices": lambda r: httpx.Response(200, json={"result": []})}
    deps.set_test_overrides(cfg=CFG, toss=toss_with(routes))
    r = TestClient(app).get("/trade-api/quote/005930")
    assert r.status_code == 400 and r.json()["error"]["code"] == "guard/symbol-unpriced"


def test_quote_delisted_local_ticker_is_guard_error(db):
    calls = []

    def route(req):
        calls.append((req.method, req.url.path))
        return httpx.Response(404, json={"error": {"code": "not-found", "message": ""}})

    toss = TossClient(CFG, http=httpx.Client(transport=httpx.MockTransport(route), base_url=CFG.base_url), sleep=lambda s: None)
    deps.set_test_overrides(cfg=CFG, toss=toss)
    r = TestClient(app).get("/trade-api/quote/TRDT02")   # db 픽스처가 상폐 처리한 시드
    assert r.status_code == 400 and r.json()["error"]["code"] == "guard/symbol-unpriced"
    assert calls == []   # 로컬에서 이미 걸러져 토스 호출 0


def test_search_escapes_wildcards(db):
    """`_`/`%` 는 리터럴로 취급돼야 한다 — 이스케이프 안 되면 와일드카드로 전체 종목과 매치되므로,
    리터럴 `_`·`%` 를 포함하지 않는 시드(TRDT01/02)가 결과에 섞여 들어오는지로 판정한다
    (실 kr_test 에는 다른 테스트 모듈이 남긴 literal `_` 포함 티커가 존재해 빈 리스트 단언은 순서의존 오탐)."""
    deps.set_test_overrides(cfg=CFG, toss=toss_with({}))
    c = TestClient(app)
    assert "TRDT01" not in [h["ticker"] for h in c.get("/trade-api/search?q=_").json()]
    assert "TRDT01" not in [h["ticker"] for h in c.get("/trade-api/search?q=%25").json()]
    assert [h["ticker"] for h in c.get("/trade-api/search?q=트레이드검색").json()] == ["TRDT01"]
