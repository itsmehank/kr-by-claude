"""데이터 파이프라인 통합 체인 — 가격→지표 순서 보장.

통합 A(daily): ohlcv 증분(raw+자체 계수, 조정일 기록·소급) → drift 안전망(DB) → (조정 종목 재계산) → indicators 일봉 증분
통합 B(weekly): (전체스윕 드리프트) → weekly 증분 → indicators 주봉 증분 → 주봉 게이트 daily 미러(#203)
기존 모듈 run() 을 순서대로 호출(무수정).
"""
from __future__ import annotations
import logging
from datetime import date
from psycopg import Connection

from kr_pipeline.ohlcv import modes as ohlcv
from kr_pipeline.weekly import modes as weekly
from kr_pipeline.indicators import modes as indicators
from kr_pipeline.llm_runner import load as llm_load
from kr_pipeline.db.runs import run_tracking
from kr_pipeline.pipeline import drift

log = logging.getLogger("kr_pipeline.pipeline.chains")


def _rollback(conn) -> None:
    conn.rollback()


def run_daily_chain(conn: Connection, *, drift_check: bool = True, limit_tickers: int | None = None) -> dict:
    """평일 통합(#207 A안): ohlcv 증분(raw + 자체 계수 — 조정일 기록·소급) → drift 안전망 스캔(DB, 접촉 0)
    → reload(조정 종목 지표 재계산) → indicators 일봉 증분.

    구 순서(detect 가 증분 '전')는 Naver 비교 전제였다 — 제거. 통합 자체를 pipeline="data_daily" 로 추적.
    """
    with run_tracking(conn, pipeline="data_daily", mode="incremental",
                      params={"limit_tickers": limit_tickers, "drift": drift_check}) as state:
        as_of = date.today()
        r_price = ohlcv.run(conn, ohlcv.Mode.INCREMENTAL, limit_tickers=limit_tickers)

        drifted: list[str] = list(r_price.adjusted_tickers)
        drift_unverified: list[str] = []
        if drift_check:
            extra = drift.detect_drifted_tickers(
                conn, as_of=as_of, limit_tickers=limit_tickers, unverified_out=drift_unverified)
            drifted += [t for t in extra if t not in drifted]
            if drift_unverified:
                state["warnings"].append(
                    f"drift_unverified: {len(drift_unverified)} 종목 검증 못 함"
                    f"(등락률 미수집/예외 — '이상 없음' 아님): {drift_unverified[:20]}")

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


def _mirror_gate_with_diff(conn: Connection, *, as_of: date) -> dict:
    """#203: 주봉 게이트 daily 미러(indicators.mirror_daily_rs_gate) 전후로 LLM 후보 집합(라이브 필터 그대로)을
    비교해 구 게이트 대비 차분을 붙인다 — 수정 후 첫 주말 실행의 차분 1회 기록 요구. 후보 조회는 LLM 층
    (llm_runner.load) 몫이므로 미러 함수가 아닌 이 오케스트레이션 층에서 호출한다.
    실패 정책 = fail-closed(예외 전파 → data_weekly failed → weekend_chain.sh 가 LLM 선별을 중단): 미러 없이
    선별하면 #203 결함(직전 주 게이트)이 그대로 재현되므로 조용히 계속하지 않는다.
    """
    before = {r["symbol"] for r in llm_load.get_qualifying_tickers(conn, as_of=as_of)}
    info = indicators.mirror_daily_rs_gate(conn, as_of=as_of)
    after = {r["symbol"] for r in llm_load.get_qualifying_tickers(conn, as_of=as_of)}
    info.update({
        "candidates_before": len(before),
        "candidates_after": len(after),
        "added": sorted(after - before),
        "removed": sorted(before - after),
    })
    return info


def run_weekly_chain(conn: Connection, *, limit_tickers: int | None = None, full_sweep: bool = True) -> dict:
    """토요일 통합: (전체스윕 drift) → weekly 증분 → indicators 주봉 증분 → 주봉 게이트 daily 미러(#203,
    daily_indicators.rs_line_not_declining_7m 기록 + 후보 차분 details).

    full_sweep(#207 A안 이후 접촉 0): 전 종목을 넓은 창(SWEEP_RECENT_DAYS)으로 DB 스캔해 미기록 조정일을
    잡는 안전망 — 평일 증분 창(30일) 너머 구간. 종목 단위 예외 격리(평일 체인과 동일). 통합 자체를
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
        # #203: 주봉 게이트 → daily 미러(Phase D 동일)를 여기서 1회 — LLM 주말 선별(weekend_chain.sh 2단계)이
        # daily 미러 컬럼을 읽으므로, 이 단계 없이는 토요일 후보가 직전 주 게이트로 뽑힌다(09-19 실증 61 vs 66).
        mirror = _mirror_gate_with_diff(conn, as_of=as_of)
        result = {
            "sweep": {"detected": len(swept), "reloaded": sweep_reloaded,
                      "failures": sweep_failures, "unverified": len(sweep_unverified)},
            "weekly": {"rows": r_price.rows_affected, "failures": len(r_price.failures)},
            "indicators_weekly": {"rows": r_ind.rows_affected, "failures": len(r_ind.failures)},
            "daily_rs_gate_mirror": mirror,
        }
        state["rows_affected"] = (r_price.rows_affected or 0) + (r_ind.rows_affected or 0)
        state["details"] = result
        return result
