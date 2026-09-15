# tests/test_trade_api_orders.py
"""주문 라우트 — 미리보기 토큰 강제, DRY_RUN 무전송, 실주문 감사 INSERT→UPDATE, 토스 에러 시 감사 기록, 정정·취소."""
import json
import threading
import time
from decimal import Decimal

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from kr_trading.audit import AuditLog
from kr_trading.config import TradeConfig
from kr_trading.preview import PreviewStore
from kr_trading.toss.client import TossClient
from trade_api import deps
from trade_api.main import app

BASE = dict(client_id="c", client_secret="s", account_seq=7, base_url="https://toss.test",
            max_order_krw=Decimal("5000000"), max_daily_krw=Decimal("10000000"))
DRY = TradeConfig(dry_run=True, **BASE)
LIVE = TradeConfig(dry_run=False, **BASE)
# 건당 상한(max_order_krw)을 600만원 이상으로 둔 live 설정 — 일일 상한(1000만) 케이스 전용(건당 상한과 분리).
LIVE_HIGH_ORDER_CAP = TradeConfig(dry_run=False, client_id="c", client_secret="s", account_seq=7,
                                  base_url="https://toss.test", max_order_krw=Decimal("7000000"),
                                  max_daily_krw=Decimal("10000000"))
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


# ── Task 2(#187 리뷰): 통신 오류 마감·pending 포함 상한·토큰 1회 소비·advisory lock·UNIQUE ──

def test_transport_error_finishes_audit_row(db):
    def create(req):
        raise httpx.ReadTimeout("t")
    deps.set_test_overrides(cfg=LIVE, toss=toss_with({**READ_ROUTES, ("POST", "/api/v1/orders"): create}, LIVE), preview=PreviewStore())
    c = TestClient(app, raise_server_exceptions=False)
    p = preview(c)
    r = c.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": p["request"]})
    assert r.status_code == 500
    row = db.execute("SELECT http_status, error_code FROM toss_order_audit WHERE client_order_id=%s", (p["clientOrderId"],)).fetchone()
    assert row == (-1, "ReadTimeout")


def test_pending_row_blocks_next_buy(db):
    db.execute("INSERT INTO toss_order_audit (kind, symbol, side, order_amount_krw, request_json, dry_run) "
              "VALUES ('create','005930','BUY',9000000,'{}',false)")   # http_status 미지정 = pending(NULL)
    deps.set_test_overrides(cfg=LIVE_HIGH_ORDER_CAP, toss=toss_with(READ_ROUTES, LIVE_HIGH_ORDER_CAP), preview=PreviewStore())
    big = {"symbol": "005930", "side": "BUY", "orderType": "LIMIT", "quantity": "100", "price": "60000"}  # 600만원
    r = TestClient(app).post("/trade-api/orders/preview", json=big)     # 900만(pending, 포함) + 600만 > 1000만
    assert r.status_code == 400 and r.json()["error"]["code"] == "guard/max-daily-amount"


def test_same_token_cannot_submit_twice(db):
    def create(req):
        body = json.loads(req.content)
        return httpx.Response(200, json={"result": {"orderId": "ord_once", "clientOrderId": body["clientOrderId"]}})
    deps.set_test_overrides(cfg=LIVE, toss=toss_with({**READ_ROUTES, ("POST", "/api/v1/orders"): create}, LIVE), preview=PreviewStore())
    c = TestClient(app)
    p = preview(c)
    r1 = c.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": p["request"]})
    assert r1.status_code == 200, r1.text
    r2 = c.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": p["request"]})
    assert r2.status_code == 400 and r2.json()["error"]["code"] == "guard/preview-required"
    rows = db.execute("SELECT count(*) FROM toss_order_audit WHERE kind='create'").fetchone()
    assert rows == (1,)


def test_concurrent_submits_only_one_passes_cap(db, test_db_url):
    """동시 제출 2건(각 600만, 상한 1000만) — advisory lock 이 직렬화해 정확히 1건만 통과.

    autouse/모듈 db 오버라이드는 단일 연결을 스레드 간 공유해 psycopg 연결이 스레드
    안전이 아니므로(#187 리뷰 I-4), 이 테스트만 요청마다 새 연결을 여는 오버라이드로 교체한다.
    """
    def create(req):
        time.sleep(0.2)      # 두 요청이 실제로 겹치도록(lock 은 begin 구간에서만 짧게 점유)
        body = json.loads(req.content)
        return httpx.Response(200, json={"result": {"orderId": "ord_race", "clientOrderId": body["clientOrderId"]}})
    deps.set_test_overrides(cfg=LIVE_HIGH_ORDER_CAP, toss=toss_with({**READ_ROUTES, ("POST", "/api/v1/orders"): create}, LIVE_HIGH_ORDER_CAP), preview=PreviewStore())
    c = TestClient(app)
    big = {"symbol": "005930", "side": "BUY", "orderType": "LIMIT", "quantity": "100", "price": "60000"}  # 600만원
    p1 = preview(c, big)
    p2 = preview(c, big)

    def _fresh_conn_override():
        conn = psycopg.connect(test_db_url)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    app.dependency_overrides[deps.get_conn] = _fresh_conn_override

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def _submit(name, p):
        client = TestClient(app)
        barrier.wait()
        results[name] = client.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": p["request"]})

    t1 = threading.Thread(target=_submit, args=("a", p1))
    t2 = threading.Thread(target=_submit, args=("b", p2))
    t1.start(); t2.start()
    t1.join(); t2.join()

    statuses = sorted(r.status_code for r in results.values())
    assert statuses == [200, 400]
    rejected = next(r for r in results.values() if r.status_code == 400)
    assert rejected.json()["error"]["code"] == "guard/max-daily-amount"
    rows = db.execute("SELECT count(*) FROM toss_order_audit WHERE kind='create' AND http_status=200").fetchone()
    assert rows == (1,)


def test_duplicate_client_order_id_rejected_by_db(test_db_url):
    with psycopg.connect(test_db_url) as conn:
        conn.execute("DELETE FROM toss_order_audit")
        conn.commit()
        log = AuditLog(conn)
        try:
            log.begin("create", "005930", "BUY", "dup-1", Decimal("700000"), {}, dry_run=False)
            conn.commit()
            with pytest.raises(psycopg.errors.UniqueViolation):
                log.begin("create", "005930", "BUY", "dup-1", Decimal("700000"), {}, dry_run=False)
            conn.rollback()
        finally:
            # 실주문 행 정리(#187 최종 수정웨이브) — 공유 kr_test 에 live pending 행이 남지 않도록.
            conn.execute("DELETE FROM toss_order_audit WHERE client_order_id = 'dup-1'")
            conn.commit()


# ── Task 4(#187 리뷰): 매도 정정 미리보기는 sellable-quantity 를 조회하지 않는다(spec §6 표 정합) ──

def test_modify_preview_sell_does_not_call_sellable(db):
    order = {"orderId": "ord_s", "symbol": "005930", "side": "SELL", "orderType": "LIMIT", "timeInForce": "DAY",
             "status": "PENDING", "price": "70000", "quantity": "10", "orderAmount": None, "currency": "KRW",
             "orderedAt": "2026-09-14T09:00:00+09:00", "canceledAt": None,
             "execution": {"filledQuantity": "0", "averageFilledPrice": None, "filledAmount": None, "commission": None, "tax": None, "filledAt": None, "settlementDate": None}}
    routes = {("GET", "/api/v1/price-limits"): LIMITS, ("GET", "/api/v1/commissions"): COMM,
              ("GET", "/api/v1/orders/ord_s"): lambda r: httpx.Response(200, json={"result": order})}
    calls = []
    deps.set_test_overrides(cfg=LIVE, toss=toss_with(routes, LIVE, calls), preview=PreviewStore())
    c = TestClient(app)
    r = c.post("/trade-api/orders/modify/preview", json={"orderId": "ord_s", "orderType": "LIMIT", "quantity": "5", "price": "71000"})
    assert r.status_code == 200, r.text
    assert ("GET", "/api/v1/sellable-quantity") not in calls   # 조회됐다면 404 → TossApiError → 비-200


# ── Task 5(#187 리뷰 추가 정리): price_limits·commissions 일단위 캐시(리셋 훅) ──

def test_price_limits_cached_per_day(db):
    calls = []
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY, calls), preview=PreviewStore())
    c = TestClient(app)
    preview(c)
    preview(c)
    assert calls.count(("GET", "/api/v1/price-limits")) == 1


def test_commissions_cached(db):
    calls = []
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY, calls), preview=PreviewStore())
    c = TestClient(app)
    preview(c)
    preview(c)
    assert calls.count(("GET", "/api/v1/commissions")) == 1


def test_commission_failure_not_cached(db):
    attempts = {"n": 0}

    def commissions(req):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(500, json={"error": {"code": "server-error", "message": "boom"}})
        return COMM(req)

    routes = {**READ_ROUTES, ("GET", "/api/v1/commissions"): commissions}
    deps.set_test_overrides(cfg=DRY, toss=toss_with(routes, DRY), preview=PreviewStore())
    c = TestClient(app)
    p1 = preview(c)
    assert p1["estimate"]["commission"] is None   # 첫 호출 실패 — 캐시되지 않음
    p2 = preview(c)
    assert p2["estimate"]["commission"] is not None   # 두 번째는 재호출되어 성공
    assert attempts["n"] == 2


def test_cache_reset_on_override(db):
    calls = []
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY, calls), preview=PreviewStore())
    c = TestClient(app)
    preview(c)
    assert calls.count(("GET", "/api/v1/price-limits")) == 1
    deps.set_test_overrides(toss=toss_with(READ_ROUTES, DRY, calls))   # 클라이언트 교체 → 리셋 훅 발화
    preview(c)
    assert calls.count(("GET", "/api/v1/price-limits")) == 2


# ── #187 최종 수정웨이브: commit-before-send 무조건화(B)·KR 주문 quantity/price 정규화(F) ──

def test_begin_audit_commits_even_if_transaction_already_open(test_db_url):
    """B: 풀링된 non-autocommit 연결에 이미 열린 트랜잭션이 있으면(conn.transaction() 이 savepoint 로
    강등) _begin_audit 의 명시적 commit 이 없으면 pending 행이 다른 세션에 durable 하지 않다."""
    from trade_api.routers.orders import _begin_audit

    conn = psycopg.connect(test_db_url)          # 비-autocommit — 운영 풀 연결과 동형
    conn.execute("SELECT 1")                     # 트랜잭션을 미리 연다(savepoint 강등 조건)
    log = AuditLog(conn)
    audit_id = None
    try:
        audit_id = _begin_audit(conn, log, LIVE, kind="create", symbol="005930", side="BUY",
                                client_order_id=None, amount=Decimal("700000"), payload={}, lock_cap=False)
        with psycopg.connect(test_db_url, autocommit=True) as c2:   # 독립(제2) 세션
            row = c2.execute("SELECT http_status FROM toss_order_audit WHERE id=%s", (audit_id,)).fetchone()
        assert row == (None,)   # pending 행이 dispatch 전에 이미 제2 세션에서 보임 = commit 됨
    finally:
        if audit_id is not None:
            conn.execute("DELETE FROM toss_order_audit WHERE id=%s", (audit_id,))
            conn.commit()
        conn.close()


def test_list_and_detail_normalize_kr_order_quantities(db):
    """F: KR 주문의 quantity·price·filledQuantity 는 토스 decimal scale('10.0','70000.00') 을
    정수 문자열로 정규화해 내보낸다(list·detail 둘 다)."""
    order = {"orderId": "ord_n", "symbol": "005930", "side": "BUY", "orderType": "LIMIT", "timeInForce": "DAY",
             "status": "PENDING", "price": "70000.00", "quantity": "10.0", "orderAmount": None, "currency": "KRW",
             "orderedAt": "2026-09-14T09:00:00+09:00", "canceledAt": None,
             "execution": {"filledQuantity": "0.0", "averageFilledPrice": None, "filledAmount": None,
                           "commission": None, "tax": None, "filledAt": None, "settlementDate": None}}
    routes = {**READ_ROUTES,
              ("GET", "/api/v1/orders/ord_n"): lambda r: httpx.Response(200, json={"result": order}),
              ("GET", "/api/v1/orders"): lambda r: httpx.Response(200, json={"result": {"orders": [order], "nextCursor": None, "hasNext": False}})}
    deps.set_test_overrides(cfg=LIVE, toss=toss_with(routes, LIVE), preview=PreviewStore())
    c = TestClient(app)
    listed = c.get("/trade-api/orders?status=OPEN").json()["orders"][0]
    assert listed["quantity"] == "10" and listed["price"] == "70000" and listed["execution"]["filledQuantity"] == "0"
    detail = c.get("/trade-api/orders/ord_n").json()
    assert detail["quantity"] == "10" and detail["price"] == "70000" and detail["execution"]["filledQuantity"] == "0"
