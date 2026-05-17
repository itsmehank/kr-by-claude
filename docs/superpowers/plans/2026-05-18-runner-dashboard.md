# LLM Runner Dashboard + Cron 관리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM runner 운영 대시보드 (`/runner` 페이지) 추가 — 모드별 최근 실행 결과 + 다음 스케줄 확인, 수동 실행 트리거 (dry-run default + 비용 확인), Cron 자동 등록/해제 (마커 + 백업 + diff 미리보기). 중복 실행 방지로 같은 영업일 같은 모드 중복 호출 시 기존 결과 반환.

**Architecture:**
- Backend: 3개 신규 모듈 (`cron_manager`, runner subprocess wrapper, API routers).
- Frontend: 1 신규 페이지 (`/runner`) + RunCard / RunControls / CronManager 컴포넌트.
- Cron 자동 관리는 BEGIN/END 마커로 경계 식별 + 변경 전 자동 백업 + diff 미리보기 + 변경 후 일관성 검증.
- 수동 실행은 `subprocess.Popen` fire-and-forget + 진행 상황은 `pipeline_runs` 테이블 polling.

**Tech Stack:** Python (subprocess, pathlib), FastAPI, psycopg / TypeScript, React 19, Tailwind, TanStack Query.

**Spec:** 이번 plan 은 별도 spec 문서 없이 [대화 이력 검토 결과](../specs/) 를 기반으로 작성. 핵심 결정:
- Phase 1: 대시보드 + 중복 방지
- Phase 2: 수동 실행 (dry-run default + 비용 확인 dialog)
- Phase 3 (Level 2): Cron 자동 관리 + 마커 + 백업 + 검증

---

## ⚙️ Autonomous Execution Protocol

**자율 실행 모드.**

### Goal State

다음 조건 모두 충족 시 종료:

1. 모든 task 체크박스 완료
2. 백엔드 회귀: 기존 233 passing 유지 + 신규 ~15 테스트 추가
3. 프론트 `npx tsc --noEmit` 0 errors
4. 백엔드 + 프론트 dev server 동시 가동
5. `/runner` 페이지 정상 렌더 (네 가지 섹션: 모드별 카드 / 다음 스케줄 / 수동 실행 / Cron 관리)
6. CLI 통합:
   - `curl POST /api/runner/run?mode=full-daily&dry_run=true` → 200 + run_id
   - `crontab -l` 에 마커 영역 있고/없고 정상 동작
7. `git status` clean (`.claude/` 만 untracked, gitignored)

### 알려진 한계

- subprocess.Popen 은 fire-and-forget. 프로세스 죽으면 `pipeline_runs.status` 가 'running' 으로 stuck 가능. 향후 별도 watchdog 가능하나 현 단계 out of scope.
- crontab 관리 는 user-level 만 (`crontab -e`). 시스템 cron 안 건드림.
- LLM 비용 보호: dry-run default + 실제 호출 모드는 확인 dialog. 의도적 misclick 까지는 보호 못 함.

### 무엇을 하지 말 것

- Celery / RQ / 별도 작업 큐 도입 (과스펙)
- DB 기반 별도 스케줄러 (cron 대체) — Level 3, 본 plan 외
- 시스템 권한 (`sudo` 필요한 작업)
- 외부 인증/IP filter — 현 환경 localhost 단독

---

## 사전 조건

- HEAD: `4547be6` (또는 이후, #4 LLM runner 작업 완료 시점)
- `kr_pipeline/llm_runner/__main__.py` 6 모드 모두 정상 작동
- `pipeline_runs` 테이블에 LLM runner 실행 이력 기록됨
- macOS / Linux (crontab 명령어 가용)

---

## Task 1: `cron_manager.py` — crontab read/write 기본

**Files:**
- Create: `kr_pipeline/llm_runner/cron_manager.py`
- Create: `tests/test_cron_manager.py`

마커 기반 cron 영역 관리, 백업, 검증.

- [ ] **Step 1: 테스트 작성**

`tests/test_cron_manager.py`:

```python
"""cron_manager — crontab read/write + 마커 + 백업."""
import pytest
from pathlib import Path


def test_extract_managed_lines_from_text():
    """마커 사이의 라인만 추출."""
    from kr_pipeline.llm_runner.cron_manager import extract_managed_lines

    crontab_text = """
0 5 * * * /usr/local/bin/my-backup.sh

# === kr-by-claude-llm-runner BEGIN ===
30 16 * * 1-5 /path/llm_runner --mode=full-daily
20 3 * * 6 /path/llm_runner --mode=weekend
# === kr-by-claude-llm-runner END ===

0 4 * * * /usr/local/bin/log-cleanup.sh
"""
    managed = extract_managed_lines(crontab_text)
    assert len(managed) == 2
    assert "--mode=full-daily" in managed[0]
    assert "--mode=weekend" in managed[1]


def test_extract_returns_empty_when_no_markers():
    from kr_pipeline.llm_runner.cron_manager import extract_managed_lines
    assert extract_managed_lines("0 5 * * * /bin/foo") == []


def test_replace_managed_block_preserves_other_lines():
    """마커 영역만 교체. 다른 라인 보존."""
    from kr_pipeline.llm_runner.cron_manager import replace_managed_block

    original = """0 5 * * * /backup
# === kr-by-claude-llm-runner BEGIN ===
old_line
# === kr-by-claude-llm-runner END ===
0 6 * * * /other"""

    new = replace_managed_block(original, ["new_line_a", "new_line_b"])
    assert "/backup" in new
    assert "/other" in new
    assert "new_line_a" in new
    assert "new_line_b" in new
    assert "old_line" not in new


def test_replace_managed_block_appends_if_no_markers():
    """마커 없으면 끝에 새 블록 append."""
    from kr_pipeline.llm_runner.cron_manager import replace_managed_block

    original = "0 5 * * * /backup\n"
    new = replace_managed_block(original, ["new_line"])
    assert "/backup" in new
    assert "kr-by-claude-llm-runner BEGIN" in new
    assert "kr-by-claude-llm-runner END" in new
    assert "new_line" in new


def test_remove_managed_block():
    """마커 영역 전체 제거."""
    from kr_pipeline.llm_runner.cron_manager import remove_managed_block

    original = """0 5 * * * /backup
# === kr-by-claude-llm-runner BEGIN ===
line1
line2
# === kr-by-claude-llm-runner END ===
0 6 * * * /other"""

    new = remove_managed_block(original)
    assert "/backup" in new
    assert "/other" in new
    assert "kr-by-claude-llm-runner" not in new
    assert "line1" not in new


def test_backup_writes_timestamp_file(tmp_path, monkeypatch):
    """현재 crontab 을 timestamp 파일로 저장."""
    from kr_pipeline.llm_runner.cron_manager import backup_crontab

    monkeypatch.setattr(
        "kr_pipeline.llm_runner.cron_manager.BACKUP_DIR",
        tmp_path / "backups",
    )

    backup_path = backup_crontab("0 5 * * * /test")
    assert backup_path.exists()
    assert "0 5 * * * /test" in backup_path.read_text()
    assert "crontab-" in backup_path.name


def test_diff_managed_block_shows_changes():
    """현재 vs 새 라인 diff."""
    from kr_pipeline.llm_runner.cron_manager import diff_managed_block

    current_lines = ["old_a", "old_b"]
    new_lines = ["new_a", "new_b", "new_c"]

    diff = diff_managed_block(current_lines, new_lines)
    assert any("-old_a" in line for line in diff)
    assert any("+new_a" in line for line in diff)
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_cron_manager.py -v
```

Expected: ImportError.

- [ ] **Step 3: 구현**

`kr_pipeline/llm_runner/cron_manager.py`:

```python
"""crontab read/write 관리 — 마커 기반 영역, 자동 백업, diff 미리보기.

안전장치:
- BEGIN/END 마커 안만 read/write. 사용자가 손으로 추가한 다른 라인 절대 안 건드림.
- 변경 직전 timestamp 백업 (~/.kr-by-claude/cron-backups/)
- replace 후 일관성 검증 (외부에서 사용)
"""
from __future__ import annotations

import difflib
import re
import subprocess
from datetime import datetime
from pathlib import Path


BEGIN_MARKER = "# === kr-by-claude-llm-runner BEGIN (auto-managed, do not edit by hand) ==="
END_MARKER = "# === kr-by-claude-llm-runner END ==="

BACKUP_DIR = Path.home() / ".kr-by-claude" / "cron-backups"


def get_current_crontab() -> str:
    """현재 user crontab 텍스트 반환. 없으면 빈 문자열."""
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
        # rc=1 이면 보통 "no crontab for user" — 빈 crontab 으로 처리
        return ""
    except FileNotFoundError:
        raise RuntimeError("crontab command not found")


def install_crontab(text: str) -> None:
    """주어진 텍스트로 crontab 덮어쓰기."""
    result = subprocess.run(
        ["crontab", "-"],
        input=text,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"crontab install failed: {result.stderr}")


def extract_managed_lines(crontab_text: str) -> list[str]:
    """마커 사이의 cron 라인 추출. 마커 자체 + 빈 줄 제외."""
    if BEGIN_MARKER not in crontab_text or END_MARKER not in crontab_text:
        return []

    pattern = re.escape(BEGIN_MARKER) + r"(.*?)" + re.escape(END_MARKER)
    match = re.search(pattern, crontab_text, re.DOTALL)
    if not match:
        return []

    lines = match.group(1).strip().splitlines()
    return [l for l in lines if l.strip() and not l.strip().startswith("#")]


def replace_managed_block(crontab_text: str, new_lines: list[str]) -> str:
    """마커 영역을 new_lines 로 교체. 마커 없으면 끝에 append.

    Returns: 새 crontab 텍스트
    """
    block = "\n".join([BEGIN_MARKER, *new_lines, END_MARKER])

    if BEGIN_MARKER in crontab_text and END_MARKER in crontab_text:
        pattern = re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER)
        return re.sub(pattern, block, crontab_text, count=1, flags=re.DOTALL)

    sep = "" if crontab_text.endswith("\n") or not crontab_text else "\n"
    return crontab_text + sep + "\n" + block + "\n"


def remove_managed_block(crontab_text: str) -> str:
    """마커 영역 전체 제거 (마커 라인 포함)."""
    if BEGIN_MARKER not in crontab_text or END_MARKER not in crontab_text:
        return crontab_text
    pattern = re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER) + r"\n?"
    return re.sub(pattern, "", crontab_text, count=1, flags=re.DOTALL)


def backup_crontab(crontab_text: str) -> Path:
    """현재 crontab 을 timestamp 파일로 저장."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    path = BACKUP_DIR / f"crontab-{ts}.txt"
    path.write_text(crontab_text)
    return path


def diff_managed_block(current_lines: list[str], new_lines: list[str]) -> list[str]:
    """current → new diff (unified format, prefix 만 추출).

    Returns: ["-old_line", "+new_line", " unchanged_line", ...]
    """
    diff = list(
        difflib.unified_diff(
            current_lines,
            new_lines,
            fromfile="current",
            tofile="new",
            lineterm="",
            n=0,
        )
    )
    # @@ hunk header 와 파일 헤더 제외
    return [
        line for line in diff
        if not line.startswith("@@") and not line.startswith("---") and not line.startswith("+++")
    ]
```

- [ ] **Step 4: 테스트 통과**

```bash
uv run pytest tests/test_cron_manager.py -v
```

Expected: 7 passed.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/cron_manager.py tests/test_cron_manager.py
git commit -m "feat(llm_runner): cron_manager — 마커 기반 crontab read/write + 백업 + diff"
```

---

## Task 2: `cron_manager` — register / unregister 헬퍼 + LLM runner cron 라인

**Files:**
- Modify: `kr_pipeline/llm_runner/cron_manager.py`
- Modify: `tests/test_cron_manager.py`

cron 라인을 정의하고 register/unregister 헬퍼 추가.

- [ ] **Step 1: 테스트 추가**

`tests/test_cron_manager.py` 끝에 추가:

```python
def test_default_cron_lines_contains_three_modes():
    """default LLM runner cron 라인 3종 (full-daily, weekend, performance)."""
    from kr_pipeline.llm_runner.cron_manager import DEFAULT_CRON_LINES

    assert len(DEFAULT_CRON_LINES) == 3
    assert any("full-daily" in line for line in DEFAULT_CRON_LINES)
    assert any("weekend" in line for line in DEFAULT_CRON_LINES)
    assert any("performance" in line for line in DEFAULT_CRON_LINES)


def test_register_and_unregister_flow(monkeypatch, tmp_path):
    """register → 마커 안 라인 있음 → unregister → 마커 사라짐."""
    from kr_pipeline.llm_runner import cron_manager as cm

    state = {"crontab": "0 5 * * * /user_backup\n"}

    def fake_get():
        return state["crontab"]

    def fake_install(text):
        state["crontab"] = text

    monkeypatch.setattr(cm, "get_current_crontab", fake_get)
    monkeypatch.setattr(cm, "install_crontab", fake_install)
    monkeypatch.setattr(cm, "BACKUP_DIR", tmp_path)

    backup1, new_text = cm.register()
    assert "kr-by-claude-llm-runner BEGIN" in state["crontab"]
    assert "--mode=full-daily" in state["crontab"]
    assert "/user_backup" in state["crontab"]
    assert backup1.exists()

    backup2, new_text = cm.unregister()
    assert "kr-by-claude-llm-runner" not in state["crontab"]
    assert "/user_backup" in state["crontab"]
    assert backup2.exists()


def test_register_is_idempotent(monkeypatch, tmp_path):
    """이미 등록된 상태에서 register 다시 호출 — 마커 한 번만 존재."""
    from kr_pipeline.llm_runner import cron_manager as cm

    state = {"crontab": ""}
    monkeypatch.setattr(cm, "get_current_crontab", lambda: state["crontab"])
    monkeypatch.setattr(
        cm, "install_crontab", lambda text: state.update(crontab=text)
    )
    monkeypatch.setattr(cm, "BACKUP_DIR", tmp_path)

    cm.register()
    cm.register()
    # 마커 BEGIN 이 1회만 등장
    assert state["crontab"].count("kr-by-claude-llm-runner BEGIN") == 1
```

- [ ] **Step 2: 구현 추가**

`kr_pipeline/llm_runner/cron_manager.py` 끝에 추가:

```python
PROJECT_DIR = Path(__file__).parent.parent.parent  # repo root

DEFAULT_CRON_LINES = [
    f"30 16 * * 1-5  cd {PROJECT_DIR} && uv run python -m kr_pipeline.llm_runner --mode=full-daily >> $HOME/.kr-by-claude/llm_runner.log 2>&1",
    f"20  3 * * 6    cd {PROJECT_DIR} && uv run python -m kr_pipeline.llm_runner --mode=weekend >> $HOME/.kr-by-claude/llm_runner.log 2>&1",
    f"0  23 * * *    cd {PROJECT_DIR} && uv run python -m kr_pipeline.llm_runner --mode=performance >> $HOME/.kr-by-claude/llm_runner.log 2>&1",
]


def register(lines: list[str] | None = None) -> tuple[Path, str]:
    """LLM runner cron 라인을 등록.

    Returns: (backup_path, new_crontab_text)
    """
    if lines is None:
        lines = DEFAULT_CRON_LINES

    current = get_current_crontab()
    backup_path = backup_crontab(current)

    new_text = replace_managed_block(current, lines)
    install_crontab(new_text)

    # 일관성 검증
    installed = get_current_crontab()
    if extract_managed_lines(installed) != lines:
        # 롤백
        install_crontab(current)
        raise RuntimeError(
            f"crontab install verification failed; rolled back. Backup at {backup_path}"
        )
    return backup_path, new_text


def unregister() -> tuple[Path, str]:
    """LLM runner cron 영역 제거.

    Returns: (backup_path, new_crontab_text)
    """
    current = get_current_crontab()
    backup_path = backup_crontab(current)

    new_text = remove_managed_block(current)
    install_crontab(new_text)

    # 검증
    installed = get_current_crontab()
    if BEGIN_MARKER in installed:
        install_crontab(current)
        raise RuntimeError(
            f"crontab unregister verification failed; rolled back. Backup at {backup_path}"
        )
    return backup_path, new_text


def get_status() -> dict:
    """현재 cron 등록 상태 + 마커 안 라인 + 다음 예정 시각 정보."""
    current = get_current_crontab()
    managed = extract_managed_lines(current)
    return {
        "registered": len(managed) > 0,
        "lines": managed,
        "default_lines": DEFAULT_CRON_LINES,
        "marker_begin": BEGIN_MARKER,
        "marker_end": END_MARKER,
    }
```

- [ ] **Step 3: 테스트 통과**

```bash
uv run pytest tests/test_cron_manager.py -v
```

Expected: 10 passed.

- [ ] **Step 4: 커밋**

```bash
git add kr_pipeline/llm_runner/cron_manager.py tests/test_cron_manager.py
git commit -m "feat(llm_runner): cron_manager.register/unregister/get_status — 안전장치 통합"
```

---

## Task 3: `runner_service.py` — subprocess 관리 + 중복 방지

**Files:**
- Create: `api/services/runner_service.py`
- Create: `tests/test_api_runner_service.py`

수동 실행 트리거 + 중복 방지 + 동시 실행 방지.

- [ ] **Step 1: 테스트 작성**

`tests/test_api_runner_service.py`:

```python
"""runner_service — subprocess 실행 + 중복/동시 방지."""
from datetime import datetime, date, timezone, timedelta


def test_check_recent_success_today_blocks_rerun(db):
    """오늘 같은 모드 success run 있으면 재실행 거부."""
    from api.services.runner_service import check_can_run

    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at, rows_affected)
               VALUES ('llm_weekend', 'weekend', 'success', %s, %s, 100)""",
            (datetime.now(timezone.utc), datetime.now(timezone.utc)),
        )
    db.commit()

    result = check_can_run(db, mode="weekend")
    assert result["can_run"] is False
    assert result["reason"] == "duplicate"
    assert result["existing_run_id"] is not None


def test_check_recent_failed_allows_rerun(db):
    """최근 fail 은 재실행 허용."""
    from api.services.runner_service import check_can_run

    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at)
               VALUES ('llm_daily_delta', 'daily-delta', 'failed', %s, %s)""",
            (datetime.now(timezone.utc), datetime.now(timezone.utc)),
        )
    db.commit()

    result = check_can_run(db, mode="daily-delta")
    assert result["can_run"] is True


def test_check_running_blocks_rerun(db):
    """현재 running 인 모드 재실행 거부."""
    from api.services.runner_service import check_can_run

    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO pipeline_runs (pipeline, mode, status, started_at)
               VALUES ('llm_weekend', 'weekend', 'running', %s)""",
            (datetime.now(timezone.utc),),
        )
    db.commit()

    result = check_can_run(db, mode="weekend")
    assert result["can_run"] is False
    assert result["reason"] == "already_running"


def test_check_force_bypasses_duplicate(db):
    """force=True 면 중복 무시."""
    from api.services.runner_service import check_can_run

    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at)
               VALUES ('llm_weekend', 'weekend', 'success', %s, %s)""",
            (datetime.now(timezone.utc), datetime.now(timezone.utc)),
        )
    db.commit()

    result = check_can_run(db, mode="weekend", force=True)
    assert result["can_run"] is True


def test_spawn_subprocess_returns_pid(mocker):
    """subprocess.Popen 호출되고 PID 반환."""
    from api.services.runner_service import spawn_runner

    fake_proc = mocker.Mock()
    fake_proc.pid = 12345
    mock_popen = mocker.patch("subprocess.Popen", return_value=fake_proc)

    result = spawn_runner(mode="weekend", dry_run=True, limit=5)
    assert result["pid"] == 12345
    args = mock_popen.call_args[0][0]
    assert "--mode=weekend" in args
    assert "--dry-run" in args
    assert "--limit=5" in args
```

- [ ] **Step 2: 구현**

`api/services/runner_service.py`:

```python
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
```

- [ ] **Step 3: 테스트 통과**

```bash
uv run pytest tests/test_api_runner_service.py -v
```

Expected: 5 passed.

- [ ] **Step 4: 커밋**

```bash
git add api/services/runner_service.py tests/test_api_runner_service.py
git commit -m "feat(api): runner_service — subprocess 실행 + 중복/동시 방지"
```

---

## Task 4: API `/api/runs/summary` — 모드별 마지막 실행 + 다음 스케줄

**Files:**
- Modify: `api/routers/runs.py`
- Modify: `tests/test_api_routers.py` (회귀 확인용)
- Create: `tests/test_api_runs_summary.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_api_runs_summary.py`:

```python
"""GET /api/runs/summary — 모드별 마지막 실행 + 다음 스케줄."""
import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_summary_returns_all_modes(client):
    r = client.get("/api/runs/summary")
    assert r.status_code == 200
    data = r.json()
    assert "modes" in data
    mode_names = {m["mode"] for m in data["modes"]}
    assert {"weekend", "full-daily", "performance"}.issubset(mode_names)


def test_summary_each_mode_has_required_fields(client):
    r = client.get("/api/runs/summary")
    data = r.json()
    for m in data["modes"]:
        assert "mode" in m
        assert "pipeline" in m
        assert "last_run" in m   # None or {id, status, started_at, ...}
        assert "next_scheduled" in m  # ISO string or null
        assert "cron_expression" in m
```

- [ ] **Step 2: 구현 (api/routers/runs.py 끝에 추가)**

기존 `runs.py` 를 read 한 후 다음 endpoint 추가:

```python
from datetime import date as _date, datetime, timedelta, timezone


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
```

- [ ] **Step 3: 테스트 통과 + 회귀**

```bash
uv run pytest tests/test_api_runs_summary.py tests/test_api_routers.py -v
```

Expected: 신규 2 + 기존 9 모두 passed.

- [ ] **Step 4: 커밋**

```bash
git add api/routers/runs.py tests/test_api_runs_summary.py
git commit -m "feat(api): /api/runs/summary — 모드별 마지막 실행 + 다음 cron 예정"
```

---

## Task 5: API `/api/runner/*` — 수동 실행 + 진행 조회

**Files:**
- Create: `api/routers/runner.py`
- Modify: `api/main.py` (마운트)
- Create: `tests/test_api_runner.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_api_runner.py`:

```python
"""POST /api/runner/run + GET /api/runner/status/{id}."""
import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_run_invalid_mode_returns_400(client):
    r = client.post("/api/runner/run", json={"mode": "invalid"})
    assert r.status_code == 400


def test_run_dry_run_spawns(client, mocker):
    """dry-run 모드 → subprocess.Popen 호출되고 200 반환."""
    fake_proc = mocker.Mock()
    fake_proc.pid = 99999
    mocker.patch("subprocess.Popen", return_value=fake_proc)

    r = client.post("/api/runner/run", json={"mode": "performance", "dry_run": True})
    assert r.status_code in (200, 409)  # 409 = duplicate (이미 오늘 돌았다면)
    if r.status_code == 200:
        data = r.json()
        assert "pid" in data
        assert "command" in data


def test_run_duplicate_returns_409(client, db):
    """오늘 success 있으면 409."""
    from datetime import datetime, timezone

    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO pipeline_runs (pipeline, mode, status, started_at, finished_at)
               VALUES ('llm_performance', 'performance', 'success', %s, %s)""",
            (datetime.now(timezone.utc), datetime.now(timezone.utc)),
        )
    db.commit()

    r = client.post("/api/runner/run", json={"mode": "performance", "dry_run": True})
    assert r.status_code == 409
    data = r.json()
    assert "existing_run_id" in data["detail"]
```

- [ ] **Step 2: 구현**

`api/routers/runner.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection
from pydantic import BaseModel

from api.deps import get_conn
from api.services.runner_service import (
    MODE_TO_PIPELINE,
    check_can_run,
    spawn_runner,
)


router = APIRouter(prefix="/api/runner", tags=["runner"])


class RunRequest(BaseModel):
    mode: str
    dry_run: bool = True
    limit: int | None = None
    ticker: str | None = None
    force: bool = False


@router.post("/run")
def run(req: RunRequest, conn: Connection = Depends(get_conn)):
    if req.mode not in MODE_TO_PIPELINE:
        raise HTTPException(400, f"unknown mode: {req.mode}")

    check = check_can_run(conn, req.mode, force=req.force)
    if not check["can_run"]:
        raise HTTPException(
            409,
            detail={
                "reason": check["reason"],
                "existing_run_id": check["existing_run_id"],
                "existing_run_summary": check.get("existing_run_summary"),
                "message": (
                    "이미 실행 중입니다."
                    if check["reason"] == "already_running"
                    else "오늘 같은 모드가 이미 성공 실행되었습니다. force=true 로 재실행 가능."
                ),
            },
        )

    spawn_result = spawn_runner(
        mode=req.mode,
        dry_run=req.dry_run,
        limit=req.limit,
        ticker=req.ticker,
    )
    return {
        "mode": req.mode,
        "dry_run": req.dry_run,
        "pid": spawn_result["pid"],
        "command": spawn_result["command"],
    }
```

- [ ] **Step 3: api/main.py 마운트**

```python
from api.routers import runner
app.include_router(runner.router)
```

- [ ] **Step 4: 테스트 + 커밋**

```bash
uv run pytest tests/test_api_runner.py -v
git add api/ tests/test_api_runner.py
git commit -m "feat(api): /api/runner/run — 수동 실행 + 중복 방지 응답"
```

---

## Task 6: API `/api/cron/*` — Cron 상태 + 등록/해제 + diff 미리보기

**Files:**
- Create: `api/routers/cron.py`
- Modify: `api/main.py`
- Create: `tests/test_api_cron.py`

- [ ] **Step 1: 테스트 작성**

`tests/test_api_cron.py`:

```python
import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_get_status_returns_required_fields(client, mocker):
    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.get_current_crontab",
        return_value="",
    )
    r = client.get("/api/cron/status")
    assert r.status_code == 200
    data = r.json()
    assert "registered" in data
    assert "lines" in data
    assert "default_lines" in data


def test_preview_register_shows_diff(client, mocker):
    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.get_current_crontab",
        return_value="0 5 * * * /backup\n",
    )
    r = client.get("/api/cron/preview?action=register")
    assert r.status_code == 200
    data = r.json()
    assert "diff" in data
    assert "new_crontab_preview" in data
    assert "new_crontab_preview" in data


def test_register_calls_install(client, mocker, tmp_path):
    state = {"crontab": "0 5 * * * /backup\n"}

    def fake_get():
        return state["crontab"]

    def fake_install(text):
        state["crontab"] = text

    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.get_current_crontab",
        side_effect=fake_get,
    )
    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.install_crontab",
        side_effect=fake_install,
    )
    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.BACKUP_DIR",
        tmp_path,
    )

    r = client.post("/api/cron/register")
    assert r.status_code == 200
    data = r.json()
    assert data["registered"] is True
    assert "kr-by-claude-llm-runner" in state["crontab"]


def test_unregister(client, mocker, tmp_path):
    initial = """0 5 * * * /backup
# === kr-by-claude-llm-runner BEGIN (auto-managed, do not edit by hand) ===
30 16 * * 1-5 /path/llm_runner
# === kr-by-claude-llm-runner END ===
0 6 * * * /other"""
    state = {"crontab": initial}

    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.get_current_crontab",
        side_effect=lambda: state["crontab"],
    )
    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.install_crontab",
        side_effect=lambda t: state.update(crontab=t),
    )
    mocker.patch(
        "kr_pipeline.llm_runner.cron_manager.BACKUP_DIR",
        tmp_path,
    )

    r = client.post("/api/cron/unregister")
    assert r.status_code == 200
    assert "kr-by-claude-llm-runner" not in state["crontab"]
```

- [ ] **Step 2: 구현**

`api/routers/cron.py`:

```python
from fastapi import APIRouter, HTTPException

from kr_pipeline.llm_runner import cron_manager


router = APIRouter(prefix="/api/cron", tags=["cron"])


@router.get("/status")
def status():
    """현재 cron 등록 상태."""
    try:
        return cron_manager.get_status()
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.get("/preview")
def preview(action: str):
    """register / unregister diff 미리보기."""
    if action not in ("register", "unregister"):
        raise HTTPException(400, "action must be 'register' or 'unregister'")

    try:
        current = cron_manager.get_current_crontab()
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    current_lines = cron_manager.extract_managed_lines(current)
    if action == "register":
        new_lines = cron_manager.DEFAULT_CRON_LINES
        new_crontab = cron_manager.replace_managed_block(current, new_lines)
    else:
        new_lines = []
        new_crontab = cron_manager.remove_managed_block(current)

    diff = cron_manager.diff_managed_block(current_lines, new_lines)
    return {
        "action": action,
        "current_lines": current_lines,
        "new_lines": new_lines,
        "diff": diff,
        "new_crontab_preview": new_crontab,
    }


@router.post("/register")
def register():
    try:
        backup_path, new_text = cron_manager.register()
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return {
        "registered": True,
        "backup_path": str(backup_path),
        "lines_count": len(cron_manager.DEFAULT_CRON_LINES),
    }


@router.post("/unregister")
def unregister():
    try:
        backup_path, new_text = cron_manager.unregister()
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return {"registered": False, "backup_path": str(backup_path)}
```

- [ ] **Step 3: api/main.py 마운트**

```python
from api.routers import cron as cron_router
app.include_router(cron_router.router)
```

- [ ] **Step 4: 테스트 + 커밋**

```bash
uv run pytest tests/test_api_cron.py -v
git add api/ tests/test_api_cron.py
git commit -m "feat(api): /api/cron/* — 상태 조회 + 등록/해제 + diff 미리보기"
```

---

## Task 7: 프론트 types.ts 확장 + API 헬퍼

**Files:**
- Modify: `web/src/lib/types.ts`

- [ ] **Step 1: types.ts 끝에 추가**

```typescript
export interface RunSummaryMode {
  mode: string;
  pipeline: string;
  cron_expression: string;
  description: string;
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
}

export interface RunSummaryResponse {
  modes: RunSummaryMode[];
}

export interface CronStatus {
  registered: boolean;
  lines: string[];
  default_lines: string[];
  marker_begin: string;
  marker_end: string;
}

export interface CronPreview {
  action: "register" | "unregister";
  current_lines: string[];
  new_lines: string[];
  diff: string[];
  new_crontab_preview: string;
}

export interface RunResponse {
  mode: string;
  dry_run: boolean;
  pid: number;
  command: string;
}

export interface RunConflict {
  reason: string;
  existing_run_id: number | null;
  existing_run_summary: Record<string, unknown> | null;
  message: string;
}
```

- [ ] **Step 2: tsc check + 커밋**

```bash
cd web && npx tsc --noEmit
cd ..
git add web/src/lib/types.ts
git commit -m "feat(web/types): RunSummary, CronStatus, RunResponse 타입 추가"
```

---

## Task 8: 프론트 `/runner` 페이지 (대시보드)

**Files:**
- Create: `web/src/pages/RunnerPage.tsx`
- Modify: `web/src/App.tsx` (route + nav)

- [ ] **Step 1: RunnerPage 작성**

`web/src/pages/RunnerPage.tsx`:

```typescript
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Play,
  Clock,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Settings,
  RefreshCw,
} from "lucide-react";
import { api, apiUrl } from "../lib/api";
import type {
  RunSummaryResponse,
  RunSummaryMode,
  CronStatus,
  CronPreview,
  RunResponse,
} from "../lib/types";
import { relativeTime } from "../lib/utils";
import { Modal } from "../components/ui/Modal";


function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds.toFixed(0)}초`;
  return `${Math.floor(seconds / 60)}분 ${Math.floor(seconds % 60)}초`;
}


function StatusChip({ status }: { status: string }) {
  if (status === "success") {
    return (
      <span className="chip bg-success-soft text-success">
        <CheckCircle2 size={11} />
        성공
      </span>
    );
  }
  if (status === "failed" || status === "error") {
    return (
      <span className="chip bg-danger-soft text-danger">
        <XCircle size={11} />
        실패
      </span>
    );
  }
  if (status === "running") {
    return (
      <span className="chip bg-amber-soft text-amber">
        <Clock size={11} className="animate-pulse" />
        실행 중
      </span>
    );
  }
  return <span className="chip bg-tint-stone text-muted">{status}</span>;
}


interface RunCardProps {
  mode: RunSummaryMode;
  onRun: (mode: string) => void;
}

function RunCard({ mode, onRun }: RunCardProps) {
  const last = mode.last_run;
  const nextDate = mode.next_scheduled ? new Date(mode.next_scheduled) : null;

  return (
    <div className="bento p-6 flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-subhead font-bold text-ink">
            {mode.mode === "weekend"
              ? "주말 분류"
              : mode.mode === "full-daily"
              ? "평일 전체 분석"
              : "성과 backfill"}
          </div>
          <div className="text-data-xs text-muted mt-0.5">
            {mode.description}
          </div>
        </div>
        <button
          onClick={() => onRun(mode.mode)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white rounded-lg text-data font-semibold hover:bg-accent-light transition-colors"
        >
          <Play size={13} />
          수동 실행
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 text-data-xs">
        <div>
          <div className="caps text-faint mb-1">마지막 실행</div>
          {last ? (
            <>
              <StatusChip status={last.status} />
              <div className="num mt-1.5 text-ink">
                {last.rows_affected != null
                  ? `${last.rows_affected.toLocaleString()}건 처리`
                  : "—"}
              </div>
              <div className="text-muted mt-0.5">
                {relativeTime(last.started_at)} ·{" "}
                {formatDuration(last.duration_seconds)}
              </div>
            </>
          ) : (
            <div className="text-faint">이력 없음</div>
          )}
        </div>
        <div>
          <div className="caps text-faint mb-1">다음 예정</div>
          {nextDate ? (
            <>
              <div className="num text-ink">
                {nextDate.toLocaleDateString("ko-KR")}
              </div>
              <div className="text-muted mt-0.5">
                {nextDate.toLocaleTimeString("ko-KR", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </div>
            </>
          ) : (
            <div className="text-faint">미스케줄</div>
          )}
        </div>
      </div>
    </div>
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
      const res = await fetch(apiUrl(`/cron/${action}`), {
        method: "POST",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      setPreviewAction(null);
      qc.invalidateQueries({ queryKey: ["cron-status"] });
    },
  });

  return (
    <section className="bento p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-xl bg-tint-violet">
            <Settings size={16} className="text-accent" strokeWidth={2} />
          </div>
          <div>
            <div className="text-subhead font-bold text-ink">
              Cron 등록 관리
            </div>
            <div className="text-data-xs text-muted mt-0.5">
              평일/주말/일일 cron 자동 등록 (마커 + 자동 백업)
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
          <div className="num text-data-xs text-muted bg-cream border border-hairline rounded-xl p-3 mb-4 max-h-32 overflow-y-auto">
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


interface RunDialogProps {
  mode: string | null;
  onClose: () => void;
}

function RunDialog({ mode, onClose }: RunDialogProps) {
  const [dryRun, setDryRun] = useState(true);
  const [limit, setLimit] = useState<number | "">(5);
  const [confirmReal, setConfirmReal] = useState(false);
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: async (req: {
      mode: string;
      dry_run: boolean;
      limit: number | null;
      force?: boolean;
    }) => {
      const res = await fetch(apiUrl("/runner/run"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      if (res.status === 409) {
        const err = await res.json();
        throw new Error(`DUPLICATE:${JSON.stringify(err.detail)}`);
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json() as Promise<RunResponse>;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["runs-summary"] });
      onClose();
    },
  });

  if (mode === null) return null;
  const canSubmit = dryRun || confirmReal;

  return (
    <Modal
      open={mode !== null}
      onClose={onClose}
      title={`수동 실행 — ${mode}`}
      subtitle="비용 보호: 실제 LLM 호출은 명시적 확인 필요"
    >
      <div className="px-6 py-5 space-y-4">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => {
              setDryRun(e.target.checked);
              setConfirmReal(false);
            }}
            className="w-4 h-4 accent-accent"
          />
          <span className="text-data font-semibold text-ink">
            Dry-run (LLM 호출 안 함, 흐름만 검증)
          </span>
        </label>

        {!dryRun && (
          <div className="bg-amber-soft border border-amber/30 rounded-xl p-3">
            <div className="flex items-start gap-2 mb-2">
              <AlertTriangle size={16} className="text-amber shrink-0 mt-0.5" />
              <div className="text-data text-amber font-semibold">
                실제 LLM 호출 — 비용 발생
              </div>
            </div>
            <div className="text-data-xs text-muted mb-2">
              {mode === "weekend"
                ? "약 100-200 LLM 호출 예상"
                : mode === "full-daily"
                ? "약 30-60 LLM 호출 예상"
                : "LLM 호출 없음 (계산만)"}
            </div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={confirmReal}
                onChange={(e) => setConfirmReal(e.target.checked)}
                className="w-4 h-4 accent-danger"
              />
              <span className="text-data text-ink">
                이해했고 실제 호출하겠습니다
              </span>
            </label>
          </div>
        )}

        <div>
          <label className="caps block mb-1.5">종목 수 제한</label>
          <input
            type="number"
            value={limit}
            onChange={(e) =>
              setLimit(e.target.value === "" ? "" : Number(e.target.value))
            }
            className="border border-hairline rounded-lg px-3 py-2 text-data bg-cream w-32"
          />
        </div>

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-paper border border-hairline rounded-lg text-data font-semibold"
          >
            취소
          </button>
          <button
            onClick={() =>
              mutation.mutate({
                mode,
                dry_run: dryRun,
                limit: limit === "" ? null : limit,
              })
            }
            disabled={!canSubmit || mutation.isPending}
            className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold disabled:opacity-50"
          >
            {mutation.isPending ? "실행 중…" : "실행"}
          </button>
        </div>

        {mutation.isError && (
          <div className="text-danger text-data-xs">
            {String(mutation.error)}
          </div>
        )}
      </div>
    </Modal>
  );
}


export default function RunnerPage() {
  const qc = useQueryClient();
  const summaryQ = useQuery<RunSummaryResponse>({
    queryKey: ["runs-summary"],
    queryFn: () => api<RunSummaryResponse>("/runs/summary"),
    refetchInterval: 30_000,
  });

  const [runMode, setRunMode] = useState<string | null>(null);

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">Runner</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            LLM 분석 운영
          </h2>
        </div>
        <button
          onClick={() => qc.invalidateQueries()}
          className="flex items-center gap-1.5 text-data text-muted hover:text-ink"
        >
          <RefreshCw size={14} />
          새로고침
        </button>
      </header>

      <div className="grid grid-cols-3 gap-5 mb-6">
        {summaryQ.data?.modes.map((m) => (
          <RunCard key={m.mode} mode={m} onRun={setRunMode} />
        ))}
      </div>

      <CronManagerSection />

      <RunDialog mode={runMode} onClose={() => setRunMode(null)} />
    </div>
  );
}
```

- [ ] **Step 2: App.tsx 에 route + nav 추가**

기존 App.tsx 의 NAV_ITEMS 에 추가 (Sparkles 자리 위에 또는 적절한 위치):

```typescript
import RunnerPage from "./pages/RunnerPage";
import { Wrench } from "lucide-react";  // 또는 기존 import 에 추가

// NAV_ITEMS 에:
{ to: "/runner", label: "Runner", kr: "분석 운영", Icon: Wrench },

// Routes 에:
<Route path="/runner" element={<RunnerPage />} />
```

- [ ] **Step 3: tsc + dev server 검증**

```bash
cd web && npx tsc --noEmit
cd ..
git add web/
git commit -m "feat(web): /runner 페이지 + RunCard + CronManager + RunDialog"
```

---

## Task 9: Goal State 검증

- [ ] **Step 1: 전체 backend 회귀**

```bash
uv run pytest 2>&1 | tail -3
```

Expected: 기존 233 + 신규 약 15 = ~248 passed.

- [ ] **Step 2: TypeScript**

```bash
cd web && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: 백엔드 라이브 endpoint 확인**

```bash
uv run uvicorn api.main:app --port 8000 &
sleep 3

echo "Summary:"
curl -s http://localhost:8000/api/runs/summary | python3 -m json.tool | head -30

echo "Cron status:"
curl -s http://localhost:8000/api/cron/status | python3 -m json.tool

echo "Run dry-run (performance):"
curl -sS -X POST http://localhost:8000/api/runner/run \
  -H "Content-Type: application/json" \
  -d '{"mode": "performance", "dry_run": true}' | python3 -m json.tool

pkill -f "uvicorn api.main"
```

Expected: 모두 정상 응답.

- [ ] **Step 4: 프론트 dev server**

```bash
cd web && npm run dev > /tmp/vite.log 2>&1 &
sleep 3
curl -s http://localhost:5173/runner | head -c 200
pkill -f vite
```

Expected: HTML 응답.

- [ ] **Step 5: git status clean 확인 + 종료 보고**

```bash
git status
```

Expected: clean (`.claude/` 만 untracked).

종료 보고 사용자에게 출력:
```
LLM Runner Dashboard + Cron 관리 완료.

구현된 자산:
- /api/runs/summary, /api/runner/run, /api/cron/* (4 신규 endpoints)
- kr_pipeline/llm_runner/cron_manager (마커 + 백업 + diff)
- api/services/runner_service (subprocess + 중복 방지)
- /runner 페이지 (RunCard + CronManager + RunDialog)
- ~15 신규 테스트 (총 ~248 passing)

다음 단계 (운영):
1. /runner 페이지에서 "등록 미리보기" → "등록 적용" 으로 cron 자동 등록
2. dry-run 으로 각 모드 1회 수동 실행 → 동작 확인
3. 실제 LLM 호출은 명시적 확인 dialog 거쳐서 진행
4. 백업: ~/.kr-by-claude/cron-backups/ 에 자동 저장
```

---

## Self-Review

✅ **요구사항 coverage**:
- 운영 대시보드 → Task 4 (API) + Task 8 (페이지)
- 다음 스케줄 → Task 4 의 `_next_scheduled`
- 수동 실행 → Task 5 (API) + Task 8 의 RunDialog
- Cron 자동 등록/해제 → Task 1, 2 (manager) + Task 6 (API) + Task 8 의 CronManagerSection
- 중복 방지 → Task 3 의 `check_can_run`
- 마커 + 백업 + diff 미리보기 + 검증 → Task 1, 2

✅ **Placeholder 없음**: 모든 step 에 실제 코드 포함.

⚠️ **알려진 한계**:
- subprocess.Popen fire-and-forget — 프로세스 자체가 죽으면 `status='running'` stuck 가능. modes.py 의 `run_*` 함수가 직접 `pipeline_runs` 에 row 생성/완료 마킹해야 함. 현재 코드에서 modes 가 그렇게 하는지 plan 에 명시 안 됨 — 자율 실행자 확인 필요.
- 만약 modes.py 가 pipeline_runs 마킹 안 하고 있다면 별도 task 로 보완 필요 (또는 implementer 가 알아서 추가).
- LLM 비용 보호: misclick 까지는 완벽히 막지 못함. 두 단계 확인 dialog 로 완화.

⚠️ **Type consistency**:
- backend `pipeline_runs.status` 가 'success' | 'failed' | 'running' — 자율 실행자가 modes.py 확인 필요
- frontend RunSummaryMode.last_run.status 가 string union 아닌 string — runtime 에 처리

자율 실행자는 위 한계를 인지하고 진행할 것.
