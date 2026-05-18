"""LLM runner subprocess 실행 + 중복/동시 실행 방지.

수동 실행 흐름:
1. check_can_run() 으로 중복 방지 체크
2. spawn_runner() 로 subprocess.Popen (fire-and-forget)
3. 진행 상황은 pipeline_runs 테이블 polling (별도 endpoint)
"""
from __future__ import annotations

import os
import subprocess
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from psycopg import Connection

from kr_pipeline.llm_runner.pipeline_specs import get_spec, get_mode_args


PROJECT_DIR = Path(__file__).parent.parent.parent.resolve()
LOG_DIR = Path.home() / ".kr-by-claude"


MODE_TO_PIPELINE = {
    "weekend": "llm_weekend",
    "daily-delta": "llm_daily_delta",
    "evaluate": "llm_evaluate_pivot",
    "entry": "llm_entry_params",
    "performance": "llm_performance",
    "full-daily": "llm_daily_delta",  # full-daily 는 여러 pipeline 로 분기. delta 만 추적
}


def check_can_run(
    conn: Connection,
    mode: str,
    *,
    force: bool = False,
) -> dict:
    """모드 실행 가능 여부 + 거부 사유.

    Returns:
        {
          "can_run": bool,
          "reason": "ok" | "already_running" | "duplicate",
          "existing_run_id": int | None,
          "existing_run_summary": {...} | None,
        }
    """
    pipeline = MODE_TO_PIPELINE.get(mode)
    if pipeline is None:
        return {"can_run": False, "reason": "unknown_mode", "existing_run_id": None}

    # 1. running 상태 체크 (force 와 무관 — 동시 실행 위험)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, started_at FROM pipeline_runs
             WHERE pipeline = %s AND status = 'running'
             ORDER BY id DESC LIMIT 1
            """,
            (pipeline,),
        )
        running = cur.fetchone()
    if running:
        return {
            "can_run": False,
            "reason": "already_running",
            "existing_run_id": running[0],
            "existing_run_summary": {"started_at": running[1].isoformat()},
        }

    if force:
        return {"can_run": True, "reason": "ok", "existing_run_id": None}

    # 2. 오늘 같은 모드 success 체크
    today = date.today()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, started_at, finished_at, rows_affected
              FROM pipeline_runs
             WHERE pipeline = %s
               AND status = 'success'
               AND (started_at AT TIME ZONE 'Asia/Seoul')::date = %s
             ORDER BY id DESC LIMIT 1
            """,
            (pipeline, today),
        )
        recent = cur.fetchone()
    if recent:
        return {
            "can_run": False,
            "reason": "duplicate",
            "existing_run_id": recent[0],
            "existing_run_summary": {
                "started_at": recent[1].isoformat(),
                "finished_at": recent[2].isoformat() if recent[2] else None,
                "rows_affected": recent[3],
            },
        }

    return {"can_run": True, "reason": "ok", "existing_run_id": None}


def spawn_runner(
    mode: str,
    *,
    dry_run: bool = True,
    limit: int | None = None,
    ticker: str | None = None,
) -> dict:
    """subprocess.Popen 으로 LLM runner 실행 (fire-and-forget).

    Returns: {"pid": int, "command": str}
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "llm_runner.log"

    cmd = [
        "uv", "run", "python", "-m", "kr_pipeline.llm_runner",
        f"--mode={mode}",
    ]
    if dry_run:
        cmd.append("--dry-run")
    if limit is not None:
        cmd.append(f"--limit={limit}")
    if ticker is not None:
        cmd.append(f"--ticker={ticker}")

    log_file = log_path.open("a")
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_DIR),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # 부모 종료해도 살아있게
    )
    return {"pid": proc.pid, "command": " ".join(cmd)}


def check_can_run_pipeline(
    conn,
    pipeline_id: str,
    *,
    force: bool = False,
) -> dict:
    """PIPELINE_SPECS 기반 중복 방지 체크.

    pipeline_id 가 'indicators-daily' / 'indicators-weekly' 같이 같은
    pipeline_db_name 을 공유하면 mode_prefix 로 구분 (pipeline_runs.mode
    가 'daily-' 또는 'weekly-' 로 시작하는 행만).
    """
    spec = get_spec(pipeline_id)
    if spec is None:
        return {"can_run": False, "reason": "unknown_pipeline"}

    pipeline_db = spec["pipeline_db_name"]
    mode_prefix = spec.get("mode_prefix")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, started_at, mode FROM pipeline_runs
             WHERE pipeline = %s AND status = 'running'
             ORDER BY id DESC LIMIT 5
            """,
            (pipeline_db,),
        )
        running_rows = cur.fetchall()

    for row in running_rows:
        run_id, started_at, mode = row
        if _matches_mode_prefix(mode, mode_prefix):
            return {
                "can_run": False,
                "reason": "already_running",
                "existing_run_id": run_id,
                "existing_run_summary": {"started_at": started_at.isoformat()},
            }

    if force:
        return {"can_run": True, "reason": "ok", "existing_run_id": None}

    today = date.today()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, started_at, finished_at, rows_affected, mode
              FROM pipeline_runs
             WHERE pipeline = %s
               AND status = 'success'
               AND (started_at AT TIME ZONE 'Asia/Seoul')::date = %s
             ORDER BY id DESC LIMIT 5
            """,
            (pipeline_db, today),
        )
        success_rows = cur.fetchall()

    for row in success_rows:
        run_id, started_at, finished_at, rows_affected, mode = row
        if _matches_mode_prefix(mode, mode_prefix):
            return {
                "can_run": False,
                "reason": "duplicate",
                "existing_run_id": run_id,
                "existing_run_summary": {
                    "started_at": started_at.isoformat(),
                    "finished_at": finished_at.isoformat() if finished_at else None,
                    "rows_affected": rows_affected,
                },
            }

    return {"can_run": True, "reason": "ok", "existing_run_id": None}


def _matches_mode_prefix(mode, prefix) -> bool:
    if prefix is None:
        return True
    if mode is None:
        return False
    return mode.startswith(prefix)


def spawn_pipeline(pipeline_id: str, mode_id: str) -> dict:
    """PIPELINE_SPECS 기반 subprocess spawn."""
    spec = get_spec(pipeline_id)
    if spec is None:
        raise ValueError(f"unknown pipeline: {pipeline_id}")

    args = get_mode_args(pipeline_id, mode_id)
    if args is None:
        raise ValueError(f"unknown mode {mode_id} for {pipeline_id}")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "cron.log"

    cmd = ["uv", "run", "python", "-m", spec["module"], *args]

    log_file = log_path.open("a")
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_DIR),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return {"pid": proc.pid, "command": " ".join(cmd)}
