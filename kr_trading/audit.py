# kr_trading/audit.py
"""주문 감사로그 (spec §5). 전송 직전 begin() → 응답 후 finish(). 커밋은 호출자."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from psycopg import Connection
from psycopg.types.json import Jsonb

KST = timezone(timedelta(hours=9))
TRANSPORT_ERROR_STATUS = -1   # http_status: 응답 미수신 채로 통신 예외로 마감(타임아웃 등) — 1일 상한 집계는 접수된 것으로 간주


def kst_today() -> date:
    return datetime.now(KST).date()


class AuditLog:
    def __init__(self, conn: Connection):
        self._conn = conn

    def begin(self, kind: str, symbol: str, side: str | None, client_order_id: str | None,
              order_amount_krw: Decimal | None, request_json: dict, dry_run: bool) -> int:
        row = self._conn.execute(
            """
            INSERT INTO toss_order_audit
              (kind, symbol, side, client_order_id, order_amount_krw, request_json, dry_run)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (kind, symbol, side, client_order_id, order_amount_krw, Jsonb(request_json), dry_run),
        ).fetchone()
        return int(row[0])

    def finish(self, audit_id: int, *, http_status: int, error_code: str | None = None,
               request_id: str | None = None, order_id: str | None = None,
               response_json: dict | None = None) -> None:
        self._conn.execute(
            """
            UPDATE toss_order_audit
               SET http_status=%s, error_code=%s, request_id=%s, order_id=%s,
                   response_json=%s, responded_at=now()
             WHERE id=%s
            """,
            (http_status, error_code, request_id, order_id,
             Jsonb(response_json) if response_json is not None else None, audit_id),
        )

    def daily_buy_total_krw(self, today_kst: date) -> Decimal:
        """fail-closed: 응답 미수신(pending, NULL)·통신 오류 마감(-1)·5xx 도 접수됐을 수 있으므로 포함한다.
        4xx/422(토스가 거부 확정) 만 제외 — 리뷰 근거: 타임아웃·5xx 는 토스가 실제로 받았을 수 있다."""
        row = self._conn.execute(
            """
            -- 5xx 는 응답을 받긴 했지만 거부가 확정된 게 아니다(예: 접수 후 게이트웨이 502) —
            -- 4xx/422(거부 확정) 만 제외하고 5xx 는 pending/-1 과 동일하게 fail-closed 로 포함한다.
            SELECT COALESCE(SUM(order_amount_krw), 0)
              FROM toss_order_audit
             WHERE kind = 'create' AND NOT dry_run AND side = 'BUY'
               AND (http_status IS NULL OR http_status IN (200, %s) OR http_status >= 500)
               AND (created_at AT TIME ZONE 'Asia/Seoul')::date = %s
            """,
            (TRANSPORT_ERROR_STATUS, today_kst),
        ).fetchone()
        return Decimal(row[0])
