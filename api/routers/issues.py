"""(2026-09-28) GitHub 이슈 쉬운 요약 캐시 API. spec: docs/superpowers/specs/2026-09-28-issues-page-design.md"""
from __future__ import annotations

import shutil
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from psycopg import Connection
from pydantic import BaseModel, Field

from api.deps import get_conn
from api.services.issue_brief import refresh as refresh_mod
from api.services.issue_brief.refresh import start_refresh
from api.services.issue_brief.store import fetch_briefs, set_override

router = APIRouter(prefix="/api/issues", tags=["issues"])


def _gh_available() -> bool:
    return shutil.which("gh") is not None


class OverrideBody(BaseModel):
    status: Literal["ready", "decision", "blocked"] | None = None
    note: str | None = Field(default=None, max_length=500)


@router.get("")
def list_issues(conn: Connection = Depends(get_conn)):
    items = fetch_briefs(conn, only_open=True)
    updated_at = max((i["observed_at"] for i in items if i["observed_at"]), default=None)
    return {"updated_at": updated_at, "items": items}


@router.get("/refresh")
def refresh_status():
    return refresh_mod.STATE.to_dict()


@router.post("/refresh")
def refresh_start():
    if not _gh_available():
        return JSONResponse(status_code=503,
                            content={"reason": "gh_unavailable", "detail": "gh CLI not found in PATH"})
    if not start_refresh():
        return JSONResponse(status_code=409, content={"reason": "already_running"})
    return JSONResponse(status_code=202, content={"started": True})


@router.put("/{number}/override")
def put_override(number: int, body: OverrideBody, conn: Connection = Depends(get_conn)):
    row = set_override(conn, number, body.status, body.note)
    if row is None:
        return JSONResponse(status_code=404, content={"detail": "issue not cached"})
    return row
