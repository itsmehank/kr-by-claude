"""(5b), (6) 용 경량 텍스트 payload 생성.

(5) 는 무거운 ZIP 13 파일 첨부. (5b), (6) 는 가벼운 JSON payload 만.
"""
from datetime import date, datetime, timedelta
from psycopg import Connection


def build_for_5b(
    conn: Connection,
    symbol: str,
    trigger_type: str,
    as_of: date | None = None,
) -> dict:
    """(5b) evaluate_pivot_trigger payload."""
    if as_of is None:
        as_of = date.today()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, market FROM stocks WHERE ticker = %s", (symbol,)
        )
        meta = cur.fetchone()
        if meta is None:
            raise ValueError(f"Stock not found: {symbol}")
        name, market = meta

        cur.execute(
            """
            SELECT classified_at, classification, pattern, pivot_price, pivot_basis,
                   base_high, base_low, base_depth_pct, risk_flags, reasoning
              FROM weekly_classification
             WHERE symbol = %s
               AND classification IN ('entry', 'watch')
             ORDER BY classified_at DESC LIMIT 1
            """,
            (symbol,),
        )
        prior = cur.fetchone()
        if prior is None:
            raise ValueError(f"No active classification for {symbol}")

        cur.execute(
            """
            SELECT date, open, high, low, close, volume
              FROM daily_prices
             WHERE ticker = %s AND date <= %s
             ORDER BY date DESC LIMIT 20
            """,
            (symbol, as_of),
        )
        ohlcv_rows = list(reversed(cur.fetchall()))

        cur.execute(
            """
            SELECT adj_close, volume, avg_volume_50d, sma_50, sma_21
              FROM daily_indicators
             WHERE ticker = %s AND date <= %s
             ORDER BY date DESC LIMIT 1
            """,
            (symbol, as_of),
        )
        cur_row = cur.fetchone()

        cur.execute(
            """
            SELECT evaluated_at, decision, reasoning, abort_reason
              FROM trigger_evaluation_log
             WHERE symbol = %s
               AND evaluated_at >= %s::date - INTERVAL '7 days'
             ORDER BY evaluated_at DESC LIMIT 7
            """,
            (symbol, as_of),
        )
        history = cur.fetchall()

    return {
        "symbol": symbol,
        "name": name,
        "market": market,
        "evaluation_date": as_of.isoformat(),
        "trigger_type": trigger_type,
        "prior_analysis": {
            "classified_at": prior[0].isoformat(),
            "days_since_classification": (as_of - prior[0].date()).days,
            "classification": prior[1],
            "pattern": prior[2],
            "pivot_price": float(prior[3]) if prior[3] else None,
            "pivot_basis": prior[4],
            "base_high": float(prior[5]) if prior[5] else None,
            "base_low": float(prior[6]) if prior[6] else None,
            "base_depth_pct": float(prior[7]) if prior[7] else None,
            "risk_flags": prior[8],
            "reasoning": prior[9],
        },
        "recent_daily_ohlcv_20d": [
            {
                "date": r[0].isoformat(),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": int(r[5]),
            }
            for r in ohlcv_rows
        ],
        "current_metrics": (
            {
                "close": float(cur_row[0]) if cur_row else None,
                "volume": int(cur_row[1]) if cur_row and cur_row[1] else None,
                "avg_volume_50d": (
                    float(cur_row[2]) if cur_row and cur_row[2] else None
                ),
                "volume_ratio": (
                    float(cur_row[1]) / float(cur_row[2])
                    if cur_row and cur_row[1] and cur_row[2] and cur_row[2] > 0
                    else None
                ),
                "sma_50": float(cur_row[3]) if cur_row and cur_row[3] else None,
                "sma_21": float(cur_row[4]) if cur_row and cur_row[4] else None,
            }
            if cur_row
            else {}
        ),
        "recent_evaluation_history": [
            {
                "evaluated_at": h[0].isoformat(),
                "decision": h[1],
                "reasoning": h[2],
                "abort_reason": h[3],
            }
            for h in history
        ],
    }


def build_for_6(
    conn: Connection,
    symbol: str,
    evaluation_at: datetime,
) -> dict:
    """(6) calculate_entry_params payload."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, market, sector FROM stocks WHERE ticker = %s", (symbol,)
        )
        meta = cur.fetchone()
        if meta is None:
            raise ValueError(f"Stock not found: {symbol}")
        name, market, sector = meta

        cur.execute(
            """
            SELECT classified_at, classification, pattern, pivot_price, pivot_basis,
                   base_high, base_low, base_depth_pct, risk_flags
              FROM weekly_classification
             WHERE symbol = %s
               AND classification IN ('entry', 'watch')
             ORDER BY classified_at DESC LIMIT 1
            """,
            (symbol,),
        )
        prior = cur.fetchone()
        if prior is None:
            raise ValueError(f"No active classification for {symbol}")

        cur.execute(
            """
            SELECT evaluated_at, decision, confidence, reasoning, trigger_type
              FROM trigger_evaluation_log
             WHERE symbol = %s AND evaluated_at = %s
            """,
            (symbol, evaluation_at),
        )
        trig = cur.fetchone()
        if trig is None:
            raise ValueError(
                f"No trigger evaluation at {evaluation_at} for {symbol}"
            )

        cur.execute(
            """
            SELECT i.adj_close, i.volume, i.avg_volume_50d,
                   p.high, p.low, p.open,
                   i.rs_rating, i.minervini_pass, i.w52_high, i.w52_low,
                   i.pct_from_52w_high
              FROM daily_indicators i
              LEFT JOIN daily_prices p
                ON p.ticker = i.ticker AND p.date = i.date
             WHERE i.ticker = %s
             ORDER BY i.date DESC LIMIT 1
            """,
            (symbol,),
        )
        state = cur.fetchone()

    return {
        "symbol": symbol,
        "name": name,
        "market": market,
        "sector": sector,
        "signal_date": evaluation_at.date().isoformat(),
        "prior_analysis": {
            "classified_at": prior[0].isoformat(),
            "classification": prior[1],
            "pattern": prior[2],
            "pivot_price": float(prior[3]) if prior[3] else None,
            "pivot_basis": prior[4],
            "base_high": float(prior[5]) if prior[5] else None,
            "base_low": float(prior[6]) if prior[6] else None,
            "base_depth_pct": float(prior[7]) if prior[7] else None,
            "risk_flags": prior[8],
        },
        "trigger_evaluation": {
            "evaluated_at": trig[0].isoformat(),
            "decision": trig[1],
            "confidence": float(trig[2]) if trig[2] else None,
            "reasoning": trig[3],
            "trigger_type": trig[4],
        },
        "current_state": (
            {
                "close": float(state[0]) if state[0] else None,
                "volume": int(state[1]) if state[1] else None,
                "avg_volume_50d": float(state[2]) if state[2] else None,
                "intraday_high": float(state[3]) if state[3] else None,
                "intraday_low": float(state[4]) if state[4] else None,
                "intraday_open": float(state[5]) if state[5] else None,
            }
            if state
            else {}
        ),
        "current_metrics_extended": (
            {
                "rs_rating": int(state[6]) if state and state[6] else None,
                "minervini_pass": bool(state[7]) if state else False,
                "w52_high": float(state[8]) if state and state[8] else None,
                "w52_low": float(state[9]) if state and state[9] else None,
                "pct_from_52w_high": float(state[10]) if state and state[10] else None,
            }
            if state
            else {}
        ),
    }
