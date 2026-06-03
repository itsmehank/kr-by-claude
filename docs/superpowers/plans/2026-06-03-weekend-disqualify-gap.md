# 주말 분류 disqualify 갭 수정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 주말 분류(`run_weekend`)가 `disqualify` 를 먼저 실행해 minervini 탈락 종목을 강등하게 하고, 독립 `--mode=disqualify` 를 추가해 즉시·온디맨드 정리를 가능하게 한다.

**Architecture:** `modes.run_weekend` 에 `disqualify.run` 호출을 `weekend.run` 앞에 추가(단, ticker 디버그 모드 제외). `__main__.py` 에 `disqualify` 모드 등록(routing + pipeline 이름 + 매핑 테스트 동기화). 강등 알고리즘 자체는 기존 `disqualify.run` 재사용 — 변경 없음.

**Tech Stack:** Python (psycopg), pytest (monkeypatch spy + real db fixture). 기존 modes/__main__ 패턴 재사용.

**테스트 규약 (CLAUDE.md):** `uv run pytest tests/` — baseline ~26 isolation fail, 늘리지 않을 것.

---

### Task 1: run_weekend 가 disqualify 먼저 실행 (+ ticker 가드)

**Files:**
- Modify: `kr_pipeline/llm_runner/modes.py` (`run_weekend`)
- Test: `tests/test_llm_modes.py` (신규)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_modes.py` 신규 생성

```python
from datetime import date


def test_run_weekend_runs_disqualify_before_weekend(db, monkeypatch):
    """full batch: disqualify 가 weekend.run 보다 먼저 호출된다."""
    import kr_pipeline.llm_runner.modes as modes
    calls = []
    monkeypatch.setattr(modes.disqualify, "run", lambda *a, **k: calls.append("disqualify") or {})
    monkeypatch.setattr(modes.weekend, "run", lambda *a, **k: calls.append("weekend") or {"processed": 0})
    monkeypatch.setattr(modes, "notify_weekend_digest", lambda **k: None)
    modes.run_weekend(db, dry_run=True, as_of=date(2025, 9, 30), limit=None)
    assert calls == ["disqualify", "weekend"]


def test_run_weekend_ticker_mode_skips_disqualify(db, monkeypatch):
    """단일 종목 디버그(ticker 지정)면 disqualify 스윕 생략."""
    import kr_pipeline.llm_runner.modes as modes
    calls = []
    monkeypatch.setattr(modes.disqualify, "run", lambda *a, **k: calls.append("disqualify") or {})
    monkeypatch.setattr(modes.weekend, "run", lambda *a, **k: calls.append("weekend") or {"processed": 0})
    monkeypatch.setattr(modes, "notify_weekend_digest", lambda **k: None)
    modes.run_weekend(db, dry_run=True, as_of=date(2025, 9, 30), limit=None, ticker="005930")
    assert "disqualify" not in calls
    assert calls == ["weekend"]
```

> 참고: `run_weekend` 는 weekend.run 뒤에 `weekly_classification` 분포 집계 쿼리를 실제 db 로 돌리고 `notify_weekend_digest` 를 부른다. 그래서 db 픽스처를 쓰고 notify 는 monkeypatch 로 무력화한다. 집계 쿼리는 무해(결과만 읽음).

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_llm_modes.py -v`
Expected: `test_run_weekend_runs_disqualify_before_weekend` FAIL — 현재 disqualify 안 불려 `calls == ["weekend"]` 라 `["disqualify","weekend"]` assert 실패. (ticker 테스트는 현재도 통과.)

- [ ] **Step 3: 구현** — `modes.py` `run_weekend` 의 `weekend.run` 호출 앞에 disqualify 추가

기존:
```python
    """주말: (5) batch + digest. ticker 지정 시 단일 종목 디버깅 mode."""
    r = weekend.run(conn, dry_run=dry_run, as_of=as_of, limit=limit, ticker=ticker)
```
변경:
```python
    """주말: (disqualify →) (5) batch + digest. ticker 지정 시 단일 종목 디버깅 mode."""
    if ticker is None:                       # 단일 종목 디버그 모드에선 전체 강등 스윕 생략
        disqualify.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    r = weekend.run(conn, dry_run=dry_run, as_of=as_of, limit=limit, ticker=ticker)
```
(이후 dist 집계·notify·`return r` 는 그대로. `disqualify` 는 modes.py 에 이미 import 돼 있음.)

- [ ] **Step 4: 통과 확인 + 회귀**

Run: `uv run pytest tests/test_llm_modes.py tests/test_llm_disqualify.py -v`
Expected: 신규 2개 PASS, 기존 disqualify 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/modes.py tests/test_llm_modes.py
git commit -m "fix(disqualify): run_weekend 가 disqualify 먼저 실행 (ticker 디버그 제외) — 탈락 종목 강등 갭 수정"
```

---

### Task 2: 독립 --mode=disqualify

**Files:**
- Modify: `kr_pipeline/llm_runner/__main__.py`
- Test: `tests/test_llm_runner_main.py` (매핑 테스트 수정)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_runner_main.py` 의 `test_pipeline_db_name_mapping_covers_all_modes` 의 `expected_modes` 에 `"disqualify"` 추가하고, 매핑 단언 한 줄 추가:

기존:
```python
    expected_modes = {"weekend", "daily-delta", "evaluate", "entry", "performance", "full-daily", "backfill"}
    assert set(PIPELINE_DB_NAME_BY_MODE.keys()) == expected_modes
```
변경:
```python
    expected_modes = {"weekend", "daily-delta", "evaluate", "entry", "performance", "full-daily", "backfill", "disqualify"}
    assert set(PIPELINE_DB_NAME_BY_MODE.keys()) == expected_modes
```
그리고 같은 테스트 안 기존 매핑 단언들 옆에 추가:
```python
    assert PIPELINE_DB_NAME_BY_MODE["disqualify"] == "llm_disqualify"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_llm_runner_main.py::test_pipeline_db_name_mapping_covers_all_modes -v`
Expected: FAIL — `PIPELINE_DB_NAME_BY_MODE` 에 아직 disqualify 없어 set 불일치 + KeyError.

- [ ] **Step 3: 구현** — `__main__.py` 4곳 수정

(a) import 에 `disqualify` 추가:
```python
from kr_pipeline.llm_runner import (
    weekend, daily_delta, evaluate_pivot, entry_params, performance, backfill, disqualify,
)
```

(b) `PIPELINE_DB_NAME_BY_MODE` dict 에 추가:
```python
    "disqualify": "llm_disqualify",
```

(c) `--mode` choices 에 `"disqualify"` 추가:
```python
        choices=["weekend", "daily-delta", "evaluate", "entry", "performance", "full-daily", "backfill", "disqualify"],
```

(d) 실행 분기에 추가 (`elif args.mode == "backfill":` 옆):
```python
            elif args.mode == "disqualify":
                result = disqualify.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
```

- [ ] **Step 4: 통과 확인 + 회귀**

Run: `uv run pytest tests/test_llm_runner_main.py -v`
Expected: 매핑 테스트 PASS, 파일 내 다른 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/__main__.py tests/test_llm_runner_main.py
git commit -m "feat(disqualify): 독립 --mode=disqualify 라우팅 + llm_disqualify 추적 (온디맨드 강등 정리)"
```

---

### Task 3: 전체 회귀 점검

**Files:** 없음 (검증만)

- [ ] **Step 1: 전체 테스트**

Run: `uv run pytest tests/ -q`
Expected: 신규 테스트 전부 PASS. 실패는 사전 baseline(~26 isolation fail) 이내 — 그 수가 늘지 않았는지 확인.

- [ ] **Step 2: 라이브 무변경 확인 (run_full_daily 그대로)**

Run: `grep -n "disqualify.run" kr_pipeline/llm_runner/modes.py`
Expected: 2곳 — `run_full_daily`(기존) + `run_weekend`(신규). full_daily 의 호출은 변경 없음.

- [ ] **Step 3: 최종 커밋 체인 확인**

Run: `git log --oneline main..HEAD`
Expected: Task 1~2 커밋 + spec 커밋 존재.

---

## 즉시 정리 (운영 단계 — 머지·검증 후, 코드 아님)

부분 1·2 머지 후, 현재 stale 데이터(watch 19·ignore 194)를 한 번 정리:
```bash
uv run python -m kr_pipeline.llm_runner --mode=disqualify
```
(LLM 호출 0의 결정론 강등. 실행 후 web 분류 페이지에서 탈락 종목이 watch/ignore 에서 사라지고 disqualified 로 강등됐는지 확인.) — 이 단계는 plan 의 코드 task 가 아니라 머지 검증 후 사람이 수행.

---

## 자기 점검 결과 (작성자)

- **스펙 커버리지**: 부분1(run_weekend disqualify-first + ticker 가드)=Task1, 부분2(--mode=disqualify)=Task2, 매핑 동기화=Task2 Step1, 강등 회귀=Task1 Step4(test_llm_disqualify), 전체 회귀=Task3, 즉시 정리=운영 단계 명시. 누락 없음.
- **placeholder**: 없음. 모든 코드/명령 구체값. routing 분기(elif)는 매핑 테스트 + 리뷰로 커버(main() 전체를 DB 연결로 도는 무거운 테스트는 비용 대비 가치 낮아 생략 — backfill T4 와 동일 판단, 단 backfill 은 --date 필수라 parser.error 테스트가 가능했고 disqualify 는 그 경로가 없음).
- **타입 일관성**: `disqualify.run(conn, *, dry_run, as_of, limit)` 시그니처가 modes.run_full_daily 호출·run_weekend 신규 호출·__main__ 분기에서 일관. `notify_weekend_digest` monkeypatch 대상이 modes 네임스페이스와 일치. PIPELINE_DB_NAME_BY_MODE 키 "disqualify"→"llm_disqualify" 가 매핑 테스트와 일치.
