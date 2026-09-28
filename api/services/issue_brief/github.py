"""gh CLI 래퍼 — open 이슈 목록·참조 이슈 상태. GitHub 쓰기 없음.

subprocess 는 `run` 인자로 주입(테스트는 가짜 run). gh 미설치·미로그인·비정상 종료는
GhUnavailable 로 승격해 라우터가 503 으로 바꾼다.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

GH_TIMEOUT_SECONDS = 60
GH_LIST_LIMIT = 200


class GhUnavailable(RuntimeError):
    """gh 실행 불가(미설치·미로그인·비정상 종료)."""


@dataclass(frozen=True)
class IssueComment:
    body: str
    created_at: str


@dataclass(frozen=True)
class IssueRaw:
    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    updated_at: str
    comments: tuple[IssueComment, ...]


@dataclass(frozen=True)
class RefState:
    number: int
    state: str  # open | closed | pr | unknown
    title: str


def _run_gh(args: list[str], run) -> str:
    cmd = ["gh", *args]
    try:
        res = run(cmd, capture_output=True, text=True, timeout=GH_TIMEOUT_SECONDS)
    except FileNotFoundError as e:
        raise GhUnavailable("gh CLI not found") from e
    except subprocess.TimeoutExpired as e:
        raise GhUnavailable(f"gh timeout: {' '.join(cmd)}") from e
    if res.returncode != 0:
        raise GhUnavailable((res.stderr or res.stdout or "gh failed").strip())
    return res.stdout


def list_open_issues(run=subprocess.run) -> list[IssueRaw]:
    out = _run_gh(
        ["issue", "list", "--state", "open", "--limit", str(GH_LIST_LIMIT),
         "--json", "number,title,body,labels,updatedAt,comments"],
        run,
    )
    rows = json.loads(out or "[]")
    issues: list[IssueRaw] = []
    for r in rows:
        issues.append(IssueRaw(
            number=int(r["number"]),
            title=r.get("title") or "",
            body=r.get("body") or "",
            labels=tuple(l["name"] for l in (r.get("labels") or [])),
            updated_at=r.get("updatedAt") or "",
            comments=tuple(
                IssueComment(body=c.get("body") or "", created_at=c.get("createdAt") or "")
                for c in (r.get("comments") or [])
            ),
        ))
    return issues


def get_ref_state(number: int, run=subprocess.run) -> RefState:
    """참조 이슈 상태. PR 번호면 'pr', 그 외 실패는 'unknown'(예외 아님 — 한 이슈 조회
    실패가 회차 전체를 멈추지 않게)."""
    try:
        out = _run_gh(["issue", "view", str(number), "--json", "number,state,title"], run)
    except GhUnavailable as e:
        msg = str(e).lower()
        if "pull request" in msg:
            return RefState(number, "pr", "")
        return RefState(number, "unknown", "")
    d = json.loads(out)
    return RefState(number, (d.get("state") or "unknown").lower(), d.get("title") or "")
