# 전체 Pipeline 운영 대시보드 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 `/runner` 페이지 (LLM 3 카드만) 를 모든 cron 작업 (universe + ohlcv + weekly + indicators + market_context + corporate_actions + LLM) 통합 운영 대시보드로 확장. 테이블 형식 + 모드 선택 모달로 수동 실행. Cron 통합 관리 (옵션 A: 한 마커, 전부 vs 전무).

**Architecture:** `PIPELINE_SPECS` dict 로 모든 pipeline 의 module/modes/default_cron 추상화. `runner_service` 확장으로 동적 subprocess spawn. Frontend 는 spec 목록을 동적으로 받아 테이블 렌더링 + 그룹별 표시.

**Tech Stack:** Python (subprocess, dataclasses), FastAPI / TypeScript, React, TanStack Query, lucide-react.

**Spec:** 별도 spec 없이 검토 답변 기반. 핵심 결정:
- Phase 1: PIPELINE_SPECS + Summary 확장 + Runner 일반화
- Phase 2: 테이블 + 모드 선택 모달
- Phase 3 (옵션 A): cron_manager.DEFAULT_CRON_LINES 를 PIPELINE_SPECS 로 동적 생성

---

## ⚙️ Autonomous Execution Protocol

**자율 실행 모드.**

### Goal State

다음 조건 모두 충족 시 종료:

1. 모든 task 체크박스 완료
2. Backend 회귀: 기존 257 passing 유지 + 신규 ~12 추가
3. Frontend tsc 0 errors
4. `/runner` 페이지에서 10+ pipeline 항목 테이블로 표시
5. 각 행 [▶] 클릭 시 모드 선택 모달
6. CLI smoke:
   - `curl /api/pipelines` → 10+ spec
   - `curl /api/runs/summary` → 모든 pipeline 의 last_run + next_scheduled
   - `curl -X POST /api/runner/run -d '{"pipeline_id":"performance"}'` → 200
7. `git status` clean

### 무엇을 하지 말 것

- 옵션 C (DB 기반 schedule) — Phase 3 는 옵션 A 만
- 모든 인자를 UI 에 노출 (default 만 사용)
- 시스템 권한 필요한 작업
- 외부 인증/IP filter

---

## 사전 조건

- HEAD: `d09d208` 또는 이후 (Runner Dashboard Plan 완료)
- 기존 `runner_service`, `cron_manager`, `RunnerPage` 작동 확인
- `pipeline_runs` 테이블이 모든 cron 작업 자동 기록 (확인됨)

---

## Task 1: `pipeline_specs.py` — 모든 pipeline 추상화

**Files:**
- Create: `kr_pipeline/llm_runner/pipeline_specs.py`
- Create: `tests/test_pipeline_specs.py`

핵심 추상화. 모든 cron 작업의 module/modes/default_cron 한 곳에서 정의.

- [ ] **Step 1: 테스트 작성**

`tests/test_pipeline_specs.py`:

```python
"""PIPELINE_SPECS 검증 — 모든 cron 작업 정의."""


def test_pipeline_specs_has_required_groups():
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    groups = {s["group"] for s in PIPELINE_SPECS}
    assert {"data", "indicators", "llm"}.issubset(groups)


def test_pipeline_specs_has_all_modules():
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    ids = {s["id"] for s in PIPELINE_SPECS}
    required = {
        "universe", "ohlcv", "weekly", "corporate-actions",
        "indicators-daily", "indicators-weekly", "market-context",
        "llm-full-daily", "llm-weekend", "llm-performance",
    }
    assert required.issubset(ids), f"missing: {required - ids}"


def test_each_spec_has_required_fields():
    from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS

    for spec in PIPELINE_SPECS:
        assert "id" in spec
        assert "group" in spec
        assert "label" in spec
        assert "module" in spec
        assert "modes" in spec and len(spec["modes"]) > 0
        assert "default_cron" in spec
        assert "pipeline_db_name" in spec  # pipeline_runs.pipeline 값
        for mode in spec["modes"]:
            assert "id" in mode
            assert "label" in mode
            assert "args" in mode  # list of CLI args


def test_get_spec_by_id():
    from kr_pipeline.llm_runner.pipeline_specs import get_spec

    spec = get_spec("ohlcv")
    assert spec is not None
    assert spec["module"] == "kr_pipeline.ohlcv"
    assert any(m["id"] == "incremental" for m in spec["modes"])


def test_get_spec_returns_none_for_unknown():
    from kr_pipeline.llm_runner.pipeline_specs import get_spec
    assert get_spec("nonexistent") is None


def test_get_mode_returns_args():
    from kr_pipeline.llm_runner.pipeline_specs import get_mode_args

    args = get_mode_args("ohlcv", "incremental")
    assert "--mode=incremental" in args


def test_get_mode_args_unknown_returns_none():
    from kr_pipeline.llm_runner.pipeline_specs import get_mode_args
    assert get_mode_args("ohlcv", "nonexistent") is None


def test_pipeline_db_name_matches_existing_runs():
    """pipeline_db_name 이 pipeline_runs 의 실제 pipeline 값과 매칭."""
    from kr_pipeline.llm_runner.pipeline_specs import get_spec

    # 기존 pipeline_runs 의 pipeline 값
    assert get_spec("universe")["pipeline_db_name"] == "universe"
    assert get_spec("ohlcv")["pipeline_db_name"] == "ohlcv"
    assert get_spec("weekly")["pipeline_db_name"] == "weekly"
    assert get_spec("indicators-daily")["pipeline_db_name"] == "indicators"
    assert get_spec("indicators-weekly")["pipeline_db_name"] == "indicators"
    assert get_spec("market-context")["pipeline_db_name"] == "market_context"
    assert get_spec("corporate-actions")["pipeline_db_name"] == "corporate_actions"
    assert get_spec("llm-full-daily")["pipeline_db_name"] == "llm_daily_delta"
    assert get_spec("llm-weekend")["pipeline_db_name"] == "llm_weekend"
    assert get_spec("llm-performance")["pipeline_db_name"] == "llm_performance"
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_pipeline_specs.py -v
```

Expected: ImportError.

- [ ] **Step 3: 구현**

`kr_pipeline/llm_runner/pipeline_specs.py`:

```python
"""모든 pipeline (cron 작업) 추상화.

frontend / backend 양쪽이 참조하는 단일 진실. 각 pipeline 의:
  - id: UI 식별자 (slug)
  - group: 'data' | 'indicators' | 'llm'
  - label: 사용자 표시명 (한국어)
  - module: subprocess 호출 시 `python -m {module}` 모듈명
  - pipeline_db_name: pipeline_runs.pipeline 컬럼 값 (지표 daily/weekly 는
                     같은 'indicators' 이므로 params 로 구분)
  - modes: 실행 모드 리스트 [{id, label, args}]
  - default_cron: cron 표현식 (incremental 또는 default 기준)
  - params_filter: 같은 pipeline_db_name 안에서 daily/weekly 구분용 (옵션)
"""
from __future__ import annotations


PIPELINE_SPECS: list[dict] = [
    # ─── 데이터 적재 ──────────────────────────────────────────────
    {
        "id": "universe",
        "group": "data",
        "label": "Universe (종목 목록)",
        "module": "kr_pipeline.universe",
        "pipeline_db_name": "universe",
        "modes": [
            {"id": "default", "label": "전체 갱신", "args": []},
        ],
        "default_cron": "0 4 1 * *",
    },
    {
        "id": "ohlcv",
        "group": "data",
        "label": "OHLCV (일봉)",
        "module": "kr_pipeline.ohlcv",
        "pipeline_db_name": "ohlcv",
        "modes": [
            {"id": "incremental", "label": "증분 (30일)",
             "args": ["--mode=incremental", "--window-days=30"]},
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--mode=full-refresh"]},
            {"id": "backfill", "label": "백필 (1년)",
             "args": ["--mode=backfill", "--years=1"]},
        ],
        "default_cron": "30 18 * * 1-5",
    },
    {
        "id": "weekly",
        "group": "data",
        "label": "Weekly (주봉)",
        "module": "kr_pipeline.weekly",
        "pipeline_db_name": "weekly",
        "modes": [
            {"id": "incremental", "label": "증분 (4주)",
             "args": ["--mode=incremental", "--window-weeks=4"]},
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--mode=full-refresh"]},
            {"id": "backfill", "label": "백필",
             "args": ["--mode=backfill"]},
        ],
        "default_cron": "0 3 * * 6",
    },
    {
        "id": "corporate-actions",
        "group": "data",
        "label": "Corporate Actions",
        "module": "kr_pipeline.corporate_actions",
        "pipeline_db_name": "corporate_actions",
        "modes": [
            {"id": "incremental", "label": "증분 (7일)",
             "args": ["--mode=incremental", "--window-days=7"]},
            {"id": "backfill", "label": "백필 (5년)",
             "args": ["--mode=backfill", "--years=5"]},
            {"id": "refresh-mapping", "label": "기업코드 매핑 갱신",
             "args": ["--mode=refresh-mapping"]},
        ],
        "default_cron": "30 4 * * 6",
    },

    # ─── 지표 계산 ────────────────────────────────────────────────
    {
        "id": "indicators-daily",
        "group": "indicators",
        "label": "Indicators (일봉)",
        "module": "kr_pipeline.indicators",
        "pipeline_db_name": "indicators",
        "params_filter": {"target": "daily"},
        "modes": [
            {"id": "incremental", "label": "증분 (30일)",
             "args": ["--target=daily", "--mode=incremental", "--window-days=30"]},
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--target=daily", "--mode=full-refresh"]},
            {"id": "backfill", "label": "백필",
             "args": ["--target=daily", "--mode=backfill"]},
        ],
        "default_cron": "0 19 * * 1-5",
    },
    {
        "id": "indicators-weekly",
        "group": "indicators",
        "label": "Indicators (주봉)",
        "module": "kr_pipeline.indicators",
        "pipeline_db_name": "indicators",
        "params_filter": {"target": "weekly"},
        "modes": [
            {"id": "incremental", "label": "증분 (4주)",
             "args": ["--target=weekly", "--mode=incremental", "--window-weeks=4"]},
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--target=weekly", "--mode=full-refresh"]},
            {"id": "backfill", "label": "백필",
             "args": ["--target=weekly", "--mode=backfill"]},
        ],
        "default_cron": "0 4 * * 6",
    },
    {
        "id": "market-context",
        "group": "indicators",
        "label": "Market Context",
        "module": "kr_pipeline.market_context",
        "pipeline_db_name": "market_context",
        "modes": [
            {"id": "incremental", "label": "증분 (30일)",
             "args": ["--mode=incremental", "--window-days=30"]},
            {"id": "full-refresh", "label": "전체 새로고침",
             "args": ["--mode=full-refresh"]},
            {"id": "backfill", "label": "백필",
             "args": ["--mode=backfill"]},
        ],
        "default_cron": "30 19 * * 1-5",
    },

    # ─── LLM 분석 ────────────────────────────────────────────────
    {
        "id": "llm-full-daily",
        "group": "llm",
        "label": "LLM 평일 전체 분석",
        "module": "kr_pipeline.llm_runner",
        "pipeline_db_name": "llm_daily_delta",
        "modes": [
            {"id": "default", "label": "평일 통합 (dry-run)",
             "args": ["--mode=full-daily", "--dry-run"]},
            {"id": "real", "label": "평일 통합 (실제 호출)",
             "args": ["--mode=full-daily"]},
        ],
        "default_cron": "30 16 * * 1-5",
    },
    {
        "id": "llm-weekend",
        "group": "llm",
        "label": "LLM 주말 분류",
        "module": "kr_pipeline.llm_runner",
        "pipeline_db_name": "llm_weekend",
        "modes": [
            {"id": "default", "label": "주말 batch (dry-run)",
             "args": ["--mode=weekend", "--dry-run"]},
            {"id": "real", "label": "주말 batch (실제 호출)",
             "args": ["--mode=weekend"]},
        ],
        "default_cron": "20 3 * * 6",
    },
    {
        "id": "llm-performance",
        "group": "llm",
        "label": "LLM 성과 backfill",
        "module": "kr_pipeline.llm_runner",
        "pipeline_db_name": "llm_performance",
        "modes": [
            {"id": "default", "label": "Performance backfill",
             "args": ["--mode=performance"]},
        ],
        "default_cron": "0 23 * * *",
    },
]


def get_spec(pipeline_id: str) -> dict | None:
    for spec in PIPELINE_SPECS:
        if spec["id"] == pipeline_id:
            return spec
    return None


def get_mode_args(pipeline_id: str, mode_id: str) -> list[str] | None:
    spec = get_spec(pipeline_id)
    if spec is None:
        return None
    for mode in spec["modes"]:
        if mode["id"] == mode_id:
            return mode["args"]
    return None


def get_default_cron_lines() -> list[str]:
    """모든 PIPELINE_SPECS 의 default_cron + 첫 번째 (incremental/default) 모드 args 로 cron 라인 생성."""
    from pathlib import Path
    project_dir = Path(__file__).parent.parent.parent.resolve()
    lines = []
    for spec in PIPELINE_SPECS:
        default_mode = spec["modes"][0]  # 첫 번째 모드 = incremental 또는 default
        args_str = " ".join(default_mode["args"])
        cron_line = (
            f"{spec['default_cron']}  cd {project_dir} && "
            f"uv run python -m {spec['module']} {args_str}".rstrip()
            + " >> $HOME/.kr-by-claude/cron.log 2>&1"
        )
        lines.append(cron_line)
    return lines
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/test_pipeline_specs.py -v
```

Expected: 8 passed.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/pipeline_specs.py tests/test_pipeline_specs.py
git commit -m "feat(llm_runner): pipeline_specs — 모든 cron 작업 추상화"
```

---

## Task 2: `runner_service` 확장 + `cron_manager.DEFAULT_CRON_LINES` 일반화

**Files:**
- Modify: `api/services/runner_service.py`
- Modify: `kr_pipeline/llm_runner/cron_manager.py`
- Modify: `tests/test_api_runner_service.py`

기존 `MODE_TO_PIPELINE` 을 PIPELINE_SPECS 기반으로 일반화. cron_manager 의 DEFAULT_CRON_LINES 도 동적 생성.

- [ ] **Step 1: 기존 코드 확인**

```bash
grep -n "MODE_TO_PIPELINE\|DEFAULT_CRON_LINES" /Users/hank.es/git/personal/kr-by-claude/api/services/runner_service.py /Users/hank.es/git/personal/kr-by-claude/kr_pipeline/llm_runner/cron_manager.py
```

- [ ] **Step 2: runner_service 확장**

기존 `MODE_TO_PIPELINE` dict 는 유지 (LLM runner mode → pipeline 매핑). 추가로 `check_can_run_pipeline` + `spawn_pipeline` 함수 도입.

`api/services/runner_service.py` 끝에 append:

```python
from kr_pipeline.llm_runner.pipeline_specs import get_spec, get_mode_args


def check_can_run_pipeline(
    conn: Connection,
    pipeline_id: str,
    *,
    force: bool = False,
) -> dict:
    """PIPELINE_SPECS 기반 중복 방지 체크.

    pipeline_id 가 'indicators-daily' / 'indicators-weekly' 같이 같은
    pipeline_db_name 을 공유하면 params_filter 로 구분.
    """
    spec = get_spec(pipeline_id)
    if spec is None:
        return {"can_run": False, "reason": "unknown_pipeline"}

    pipeline_db = spec["pipeline_db_name"]
    params_filter = spec.get("params_filter")

    # 1. running 체크
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, started_at, params FROM pipeline_runs
             WHERE pipeline = %s AND status = 'running'
             ORDER BY id DESC LIMIT 5
            """,
            (pipeline_db,),
        )
        running_rows = cur.fetchall()

    for row in running_rows:
        run_id, started_at, params = row
        if _matches_filter(params, params_filter):
            return {
                "can_run": False,
                "reason": "already_running",
                "existing_run_id": run_id,
                "existing_run_summary": {"started_at": started_at.isoformat()},
            }

    if force:
        return {"can_run": True, "reason": "ok", "existing_run_id": None}

    # 2. 오늘 success 체크 (Asia/Seoul 기준)
    today = date.today()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, started_at, finished_at, rows_affected, params
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
        run_id, started_at, finished_at, rows_affected, params = row
        if _matches_filter(params, params_filter):
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


def _matches_filter(params: dict | None, filter_: dict | None) -> bool:
    """params_filter 가 None 이면 무조건 매치. 있으면 모든 key/value 매치."""
    if filter_ is None:
        return True
    if params is None:
        return False
    return all(params.get(k) == v for k, v in filter_.items())


def spawn_pipeline(
    pipeline_id: str,
    mode_id: str,
) -> dict:
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
```

- [ ] **Step 3: cron_manager.DEFAULT_CRON_LINES 동적 생성**

`kr_pipeline/llm_runner/cron_manager.py` 의 기존 `DEFAULT_CRON_LINES` 정의를 다음으로 교체:

```python
# 기존:
# DEFAULT_CRON_LINES = [...]

# 변경 후:
def _get_default_cron_lines() -> list[str]:
    """PIPELINE_SPECS 기반 동적 생성. import 순환 회피 위해 함수 안에서 import."""
    from kr_pipeline.llm_runner.pipeline_specs import get_default_cron_lines
    return get_default_cron_lines()


# 모듈 로드 시 한 번만 계산. 단 lazy import 패턴 사용.
DEFAULT_CRON_LINES = _get_default_cron_lines()
```

순환 import 피하려면 함수 안에서 import.

- [ ] **Step 4: 기존 runner_service 테스트가 여전히 통과하는지 + 신규 테스트 추가**

`tests/test_api_runner_service.py` 끝에 append:

```python
def test_check_can_run_pipeline_with_target_filter(db):
    """indicators-daily vs indicators-weekly: 같은 pipeline_db_name 이지만 params_filter 로 구분."""
    from datetime import datetime, timezone
    from api.services.runner_service import check_can_run_pipeline

    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at, params)
               VALUES ('indicators', 'incremental', 'success', %s, %s, %s::jsonb)""",
            (datetime.now(timezone.utc), datetime.now(timezone.utc), '{"target": "daily"}'),
        )

    # daily 는 오늘 success 있음 → 거부
    result = check_can_run_pipeline(db, pipeline_id="indicators-daily")
    assert result["can_run"] is False
    assert result["reason"] == "duplicate"

    # weekly 는 오늘 success 없음 → 허용
    result = check_can_run_pipeline(db, pipeline_id="indicators-weekly")
    assert result["can_run"] is True


def test_spawn_pipeline_universe(mocker):
    from api.services.runner_service import spawn_pipeline

    fake_proc = mocker.Mock()
    fake_proc.pid = 55555
    mock_popen = mocker.patch("subprocess.Popen", return_value=fake_proc)

    result = spawn_pipeline("universe", "default")
    assert result["pid"] == 55555
    args = mock_popen.call_args[0][0]
    assert "kr_pipeline.universe" in args


def test_spawn_pipeline_with_indicator_target(mocker):
    from api.services.runner_service import spawn_pipeline

    fake_proc = mocker.Mock()
    fake_proc.pid = 66666
    mock_popen = mocker.patch("subprocess.Popen", return_value=fake_proc)

    result = spawn_pipeline("indicators-weekly", "incremental")
    args = mock_popen.call_args[0][0]
    assert "kr_pipeline.indicators" in args
    assert "--target=weekly" in args
    assert "--mode=incremental" in args
```

- [ ] **Step 5: 테스트 통과**

```bash
uv run pytest tests/test_api_runner_service.py tests/test_pipeline_specs.py tests/test_cron_manager.py -v
```

Expected: 기존 5 + 신규 3 + 8 + 10 = 26 passed.

- [ ] **Step 6: 커밋**

```bash
git add api/services/runner_service.py kr_pipeline/llm_runner/cron_manager.py tests/test_api_runner_service.py
git commit -m "feat: runner_service.check_can_run_pipeline + spawn_pipeline + DEFAULT_CRON_LINES 일반화"
```

---

## Task 3: API `/api/pipelines` + `/api/runs/summary` 확장 + `/api/runner/run` 확장

**Files:**
- Create: `api/routers/pipelines.py`
- Modify: `api/main.py`
- Modify: `api/routers/runs.py` (summary endpoint)
- Modify: `api/routers/runner.py` (run endpoint)
- Modify: `tests/test_api_runs_summary.py`
- Modify: `tests/test_api_runner.py`

- [ ] **Step 1: `/api/pipelines` 신규 router**

`api/routers/pipelines.py`:

```python
from fastapi import APIRouter

from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS


router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


@router.get("")
def list_pipelines():
    """모든 pipeline spec 반환 (frontend 가 동적 렌더링용)."""
    return {"pipelines": PIPELINE_SPECS}
```

`api/main.py` 에 마운트 추가:

```python
from api.routers import pipelines
app.include_router(pipelines.router)
```

- [ ] **Step 2: `/api/runs/summary` 확장**

`api/routers/runs.py` 의 `get_summary` 함수를 다음으로 교체:

```python
from kr_pipeline.llm_runner.pipeline_specs import PIPELINE_SPECS


@router.get("/summary")
def get_summary(conn: Connection = Depends(get_conn)):
    """모든 pipeline 의 last_run + next_scheduled."""
    result = []
    with conn.cursor() as cur:
        for spec in PIPELINE_SPECS:
            pipeline_db = spec["pipeline_db_name"]
            params_filter = spec.get("params_filter")

            # 같은 pipeline_db_name 의 최근 5건 중 params_filter 매치하는 첫 row
            cur.execute(
                """
                SELECT id, status, rows_affected, error, started_at, finished_at, params
                  FROM pipeline_runs
                 WHERE pipeline = %s
                 ORDER BY id DESC LIMIT 10
                """,
                (pipeline_db,),
            )
            rows = cur.fetchall()
            last_run = None
            for row in rows:
                params = row[6]
                if _matches_filter(params, params_filter):
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


def _matches_filter(params, filter_):
    if filter_ is None:
        return True
    if params is None:
        return False
    return all(params.get(k) == v for k, v in filter_.items())
```

기존 `MODE_SCHEDULES` 와 LLM 만 처리하던 코드는 제거. `_next_scheduled` 는 그대로 유지.

- [ ] **Step 3: `/api/runner/run` 확장**

`api/routers/runner.py` 의 `RunRequest` + `run` 함수 다음으로 교체:

```python
from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from pydantic import BaseModel

from api.deps import get_conn
from api.services.runner_service import (
    check_can_run_pipeline,
    spawn_pipeline,
)


router = APIRouter(prefix="/api/runner", tags=["runner"])


class RunRequest(BaseModel):
    pipeline_id: str
    mode_id: str = "default"  # 또는 첫 번째 mode (대부분 incremental)
    force: bool = False


@router.post("/run")
def run(req: RunRequest, conn: Connection = Depends(get_conn)):
    check = check_can_run_pipeline(conn, req.pipeline_id, force=req.force)
    if not check["can_run"]:
        raise HTTPException(
            409,
            detail={
                "reason": check["reason"],
                "existing_run_id": check.get("existing_run_id"),
                "existing_run_summary": check.get("existing_run_summary"),
                "message": (
                    "이미 실행 중입니다."
                    if check["reason"] == "already_running"
                    else "오늘 같은 작업이 이미 성공 실행되었습니다. force=true 로 재실행 가능."
                ),
            },
        )

    try:
        spawn_result = spawn_pipeline(req.pipeline_id, req.mode_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "pipeline_id": req.pipeline_id,
        "mode_id": req.mode_id,
        "pid": spawn_result["pid"],
        "command": spawn_result["command"],
    }
```

- [ ] **Step 4: 신규 테스트 추가**

`tests/test_api_pipelines.py`:

```python
import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_list_pipelines_returns_all_specs(client):
    r = client.get("/api/pipelines")
    assert r.status_code == 200
    data = r.json()
    assert "pipelines" in data
    ids = {p["id"] for p in data["pipelines"]}
    assert {"universe", "ohlcv", "weekly", "corporate-actions",
            "indicators-daily", "indicators-weekly", "market-context",
            "llm-full-daily", "llm-weekend", "llm-performance"}.issubset(ids)


def test_summary_includes_all_pipelines(client):
    r = client.get("/api/runs/summary")
    assert r.status_code == 200
    data = r.json()
    assert "pipelines" in data
    assert len(data["pipelines"]) >= 10
    for p in data["pipelines"]:
        assert "pipeline_id" in p
        assert "group" in p
        assert "label" in p
        assert "last_run" in p
        assert "next_scheduled" in p
        assert "modes" in p
```

기존 `tests/test_api_runs_summary.py` 의 테스트는 응답 구조가 바뀌었으므로 수정:

```python
# 기존: data["modes"], m["mode"]
# 변경: data["pipelines"], p["pipeline_id"]
```

- [ ] **Step 5: 기존 runner test 수정**

`tests/test_api_runner.py` — `RunRequest.mode` → `pipeline_id`/`mode_id` 로 바꿈:

```python
def test_run_invalid_pipeline_returns_400(client):
    r = client.post("/api/runner/run", json={"pipeline_id": "invalid", "mode_id": "default"})
    # 400 (spawn_pipeline ValueError) 또는 409 (check_can_run unknown_pipeline)
    assert r.status_code in (400, 409)


def test_run_universe_spawns(client, mocker):
    fake_proc = mocker.Mock()
    fake_proc.pid = 99999
    mocker.patch("subprocess.Popen", return_value=fake_proc)

    r = client.post("/api/runner/run", json={"pipeline_id": "universe", "mode_id": "default"})
    assert r.status_code in (200, 409)
    if r.status_code == 200:
        data = r.json()
        assert "pid" in data
        assert "command" in data
        assert data["pipeline_id"] == "universe"


def test_run_duplicate_returns_409(client, db):
    from datetime import datetime, timezone
    from api.deps import get_conn

    def override_get_conn():
        yield db

    app.dependency_overrides[get_conn] = override_get_conn
    try:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at)
                   VALUES ('llm_performance', 'performance', 'success', %s, %s)""",
                (datetime.now(timezone.utc), datetime.now(timezone.utc)),
            )

        r = client.post("/api/runner/run", json={"pipeline_id": "llm-performance", "mode_id": "default"})
        assert r.status_code == 409
        assert "existing_run_id" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_conn, None)
```

- [ ] **Step 6: 테스트 통과**

```bash
uv run pytest tests/test_api_pipelines.py tests/test_api_runs_summary.py tests/test_api_runner.py -v
```

Expected: 2 + 2 + 3 = 7 passed.

- [ ] **Step 7: 커밋**

```bash
git add api/routers/ tests/test_api_pipelines.py tests/test_api_runs_summary.py tests/test_api_runner.py
git commit -m "feat(api): /api/pipelines + /summary/runner 확장 — 모든 pipeline 지원"
```

---

## Task 4: Frontend types.ts + RunnerPage 테이블 변환

**Files:**
- Modify: `web/src/lib/types.ts`
- Modify: `web/src/pages/RunnerPage.tsx`

기존 RunnerPage 의 RunCard 3개 그리드를 모든 pipeline 표시하는 테이블로 재작성.

- [ ] **Step 1: types.ts 확장**

기존 `RunSummaryMode` 인터페이스를 변경 + 새 타입 추가:

```typescript
// 기존 RunSummaryMode, RunSummaryResponse 제거 또는 변경:

export interface PipelineMode {
  id: string;
  label: string;
  args: string[];
}

export interface PipelineSpec {
  id: string;
  group: string;
  label: string;
  module: string;
  pipeline_db_name: string;
  modes: PipelineMode[];
  default_cron: string;
}

export interface PipelineSummary {
  pipeline_id: string;
  group: string;
  label: string;
  module: string;
  cron_expression: string;
  last_run: {
    id: number;
    status: string;
    rows_affected: number | null;
    error: string | null;
    started_at: string | null;
    finished_at: string | null;
    duration_seconds: number | null;
  } | null;
  next_scheduled: string | null;
  modes: PipelineMode[];
}

export interface RunSummaryResponse {
  pipelines: PipelineSummary[];
}

// RunResponse 변경:
export interface RunResponse {
  pipeline_id: string;
  mode_id: string;
  pid: number;
  command: string;
}
```

- [ ] **Step 2: RunnerPage 재작성**

`web/src/pages/RunnerPage.tsx` 의 RunCard, RunDialog, RunnerPage 부분 교체. CronManagerSection 은 그대로 유지.

```typescript
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Play,
  CheckCircle2,
  XCircle,
  Clock,
  Settings,
  RefreshCw,
  AlertTriangle,
} from "lucide-react";
import { api, apiUrl } from "../lib/api";
import type {
  RunSummaryResponse,
  PipelineSummary,
  CronStatus,
  CronPreview,
} from "../lib/types";
import { relativeTime } from "../lib/utils";
import { Modal } from "../components/ui/Modal";


const GROUP_LABELS: Record<string, string> = {
  data: "데이터 적재",
  indicators: "지표 계산",
  llm: "LLM 분석",
};

const GROUP_ORDER = ["data", "indicators", "llm"];


function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(0)}초`;
  return `${Math.floor(seconds / 60)}분 ${Math.floor(seconds % 60)}초`;
}

function formatNextSchedule(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const date = d.toLocaleDateString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
  });
  const time = d.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${date} ${time}`;
}


function StatusChip({ status }: { status: string }) {
  if (status === "success")
    return <span className="chip bg-success-soft text-success"><CheckCircle2 size={11} />성공</span>;
  if (status === "failed" || status === "error")
    return <span className="chip bg-danger-soft text-danger"><XCircle size={11} />실패</span>;
  if (status === "running")
    return <span className="chip bg-amber-soft text-amber"><Clock size={11} className="animate-pulse" />실행 중</span>;
  return <span className="chip bg-tint-stone text-muted">{status}</span>;
}


interface RunDialogProps {
  pipeline: PipelineSummary | null;
  onClose: () => void;
}

function RunDialog({ pipeline, onClose }: RunDialogProps) {
  const [modeId, setModeId] = useState<string>("");
  const [force, setForce] = useState(false);
  const qc = useQueryClient();

  // pipeline 바뀌면 첫 번째 mode 로 reset
  if (pipeline && !modeId) {
    setModeId(pipeline.modes[0]?.id ?? "");
  }

  const mutation = useMutation({
    mutationFn: async () => {
      if (!pipeline) throw new Error("no pipeline");
      const res = await fetch(apiUrl("/runner/run"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pipeline_id: pipeline.pipeline_id,
          mode_id: modeId,
          force,
        }),
      });
      if (res.status === 409) {
        const err = await res.json();
        throw new Error(`DUPLICATE:${JSON.stringify(err.detail)}`);
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs-summary"] });
      setModeId("");
      setForce(false);
      onClose();
    },
  });

  if (pipeline === null) return null;

  const selectedMode = pipeline.modes.find((m) => m.id === modeId);
  const isHeavy = selectedMode
    ? selectedMode.label.includes("전체") || selectedMode.label.includes("백필") || selectedMode.label.includes("실제")
    : false;

  return (
    <Modal
      open={pipeline !== null}
      onClose={onClose}
      title={`수동 실행 — ${pipeline.label}`}
      subtitle={pipeline.module}
    >
      <div className="px-6 py-5 space-y-4">
        <div>
          <label className="caps block mb-2">실행 모드</label>
          <div className="flex flex-col gap-2">
            {pipeline.modes.map((m) => (
              <label
                key={m.id}
                className="flex items-center gap-2 cursor-pointer p-2 border border-hairline rounded-lg hover:border-accent"
              >
                <input
                  type="radio"
                  name="mode"
                  value={m.id}
                  checked={modeId === m.id}
                  onChange={(e) => setModeId(e.target.value)}
                  className="accent-accent"
                />
                <span className="text-data text-ink">{m.label}</span>
                <span className="num text-data-xs text-faint ml-auto">
                  {m.args.join(" ")}
                </span>
              </label>
            ))}
          </div>
        </div>

        {isHeavy && (
          <div className="bg-amber-soft border border-amber/30 rounded-xl p-3">
            <div className="flex items-start gap-2">
              <AlertTriangle size={16} className="text-amber shrink-0 mt-0.5" />
              <div className="text-data text-amber">
                무거운 작업입니다 (수 분 ~ 수 시간 소요 가능, 또는 LLM 비용 발생).
              </div>
            </div>
          </div>
        )}

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={force}
            onChange={(e) => setForce(e.target.checked)}
            className="w-4 h-4 accent-accent"
          />
          <span className="text-data text-ink">
            오늘 이미 성공한 경우에도 강제 재실행 (force)
          </span>
        </label>

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-paper border border-hairline rounded-lg text-data font-semibold"
          >
            취소
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={!modeId || mutation.isPending}
            className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold disabled:opacity-50"
          >
            {mutation.isPending ? "실행 중…" : "실행"}
          </button>
        </div>

        {mutation.isError && (
          <div className="text-danger text-data-xs">{String(mutation.error)}</div>
        )}
      </div>
    </Modal>
  );
}


function CronManagerSection() {
  const qc = useQueryClient();
  const statusQ = useQuery<CronStatus>({
    queryKey: ["cron-status"],
    queryFn: () => api<CronStatus>("/cron/status"),
    staleTime: 30_000,
  });

  const [previewAction, setPreviewAction] = useState<
    "register" | "unregister" | null
  >(null);

  const previewQ = useQuery<CronPreview>({
    queryKey: ["cron-preview", previewAction],
    queryFn: () => api<CronPreview>(`/cron/preview?action=${previewAction}`),
    enabled: previewAction !== null,
    staleTime: 0,
  });

  const mutation = useMutation({
    mutationFn: async (action: "register" | "unregister") => {
      const res = await fetch(apiUrl(`/cron/${action}`), { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      setPreviewAction(null);
      qc.invalidateQueries({ queryKey: ["cron-status"] });
    },
  });

  return (
    <section className="bento p-6 mt-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-tint-violet">
            <Settings size={16} className="text-accent" strokeWidth={2} />
          </div>
          <div>
            <div className="text-subhead font-bold text-ink">Cron 통합 관리</div>
            <div className="text-data-xs text-muted mt-0.5">
              모든 cron 작업 (데이터/지표/LLM) 자동 등록 또는 해제. 한 마커 안에서 일괄.
            </div>
          </div>
        </div>
        {statusQ.data && (
          <span
            className={`chip ${
              statusQ.data.registered
                ? "bg-success-soft text-success"
                : "bg-tint-stone text-muted"
            }`}
          >
            {statusQ.data.registered ? "등록됨" : "미등록"}
          </span>
        )}
      </div>

      {statusQ.data && (
        <>
          <div className="num text-data-xs text-muted bg-cream border border-hairline rounded-xl p-3 mb-4 max-h-48 overflow-y-auto">
            {statusQ.data.registered ? (
              <pre className="whitespace-pre-wrap">
                {statusQ.data.lines.join("\n")}
              </pre>
            ) : (
              <span className="text-faint">등록된 cron 라인 없음</span>
            )}
          </div>
          <div className="flex gap-2">
            {!statusQ.data.registered && (
              <button
                onClick={() => setPreviewAction("register")}
                className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold hover:bg-accent-light"
              >
                등록 미리보기
              </button>
            )}
            {statusQ.data.registered && (
              <button
                onClick={() => setPreviewAction("unregister")}
                className="px-4 py-2 bg-paper border border-danger text-danger rounded-lg text-data font-semibold hover:bg-danger-soft"
              >
                해제 미리보기
              </button>
            )}
          </div>
        </>
      )}

      <Modal
        open={previewAction !== null}
        onClose={() => setPreviewAction(null)}
        title={
          previewAction === "register"
            ? "Cron 등록 미리보기"
            : "Cron 해제 미리보기"
        }
        subtitle="변경 후 crontab — 적용 전 확인"
        maxWidth="max-w-3xl"
      >
        <div className="px-6 py-5 space-y-4">
          {previewQ.isLoading && <div className="text-muted">로딩 중…</div>}
          {previewQ.data && (
            <>
              <div>
                <div className="caps mb-2">변경 사항 (diff)</div>
                <pre className="num text-data-xs bg-cream border border-hairline rounded-xl p-3 max-h-48 overflow-auto">
                  {previewQ.data.diff.length > 0
                    ? previewQ.data.diff.join("\n")
                    : "변경 없음"}
                </pre>
              </div>
              <div>
                <div className="caps mb-2">변경 후 전체 crontab</div>
                <pre className="num text-data-xs bg-cream border border-hairline rounded-xl p-3 max-h-64 overflow-auto whitespace-pre-wrap">
                  {previewQ.data.new_crontab_preview}
                </pre>
              </div>
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => setPreviewAction(null)}
                  className="px-4 py-2 bg-paper border border-hairline rounded-lg text-data font-semibold"
                >
                  취소
                </button>
                <button
                  onClick={() => mutation.mutate(previewAction!)}
                  disabled={mutation.isPending}
                  className={`px-4 py-2 rounded-lg text-data font-semibold text-white ${
                    previewAction === "register"
                      ? "bg-accent hover:bg-accent-light"
                      : "bg-danger hover:opacity-90"
                  } disabled:opacity-50`}
                >
                  {mutation.isPending
                    ? "적용 중…"
                    : previewAction === "register"
                    ? "등록 적용"
                    : "해제 적용"}
                </button>
              </div>
              {mutation.isError && (
                <div className="text-danger text-data-xs">
                  {String(mutation.error)}
                </div>
              )}
            </>
          )}
        </div>
      </Modal>
    </section>
  );
}


export default function RunnerPage() {
  const qc = useQueryClient();
  const summaryQ = useQuery<RunSummaryResponse>({
    queryKey: ["runs-summary"],
    queryFn: () => api<RunSummaryResponse>("/runs/summary"),
    refetchInterval: 30_000,
  });

  const [runPipeline, setRunPipeline] = useState<PipelineSummary | null>(null);

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">Runner</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            분석 운영
          </h2>
          <div className="text-data-xs text-muted mt-2">
            모든 cron 작업 (데이터 적재 / 지표 / LLM) 모니터링 + 수동 실행 + Cron 통합 관리
          </div>
        </div>
        <button
          onClick={() => qc.invalidateQueries()}
          className="flex items-center gap-1.5 text-data text-muted hover:text-ink"
        >
          <RefreshCw size={14} />
          새로고침
        </button>
      </header>

      <section className="bento p-2 mb-6 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-hairline">
              <th className="caps text-left px-4 py-3">그룹</th>
              <th className="caps text-left px-4 py-3">작업</th>
              <th className="caps text-left px-4 py-3">마지막 실행</th>
              <th className="caps text-left px-4 py-3">다음 예정</th>
              <th className="caps text-left px-4 py-3">상태</th>
              <th className="caps text-center px-4 py-3 w-20">실행</th>
            </tr>
          </thead>
          <tbody>
            {summaryQ.isLoading && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted">
                  로딩 중…
                </td>
              </tr>
            )}
            {summaryQ.data &&
              GROUP_ORDER.flatMap((group) =>
                summaryQ.data!.pipelines
                  .filter((p) => p.group === group)
                  .map((p, idx, arr) => (
                    <tr
                      key={p.pipeline_id}
                      className="border-b border-hairline last:border-b-0 hover:bg-cream"
                    >
                      <td className="px-4 py-3 text-data text-muted">
                        {idx === 0 ? GROUP_LABELS[group] : ""}
                      </td>
                      <td className="px-4 py-3">
                        <div className="text-data text-ink font-medium">
                          {p.label}
                        </div>
                        <div className="num text-data-xs text-faint mt-0.5">
                          {p.module}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-data text-muted">
                        {p.last_run ? (
                          <>
                            <div>{relativeTime(p.last_run.started_at)}</div>
                            <div className="text-data-xs text-faint mt-0.5">
                              {p.last_run.rows_affected != null
                                ? `${p.last_run.rows_affected.toLocaleString()}건 · `
                                : ""}
                              {formatDuration(p.last_run.duration_seconds)}
                            </div>
                          </>
                        ) : (
                          <span className="text-faint">이력 없음</span>
                        )}
                      </td>
                      <td className="px-4 py-3 num text-data text-muted">
                        {formatNextSchedule(p.next_scheduled)}
                      </td>
                      <td className="px-4 py-3">
                        {p.last_run ? <StatusChip status={p.last_run.status} /> : <span className="text-faint">—</span>}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={() => setRunPipeline(p)}
                          className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-accent text-white hover:bg-accent-light"
                          title="수동 실행"
                        >
                          <Play size={14} />
                        </button>
                      </td>
                    </tr>
                  ))
              )}
          </tbody>
        </table>
      </section>

      <CronManagerSection />

      <RunDialog pipeline={runPipeline} onClose={() => setRunPipeline(null)} />
    </div>
  );
}
```

- [ ] **Step 3: tsc + 커밋**

```bash
cd web && npx tsc --noEmit
cd ..
git add web/src/lib/types.ts web/src/pages/RunnerPage.tsx
git commit -m "feat(web): /runner 전체 pipeline 테이블 + 모드 선택 모달"
```

NO Co-Authored-By trailer.

---

## Task 5: Goal State 검증

- [ ] **Step 1: Backend 전체 회귀**

```bash
cd /Users/hank.es/git/personal/kr-by-claude
uv run pytest 2>&1 | tail -3
```

Expected: 기존 257 + 신규 ~12 = ~269 passed.

- [ ] **Step 2: Frontend tsc**

```bash
cd web && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: Backend live + frontend live**

```bash
pkill -f "uvicorn api.main" 2>&1; sleep 1
cd /Users/hank.es/git/personal/kr-by-claude
uv run uvicorn api.main:app --port 8000 --log-level warning > /tmp/uvicorn.log 2>&1 &
sleep 3

echo "--- /api/pipelines ---"
curl -s http://localhost:8000/api/pipelines | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'pipelines count: {len(d[\"pipelines\"])}')
for p in d['pipelines']:
    print(f'  [{p[\"group\"]:11s}] {p[\"id\"]:22s} modes={len(p[\"modes\"])}')
"

echo ""
echo "--- /api/runs/summary ---"
curl -s http://localhost:8000/api/runs/summary | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'pipelines: {len(d[\"pipelines\"])}')
"

echo ""
echo "--- POST /api/runner/run with pipeline_id ---"
curl -sS -o /tmp/run.json -w 'HTTP %{http_code}\n' -X POST http://localhost:8000/api/runner/run \
  -H 'Content-Type: application/json' \
  -d '{"pipeline_id": "llm-performance", "mode_id": "default", "force": true}'
cat /tmp/run.json | python3 -m json.tool

pkill -f "uvicorn api.main" 2>&1
```

Expected: 10+ pipelines, summary 10+, run 200.

- [ ] **Step 4: git status**

```bash
git status
```

Expected: clean.

---

## Self-Review

✅ **Spec coverage**:
- 모든 cron 작업 모니터링 → Task 1 PIPELINE_SPECS + Task 3 /summary 확장 + Task 4 테이블
- 수동 실행 → Task 2 runner_service 확장 + Task 3 API + Task 4 RunDialog
- Cron 통합 관리 → Task 2 DEFAULT_CRON_LINES 동적 + 기존 cron_manager 그대로

✅ **Placeholder 없음**: 모든 step 에 실제 코드.

⚠️ **알려진 한계**:
- `pipeline_runs.params` JSONB 가 `target` 필드를 갖는지 indicators 파이프라인에서 확인 필요. 만약 없으면 `params_filter` 매칭 실패 → 자율 실행자가 `kr_pipeline/indicators/modes.py` 확인 후 params 에 target 추가하거나 다른 분기 방식 채택.
- `--dry-run` 같은 LLM runner 전용 옵션이 다른 모듈에서 invalid 인데, PIPELINE_SPECS 가 그걸 어떻게 분기하는지: 각 mode 의 args 에 명시적으로 포함시킴 (현재 LLM modes 만 `--dry-run` 있음, 다른 모듈은 없음). OK.

⚠️ **Type consistency**:
- `RunRequest.pipeline_id` + `mode_id` (기존 `mode` 한 필드에서 분리)
- Frontend `RunSummaryResponse.pipelines` (기존 `modes`)
- 위 두 변화로 기존 호출자 (HomePage, 다른 페이지) 영향 없는지 확인. RunnerPage 만 사용 → 영향 없음.

자율 실행자는 위 한계 인지하고 진행.
