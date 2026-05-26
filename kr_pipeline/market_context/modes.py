# kr_pipeline/market_context/modes.py
"""market_context 모드 분기 + 오케스트레이션."""
import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from psycopg import Connection

from kr_pipeline.db.runs import run_tracking
from kr_pipeline.market_context.compute.distribution_day import count_distribution_days
from kr_pipeline.market_context.compute.follow_through import detect_last_ftd
from kr_pipeline.market_context.compute.status import determine_status
from kr_pipeline.market_context.compute.breadth import compute_breadth
from kr_pipeline.market_context.load import (
    load_index_daily_with_sma200, load_market_daily_indicators, get_index_min_date,
)
from kr_pipeline.market_context.store import upsert_market_context
from kr_pipeline.common.thresholds import (
    NASDAQ_REFERENCE_SIGMA,
    FTD_PCT_BASE,
    DISTRIBUTION_PCT_BASE,
    KOREAN_SIGMA_RATIO_FLOOR,
    KOREAN_SIGMA_RATIO_CEILING,
)
from kr_pipeline.market_context.compute.volatility import (
    compute_korean_sigma_pct,
    derive_market_thresholds,
    book_default_thresholds,
)


log = logging.getLogger("kr_pipeline.market_context")

# 캘린더 일 — 200~252 거래일 lookback (SMA-200 + yearly high) 보장용.
# timedelta(days=) 가 캘린더 단위이므로 거래일을 캘린더 일로 환산.
LOOKBACK_DAYS = 400           # 252 거래일 ≈ 375 캘린더 일 + 안전 마진


INDICES = [
    ("1001", "KOSPI"),
    ("2001", "KOSDAQ"),
]


COMPUTATION_NOTES = json.dumps({
    "distribution_day_pct_base": -0.2,
    "ftd_pct_base": 1.4,
    "note": "P2-1a: market thresholds scaled per-index by Korean σ. See log for per-date applied values.",
    "ftd_rally_window_min": 3,
    "ftd_rally_window_max": 15,
    "ftd_lookback_days": 90,
    "correction_off_high_pct": -10,
    "downtrend_off_high_pct": -15,
    "dist_count_threshold_for_ftd_invalidation": 6,
}, ensure_ascii=False)


class Mode(str, Enum):
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"
    FULL_REFRESH = "full-refresh"


@dataclass
class RunStats:
    rows_affected: int
    failures: list[tuple[str, str]]
    warnings: list[str] = field(default_factory=list)


def _get_min_date(conn: Connection | None) -> date:
    """index_daily 의 가장 오래된 날짜 (KOSPI 와 KOSDAQ 둘 중 작은 것)."""
    if conn is None:
        return date.today()
    kospi_min = get_index_min_date(conn, "1001")
    kosdaq_min = get_index_min_date(conn, "2001")
    candidates = [d for d in (kospi_min, kosdaq_min) if d]
    return min(candidates) if candidates else date.today()


def compute_date_range(
    mode: Mode,
    *,
    window_days: int = 30,
    conn: Connection | None = None,
) -> tuple[date, date, date]:
    """(load_start, load_end, upsert_start)."""
    today = date.today()
    yesterday = today - timedelta(days=1)

    if mode == Mode.INCREMENTAL:
        load_start = today - timedelta(days=window_days + LOOKBACK_DAYS)
        upsert_start = today - timedelta(days=window_days)
        return load_start, yesterday, upsert_start

    if mode in (Mode.BACKFILL, Mode.FULL_REFRESH):
        min_date = _get_min_date(conn)
        return min_date, yesterday, min_date

    raise ValueError(f"Unknown mode: {mode}")


def _process_one_date(
    conn: Connection,
    target_date: date,
    index_code: str,
    market: str,
    index_df,
    *,
    thresholds_override: dict | None = None,
) -> dict | None:
    """특정 (date, index_code) 의 컨텍스트 1 행 계산.

    index_df: load_index_daily_with_sma200 결과 (시계열, end_idx 까지).
    target_date 가 index_df 에 있어야 함.

    thresholds_override: verification harness 전용 (replay). None (default) 이면
    운영 경로 — σ 측정 + derive. dict 주입 시 σ 측정 건너뛰고 그 임계 사용
    (base vs corrected 비교용). 운영 cron 은 항상 None — 동작 변화 0.
    """
    # target_date 의 row 위치 찾기
    matching = index_df[index_df["date"] == target_date]
    if matching.empty:
        return None
    end_idx = matching.index[0]

    today_row = index_df.iloc[end_idx]

    # Status 결정 입력 준비
    close = float(today_row["close"])
    sma_50 = float(today_row["sma_50"]) if not _is_nan(today_row["sma_50"]) else None
    sma_200 = float(today_row["sma_200"]) if not _is_nan(today_row["sma_200"]) else None
    yearly_high = float(today_row["yearly_high"])
    pct_off_yearly_high = (close - yearly_high) / yearly_high * 100 if yearly_high > 0 else 0.0

    # P2-1a: 시장별 σ 측정 → 보정 임계 derive (fallback 안전 후퇴 보장)
    # thresholds_override 가 주어지면 (replay verification harness) σ 측정 건너뜀.
    if thresholds_override is not None:
        thresholds = thresholds_override
    elif (sigma := compute_korean_sigma_pct(conn, index_code, as_of=target_date)) is None:
        thresholds = book_default_thresholds(
            ftd_base=FTD_PCT_BASE,
            dist_base=DISTRIBUTION_PCT_BASE,
        )
        log.warning(
            "sigma fallback for %s @ %s — using book defaults (ftd=%.3f, dist=%.3f)",
            index_code, target_date,
            thresholds["ftd_pct"], thresholds["distribution_pct"],
        )
    else:
        thresholds = derive_market_thresholds(
            sigma,
            anchor_sigma=NASDAQ_REFERENCE_SIGMA,
            ftd_base=FTD_PCT_BASE,
            dist_base=DISTRIBUTION_PCT_BASE,
            clamp_floor=KOREAN_SIGMA_RATIO_FLOOR,
            clamp_ceiling=KOREAN_SIGMA_RATIO_CEILING,
        )
        log.info(
            "sigma derived for %s @ %s: sigma=%.3f raw_ratio=%.3f ratio_applied=%.3f clamped=%s ftd_pct=%.3f dist_pct=%.3f",
            index_code, target_date, sigma,
            thresholds["raw_ratio"], thresholds["ratio_applied"], thresholds["clamped"],
            thresholds["ftd_pct"], thresholds["distribution_pct"],
        )

    dist_count = count_distribution_days(
        index_df, end_idx=end_idx,
        pct_threshold=thresholds["distribution_pct"],
        lookback=25,
    )
    last_ftd_date = detect_last_ftd(
        index_df, end_idx=end_idx,
        pct_threshold=thresholds["ftd_pct"],
        lookback_days=90,
    )
    days_since_ftd = (target_date - last_ftd_date).days if last_ftd_date else None

    current_status = determine_status(
        close=close, sma_50=sma_50, sma_200=sma_200,
        pct_off_yearly_high=pct_off_yearly_high,
        dist_count=dist_count, last_ftd_date=last_ftd_date, today_date=target_date,
    )

    # Breadth
    rows_for_breadth = load_market_daily_indicators(conn, market, target_date)
    breadth = compute_breadth(rows_for_breadth)

    return {
        "date": target_date,
        "index_code": index_code,
        "current_status": current_status,
        "distribution_day_count_last_25": dist_count,
        "last_follow_through_day": last_ftd_date,
        "days_since_follow_through": days_since_ftd,
        "pct_stocks_above_200d_ma": breadth,
        "computation_notes": COMPUTATION_NOTES,
    }


def _is_nan(v) -> bool:
    import math
    if v is None:
        return True
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


def _run_sanity_checks(conn: Connection, upsert_end: date) -> list[str]:
    warnings = []
    with conn.cursor() as cur:
        # 1. status 분포 (4 enum 외 없는지 — 코드 보장이라 거의 안 트리거)
        cur.execute("""
            SELECT current_status, COUNT(*) FROM market_context_daily
             WHERE date = %s GROUP BY current_status
        """, (upsert_end,))
        statuses = {row[0]: row[1] for row in cur.fetchall()}
        if any(s not in ("confirmed_uptrend", "rally_attempt", "correction", "downtrend") for s in statuses):
            warnings.append(f"unknown_status: {set(statuses) - {'confirmed_uptrend','rally_attempt','correction','downtrend'}}")

        # 2. breadth 범위 (0~100)
        cur.execute("""
            SELECT COUNT(*) FROM market_context_daily
             WHERE date = %s AND pct_stocks_above_200d_ma IS NOT NULL
               AND (pct_stocks_above_200d_ma < 0 OR pct_stocks_above_200d_ma > 100)
        """, (upsert_end,))
        bad_breadth = cur.fetchone()[0]
        if bad_breadth > 0:
            warnings.append(f"breadth_out_of_range: {bad_breadth} rows")

        # 3. dist_count 범위 (0~25)
        cur.execute("""
            SELECT COUNT(*) FROM market_context_daily
             WHERE date = %s AND (distribution_day_count_last_25 < 0 OR distribution_day_count_last_25 > 25)
        """, (upsert_end,))
        bad_dist = cur.fetchone()[0]
        if bad_dist > 0:
            warnings.append(f"dist_count_out_of_range: {bad_dist} rows")
    return warnings


def run(
    conn: Connection,
    mode: Mode,
    *,
    window_days: int = 30,
) -> RunStats:
    load_start, load_end, upsert_start = compute_date_range(
        mode, window_days=window_days, conn=conn,
    )
    log.info(f"market_context mode={mode.value} load={load_start}..{load_end} upsert={upsert_start}..{load_end}")

    rows_total = 0
    failures: list[tuple[str, str]] = []

    with run_tracking(
        conn,
        pipeline="market_context",
        mode=mode.value,
        params={"window_days": window_days, "load_start": str(load_start),
                "load_end": str(load_end), "upsert_start": str(upsert_start)},
    ) as state:
        # KOSPI 와 KOSDAQ 처리
        for index_code, market in INDICES:
            try:
                idx_df = load_index_daily_with_sma200(conn, index_code, load_start, load_end)
                if idx_df.empty:
                    log.warning(f"no index_daily data for {index_code}")
                    continue

                # upsert_start 이상인 날짜만 처리
                target_rows = idx_df[idx_df["date"] >= upsert_start]
                rows_to_upsert = []
                for _, row in target_rows.iterrows():
                    target_date = row["date"]
                    if isinstance(target_date, str):
                        from datetime import date as _date
                        target_date = _date.fromisoformat(target_date)
                    elif hasattr(target_date, "date"):
                        target_date = target_date.date()
                    try:
                        result = _process_one_date(conn, target_date, index_code, market, idx_df)
                        if result:
                            rows_to_upsert.append(result)
                    except Exception as e:
                        failures.append((f"{index_code}@{target_date}", str(e)))

                if rows_to_upsert:
                    rows_total += upsert_market_context(conn, rows_to_upsert)
                    conn.commit()
                    log.info(f"{index_code}: upserted {len(rows_to_upsert)} rows")

            except Exception as e:
                failures.append((index_code, str(e)))
                conn.rollback()

        # Sanity
        warnings = _run_sanity_checks(conn, load_end)
        state["warnings"].extend(warnings)
        state["rows_affected"] = rows_total

    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings)
