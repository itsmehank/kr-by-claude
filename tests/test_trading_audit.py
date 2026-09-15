# tests/test_trading_audit.py
"""AuditLog — 전송 전 INSERT(pending) → finish UPDATE, 1일 BUY 누적(KST·dry_run·kind 필터)."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest

from kr_trading.audit import TRANSPORT_ERROR_STATUS, AuditLog, kst_today

KST = timezone(timedelta(hours=9))


@pytest.fixture
def conn(test_db_url):
    with psycopg.connect(test_db_url) as c:
        c.execute("DELETE FROM toss_order_audit")
        yield c
        c.rollback()


def test_begin_leaves_pending_row_even_if_send_never_finishes(conn):
    log = AuditLog(conn)
    aid = log.begin("create", "005930", "BUY", "c1", Decimal("700000"),
                    {"symbol": "005930", "price": "70000", "quantity": "10"}, dry_run=False)
    conn.commit()
    row = conn.execute("SELECT http_status, order_id, request_json->>'price' FROM toss_order_audit WHERE id=%s", (aid,)).fetchone()
    assert row == (None, None, "70000")   # pending 행 존재


def test_finish_updates_row(conn):
    log = AuditLog(conn)
    aid = log.begin("create", "005930", "BUY", "c1", Decimal("700000"), {"x": 1}, dry_run=False)
    log.finish(aid, http_status=200, request_id="req-1", order_id="ord_1", response_json={"orderId": "ord_1"})
    conn.commit()
    row = conn.execute("SELECT http_status, request_id, order_id, responded_at IS NOT NULL FROM toss_order_audit WHERE id=%s", (aid,)).fetchone()
    assert row == (200, "req-1", "ord_1", True)


def test_daily_buy_total_filters(conn):
    log = AuditLog(conn)
    today = kst_today()
    def add(kind, side, amt, dry, status, created=None):
        aid = log.begin(kind, "005930", side, None, Decimal(amt), {}, dry_run=dry)
        if status is not None:
            log.finish(aid, http_status=status)
        if created is not None:
            conn.execute("UPDATE toss_order_audit SET created_at=%s WHERE id=%s", (created, aid))
    add("create", "BUY", "1000000", False, 200)          # 포함
    add("create", "BUY", "2000000", False, 200)          # 포함
    add("create", "BUY", "5000000", True, 200)           # dry_run 제외
    add("create", "SELL", "5000000", False, 200)         # SELL 제외
    add("modify", "BUY", "5000000", False, 200)          # 정정 제외(이중 집계 방지)
    add("create", "BUY", "5000000", False, 422)          # 거부(422) 제외 — 토스가 거부 확정
    add("create", "BUY", "5000000", False, None)         # pending(NULL) 포함 — fail-closed(#187 리뷰)
    yesterday_2330 = datetime.combine(today - timedelta(days=1), datetime.min.time(), KST) + timedelta(hours=23, minutes=30)
    add("create", "BUY", "5000000", False, 200, created=yesterday_2330)   # 전날 23:30 KST 제외
    conn.commit()
    assert log.daily_buy_total_krw(today) == Decimal("8000000")


def test_daily_total_counts_pending_and_transport_error_rows(conn):
    """pending(NULL)·통신오류(-1)·5xx 는 접수됐을 수 있으므로 포함(fail-closed) — 422(거부 확정)·dry_run·
    SELL(side 필터) 은 제외."""
    log = AuditLog(conn)

    def add(status, amt, dry=False, side="BUY"):
        aid = log.begin("create", "005930", side, None, Decimal(amt), {}, dry_run=dry)
        if status is not None:
            log.finish(aid, http_status=status)

    add(None, "1000000")                          # pending 포함
    add(TRANSPORT_ERROR_STATUS, "2000000")        # 통신 오류로 마감 — 포함
    add(200, "3000000")                           # 정상 완료 — 포함
    add(502, "4000000")                           # 5xx(거부 확정 아님) — 포함
    add(422, "5000000")                           # 거부 확정 — 제외
    add(200, "9000000", dry=True)                 # dry_run — 제외
    add(503, "8000000", side="SELL")              # SELL — side 필터로 제외
    conn.commit()
    assert log.daily_buy_total_krw(kst_today()) == Decimal("10000000")


def test_kst_today_is_date():
    assert isinstance(kst_today(), date)
