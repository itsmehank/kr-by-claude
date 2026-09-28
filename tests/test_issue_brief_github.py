"""gh CLI 래퍼 테스트 — subprocess 주입(실 gh 호출 0)."""
import json
from types import SimpleNamespace

import pytest

from api.services.issue_brief.github import (
    GhUnavailable, IssueComment, IssueRaw, RefState, get_ref_state, list_open_issues,
)


def _fake_run(stdout="", returncode=0, stderr=""):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    run.calls = calls
    return run


def test_list_open_issues_parses_gh_json():
    payload = [{
        "number": 213, "title": "T", "body": "B #201",
        "labels": [{"name": "bug"}], "updatedAt": "2026-09-27T10:00:00Z",
        "comments": [{"body": "c1", "createdAt": "2026-09-27T11:00:00Z"}],
    }]
    run = _fake_run(json.dumps(payload))
    issues = list_open_issues(run=run)
    assert issues == [IssueRaw(
        number=213, title="T", body="B #201", labels=("bug",),
        updated_at="2026-09-27T10:00:00Z",
        comments=(IssueComment("c1", "2026-09-27T11:00:00Z"),),
    )]
    cmd = run.calls[0]
    assert cmd[:3] == ["gh", "issue", "list"] and "--state" in cmd and "open" in cmd


def test_list_open_issues_null_body_becomes_empty():
    run = _fake_run(json.dumps([{"number": 1, "title": "T", "body": None,
                                 "labels": [], "updatedAt": "x", "comments": []}]))
    assert list_open_issues(run=run)[0].body == ""


def test_list_open_issues_gh_failure_raises_unavailable():
    run = _fake_run(returncode=1, stderr="gh: not logged in")
    with pytest.raises(GhUnavailable) as e:
        list_open_issues(run=run)
    assert "not logged in" in str(e.value)


def test_list_open_issues_gh_missing_raises_unavailable():
    def run(cmd, **kw):
        raise FileNotFoundError("gh")
    with pytest.raises(GhUnavailable):
        list_open_issues(run=run)


def test_get_ref_state_open_and_closed():
    run = _fake_run(json.dumps({"number": 114, "state": "CLOSED", "title": "old"}))
    assert get_ref_state(114, run=run) == RefState(114, "closed", "old")
    run = _fake_run(json.dumps({"number": 5, "state": "OPEN", "title": "o"}))
    assert get_ref_state(5, run=run).state == "open"


def test_get_ref_state_pr_number_marked_pr():
    run = _fake_run(returncode=1, stderr="GraphQL: Could not resolve to an issue (pull request #187)")
    assert get_ref_state(187, run=run) == RefState(187, "pr", "")


def test_get_ref_state_other_failure_unknown():
    run = _fake_run(returncode=1, stderr="network error")
    assert get_ref_state(9999, run=run) == RefState(9999, "unknown", "")
