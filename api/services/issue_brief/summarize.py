"""이슈 1건 → Brief. call_claude 는 주입 가능(테스트는 가짜). 스키마 불일치 1회 재호출."""
from __future__ import annotations

from typing import Callable, Literal

from pydantic import BaseModel, Field, ValidationError

from kr_pipeline.llm_runner.llm.claude_cli import call_claude

from .github import IssueRaw, RefState

PROMPT_FILE = "issue_brief_v1.md"
BODY_MAX = 6000
COMMENT_MAX = 1500
COMMENT_KEEP = 5
CALL_TIMEOUT_SECONDS = 180

Group = Literal["data", "book", "trading_ui", "validation", "ops"]
StartStatus = Literal["ready", "decision", "blocked"]


class Brief(BaseModel):
    summary: str = Field(min_length=1, max_length=120)
    group: Group
    start_status: StartStatus
    start_reason: str = Field(min_length=1, max_length=160)
    depends_on: list[int] = Field(default_factory=list)


class SummarizeFailed(RuntimeError):
    """재호출 후에도 스키마 불일치."""


def _pick_comments(raw: IssueRaw) -> list[dict]:
    cs = list(raw.comments)
    if len(cs) > COMMENT_KEEP:
        cs = [cs[0], *cs[-(COMMENT_KEEP - 1):]]
    return [{"body": c.body[:COMMENT_MAX], "created_at": c.created_at} for c in cs]


def build_payload(raw: IssueRaw, refs: list[RefState]) -> dict:
    return {
        "number": raw.number,
        "title": raw.title,
        "labels": list(raw.labels),
        "body": raw.body[:BODY_MAX],
        "comments": _pick_comments(raw),
        "referenced_issues": [
            {"number": r.number, "state": r.state, "title": r.title}
            for r in sorted(refs, key=lambda r: r.number) if r.state in ("open", "closed")
        ],
    }


def summarize(
    raw: IssueRaw,
    refs: list[RefState],
    call: Callable[..., dict] = call_claude,
) -> tuple[Brief, str | None]:
    payload = build_payload(raw, refs)
    last_err: Exception | None = None
    for _attempt in range(2):
        meta: dict = {}
        out = call(PROMPT_FILE, payload_inline=payload,
                   timeout_seconds=CALL_TIMEOUT_SECONDS, meta_out=meta)
        try:
            return Brief.model_validate(out), meta.get("model")
        except ValidationError as e:
            last_err = e
    raise SummarizeFailed(f"issue #{raw.number}: schema mismatch after retry: {last_err}")
