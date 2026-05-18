from datetime import datetime, timedelta
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


# 평일/주말 모드별 cron 스케줄 (cron.example 과 일치)
MODE_SCHEDULES = {
    "full-daily": {
        "pipeline": "llm_daily_delta",  # full-daily 의 첫 단계 = daily_delta
        "cron": "30 16 * * 1-5",
        "description": "평일 16:30 — daily-delta + evaluate + entry + performance",
    },
    "weekend": {
        "pipeline": "llm_weekend",
        "cron": "20 3 * * 6",
        "description": "토요일 03:20 — 전체 후보 (5) 분류",
    },
    "performance": {
        "pipeline": "llm_performance",
        "cron": "0 23 * * *",
        "description": "매일 23:00 — signal_performance backfill",
    },
}


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


@router.get("/summary")
def get_summary(conn: Connection = Depends(get_conn)):
    """모드별 마지막 실행 + 다음 예정 시각."""
    result = []
    with conn.cursor() as cur:
        for mode, sched in MODE_SCHEDULES.items():
            cur.execute(
                """
                SELECT id, status, rows_affected, error, started_at, finished_at
                  FROM pipeline_runs
                 WHERE pipeline = %s
                 ORDER BY id DESC LIMIT 1
                """,
                (sched["pipeline"],),
            )
            row = cur.fetchone()
            last_run = None
            if row:
                started = row[4]
                finished = row[5]
                duration_s = (finished - started).total_seconds() if started and finished else None
                last_run = {
                    "id": row[0],
                    "status": row[1],
                    "rows_affected": row[2],
                    "error": row[3],
                    "started_at": started.isoformat() if started else None,
                    "finished_at": finished.isoformat() if finished else None,
                    "duration_seconds": duration_s,
                }
            result.append({
                "mode": mode,
                "pipeline": sched["pipeline"],
                "cron_expression": sched["cron"],
                "description": sched["description"],
                "last_run": last_run,
                "next_scheduled": _next_scheduled(sched["cron"]),
            })
    return {"modes": result}


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
