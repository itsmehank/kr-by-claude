"""payload.json 통합 빌더."""
from datetime import date, timedelta
from psycopg import Connection

from api.services.market_context_builder import build_market_context
from api.services.corporate_actions_builder import build_corporate_actions
from api.services.minervini_detail_builder import build_minervini_detail


def build_payload(conn: Connection, ticker: str, on_date: date | None = None) -> dict:
    """payload.json 의 전체 딕셔너리 생성."""
    if on_date is None:
        on_date = date.today()

    with conn.cursor() as cur:
        cur.execute("SELECT name, market, sector FROM stocks WHERE ticker = %s", (ticker,))
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"Stock not found: {ticker}")
    name, market, sector = row

    # 미너비니 detail
    minervini = build_minervini_detail(conn, ticker, on_date)
    conditions_met = {k: v["passed"] for k, v in minervini.items()}

    # rs_rating: c8의 values 에 있거나, 없으면 None
    rs_rating = next(
        (v["values"].get("rs_rating") for v in minervini.values() if "rs_rating" in v.get("values", {})),
        None,
    )

    current = _build_current_metrics(conn, ticker, on_date)
    daily_ohlcv = _fetch_daily_ohlcv(conn, ticker, on_date, days=60)
    weekly_ohlcv = _fetch_weekly_ohlcv(conn, ticker, on_date, weeks=104)
    indicators_60d = _fetch_indicators_recent(conn, ticker, on_date, days=60)

    market_context = build_market_context(conn, market, on_date)
    price_data_notes = build_corporate_actions(conn, ticker, lookback_years=5, as_of_date=on_date)

    return {
        "symbol": ticker,
        "name": name,
        "market": market,
        "sector": sector,
        "date": on_date.isoformat(),
        "conditions_met": conditions_met,
        "conditions_detail": minervini,
        "rs_rating": rs_rating,
        "current_metrics": current,
        "daily_ohlcv_recent_60d": daily_ohlcv,
        "weekly_ohlcv_recent_104w": weekly_ohlcv,
        "indicators_recent_60d": indicators_60d,
        "market_context": market_context,
        "price_data_notes": price_data_notes,
    }


def _build_current_metrics(conn: Connection, ticker: str, on_date: date) -> dict:
    """가격·거래량은 daily_prices 권위 소스, 52w·volume_ratio 는 daily_indicators."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.adj_close, i.w52_high, i.w52_low,
                   i.pct_from_52w_high, i.pct_from_52w_low,
                   i.avg_volume_50d, i.volume_ratio_50d
              FROM daily_prices p
              LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = %s AND p.date <= %s
             ORDER BY p.date DESC
             LIMIT 1
        """, (ticker, on_date))
        row = cur.fetchone()
    if row is None:
        return {
            "close": None,
            "w52_high": None,
            "w52_low": None,
            "pct_above_w52_low": None,
            "pct_below_w52_high": None,
            "volume_ma_50": None,
            "volume_ratio": None,
        }
    adj_close, wh, wl, pct_hi, pct_lo, av, vr = row
    return {
        "close": float(adj_close) if adj_close is not None else None,
        "w52_high": float(wh) if wh is not None else None,
        "w52_low": float(wl) if wl is not None else None,
        "pct_above_w52_low": float(pct_lo) if pct_lo is not None else None,
        "pct_below_w52_high": float(pct_hi) if pct_hi is not None else None,
        "volume_ma_50": float(av) if av is not None else None,
        "volume_ratio": float(vr) if vr is not None else None,
    }


def _fetch_daily_ohlcv(conn: Connection, ticker: str, on_date: date, days: int = 60) -> list:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT date,
                   COALESCE(adj_open,  open)   AS o,
                   COALESCE(adj_high,  high)   AS h,
                   COALESCE(adj_low,   low)    AS l,
                   COALESCE(adj_close, close)  AS c,
                   COALESCE(adj_volume,volume) AS v
              FROM daily_prices
             WHERE ticker = %s AND date <= %s
               -- 거래정지/무거래일(OHLV·volume 0) 제외: 0-저가/0-거래량 바 LLM 노출 방지
               AND NOT (open = 0 AND high = 0 AND low = 0 AND volume = 0)
             ORDER BY date DESC LIMIT %s
        """, (ticker, on_date, days))
        rows = cur.fetchall()
    return [
        {
            "date": r[0].isoformat(),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": int(round(float(r[5]))),
        }
        for r in reversed(rows)
    ]


def _fetch_weekly_ohlcv(conn: Connection, ticker: str, on_date: date, weeks: int = 104) -> list:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT week_end_date,
                   COALESCE(adj_open,  open)   AS o,
                   COALESCE(adj_high,  high)   AS h,
                   COALESCE(adj_low,   low)    AS l,
                   COALESCE(adj_close, close)  AS c,
                   COALESCE(adj_volume,volume) AS v
              FROM weekly_prices
             WHERE ticker = %s AND week_end_date <= %s
             ORDER BY week_end_date DESC LIMIT %s
        """, (ticker, on_date, weeks))
        rows = cur.fetchall()
    return [
        {
            "week_start": (r[0] - timedelta(days=4)).isoformat(),
            "week_end": r[0].isoformat(),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": int(round(float(r[5]))) if r[5] is not None else None,
        }
        for r in reversed(rows)
    ]


def _fetch_indicators_recent(conn: Connection, ticker: str, on_date: date, days: int = 60) -> list:
    """daily_prices(가격·거래량) + daily_indicators(지표) JOIN → 최근 N일 series."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT p.date, p.adj_close, p.volume,
                   i.sma_10, i.sma_21, i.sma_50, i.sma_150, i.sma_200,
                   i.w52_high, i.w52_low, i.rs_line, i.rs_rating, i.minervini_pass,
                   i.avg_volume_50d, i.volume_ratio_50d, i.pocket_pivot_flag, i.distribution_day_flag,
                   i.rs_line_at_52w_high, i.rs_line_uptrend_6w, i.rs_line_uptrend_13w
              FROM daily_prices p
              LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = %s AND p.date <= %s
             ORDER BY p.date DESC LIMIT %s
        """, (ticker, on_date, days))
        rows = cur.fetchall()
    return [
        {
            "date": r[0].isoformat(),
            "adj_close": float(r[1]) if r[1] is not None else None,
            "volume": int(r[2]) if r[2] is not None else None,
            "sma_10": float(r[3]) if r[3] is not None else None,
            "sma_21": float(r[4]) if r[4] is not None else None,
            "sma_50": float(r[5]) if r[5] is not None else None,
            "sma_150": float(r[6]) if r[6] is not None else None,
            "sma_200": float(r[7]) if r[7] is not None else None,
            "w52_high": float(r[8]) if r[8] is not None else None,
            "w52_low": float(r[9]) if r[9] is not None else None,
            "rs_line": float(r[10]) if r[10] is not None else None,
            "rs_rating": int(r[11]) if r[11] is not None else None,
            "minervini_pass": bool(r[12]) if r[12] is not None else None,
            "volume_ma_50": float(r[13]) if r[13] is not None else None,
            "volume_ratio": float(r[14]) if r[14] is not None else None,
            "pocket_pivot_flag": bool(r[15]) if r[15] is not None else None,
            "distribution_day_flag": bool(r[16]) if r[16] is not None else None,
            "rs_line_at_52w_high": bool(r[17]) if r[17] is not None else None,
            "rs_line_uptrend_6w": bool(r[18]) if r[18] is not None else None,
            "rs_line_uptrend_13w": bool(r[19]) if r[19] is not None else None,
        }
        for r in reversed(rows)
    ]
