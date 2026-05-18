from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from api.deps import get_conn
from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS


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


def _next_scheduled(cron: str, now: datetime | None = None) -> str | None:
    """간단한 cron next-fire 계산 (월~금/토 기준). croniter 없이 직접 계산."""
    if now is None:
        now = datetime.now()
    # cron 형식: "M H D M W"
    parts = cron.split()
    if len(parts) != 5:
        return None
    minute, hour, _dom, _mon, dow = parts
    try:
        m = int(minute)
        h = int(hour)
    except ValueError:
        return None

    for delta in range(0, 14):
        candidate = (now + timedelta(days=delta)).replace(
            hour=h, minute=m, second=0, microsecond=0
        )
        if candidate <= now:
            continue
        weekday = candidate.weekday()  # 0=Mon ... 6=Sun
        # dow 매핑: cron 1-5 = Mon-Fri, 6 = Sat, 0 = Sun, * = any
        if dow == "*":
            return candidate.isoformat()
        if dow == "1-5" and weekday <= 4:
            return candidate.isoformat()
        if dow == "6" and weekday == 5:
            return candidate.isoformat()
        if dow == "0" and weekday == 6:
            return candidate.isoformat()
    return None


def _matches_mode_prefix(mode, prefix):
    if prefix is None:
        return True
    if mode is None:
        return False
    return mode.startswith(prefix)


@router.get("/summary")
def get_summary(conn: Connection = Depends(get_conn)):
    """모든 pipeline 의 last_run + next_scheduled."""
    result = []
    with conn.cursor() as cur:
        for spec in PIPELINE_SPECS:
            pipeline_db = spec["pipeline_db_name"]
            mode_prefix = spec.get("mode_prefix")

            cur.execute(
                """
                SELECT id, status, rows_affected, error, started_at, finished_at, mode
                  FROM pipeline_runs
                 WHERE pipeline = %s
                 ORDER BY id DESC LIMIT 10
                """,
                (pipeline_db,),
            )
            rows = cur.fetchall()
            last_run = None
            for row in rows:
                mode = row[6]
                if _matches_mode_prefix(mode, mode_prefix):
                    started = row[4]
                    finished = row[5]
                    duration_s = (
                        (finished - started).total_seconds()
                        if started and finished
                        else None
                    )
                    last_run = {
                        "id": row[0],
                        "status": row[1],
                        "rows_affected": row[2],
                        "error": row[3],
                        "started_at": started.isoformat() if started else None,
                        "finished_at": finished.isoformat() if finished else None,
                        "duration_seconds": duration_s,
                    }
                    break

            result.append({
                "pipeline_id": spec["id"],
                "group": spec["group"],
                "label": spec["label"],
                "module": spec["module"],
                "cron_expression": spec["default_cron"],
                "last_run": last_run,
                "next_scheduled": _next_scheduled(spec["default_cron"]),
                "modes": spec["modes"],
            })
    return {"pipelines": result}


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
