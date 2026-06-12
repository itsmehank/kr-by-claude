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

from kr_pipeline.llm_runner.pipeline_specs import get_spec, get_mode_args, matches_mode_prefix
from kr_pipeline.llm_runner.load import resolve_as_of


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

    # 2. as_of 기반 duplicate 체크 (as_of 없으면 wall-clock 폴백)
    prospective = resolve_as_of(conn)
    today = date.today()
    with conn.cursor() as cur:
        # duplicate 판정: 데이터 날짜(as_of) 기준. as_of 있으면 같은 as_of 만 중복(오전/오후 독립),
        # as_of 없는 파이프라인(비-LLM)은 기존 wall-clock today 로 fallback.
        cur.execute(
            """
            SELECT id, started_at, finished_at, rows_affected
              FROM pipeline_runs
             WHERE pipeline = %s
               AND status = 'success'
               AND ( params->>'as_of' = %s
                     OR (params->>'as_of' IS NULL
                         AND (started_at AT TIME ZONE 'Asia/Seoul')::date = %s) )
             ORDER BY id DESC LIMIT 1
            """,
            (pipeline, prospective.isoformat(), today),
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
    force: bool = False,
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
    if force:
        cmd.append("--force")

    log_file = log_path.open("a")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # 부모 종료해도 살아있게
        )
    finally:
        log_file.close()
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
        if matches_mode_prefix(mode, mode_prefix):
            return {
                "can_run": False,
                "reason": "already_running",
                "existing_run_id": run_id,
                "existing_run_summary": {"started_at": started_at.isoformat()},
            }

    if force:
        return {"can_run": True, "reason": "ok", "existing_run_id": None}

    prospective = resolve_as_of(conn)
    today = date.today()
    with conn.cursor() as cur:
        # duplicate 판정: 데이터 날짜(as_of) 기준. as_of 있으면 같은 as_of 만 중복(오전/오후 독립),
        # as_of 없는 파이프라인(비-LLM)은 기존 wall-clock today 로 fallback.
        cur.execute(
            """
            SELECT id, started_at, finished_at, rows_affected, mode, params
              FROM pipeline_runs
             WHERE pipeline = %s
               AND status = 'success'
               AND ( params->>'as_of' = %s
                     OR (params->>'as_of' IS NULL
                         AND (started_at AT TIME ZONE 'Asia/Seoul')::date = %s) )
             ORDER BY id DESC LIMIT 5
            """,
            (pipeline_db, prospective.isoformat(), today),
        )
        success_rows = cur.fetchall()

    for row in success_rows:
        run_id, started_at, finished_at, rows_affected, mode, _params = row
        if matches_mode_prefix(mode, mode_prefix):
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


def spawn_pipeline(pipeline_id: str, mode_id: str, params: dict | None = None, *, force: bool = False) -> dict:
    """PIPELINE_SPECS 기반 subprocess spawn.

    params: 사용자가 UI 에서 입력한 모드별 추가 인자 (e.g., {"years": 3}).
    모드의 params 정의를 참고해 --{name}={value} 형태로 cmd 에 append.
    """
    spec = get_spec(pipeline_id)
    if spec is None:
        raise ValueError(f"unknown pipeline: {pipeline_id}")

    args = get_mode_args(pipeline_id, mode_id)
    if args is None:
        raise ValueError(f"unknown mode {mode_id} for {pipeline_id}")

    # mode 의 params 정의를 가져와 사용자 입력 또는 default 적용
    mode = next((m for m in spec["modes"] if m["id"] == mode_id), None)
    mode_params = mode.get("params", []) if mode else []
    extra_args = []
    for p in mode_params:
        value = (params or {}).get(p["name"], p["default"])
        extra_args.append(f"--{p['name']}={value}")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "cron.log"

    cmd = ["uv", "run", "python", "-m", spec["module"], *args, *extra_args]
    # --force 는 그 인자를 정의한 모듈(LLM 러너)에만 전달. 데이터 파이프라인 모듈들은
    # --force 를 모르므로 붙이면 argparse 가 즉시 거부(exit 2)해 run_tracking 전에 죽는다
    # → UI 에 실행중/로그가 안 뜬다. 데이터 파이프라인 중복 방지는 API 레이어
    # (check_can_run_pipeline)가 전담하므로 모듈에 --force 를 넘길 필요가 없다.
    if force and spec["module"] == "kr_pipeline.llm_runner":
        cmd.append("--force")

    log_file = log_path.open("a")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_file.close()
    return {"pid": proc.pid, "command": " ".join(cmd), "proc": proc}


def wait_for_run_registration(
    conn, pipeline_id: str, proc, *, timeout_s: float = 2.5, poll_interval: float = 0.2
) -> dict:
    """spawn 후 자식이 pipeline_runs 에 running 행을 등록할 때까지 짧게 대기.

    목적 둘:
    1. 즉사 가시화 — 자식이 run_tracking 전에 죽으면(argparse exit 2,
       import error, uv 문제) API 는 200+pid 를 돌려줬는데 run 행/로그가 없어
       UI 에선 '눌렀는데 아무 일 없음'이 됐다 → died 로 감지해 에러 응답.
    2. TOCTOU 잔여 틈새 축소 — 이 대기 동안 요청의 advisory xact lock 이
       유지되므로, 자식이 등록을 마친 뒤에야 다음 요청이 check 를 통과한다.

    Returns: {"status": "registered" | "died" | "timeout", "returncode": int|None}
    timeout 은 fail-open(정상 진행) — 느린 부팅을 실패로 오판하지 않는다.
    """
    import time

    spec = get_spec(pipeline_id)
    pipeline_db = spec["pipeline_db_name"]
    prefix = spec.get("mode_prefix")

    deadline = time.monotonic() + timeout_s
    while True:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT mode FROM pipeline_runs WHERE pipeline = %s AND status = 'running' "
                "ORDER BY id DESC LIMIT 5",
                (pipeline_db,),
            )
            rows = cur.fetchall()
        if any(matches_mode_prefix(m, prefix) for (m,) in rows):
            return {"status": "registered", "returncode": None}
        rc = proc.poll()
        if rc is not None:
            if rc == 0:
                # 초단기 작업이 이미 정상 종료(success 행) — 등록으로 간주
                return {"status": "registered", "returncode": 0}
            return {"status": "died", "returncode": rc}
        if time.monotonic() >= deadline:
            return {"status": "timeout", "returncode": None}
        time.sleep(poll_interval)
