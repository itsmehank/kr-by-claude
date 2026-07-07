"""데이터 파이프라인 통합 체인 — 가격→지표 순서 보장.

통합 A(daily): (공시 후보 드리프트 감지) → ohlcv 증분 → (감지 종목 재적재) → indicators 일봉 증분
통합 B(weekly): (전체스윕 드리프트) → weekly 증분 → indicators 주봉 증분
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
        drift_unverified: list[str] = []
        if drift_check:
            candidates = drift.recent_corp_action_tickers(
                conn, as_of=as_of, lookback_days=drift.CA_LOOKBACK_DAYS)
            drifted = drift.detect_drifted_tickers(
                conn, as_of=as_of, tickers=candidates, limit_tickers=limit_tickers,
                unverified_out=drift_unverified)
            if drift_unverified:
                state["warnings"].append(
                    f"drift_unverified: {len(drift_unverified)} 종목 검증 못 함"
                    f"(빈 재조회/예외 — '이상 없음' 아님): {drift_unverified[:20]}")

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
                      "failures": reload_failures, "tickers": drifted,
                      "unverified": len(drift_unverified)},
            "ohlcv": {"rows": r_price.rows_affected, "failures": len(r_price.failures)},
            "indicators_daily": {"rows": r_ind.rows_affected, "failures": len(r_ind.failures)},
        }
        state["rows_affected"] = (r_price.rows_affected or 0) + (r_ind.rows_affected or 0)
        state["details"] = result
        return result


def run_weekly_chain(conn: Connection, *, limit_tickers: int | None = None, full_sweep: bool = True) -> dict:
    """토요일 통합: (전체스윕 drift) → weekly 증분 → indicators 주봉 증분.

    full_sweep: corporate_actions 가 놓친 드리프트를 잡는 안전망. 전 종목을 넓은
    비교창(SWEEP_RECENT_DAYS)으로 검사 — 평일 증분이 덮은 최근 구간 너머 옛 구간에서
    놓친 split 을 포착. 종목 단위 예외 격리(평일 체인과 동일). 통합 자체를
    pipeline="data_weekly" 로 추적.
    """
    with run_tracking(conn, pipeline="data_weekly", mode="incremental",
                      params={"limit_tickers": limit_tickers, "full_sweep": full_sweep}) as state:
        as_of = date.today()
        swept: list[str] = []
        sweep_unverified: list[str] = []
        sweep_reloaded, sweep_failures = 0, 0
        if full_sweep:
            swept = drift.detect_drifted_tickers(
                conn, as_of=as_of, tickers=None,
                recent_days=drift.SWEEP_RECENT_DAYS, limit_tickers=limit_tickers,
                unverified_out=sweep_unverified)
            if sweep_unverified:
                state["warnings"].append(
                    f"sweep_unverified: {len(sweep_unverified)} 종목 검증 못 함"
                    f"(빈 재조회/예외 — '이상 없음' 아님): {sweep_unverified[:20]}")
            for t in swept:
                try:
                    drift.reload_ticker(conn, t, as_of=as_of)
                    sweep_reloaded += 1
                except Exception as e:  # noqa: BLE001 — 종목 단위 격리
                    sweep_failures += 1
                    _rollback(conn)
                    log.warning("weekly sweep reload failed %s: %s", t, e)

        r_price = weekly.run(conn, weekly.Mode.INCREMENTAL, limit_tickers=limit_tickers,
                             check_freshness=True)  # 일봉 stale 시 부분 주봉 방지(fail-closed)
        r_ind = indicators.run_weekly(conn, indicators.Mode.INCREMENTAL, limit_tickers=limit_tickers)
        result = {
            "sweep": {"detected": len(swept), "reloaded": sweep_reloaded,
                      "failures": sweep_failures, "unverified": len(sweep_unverified)},
            "weekly": {"rows": r_price.rows_affected, "failures": len(r_price.failures)},
            "indicators_weekly": {"rows": r_ind.rows_affected, "failures": len(r_ind.failures)},
        }
        state["rows_affected"] = (r_price.rows_affected or 0) + (r_ind.rows_affected or 0)
        state["details"] = result
        return result
