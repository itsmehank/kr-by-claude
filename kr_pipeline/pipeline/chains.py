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
from kr_pipeline.db.runs import run_tracking

log = logging.getLogger("kr_pipeline.pipeline.chains")


def run_daily_chain(conn: Connection, *, limit_tickers: int | None = None) -> dict:
    """평일 통합: ohlcv 증분 → indicators 일봉 증분.

    통합 자체를 pipeline="data_daily" 로 추적(runners/상세 페이지가 이 이름으로 조회).
    하위 ohlcv/indicators run() 도 각자 자기 이름으로 행을 남긴다.
    """
    with run_tracking(conn, pipeline="data_daily", mode="incremental",
                      params={"limit_tickers": limit_tickers}) as state:
        r_price = ohlcv.run(conn, ohlcv.Mode.INCREMENTAL, limit_tickers=limit_tickers)
        r_ind = indicators.run_daily(conn, indicators.Mode.INCREMENTAL, limit_tickers=limit_tickers)
        result = {
            "ohlcv": {"rows": r_price.rows_affected, "failures": len(r_price.failures)},
            "indicators_daily": {"rows": r_ind.rows_affected, "failures": len(r_ind.failures)},
        }
        state["rows_affected"] = (r_price.rows_affected or 0) + (r_ind.rows_affected or 0)
        state["details"] = result
        return result


def run_weekly_chain(conn: Connection, *, limit_tickers: int | None = None) -> dict:
    """토요일 통합: weekly 증분 → indicators 주봉 증분.

    통합 자체를 pipeline="data_weekly" 로 추적. 하위 모듈도 자기 이름으로 행을 남긴다.
    """
    with run_tracking(conn, pipeline="data_weekly", mode="incremental",
                      params={"limit_tickers": limit_tickers}) as state:
        r_price = weekly.run(conn, weekly.Mode.INCREMENTAL, limit_tickers=limit_tickers)
        r_ind = indicators.run_weekly(conn, indicators.Mode.INCREMENTAL, limit_tickers=limit_tickers)
        result = {
            "weekly": {"rows": r_price.rows_affected, "failures": len(r_price.failures)},
            "indicators_weekly": {"rows": r_ind.rows_affected, "failures": len(r_ind.failures)},
        }
        state["rows_affected"] = (r_price.rows_affected or 0) + (r_ind.rows_affected or 0)
        state["details"] = result
        return result
