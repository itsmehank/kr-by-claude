"""issue_briefs 저장 계층 테스트 (spec: docs/superpowers/specs/2026-09-28-issues-page-design.md)."""


def test_issue_briefs_table_exists(db):
    with db.cursor() as cur:
        cur.execute("SELECT to_regclass('issue_briefs')")
        assert cur.fetchone()[0] == "issue_briefs"

from api.services.issue_brief.github import IssueComment, IssueRaw
from api.services.issue_brief.store import (
    fetch_briefs, fetch_closed_numbers, fetch_hashes, mark_closed, set_brief, set_brief_error,
    set_override, upsert_observed,
)
from api.services.issue_brief.summarize import Brief


def _raw(n=900001, title="t", labels=("a",), body="b"):
    return IssueRaw(number=n, title=title, body=body, labels=labels,
                    updated_at="2026-09-27T10:00:00Z",
                    comments=(IssueComment("c", "2026-09-27T11:00:00Z"),))


def _brief(status="ready"):
    return Brief(summary="s", group="ops", start_status=status, start_reason="r", depends_on=[1])


def test_upsert_new_starts_with_empty_hash(db):
    upsert_observed(db, _raw())
    row = next(r for r in fetch_briefs(db) if r["number"] == 900001)
    assert row["title"] == "t" and row["labels"] == ["a"] and row["state"] == "open"
    assert row["brief"] is None and row["override_status"] is None
    assert fetch_hashes(db)[900001] == ("", "open")


def test_upsert_existing_updates_meta_but_never_hash(db):
    upsert_observed(db, _raw())
    set_brief(db, 900001, _brief(), "m", "h1")
    upsert_observed(db, _raw(title="t2", labels=("z",)))
    assert fetch_hashes(db)[900001] == ("h1", "open")
    row = next(r for r in fetch_briefs(db) if r["number"] == 900001)
    assert row["title"] == "t2" and row["labels"] == ["z"] and row["brief"]["summary"] == "s"


def test_set_brief_sets_hash_and_clears_error_and_error_keeps_brief(db):
    upsert_observed(db, _raw())
    set_brief_error(db, 900001, "boom")
    set_brief(db, 900001, _brief(), "claude-sonnet-5", "h1")
    row = next(r for r in fetch_briefs(db) if r["number"] == 900001)
    assert row["brief"]["summary"] == "s" and row["brief_model"] == "claude-sonnet-5"
    assert row["brief_error"] is None and row["brief_at"] is not None
    assert fetch_hashes(db)[900001][0] == "h1"
    set_brief_error(db, 900001, "later")
    row = next(r for r in fetch_briefs(db) if r["number"] == 900001)
    assert row["brief"]["summary"] == "s" and row["brief_error"] == "later"
    assert fetch_hashes(db)[900001][0] == "h1"          # 실패는 해시를 건드리지 않음


def test_mark_closed_hides_from_open_fetch_lists_in_closed_and_reopen_restores(db):
    upsert_observed(db, _raw())
    set_brief(db, 900001, _brief(), "m", "h1")
    mark_closed(db, [900001])
    assert all(r["number"] != 900001 for r in fetch_briefs(db))
    assert 900001 in fetch_closed_numbers(db)
    assert fetch_hashes(db)[900001] == ("h1", "closed")
    upsert_observed(db, _raw())          # 재오픈 관측 — 해시 유지 → 재요약 없음
    assert any(r["number"] == 900001 for r in fetch_briefs(db))
    assert fetch_hashes(db)[900001] == ("h1", "open")
    assert 900001 not in fetch_closed_numbers(db)


def test_set_override_and_clear(db):
    upsert_observed(db, _raw())
    row = set_override(db, 900001, "blocked", "메모")
    assert row["override_status"] == "blocked" and row["override_note"] == "메모"
    row = set_override(db, 900001, None, None)
    assert row["override_status"] is None
    assert set_override(db, 999999, "ready", None) is None
