from fastapi import APIRouter, Depends
from psycopg import Connection

from api.deps import get_conn
from api.schemas.signal import PerformanceStats


router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get("/stats")
def get_stats(period: str = "2w", conn: Connection = Depends(get_conn)):
    col = f"return_{period}_pct"
    market_col = f"market_return_{period}_pct"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS n,
                   AVG({col})::FLOAT AS avg_return,
                   AVG({market_col})::FLOAT AS avg_market,
                   AVG(CASE WHEN {col} > 0 THEN 1.0 ELSE 0.0 END)::FLOAT AS win_rate
              FROM signal_performance
             WHERE {col} IS NOT NULL
            """
        )
        row = cur.fetchone()
    n, avg_r, avg_m, win = row
    return {
        "period": period,
        "signal_count": int(n),
        "avg_return_pct": avg_r,
        "avg_market_return_pct": avg_m,
        "outperform_pct": (avg_r - avg_m) if (avg_r is not None and avg_m is not None) else None,
        "win_rate": win,
    }


@router.get("/signals")
def list_perf_signals(
    limit: int = 50,
    ticker: str | None = None,
    conn: Connection = Depends(get_conn),
):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sp.symbol, s.name, sp.signal_at, sp.entry_price,
                   sp.return_1w_pct, sp.return_2w_pct, sp.return_4w_pct, sp.return_8w_pct,
                   sp.market_return_1w_pct, sp.market_return_2w_pct,
                   sp.market_return_4w_pct, sp.market_return_8w_pct
              FROM signal_performance sp
              JOIN stocks s ON s.ticker = sp.symbol
             WHERE (%s::text IS NULL OR sp.symbol = %s)
             ORDER BY sp.signal_at DESC LIMIT %s
            """,
            (ticker, ticker, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "symbol": r[0], "name": r[1], "signal_at": r[2].isoformat(),
            "entry_price": float(r[3]),
            "return_1w_pct": float(r[4]) if r[4] is not None else None,
            "return_2w_pct": float(r[5]) if r[5] is not None else None,
            "return_4w_pct": float(r[6]) if r[6] is not None else None,
            "return_8w_pct": float(r[7]) if r[7] is not None else None,
            "market_return_1w_pct": float(r[8]) if r[8] is not None else None,
            "market_return_2w_pct": float(r[9]) if r[9] is not None else None,
            "market_return_4w_pct": float(r[10]) if r[10] is not None else None,
            "market_return_8w_pct": float(r[11]) if r[11] is not None else None,
        }
        for r in rows
    ]
