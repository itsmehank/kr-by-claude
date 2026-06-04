# kr_pipeline/indicators/modes.py
"""indicators 파이프라인 모드 분기 + 오케스트레이션."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
import logging

import numpy as np
import pandas as pd
from psycopg import Connection

from kr_pipeline.db.runs import run_tracking
from kr_pipeline.indicators.compute.sma import sma
from kr_pipeline.indicators.compute.high_low import w52_high_low, pct_from_high_low
from kr_pipeline.indicators.compute.rs_line import (
    compute_rs_line, compute_rs_line_52w_high_and_date,
    compute_rs_line_at_52w_high, compute_rs_line_uptrend_slope,
    compute_rs_line_not_declining,
)
from kr_pipeline.common.thresholds import (
    RS_LINE_UPTREND_SHORT_WEEKS, RS_LINE_UPTREND_LONG_WEEKS, RS_LINE_DECLINE_GATE_WEEKS,
)
from kr_pipeline.indicators.compute.rs_rating import compute_ibd_strength_factor, assign_rs_rating_percentiles
from kr_pipeline.indicators.compute.minervini import compute_minervini_c1_to_c7
from kr_pipeline.indicators.compute.volume import (
    avg_volume, volume_ratio,
    pocket_pivot, volume_dry_up, up_down_volume_ratio, distribution_day,
)
from kr_pipeline.indicators.load import (
    load_daily_prices, load_index_daily, load_weekly_prices, load_weekly_index,
    load_active_tickers_with_market,
    get_daily_prices_min_date, get_weekly_prices_min_date,
)
from kr_pipeline.indicators.store import (
    upsert_daily_indicators_phase_a, update_daily_indicators_rs_rating,
    update_daily_indicators_minervini_pass,
    upsert_weekly_indicators_phase_a, update_weekly_indicators_rs_rating,
    update_weekly_indicators_minervini_pass,
    update_daily_rs_gate_from_weekly,
)


log = logging.getLogger("kr_pipeline.indicators")

# 캘린더 일 — 252 거래일 + 휴일 여유 (한국 거래일 ≈ 245/365, 안전 마진 포함).
# timedelta(days=) 가 캘린더 일 단위이므로 거래일이 아니라 캘린더 일로 환산해야
# sma_200 / rs_rating 등 200~252 거래일 lookback 지표가 NULL 없이 채워짐.
LOOKBACK_DAYS = 400       # 252 거래일 ≈ 375 캘린더 일 + 25일 안전 마진
LOOKBACK_WEEKS = 60       # 52 주 + 8 주 안전 마진 (휴일 분포)


class Mode(str, Enum):
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"
    FULL_REFRESH = "full-refresh"


class Target(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass
class RunStats:
    rows_affected: int
    failures: list[tuple[str, str]]
    warnings: list[str] = field(default_factory=list)


# 임시 module-level cache for Phase B input (Phase A 가 채워둠)
_phase_b_cache: dict[str, dict[date, float | None]] = {}


def _get_db_min_date(conn: Connection, target: Target) -> date:
    if target == Target.DAILY:
        d = get_daily_prices_min_date(conn)
    else:
        d = get_weekly_prices_min_date(conn)
    return d if d else date.today()


def compute_date_range(
    target: Target,
    mode: Mode,
    *,
    window: int = 30,
    conn: Connection | None = None,
) -> tuple[date, date, date]:
    """(load_start, load_end, upsert_start) 반환.

    load 는 lookback 포함, upsert 는 window 부분만.
    """
    today = date.today()

    if mode == Mode.INCREMENTAL:
        if target == Target.DAILY:
            load_start = today - timedelta(days=window + LOOKBACK_DAYS)
            upsert_start = today - timedelta(days=window)
        else:
            load_start = today - timedelta(days=(window + LOOKBACK_WEEKS) * 7)
            upsert_start = today - timedelta(days=window * 7)
        return load_start, today, upsert_start

    if mode in (Mode.BACKFILL, Mode.FULL_REFRESH):
        load_start = _get_db_min_date(conn, target)
        return load_start, today, load_start

    raise ValueError(f"Unknown mode: {mode}")


KOSPI_INDEX_CODE = "1001"  # RS Line 광역 단일 분모 (설계 D2: 코스피·코스닥 전 종목 공통)


def _as_float(v) -> float | None:
    if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
        return None
    return float(v)


def _as_bool(v) -> bool | None:
    if v is None or pd.isna(v):
        return None
    return bool(v)


def _process_ticker_daily(
    conn: Connection,
    ticker: str,
    market: str,
    load_start: date,
    load_end: date,
    upsert_start: date,
) -> int:
    """한 종목의 일봉 지표 Phase A 처리."""
    df_daily = load_daily_prices(conn, ticker, load_start, load_end)
    if df_daily.empty:
        return 0

    index_code = KOSPI_INDEX_CODE  # D2: 종목 시장 무관 KOSPI 단일 분모
    df_idx = load_index_daily(conn, index_code, load_start, load_end)
    if df_idx.empty:
        return 0

    # join on date
    df = df_daily.merge(df_idx.rename(columns={"close": "index_close"}), on="date", how="left")
    df = df.set_index("date").sort_index()

    adj_close = df["adj_close"]

    # V3: daily_prices.adj_volume 직접 읽기 (split-adjusted volume 재계산 제거)
    adj_volume = df["adj_volume"]
    avg_vol_50 = avg_volume(adj_volume, window=50)
    vol_ratio_50 = volume_ratio(adj_volume, avg_vol_50)

    is_up = adj_close > adj_close.shift(1)
    is_down = adj_close < adj_close.shift(1)

    # SMAs
    sma_10 = sma(adj_close, 10)
    sma_21 = sma(adj_close, 21)
    sma_50 = sma(adj_close, 50)
    sma_150 = sma(adj_close, 150)
    sma_200 = sma(adj_close, 200)

    # V2 거래량 파생 지표 (sma_50 필요하므로 SMAs 다음)
    pp_flag = pocket_pivot(is_up, adj_volume, sma_50, adj_close, lookback=10)
    vdu_flag = volume_dry_up(adj_volume, avg_vol_50, threshold=0.5)
    ud_ratio_50 = up_down_volume_ratio(adj_volume, is_up, is_down, window=50)
    dist_flag = distribution_day(is_down, adj_volume, avg_vol_50, threshold=1.25)

    # 52w
    w52h, w52l = w52_high_low(df["adj_high"], df["adj_low"], window=252)
    pct_h, pct_l = pct_from_high_low(adj_close, w52h, w52l)

    # RS Line
    rs_line = compute_rs_line(adj_close, df["index_close"])
    rs_line_high, rs_line_high_date = compute_rs_line_52w_high_and_date(rs_line, window=252)
    rs_at_high = compute_rs_line_at_52w_high(rs_line, rs_line_high)
    rs_up_6w = compute_rs_line_uptrend_slope(rs_line, window=RS_LINE_UPTREND_SHORT_WEEKS * 5)   # 6주≈30영업일
    rs_up_13w = compute_rs_line_uptrend_slope(rs_line, window=RS_LINE_UPTREND_LONG_WEEKS * 5)   # 13주≈65영업일

    # SF (rs_rating 입력) — IBD 가중, 최근 분기 2배
    one_y_ret = compute_ibd_strength_factor(adj_close, 63, 126, 189, 252)

    # Minervini c1-c7
    mn_df = pd.DataFrame({
        "adj_close": adj_close,
        "sma_50": sma_50, "sma_150": sma_150, "sma_200": sma_200,
        "w52_high": w52h, "w52_low": w52l,
    }, index=df.index)
    mn = compute_minervini_c1_to_c7(mn_df, sma_200_lookback=22)

    # Build row dicts, filter to upsert_start..load_end
    rows = []
    one_y_returns_for_phase_b = {}  # date -> 1y_return
    for d in df.index:
        if d < upsert_start:
            continue
        row = {
            "ticker": ticker,
            "date": d,
            "adj_close": float(adj_close.loc[d]),
            "sma_10": _as_float(sma_10.loc[d]),
            "sma_21": _as_float(sma_21.loc[d]),
            "sma_50": _as_float(sma_50.loc[d]),
            "sma_150": _as_float(sma_150.loc[d]),
            "sma_200": _as_float(sma_200.loc[d]),
            "w52_high": _as_float(w52h.loc[d]),
            "w52_low": _as_float(w52l.loc[d]),
            "pct_from_52w_high": _as_float(pct_h.loc[d]),
            "pct_from_52w_low": _as_float(pct_l.loc[d]),
            "rs_line": _as_float(rs_line.loc[d]),
            "rs_line_52w_high": _as_float(rs_line_high.loc[d]),
            "rs_line_52w_high_date": rs_line_high_date.loc[d] if pd.notna(rs_line_high_date.loc[d]) else None,
            "rs_line_at_52w_high": _as_bool(rs_at_high.loc[d]),
            "rs_line_uptrend_6w": _as_bool(rs_up_6w.loc[d]),
            "rs_line_uptrend_13w": _as_bool(rs_up_13w.loc[d]),
            "rs_line_not_declining_7m": None,  # Task 9 미러 단계에서 weekly 값으로 채움
            "minervini_c1": _as_bool(mn["minervini_c1"].loc[d]),
            "minervini_c2": _as_bool(mn["minervini_c2"].loc[d]),
            "minervini_c3": _as_bool(mn["minervini_c3"].loc[d]),
            "minervini_c4": _as_bool(mn["minervini_c4"].loc[d]),
            "minervini_c5": _as_bool(mn["minervini_c5"].loc[d]),
            "minervini_c6": _as_bool(mn["minervini_c6"].loc[d]),
            "minervini_c7": _as_bool(mn["minervini_c7"].loc[d]),
            # V2 거래량 지표
            "volume": _as_float(adj_volume.loc[d]),
            "avg_volume_50d": _as_float(avg_vol_50.loc[d]),
            "volume_ratio_50d": _as_float(vol_ratio_50.loc[d]),
            "pocket_pivot_flag": _as_bool(pp_flag.loc[d]),
            "volume_dry_up_flag": _as_bool(vdu_flag.loc[d]),
            "up_down_volume_ratio_50d": _as_float(ud_ratio_50.loc[d]),
            "distribution_day_flag": _as_bool(dist_flag.loc[d]),
        }
        rows.append(row)
        one_y_returns_for_phase_b[d] = _as_float(one_y_ret.loc[d])

    if not rows:
        return 0
    affected = upsert_daily_indicators_phase_a(conn, rows)
    conn.commit()
    # store 1y returns 임시 cache (Phase B 입력)
    _phase_b_cache.setdefault(ticker, {}).update(one_y_returns_for_phase_b)
    return affected


def _run_phase_b_daily(conn: Connection, upsert_start: date, upsert_end: date) -> int:
    """날짜별 RS Rating 계산 → UPDATE."""
    # 모든 ticker 의 1y_return을 date 별로 모음
    by_date: dict[date, dict[str, float | None]] = {}
    for ticker, date_to_ret in _phase_b_cache.items():
        for d, r in date_to_ret.items():
            if d < upsert_start or d > upsert_end:
                continue
            by_date.setdefault(d, {})[ticker] = r

    update_rows = []
    for d, ticker_to_ret in by_date.items():
        returns = pd.Series(ticker_to_ret, dtype=float)
        rs = assign_rs_rating_percentiles(returns)
        for ticker, rating in rs.items():
            if pd.isna(rating):
                update_rows.append((ticker, d, None))
            else:
                update_rows.append((ticker, d, int(rating)))

    affected = update_daily_indicators_rs_rating(conn, update_rows)
    conn.commit()
    return affected


def _run_sanity_checks_daily(conn: Connection, upsert_end: date) -> list[str]:
    """sanity 검증 (spec §7)."""
    warnings = []
    with conn.cursor() as cur:
        # 1. 커버리지
        cur.execute("SELECT COUNT(*) FROM daily_indicators WHERE date = %s", (upsert_end,))
        ind_count = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM daily_prices WHERE date = %s", (upsert_end,))
        prc_count = cur.fetchone()[0] or 0
        if prc_count > 0:
            ratio = ind_count / prc_count
            if ratio < 0.95:
                warnings.append(f"coverage_low: 지표 행 {ind_count}/{prc_count} ({ratio*100:.1f}%, 임계 95%)")

        # 2. SMA NULL 비율
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE sma_200 IS NULL), COUNT(*)
              FROM daily_indicators WHERE date = %s
        """, (upsert_end,))
        null_count, total = cur.fetchone()
        if total > 0:
            null_ratio = (null_count or 0) / total
            if null_ratio > 0.30:
                warnings.append(f"sma_200_null_ratio_high: {null_ratio*100:.1f}% (임계 30%)")

        # 3. RS Rating 분포
        cur.execute("""
            SELECT MAX(rs_rating), MIN(rs_rating), COUNT(rs_rating)
              FROM daily_indicators WHERE date = %s
        """, (upsert_end,))
        mx, mn, cnt = cur.fetchone()
        if cnt and cnt > 1000:
            if mx != 99 or mn != 0:
                warnings.append(f"rs_rating_distribution_odd: max={mx}, min={mn}, count={cnt}")

        # 4. 미너비니 통과율
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE minervini_pass = TRUE), COUNT(*)
              FROM daily_indicators WHERE date = %s AND minervini_pass IS NOT NULL
        """, (upsert_end,))
        pass_cnt, eval_cnt = cur.fetchone()
        if eval_cnt and eval_cnt > 0:
            ratio = (pass_cnt or 0) / eval_cnt
            if ratio == 0 or ratio > 0.50:
                warnings.append(f"minervini_pass_rate_odd: {ratio*100:.1f}% (정상 1-15%)")
    return warnings


def _run_sanity_checks_weekly(conn: Connection, upsert_end: date) -> list[str]:
    """주봉 지표 sanity 검증 — daily 패턴 미러."""
    warnings = []
    with conn.cursor() as cur:
        # 1. 커버리지
        cur.execute("SELECT COUNT(*) FROM weekly_indicators WHERE week_end_date = %s", (upsert_end,))
        ind_count = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM weekly_prices WHERE week_end_date = %s", (upsert_end,))
        prc_count = cur.fetchone()[0] or 0
        if prc_count > 0:
            ratio = ind_count / prc_count
            if ratio < 0.95:
                warnings.append(f"coverage_low: 주봉 지표 행 {ind_count}/{prc_count} ({ratio*100:.1f}%, 임계 95%)")

        # 2. SMA NULL 비율 (40w 사용)
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE sma_40w IS NULL), COUNT(*)
              FROM weekly_indicators WHERE week_end_date = %s
        """, (upsert_end,))
        null_count, total = cur.fetchone()
        if total > 0:
            null_ratio = (null_count or 0) / total
            if null_ratio > 0.30:
                warnings.append(f"sma_40w_null_ratio_high: {null_ratio*100:.1f}% (임계 30%)")

        # 3. RS Rating 분포
        cur.execute("""
            SELECT MAX(rs_rating), MIN(rs_rating), COUNT(rs_rating)
              FROM weekly_indicators WHERE week_end_date = %s
        """, (upsert_end,))
        mx, mn, cnt = cur.fetchone()
        if cnt and cnt > 1000:
            if mx != 99 or mn != 0:
                warnings.append(f"rs_rating_distribution_odd: max={mx}, min={mn}, count={cnt}")

        # 4. 미너비니 통과율
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE minervini_pass = TRUE), COUNT(*)
              FROM weekly_indicators WHERE week_end_date = %s AND minervini_pass IS NOT NULL
        """, (upsert_end,))
        pass_cnt, eval_cnt = cur.fetchone()
        if eval_cnt and eval_cnt > 0:
            ratio = (pass_cnt or 0) / eval_cnt
            if ratio == 0 or ratio > 0.50:
                warnings.append(f"minervini_pass_rate_odd: {ratio*100:.1f}% (정상 1-15%)")
    return warnings


def run_daily(
    conn: Connection,
    mode: Mode,
    *,
    window: int = 30,
    limit_tickers: int | None = None,
) -> RunStats:
    """일봉 지표 파이프라인 실행."""
    global _phase_b_cache
    _phase_b_cache = {}  # reset

    load_start, load_end, upsert_start = compute_date_range(
        Target.DAILY, mode, window=window, conn=conn,
    )
    log.info(f"daily indicators mode={mode.value} load={load_start}..{load_end} upsert={upsert_start}..{load_end}")

    tickers = load_active_tickers_with_market(conn, limit=limit_tickers)
    log.info(f"daily indicators tickers: {len(tickers)}")

    rows_total = 0
    failures: list[tuple[str, str]] = []

    with run_tracking(
        conn,
        pipeline="indicators",
        mode=f"daily-{mode.value}",
        params={"window": window, "limit_tickers": limit_tickers,
                "load_start": str(load_start), "load_end": str(load_end),
                "upsert_start": str(upsert_start)},
    ) as state:
        # Phase A
        log.info("Phase A: per-ticker time-series indicators")
        for i, (ticker, market) in enumerate(tickers, 1):
            try:
                rows_total += _process_ticker_daily(conn, ticker, market, load_start, load_end, upsert_start)
            except Exception as e:
                failures.append((ticker, str(e)))
                conn.rollback()
            if i % 100 == 0:
                log.info(f"Phase A progress: {i}/{len(tickers)} (failures: {len(failures)})")

        # End-of-run retry for Phase A
        if failures:
            log.warning(f"Phase A retrying {len(failures)} failed tickers")
            retry_failures = []
            ticker_to_market = {t: m for t, m in tickers}
            for ticker, _ in failures:
                try:
                    rows_total += _process_ticker_daily(conn, ticker, ticker_to_market[ticker], load_start, load_end, upsert_start)
                except Exception as e:
                    retry_failures.append((ticker, str(e)))
                    conn.rollback()
            failures = retry_failures

        # Phase B
        log.info("Phase B: per-date RS Rating")
        rs_affected = _run_phase_b_daily(conn, upsert_start, load_end)
        log.info(f"Phase B: {rs_affected} rs_rating cells updated")

        # Phase C
        log.info("Phase C: minervini c8 + pass (SQL UPDATE)")
        mn_affected = update_daily_indicators_minervini_pass(conn, upsert_start, load_end)
        conn.commit()
        log.info(f"Phase C: {mn_affected} rows updated")

        # Phase D: 주봉 게이트(rs_line_not_declining_7m)를 daily 행에 미러.
        # 전제: weekly_indicators 가 먼저 적재돼 있어야 정확(없으면 NULL→후보쿼리 = TRUE 게이트에서 제외).
        # 전체 재계산 시 weekly → daily 순서 실행(설계 §9.1, plan Task 14).
        gate_affected = update_daily_rs_gate_from_weekly(conn, upsert_start, load_end)
        conn.commit()
        log.info("daily rs gate mirrored: %d rows", gate_affected)

        # Sanity
        warnings = _run_sanity_checks_daily(conn, load_end)
        state["warnings"].extend(warnings)
        state["rows_affected"] = rows_total

    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings)


def run(
    conn: Connection,
    *,
    target: str = "daily",
    mode: Mode,
    limit_tickers: int | None = None,
    window: int = 30,
) -> RunStats:
    """target ('daily' | 'weekly') 에 따라 run_daily / run_weekly 분기."""
    if target == "daily" or target == Target.DAILY:
        return run_daily(conn, mode, window=window, limit_tickers=limit_tickers)
    elif target == "weekly" or target == Target.WEEKLY:
        return run_weekly(conn, mode, window=window, limit_tickers=limit_tickers)
    else:
        raise ValueError(f"Unknown target: {target!r}")


# Weekly 동일 패턴 (compute 호출 시 window 가 주봉 기준)
def _process_ticker_weekly(
    conn: Connection,
    ticker: str,
    market: str,
    load_start: date,
    load_end: date,
    upsert_start: date,
) -> int:
    df_weekly = load_weekly_prices(conn, ticker, load_start, load_end)
    if df_weekly.empty:
        return 0
    index_code = KOSPI_INDEX_CODE  # D2: 종목 시장 무관 KOSPI 단일 분모
    df_idx = load_weekly_index(conn, index_code, load_start, load_end)
    if df_idx.empty:
        return 0

    df = df_weekly.merge(df_idx.rename(columns={"close": "index_close"}), on="date", how="left")
    df = df.set_index("date").sort_index()
    adj_close = df["adj_close"]

    # V3: weekly_prices.adj_volume 직접 읽기 (split-adjusted volume 재계산 제거, 주봉 window=10)
    adj_volume = df["adj_volume"]
    avg_vol_10w = avg_volume(adj_volume, window=10)
    vol_ratio_10w = volume_ratio(adj_volume, avg_vol_10w)

    is_up = adj_close > adj_close.shift(1)
    is_down = adj_close < adj_close.shift(1)
    ud_ratio_10w = up_down_volume_ratio(adj_volume, is_up, is_down, window=10)

    sma_10w_s = sma(adj_close, 10)
    sma_30w_s = sma(adj_close, 30)
    sma_40w_s = sma(adj_close, 40)
    w52h, w52l = w52_high_low(df["adj_high"], df["adj_low"], window=52)
    pct_h, pct_l = pct_from_high_low(adj_close, w52h, w52l)
    rs_line = compute_rs_line(adj_close, df["index_close"])
    rs_line_high, rs_line_high_date = compute_rs_line_52w_high_and_date(rs_line, window=52)
    rs_at_high = compute_rs_line_at_52w_high(rs_line, rs_line_high)
    rs_up_6w = compute_rs_line_uptrend_slope(rs_line, window=RS_LINE_UPTREND_SHORT_WEEKS)
    rs_up_13w = compute_rs_line_uptrend_slope(rs_line, window=RS_LINE_UPTREND_LONG_WEEKS)
    rs_not_declining = compute_rs_line_not_declining(rs_line, window=RS_LINE_DECLINE_GATE_WEEKS)
    one_y_ret = compute_ibd_strength_factor(adj_close, 13, 26, 39, 52)

    mn_df = pd.DataFrame({
        "adj_close": adj_close,
        "sma_50": sma_10w_s, "sma_150": sma_30w_s, "sma_200": sma_40w_s,
        "w52_high": w52h, "w52_low": w52l,
    }, index=df.index)
    mn = compute_minervini_c1_to_c7(mn_df, sma_200_lookback=5)  # 5주 ≈ 1개월 (책 정합)

    rows = []
    one_y_returns_for_phase_b = {}
    for d in df.index:
        if d < upsert_start:
            continue
        row = {
            "ticker": ticker, "week_end_date": d, "adj_close": float(adj_close.loc[d]),
            "sma_10w": _as_float(sma_10w_s.loc[d]),
            "sma_30w": _as_float(sma_30w_s.loc[d]),
            "sma_40w": _as_float(sma_40w_s.loc[d]),
            "w52_high": _as_float(w52h.loc[d]),
            "w52_low": _as_float(w52l.loc[d]),
            "pct_from_52w_high": _as_float(pct_h.loc[d]),
            "pct_from_52w_low": _as_float(pct_l.loc[d]),
            "rs_line": _as_float(rs_line.loc[d]),
            "rs_line_52w_high": _as_float(rs_line_high.loc[d]),
            "rs_line_52w_high_date": rs_line_high_date.loc[d] if pd.notna(rs_line_high_date.loc[d]) else None,
            "rs_line_at_52w_high": _as_bool(rs_at_high.loc[d]),
            "rs_line_uptrend_6w": _as_bool(rs_up_6w.loc[d]),
            "rs_line_uptrend_13w": _as_bool(rs_up_13w.loc[d]),
            "rs_line_not_declining_7m": _as_bool(rs_not_declining.loc[d]),
            "minervini_c1": _as_bool(mn["minervini_c1"].loc[d]),
            "minervini_c2": _as_bool(mn["minervini_c2"].loc[d]),
            "minervini_c3": _as_bool(mn["minervini_c3"].loc[d]),
            "minervini_c4": _as_bool(mn["minervini_c4"].loc[d]),
            "minervini_c5": _as_bool(mn["minervini_c5"].loc[d]),
            "minervini_c6": _as_bool(mn["minervini_c6"].loc[d]),
            "minervini_c7": _as_bool(mn["minervini_c7"].loc[d]),
            # V2 거래량 지표
            "volume": _as_float(adj_volume.loc[d]),
            "avg_volume_10w": _as_float(avg_vol_10w.loc[d]),
            "volume_ratio_10w": _as_float(vol_ratio_10w.loc[d]),
            "up_down_volume_ratio_10w": _as_float(ud_ratio_10w.loc[d]),
        }
        rows.append(row)
        one_y_returns_for_phase_b[d] = _as_float(one_y_ret.loc[d])

    if not rows:
        return 0
    affected = upsert_weekly_indicators_phase_a(conn, rows)
    conn.commit()
    _phase_b_cache.setdefault(ticker, {}).update(one_y_returns_for_phase_b)
    return affected


def _run_phase_b_weekly(conn: Connection, upsert_start: date, upsert_end: date) -> int:
    by_date: dict[date, dict[str, float | None]] = {}
    for ticker, date_to_ret in _phase_b_cache.items():
        for d, r in date_to_ret.items():
            if d < upsert_start or d > upsert_end:
                continue
            by_date.setdefault(d, {})[ticker] = r

    update_rows = []
    for d, ticker_to_ret in by_date.items():
        returns = pd.Series(ticker_to_ret, dtype=float)
        rs = assign_rs_rating_percentiles(returns)
        for ticker, rating in rs.items():
            update_rows.append((ticker, d, None if pd.isna(rating) else int(rating)))
    affected = update_weekly_indicators_rs_rating(conn, update_rows)
    conn.commit()
    return affected


def run_weekly(
    conn: Connection,
    mode: Mode,
    *,
    window: int = 4,
    limit_tickers: int | None = None,
) -> RunStats:
    global _phase_b_cache
    _phase_b_cache = {}

    load_start, load_end, upsert_start = compute_date_range(
        Target.WEEKLY, mode, window=window, conn=conn,
    )
    log.info(f"weekly indicators mode={mode.value} load={load_start}..{load_end} upsert={upsert_start}..{load_end}")

    tickers = load_active_tickers_with_market(conn, limit=limit_tickers)
    log.info(f"weekly indicators tickers: {len(tickers)}")

    rows_total = 0
    failures: list[tuple[str, str]] = []

    with run_tracking(
        conn,
        pipeline="indicators",
        mode=f"weekly-{mode.value}",
        params={"window": window, "limit_tickers": limit_tickers,
                "load_start": str(load_start), "load_end": str(load_end),
                "upsert_start": str(upsert_start)},
    ) as state:
        for i, (ticker, market) in enumerate(tickers, 1):
            try:
                rows_total += _process_ticker_weekly(conn, ticker, market, load_start, load_end, upsert_start)
            except Exception as e:
                failures.append((ticker, str(e)))
                conn.rollback()
            if i % 100 == 0:
                log.info(f"Phase A progress: {i}/{len(tickers)} (failures: {len(failures)})")

        if failures:
            ticker_to_market = {t: m for t, m in tickers}
            retry_failures = []
            for ticker, _ in failures:
                try:
                    rows_total += _process_ticker_weekly(conn, ticker, ticker_to_market[ticker], load_start, load_end, upsert_start)
                except Exception as e:
                    retry_failures.append((ticker, str(e)))
                    conn.rollback()
            failures = retry_failures

        rs_affected = _run_phase_b_weekly(conn, upsert_start, load_end)
        log.info(f"Phase B weekly: {rs_affected} updated")

        mn_affected = update_weekly_indicators_minervini_pass(conn, upsert_start, load_end)
        conn.commit()
        log.info(f"Phase C weekly: {mn_affected} updated")

        warnings = _run_sanity_checks_weekly(conn, load_end)
        state["warnings"].extend(warnings)
        state["rows_affected"] = rows_total

    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings)
