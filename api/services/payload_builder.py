"""payload.json 통합 빌더."""
from datetime import date, timedelta
from psycopg import Connection

from api.services.market_context_builder import build_market_context
from api.services.corporate_actions_builder import build_corporate_actions
from api.services.minervini_detail_builder import build_minervini_detail
from kr_pipeline.common.thresholds import (
    MARKET_DIST_DEMOTION_COUNT_25S,
    MARKET_DIST_NORMAL_MAX_25S,
    TT_MARGIN_MARGINAL_PCT,
    TT_MARGINAL_DEMOTION_COUNT,
)


def _conditions_summary(conditions_detail: dict) -> dict:
    """(#23) A §2 marginal 카운트 선계산 — 프롬프트는 이 값을 재계수 없이 소비.

    marginal = 'PASS 하면서 margin < TT_MARGIN_MARGINAL_PCT%' 인 조건 (A §2 정의).
    미확정(null): passed 가 None(지표 미산출)이거나, PASS 인데 margin 이 None
    (마진 미산출 — 예: sma_200 이력 23행 미만의 c3)인 조건이 하나라도 있으면
    카운트 전체를 미확정으로 — 확정 숫자로 내보내면 재계수 금지 규약이 LLM 의
    결측 감지 능력을 제거한다(#38 리뷰). null 이면 프롬프트 예외 조항에 따라
    LLM 이 conditions_detail 을 직접 검토(기존 경로 보존).
    """
    for c in conditions_detail.values():
        if c.get("passed") is None or (
            c.get("passed") is True and c.get("margin_pct") is None
        ):
            return {
                "marginal_count": None,
                "marginal_conditions": None,
                "demotion_trigger": None,
            }
    marginal = sorted(
        k
        for k, c in conditions_detail.items()
        if c.get("passed") is True
        and c.get("margin_pct") is not None
        and c["margin_pct"] < TT_MARGIN_MARGINAL_PCT
    )
    return {
        "marginal_count": len(marginal),
        "marginal_conditions": marginal,
        "demotion_trigger": len(marginal) >= TT_MARGINAL_DEMOTION_COUNT,
    }


_KNOWN_MARKET_STATUSES = frozenset(
    {"confirmed_uptrend", "rally_attempt", "downtrend", "correction"}
)


def _market_direction_gate(market_context: dict) -> dict:
    """(#23) A §3.5 시장 하드룰의 판정 입력 선계산 (규칙 텍스트는 프롬프트 유지).

    §3.5 하드룰 4개를 그대로 인코딩:
    - force_watch: downtrend/correction (무조건) 또는 rally_attempt **인데 FTD 부재**
      — 프롬프트 둘째 룰의 'without a follow-through day' 한정어 보존(#38 리뷰:
      rally_attempt + FTD 존재 조합은 강등 비대상 — 무조건 강등 시 동작 변화).
    - confidence_penalty: 시장 분배일 >= MARKET_DIST_DEMOTION_COUNT_25S
    - normal_range: confirmed_uptrend 이고 분배일 <= MARKET_DIST_NORMAL_MAX_25S
    - confirmed_uptrend 인데 분배일 4 인 구간은 프롬프트가 원래 미규정 — 갭 보존.
    입력 None 또는 미지의 status 값 → 해당 boolean null (미지 상태를 통과로
    단정하지 않음 — 프롬프트 null 규약이 entry 금지로 보수 처리).
    """
    status = market_context.get("current_status")
    dist = market_context.get("distribution_day_count_last_25_sessions")
    last_ftd = market_context.get("last_follow_through_day")

    if status is None or status not in _KNOWN_MARKET_STATUSES:
        force_watch = None
        normal_range = None
    else:
        force_watch = status in ("downtrend", "correction") or (
            status == "rally_attempt" and last_ftd is None
        )
        normal_range = (
            status == "confirmed_uptrend" and dist <= MARKET_DIST_NORMAL_MAX_25S
            if dist is not None
            else None
        )
    confidence_penalty = (
        dist >= MARKET_DIST_DEMOTION_COUNT_25S if dist is not None else None
    )
    return {
        "status": status,
        "dist_count": dist,
        "last_follow_through_day": last_ftd,
        "force_watch": force_watch,
        "confidence_penalty": confidence_penalty,
        "normal_range": normal_range,
    }


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
        # (#23) §2/§3.5 정량 판정 입력 선계산 — 프롬프트 재계수 금지 규약의 대상
        "conditions_summary": _conditions_summary(minervini),
        "market_direction_gate": _market_direction_gate(market_context),
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
            -- volume 은 i.volume(=adj_volume, modes.py:231) — daily_ohlcv·avg_volume_50d·
            -- volume_ratio 가 전부 adj 라, 여기서 p.volume(raw) 을 쓰면 같은 날 두 도메인 혼입.
            SELECT p.date, p.adj_close, i.volume,
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
            "volume": int(round(float(r[2]))) if r[2] is not None else None,  # adj(i.volume), halt=NULL
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
