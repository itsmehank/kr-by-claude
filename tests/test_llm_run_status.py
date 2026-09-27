"""#201 — LLM 러너 fail-soft 상태 표기 결함(판정 09-27 회신 17 Q-3 A).
발단: 2026-09-19 weekend run 1979 — 후보 61 전량 실패(`Exec format error: 'claude'`, processed 0·failures 61)인데 status=success
→ 결손 주가 미탐지. 사양: failed = **성공 행 0**(processed 0 이면서 시도 ≥1). 부분 실패 임계 신설 금지(warnings 집계 유지).
failed 시 후속 체인 중단(비-0 종료) + 알림(watch_pipelines failed 감시). run_tracking 은 실패 시에도 details(failed_tickers) 보존."""
from datetime import date

import pytest

from kr_pipeline.llm_runner.run_status import AllAttemptsFailedError, check_all_failed


def test_all_attempts_failed_raises():
    r = {"processed": 0, "candidates": 61, "failures": 61, "failed_tickers": [{"symbol": "001210", "error": "Exec format error", "attempts": 1}] * 61}
    with pytest.raises(AllAttemptsFailedError, match="61/61"):
        check_all_failed(r, mode="weekend")


def test_partial_failure_is_not_failed():
    check_all_failed({"processed": 60, "candidates": 61, "failures": 1, "failed_tickers": [{"symbol": "159010"}]}, mode="weekend")


def test_zero_candidates_or_non_llm_result_is_not_failed():
    check_all_failed({"processed": 0, "candidates": 0, "failures": 0, "failed_tickers": []}, mode="weekend")   # 할 일 없음
    check_all_failed({"rows_affected": 3}, mode="performance")                                              # 키 없음 → 판정 안 함
    check_all_failed({}, mode="entry")


def test_run_tracking_failure_keeps_details(db):
    """예외로 failed 기록될 때 state['details'](failed_tickers 등)가 사라지지 않는다 — 결손 원인 추적용."""
    from kr_pipeline.db.runs import run_tracking
    with pytest.raises(RuntimeError):
        with run_tracking(db, pipeline="llm_weekend", mode="weekend", params={}) as state:
            state["details"] = {"processed": 0, "failures": 2, "failed_tickers": [{"symbol": "A"}, {"symbol": "B"}]}
            state["warnings"].append("w1")
            raise RuntimeError("all failed 2/2")
    with db.cursor() as cur:
        cur.execute("SELECT status, error, details->>'failures', details->'failed_tickers'->0->>'symbol' FROM pipeline_runs WHERE id = %s", (state["run_id"],))
        st, err, nf, sym = cur.fetchone()
    assert st == "failed" and "all failed 2/2" in err and nf == "2" and sym == "A"


def test_full_daily_nested_stage_all_failed_raises():
    """full-daily 는 단계별 결과가 중첩 — 한 단계(예: daily_delta)가 전량 실패면 failed."""
    r = {"disqualify": {"processed": 3}, "daily_delta": {"processed": 0, "failures": 7, "failed_tickers": [{}] * 7},
         "evaluate": {"processed": 2, "failures": 0}, "entry": {}, "performance": {"rows_affected": 1}}
    with pytest.raises(AllAttemptsFailedError, match="full-daily/daily_delta"):
        check_all_failed(r, mode="full-daily")
    check_all_failed({**r, "daily_delta": {"processed": 5, "failures": 2}}, mode="full-daily")
