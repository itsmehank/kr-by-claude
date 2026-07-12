"""(5b), (6) 용 경량 텍스트 payload 생성.

(5) 는 무거운 ZIP 13 파일 첨부. (5b), (6) 는 가벼운 JSON payload 만.
"""
from datetime import date, datetime, timedelta
from psycopg import Connection

from api.services.market_context_builder import build_market_context
from api.services.minervini_detail_builder import build_minervini_detail


_PRIOR_KEYS = (
    "classified_at", "classification", "pattern", "pivot_price", "pivot_basis",
    "base_high", "base_low", "base_depth_pct", "risk_flags", "reasoning",
    "watch_reason",
)


def build_for_5b(
    conn: Connection,
    symbol: str,
    trigger_type: str,
    as_of: date | None = None,
    prior_row: dict | None = None,
) -> dict:
    """(5b) evaluate_pivot_trigger payload.

    prior_row: 직전 분석을 직접 주입(키 = _PRIOR_KEYS). 백테스트 감사용 —
        기본 조회는 weekly_classification 최신 1건(as_of 상한 없음)이라 과거
        as_of 재생 시 미래 분류가 새어든다(look-ahead). production(오늘 실행)은
        미주입 = 기존 동작 그대로.
    """
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

        if prior_row is not None:
            prior = tuple(prior_row[k] for k in _PRIOR_KEYS)
        else:
            cur.execute(
                """
                SELECT classified_at, classification, pattern, pivot_price, pivot_basis,
                       base_high, base_low, base_depth_pct, risk_flags, reasoning,
                       watch_reason
                  FROM weekly_classification
                 WHERE symbol = %s
                   AND classification IN ('entry', 'watch')
                 ORDER BY COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC LIMIT 1
                """,
                (symbol,),
            )
            prior = cur.fetchone()
            if prior is None:
                raise ValueError(f"No active classification for {symbol}")

        cur.execute(
            """
            SELECT p.date,
                   COALESCE(p.adj_open, p.open),
                   COALESCE(p.adj_high, p.high),
                   COALESCE(p.adj_low, p.low),
                   COALESCE(p.adj_close, p.close),
                   COALESCE(p.adj_volume, p.volume),
                   i.distribution_day_flag
              FROM daily_prices p
              -- (#31) 종목 분배일 flag — B 게이트 판정의 authoritative 입력
              -- (LLM 자체 재계산 금지). 0-바 제외가 선행이라 halt 행 flag 미노출.
              LEFT JOIN daily_indicators i
                ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = %s AND p.date <= %s
               -- 거래정지/무거래일 제외 (0-바 LLM 노출 방지)
               AND NOT (p.open = 0 AND p.high = 0 AND p.low = 0 AND p.volume = 0)
             ORDER BY p.date DESC LIMIT 20
            """,
            (symbol, as_of),
        )
        ohlcv_rows = list(reversed(cur.fetchall()))

        # current_metrics 는 무배제 최신(halt 직후엔 20d 리스트 말미와 날짜가 다를 수
        # 있음 — as-of 의미가 달라 20d 쿼리와 통합 금지, #35 리뷰).
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
               AND evaluated_at <  %s::date + INTERVAL '1 day'
             ORDER BY evaluated_at DESC LIMIT 7
            """,
            (symbol, as_of, as_of),
        )
        history = cur.fetchall()

    # breakout_from_watch §3.5 의 unfavorable_market / marginal_tt 분기 입력 —
    # **현재(as_of) 값** (분류시점 스냅샷 금지, finding-C 동일선상). additive: 기존 5b
    # 소비자(프롬프트)는 무시해도 무방. echo(신규 임계 아님): market_context_daily 적재값 +
    # minervini.py 당일 결정론 산출.
    market_context = build_market_context(conn, market, as_of)
    minervini = build_minervini_detail(conn, symbol, as_of)
    conditions_met = {k: v["passed"] for k, v in minervini.items()}
    rs_rating = next(
        (v["values"].get("rs_rating") for v in minervini.values()
         if "rs_rating" in v.get("values", {})),
        None,
    )

    return {
        "symbol": symbol,
        "name": name,
        "market": market,
        "evaluation_date": as_of.isoformat(),
        "trigger_type": trigger_type,
        "market_context": market_context,
        "conditions_met": conditions_met,
        "conditions_detail": minervini,
        "rs_rating": rs_rating,
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
            "watch_reason": prior[10],
        },
        "recent_daily_ohlcv_20d": [
            {
                "date": r[0].isoformat(),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": int(round(float(r[5]))),
                "distribution_day_flag": bool(r[6]) if r[6] is not None else None,
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
                   base_high, base_low, base_depth_pct, risk_flags, confidence, reasoning
              FROM weekly_classification
             WHERE symbol = %s
               AND classification IN ('entry', 'watch')
             ORDER BY COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC LIMIT 1
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
                   COALESCE(p.adj_high, p.high),
                   COALESCE(p.adj_low, p.low),
                   COALESCE(p.adj_open, p.open),
                   i.rs_rating, i.minervini_pass, i.w52_high, i.w52_low,
                   i.pct_from_52w_high
              FROM daily_indicators i
              LEFT JOIN daily_prices p
                ON p.ticker = i.ticker AND p.date = i.date
             WHERE i.ticker = %s
               AND i.date <= %s
             ORDER BY i.date DESC LIMIT 1
            """,
            (symbol, evaluation_at.date()),
        )
        state = cur.fetchone()

        # (#18) §0.5/§1.2 pocket pivot 감지 + §2.3 stop 입력 — 최근 10 거래일 지표.
        # look-ahead 상한은 current_state 와 동일하게 evaluation 날짜.
        # sma_50·low: §2.3 pocket pivot stop 계산 입력 (#26 리뷰 — bare-name 유령 해소).
        # volume IS NOT NULL: 거래정지일 배제 (#26 리뷰) — halt 행은 volume NULL +
        # 동결가 carry 라 창을 잠식·오도 (5b 의 0-바 배제와 동일 규약; daily_indicators
        # 에는 raw 0-바 컬럼이 없어 volume NULL 이 halt 마커).
        cur.execute(
            """
            SELECT i.date, i.adj_close, i.volume, i.avg_volume_50d, i.pocket_pivot_flag,
                   i.sma_50, COALESCE(p.adj_low, p.low)
              FROM daily_indicators i
              LEFT JOIN daily_prices p
                ON p.ticker = i.ticker AND p.date = i.date
             WHERE i.ticker = %s AND i.date <= %s
               AND i.volume IS NOT NULL
             ORDER BY i.date DESC LIMIT 10
            """,
            (symbol, evaluation_at.date()),
        )
        recent_rows = list(reversed(cur.fetchall()))

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
            "confidence": float(prior[9]) if prior[9] is not None else None,
            "reasoning": prior[10],
        },
        "recent_daily_indicators": [
            {
                "date": r[0].isoformat(),
                "close": float(r[1]) if r[1] is not None else None,
                "volume": int(r[2]) if r[2] is not None else None,
                "avg_volume_50d": float(r[3]) if r[3] is not None else None,
                "pocket_pivot_flag": bool(r[4]) if r[4] is not None else None,
                "sma_50": float(r[5]) if r[5] is not None else None,
                "low": float(r[6]) if r[6] is not None else None,
            }
            for r in recent_rows
        ],
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
