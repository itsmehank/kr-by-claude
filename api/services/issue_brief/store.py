"""issue_briefs 읽기/쓰기. commit 은 호출자."""
from __future__ import annotations

from psycopg import Connection
from psycopg.types.json import Jsonb

from .github import IssueRaw
from .summarize import Brief

_COLS = ("number, title, labels, state, gh_updated_at, brief, brief_at, brief_model, "
         "brief_error, override_status, override_note, observed_at")
_KEYS = [c.strip() for c in _COLS.split(",")]


def _row_to_dict(r) -> dict:
    d = dict(zip(_KEYS, r))
    for k in ("gh_updated_at", "brief_at", "observed_at"):
        if d[k] is not None:
            d[k] = d[k].isoformat()
    d["labels"] = list(d["labels"] or [])
    return d


def fetch_briefs(conn: Connection, *, only_open: bool = True) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {_COLS} FROM issue_briefs "
            + ("WHERE state = 'open' " if only_open else "")
            + "ORDER BY number DESC"
        )
        return [_row_to_dict(r) for r in cur.fetchall()]


def fetch_hashes(conn: Connection) -> dict[int, tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT number, content_hash, state FROM issue_briefs")
        return {n: (h, s) for n, h, s in cur.fetchall()}


def fetch_numbers_with_error_prefix(conn: Connection, prefix: str) -> set[int]:
    """brief_error 가 prefix 로 시작하는 이슈 번호(usage_limit 오판 이슈를 회차 뒤로 미루는 용도)."""
    with conn.cursor() as cur:
        cur.execute("SELECT number FROM issue_briefs WHERE brief_error LIKE %s", (prefix + "%",))
        return {r[0] for r in cur.fetchall()}


def upsert_observed(conn: Connection, raw: IssueRaw, content_hash: str, *, keep_hash: bool) -> None:
    """관측 upsert. keep_hash=True 면 기존 행의 해시 유지(신규 행은 인자 저장)."""
    hash_expr = "issue_briefs.content_hash" if keep_hash else "EXCLUDED.content_hash"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO issue_briefs
                (number, title, labels, state, gh_updated_at, content_hash, observed_at)
            VALUES (%s, %s, %s, 'open', %s, %s, now())
            ON CONFLICT (number) DO UPDATE SET
                title = EXCLUDED.title,
                labels = EXCLUDED.labels,
                state = 'open',
                gh_updated_at = EXCLUDED.gh_updated_at,
                content_hash = {hash_expr},
                observed_at = now()
            """,
            (raw.number, raw.title, list(raw.labels), raw.updated_at or "1970-01-01T00:00:00Z",
             content_hash),
        )


def set_brief(conn: Connection, number: int, brief: Brief, model: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE issue_briefs
                  SET brief = %s, brief_model = %s, brief_at = now(), brief_error = NULL
                WHERE number = %s""",
            (Jsonb(brief.model_dump()), model, number),
        )


def set_brief_error(conn: Connection, number: int, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE issue_briefs SET brief_error = %s WHERE number = %s",
                    (error[:2000], number))


def mark_closed(conn: Connection, numbers: list[int]) -> None:
    if not numbers:
        return
    with conn.cursor() as cur:
        cur.execute("UPDATE issue_briefs SET state = 'closed', observed_at = now() "
                    "WHERE number = ANY(%s)", (numbers,))


def set_override(conn: Connection, number: int, status: str | None, note: str | None) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            f"""UPDATE issue_briefs SET override_status = %s, override_note = %s
                 WHERE number = %s RETURNING {_COLS}""",
            (status, note, number),
        )
        r = cur.fetchone()
    return _row_to_dict(r) if r else None
