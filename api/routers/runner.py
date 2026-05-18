from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from pydantic import BaseModel

from api.deps import get_conn
from api.services.runner_service import (
    MODE_TO_PIPELINE,
    check_can_run,
    spawn_runner,
)


router = APIRouter(prefix="/api/runner", tags=["runner"])


class RunRequest(BaseModel):
    mode: str
    dry_run: bool = True
    limit: int | None = None
    ticker: str | None = None
    force: bool = False


@router.post("/run")
def run(req: RunRequest, conn: Connection = Depends(get_conn)):
    if req.mode not in MODE_TO_PIPELINE:
        raise HTTPException(400, f"unknown mode: {req.mode}")

    check = check_can_run(conn, req.mode, force=req.force)
    if not check["can_run"]:
        raise HTTPException(
            409,
            detail={
                "reason": check["reason"],
                "existing_run_id": check["existing_run_id"],
                "existing_run_summary": check.get("existing_run_summary"),
                "message": (
                    "이미 실행 중입니다."
                    if check["reason"] == "already_running"
                    else "오늘 같은 모드가 이미 성공 실행되었습니다. force=true 로 재실행 가능."
                ),
            },
        )

    spawn_result = spawn_runner(
        mode=req.mode,
        dry_run=req.dry_run,
        limit=req.limit,
        ticker=req.ticker,
    )
    return {
        "mode": req.mode,
        "dry_run": req.dry_run,
        "pid": spawn_result["pid"],
        "command": spawn_result["command"],
    }
