"""데이터 파이프라인 통합 체인 — 가격→지표 순서 보장.

통합 A(daily): ohlcv 증분 → indicators 일봉 증분
통합 B(weekly): weekly 증분 → indicators 주봉 증분
기존 모듈 run() 을 순서대로 호출(무수정). 드리프트 자동 재적재는 P1b.
"""
from __future__ import annotations
import logging
from psycopg import Connection

from kr_pipeline.ohlcv import modes as ohlcv
from kr_pipeline.weekly import modes as weekly
from kr_pipeline.indicators import modes as indicators

log = logging.getLogger("kr_pipeline.pipeline.chains")


def run_daily_chain(conn: Connection, *, limit_tickers: int | None = None) -> dict:
    """평일 통합: ohlcv 증분 → indicators 일봉 증분."""
    r_price = ohlcv.run(conn, ohlcv.Mode.INCREMENTAL, limit_tickers=limit_tickers)
    r_ind = indicators.run_daily(conn, indicators.Mode.INCREMENTAL, limit_tickers=limit_tickers)
    return {
        "ohlcv": {"rows": r_price.rows_affected, "failures": len(r_price.failures)},
        "indicators_daily": {"rows": r_ind.rows_affected, "failures": len(r_ind.failures)},
    }


def run_weekly_chain(conn: Connection, *, limit_tickers: int | None = None) -> dict:
    """토요일 통합: weekly 증분 → indicators 주봉 증분."""
    r_price = weekly.run(conn, weekly.Mode.INCREMENTAL, limit_tickers=limit_tickers)
    r_ind = indicators.run_weekly(conn, indicators.Mode.INCREMENTAL, limit_tickers=limit_tickers)
    return {
        "weekly": {"rows": r_price.rows_affected, "failures": len(r_price.failures)},
        "indicators_weekly": {"rows": r_ind.rows_affected, "failures": len(r_ind.failures)},
    }
