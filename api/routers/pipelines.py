from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from api.deps import get_conn
from kr_pipeline.llm_runner.pipeline_specs import (
    PIPELINE_SPECS,
    get_spec,
    matches_mode_prefix,
)


router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


@router.get("")
def list_pipelines():
    """모든 pipeline spec 반환 (frontend 가 동적 렌더링용)."""
    return {"pipelines": PIPELINE_SPECS}


@router.get("/{pipeline_id}")
def get_pipeline_detail(pipeline_id: str, conn: Connection = Depends(get_conn)):
    """단일 pipeline 상세 — depends_on 에 label 채움 + consumed_by reverse + recent_runs."""
    spec = get_spec(pipeline_id)
    if spec is None:
        raise HTTPException(404, f"pipeline not found: {pipeline_id}")

    # depends_on: id → {id, label}
    depends_on = [
        {"id": dep_id, "label": _label_of(dep_id)}
        for dep_id in spec["depends_on"]
    ]

    # consumed_by: PIPELINE_SPECS 순회 — depends_on 에 pipeline_id 포함하는 spec 들
    consumed_by = [
        {"id": s["id"], "label": s["label"]}
        for s in PIPELINE_SPECS
        if pipeline_id in s["depends_on"]
    ]

    # recent_runs: pipeline_db_name 으로 SELECT, mode_prefix 적용 후 상위 5건
    pipeline_db = spec["pipeline_db_name"]
    mode_prefix = spec.get("mode_prefix")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, mode, status, started_at, finished_at, rows_affected, error
              FROM pipeline_runs
             WHERE pipeline = %s
             ORDER BY id DESC LIMIT 10
            """,
            (pipeline_db,),
        )
        rows = cur.fetchall()

    recent_runs = []
    for row in rows:
        run_id, mode, status, started, finished, rows_affected, error = row
        if not matches_mode_prefix(mode, mode_prefix):
            continue
        duration_s = (
            (finished - started).total_seconds()
            if started and finished
            else None
        )
        recent_runs.append({
            "id": run_id,
            "mode": mode,
            "status": status,
            "started_at": started.isoformat() if started else None,
            "finished_at": finished.isoformat() if finished else None,
            "rows_affected": rows_affected,
            "duration_seconds": duration_s,
            "error": error,
        })
        if len(recent_runs) >= 5:
            break

    return {
        "id": spec["id"],
        "group": spec["group"],
        "label": spec["label"],
        "description": spec["description"],
        "long_description": spec["long_description"],
        "module": spec["module"],
        "schedule_label": spec["schedule_label"],
        "default_cron": spec["default_cron"],
        "inputs": spec["inputs"],
        "outputs": spec["outputs"],
        "depends_on": depends_on,
        "consumed_by": consumed_by,
        "modes": spec["modes"],
        "recent_runs": recent_runs,
    }


def _label_of(pipeline_id: str) -> str:
    s = get_spec(pipeline_id)
    return s["label"] if s else pipeline_id
