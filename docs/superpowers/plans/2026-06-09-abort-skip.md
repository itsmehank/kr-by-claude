# ⑧ abort 자가리셋 skip 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현재 분류에 대해 `abort` 판정난 종목을 다음 재분류 전까지 evaluate_pivot 재평가에서 skip한다(분류는 안 바꿈, 자가리셋).

**Architecture:** `evaluate_pivot.py`에 헬퍼 `_aborted_since_classification`를 추가해 `(symbol, prior_classification_at)` abort 쌍을 현재 active 행의 `(symbol, classified_at)`와 정확 매칭. `run()`의 `elif not force:` 블록에서 기존 멱등 skip(`done`)과 합집합으로 `triggered`에서 제외하고, `abort_skipped` 카운트를 결과 dict에 추가.

**Tech Stack:** Python, psycopg, pytest (TEST_DATABASE_URL=kr_test). spec: `docs/superpowers/specs/2026-06-09-abort-skip-design.md`.

---

## File Structure

- Modify: `kr_pipeline/llm_runner/evaluate_pivot.py`
  - 추가: `_aborted_since_classification(conn, active) -> set[str]` (기존 `_already_evaluated_symbols` 바로 아래, run() 위).
  - 수정: `run()`의 `elif not force:` 블록 (filter 합집합) + 반환 dict (`abort_skipped`).
- Create: `tests/test_abort_skip.py` (헬퍼 단위 테스트 4건 + 결과 dict 키 smoke 1건).

기존 코드 참고:
- `_already_evaluated_symbols` (evaluate_pivot.py:22-30) — 헬퍼 시그니처/스타일 미러.
- `run()` filter 블록 (evaluate_pivot.py:79-83) + 반환 dict (101-106).
- 시드 패턴: `tests/test_rerun_evaluate_skip.py` (trigger_evaluation_log INSERT 컬럼 순서).
- `db` fixture (tests/conftest.py:30-38)는 teardown `rollback` → **테스트에서 `db.commit()` 불필요**(같은 connection이 미커밋 행을 읽음, 오염 없음).

---

### Task 1: `_aborted_since_classification` 헬퍼 + 단위 테스트

**Files:**
- Test: `tests/test_abort_skip.py` (create)
- Modify: `kr_pipeline/llm_runner/evaluate_pivot.py` (add helper after line 30)

- [ ] **Step 1: Write the failing tests**

`tests/test_abort_skip.py` 생성. 헬퍼는 `active`를 dict 리스트로 받으므로 weekly_classification/daily_indicators 시드 불필요 — `active`는 합성 dict, abort 행만 `trigger_evaluation_log`에 시드. `db.commit()` 호출 금지(teardown rollback 격리).

```python
from datetime import date, datetime, timezone


def _seed_abort(cur, symbol, prior_at, *, decision="abort", evaluated_at=None):
    cur.execute(
        "INSERT INTO stocks (ticker,name,market) VALUES (%s,'x','KOSPI') ON CONFLICT DO NOTHING",
        (symbol,),
    )
    ev = evaluated_at or datetime(2099, 3, 2, 1, 0, tzinfo=timezone.utc)
    cur.execute(
        "INSERT INTO trigger_evaluation_log "
        "(symbol,evaluated_at,trigger_type,decision,prior_classification_at,analyzed_for_date) "
        "VALUES (%s,%s,'invalidation',%s,%s,%s) ON CONFLICT DO NOTHING",
        (symbol, ev, decision, prior_at, date(2099, 3, 2)),
    )


def test_abort_against_current_classification_is_skipped(db):
    from kr_pipeline.llm_runner.evaluate_pivot import _aborted_since_classification
    cls_at = datetime(2099, 3, 1, 3, 20, tzinfo=timezone.utc)
    with db.cursor() as cur:
        _seed_abort(cur, "ABT1", cls_at)   # prior == current classified_at
    active = [{"symbol": "ABT1", "classified_at": cls_at}]
    assert _aborted_since_classification(db, active) == {"ABT1"}


def test_abort_against_old_classification_not_skipped(db):
    # 재분류됨: abort 의 prior 는 옛 분류, active.classified_at 은 새 분류 → 미포함(자가리셋)
    from kr_pipeline.llm_runner.evaluate_pivot import _aborted_since_classification
    old_cls = datetime(2099, 3, 1, 3, 20, tzinfo=timezone.utc)
    new_cls = datetime(2099, 3, 8, 3, 20, tzinfo=timezone.utc)
    with db.cursor() as cur:
        _seed_abort(cur, "ABT2", old_cls)
    active = [{"symbol": "ABT2", "classified_at": new_cls}]
    assert _aborted_since_classification(db, active) == set()


def test_no_abort_or_wait_only_not_skipped(db):
    from kr_pipeline.llm_runner.evaluate_pivot import _aborted_since_classification
    cls_at = datetime(2099, 3, 1, 3, 20, tzinfo=timezone.utc)
    with db.cursor() as cur:
        _seed_abort(cur, "ABT3", cls_at, decision="wait")   # wait → 대상 아님
    active = [
        {"symbol": "ABT3", "classified_at": cls_at},
        {"symbol": "ABT4", "classified_at": cls_at},          # abort 행 자체 없음
    ]
    assert _aborted_since_classification(db, active) == set()


def test_classified_at_none_does_not_crash(db):
    from kr_pipeline.llm_runner.evaluate_pivot import _aborted_since_classification
    cls_at = datetime(2099, 3, 1, 3, 20, tzinfo=timezone.utc)
    with db.cursor() as cur:
        _seed_abort(cur, "ABT5", cls_at)
    active = [{"symbol": "ABT5", "classified_at": None}]      # None 방어
    assert _aborted_since_classification(db, active) == set()


def test_empty_active_returns_empty(db):
    from kr_pipeline.llm_runner.evaluate_pivot import _aborted_since_classification
    assert _aborted_since_classification(db, []) == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_abort_skip.py -v`
Expected: FAIL with `ImportError` / `cannot import name '_aborted_since_classification'`.

- [ ] **Step 3: Implement the helper**

`kr_pipeline/llm_runner/evaluate_pivot.py`의 `_already_evaluated_symbols` 함수(라인 30 `return {...}` 끝) 바로 아래, `def run(` 위에 삽입:

```python
def _aborted_since_classification(conn, active: list[dict]) -> set:
    """현재 분류(classified_at)에 대해 abort 판정난 종목 집합.

    abort 기록 시 store 가 prior_classification_at = 그 시점 classified_at 을 박아두므로,
    abort 행의 prior_classification_at == active 행의 현재 classified_at 이면 "현재 분류에
    대한 abort" 다. 재분류되면 classified_at 이 바뀌어 옛 abort 의 prior 와 불일치 → 자동 해제.
    """
    symbols = [a["symbol"] for a in active]
    if not symbols:
        return set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol, prior_classification_at "
            "FROM trigger_evaluation_log "
            "WHERE decision = 'abort' AND symbol = ANY(%s)",
            (symbols,),
        )
        abort_pairs = {(r[0], r[1]) for r in cur.fetchall()}
    result = set()
    for a in active:
        cls_at = a.get("classified_at")
        # classified_at None 이면 매칭 안 함(안전 기본값). abort prior 가 NULL 이면 (sym,NULL)
        # 쌍이 어떤 timestamp 와도 불일치 → 자연 skip-안함.
        if cls_at is not None and (a["symbol"], cls_at) in abort_pairs:
            result.add(a["symbol"])
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_abort_skip.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_abort_skip.py kr_pipeline/llm_runner/evaluate_pivot.py
git commit -m "feat(weekend): ⑧ _aborted_since_classification 헬퍼 (prior_classification_at 정확매칭) + 단위테스트"
```

---

### Task 2: `run()` 필터 합류 + `abort_skipped` 카운트

**Files:**
- Modify: `kr_pipeline/llm_runner/evaluate_pivot.py` (run(): filter 블록 79-83, 반환 dict 101-106)
- Test: `tests/test_abort_skip.py` (smoke 1건 추가)

- [ ] **Step 1: Write the failing smoke test**

`tests/test_abort_skip.py` 끝에 추가. active 종목이 없으면 `triggered=0`이라 LLM 호출 없이 결과 dict만 검증(키 존재 + 기본값 0). 결정론·무부작용.

```python
def test_run_result_includes_abort_skipped_key(db):
    from kr_pipeline.llm_runner import evaluate_pivot
    # 활성 종목 없는 sentinel 미래 as_of → triggered 0, LLM 미호출
    res = evaluate_pivot.run(db, dry_run=True, as_of=date(2099, 12, 31))
    assert "abort_skipped" in res
    assert res["abort_skipped"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_abort_skip.py::test_run_result_includes_abort_skipped_key -v`
Expected: FAIL with `KeyError: 'abort_skipped'` (assert "abort_skipped" in res).

- [ ] **Step 3: Wire the filter + count into run()**

`kr_pipeline/llm_runner/evaluate_pivot.py`의 `elif not force:` 블록을 교체. 현재:

```python
    elif not force:
        done = _already_evaluated_symbols(conn, as_of)
        triggered = [(a, t) for (a, t) in triggered if a["symbol"] not in done]
```

교체 후 (abort_skipped 는 force 경로에서도 정의되도록 블록 위에서 0 초기화):

```python
    abort_skipped = 0
    if force and not dry_run:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM trigger_evaluation_log "
                "WHERE COALESCE(analyzed_for_date, (evaluated_at AT TIME ZONE 'UTC')::date) = %s",
                (as_of,),
            )
        conn.commit()
    elif not force:
        done = _already_evaluated_symbols(conn, as_of)
        aborted = _aborted_since_classification(conn, active)
        abort_skipped = sum(1 for (a, _t) in triggered if a["symbol"] in aborted)
        triggered = [(a, t) for (a, t) in triggered if a["symbol"] not in (done | aborted)]
```

> 주의: 위 교체는 기존 `if force and not dry_run: ... elif not force: ...` 전체를 감싸되,
> `abort_skipped = 0` 을 그 if/elif **앞**에 둔다(force·dry_run+force 경로에서도 반환 dict 가
> 키를 갖도록). `if/elif` 본문 자체(force 의 DELETE 블록)는 변경 없음 — `elif not force` 만 확장.

반환 dict(101-106)에 키 추가:

```python
    return {
        "evaluated": evaluated,
        "failures": len(failed),
        "active": len(active),
        "triggered": len(triggered),
        "abort_skipped": abort_skipped,
    }
```

- [ ] **Step 4: Run smoke test + regression**

Run: `uv run pytest tests/test_abort_skip.py tests/test_rerun_evaluate_skip.py tests/test_evaluate_pivot_guard.py tests/test_llm_evaluate_pivot.py -v`
Expected: all pass (test_abort_skip 6건 포함). 회귀 없음.

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/llm_runner/evaluate_pivot.py tests/test_abort_skip.py
git commit -m "feat(weekend): ⑧ run() 에 abort skip 필터 합류 + abort_skipped 카운트(weekend 밀림 가시화)"
```

---

## Self-Review (작성자 체크 결과)

- **Spec coverage:** 헬퍼(판정)=Task1, 필터 합류+abort_skipped=Task2, 자가리셋=prior 매칭(Task1 test 2건), None 방어=Task1 test, force 미적용=Task2 elif 위치. 숨은 이득 2가지는 동작 보장(별 테스트 불필요 — 필터 부작용). ✓
- **Placeholder scan:** 없음(모든 코드/명령 구체). ✓
- **Type consistency:** 헬퍼명 `_aborted_since_classification` 양 Task 일치. 반환 dict 키 `abort_skipped` 일치. `db` fixture 미커밋 패턴 일관. ✓
- **회귀 주의:** `elif not force` 만 확장, force 의 DELETE 본문 불변 → 기존 rerun/force 테스트 보존.
