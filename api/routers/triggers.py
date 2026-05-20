from datetime import date as _date
from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from api.deps import get_conn
from api.schemas.trigger import TriggerOut


router = APIRouter(prefix="/api/triggers", tags=["triggers"])


@router.get("", response_model=list[TriggerOut])
def list_triggers(
    ticker: str | None = None,
    date: _date | None = None,
    from_: _date | None = Query(default=None, alias="from"),
    to: _date | None = None,
    decision: str | None = None,
    trigger_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
    conn: Connection = Depends(get_conn),
):
    if limit > 1000:
        limit = 1000

    sql = """
        SELECT t.symbol, s.name, s.market,
               t.evaluated_at, t.trigger_type,
               t.close, t.volume, t.pivot_price,
               di.avg_volume_50d,
               t.decision, t.confidence, t.reasoning, t.abort_reason
          FROM trigger_evaluation_log t
          LEFT JOIN stocks s ON s.ticker = t.symbol
          LEFT JOIN daily_indicators di
                 ON di.ticker = t.symbol
                AND di.date = (t.evaluated_at AT TIME ZONE 'Asia/Seoul')::date
         WHERE (%(ticker)s::text   IS NULL OR t.symbol = %(ticker)s)
           AND (%(date)s::date     IS NULL OR (t.evaluated_at AT TIME ZONE 'Asia/Seoul')::date = %(date)s)
           AND (%(from_)s::date    IS NULL OR (t.evaluated_at AT TIME ZONE 'Asia/Seoul')::date >= %(from_)s)
           AND (%(to)s::date       IS NULL OR (t.evaluated_at AT TIME ZONE 'Asia/Seoul')::date <= %(to)s)
           AND (%(decision)s::text IS NULL OR t.decision = %(decision)s)
           AND (%(trigger_type)s::text IS NULL OR t.trigger_type = %(trigger_type)s)
         ORDER BY t.evaluated_at DESC
         LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {
        "ticker": ticker,
        "date": date,
        "from_": from_,
        "to": to,
        "decision": decision,
        "trigger_type": trigger_type,
        "limit": limit,
        "offset": offset,
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    result: list[TriggerOut] = []
    for r in rows:
        close = float(r[5]) if r[5] is not None else None
        volume = int(r[6]) if r[6] is not None else None
        pivot = float(r[7]) if r[7] is not None else None
        avg_vol = float(r[8]) if r[8] is not None else None

        vol_ratio = (volume / avg_vol) if (volume is not None and avg_vol and avg_vol > 0) else None
        pivot_delta = ((close - pivot) / pivot * 100.0) if (close is not None and pivot is not None and pivot > 0) else None

        result.append(TriggerOut(
            symbol=r[0],
            name=r[1],
            market=r[2],
            evaluated_at=r[3],
            trigger_type=r[4],
            close=close,
            volume=volume,
            pivot_price=pivot,
            avg_volume_50d_ratio=vol_ratio,
            pivot_delta_pct=pivot_delta,
            decision=r[9],
            confidence=float(r[10]) if r[10] is not None else None,
            reasoning=r[11],
            abort_reason=r[12],
        ))
    return result
