# 평일 파이프라인 재실행 멱등성 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** evaluate_pivot·entry_params 를 데이터 날짜(as_of) 기준으로 멱등화하고, run 레이어 duplicate 판정도 as_of 기준으로 바꿔 오전(전날 데이터)·오후(당일 데이터) 실행이 force 없이 독립 실행되게 한다.

**Architecture:** `weekly_classification` 의 검증된 `analyzed_for_date`(데이터 날짜) 패턴을 `trigger_evaluation_log`·`entry_params` 에 적용. 매칭/skip 은 `COALESCE(analyzed_for_date, wall-clock::date) = as_of` (레거시 backward-compat). 기본 skip, `--force` 시 같은 as_of 행 삭제 후 재분석(replace). run 레이어는 `check_can_run_pipeline` 의 duplicate 를 `params->>'as_of'` 비교로.

**Tech Stack:** Python, psycopg, PostgreSQL, FastAPI, pytest. 설계: `docs/superpowers/specs/2026-06-09-rerun-idempotency-design.md`.

**테스트 규약:** DB 테스트는 `db` fixture(트랜잭션 rollback 격리), conftest 가 `schema.sql` 을 `kr_test` 에 세션 1회 적용. `uv run pytest` 로 실행. 회귀 baseline = base↔HEAD 실패 수 비교(사전존재 실패 다수).

---

## Task 1: 스키마 — analyzed_for_date 컬럼 + 인덱스

**Files:**
- Modify: `kr_pipeline/db/schema.sql` (trigger_evaluation_log·entry_params ALTER 구역)
- Test: `tests/test_schema_rerun_idempotency.py` (Create)

- [ ] **Step 1: 실패 테스트 작성** — 두 테이블에 analyzed_for_date 컬럼 존재 검증

```python
# tests/test_schema_rerun_idempotency.py
import pytest

@pytest.mark.parametrize("table", ["trigger_evaluation_log", "entry_params"])
def test_analyzed_for_date_column_exists(db, table):
    with db.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s",
            (table,),
        )
        cols = {r[0] for r in cur.fetchall()}
    assert "analyzed_for_date" in cols
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_schema_rerun_idempotency.py -v`
Expected: FAIL — `assert 'analyzed_for_date' in cols` (컬럼 없음)

- [ ] **Step 3: schema.sql 에 ALTER + 인덱스 추가**

`kr_pipeline/db/schema.sql` 의 `trigger_evaluation_log` CREATE 블록 직후(인덱스 `idx_trigger_eval_at` 다음 줄)와 `entry_params` 의 기존 `ALTER TABLE entry_params ADD COLUMN ...` 묶음 끝에 각각 추가:

```sql
-- rerun-idempotency: 데이터 날짜(as_of) — wall-clock(evaluated_at/signal_at)과 분리한 dedup 키.
-- CREATE TABLE IF NOT EXISTS 는 기존 테이블 미반영 → ALTER 가 실효 구문.
ALTER TABLE trigger_evaluation_log ADD COLUMN IF NOT EXISTS analyzed_for_date DATE;
CREATE INDEX IF NOT EXISTS idx_trigger_eval_afd ON trigger_evaluation_log (analyzed_for_date);

ALTER TABLE entry_params ADD COLUMN IF NOT EXISTS analyzed_for_date DATE;
CREATE INDEX IF NOT EXISTS idx_entry_params_afd ON entry_params (analyzed_for_date);
```

- [ ] **Step 4: 테스트 통과 확인** (conftest 가 schema.sql 을 kr_test 에 재적용)

Run: `uv run pytest tests/test_schema_rerun_idempotency.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/db/schema.sql tests/test_schema_rerun_idempotency.py
git commit -m "feat(schema): trigger_evaluation_log·entry_params 에 analyzed_for_date 추가"
```

---

## Task 2: 공유 헬퍼 resolve_as_of

**Files:**
- Modify: `kr_pipeline/llm_runner/load.py` (함수 추가)
- Test: `tests/test_resolve_as_of.py` (Create)

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_resolve_as_of.py
from datetime import date

def test_resolve_as_of_uses_max_indicator_date(db):
    from kr_pipeline.llm_runner.load import resolve_as_of
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('RAO1','x','KOSPI') ON CONFLICT DO NOTHING")
        for d in (date(2026, 6, 6), date(2026, 6, 8)):
            cur.execute(
                "INSERT INTO daily_indicators (ticker,date,adj_close,volume,sma_50,avg_volume_50d,w52_high,w52_low) "
                "VALUES ('RAO1',%s,100,1000,90,1000,120,60) ON CONFLICT DO NOTHING",
                (d,),
            )
    db.commit()
    assert resolve_as_of(db) == date(2026, 6, 8)               # MAX
    assert resolve_as_of(db, date(2026, 6, 6)) == date(2026, 6, 6)  # explicit 우선
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_resolve_as_of.py -v`
Expected: FAIL — ImportError: cannot import name 'resolve_as_of'

- [ ] **Step 3: load.py 에 resolve_as_of 추가**

`kr_pipeline/llm_runner/load.py` 상단 import 에 `date` 가 이미 있음(`from datetime import date`). 파일 끝에 추가:

```python
def resolve_as_of(conn: Connection, explicit_date: date | None = None) -> date:
    """파이프라인 as_of(데이터 날짜) 결정 — __main__ 과 run-게이트 공유.

    explicit_date 있으면 그 값, 없으면 MAX(daily_indicators.date), 둘 다 없으면 today.
    """
    if explicit_date is not None:
        return explicit_date
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(date) FROM daily_indicators")
        row = cur.fetchone()
    return row[0] if row and row[0] else date.today()
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_resolve_as_of.py -v`
Expected: PASS

- [ ] **Step 5: __main__ 이 헬퍼 사용하도록 정리(중복 제거)**

`kr_pipeline/llm_runner/__main__.py` 의 as_of 계산 블록(현재):
```python
        if args.date:
            as_of = _date.fromisoformat(args.date)
        else:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(date) FROM daily_indicators")
                row = cur.fetchone()
            as_of = row[0] if row and row[0] else _date.today()
```
를 다음으로 교체(상단에 `from kr_pipeline.llm_runner.load import resolve_as_of` 추가):
```python
        explicit = _date.fromisoformat(args.date) if args.date else None
        as_of = resolve_as_of(conn, explicit)
```

- [ ] **Step 6: 기존 evaluate_pivot 테스트로 회귀 확인 + 커밋**

Run: `uv run pytest tests/test_llm_evaluate_pivot.py -v`
Expected: PASS (1 passed)

```bash
git add kr_pipeline/llm_runner/load.py kr_pipeline/llm_runner/__main__.py tests/test_resolve_as_of.py
git commit -m "feat(runner): resolve_as_of 공유 헬퍼 + __main__ 중복 제거"
```

---

## Task 3: 쓰기 — analyzed_for_date 저장

**Files:**
- Modify: `kr_pipeline/llm_runner/store.py` (insert_trigger_log, insert_entry_params)
- Modify: `kr_pipeline/llm_runner/evaluate_pivot.py:_process_one`
- Modify: `kr_pipeline/llm_runner/entry_params.py:_process_one, run`
- Test: `tests/test_rerun_write_afd.py` (Create)

- [ ] **Step 1: 실패 테스트 작성** — insert 시 analyzed_for_date 저장

```python
# tests/test_rerun_write_afd.py
from datetime import date, datetime, timezone

def test_insert_trigger_log_stores_analyzed_for_date(db):
    from kr_pipeline.llm_runner.store import insert_trigger_log
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('WAFD1','x','KOSPI') ON CONFLICT DO NOTHING")
    ev = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    insert_trigger_log(
        db, symbol="WAFD1", evaluated_at=ev, trigger_type="breakout",
        close=100, volume=1000, pivot_price=99,
        result={"decision": "wait", "confidence": 0.5, "reasoning": "x", "abort_reason": None},
        prior_classification_at=ev, llm_meta={"duration_s": 0.1, "input_tokens": None, "output_tokens": None},
        analyzed_for_date=date(2026, 6, 8),
    )
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT analyzed_for_date FROM trigger_evaluation_log WHERE symbol='WAFD1'")
        assert cur.fetchone()[0] == date(2026, 6, 8)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_rerun_write_afd.py -v`
Expected: FAIL — TypeError: insert_trigger_log() got an unexpected keyword argument 'analyzed_for_date'

- [ ] **Step 3: insert_trigger_log 수정**

`store.py` insert_trigger_log 시그니처에 파라미터 추가(`llm_meta: dict,` 다음 줄):
```python
    analyzed_for_date: date | None = None,
```
INSERT 컬럼 리스트의 `prior_classification_at,` 앞에 `analyzed_for_date,` 추가, VALUES 자리표시자 1개(`%s`) 추가, 값 튜플에서 `prior_classification_at,` 앞에 `analyzed_for_date,` 추가. (파일 상단에 `from datetime import date` 가 이미 있는지 확인 — 없으면 추가.)

- [ ] **Step 4: insert_entry_params 동일 수정**

`store.py` insert_entry_params 시그니처에 `analyzed_for_date: date | None = None,` 추가. INSERT 컬럼 `(symbol, signal_at,` 다음에 `analyzed_for_date,` 추가, VALUES 자리표시자 추가, 값 튜플 `symbol, signal_at,` 다음에 `analyzed_for_date,` 추가.

- [ ] **Step 5: _process_one 들이 as_of 전달**

`evaluate_pivot.py:_process_one` 의 `insert_trigger_log(...)` 호출에 인자 추가:
```python
        analyzed_for_date=as_of,
```
`entry_params.py:_process_one` 시그니처를 `def _process_one(conn, symbol, eval_at, prior_at, *, dry_run, as_of):` 로 바꾸고 `insert_entry_params(...)` 호출에 `analyzed_for_date=as_of,` 추가. `entry_params.py:run` 의 루프 호출을 `_process_one(conn, symbol, eval_at, prior_at, dry_run=dry_run, as_of=as_of)` 로 수정.

- [ ] **Step 6: entry_params 쓰기 테스트 추가 + 전체 통과**

`tests/test_rerun_write_afd.py` 에 추가:
```python
def test_insert_entry_params_stores_analyzed_for_date(db):
    from kr_pipeline.llm_runner.store import insert_entry_params
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('WAFD2','x','KOSPI') ON CONFLICT DO NOTHING")
    sig = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    result = {
        "entry_mode": "pivot_breakout", "pivot_price": 100, "trigger_price": 100, "current_price": 101,
        "stop_loss_price": 92, "stop_loss_pct_from_pivot": -8, "stop_loss_pct_from_current_price": -9,
        "suggested_weight_pct": 5, "expected_target_price": 120, "expected_target_pct": 20,
        "pattern_basis": "flat_base", "entry_window_days": 3, "max_chase_pct_from_pivot": 5,
        "breakout_volume_requirement": "ge_1.4x_50day_avg", "observed_breakout_volume_ratio": 1.6,
        "known_warnings": [], "other_warnings": [], "notes": "x",
    }
    insert_entry_params(
        db, symbol="WAFD2", signal_at=sig, result=result,
        trigger_evaluation_at=sig, prior_classification_at=sig,
        llm_meta={"duration_s": 0.1, "input_tokens": None, "output_tokens": None},
        analyzed_for_date=date(2026, 6, 8),
    )
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT analyzed_for_date FROM entry_params WHERE symbol='WAFD2'")
        assert cur.fetchone()[0] == date(2026, 6, 8)
```

Run: `uv run pytest tests/test_rerun_write_afd.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: 커밋**

```bash
git add kr_pipeline/llm_runner/store.py kr_pipeline/llm_runner/evaluate_pivot.py kr_pipeline/llm_runner/entry_params.py tests/test_rerun_write_afd.py
git commit -m "feat(runner): trigger/entry insert 에 analyzed_for_date=as_of 저장"
```

---

## Task 4: stage 읽기 — entry_params skip (COALESCE + NOT EXISTS + DISTINCT ON)

**Files:**
- Modify: `kr_pipeline/llm_runner/entry_params.py:_fetch_go_now_candidates, run`
- Test: `tests/test_rerun_entry_skip.py` (Create)

- [ ] **Step 1: 실패 테스트 작성** — 이미 entry_params 있는 종목 제외 + 다른 as_of 독립

```python
# tests/test_rerun_entry_skip.py
from datetime import date, datetime, timezone

def _seed_trigger(cur, symbol, eval_at, afd):
    cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'x','KOSPI') ON CONFLICT DO NOTHING", (symbol,))
    cur.execute("INSERT INTO weekly_classification (symbol,classified_at,market,classification,source) "
                "VALUES (%s,%s,'KOSPI','entry','test') ON CONFLICT DO NOTHING", (symbol, eval_at))
    cur.execute("INSERT INTO trigger_evaluation_log "
                "(symbol,evaluated_at,trigger_type,decision,prior_classification_at,analyzed_for_date) "
                "VALUES (%s,%s,'breakout','go_now',%s,%s) ON CONFLICT DO NOTHING",
                (symbol, eval_at, eval_at, afd))

def test_fetch_excludes_already_entry_and_isolates_as_of(db):
    from kr_pipeline.llm_runner.entry_params import _fetch_go_now_candidates
    as_of = date(2026, 6, 8)
    ev = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        _seed_trigger(cur, "ESK_DONE", ev, as_of)
        _seed_trigger(cur, "ESK_TODO", ev, as_of)
        _seed_trigger(cur, "ESK_OTHER", ev, date(2026, 6, 9))  # 다른 as_of
        # ESK_DONE 은 이미 entry_params 존재
        cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,analyzed_for_date) "
                    "VALUES ('ESK_DONE',%s,100,92,%s)", (ev, as_of))
    db.commit()
    got = {r[0] for r in _fetch_go_now_candidates(db, as_of)}
    assert "ESK_TODO" in got        # 미처리 → 포함
    assert "ESK_DONE" not in got    # 이미 entry_params → skip
    assert "ESK_OTHER" not in got   # 다른 as_of → 비대상
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_rerun_entry_skip.py -v`
Expected: FAIL — ESK_DONE 이 결과에 포함됨(현재 skip·as_of 매칭 없음)

- [ ] **Step 3: _fetch_go_now_candidates 수정 (force 인자 추가)**

`entry_params.py:_fetch_go_now_candidates` 를 다음으로 교체:
```python
def _fetch_go_now_candidates(conn, as_of: date, force: bool = False) -> list:
    """as_of go_now breakout(+from_watch) 후보. 2E_tier2 제외.

    force=False 면 이미 entry_params(같은 as_of) 있는 종목 skip(멱등 재개).
    같은 as_of·종목 trigger 행이 둘 이상이어도 DISTINCT ON 으로 1건만.
    """
    skip_clause = "" if force else """
               AND NOT EXISTS (
                   SELECT 1 FROM entry_params ep
                    WHERE ep.symbol = t.symbol
                      AND COALESCE(ep.analyzed_for_date, (ep.signal_at AT TIME ZONE 'UTC')::date) = %(as_of)s
               )"""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT ON (t.symbol) t.symbol, t.evaluated_at, t.prior_classification_at
              FROM trigger_evaluation_log t
             WHERE COALESCE(t.analyzed_for_date, (t.evaluated_at AT TIME ZONE 'UTC')::date) = %(as_of)s
               AND t.decision = 'go_now'
               AND t.trigger_type IN ('breakout', 'breakout_from_watch')
               AND NOT EXISTS (
                   SELECT 1 FROM weekly_classification wc
                    WHERE wc.symbol = t.symbol
                      AND wc.classified_at = (
                          SELECT MAX(classified_at) FROM weekly_classification WHERE symbol = t.symbol
                      )
                      AND wc.triggered_rules ? '2E_tier2'
               ){skip_clause}
             ORDER BY t.symbol, t.evaluated_at DESC
            """,
            {"as_of": as_of},
        )
        return cur.fetchall()
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_rerun_entry_skip.py -v`
Expected: PASS

- [ ] **Step 5: entry_params.run 에 force 배선 + replace delete**

`entry_params.py:run` 시그니처에 `force: bool = False,` 추가. `go_now = _fetch_go_now_candidates(conn, as_of)` 앞에 추가:
```python
    if force:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM entry_params "
                "WHERE COALESCE(analyzed_for_date, (signal_at AT TIME ZONE 'UTC')::date) = %s",
                (as_of,),
            )
        conn.commit()
    go_now = _fetch_go_now_candidates(conn, as_of, force=force)
```

- [ ] **Step 6: force replace 테스트 추가 + 통과**

`tests/test_rerun_entry_skip.py` 에 추가:
```python
def test_force_deletes_entry_params_for_as_of(db):
    from kr_pipeline.llm_runner import entry_params
    as_of = date(2026, 6, 8)
    ev = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('EFD1','x','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,analyzed_for_date) "
                    "VALUES ('EFD1',%s,100,92,%s)", (ev, as_of))
    db.commit()
    # force run (go_now 후보 0 — 삭제만 검증, LLM 미호출)
    entry_params.run(db, dry_run=True, as_of=as_of, force=True)
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM entry_params WHERE symbol='EFD1'")
        assert cur.fetchone()[0] == 0
```

Run: `uv run pytest tests/test_rerun_entry_skip.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: 커밋**

```bash
git add kr_pipeline/llm_runner/entry_params.py tests/test_rerun_entry_skip.py
git commit -m "feat(entry): as_of 기준 skip(NOT EXISTS+DISTINCT ON) + --force replace"
```

---

## Task 5: stage 읽기 — evaluate_pivot skip + force

**Files:**
- Modify: `kr_pipeline/llm_runner/evaluate_pivot.py:run`
- Test: `tests/test_rerun_evaluate_skip.py` (Create)

- [ ] **Step 1: 실패 테스트 작성** — 이미 평가된 종목 제외 헬퍼

```python
# tests/test_rerun_evaluate_skip.py
from datetime import date, datetime, timezone

def test_already_evaluated_symbols_for_as_of(db):
    from kr_pipeline.llm_runner.evaluate_pivot import _already_evaluated_symbols
    as_of = date(2026, 6, 8)
    ev = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('EVS1','x','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO trigger_evaluation_log "
                    "(symbol,evaluated_at,trigger_type,decision,prior_classification_at,analyzed_for_date) "
                    "VALUES ('EVS1',%s,'breakout','wait',%s,%s)", (ev, ev, as_of))
    db.commit()
    assert _already_evaluated_symbols(db, as_of) == {"EVS1"}
    assert _already_evaluated_symbols(db, date(2026, 6, 9)) == set()  # 다른 as_of
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_rerun_evaluate_skip.py -v`
Expected: FAIL — ImportError: cannot import name '_already_evaluated_symbols'

- [ ] **Step 3: evaluate_pivot.py 에 헬퍼 + run 배선**

`evaluate_pivot.py` 에 함수 추가:
```python
def _already_evaluated_symbols(conn, as_of) -> set:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol FROM trigger_evaluation_log "
            "WHERE COALESCE(analyzed_for_date, (evaluated_at AT TIME ZONE 'UTC')::date) = %s",
            (as_of,),
        )
        return {r[0] for r in cur.fetchall()}
```
`run` 시그니처에 `force: bool = False,` 추가. `triggered` 리스트 구성 직후(`if limit:` 앞)에 추가:
```python
    if force:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM trigger_evaluation_log "
                "WHERE COALESCE(analyzed_for_date, (evaluated_at AT TIME ZONE 'UTC')::date) = %s",
                (as_of,),
            )
        conn.commit()
    else:
        done = _already_evaluated_symbols(conn, as_of)
        triggered = [(a, t) for (a, t) in triggered if a["symbol"] not in done]
```

- [ ] **Step 4: 통과 확인 + 기존 evaluate 테스트 회귀**

Run: `uv run pytest tests/test_rerun_evaluate_skip.py tests/test_llm_evaluate_pivot.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/evaluate_pivot.py tests/test_rerun_evaluate_skip.py
git commit -m "feat(evaluate): as_of 기준 이미평가 종목 skip + --force replace delete"
```

---

## Task 6: run 레이어 — duplicate 를 as_of 기준으로

**Files:**
- Modify: `api/services/runner_service.py:check_can_run_pipeline`(프로덕션), `check_can_run`(테스트전용 — 일관성)
- Test: `tests/test_rerun_run_gate.py` (Create)
- (참고: as_of 계산은 Task 2 의 `resolve_as_of` 공유. duplicate 쿼리 자체는 두 함수의 pipeline/mode_prefix 처리가 달라 각자 인라인 수정.)

- [ ] **Step 1: 실패 테스트 작성** — 다른 as_of success 는 can_run, 같은 as_of 는 duplicate

```python
# tests/test_rerun_run_gate.py
from datetime import date, datetime, timedelta, timezone
import json

def _seed_indicators(cur, d):
    cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('RGT1','x','KOSPI') ON CONFLICT DO NOTHING")
    cur.execute("INSERT INTO daily_indicators (ticker,date,adj_close,volume,sma_50,avg_volume_50d,w52_high,w52_low) "
                "VALUES ('RGT1',%s,100,1000,90,1000,120,60) ON CONFLICT DO NOTHING", (d,))

def _seed_success_run(cur, pipeline, as_of, started):
    cur.execute("INSERT INTO pipeline_runs (pipeline,mode,started_at,finished_at,status,params) "
                "VALUES (%s,'full-daily',%s,%s,'success',%s)",
                (pipeline, started, started, json.dumps({"as_of": as_of.isoformat()})))

def test_different_as_of_not_duplicate(db):
    from api.services.runner_service import check_can_run_pipeline
    today = date.today()
    with db.cursor() as cur:
        _seed_indicators(cur, today)  # prospective as_of = today
        # 어제 as_of 로 성공한 run 존재 → 다른 as_of → 중복 아님
        _seed_success_run(cur, "llm_daily_delta", today - timedelta(days=1),
                          datetime.now(timezone.utc))
    db.commit()
    res = check_can_run_pipeline(db, "llm-full-daily")
    assert res["can_run"] is True and res["reason"] == "ok"

def test_same_as_of_is_duplicate(db):
    from api.services.runner_service import check_can_run_pipeline
    today = date.today()
    with db.cursor() as cur:
        _seed_indicators(cur, today)
        _seed_success_run(cur, "llm_daily_delta", today, datetime.now(timezone.utc))
    db.commit()
    res = check_can_run_pipeline(db, "llm-full-daily")
    assert res["can_run"] is False and res["reason"] == "duplicate"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_rerun_run_gate.py -v`
Expected: FAIL — `test_different_as_of_not_duplicate` 가 duplicate 로 차단됨(현재 wall-clock 기준)

- [ ] **Step 3: check_can_run_pipeline 의 duplicate 판정 교체**

`api/services/runner_service.py` 상단에 `from kr_pipeline.llm_runner.load import resolve_as_of` 추가. `check_can_run_pipeline` 의 success 쿼리 블록을 다음으로 교체.

⚠️ **중요(backward-compat)**: `check_can_run_pipeline` 은 모든 파이프라인이 공유하는데, params 에
`as_of` 를 넣는 건 **llm_runner 뿐**(ohlcv/indicators/weekly/market_context/corporate_actions/
universe/data_daily/data_weekly 는 미저장). 순수 `params->>'as_of'` 비교로 바꾸면 그들의 duplicate
방지가 깨짐. 따라서 **결합 조건** — as_of 있으면 as_of 비교(LLM: 오전/오후 독립), 없으면 기존
wall-clock today(레거시 보존):
```python
    prospective = resolve_as_of(conn)
    today = date.today()
    with conn.cursor() as cur:
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
                "can_run": False, "reason": "duplicate", "existing_run_id": run_id,
                "existing_run_summary": {
                    "started_at": started_at.isoformat(),
                    "finished_at": finished_at.isoformat() if finished_at else None,
                    "rows_affected": rows_affected,
                },
            }
    return {"can_run": True, "reason": "ok", "existing_run_id": None}
```
- LLM(as_of 있음): as_of 로 매칭(어느 wall-clock 날이든) → 오전(D-1)/오후(D) 다른 as_of = 중복 아님,
  같은 as_of = 중복.
- 비-LLM(as_of NULL): 기존 wall-clock today 로 매칭(레거시 보존). `universe` 는 키가 `on_date` 라
  as_of NULL 취급 → wall-clock 유지(의도된 비변경).

- [ ] **Step 4: check_can_run (모드기반, 테스트전용) 동일 교체 + 비-LLM 레거시 회귀 테스트**

`check_can_run` 의 success 쿼리도 같은 **결합 조건**(as_of 매칭 OR (as_of NULL AND wall-clock today))으로 교체. `tests/test_rerun_run_gate.py` 에 비-LLM 보존 테스트 추가:
```python
def test_non_asof_pipeline_keeps_wallclock_duplicate(db):
    """as_of 없는 파이프라인(ohlcv 등)은 오늘 성공 시 여전히 duplicate(레거시 보존)."""
    from api.services.runner_service import check_can_run_pipeline
    from datetime import datetime, timezone
    with db.cursor() as cur:
        # ohlcv 파이프라인: params 에 as_of 없음
        cur.execute("INSERT INTO pipeline_runs (pipeline,mode,started_at,finished_at,status,params) "
                    "VALUES ('ohlcv','incremental',%s,%s,'success',%s)",
                    (datetime.now(timezone.utc), datetime.now(timezone.utc), '{\"start\": \"2026-06-01\"}'))
    db.commit()
    res = check_can_run_pipeline(db, "ohlcv")   # spec id 확인: ohlcv pipeline_id
    assert res["can_run"] is False and res["reason"] == "duplicate"
```
(※ `ohlcv` pipeline_id 가 PIPELINE_SPECS 의 실제 id 와 다르면 그 id 로 교체. mode_prefix 없으면 mode 'incremental' 매칭.)

- [ ] **Step 5: 통과 확인 + 기존 runner_service 테스트 갱신**

Run: `uv run pytest tests/test_rerun_run_gate.py tests/test_api_runner_service.py -v`
Expected: `test_rerun_run_gate` PASS. `test_api_runner_service` 의 wall-clock 가정 케이스가 깨지면, 그 테스트의 success seed 에 `params={"as_of": ...}` 를 넣고 prospective 와 맞춰 갱신(같은 as_of=duplicate, 다른 as_of=ok). 갱신 후 PASS.

- [ ] **Step 6: 커밋**

```bash
git add api/services/runner_service.py tests/test_rerun_run_gate.py tests/test_api_runner_service.py
git commit -m "feat(runner-gate): duplicate 판정을 params.as_of 기준으로 (오전/오후 독립)"
```

---

## Task 7: force 전파 (CLI + run_full_daily + spawn + router)

**Files:**
- Modify: `kr_pipeline/llm_runner/__main__.py` (--force arg + 전파)
- Modify: `kr_pipeline/llm_runner/modes.py:run_full_daily`
- Modify: `api/services/runner_service.py:spawn_pipeline, spawn_runner`
- Modify: `api/routers/runner.py` (force → spawn)
- Test: `tests/test_rerun_force_wiring.py` (Create)

- [ ] **Step 1: 실패 테스트 작성** — spawn_pipeline 이 --force 를 cmd 에 포함

```python
# tests/test_rerun_force_wiring.py
def test_spawn_pipeline_includes_force(monkeypatch):
    import api.services.runner_service as rs
    captured = {}
    class _Proc:
        pid = 123
    def _fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return _Proc()
    monkeypatch.setattr(rs.subprocess, "Popen", _fake_popen)
    rs.spawn_pipeline("llm-full-daily", "default", params=None, force=True)
    assert "--force" in captured["cmd"]

def test_spawn_pipeline_omits_force_by_default(monkeypatch):
    import api.services.runner_service as rs
    captured = {}
    class _Proc:
        pid = 123
    monkeypatch.setattr(rs.subprocess, "Popen", lambda cmd, **kw: captured.update(cmd=cmd) or _Proc())
    rs.spawn_pipeline("llm-full-daily", "default", params=None)
    assert "--force" not in captured["cmd"]
```
(mode_id "default" 가 spec 에 없으면 llm-full-daily 의 실제 mode_id 로 교체 — `get_mode_args` 가 받는 값.)

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_rerun_force_wiring.py -v`
Expected: FAIL — TypeError: spawn_pipeline() got unexpected keyword 'force' (또는 --force 미포함)

- [ ] **Step 3: spawn_pipeline 에 force 추가**

`spawn_pipeline` 시그니처를 `def spawn_pipeline(pipeline_id, mode_id, params=None, *, force=False):` 로. `cmd = [...]` 다음 줄에:
```python
    if force:
        cmd.append("--force")
```
`spawn_runner` 도 `*, force: bool = False` 추가 + 동일하게 `if force: cmd.append("--force")`.

- [ ] **Step 4: __main__ 에 --force + 전파**

`__main__.py` argparse 에 추가: `parser.add_argument("--force", action="store_true")`. 모드 분기에서:
```python
            elif args.mode == "evaluate":
                result = evaluate_pivot.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit, force=args.force)
            elif args.mode == "entry":
                result = entry_params.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit, force=args.force)
            ...
            elif args.mode == "full-daily":
                result = modes.run_full_daily(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit, force=args.force)
```

- [ ] **Step 5: run_full_daily 전파**

`modes.py:run_full_daily` 시그니처에 `force: bool = False` 추가. evaluate/entry 호출에 `force=force` 전달(disqualify/daily_delta/performance 는 기존 멱등이라 무전파):
```python
    r2 = evaluate_pivot.run(conn, dry_run=dry_run, as_of=as_of, limit=limit, force=force)
    r3 = entry_params.run(conn, dry_run=dry_run, as_of=as_of, limit=limit, force=force)
```

- [ ] **Step 6: router /run 이 force 를 spawn 까지 전달**

`api/routers/runner.py` 의 `spawn_pipeline(req.pipeline_id, req.mode_id, params=req.params)` 를 `spawn_pipeline(req.pipeline_id, req.mode_id, params=req.params, force=req.force)` 로.

- [ ] **Step 7: 통과 확인**

Run: `uv run pytest tests/test_rerun_force_wiring.py -v`
Expected: PASS

- [ ] **Step 8: 커밋**

```bash
git add kr_pipeline/llm_runner/__main__.py kr_pipeline/llm_runner/modes.py api/services/runner_service.py api/routers/runner.py tests/test_rerun_force_wiring.py
git commit -m "feat: --force 전파 (CLI→run_full_daily→stage, web force→spawn --force)"
```

---

## Task 8: 통합 — 오전/오후 독립 + 양쪽 DB 적용 + 회귀

**Files:**
- Test: `tests/test_rerun_morning_evening.py` (Create)

- [ ] **Step 1: 오전/오후 독립 통합 테스트 작성** (stage 레벨, dry_run=False 없이 결정론 부분만)

```python
# tests/test_rerun_morning_evening.py
from datetime import date, datetime, timezone

def test_two_as_of_entry_params_independent(db):
    """as_of=D-1 / as_of=D 의 entry_params 가 서로 skip 하지 않고 독립."""
    from kr_pipeline.llm_runner.entry_params import _fetch_go_now_candidates
    d_prev, d_cur = date(2026, 6, 6), date(2026, 6, 8)
    ev_prev = datetime(2026, 6, 6, 23, 0, tzinfo=timezone.utc)
    ev_cur = datetime(2026, 6, 8, 9, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        for sym, ev, afd in [("MEV1", ev_prev, d_prev), ("MEV1", ev_cur, d_cur)]:
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'x','KOSPI') ON CONFLICT DO NOTHING", (sym,))
            cur.execute("INSERT INTO weekly_classification (symbol,classified_at,market,classification,source) "
                        "VALUES (%s,%s,'KOSPI','entry','test') ON CONFLICT DO NOTHING", (sym, ev))
            cur.execute("INSERT INTO trigger_evaluation_log "
                        "(symbol,evaluated_at,trigger_type,decision,prior_classification_at,analyzed_for_date) "
                        "VALUES (%s,%s,'breakout','go_now',%s,%s) ON CONFLICT DO NOTHING", (sym, ev, ev, afd))
        # 오전(D-1) 분은 이미 entry_params 처리됨
        cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,analyzed_for_date) "
                    "VALUES ('MEV1',%s,100,92,%s)", (ev_prev, d_prev))
    db.commit()
    # 오후(D) 후보: D-1 이 done 이어도 D 는 여전히 후보(독립)
    assert "MEV1" in {r[0] for r in _fetch_go_now_candidates(db, d_cur)}
    # 오전(D-1) 재실행: 이미 done 이라 skip
    assert "MEV1" not in {r[0] for r in _fetch_go_now_candidates(db, d_prev)}
```

- [ ] **Step 2: 통과 확인**

Run: `uv run pytest tests/test_rerun_morning_evening.py -v`
Expected: PASS

- [ ] **Step 3: 운영 DB 양쪽 스키마 적용**

```bash
psql -d kr_pipeline -f kr_pipeline/db/schema.sql >/dev/null && echo kr_pipeline OK
psql -d kr_test -f kr_pipeline/db/schema.sql >/dev/null && echo kr_test OK
for DB in kr_pipeline kr_test; do
  for T in trigger_evaluation_log entry_params; do
    echo -n "$DB.$T.analyzed_for_date: "
    psql -d $DB -tAc "SELECT column_name FROM information_schema.columns WHERE table_name='$T' AND column_name='analyzed_for_date'"
  done
done
```
Expected: 4줄 모두 `analyzed_for_date` 출력.

- [ ] **Step 4: 전체 회귀 (worktree vs base 실패 수 비교)**

Run: `uv run pytest tests/ -q 2>&1 | tail -3`
그리고 base(main) 에서 동일 실행해 **실패 집합이 동일(net 신규 0)** 인지 비교. 신규 테스트는 전부 PASS 여야 함.

- [ ] **Step 5: 커밋**

```bash
git add tests/test_rerun_morning_evening.py
git commit -m "test: 오전/오후 as_of 독립 통합 + 양쪽 DB 스키마 적용"
```

---

## 후속 티켓 (이 계획 범위 밖 — docs/superpowers/backlog 에 별도 기록)
- **(B) performance 기준일 = analyzed_for_date** 교체.
- web UI 설명문(`LlmPipelinePage.tsx`, `tables.ts`) 동기화.
- (선택) 과거 wall-clock 중복 행 일회 cleanup.
