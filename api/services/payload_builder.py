"""payload.json 통합 빌더."""
from datetime import date, timedelta
from psycopg import Connection

from api.services.market_context_builder import build_market_context
from api.services.corporate_actions_builder import build_corporate_actions
from api.services.minervini_detail_builder import build_minervini_detail
from kr_pipeline.llm_runner.compute.climax_topping import (
    compute_climax_gates,
    compute_topping_gates,
    find_anchor,
)
from kr_pipeline.common.thresholds import (
    MARKET_DIST_DEMOTION_COUNT_25S,
    MARKET_DIST_NORMAL_MAX_25S,
    STATUS_FTD_RECENT_DAYS,
    TT_MARGINAL_DEMOTION_COUNT,
)
from kr_pipeline.llm_runner.compute.tt_marginal import tt_marginal_summary


def _conditions_summary(conditions_detail: dict) -> dict:
    """(#23) A §2 marginal 카운트 선계산 — 프롬프트는 이 값을 재계수 없이 소비.

    marginal = 'PASS 하면서 margin < TT_MARGIN_MARGINAL_PCT%' 인 조건 (A §2 정의).
    미확정(null): passed 가 None(지표 미산출)이거나, PASS 인데 margin 이 None
    (마진 미산출 — 예: sma_200 이력 23행 미만의 c3)인 조건이 하나라도 있으면
    카운트 전체를 미확정으로 — 확정 숫자로 내보내면 재계수 금지 규약이 LLM 의
    결측 감지 능력을 제거한다(#38 리뷰). null 이면 프롬프트 예외 조항에 따라
    LLM 이 conditions_detail 을 직접 검토(기존 경로 보존).
    """
    s = tt_marginal_summary(conditions_detail)  # 계수·결측 규약의 단일 정의(A·B 공용)
    if s["marginal_count"] is None:
        return {
            "marginal_count": None,
            "marginal_conditions": None,
            "demotion_trigger": None,
        }
    return {
        "marginal_count": s["marginal_count"],
        "marginal_conditions": s["marginal_conditions"],
        "demotion_trigger": s["marginal_count"] >= TT_MARGINAL_DEMOTION_COUNT,
    }


_KNOWN_MARKET_STATUSES = frozenset(
    {"confirmed_uptrend", "rally_attempt", "downtrend", "correction"}
)


def _market_direction_gate(market_context: dict) -> dict:
    """(#23) A §3.5 시장 하드룰의 판정 입력 선계산 (규칙 텍스트는 프롬프트 유지).

    §3.5 하드룰 4개를 그대로 인코딩:
    - force_watch: downtrend/correction (무조건) 또는 rally_attempt **인데 최근 FTD 부재**
      — 프롬프트 둘째 룰의 'without a follow-through day' 한정어 보존. '최근' 판정은
      status.py 와 동일하게 경과일 ≤ STATUS_FTD_RECENT_DAYS (#38 재리뷰: FTD 만료 때문에
      rally_attempt 로 내려온 경로에서는 만료 FTD 기록이 항상 잔존 — 기록 존재만 보면
      §3.5 하드룰이 상시 우회된다. 경과일 미산출도 최근 확인 불가 = 보수 강등).
    - confidence_penalty: 시장 분배일 >= MARKET_DIST_DEMOTION_COUNT_25S
    - normal_range: confirmed_uptrend 이고 분배일 <= MARKET_DIST_NORMAL_MAX_25S.
      status 가 confirmed_uptrend 가 아니면 넷째 룰 전제 자체가 거짓 — 분배일 결측이어도
      null 이 아니라 False 확정 (#38 재리뷰: null 승격은 확정 정보의 손실이며 부분 결손을
      조문에 없는 전면 entry 금지로 증폭).
    - confirmed_uptrend 인데 분배일 4 인 구간은 프롬프트가 원래 미규정 — 갭 보존.
    입력 None 또는 미지의 status 값 → 해당 boolean null (미지 상태를 통과로
    단정하지 않음 — 프롬프트 null 규약이 entry 금지로 보수 처리).
    """
    status = market_context.get("current_status")
    dist = market_context.get("distribution_day_count_last_25_sessions")
    last_ftd = market_context.get("last_follow_through_day")
    ftd_age = market_context.get("days_since_follow_through")

    if status is None or status not in _KNOWN_MARKET_STATUSES:
        force_watch = None
        normal_range = None
    else:
        ftd_recent = (
            last_ftd is not None
            and ftd_age is not None
            and ftd_age <= STATUS_FTD_RECENT_DAYS
        )
        force_watch = status in ("downtrend", "correction") or (
            status == "rally_attempt" and not ftd_recent
        )
        if status != "confirmed_uptrend":
            normal_range = False  # 전제(confirmed_uptrend) 거짓 — dist 무관 확정
        elif dist is not None:
            normal_range = dist <= MARKET_DIST_NORMAL_MAX_25S
        else:
            normal_range = None
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


def _dist_count_25s(indicators_60d: list) -> int | None:
    """(#44 Task 5) T-D 분배일 카운트 입력 — indicators_recent_60d 의 마지막 25행 기준.

    null=보수(brief 규약): 25행 미만이거나, 마지막 25행 중 하나라도
    distribution_day_flag 가 None(미산출)이면 부분 결측을 조용히 과소계수하지
    않고 전체를 None 으로 반환한다.
    """
    if len(indicators_60d) < 25:
        return None
    last_25 = indicators_60d[-25:]
    flags = [row.get("distribution_day_flag") for row in last_25]
    if any(f is None for f in flags):
        return None
    return sum(1 for f in flags if f is True)


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

    # (#44 Task 5) climax/topping 게이트 통합 — anchor 전 이력 탐색 + §6.1/§6.2 산술
    weekly_full = _fetch_weekly_full(conn, ticker, on_date)
    anchor = find_anchor(weekly_full)
    climax_topping_gates = {
        **compute_climax_gates(weekly_full, daily_ohlcv[-20:], anchor),
        **compute_topping_gates(weekly_full, _dist_count_25s(indicators_60d), anchor),
        "anchor_week": anchor["anchor_week"],
        "left_censored": anchor["left_censored"],
        "no_transition": anchor["no_transition"],
    }
    # supporting_ext_sma200_pct: Task 3 는 daily 입력에 sma200 부재로 None 고정 —
    # Task 5 에서 indicators_60d(마지막 행의 sma_200·adj_close) 로 공급하기로 확정
    # (Task 3 report 의 concern 해소). 둘 중 하나라도 미산출이면 None 유지(보수).
    last_ind = indicators_60d[-1] if indicators_60d else None
    if last_ind is not None and last_ind["sma_200"] is not None and last_ind["adj_close"] is not None:
        climax_topping_gates["supporting_ext_sma200_pct"] = (
            last_ind["adj_close"] / last_ind["sma_200"] - 1
        ) * 100
    else:
        climax_topping_gates["supporting_ext_sma200_pct"] = None

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
        "climax_topping_gates": climax_topping_gates,
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


def _fetch_weekly_full(conn: Connection, ticker: str, on_date: date) -> list:
    """(#44 Task 5) climax/topping anchor 탐색용 — 주봉 전 이력, LIMIT 없음, 오름차순.

    _fetch_weekly_ohlcv(:216) 와 동일 소스·adj 정합 규약이나: LIMIT 없이 전 이력을
    가져오고(anchor 는 임의 시점 이전 이력을 뒤로 거슬러 탐색해야 하므로 104주로
    자를 수 없음), zero-bar(거래정지/무거래주) 제외 규약을 daily(:199)와 동일하게
    추가한다(주봉은 daily 와 달리 이 규약이 없었음 — climax/topping SMA 산술에
    0-바가 섞이면 오염).
    """
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
               -- 거래정지/무거래주(OHLV·volume 0) 제외: daily(:199)와 동일 규약
               AND NOT (open = 0 AND high = 0 AND low = 0 AND volume = 0)
             ORDER BY week_end_date ASC
        """, (ticker, on_date))
        rows = cur.fetchall()
    return [
        {
            "week_end": r[0].isoformat(),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": int(round(float(r[5]))) if r[5] is not None else None,
        }
        for r in rows
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
