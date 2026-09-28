"""(2026-09-28) GitHub 이슈 쉬운 요약 캐시 API. spec: docs/superpowers/specs/2026-09-28-issues-page-design.md"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from psycopg import Connection
from pydantic import BaseModel, Field

from api.deps import get_conn
from api.services.issue_brief import refresh as refresh_mod
from api.services.issue_brief.github import gh_available
from api.services.issue_brief.refresh import is_running, request_cancel, start_refresh
from api.services.issue_brief.store import fetch_briefs, fetch_closed_numbers, set_override

router = APIRouter(prefix="/api/issues", tags=["issues"])


class OverrideBody(BaseModel):
    status: Literal["ready", "decision", "blocked"] | None = None
    note: str | None = Field(default=None, max_length=500)


@router.get("")
def list_issues(conn: Connection = Depends(get_conn)):
    items = fetch_briefs(conn, only_open=True)
    updated_at = max((i["observed_at"] for i in items if i["observed_at"]), default=None)
    # closed_numbers: 의존 칩을 열림/닫힘/미확인 3값으로 그리기 위한 캐시의 closed 번호 목록
    return {"updated_at": updated_at, "items": items, "closed_numbers": fetch_closed_numbers(conn)}


@router.get("/refresh")
def refresh_status():
    return refresh_mod.STATE.to_dict()


@router.post("/refresh")
def refresh_start():
    # 락 확인을 gh 프로브보다 먼저 — 실행 중 클릭이 네트워크 프로브(최대 60초)에 막히지 않게
    if is_running():
        return JSONResponse(status_code=409, content={"reason": "already_running"})
    ok, detail = gh_available()          # 설치 + 로그인(`gh auth status`) 동기 사전 검사
    if not ok:
        return JSONResponse(status_code=503, content={"reason": "gh_unavailable", "detail": detail})
    if not start_refresh():
        return JSONResponse(status_code=409, content={"reason": "already_running"})
    return JSONResponse(status_code=202, content={"started": True})


@router.delete("/refresh")
def refresh_cancel():
    """진행 중 회차 취소 요청 — 다음 이슈 경계에서 중단(진행 중 claude 호출은 끝까지 기다림)."""
    if not request_cancel():
        return JSONResponse(status_code=409, content={"reason": "not_running"})
    return JSONResponse(status_code=202, content={"cancel_requested": True})


@router.put("/{number}/override")
def put_override(number: int, body: OverrideBody, conn: Connection = Depends(get_conn)):
    row = set_override(conn, number, body.status, body.note)
    if row is None:
        return JSONResponse(status_code=404, content={"detail": "issue not cached"})
    return row
