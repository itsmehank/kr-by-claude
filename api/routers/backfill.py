"""(#242) #110 확장 백필 제어 — 웹 스위치는 backfill_control 값만 바꾼다(cron/launchd 등록 금지, #86).

미열람 보존: 노출 값은 건수·모델 종수·트립와이어뿐 — 분류 결과(verdict 분포·수익률)는 내지 않는다.
"""
from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from pydantic import BaseModel

from api.deps import get_conn
from kr_pipeline.backtest import bt110

router = APIRouter(prefix="/api/backfill", tags=["backfill"])


class SwitchRequest(BaseModel):
    enabled: bool
    note: str | None = None


@router.get("/bt110/status")
def bt110_status(conn: Connection = Depends(get_conn)):
    return bt110.status(conn)


@router.post("/bt110/switch")
def bt110_switch(req: SwitchRequest, conn: Connection = Depends(get_conn)):
    """on: 스냅샷 없으면 셀·기준선 1회 동결. off: enabled 만 false(진행 중 패스는 데드라인까지 계속)."""
    try:
        ctl = bt110.set_switch(conn, req.enabled, note=req.note)
    except Exception as e:  # noqa: BLE001 — DB 오류를 500 으로 그대로
        raise HTTPException(500, str(e))
    return {"enabled": ctl["enabled"], "cells_count": len(ctl.get("cells") or []),
            "switched_at": ctl["switched_at"], "baseline": ctl.get("baseline")}
