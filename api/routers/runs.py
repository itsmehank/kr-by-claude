from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from api.deps import get_conn


router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("")
def list_runs(
    pipeline: str | None = None,
    limit: int = 20,
    conn: Connection = Depends(get_conn),
):
    sql = """
        SELECT id, pipeline, mode, status, rows_affected, error, started_at, finished_at
          FROM pipeline_runs
    """
    params = []
    if pipeline:
        sql += " WHERE pipeline = %s"
        params.append(pipeline)
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "pipeline": r[1],
            "mode": r[2],
            "status": r[3],
            "rows_affected": r[4],
            "error": r[5],
            "started_at": r[6].isoformat() if r[6] else None,
            "finished_at": r[7].isoformat() if r[7] else None,
        }
        for r in rows
    ]


@router.get("/{run_id}")
def get_run(run_id: int, conn: Connection = Depends(get_conn)):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, pipeline, mode, status, rows_affected, error,
                   started_at, finished_at, params
              FROM pipeline_runs
             WHERE id = %s
            """,
            (run_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, f"Run not found: {run_id}")

    started = row[6]
    finished = row[7]
    duration_seconds = None
    if started and finished:
        duration_seconds = (finished - started).total_seconds()

    return {
        "id": row[0],
        "pipeline": row[1],
        "mode": row[2],
        "status": row[3],
        "rows_affected": row[4],
        "error": row[5],
        "started_at": started.isoformat() if started else None,
        "finished_at": finished.isoformat() if finished else None,
        "duration_seconds": duration_seconds,
        "params": row[8],
    }
