from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from pydantic import BaseModel

from api.deps import get_conn
from api.services.runner_service import (
    check_can_run_pipeline,
    spawn_pipeline,
)


router = APIRouter(prefix="/api/runner", tags=["runner"])


class RunRequest(BaseModel):
    pipeline_id: str
    mode_id: str = "default"
    force: bool = False


@router.post("/run")
def run(req: RunRequest, conn: Connection = Depends(get_conn)):
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
                    else "오늘 같은 작업이 이미 성공 실행되었습니다. force=true 로 재실행 가능."
                ),
            },
        )

    try:
        spawn_result = spawn_pipeline(req.pipeline_id, req.mode_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "pipeline_id": req.pipeline_id,
        "mode_id": req.mode_id,
        "pid": spawn_result["pid"],
        "command": spawn_result["command"],
    }
