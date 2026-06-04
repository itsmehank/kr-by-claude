"""조정 드리프트(분할 등) 감지 + 단일종목 전 기간 재적재.

detect 는 ohlcv 증분 전에 실행해야 한다(증분이 adj_close 를 덮어쓰기 전 DB vs KRX 비교).
스펙: docs/superpowers/specs/2026-06-04-pipeline-integration-drift-reload-design.md §2.
"""
from __future__ import annotations
import logging
from datetime import date, timedelta

from psycopg import Connection

from kr_pipeline.ohlcv.fetch import fetch_adj_only
from kr_pipeline.ohlcv.store import update_adj_prices
from kr_pipeline.weekly.load import get_daily_min_date
from kr_pipeline.weekly import modes as weekly
from kr_pipeline.indicators import modes as indicators

log = logging.getLogger("kr_pipeline.pipeline.drift")


def is_drift(
    db_adj: dict[date, float],
    krx_adj: dict[date, float],
    rel_tol: float,
) -> bool:
    """DB 저장 adj_close vs KRX 재조회 adj_close 비교.

    겹치는 날짜(둘 다 존재)에서 상대차 |db-krx|/|krx| 가 rel_tol 초과면 True.
    겹침이 없으면 False(호출부가 기간 확대를 책임진다).
    """
    overlap = db_adj.keys() & krx_adj.keys()
    for d in overlap:
        k = krx_adj[d]
        if k == 0:
            continue
        if abs(db_adj[d] - k) / abs(k) > rel_tol:
            return True
    return False


def _active_tickers(conn: Connection, limit: int | None = None) -> list[str]:
    sql = "SELECT ticker FROM stocks WHERE delisted_at IS NULL ORDER BY ticker"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn.cursor() as cur:
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]


def _db_adj_close(conn: Connection, ticker: str, start: date, end: date) -> dict[date, float]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, adj_close FROM daily_prices "
            "WHERE ticker = %s AND date BETWEEN %s AND %s AND adj_close IS NOT NULL",
            (ticker, start, end),
        )
        return {r[0]: float(r[1]) for r in cur.fetchall()}


def _krx_adj_close(ticker: str, start: date, end: date) -> dict[date, float]:
    df = fetch_adj_only(ticker, start, end)
    if df.empty:
        return {}
    # fetch_adj_only 의 'close' 가 수정종가, 'date' 는 datetime.date 컬럼
    return {row.date: float(row.close) for row in df.itertuples(index=False)}


def detect_drifted_tickers(
    conn: Connection,
    *,
    as_of: date,
    rel_tol: float = 0.01,
    recent_days: int = 30,
    wide_days: int = 365,
    limit_tickers: int | None = None,
) -> list[str]:
    """활성 종목별 DB(현재, 덮어쓰기 전) vs KRX 재조회 adj_close 비교 → 드리프트 종목.

    반드시 ohlcv 증분 적재 전에 호출(증분이 adj_close 를 덮으면 비교가 일치해버림).
    종목별 fetch 예외는 로그+skip.
    """
    drifted: list[str] = []
    for t in _active_tickers(conn, limit=limit_tickers):
        try:
            recent_start = as_of - timedelta(days=recent_days)
            db = _db_adj_close(conn, t, recent_start, as_of)
            krx = _krx_adj_close(t, recent_start, as_of)
            if not (db.keys() & krx.keys()):
                wide_start = as_of - timedelta(days=wide_days)
                db = _db_adj_close(conn, t, wide_start, as_of)
                krx = _krx_adj_close(t, wide_start, as_of)
            if is_drift(db, krx, rel_tol):
                drifted.append(t)
        except Exception as e:  # noqa: BLE001 — 종목 단위 격리
            log.warning("drift detect skip %s: %s", t, e)
    log.info("drift detected: %d tickers %s", len(drifted), drifted[:20])
    return drifted


def reload_ticker(conn: Connection, ticker: str, *, as_of: date) -> dict:
    """드리프트 종목 전 기간 재적재.

    1) daily adj 재수신(fetch_adj_only) → update_adj_prices(매칭 행 adj_* 만 갱신, raw 불변)
    2) daily 시계열 지표 Phase A 전 기간 재계산
    3) 주봉 가격 재집계(weekly.run FULL_REFRESH, 그 종목만)
    4) 주봉 시계열 지표 Phase A 전 기간 재계산
    횡단면 RS 순위는 체인의 전 종목 증분/주간 실행이 최신값 확정.

    단계별 commit 이므로 3)~4) 에서 실패하면 daily 는 갱신·weekly 는 stale 인
    부분 상태가 남을 수 있다(다음 전체/주간 실행이 복구). 호출부(run_daily_chain)는
    종목 단위로 예외를 격리한다.
    """
    start = get_daily_min_date(conn) or (as_of - timedelta(days=365 * 5))
    df = fetch_adj_only(ticker, start, as_of)
    rows = [
        (ticker, row.date, float(row.close), float(row.high),
         float(row.low), float(row.open), float(row.volume))
        for row in df.itertuples(index=False)
    ]
    updated = update_adj_prices(conn, rows) if rows else 0

    r_ind_d = indicators.recompute_ticker_daily(conn, ticker)
    r_wk = weekly.run(conn, weekly.Mode.FULL_REFRESH, only_tickers=[ticker])
    r_ind_w = indicators.recompute_ticker_weekly(conn, ticker)

    return {
        "ticker": ticker,
        "adj_rows": updated,
        "indicators_daily": r_ind_d,
        "weekly": r_wk.rows_affected,
        "indicators_weekly": r_ind_w,
    }
