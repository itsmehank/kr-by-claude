"""(#47) positions 수동 기록 store — open/close/조회.

포지션 소스 결정(2026-07-22): 수동 기록. 어댑터 구조 — 브로커 연동 도입 시
이 모듈 뒤에 소스 어댑터를 붙이고 source 컬럼으로 구분(러너·스키마는 불변).
"""
from __future__ import annotations

from datetime import date

from psycopg import Connection


def open_position(
    conn: Connection,
    *,
    symbol: str,
    entry_date: date,
    entry_price: float,
    quantity: int | None = None,
    note: str | None = None,
    source: str = "manual",
) -> int:
    """포지션 개설 — 새 id 반환. entry_price 는 평균매입가(체결 사실, 이후 불변)."""
    if entry_price is None or not (entry_price > 0):
        raise ValueError(f"entry_price must be positive: {entry_price}")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO positions (symbol, entry_date, entry_price, quantity, note, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (symbol, entry_date, entry_price, quantity, note, source),
        )
        return cur.fetchone()[0]


def close_position(conn: Connection, *, position_id: int, reason: str | None = None,
                   closed_at: date | None = None) -> None:
    """포지션 종료 — 이후 일일 평가 대상에서 제외. 평가 이력은 보존."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE positions
               SET status = 'closed', closed_at = COALESCE(%s, CURRENT_DATE),
                   close_reason = %s
             WHERE id = %s AND status = 'open'
            """,
            (closed_at, reason, position_id),
        )
        if cur.rowcount != 1:
            raise ValueError(f"open position not found: id={position_id}")


def get_open_positions(conn: Connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, symbol, entry_date, entry_price, quantity, breakeven_armed, note
              FROM positions
             WHERE status = 'open'
             ORDER BY entry_date, id
            """
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0], "symbol": r[1], "entry_date": r[2],
            "entry_price": float(r[3]), "quantity": r[4],
            "breakeven_armed": bool(r[5]), "note": r[6],
        }
        for r in rows
    ]
