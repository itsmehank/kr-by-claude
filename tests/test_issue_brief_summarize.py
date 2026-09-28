"""summarize — call_claude 주입, 스키마 검증·1회 재호출·한도 전파."""
import pytest

from api.services.issue_brief.github import IssueComment, IssueRaw, RefState
from api.services.issue_brief.summarize import (
    PROMPT_FILE, Brief, SummarizeFailed, build_payload, summarize,
)
from kr_pipeline.llm_runner.llm.claude_cli import PROMPTS_DIR, UsageLimitError


def _raw(ncomments=0, body="body"):
    return IssueRaw(number=7, title="T", body=body, labels=("bug",), updated_at="u",
                    comments=tuple(IssueComment(f"c{i}", f"t{i}") for i in range(ncomments)))


GOOD = {"summary": "s", "group": "data", "start_status": "ready",
        "start_reason": "r", "depends_on": [114]}


def test_prompt_file_exists_and_is_not_analysis_prompt():
    text = (PROMPTS_DIR / PROMPT_FILE).read_text(encoding="utf-8")
    assert "thresholds" in text and "#197" in text          # 비-분석 프롬프트 선언
    for token in ("ready", "decision", "blocked", "data", "book", "trading_ui", "validation", "ops"):
        assert token in text


def test_build_payload_truncates_and_keeps_first_plus_last_four_comments():
    raw = _raw(ncomments=8, body="x" * 7000)
    p = build_payload(raw, [RefState(114, "closed", "old"), RefState(187, "pr", "")])
    assert p["number"] == 7 and p["labels"] == ["bug"]
    assert len(p["body"]) == 6000
    assert [c["body"] for c in p["comments"]] == ["c0", "c4", "c5", "c6", "c7"]
    assert p["referenced_issues"] == [{"number": 114, "state": "closed", "title": "old"}]  # pr 제외


def test_summarize_returns_brief_and_model():
    calls = []

    def call(prompt_file, payload_inline=None, timeout_seconds=0, meta_out=None):
        calls.append(prompt_file)
        meta_out["model"] = "claude-sonnet-5"
        return dict(GOOD)

    brief, model = summarize(_raw(), [], call=call)
    assert brief == Brief(**GOOD) and model == "claude-sonnet-5" and calls == [PROMPT_FILE]


def test_summarize_retries_once_on_schema_error_then_succeeds():
    answers = [{"summary": "s", "group": "nope"}, dict(GOOD)]

    def call(prompt_file, payload_inline=None, timeout_seconds=0, meta_out=None):
        return answers.pop(0)

    brief, _ = summarize(_raw(), [], call=call)
    assert brief.group == "data" and answers == []


def test_summarize_fails_after_two_schema_errors():
    def call(prompt_file, payload_inline=None, timeout_seconds=0, meta_out=None):
        return {"summary": "s"}

    with pytest.raises(SummarizeFailed):
        summarize(_raw(), [], call=call)


def test_summarize_propagates_usage_limit():
    def call(prompt_file, payload_inline=None, timeout_seconds=0, meta_out=None):
        raise UsageLimitError("limit")

    with pytest.raises(UsageLimitError):
        summarize(_raw(), [], call=call)


def test_brief_rejects_overlong_summary():
    with pytest.raises(Exception):
        Brief(summary="x" * 121, group="ops", start_status="ready", start_reason="r", depends_on=[])
