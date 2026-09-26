"""조정 드리프트(분할 등) 감지 + 단일종목 재적재 — #207 A안(회신 15·16) 이후 **외부 접촉 0**.

구 설계(DB adj_close vs Naver 재조회 비교·Naver 전 기간 재수신)는 Naver 원천 자격 상실(#207)로 제거.
현 설계: 조정일 = daily_prices.change_pct(KRX 등락률) 기반 판정(adjust.is_adjustment). 증분 적재(ohlcv._run_upsert)가
조정일을 기록·소급하므로 여기의 detect 는 **안전망**(창 안 미기록 조정일 스캔, DB 전용)이고 reload 는 미기록
이벤트 기록·소급 후 지표 재계산이다. 스펙: docs/superpowers/specs/2026-06-04-pipeline-integration-drift-reload-design.md §2(구),
#207 회신 15·16(현).
"""
from __future__ import annotations
import logging
from datetime import date, timedelta

from psycopg import Connection

from kr_pipeline.ohlcv import adjust
from kr_pipeline.weekly.load import load_active_tickers
from kr_pipeline.weekly import modes as weekly
from kr_pipeline.indicators import modes as indicators

log = logging.getLogger("kr_pipeline.pipeline.drift")

SWEEP_RECENT_DAYS = 90  # 토요일 스윕 비교창. ohlcv window_days(30)보다 커야 증분 창 너머 옛 구간의 미기록 조정을 잡는다.
RELOAD_LOOKBACK_DAYS = 365   # reload 시 미기록 이벤트 탐색 창


def _windows_lacking_change_pct(conn: Connection, tickers: list[str], start: date, end: date) -> list[str]:
    """창 안 행에 change_pct 가 하나도 없는 종목(등락률 미수집 = 판정 못 함) — 단일 쿼리."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.ticker FROM stocks s
             WHERE s.ticker = ANY(%s)
               AND NOT EXISTS (SELECT 1 FROM daily_prices p WHERE p.ticker = s.ticker AND p.date BETWEEN %s AND %s AND p.change_pct IS NOT NULL)
             ORDER BY 1
            """,
            (tickers, start, end),
        )
        return [r[0] for r in cur.fetchall()]


def detect_drifted_tickers(
    conn: Connection,
    *,
    as_of: date,
    recent_days: int = 30,
    tickers: list[str] | None = None,
    limit_tickers: int | None = None,
    unverified_out: list[str] | None = None,
) -> list[str]:
    """창(as_of−recent_days..as_of) 안에 change_pct 기반 조정일이 있는데 adj_factor_events 에 없는 종목(DB 전용, 접촉 0,
    set-based 단일 쿼리 adjust.detect_events_all). tickers=None 이면 활성 전 종목.
    unverified_out: 창 안 행에 change_pct 가 하나도 없어 판정 못 한 종목('이상 없음' 아님 — 등락률 미수집 구간)."""
    scan = load_active_tickers(conn, limit=limit_tickers) if tickers is None else \
        (list(tickers[:limit_tickers]) if limit_tickers else list(tickers))
    if not scan:
        return []
    since = as_of - timedelta(days=recent_days)
    unverified = _windows_lacking_change_pct(conn, scan, since, as_of)
    found = adjust.detect_events_all(conn, since=since, tickers=scan)
    drifted = sorted(t for t in found if t not in unverified)
    if unverified:
        log.warning("drift unverified: %d tickers (등락률 미수집 — '이상 없음' 아님) %s", len(unverified), unverified[:20])
    if unverified_out is not None:
        unverified_out.extend(unverified)
    log.info("drift detected: %d tickers %s", len(drifted), drifted[:20])
    return drifted


def reload_ticker(conn: Connection, ticker: str, *, as_of: date) -> dict:
    """단일 종목 재적재(접촉 0): 미기록 조정일 → adjust.ingest_events(기록·정책 소급·시임 이후 재유도) → daily Phase A
    재계산 → 주봉 가격 재집계(weekly FULL_REFRESH, 그 종목만) → weekly Phase A 재계산. 횡단면 RS 는 체인의 전 종목 실행이 확정.
    멱등. 단계별 commit(부분 상태는 다음 실행이 복구), 호출부가 종목 단위 격리.
    """
    events = adjust.detect_events(conn, ticker, since=as_of - timedelta(days=RELOAD_LOOKBACK_DAYS))
    info = adjust.ingest_events(conn, ticker, events)
    if info["recorded"]:
        log.info("reload %s: adjustment events ingested %s", ticker, info)
    conn.commit()

    r_ind_d = indicators.recompute_ticker_daily(conn, ticker)
    r_wk = weekly.run(conn, weekly.Mode.FULL_REFRESH, only_tickers=[ticker])
    r_ind_w = indicators.recompute_ticker_weekly(conn, ticker)

    return {
        "ticker": ticker,
        "adj_events": info["recorded"],
        "adj_rows": info["applied_rows"] + info["rederived_rows"],
        "indicators_daily": r_ind_d,
        "weekly": r_wk.rows_affected,
        "indicators_weekly": r_ind_w,
    }
