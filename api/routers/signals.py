from datetime import date, timedelta
from fastapi import APIRouter, Depends
from psycopg import Connection

from api.deps import get_conn
from api.schemas.signal import SignalOut


router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("", response_model=list[SignalOut])
def list_signals(
    days: int = 5,
    ticker: str | None = None,
    conn: Connection = Depends(get_conn),
):
    cutoff = date.today() - timedelta(days=days)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ep.symbol, s.name, s.sector, s.market,
                   ep.signal_at, ep.entry_mode, ep.trigger_price, ep.entry_price,
                   ep.stop_loss, ep.stop_loss_pct_from_pivot, ep.stop_loss_pct_from_current_price,
                   ep.expected_target_price, ep.expected_target_pct, ep.risk_reward_ratio,
                   ep.position_size_pct, ep.known_warnings, ep.notes
              FROM entry_params ep
              JOIN stocks s ON s.ticker = ep.symbol
             WHERE ep.signal_at::date >= %s
               AND (%s::text IS NULL OR ep.symbol = %s)
             ORDER BY ep.signal_at DESC
            """,
            (cutoff, ticker, ticker),
        )
        rows = cur.fetchall()
    return [
        SignalOut(
            symbol=r[0], name=r[1], sector=r[2], market=r[3],
            signal_at=r[4], entry_mode=r[5],
            # `if r[n] else None` 은 Decimal('0') 을 None 으로 오변환 — is not None 통일.
            # entry_price/stop_loss 는 NULLABLE — 무조건 float() 시 NULL 행 하나로 전체 500.
            trigger_price=float(r[6]) if r[6] is not None else None,
            entry_price=float(r[7]) if r[7] is not None else None,
            stop_loss=float(r[8]) if r[8] is not None else None,
            stop_loss_pct_from_pivot=float(r[9]) if r[9] is not None else None,
            stop_loss_pct_from_current_price=float(r[10]) if r[10] is not None else None,
            expected_target_price=float(r[11]) if r[11] is not None else None,
            expected_target_pct=float(r[12]) if r[12] is not None else None,
            risk_reward_ratio=float(r[13]) if r[13] is not None else None,
            position_size_pct=float(r[14]) if r[14] is not None else None,
            known_warnings=r[15] if r[15] else [],
            notes=r[16],
        )
        for r in rows
    ]
