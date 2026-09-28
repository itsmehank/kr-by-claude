"""갱신 회차 — gh·요약 주입(실 호출 0). 행 단위 커밋·해시·닫힘·실패 재시도·락."""
import threading

import pytest

from api.services.issue_brief.github import GhUnavailable, IssueComment, IssueRaw, RefState
from api.services.issue_brief.refresh import RefreshState, run_refresh, start_refresh
from api.services.issue_brief.store import fetch_briefs, fetch_hashes
from api.services.issue_brief.summarize import Brief, SummarizeFailed
from kr_pipeline.llm_runner.llm.claude_cli import UsageLimitError

N1, N2 = 910001, 910002


@pytest.fixture(autouse=True)
def _clean_rows(db):
    # run_refresh 는 행 단위 commit 을 하므로 db 픽스처의 rollback 으로 격리되지 않는다.
    def _delete():
        with db.cursor() as cur:
            cur.execute("DELETE FROM issue_briefs WHERE number IN (%s, %s)", (N1, N2))
        db.commit()
    _delete()
    yield
    _delete()


def _raw(n, body="b", comments=()):
    return IssueRaw(number=n, title=f"t{n}", body=body, labels=(), updated_at="2026-09-27T00:00:00Z",
                    comments=tuple(IssueComment(c, "x") for c in comments))


def _brief():
    return Brief(summary="s", group="ops", start_status="ready", start_reason="r", depends_on=[])


class Spy:
    def __init__(self, result=None, exc=None):
        self.calls = []
        self.result = result
        self.exc = exc

    def __call__(self, raw, refs, **kw):
        self.calls.append((raw.number, sorted(r.number for r in refs)))
        if self.exc:
            raise self.exc
        return (self.result or _brief()), "m"


def _refs(states: dict):
    return lambda n: RefState(n, states.get(n, "unknown"), "")


def test_new_issue_is_summarized_and_stored(db):
    spy = Spy()
    st = run_refresh(db, list_issues=lambda: [_raw(N1, body="see #114")],
                     ref_state=_refs({114: "closed"}), do_summarize=spy, state=RefreshState())
    assert spy.calls == [(N1, [114])]
    row = next(r for r in fetch_briefs(db) if r["number"] == N1)
    assert row["brief"]["summary"] == "s" and row["brief_model"] == "m"
    assert (st.total, st.done, st.summarized, st.failed, st.running) == (1, 1, 1, 0, False)


def test_unchanged_issue_not_resummarized(db):
    issues = lambda: [_raw(N1)]
    run_refresh(db, list_issues=issues, ref_state=_refs({}), do_summarize=Spy(), state=RefreshState())
    spy = Spy()
    st = run_refresh(db, list_issues=issues, ref_state=_refs({}), do_summarize=spy, state=RefreshState())
    assert spy.calls == [] and st.summarized == 0 and st.done == 1


def test_ref_state_change_triggers_resummary(db):
    issues = lambda: [_raw(N1, body="after #114")]
    run_refresh(db, list_issues=issues, ref_state=_refs({114: "open"}), do_summarize=Spy(), state=RefreshState())
    spy = Spy()
    run_refresh(db, list_issues=issues, ref_state=_refs({114: "closed"}), do_summarize=spy, state=RefreshState())
    assert spy.calls == [(N1, [114])]


def test_ref_in_open_set_uses_open_without_gh_lookup(db):
    looked = []

    def ref_state(n):
        looked.append(n)
        return RefState(n, "closed", "")

    run_refresh(db, list_issues=lambda: [_raw(N1, body="#%d" % N2), _raw(N2)],
                ref_state=ref_state, do_summarize=Spy(), state=RefreshState())
    assert looked == []


def test_closed_issue_marked_closed_and_hidden(db):
    run_refresh(db, list_issues=lambda: [_raw(N1), _raw(N2)], ref_state=_refs({}), do_summarize=Spy(), state=RefreshState())
    run_refresh(db, list_issues=lambda: [_raw(N2)], ref_state=_refs({}), do_summarize=Spy(), state=RefreshState())
    assert fetch_hashes(db)[N1][1] == "closed"
    assert [r["number"] for r in fetch_briefs(db) if r["number"] in (N1, N2)] == [N2]


def test_summarize_failure_keeps_previous_brief_and_hash(db):
    issues_v1 = lambda: [_raw(N1, comments=("c1",))]
    run_refresh(db, list_issues=issues_v1, ref_state=_refs({}), do_summarize=Spy(), state=RefreshState())
    h1 = fetch_hashes(db)[N1][0]
    issues_v2 = lambda: [_raw(N1, comments=("c1", "c2"))]
    st = run_refresh(db, list_issues=issues_v2, ref_state=_refs({}),
                     do_summarize=Spy(exc=SummarizeFailed("bad")), state=RefreshState())
    row = next(r for r in fetch_briefs(db) if r["number"] == N1)
    assert row["brief"]["summary"] == "s" and "bad" in row["brief_error"]
    assert fetch_hashes(db)[N1][0] == h1 and st.failed == 1
    spy = Spy()
    run_refresh(db, list_issues=issues_v2, ref_state=_refs({}), do_summarize=spy, state=RefreshState())
    assert spy.calls == [(N1, [])]           # 다음 회차 재시도
    assert next(r for r in fetch_briefs(db) if r["number"] == N1)["brief_error"] is None


def test_new_issue_summarize_failure_retried_next_round(db):
    issues = lambda: [_raw(N1)]
    st = run_refresh(db, list_issues=issues, ref_state=_refs({}),
                     do_summarize=Spy(exc=SummarizeFailed("bad")), state=RefreshState())
    assert st.failed == 1 and fetch_hashes(db)[N1][0] == ""
    row = next(r for r in fetch_briefs(db) if r["number"] == N1)
    assert row["brief"] is None and "bad" in row["brief_error"]
    spy = Spy()
    run_refresh(db, list_issues=issues, ref_state=_refs({}), do_summarize=spy, state=RefreshState())
    assert spy.calls == [(N1, [])] and fetch_hashes(db)[N1][0] != ""


def test_usage_limit_stops_round(db):
    spy = Spy(exc=UsageLimitError("limit"))
    st = run_refresh(db, list_issues=lambda: [_raw(N1), _raw(N2)], ref_state=_refs({}),
                     do_summarize=spy, state=RefreshState())
    assert st.stopped_reason == "usage_limit" and len(spy.calls) == 1 and st.running is False


def test_gh_unavailable_recorded_not_raised(db):
    def boom():
        raise GhUnavailable("no gh")

    st = run_refresh(db, list_issues=boom, ref_state=_refs({}), do_summarize=Spy(), state=RefreshState())
    assert st.stopped_reason == "gh_unavailable" and st.running is False


def test_start_refresh_refuses_concurrent(monkeypatch):
    import api.services.issue_brief.refresh as mod
    gate = threading.Event()

    def slow(conn, **kw):
        gate.wait(5)

    monkeypatch.setattr(mod, "run_refresh", slow)
    monkeypatch.setattr(mod, "STATE", RefreshState())

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    assert start_refresh(conn_factory=lambda: _Conn()) is True
    assert start_refresh(conn_factory=lambda: _Conn()) is False
    gate.set()
    mod._THREAD.join(5)
    assert start_refresh(conn_factory=lambda: _Conn()) is True
    gate.set()
    mod._THREAD.join(5)
