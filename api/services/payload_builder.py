"""payload.json 통합 빌더."""
from datetime import date, timedelta
from psycopg import Connection

from api.services.market_context_builder import build_market_context
from api.services.corporate_actions_builder import build_corporate_actions
from api.services.minervini_detail_builder import build_minervini_detail
from kr_pipeline.llm_runner.compute.climax_topping import (
    compute_climax_gates,
    compute_daily_extremes,
    compute_topping_gates,
    find_anchor,
)
from kr_pipeline.common.thresholds import (
    MARKET_DIST_DEMOTION_COUNT_25S,
    MARKET_DIST_NORMAL_MAX_25S,
    STATUS_FTD_RECENT_DAYS,
    TT_MARGINAL_DEMOTION_COUNT,
)
from kr_pipeline.llm_runner.compute.recent_transition import (
    WINDOW_ROWS,
    recent_transition_count_63d,
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
    """(#44 Task 5) T-D 분배일 카운트 입력 — 지표 시계열(_fetch_indicators_recent,
    #99 부터 payload 미출력·내부 계산 전용)의 마지막 25행 기준.

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
    # (#99) weekly_ohlcv/indicators_60d 는 더 이상 payload 로 출력하지 않는다 —
    # 주봉 OHLCV 는 weekly_ohlcv.csv(build_weekly_ohlcv_csv), 지표 시계열은
    # daily.csv(17지표) 가 유일 표현. indicators_60d 는 아래 게이트 산술
    # (climax/topping, dist count, supporting_ext_sma200_pct) 의 입력으로만 유지.
    indicators_60d = _fetch_indicators_recent(conn, ticker, on_date, days=60)

    market_context = build_market_context(conn, market, on_date)
    price_data_notes = build_corporate_actions(conn, ticker, lookback_years=5, as_of_date=on_date)

    # (#44 Task 5) climax/topping 게이트 통합 — anchor 전 이력 탐색 + §6.1/§6.2 산술
    weekly_full = _fetch_weekly_full(conn, ticker, on_date)
    anchor = find_anchor(weekly_full)
    climax = compute_climax_gates(weekly_full, daily_ohlcv[-20:], anchor)
    topping = compute_topping_gates(weekly_full, _dist_count_25s(indicators_60d), anchor)
    # (항목 ① 2026-09-07) 일간 극값 신호 T5·T6·TA-d — anchor 이후 전 일봉 별도 경로.
    # 기존 T3/T4 입력(daily_ohlcv[-20:], 60일 조회)은 불변. left_censored 는 조회 생략.
    # Q-5 quality_flag → None / Q-8 no_transition → None(시작점 부재 = 미정의; #169 부터 주간
    # anchor 의존 신호도 동일 규약) → 두 결측 모드·left_censored 는 조회 자체를 생략한다.
    if anchor["left_censored"] or anchor["no_transition"] or climax["quality_flag"]:
        daily_ext = compute_daily_extremes(None, None, anchor, quality_flag=climax["quality_flag"])
    else:
        bl_start = _anchor_baseline_start(anchor["anchor_week"])
        daily_ext = compute_daily_extremes(
            _fetch_daily_since(conn, ticker, bl_start, on_date), bl_start.isoformat(), anchor)
    climax_topping_gates = {
        **climax,
        **topping,
        **daily_ext,
        "anchor_week": anchor["anchor_week"],
        "left_censored": anchor["left_censored"],
        "no_transition": anchor["no_transition"],
    }
    # (#44 Task 5 리뷰) climax/topping 각자 quality_flag 키를 내는데 위 병합 순서상
    # topping 이 climax 값을 조용히 덮어씀(climax 의 None 계약이 topping 의 항상-계산
    # bool 로 사라짐) — controller 가 두 값을 명시적으로 분리해 노출하고 충돌 키는 제거.
    climax_topping_gates.pop("quality_flag", None)
    climax_topping_gates["quality_flag_climax"] = climax["quality_flag"]
    climax_topping_gates["quality_flag_topping"] = topping["quality_flag"]
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
        # + (rtc_63d) 자문 입력 — demotion_trigger 인근 배치(맵 §1-2), None 허용
        "conditions_summary": {
            **_conditions_summary(minervini),
            "recent_transition_count_63d": recent_transition_count_63d(
                _fetch_minervini_pass_series(conn, ticker, on_date)
            ),
        },
        "market_direction_gate": _market_direction_gate(market_context),
        "rs_rating": rs_rating,
        "current_metrics": current,
        "daily_ohlcv_recent_60d": daily_ohlcv,
        "market_context": market_context,
        "price_data_notes": price_data_notes,
        "climax_topping_gates": climax_topping_gates,
    }


def _fetch_minervini_pass_series(conn: Connection, ticker: str, on_date: date) -> list[bool | None]:
    """기준일 이하 최근 64행(창 63 + 창 시작 행 판정용 직전 1행)의 minervini_pass.

    시간 오름차순 반환 — recent_transition_count_63d 입력 규약(마지막 행 = 기준일,
    look-ahead 금지는 date <= on_date 로 보장). 거래일 = daily_indicators 행 존재일.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT minervini_pass
              FROM daily_indicators
             WHERE ticker = %s AND date <= %s
             ORDER BY date DESC
             LIMIT %s
        """, (ticker, on_date, WINDOW_ROWS + 1))
        rows = cur.fetchall()
    return [r[0] for r in reversed(rows)]


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


# 일봉 조회 공통 조각 — _fetch_daily_ohlcv(T3/T4·LLM 노출 60행)와 _fetch_daily_since(항목 ①
# T5/T6/TA-d baseline)가 같은 바 집합·같은 adj 규약을 보도록 한 곳에 둔다(사본 분기 방지).
_DAILY_OHLCV_COLS = """date,
                   COALESCE(adj_open,  open)   AS o,
                   COALESCE(adj_high,  high)   AS h,
                   COALESCE(adj_low,   low)    AS l,
                   COALESCE(adj_close, close)  AS c,
                   COALESCE(adj_volume,volume) AS v"""
# 거래정지/무거래일(OHLV·volume 0) 제외: 0-저가/0-거래량 바 LLM 노출·산술 오염 방지
_DAILY_NOT_ZERO_BAR = "NOT (open = 0 AND high = 0 AND low = 0 AND volume = 0)"


def _daily_row(r) -> dict:
    return {
        "date": r[0].isoformat(),
        "open": float(r[1]),
        "high": float(r[2]),
        "low": float(r[3]),
        "close": float(r[4]),
        "volume": int(round(float(r[5]))),
    }


def _fetch_daily_ohlcv(conn: Connection, ticker: str, on_date: date, days: int = 60) -> list:
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT {_DAILY_OHLCV_COLS}
              FROM daily_prices
             WHERE ticker = %s AND date <= %s
               AND {_DAILY_NOT_ZERO_BAR}
             ORDER BY date DESC LIMIT %s
        """, (ticker, on_date, days))
        rows = cur.fetchall()
    return [_daily_row(r) for r in reversed(rows)]


def _anchor_baseline_start(anchor_week: str) -> date:
    """(항목 ① Q-1 판정 B) anchor 주의 첫 거래일 탐색 시작점 = 그 ISO 주(월~일, weekly
    transform 의 W-SUN 그룹과 동일)의 월요일. week_end_date 는 그 주 max(date) 이므로
    weekday() 만큼 되돌리면 월요일. 실제 첫 거래일은 _fetch_daily_since 가 이 날짜 이상의
    첫 비-zero-bar 행으로 결정한다(월요일 휴장이면 자연히 화요일).
    ※ 같은 ISO-월요일 식이 kr_pipeline/weekly/store.py·llm_runner/modes.py 에도 있음 —
    공용 helper 승격은 별건(리뷰 지적, 범위 밖). _fetch_weekly_ohlcv 의 week_start
    (week_end−4일) 는 표기용 근사로 이 함수와 무관."""
    we = date.fromisoformat(anchor_week)
    return we - timedelta(days=we.weekday())


def _fetch_daily_since(conn: Connection, ticker: str, start: date, on_date: date) -> list:
    """(항목 ①) start 이후(포함) ~ on_date 의 일봉 전부 + start 직전 1행(baseline 첫날의
    prev_close 공급용 — zero-bar 여부 무관 최신 1행). 컬럼·adj 규약은 _fetch_daily_ohlcv 와
    동일 조각을 공유하되 두 가지가 다르다(compute_daily_extremes 규약):
    - zero-bar(거래정지) 행을 **제외하지 않고** `zero_bar=True` 로 표시해 넘긴다 — Q-6 판정
      (연속 세션만: prev↔today 사이 zero-bar 존재 시 쌍 제외, 재개일 today → None).
    - `adj_hl` = adj_high·adj_low 둘 다 존재(high·low 가 adj 소스) — Q-7 판정(T6 공식
      유효성: high·low·prev_close 가 같은 조정 기준일 때만 산출; prev_close=adj_close 는
      NOT NULL 이라 항상 adj)."""
    cols = f"""{_DAILY_OHLCV_COLS},
                   (open = 0 AND high = 0 AND low = 0 AND volume = 0) AS zero_bar,
                   (adj_high IS NOT NULL AND adj_low IS NOT NULL)     AS adj_hl"""
    with conn.cursor() as cur:
        cur.execute(f"""
            (SELECT {cols}
               FROM daily_prices
              WHERE ticker = %s AND date < %s
              ORDER BY date DESC LIMIT 1)
            UNION ALL
            (SELECT {cols}
               FROM daily_prices
              WHERE ticker = %s AND date >= %s AND date <= %s
              ORDER BY date ASC)
            ORDER BY date ASC
        """, (ticker, start, ticker, start, on_date))
        rows = cur.fetchall()
    return [{**_daily_row(r), "zero_bar": bool(r[6]), "adj_hl": bool(r[7])} for r in rows]


def _fetch_weekly_ohlcv(conn: Connection, ticker: str, on_date: date, weeks: int = 104) -> list:
    """주봉 OHLCV 104주 (COALESCE(adj_*, raw)). #99 부터 payload 미출력 —
    csv_builder.build_weekly_ohlcv_csv 가 이 함수를 소비해 CSV 로 직렬화한다."""
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

    _fetch_weekly_ohlcv 와 동일 소스·adj 정합 규약이나: LIMIT 없이 전 이력을 가져오고(anchor 는
    임의 시점 이전 이력을 뒤로 거슬러 탐색해야 하므로 104주로 자를 수 없음), zero-bar(거래정지/
    무거래주) 는 **반환 목록에서 제외**한다(climax/topping SMA 산술 오염 방지 — 기존 규약).
    (#156) 대신 각 행에 두 플래그를 싣는다:
    - `gap_before` = 이 주와 직전 반환 행 사이에 zero-bar 주가 있었음(T1 비율의 prev_close 불연속).
    - `adj_hl` = adj_high·adj_low 둘 다 존재(high·low 가 adj 소스; T1 (high−low)/adj_close 유효성).
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT week_end_date,
                   COALESCE(adj_open,  open)   AS o,
                   COALESCE(adj_high,  high)   AS h,
                   COALESCE(adj_low,   low)    AS l,
                   COALESCE(adj_close, close)  AS c,
                   COALESCE(adj_volume,volume) AS v,
                   (open = 0 AND high = 0 AND low = 0 AND volume = 0) AS zero_bar,
                   (adj_high IS NOT NULL AND adj_low IS NOT NULL)     AS adj_hl
              FROM weekly_prices
             WHERE ticker = %s AND week_end_date <= %s
             ORDER BY week_end_date ASC
        """, (ticker, on_date))
        rows = cur.fetchall()
    out = []
    gap = False
    for r in rows:
        if r[6]:
            gap = True
            continue
        out.append({
            "week_end": r[0].isoformat(),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": int(round(float(r[5]))) if r[5] is not None else None,
            "gap_before": gap,
            "adj_hl": bool(r[7]),
        })
        gap = False
    return out
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
