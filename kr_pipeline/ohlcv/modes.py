from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
import logging

import pandas as pd
from psycopg import Connection

from kr_pipeline.db.runs import run_tracking
from kr_pipeline.ohlcv import adjust, tripwires
from kr_pipeline.ohlcv.fetch import fetch_raw_datewise, fetch_index
from kr_pipeline.ohlcv.transform import (
    to_price_rows, to_index_rows, nullify_halt_adj,
)
from kr_pipeline.ohlcv.store import upsert_daily_prices, update_adj_prices, upsert_index_daily


log = logging.getLogger("kr_pipeline.ohlcv")


class Mode(str, Enum):
    BACKFILL = "backfill"
    INCREMENTAL = "incremental"
    FULL_REFRESH = "full-refresh"


def _get_db_min_date(conn: Connection) -> date:
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(date) FROM daily_prices")
        row = cur.fetchone()
        return row[0] if row and row[0] else date.today()


def compute_date_range(
    mode: Mode,
    *,
    years: int = 2,
    window_days: int = 30,
    conn: Connection | None = None,
    exclude_today: bool = False,
) -> tuple[date, date]:
    """모드별 일봉 fetch 범위.

    exclude_today: INCREMENTAL 에서 end 를 어제로 당김 (장중 수동 실행 시 오늘 *미확정*
        부분봉 회피용 opt-in). 기본 False = end=today — 마감 후 cron 이 당일 확정봉을
        같은 날 적재하는 동작을 보존. BACKFILL/FULL_REFRESH 는 이미 end=어제라 무영향.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)
    if mode == Mode.BACKFILL:
        return today - timedelta(days=365 * years), yesterday
    if mode == Mode.INCREMENTAL:
        return today - timedelta(days=window_days), (yesterday if exclude_today else today)
    if mode == Mode.FULL_REFRESH:
        return _get_db_min_date(conn), yesterday
    raise ValueError(f"Unknown mode: {mode}")


def _load_active_tickers(conn: Connection, limit: int | None = None) -> list[str]:
    with conn.cursor() as cur:
        sql = "SELECT ticker FROM stocks WHERE delisted_at IS NULL ORDER BY ticker"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]


@dataclass
class RunStats:
    rows_affected: int
    failures: list[tuple[str, str]]
    warnings: list[str] = field(default_factory=list)
    adjusted_tickers: list[str] = field(default_factory=list)   # #207: 이번 run 에서 신규 조정일이 기록·소급된 종목


# [design judgment] 빈 응답 경고 강화 임계 — book 근거 아님. KRX throttling 은
# 예외가 아닌 '빈 DataFrame' 으로 나타나 성공도 실패도 아닌 상태로 소멸했다
# (2026-06-10 사고: backfill 607종목 과거 미적재인데 failures=0). 정상일에도
# 거래정지 등으로 소수의 빈 응답은 있을 수 있어, 집계는 항상 하되 비율이
# 이 임계를 넘으면 throttling 패턴으로 강조한다.
_EMPTY_FETCH_WARN_RATIO = 0.01


def _empty_fetch_warning(empties: list[str], total: int) -> list[str]:
    """빈 응답 종목 계정 → warnings 항목. 빈 응답 0건이면 빈 리스트."""
    if not empties:
        return []
    ratio = len(empties) / total if total else 0.0
    msg = f"empty_fetch: {len(empties)}/{total} 종목 빈 응답 (KRX throttling 의심, {ratio:.1%})"
    if ratio > _EMPTY_FETCH_WARN_RATIO:
        msg += f" — 임계 {_EMPTY_FETCH_WARN_RATIO:.0%} 초과, 과거 조용한 누락 사고 패턴"
    msg += f": {empties[:20]}"
    return [msg]


# (#49) 수정 OHLC 봉 불변식 위반의 실측 기준 (2026-07-17 0단계 검증 F1, 21,541행).
# 소스(pykrx adjusted)가 수정 환산 시 컬럼별 독립 반올림을 해 adj_close > adj_high
# 행을 돌려주는 것을 직접 호출로 확증 — 로컬 수리 불가라 보정은 보류(관측 전용).
# 강조 신호 2종 (empty_fetch 임계와 동일 철학 — 항상 집계, 임계 초과 시 강조):
# 1) 절대 기준 초과 — full-refresh 가 과거 이력까지 대량 오염시키는 소스 변화 감지.
#    단, 카운트는 주간 재정규화로 하향 드리프트(2026-07-21 실측 21,288)하므로
#    이 기준의 민감도는 ±수백 행 수준이다 — 소량 신규 위반은 2)가 담당.
# 2) 최근 30일 위반 행 수 — 신규 적재분의 위반 급증 감지 (드리프트 무관).
#    2025+ 전체가 8행(월 ~0.7행)이라 30일 3행 초과는 정상 대비 ~4배 신호.
_ADJ_INVARIANT_BASELINE = 21_541
_ADJ_INVARIANT_RECENT_WARN = 3


def _run_sanity_checks(conn: Connection, mode: Mode) -> list[str]:
    """OHLCV 적재 후 데이터 sanity 검증. 경고 메시지 리스트 반환 (실패 아님).

    검증 항목:
    1. 최근 영업일 커버리지: daily_prices 의 가장 최근 날짜에 들어온 종목 수가
       활성 universe 의 80% 미만이면 경고.
    2. 가격 이상치: close <= 0 또는 adj_close <= 0 인 행이 있으면 경고.
    3. (#49) 수정 봉 불변식: adj_close 가 adj_high 초과 또는 adj_low 미만인 행
       카운트 — pykrx 유래 관측 전용. 강조는 최근 30일 급증(우선) 또는
       절대 기준(_ADJ_INVARIANT_BASELINE) 초과 시.

    full-refresh 모드는 새 행을 추가하지 않으므로 커버리지 검증을 건너뜀.
    """
    warnings: list[str] = []

    with conn.cursor() as cur:
        # 검증 1: 최근 영업일 커버리지 (full-refresh 제외)
        if mode != Mode.FULL_REFRESH:
            cur.execute("""
                SELECT COUNT(DISTINCT ticker)
                  FROM daily_prices
                 WHERE date = (SELECT MAX(date) FROM daily_prices)
            """)
            coverage_count = cur.fetchone()[0] or 0

            cur.execute("SELECT COUNT(*) FROM stocks WHERE delisted_at IS NULL")
            active_count = cur.fetchone()[0] or 0

            if active_count > 0:
                ratio = coverage_count / active_count
                if ratio < 0.80:
                    warnings.append(
                        f"coverage_low: 최근 영업일 일봉 수신 종목 {coverage_count}/{active_count} "
                        f"({ratio*100:.1f}%, 임계 80%)"
                    )

        # 검증 2: 이상치
        cur.execute("""
            SELECT COUNT(*) FROM daily_prices
             WHERE close <= 0 OR adj_close <= 0
        """)
        bad_price_count = cur.fetchone()[0] or 0
        if bad_price_count > 0:
            warnings.append(f"bad_prices: {bad_price_count} 행이 close 또는 adj_close <= 0")

        # 검증 3 (#49): 수정 봉 불변식 (adj_low ≤ adj_close ≤ adj_high)
        # total 은 COUNT(*)(고유 행) — 양방향 동시 위반 행의 이중 계수 방지.
        cur.execute("""
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE adj_close > adj_high),
                   COUNT(*) FILTER (WHERE adj_close < adj_low),
                   COUNT(*) FILTER (WHERE date >= CURRENT_DATE - 30),
                   MAX(date)
              FROM daily_prices
             WHERE adj_close > adj_high OR adj_close < adj_low
        """)
        total, over_high, under_low, recent, latest = cur.fetchone()
        if total > 0:
            msg = (
                f"adj_ohlc_invariant: {total}행 수정 봉 불변식 위반 "
                f"(close>high {over_high}·close<low {under_low}, 최근 {latest}) "
                f"— pykrx 반올림 유래 관측(#49)"
            )
            if recent > _ADJ_INVARIANT_RECENT_WARN:
                msg += (
                    f" — 최근 30일 {recent}행(임계 {_ADJ_INVARIANT_RECENT_WARN}행 초과), "
                    f"신규 적재 위반 급증 — 소스 동작 변화 의심"
                )
            elif total > _ADJ_INVARIANT_BASELINE:
                msg += (
                    f" — 기준 {_ADJ_INVARIANT_BASELINE:,}행(2026-07 실측) 초과, "
                    f"소스 동작 변화 의심"
                )
            warnings.append(msg)

    return warnings


def run(
    conn: Connection,
    mode: Mode,
    *,
    years: int = 2,
    window_days: int = 30,
    limit_tickers: int | None = None,
    max_workers: int = 3,
    exclude_today: bool = False,
) -> RunStats:
    params = {
        "years": years if mode == Mode.BACKFILL else None,
        "window_days": window_days if mode == Mode.INCREMENTAL else None,
        "limit_tickers": limit_tickers,
        "exclude_today": exclude_today if (mode == Mode.INCREMENTAL and exclude_today) else None,
    }
    params = {k: v for k, v in params.items() if v is not None}

    start, end = compute_date_range(
        mode, years=years, window_days=window_days, conn=conn, exclude_today=exclude_today,
    )
    log.info(f"mode={mode.value} range={start}..{end}")

    tickers = _load_active_tickers(conn, limit=limit_tickers)
    log.info(f"tickers to process: {len(tickers)}")

    with run_tracking(conn, pipeline="ohlcv", mode=mode.value, params={**params, "start": str(start), "end": str(end)}) as state:
        if mode == Mode.FULL_REFRESH:
            stats = _run_full_refresh(conn, tickers, start, end, max_workers, mode)
        else:
            stats = _run_upsert(conn, tickers, start, end, max_workers, mode)
        state["warnings"].extend(stats.warnings)
        state["rows_affected"] = stats.rows_affected
        return stats


def _run_upsert(conn, tickers, start, end, max_workers, mode: Mode) -> RunStats:
    """#207 A안: raw(KRX) 만 수집, 수정 OHLCV 는 자체 계수(adjust)로 산출 — Naver 접촉 0. 4단계(회신 17 조건 = 예외 위치):
    ① raw 적재(fail-open): 종목별 조정일 후보 검출(직전 거래일 결측이면 보류) → 배치 행 adj = raw × F(기록된 이벤트만) → upsert
       (시임 이전 기존 행 adj 보존) → commit. 당일 KRX 봉은 여기서 전부 저장된다.
    ② 트립와이어 (1′)(3): 후보 이벤트 일별 수 · raw 봉 정합 → 위반 시 AdjustmentTripwireError(이벤트 기록·소급·재유도 **전**,
       ohlcv run failed → 체인 중단 → 지표 미계산).
    ③ 이벤트 유도: adjust.ingest_events(기록 → 정책 소급 → 시임 이후 재유도) → adjusted_tickers.
    ④ 트립와이어 (2): 유도 결과 봉 포함 관계 → 위반 시 예외(지표 전)."""
    successes, failures = fetch_raw_datewise(tickers, start, end)
    blocked = {date.fromisoformat(ident.split("snapshot:", 1)[1]) for ident, _ in failures if ident.startswith("snapshot:")}
    batch_dates = {d for raw in successes.values() if not raw.empty for d in raw["date"]}
    calendar = adjust.trading_days(conn, start - timedelta(days=45)) | batch_dates | blocked   # 거래일(또는 미확인) 집합
    rows_total = 0
    empties: list[str] = []
    pending: dict[str, list[tuple[date, float]]] = {}
    # ① raw 적재(fail-open)
    for ticker, raw in successes.items():
        if raw.empty:
            # 성공도 실패도 아닌 소멸 금지 — 계정 후 skip (P1-5 B)
            empties.append(ticker)
            continue
        raw = raw.sort_values("date").reset_index(drop=True)
        known = adjust.load_events(conn, ticker)
        prev_date, prev_close = adjust.last_row_before(conn, ticker, raw["date"].min())
        new_events = adjust.unrecorded(conn, ticker, adjust.events_in_frame(
            raw, prev_close=prev_close, prev_date=prev_date, open_days=calendar))
        if new_events:
            pending[ticker] = new_events
        rows = to_price_rows(ticker, adjust.derive_adj(raw, known))
        rows_total += upsert_daily_prices(conn, rows, adj_from=adjust.ADJ_SELF_START)
        conn.commit()
    # ② (1′)(3) — raw 저장 후 · 이벤트 유도 전
    tripwires.raise_if_violations(tripwires.check_pending_event_counts(pending) + tripwires.check_raw_bars(conn, start=start, end=end))
    # ③ 이벤트 유도
    adjusted: list[str] = []
    for ticker, new_events in pending.items():
        info = adjust.ingest_events(conn, ticker, new_events)
        adjusted.append(ticker)
        log.info("adjustment events %s: %s -> %s", ticker, [(str(d), round(c, 6)) for d, c in new_events], info)
        conn.commit()
    # ④ (2) — 유도 결과 검사
    tripwires.raise_if_violations(tripwires.check_adj_envelope(conn, start=start, end=end))

    # 지수
    empty_indexes: list[str] = []
    for index_code in ("1001", "2001"):
        idx_df = fetch_index(index_code, start, end)
        if idx_df.empty:
            empty_indexes.append(index_code)
            continue
        idx_rows = to_index_rows(index_code, idx_df)
        upsert_index_daily(conn, idx_rows)
        conn.commit()

    warnings = _empty_fetch_warning(empties, len(tickers))
    # 스냅샷 결측 날짜 승격 (#94 리뷰) — 창 중간 하루 차단/실패는 어떤 종목도
    # raw.empty 로 만들지 않아 empty_fetch 가 못 잡는다. failures 는 run warnings
    # 에 영속되지 않으므로(run_tracking 은 warnings 만 기록) 여기서 승격한다.
    snap_gaps = [ident.split("snapshot:", 1)[1] for ident, _ in failures
                 if ident.startswith("snapshot:")]
    if snap_gaps:
        warnings.append(
            f"snapshot_gap: 날짜별 스냅샷 결측 {len(snap_gaps)}건 {snap_gaps} — "
            f"해당 날짜 전 종목 raw 미적재 (P1-5 계열, backfill 이면 해당 구간 재실행 필요)"
        )
    if empty_indexes:
        warnings.append(f"empty_index_fetch: 지수 {empty_indexes} 빈 응답")
    warnings.extend(_run_sanity_checks(conn, mode))
    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings, adjusted_tickers=adjusted)


def _run_full_refresh(conn, tickers, start, end, max_workers, mode: Mode = Mode.FULL_REFRESH) -> RunStats:
    """#207 A안: 수정 OHLCV 전체 재유도 — **외부 접촉 0**. 종목별 adjust.rederive_post_seam(시임 이후 행 raw × F, adj 컬럼만).
    시임 이전 행(Naver 구정의 이력, 후행 이벤트 소급 포함)은 건드리지 않는다. start 는 무시(시임이 하한), end 는 상한."""
    rows_total = 0
    failures: list[tuple[str, str]] = []
    for i, ticker in enumerate(tickers, 1):
        try:
            rows_total += adjust.rederive_post_seam(conn, ticker, end=end)
            conn.commit()
        except Exception as e:
            failures.append((ticker, str(e)))
            conn.rollback()  # DB 측 예외의 aborted 트랜잭션이 후속 종목으로 연쇄되지 않게
        if i % 100 == 0:
            log.info(f"full-refresh progress: {i}/{len(tickers)} (failures so far: {len(failures)})")
    warnings = _run_sanity_checks(conn, mode)
    return RunStats(rows_affected=rows_total, failures=failures, warnings=warnings)
