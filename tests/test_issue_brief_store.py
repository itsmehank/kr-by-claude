"""issue_briefs 저장 계층 테스트 (spec: docs/superpowers/specs/2026-09-28-issues-page-design.md)."""


def test_issue_briefs_table_exists(db):
    with db.cursor() as cur:
        cur.execute("SELECT to_regclass('issue_briefs')")
        assert cur.fetchone()[0] == "issue_briefs"

from api.services.issue_brief.github import IssueComment, IssueRaw
from api.services.issue_brief.store import (
    fetch_briefs, fetch_hashes, mark_closed, set_brief, set_brief_error,
    set_override, upsert_observed,
)
from api.services.issue_brief.summarize import Brief


def _raw(n=900001, title="t", labels=("a",), body="b"):
    return IssueRaw(number=n, title=title, body=body, labels=labels,
                    updated_at="2026-09-27T10:00:00Z",
                    comments=(IssueComment("c", "2026-09-27T11:00:00Z"),))


def _brief(status="ready"):
    return Brief(summary="s", group="ops", start_status=status, start_reason="r", depends_on=[1])


def test_upsert_new_then_fetch(db):
    upsert_observed(db, _raw(), "h1", keep_hash=False)
    rows = fetch_briefs(db)
    row = next(r for r in rows if r["number"] == 900001)
    assert row["title"] == "t" and row["labels"] == ["a"] and row["state"] == "open"
    assert row["brief"] is None and row["override_status"] is None
    assert fetch_hashes(db)[900001] == ("h1", "open")


def test_upsert_existing_keep_hash_preserves_hash_but_updates_meta(db):
    upsert_observed(db, _raw(), "h1", keep_hash=False)
    upsert_observed(db, _raw(title="t2", labels=("z",)), "h2", keep_hash=True)
    assert fetch_hashes(db)[900001] == ("h1", "open")
    row = next(r for r in fetch_briefs(db) if r["number"] == 900001)
    assert row["title"] == "t2" and row["labels"] == ["z"]


def test_upsert_existing_replace_hash(db):
    upsert_observed(db, _raw(), "h1", keep_hash=False)
    upsert_observed(db, _raw(), "h2", keep_hash=False)
    assert fetch_hashes(db)[900001][0] == "h2"


def test_set_brief_clears_error_and_set_error_keeps_brief(db):
    upsert_observed(db, _raw(), "h1", keep_hash=False)
    set_brief_error(db, 900001, "boom")
    set_brief(db, 900001, _brief(), "claude-sonnet-5")
    row = next(r for r in fetch_briefs(db) if r["number"] == 900001)
    assert row["brief"]["summary"] == "s" and row["brief_model"] == "claude-sonnet-5"
    assert row["brief_error"] is None and row["brief_at"] is not None
    set_brief_error(db, 900001, "later")
    row = next(r for r in fetch_briefs(db) if r["number"] == 900001)
    assert row["brief"]["summary"] == "s" and row["brief_error"] == "later"


def test_mark_closed_hides_from_open_fetch_and_reopen_restores(db):
    upsert_observed(db, _raw(), "h1", keep_hash=False)
    mark_closed(db, [900001])
    assert all(r["number"] != 900001 for r in fetch_briefs(db))
    assert fetch_hashes(db)[900001] == ("h1", "closed")
    upsert_observed(db, _raw(), "h1", keep_hash=True)          # 재오픈 관측
    assert any(r["number"] == 900001 for r in fetch_briefs(db))


def test_set_override_and_clear(db):
    upsert_observed(db, _raw(), "h1", keep_hash=False)
    row = set_override(db, 900001, "blocked", "메모")
    assert row["override_status"] == "blocked" and row["override_note"] == "메모"
    row = set_override(db, 900001, None, None)
    assert row["override_status"] is None
    assert set_override(db, 999999, "ready", None) is None
