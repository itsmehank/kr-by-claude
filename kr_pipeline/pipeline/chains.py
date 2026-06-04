"""데이터 파이프라인 통합 체인 — 가격→지표 순서 보장.

통합 A(daily): (드리프트 감지) → ohlcv 증분 → (감지 종목 재적재) → indicators 일봉 증분
통합 B(weekly): weekly 증분 → indicators 주봉 증분
기존 모듈 run() 을 순서대로 호출(무수정).
"""
from __future__ import annotations
import logging
from datetime import date
from psycopg import Connection

from kr_pipeline.ohlcv import modes as ohlcv
from kr_pipeline.weekly import modes as weekly
from kr_pipeline.indicators import modes as indicators
from kr_pipeline.db.runs import run_tracking
from kr_pipeline.pipeline import drift

log = logging.getLogger("kr_pipeline.pipeline.chains")


def _rollback(conn) -> None:
    conn.rollback()


def run_daily_chain(conn: Connection, *, drift_check: bool = True, limit_tickers: int | None = None) -> dict:
    """평일 통합: (드리프트 감지) → ohlcv 증분 → (감지 종목 재적재) → indicators 일봉 증분.

    드리프트 감지는 ohlcv 증분 '전에' 실행(증분이 adj_close 덮어쓰기 전 비교). 스펙 §1/§2.
    통합 자체를 pipeline="data_daily" 로 추적. 하위 모듈도 각자 자기 이름으로 행을 남긴다.
    """
    with run_tracking(conn, pipeline="data_daily", mode="incremental",
                      params={"limit_tickers": limit_tickers, "drift": drift_check}) as state:
        as_of = date.today()
        drifted: list[str] = []
        if drift_check:
            drifted = drift.detect_drifted_tickers(conn, as_of=as_of, limit_tickers=limit_tickers)

        r_price = ohlcv.run(conn, ohlcv.Mode.INCREMENTAL, limit_tickers=limit_tickers)

        reloaded, reload_failures = 0, 0
        for t in drifted:
            try:
                drift.reload_ticker(conn, t, as_of=as_of)
                reloaded += 1
            except Exception as e:  # noqa: BLE001 — 종목 단위 격리
                reload_failures += 1
                _rollback(conn)
                log.warning("drift reload failed %s: %s", t, e)

        r_ind = indicators.run_daily(conn, indicators.Mode.INCREMENTAL, limit_tickers=limit_tickers)

        result = {
            "drift": {"detected": len(drifted), "reloaded": reloaded,
                      "failures": reload_failures, "tickers": drifted},
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
