"""조정 드리프트(분할 등) 감지 + 단일종목 전 기간 재적재.

detect 는 ohlcv 증분 전에 실행해야 한다(증분이 adj_close 를 덮어쓰기 전 DB vs KRX 비교).
스펙: docs/superpowers/specs/2026-06-04-pipeline-integration-drift-reload-design.md §2.
"""
from __future__ import annotations
import logging
import time
from datetime import date, timedelta

import pandas as pd
from psycopg import Connection

from kr_pipeline.ohlcv.fetch import fetch_adj_only
from kr_pipeline.ohlcv.store import update_adj_prices
from kr_pipeline.ohlcv.transform import nullify_halt_adj
from kr_pipeline.weekly.load import get_daily_min_date
from kr_pipeline.weekly import modes as weekly
from kr_pipeline.indicators import modes as indicators

log = logging.getLogger("kr_pipeline.pipeline.drift")

# 수정주가를 바꾸는 corporate action 유형 (현금배당 제외 — 수정주가 무관).
# 목록이 넉넉해도 안전: 실제 재적재 판정은 is_drift(가격 대조)가 한다.
ADJ_AFFECTING_EVENT_TYPES = (
    "stock_split", "reverse_split", "bonus_issue", "rights_offering",
    "merger", "spinoff", "capital_reduction",
)

CA_LOOKBACK_DAYS = 90   # 평일 후보: 최근 N일 공시. 결정→권리락 간격(수 주) 흡수.
SWEEP_RECENT_DAYS = 90  # 토요일 스윕 비교창. ohlcv window_days(30)보다 커야
                        # 증분이 덮은 최근 구간 너머 옛 구간에서 놓친 split 을 잡는다.


def recent_corp_action_tickers(conn: Connection, *, as_of: date, lookback_days: int) -> list[str]:
    """corporate_actions 에 [as_of-lookback, as_of] 영향 이벤트가 있는 활성 종목(distinct).

    event_type 가 ADJ_AFFECTING_EVENT_TYPES 이고 상장 유지(delisted_at IS NULL)인 종목만.
    인덱스 idx_corp_actions_event_type_date(event_type, event_date) 활용.
    """
    since = as_of - timedelta(days=lookback_days)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ca.ticker FROM corporate_actions ca "
            "JOIN stocks s ON s.ticker = ca.ticker "
            "WHERE ca.event_type = ANY(%s) AND ca.event_date BETWEEN %s AND %s "
            "AND s.delisted_at IS NULL "
            "ORDER BY ca.ticker",
            (list(ADJ_AFFECTING_EVENT_TYPES), since, as_of),
        )
        return [r[0] for r in cur.fetchall()]


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
    tickers: list[str] | None = None,
    limit_tickers: int | None = None,
    unverified_out: list[str] | None = None,
    sleep_s: float = 0.1,
) -> list[str]:
    """활성 종목별 DB(현재, 덮어쓰기 전) vs KRX 재조회 adj_close 비교 → 드리프트 종목.

    tickers=None 이면 활성 전 종목(전체스윕). tickers 가 리스트면 그 목록만 검사
    (빈 리스트 = 검사 0건, 전 종목 아님). 반드시 ohlcv 증분 적재 전에 호출.

    unverified_out (P1-5 C): '검증 못 함' 을 '이상 없음' 과 구분하는 계정 —
    wide 확대 후에도 비교 겹침이 없거나(KRX 빈 응답 등) 재시도 소진 예외로
    skip 된 종목을 담는다. 기존엔 둘 다 조용히 False(드리프트 없음) 취급이라
    놓친 split 이 무경고 통과했다. None 이면 기존 반환 계약 그대로(비파괴).

    sleep_s: 종목 간 대기 — 전체스윕(~2,550종목)이 무-sleep 직렬 호출로 스스로
    throttle 을 유발하지 않게. _run_full_refresh 의 0.1s 선례. 테스트는 0.
    """
    if tickers is None:
        scan = _active_tickers(conn, limit=limit_tickers)
    else:
        scan = list(tickers[:limit_tickers]) if limit_tickers else list(tickers)
    drifted: list[str] = []
    unverified: list[str] = []
    for t in scan:
        try:
            recent_start = as_of - timedelta(days=recent_days)
            db = _db_adj_close(conn, t, recent_start, as_of)
            krx = _krx_adj_close(t, recent_start, as_of)
            if not (db.keys() & krx.keys()):
                wide_start = as_of - timedelta(days=wide_days)
                db = _db_adj_close(conn, t, wide_start, as_of)
                krx = _krx_adj_close(t, wide_start, as_of)
            if not (db.keys() & krx.keys()):
                unverified.append(t)
            elif is_drift(db, krx, rel_tol):
                drifted.append(t)
        except Exception as e:  # noqa: BLE001 — 종목 단위 격리
            unverified.append(t)
            log.warning("drift detect skip %s: %s", t, e)
        finally:
            if sleep_s:
                time.sleep(sleep_s)
    if unverified:
        log.warning("drift unverified: %d tickers (빈 재조회/예외 — '이상 없음' 아님) %s",
                    len(unverified), unverified[:20])
    if unverified_out is not None:
        unverified_out.extend(unverified)
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
    # 단일 chokepoint 경유 — adj-refresh(_run_full_refresh._process_ticker) 와 동일하게
    # 거래정지일 adj_* 를 NULL 화. fetch_adj_only 컬럼(open/high/low/close/volume=수정값)을
    # adj_* 로 매핑 후 nullify_halt_adj. 이를 빠뜨리면 halt 행이 0 으로 적재돼 w52_low=0 재오염.
    if not df.empty:
        df = df.rename(columns={"close": "adj_close", "high": "adj_high", "low": "adj_low",
                                "open": "adj_open", "volume": "adj_volume"})
        df = nullify_halt_adj(df)

    def _n(v):
        return None if pd.isna(v) else float(v)
    rows = [
        (ticker, r["date"], _n(r["adj_close"]), _n(r["adj_high"]), _n(r["adj_low"]),
         _n(r["adj_open"]), _n(r["adj_volume"]))
        for _, r in df.iterrows()
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
