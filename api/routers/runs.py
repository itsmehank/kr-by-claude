from fastapi import APIRouter, Depends
from psycopg import Connection

from api.deps import get_conn


router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("")
def list_runs(pipeline: str | None = None, limit: int = 20, conn: Connection = Depends(get_conn)):
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
    return [{
        "id": r[0], "pipeline": r[1], "mode": r[2], "status": r[3],
        "rows_affected": r[4], "error": r[5],
        "started_at": r[6].isoformat() if r[6] else None,
        "finished_at": r[7].isoformat() if r[7] else None,
    } for r in rows]
