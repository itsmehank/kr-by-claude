import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from psycopg import Connection


def start_run(conn: Connection, *, pipeline: str, mode: str, params: dict) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pipeline_runs (pipeline, mode, started_at, status, params)
            VALUES (%s, %s, %s, 'running', %s::jsonb)
            RETURNING id
            """,
            (pipeline, mode, datetime.now(timezone.utc), json.dumps(params)),
        )
        return cur.fetchone()[0]


def finish_run(
    conn: Connection,
    run_id: int,
    *,
    status: str,
    rows_affected: int | None = None,
    error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE pipeline_runs
               SET finished_at = %s, status = %s, rows_affected = %s, error = %s
             WHERE id = %s
            """,
            (datetime.now(timezone.utc), status, rows_affected, error, run_id),
        )


@contextmanager
def run_tracking(conn: Connection, *, pipeline: str, mode: str, params: dict) -> Iterator[dict]:
    """yields a dict {run_id: int, warnings: list[str]}.

    Caller may append to warnings list during work; warnings are recorded as JSON
    in pipeline_runs.error on successful completion. Status stays 'success'.
    """
    run_id = start_run(conn, pipeline=pipeline, mode=mode, params=params)
    conn.commit()
    state: dict = {"run_id": run_id, "warnings": []}
    try:
        yield state
        # success path with possible warnings
        warnings_json: str | None = None
        if state["warnings"]:
            warnings_json = json.dumps({"warnings": state["warnings"]}, ensure_ascii=False)
        finish_run(conn, run_id, status="success", error=warnings_json)
        conn.commit()
    except Exception as e:
        conn.rollback()
        # 새 트랜잭션으로 실패 기록
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pipeline_runs SET finished_at = NOW(), status = 'failed', error = %s WHERE id = %s",
                (str(e), run_id),
            )
        conn.commit()
        raise
