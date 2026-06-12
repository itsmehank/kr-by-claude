from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from pydantic import BaseModel

from api.deps import get_conn
from api.services.runner_service import (
    check_can_run_pipeline,
    spawn_pipeline,
    wait_for_run_registration,
)


router = APIRouter(prefix="/api/runner", tags=["runner"])


class RunRequest(BaseModel):
    pipeline_id: str
    mode_id: str = "default"
    force: bool = False
    params: dict | None = None


@router.post("/run")
def run(req: RunRequest, conn: Connection = Depends(get_conn)):
    # check(SELECT)→spawn(Popen) 사이 TOCTOU 차단: 더블클릭 동시 요청 2건이
    # 모두 check 를 통과해 같은 파이프라인이 2개 돌 수 있다. 요청 트랜잭션
    # 동안 유지되는 advisory xact lock 으로 check+spawn 을 직렬화.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_try_advisory_xact_lock(hashtext('runner:' || %s)::bigint)",
            (req.pipeline_id,),
        )
        if not cur.fetchone()[0]:
            raise HTTPException(
                409,
                detail={
                    "reason": "concurrent_request",
                    "existing_run_id": None,
                    "existing_run_summary": None,
                    "message": "같은 파이프라인의 다른 실행 요청이 처리 중입니다. 잠시 후 다시 시도하세요.",
                },
            )

    check = check_can_run_pipeline(conn, req.pipeline_id, force=req.force)
    if not check["can_run"]:
        raise HTTPException(
            409,
            detail={
                "reason": check["reason"],
                "existing_run_id": check.get("existing_run_id"),
                "existing_run_summary": check.get("existing_run_summary"),
                "message": (
                    "이미 실행 중입니다."
                    if check["reason"] == "already_running"
                    else "같은 데이터 날짜(as_of)의 작업이 이미 성공 실행되었습니다. force=true 로 재실행 가능."
                ),
            },
        )

    try:
        spawn_result = spawn_pipeline(req.pipeline_id, req.mode_id, params=req.params, force=req.force)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # 자식의 run 행 등록을 짧게 대기 — 즉사 가시화 + (advisory lock 보유 중이라)
    # spawn 직후 boot window 의 이중 실행 틈새 축소. timeout 은 fail-open.
    wait = wait_for_run_registration(conn, req.pipeline_id, spawn_result["proc"])
    if wait["status"] == "died":
        raise HTTPException(
            502,
            detail={
                "reason": "spawn_failed",
                "existing_run_id": None,
                "existing_run_summary": None,
                "message": (
                    f"파이프라인 프로세스가 실행 등록 전에 종료됐습니다 (exit {wait['returncode']}). "
                    "~/.kr-by-claude/cron.log 를 확인하세요."
                ),
            },
        )

    return {
        "pipeline_id": req.pipeline_id,
        "mode_id": req.mode_id,
        "pid": spawn_result["pid"],
        "command": spawn_result["command"],
    }
