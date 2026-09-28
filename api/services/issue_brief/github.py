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
    state: str  # open | closed | unknown  (PR 은 MERGED/CLOSED → closed, OPEN → open)
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


def gh_available(run=subprocess.run) -> tuple[bool, str]:
    """gh 설치·로그인 사전 검사(`gh auth status`). (ok, detail)."""
    try:
        _run_gh(["auth", "status"], run)
    except GhUnavailable as e:
        return False, str(e)
    return True, ""


def _norm_state(raw: str | None) -> str:
    st = (raw or "").lower()
    if st == "merged":
        return "closed"
    return st if st in ("open", "closed") else "unknown"


def get_ref_states(numbers: set[int], run=subprocess.run) -> dict[int, RefState]:
    """참조 번호들의 상태를 배치 조회 — 이슈 전체 + PR 전체 목록 2콜(번호별 view 반복 대신).

    gh 는 PR 번호도 `issue view` 로 응답하므로(state MERGED) 이슈/PR 을 함께 조회해 정규화한다.
    목록에 없는 번호는 'unknown'. gh 실패는 GhUnavailable 전파(회차 중단 — 부분 결과로 해시가
    흔들리지 않게).
    """
    if not numbers:
        return {}
    found: dict[int, RefState] = {}
    for sub in ("issue", "pr"):
        out = _run_gh([sub, "list", "--state", "all", "--limit", "1000",
                       "--json", "number,state,title"], run)
        for r in json.loads(out or "[]"):
            n = int(r["number"])
            if n in numbers and n not in found:
                found[n] = RefState(n, _norm_state(r.get("state")), r.get("title") or "")
    return {n: found.get(n, RefState(n, "unknown", "")) for n in numbers}
