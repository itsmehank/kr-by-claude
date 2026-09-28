"""issue_briefs 저장 계층 테스트 (spec: docs/superpowers/specs/2026-09-28-issues-page-design.md)."""


def test_issue_briefs_table_exists(db):
    with db.cursor() as cur:
        cur.execute("SELECT to_regclass('issue_briefs')")
        assert cur.fetchone()[0] == "issue_briefs"
