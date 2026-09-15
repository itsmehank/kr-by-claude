# tests/test_trade_api_orders.py
"""주문 라우트 — 미리보기 토큰 강제, DRY_RUN 무전송, 실주문 감사 INSERT→UPDATE, 토스 에러 시 감사 기록, 정정·취소."""
import json
from decimal import Decimal

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from kr_trading.config import TradeConfig
from kr_trading.preview import PreviewStore
from kr_trading.toss.client import TossClient
from trade_api import deps
from trade_api.main import app

BASE = dict(client_id="c", client_secret="s", account_seq=7, base_url="https://toss.test",
            max_order_krw=Decimal("5000000"), max_daily_krw=Decimal("10000000"))
DRY = TradeConfig(dry_run=True, **BASE)
LIVE = TradeConfig(dry_run=False, **BASE)
TOKEN_OK = httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
LIMITS = lambda r: httpx.Response(200, json={"result": {"timestamp": "t", "currency": "KRW", "upperLimitPrice": "91000", "lowerLimitPrice": "49000"}})
COMM = lambda r: httpx.Response(200, json={"result": [{"marketCountry": "KR", "commissionRate": "0.00015", "startDate": None, "endDate": None}]})
SELLABLE = lambda r: httpx.Response(200, json={"result": {"sellableQuantity": "5"}})


def toss_with(routes: dict, cfg, calls: list | None = None):
    def route(req):
        if calls is not None: calls.append((req.method, req.url.path))
        if req.url.path == "/oauth2/token": return TOKEN_OK
        fn = routes.get((req.method, req.url.path))
        return fn(req) if fn else httpx.Response(404, json={"error": {"code": "not-found", "message": ""}})
    return TossClient(cfg, http=httpx.Client(transport=httpx.MockTransport(route), base_url=cfg.base_url), sleep=lambda s: None)


@pytest.fixture
def db(test_db_url):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        c.execute("DELETE FROM toss_order_audit")
        # 앱의 get_conn 을 이 kr_test 연결로 — 미오버라이드 시 운영 DB 로 감(관례 tests/test_api_triggers.py:17).
        # autocommit 연결: 라우터의 conn.commit() 은 no-op, 모든 문장이 즉시 durable → pending 행 관측에 적합.
        def _override():
            yield c
        app.dependency_overrides[deps.get_conn] = _override
        yield c
        app.dependency_overrides.pop(deps.get_conn, None)


def setup_function():
    deps.reset_overrides()


READ_ROUTES = {("GET", "/api/v1/price-limits"): LIMITS, ("GET", "/api/v1/commissions"): COMM,
               ("GET", "/api/v1/sellable-quantity"): SELLABLE}
BUY = {"symbol": "005930", "side": "BUY", "orderType": "LIMIT", "quantity": "10", "price": "70000"}


def preview(client, body=BUY):
    r = client.post("/trade-api/orders/preview", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_preview_returns_token_and_client_order_id_without_calling_order_api(db):
    calls = []
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY, calls), preview=PreviewStore())
    p = preview(TestClient(app))
    assert p["clientOrderId"].startswith("2") and len(p["previewToken"]) == 64
    assert p["request"]["price"] == "70000" and p["request"]["clientOrderId"] == p["clientOrderId"]
    assert p["estimate"] == {"amount": "700000", "amountBasis": "limit", "commission": "105.00000", "total": "700105.00000"}
    assert p["dryRun"] is True
    assert ("POST", "/api/v1/orders") not in calls


def test_preview_guard_rejection_is_400_with_guard_code(db):
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY), preview=PreviewStore())
    r = TestClient(app).post("/trade-api/orders/preview", json={**BUY, "price": "70050"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "guard/tick-size"


def test_preview_rejects_invalid_side_literal(db):
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY), preview=PreviewStore())
    r = TestClient(app).post("/trade-api/orders/preview", json={**BUY, "side": "buy"})
    assert r.status_code == 422


def test_submit_without_preview_is_rejected(db):
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY), preview=PreviewStore())
    r = TestClient(app).post("/trade-api/orders", json={"previewToken": "x" * 64, "request": BUY})
    assert r.status_code == 400 and r.json()["error"]["code"] == "guard/preview-required"


def test_submit_mismatched_body_is_rejected(db):
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY), preview=PreviewStore())
    c = TestClient(app)
    p = preview(c)
    tampered = {**p["request"], "quantity": "100"}
    r = c.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": tampered})
    assert r.status_code == 400 and r.json()["error"]["code"] == "guard/preview-mismatch"


def test_dry_run_submit_records_audit_and_does_not_call_toss(db):
    calls = []
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY, calls), preview=PreviewStore())
    c = TestClient(app)
    p = preview(c)
    r = c.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": p["request"]})
    assert r.status_code == 200
    body = r.json()
    assert body["dryRun"] is True and body["orderId"] is None and body["clientOrderId"] == p["clientOrderId"]
    assert ("POST", "/api/v1/orders") not in calls
    row = db.execute("SELECT kind, dry_run, http_status, order_amount_krw, side FROM toss_order_audit WHERE id=%s", (body["auditId"],)).fetchone()
    assert row == ("create", True, 0, Decimal("700000.00"), "BUY")


def test_live_submit_audit_insert_then_update(db):
    seen = {}
    def create(req):
        seen["body"] = json.loads(req.content)
        pending = db.execute("SELECT http_status FROM toss_order_audit WHERE client_order_id=%s", (seen["body"]["clientOrderId"],)).fetchone()
        seen["pending_at_send"] = pending
        return httpx.Response(200, headers={"X-Request-Id": "req-7"}, json={"result": {"orderId": "ord_9", "clientOrderId": seen["body"]["clientOrderId"]}})
    deps.set_test_overrides(cfg=LIVE, toss=toss_with({**READ_ROUTES, ("POST", "/api/v1/orders"): create}, LIVE), preview=PreviewStore())
    c = TestClient(app)
    p = preview(c)
    r = c.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": p["request"]})
    assert r.status_code == 200 and r.json()["orderId"] == "ord_9" and r.json()["dryRun"] is False
    assert seen["pending_at_send"] == (None,)            # 전송 시점에 pending 행이 이미 존재
    assert seen["body"]["price"] == "70000" and seen["body"]["clientOrderId"] == p["clientOrderId"]
    row = db.execute("SELECT http_status, order_id, dry_run, request_id FROM toss_order_audit WHERE id=%s", (r.json()["auditId"],)).fetchone()
    assert row == (200, "ord_9", False, "req-7")


def test_live_submit_toss_error_is_recorded_and_passed_through(db):
    def create(req):
        return httpx.Response(422, json={"error": {"code": "insufficient-buying-power", "message": "잔고", "requestId": "r-1", "data": {"needKrw": "1"}}})
    deps.set_test_overrides(cfg=LIVE, toss=toss_with({**READ_ROUTES, ("POST", "/api/v1/orders"): create}, LIVE), preview=PreviewStore())
    c = TestClient(app)
    p = preview(c)
    r = c.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": p["request"]})
    assert r.status_code == 422 and r.json()["error"] == {"code": "insufficient-buying-power", "message": "잔고", "data": {"needKrw": "1"}, "requestId": "r-1"}
    row = db.execute("SELECT http_status, error_code, request_id FROM toss_order_audit WHERE client_order_id=%s", (p["clientOrderId"],)).fetchone()
    assert row == (422, "insufficient-buying-power", "r-1")


def test_pending_row_is_durable_to_other_sessions_before_send(test_db_url):
    """commit-before-send 계약 pin — 비-autocommit 오버라이드(운영 풀 연결과 동형) + **제2 세션**에서
    전송 시점의 pending 행을 관측한다. 라우터의 begin 직후 conn.commit() 이 빠지면 제2 세션은 행을 못 본다.
    (기존 test_live_submit_* 는 autocommit 동일 연결이라 commit 유무를 구분하지 못함 — 리뷰 I-1)"""
    seen = {}
    c1 = psycopg.connect(test_db_url)                    # 비-autocommit
    c1.execute("DELETE FROM toss_order_audit"); c1.commit()

    def _override():
        yield c1
        c1.commit()                                      # 풀 컨텍스트의 정상 종료 commit 과 동형

    app.dependency_overrides[deps.get_conn] = _override
    try:
        def create(req):
            body = json.loads(req.content)
            with psycopg.connect(test_db_url, autocommit=True) as c2:   # 독립 세션
                seen["other_session"] = c2.execute(
                    "SELECT http_status FROM toss_order_audit WHERE client_order_id=%s",
                    (body["clientOrderId"],)).fetchone()
            return httpx.Response(200, json={"result": {"orderId": "ord_d", "clientOrderId": body["clientOrderId"]}})
        deps.set_test_overrides(cfg=LIVE, toss=toss_with({**READ_ROUTES, ("POST", "/api/v1/orders"): create}, LIVE), preview=PreviewStore())
        c = TestClient(app)
        p = preview(c)
        r = c.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": p["request"]})
        assert r.status_code == 200, r.text
        assert seen["other_session"] == (None,)          # 전송 시점에 타 세션이 pending 행을 봄 = commit 됨
        with psycopg.connect(test_db_url, autocommit=True) as c3:
            assert c3.execute("SELECT http_status, order_id FROM toss_order_audit WHERE id=%s",
                              (r.json()["auditId"],)).fetchone() == (200, "ord_d")
    finally:
        app.dependency_overrides.pop(deps.get_conn, None)
        c1.close()


def test_daily_cap_uses_audit(db):
    db.execute("INSERT INTO toss_order_audit (kind, symbol, side, order_amount_krw, request_json, dry_run, http_status) VALUES ('create','005930','BUY',9500000,'{}',false,200)")
    deps.set_test_overrides(cfg=LIVE, toss=toss_with(READ_ROUTES, LIVE), preview=PreviewStore())
    r = TestClient(app).post("/trade-api/orders/preview", json=BUY)     # 950만 + 70만 > 1000만
    assert r.status_code == 400 and r.json()["error"]["code"] == "guard/max-daily-amount"


def test_daily_cap_rechecked_at_submit(db):
    """미리보기 시점엔 둘 다 통과(총액 0) but 첫 제출 후 제출 시점 재검(I-2)이 둘째를 막는다."""
    def create(req):
        body = json.loads(req.content)
        return httpx.Response(200, json={"result": {"orderId": "ord_cap", "clientOrderId": body["clientOrderId"]}})
    live_cap = TradeConfig(dry_run=False, client_id="c", client_secret="s", account_seq=7, base_url="https://toss.test",
                           max_order_krw=Decimal("7000000"), max_daily_krw=Decimal("10000000"))
    deps.set_test_overrides(cfg=live_cap, toss=toss_with({**READ_ROUTES, ("POST", "/api/v1/orders"): create}, live_cap), preview=PreviewStore())
    c = TestClient(app)
    big = {"symbol": "005930", "side": "BUY", "orderType": "LIMIT", "quantity": "100", "price": "60000"}  # 600만원
    p1 = preview(c, big)
    p2 = preview(c, big)   # 둘 다 미리보기 시점 누적 0 → 통과
    r1 = c.post("/trade-api/orders", json={"previewToken": p1["previewToken"], "request": p1["request"]})
    assert r1.status_code == 200, r1.text
    r2 = c.post("/trade-api/orders", json={"previewToken": p2["previewToken"], "request": p2["request"]})
    assert r2.status_code == 400 and r2.json()["error"]["code"] == "guard/max-daily-amount"
    rows = db.execute("SELECT count(*) FROM toss_order_audit WHERE kind='create' AND http_status=200").fetchone()
    assert rows == (1,)


def test_cancel_and_modify_with_audit(db):
    order = {"orderId": "ord_1", "symbol": "005930", "side": "BUY", "orderType": "LIMIT", "timeInForce": "DAY",
             "status": "PENDING", "price": "70000", "quantity": "10", "orderAmount": None, "currency": "KRW",
             "orderedAt": "2026-09-14T09:00:00+09:00", "canceledAt": None,
             "execution": {"filledQuantity": "0", "averageFilledPrice": None, "filledAmount": None, "commission": None, "tax": None, "filledAt": None, "settlementDate": None}}
    routes = {**READ_ROUTES,
              ("GET", "/api/v1/orders/ord_1"): lambda r: httpx.Response(200, json={"result": order}),
              ("POST", "/api/v1/orders/ord_1/cancel"): lambda r: httpx.Response(200, json={"result": {"orderId": "ord_2"}}),
              ("POST", "/api/v1/orders/ord_1/modify"): lambda r: httpx.Response(200, json={"result": {"orderId": "ord_3"}}),
              ("GET", "/api/v1/orders"): lambda r: httpx.Response(200, json={"result": {"orders": [order], "nextCursor": None, "hasNext": False}})}
    deps.set_test_overrides(cfg=LIVE, toss=toss_with(routes, LIVE), preview=PreviewStore())
    c = TestClient(app)
    # 취소
    r = c.post("/trade-api/orders/ord_1/cancel")
    assert r.status_code == 200 and r.json()["orderId"] == "ord_2"
    assert db.execute("SELECT kind, http_status, order_id FROM toss_order_audit WHERE id=%s", (r.json()["auditId"],)).fetchone() == ("cancel", 200, "ord_2")
    # 정정 미리보기 → 제출 (1일 누적은 재검 안 함)
    db.execute("INSERT INTO toss_order_audit (kind, symbol, side, order_amount_krw, request_json, dry_run, http_status) VALUES ('create','005930','BUY',9900000,'{}',false,200)")
    p = c.post("/trade-api/orders/modify/preview", json={"orderId": "ord_1", "orderType": "LIMIT", "quantity": "15", "price": "71000"})
    assert p.status_code == 200, p.text
    assert p.json()["estimate"]["amount"] == "1065000" and p.json()["clientOrderId"] is None
    r = c.post("/trade-api/orders/ord_1/modify", json={"previewToken": p.json()["previewToken"], "orderId": "ord_1", "request": {"orderType": "LIMIT", "quantity": "15", "price": "71000"}})
    assert r.status_code == 200 and r.json()["orderId"] == "ord_3"
    assert db.execute("SELECT kind, http_status FROM toss_order_audit WHERE id=%s", (r.json()["auditId"],)).fetchone() == ("modify", 200)
    # 목록·상세 그대로 전달
    assert c.get("/trade-api/orders?status=OPEN").json()["orders"][0]["price"] == "70000"
    assert c.get("/trade-api/orders/ord_1").json()["execution"]["filledQuantity"] == "0"
