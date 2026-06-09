"""재실행 게이트 — as_of 기반 duplicate 판정 테스트."""
from datetime import datetime, timedelta, timezone
import json


def _seed_success_run(cur, pipeline, as_of, started, params_extra=None):
    params = {"as_of": as_of.isoformat()} if as_of is not None else (params_extra or {})
    cur.execute("INSERT INTO pipeline_runs (pipeline,mode,started_at,finished_at,status,params) "
                "VALUES (%s,'full-daily',%s,%s,'success',%s)",
                (pipeline, started, started, json.dumps(params)))


def _get_prospective(conn):
    """현재 DB 의 resolve_as_of 결과 (daily_indicators MAX date)."""
    from kr_pipeline.llm_runner.load import resolve_as_of
    return resolve_as_of(conn)


def test_different_as_of_not_duplicate(db):
    from api.services.runner_service import check_can_run_pipeline
    prospective = _get_prospective(db)
    prev = prospective - timedelta(days=1)
    with db.cursor() as cur:
        # 기존 llm_daily_delta success 행을 트랜잭션 안에서 제거 (rollback 으로 복원됨)
        cur.execute("DELETE FROM pipeline_runs WHERE pipeline='llm_daily_delta' AND status='success'")
        # prev as_of 로만 seeding — prospective 매치 없어야 can_run=True
        _seed_success_run(cur, "llm_daily_delta", prev, datetime.now(timezone.utc))
    res = check_can_run_pipeline(db, "llm-full-daily")
    assert res["can_run"] is True and res["reason"] == "ok"


def test_same_as_of_is_duplicate(db):
    from api.services.runner_service import check_can_run_pipeline
    prospective = _get_prospective(db)
    with db.cursor() as cur:
        # 기존 행 제거 후 prospective as_of 로 seeding → duplicate 확인
        cur.execute("DELETE FROM pipeline_runs WHERE pipeline='llm_daily_delta' AND status='success'")
        _seed_success_run(cur, "llm_daily_delta", prospective, datetime.now(timezone.utc))
    res = check_can_run_pipeline(db, "llm-full-daily")
    assert res["can_run"] is False and res["reason"] == "duplicate"


def test_non_asof_pipeline_keeps_wallclock_duplicate(db):
    """as_of 없는 파이프라인(ohlcv 등)은 오늘 성공 시 여전히 duplicate(레거시 보존)."""
    from api.services.runner_service import check_can_run_pipeline
    with db.cursor() as cur:
        _seed_success_run(cur, "ohlcv", None, datetime.now(timezone.utc), params_extra={"start": "2026-06-01"})
    # ohlcv pipeline_id is "ohlcv" (pipeline_db_name="ohlcv")
    res = check_can_run_pipeline(db, "ohlcv")
    assert res["can_run"] is False and res["reason"] == "duplicate"
