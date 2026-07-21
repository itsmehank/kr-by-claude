"""(#47) 보유 포지션 + 일일 손절 평가 조회 API (read-only)."""
from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from api.deps import get_conn

router = APIRouter(prefix="/api/positions", tags=["positions"])


def _f(v):
    return float(v) if v is not None else None


@router.get("")
def list_positions(
    status: str = "open",
    conn: Connection = Depends(get_conn),
):
    """포지션 목록 + 각자의 최신 손절 평가 1건 (LATERAL)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.id, p.symbol, s.name, p.entry_date, p.entry_price, p.quantity,
                   p.breakeven_armed, p.status, p.closed_at, p.close_reason, p.note,
                   e.eval_date, e.close, e.sma_50, e.effective_stop, e.binding,
                   e.triggered, e.warnings
              FROM positions p
              LEFT JOIN stocks s ON s.ticker = p.symbol
              LEFT JOIN LATERAL (
                SELECT eval_date, close, sma_50, effective_stop, binding,
                       triggered, warnings
                  FROM position_stop_evaluations
                 WHERE position_id = p.id
                 ORDER BY eval_date DESC
                 LIMIT 1
              ) e ON true
             WHERE (%s = 'all' OR p.status = %s)
             ORDER BY p.status DESC, p.entry_date DESC, p.id DESC
            """,
            (status, status),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0], "symbol": r[1], "name": r[2], "entry_date": r[3],
            "entry_price": _f(r[4]), "quantity": r[5],
            "breakeven_armed": bool(r[6]), "status": r[7],
            "closed_at": r[8], "close_reason": r[9], "note": r[10],
            "last_eval": None if r[11] is None else {
                "eval_date": r[11], "close": _f(r[12]), "sma_50": _f(r[13]),
                "effective_stop": _f(r[14]), "binding": r[15],
                "triggered": bool(r[16]), "warnings": r[17] or [],
            },
        }
        for r in rows
    ]


@router.get("/{position_id}/evaluations")
def list_evaluations(
    position_id: int,
    limit: int = Query(60, ge=1, le=500),
    conn: Connection = Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT eval_date, close, sma_50, effective_stop, binding,
                   breakeven_armed, triggered, warnings
              FROM position_stop_evaluations
             WHERE position_id = %s
             ORDER BY eval_date DESC
             LIMIT %s
            """,
            (position_id, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "eval_date": r[0], "close": _f(r[1]), "sma_50": _f(r[2]),
            "effective_stop": _f(r[3]), "binding": r[4],
            "breakeven_armed": bool(r[5]), "triggered": bool(r[6]),
            "warnings": r[7] or [],
        }
        for r in rows
    ]
