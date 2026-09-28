"""gh CLI 래퍼 테스트 — subprocess 주입(실 gh 호출 0)."""
import json
from types import SimpleNamespace

import pytest

from api.services.issue_brief.github import (
    GhUnavailable, IssueComment, IssueRaw, RefState, get_ref_states, gh_available, list_open_issues,
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


def _fake_run_seq(responses):
    """호출 순서대로 (returncode, stdout, stderr) 반환."""
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        rc, out, err = responses.pop(0)
        return SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    run.calls = calls
    return run


def test_get_ref_states_batches_issues_and_prs_and_normalizes_merged():
    issues = json.dumps([{"number": 114, "state": "CLOSED", "title": "old"},
                         {"number": 5, "state": "OPEN", "title": "o"}])
    prs = json.dumps([{"number": 187, "state": "MERGED", "title": "pr"},
                      {"number": 214, "state": "OPEN", "title": "pr2"}])
    run = _fake_run_seq([(0, issues, ""), (0, prs, "")])
    got = get_ref_states({114, 5, 187, 214, 9999}, run=run)
    assert got[114] == RefState(114, "closed", "old")
    assert got[5].state == "open"
    assert got[187] == RefState(187, "closed", "pr")       # MERGED → closed
    assert got[214].state == "open"
    assert got[9999] == RefState(9999, "unknown", "")
    assert [c[:2] for c in run.calls] == [["gh", "issue"], ["gh", "pr"]]
    assert all("--state" in c and "all" in c for c in run.calls)


def test_get_ref_states_empty_set_makes_no_call():
    run = _fake_run()
    assert get_ref_states(set(), run=run) == {} and run.calls == []


def test_get_ref_states_gh_failure_propagates():
    run = _fake_run(returncode=1, stderr="boom")
    with pytest.raises(GhUnavailable):
        get_ref_states({1}, run=run)


def test_gh_available_probe():
    ok, detail = gh_available(run=_fake_run(stdout="Logged in"))
    assert ok is True and detail == ""
    ok, detail = gh_available(run=_fake_run(returncode=1, stderr="You are not logged into any GitHub hosts"))
    assert ok is False and "not logged" in detail

    def missing(cmd, **kw):
        raise FileNotFoundError("gh")
    ok, detail = gh_available(run=missing)
    assert ok is False and "not found" in detail
