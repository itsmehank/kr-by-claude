# 분류 자격 상실(disqualified) 강등 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 평일 `full-daily` 분석 시, 최신 분류가 entry/watch/ignore 인데 오늘 `minervini_pass=false` 가 된 종목을 `disqualified` 로 강등(시스템 기록) → active/`/classifications` 기본 뷰에서 즉시 제외하고 이탈 이벤트를 이력에 남긴다.

**Architecture:** `run_full_daily` 맨 앞에 결정론 "강등 점검" 단계 신규. load(미통과 active) → store(게이트 우회 직접 INSERT `disqualified`). 멱등(이미 disqualified 는 대상 밖). 필터링은 쿼리 레벨(active 로드 entry/watch 필터 + classifications API 기본 제외)이라 항상 동작.

**Tech Stack:** Python (psycopg, pytest, real test DB rollback fixture) + FastAPI + React/TS. FE 단위테스트 없음 → 프론트는 `npm run build`+`npm run lint`.

**Spec:** `docs/superpowers/specs/2026-06-02-classification-disqualify-design.md`

**Pre-req:** 백엔드 테스트는 `TEST_DATABASE_URL` 필요 (`uv run pytest tests/`). 사전 isolation fail ~26개 baseline — 본 작업이 늘리지 않는지 확인.

---

## File Structure

| 파일 | 책임 | 작업 |
|---|---|---|
| `kr_pipeline/db/schema.sql` | `weekly_classification.classification` VARCHAR(20) widen | Modify |
| `kr_pipeline/llm_runner/store.py` | `insert_disqualification(...)` — 게이트 우회 직접 INSERT | Modify |
| `kr_pipeline/llm_runner/load.py` | `get_classified_losing_minervini(conn, as_of)` | Modify |
| `kr_pipeline/llm_runner/disqualify.py` | 강등 점검 단계 `run(conn, *, dry_run, as_of, limit)` | Create |
| `kr_pipeline/llm_runner/modes.py` | `run_full_daily` 에 disqualify 단계(맨 앞) | Modify |
| `api/routers/classifications.py` | 기본 쿼리에서 `disqualified` 제외 (필터 명시 시만 노출) | Modify |
| `web/src/pages/ClassificationsPage.tsx` | "자격 상실" opt-in 필터 칩 | Modify |
| `web/src/data/llm-pipeline/lifecycle-story.ts` | ⑥장면에 강등 이탈 경로 한 줄 | Modify |
| `tests/test_llm_disqualify.py` | load + 단계 테스트 | Create |
| `tests/test_llm_runner_store.py` | insert_disqualification 테스트 | Modify |
| `tests/test_api_classifications.py` | 기본 제외/필터 포함 테스트 | Create |

---

## Task 1: 스키마 widen + `insert_disqualification`

**Files:** Modify `kr_pipeline/db/schema.sql`, `kr_pipeline/llm_runner/store.py`; Test `tests/test_llm_runner_store.py`

- [ ] **Step 1: 실패 테스트 작성** — append to `tests/test_llm_runner_store.py`:

```python
def test_insert_disqualification(db):
    """시스템 강등 행 — classification='disqualified', source='system_disqualify'."""
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_disqualification
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='DQ1'")
    insert_disqualification(db, symbol="DQ1", classified_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
                            market="KOSPI")
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT classification, source, reasoning FROM weekly_classification WHERE symbol='DQ1'")
        row = cur.fetchone()
    assert row[0] == "disqualified"
    assert row[1] == "system_disqualify"
    assert row[2] is not None  # 자동 사유 문구
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_llm_runner_store.py::test_insert_disqualification -v` → FAIL (ImportError or value too long for VARCHAR(10)).

- [ ] **Step 3: 스키마 widen** — `kr_pipeline/db/schema.sql`, `triggered_rules`/`measurements` ALTER 블록 근처(weekly_classification 관련 ALTER 모음)에 추가:

```sql
-- 2026-06-02: classification 에 'disqualified'(12자) 수용 위해 widen (기존 VARCHAR(10))
ALTER TABLE weekly_classification
  ALTER COLUMN classification TYPE VARCHAR(20);
```
테스트 DB 반영: `psql "$TEST_DATABASE_URL" -f kr_pipeline/db/schema.sql` (idempotent, 에러 없음).

- [ ] **Step 4: `insert_disqualification` 구현** — `kr_pipeline/llm_runner/store.py` 에 함수 추가 (기존 import 그대로 사용; date/datetime 이미 import 됨):

```python
def insert_disqualification(
    conn: Connection,
    *,
    symbol: str,
    classified_at: datetime,
    market: str,
    reason: str = "minervini_pass=false — 미너비니 자격 상실(시스템 강등)",
) -> None:
    """시스템 발 강등 행 직접 INSERT (LLM/Phase1 게이트 우회).

    disqualified 는 결정론 이벤트이지 LLM 분류가 아니므로 apply_phase1_gates 를 거치지 않는다.
    pattern/pivot/confidence/triggered_rules 는 NULL.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO weekly_classification
              (symbol, classified_at, market, classification, source, reasoning)
            VALUES (%s, %s, %s, 'disqualified', 'system_disqualify', %s)
            ON CONFLICT (symbol, classified_at) DO NOTHING
            """,
            (symbol, classified_at, market, reason),
        )
```

- [ ] **Step 5: 통과 확인** — `uv run pytest tests/test_llm_runner_store.py -v` → PASS (신규 + 기존).

- [ ] **Step 6: Commit**
```bash
git add kr_pipeline/db/schema.sql kr_pipeline/llm_runner/store.py tests/test_llm_runner_store.py
git commit -m "feat(disqualify): classification VARCHAR(20) widen + insert_disqualification (게이트 우회 직접 INSERT)"
```

---

## Task 2: `get_classified_losing_minervini` (load)

**Files:** Modify `kr_pipeline/llm_runner/load.py`; Create `tests/test_llm_disqualify.py`

- [ ] **Step 1: 실패 테스트 작성** — create `tests/test_llm_disqualify.py`:

```python
from datetime import date, datetime, timezone

AS_OF = date(2026, 6, 2)

def _seed(cur, ticker, classification, minervini_pass):
    cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
                (ticker, ticker))
    cur.execute("""INSERT INTO daily_indicators (ticker, date, adj_close, minervini_pass)
                   VALUES (%s, %s, 100, %s) ON CONFLICT DO NOTHING""", (ticker, AS_OF, minervini_pass))
    cur.execute("""INSERT INTO weekly_classification (symbol, classified_at, market, classification, source)
                   VALUES (%s, %s, 'KOSPI', %s, 'weekend')""",
                (ticker, datetime(2026, 5, 30, tzinfo=timezone.utc), classification))


def test_get_classified_losing_minervini(db):
    from kr_pipeline.llm_runner.load import get_classified_losing_minervini
    with db.cursor() as cur:
        for t in ("LOSE_W", "LOSE_E", "LOSE_I", "KEEP_W", "ALREADY_DQ"):
            cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (t,))
        _seed(cur, "LOSE_W", "watch", False)    # 강등 대상
        _seed(cur, "LOSE_E", "entry", False)    # 강등 대상
        _seed(cur, "LOSE_I", "ignore", False)   # 강등 대상
        _seed(cur, "KEEP_W", "watch", True)     # 통과 → 대상 아님
        _seed(cur, "ALREADY_DQ", "disqualified", False)  # 이미 강등 → 대상 아님(멱등)
    db.commit()
    losers = {x["symbol"] for x in get_classified_losing_minervini(db, AS_OF)}
    assert losers >= {"LOSE_W", "LOSE_E", "LOSE_I"}
    assert "KEEP_W" not in losers
    assert "ALREADY_DQ" not in losers
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_llm_disqualify.py::test_get_classified_losing_minervini -v` → FAIL (ImportError).

- [ ] **Step 3: 구현** — `kr_pipeline/llm_runner/load.py` 에 함수 추가:

```python
def get_classified_losing_minervini(conn: Connection, as_of: date) -> list[dict]:
    """최신 분류가 entry/watch/ignore 인데 as_of 의 minervini_pass=false 인 종목.

    이미 disqualified 인 종목은 IN 절에서 제외 → 멱등(재강등 안 함).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH latest AS (
              SELECT DISTINCT ON (symbol) symbol, market, classification
                FROM weekly_classification
               ORDER BY symbol, classified_at DESC
            )
            SELECT l.symbol, l.market
              FROM latest l
              JOIN daily_indicators i ON i.ticker = l.symbol AND i.date = %s
             WHERE l.classification IN ('entry', 'watch', 'ignore')
               AND i.minervini_pass = FALSE
            """,
            (as_of,),
        )
        return [{"symbol": r[0], "market": r[1]} for r in cur.fetchall()]
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_llm_disqualify.py -v` → PASS.

- [ ] **Step 5: Commit**
```bash
git add kr_pipeline/llm_runner/load.py tests/test_llm_disqualify.py
git commit -m "feat(disqualify): get_classified_losing_minervini — 미통과 active 종목 로드(멱등)"
```

---

## Task 3: `disqualify.py` 단계 + `run_full_daily` 연결

**Files:** Create `kr_pipeline/llm_runner/disqualify.py`; Modify `kr_pipeline/llm_runner/modes.py`; Test `tests/test_llm_disqualify.py`

- [ ] **Step 1: 실패 테스트 작성** — append to `tests/test_llm_disqualify.py` (헬퍼 `_seed` 재사용):

```python
def test_disqualify_run_writes_and_idempotent(db):
    from kr_pipeline.llm_runner import disqualify
    with db.cursor() as cur:
        for t in ("RUN_LOSE", "RUN_KEEP"):
            cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (t,))
        _seed(cur, "RUN_LOSE", "watch", False)
        _seed(cur, "RUN_KEEP", "entry", True)
    db.commit()

    r1 = disqualify.run(db, dry_run=False, as_of=AS_OF, limit=None)
    assert r1["disqualified"] == 1
    with db.cursor() as cur:
        cur.execute("SELECT DISTINCT ON (symbol) classification FROM weekly_classification WHERE symbol='RUN_LOSE' ORDER BY symbol, classified_at DESC")
        assert cur.fetchone()[0] == "disqualified"
        cur.execute("SELECT DISTINCT ON (symbol) classification FROM weekly_classification WHERE symbol='RUN_KEEP' ORDER BY symbol, classified_at DESC")
        assert cur.fetchone()[0] == "entry"  # 통과 종목 그대로

    # 멱등: 2회차엔 추가 강등 없음 (이미 disqualified)
    r2 = disqualify.run(db, dry_run=False, as_of=AS_OF, limit=None)
    assert r2["disqualified"] == 0


def test_disqualify_dry_run_no_write(db):
    from kr_pipeline.llm_runner import disqualify
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='DRY_LOSE'")
        _seed(cur, "DRY_LOSE", "watch", False)
    db.commit()
    r = disqualify.run(db, dry_run=True, as_of=AS_OF, limit=None)
    assert r["disqualified"] == 0
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM weekly_classification WHERE symbol='DRY_LOSE' AND classification='disqualified'")
        assert cur.fetchone()[0] == 0
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_llm_disqualify.py::test_disqualify_run_writes_and_idempotent -v` → FAIL (모듈 없음).

- [ ] **Step 3: `disqualify.py` 구현** — create `kr_pipeline/llm_runner/disqualify.py`:

```python
"""평일 강등 점검 — 최신 분류 종목이 minervini 미통과로 떨어지면 disqualified 기록.

결정론·LLM 미호출. run_full_daily 맨 앞에서 실행. 멱등(이미 disqualified 는 대상 밖).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from psycopg import Connection

from kr_pipeline.llm_runner.load import get_classified_losing_minervini
from kr_pipeline.llm_runner.store import insert_disqualification

log = logging.getLogger("kr_pipeline.llm_runner.disqualify")


def run(conn: Connection, *, dry_run: bool = False, as_of: date | None = None,
        limit: int | None = None) -> dict:
    if as_of is None:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) FROM daily_indicators")
            row = cur.fetchone()
        as_of = row[0] if row and row[0] else date.today()

    losers = get_classified_losing_minervini(conn, as_of)
    if limit:
        losers = losers[:limit]
    log.info("disqualify: %d candidate(s) losing minervini as_of=%s", len(losers), as_of)

    classified_at = datetime.now(timezone.utc)
    count = 0
    for x in losers:
        if dry_run:
            continue
        try:
            insert_disqualification(conn, symbol=x["symbol"], classified_at=classified_at, market=x["market"])
            conn.commit()
            count += 1
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            log.warning("disqualify failed symbol=%s: %s", x["symbol"], e)

    return {"disqualified": count, "candidates": len(losers), "as_of": str(as_of)}
```

- [ ] **Step 4: `run_full_daily` 연결** — `kr_pipeline/llm_runner/modes.py`:
  - import 라인(`weekend, daily_delta, evaluate_pivot, entry_params, performance,`)에 `disqualify` 추가.
  - `run_full_daily` 본문 맨 앞에 단계 추가:
```python
def run_full_daily(conn: Connection, *, dry_run: bool, as_of: date, limit: int | None) -> dict:
    """평일 통합: disqualify → daily_delta → evaluate → entry → performance."""
    r0 = disqualify.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    r1 = daily_delta.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    r2 = evaluate_pivot.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    r3 = entry_params.run(conn, dry_run=dry_run, as_of=as_of, limit=limit)
    r4 = performance.run(conn, as_of=as_of)
    return {"disqualify": r0, "daily_delta": r1, "evaluate": r2, "entry": r3, "performance": r4}
```

- [ ] **Step 5: 통과 + 회귀** — `uv run pytest tests/test_llm_disqualify.py -v` → PASS. `uv run python -c "from kr_pipeline.llm_runner import modes, disqualify; print('import OK')"`.

- [ ] **Step 6: Commit**
```bash
git add kr_pipeline/llm_runner/disqualify.py kr_pipeline/llm_runner/modes.py tests/test_llm_disqualify.py
git commit -m "feat(disqualify): 강등 점검 단계 + run_full_daily 맨앞 연결 (멱등·dry_run)"
```

---

## Task 4: `/classifications` 기본 제외 + 필터 포함

**Files:** Modify `api/routers/classifications.py`; Create `tests/test_api_classifications.py`

- [ ] **Step 1: 실패 테스트 작성** — create `tests/test_api_classifications.py`:

```python
from datetime import datetime, timezone

def _seed(cur, ticker, classification):
    cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
                (ticker, ticker))
    cur.execute("""INSERT INTO weekly_classification (symbol, classified_at, market, classification, source)
                   VALUES (%s, %s, 'KOSPI', %s, 'weekend')""",
                (ticker, datetime.now(timezone.utc), classification))


def test_classifications_default_excludes_disqualified(db):
    from api.routers.classifications import get_classifications
    with db.cursor() as cur:
        for t in ("API_W", "API_DQ"):
            cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (t,))
        _seed(cur, "API_W", "watch")
        _seed(cur, "API_DQ", "disqualified")
    db.commit()
    # 기본(필터 미지정) → disqualified 제외
    syms = {r.symbol for r in get_classifications(conn=db)}
    assert "API_W" in syms
    assert "API_DQ" not in syms
    # 명시 필터 → 포함
    syms2 = {r.symbol for r in get_classifications(classifications=["disqualified"], conn=db)}
    assert "API_DQ" in syms2
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_api_classifications.py -v` → FAIL (기본이 disqualified 포함하므로 `API_DQ not in` 단언 실패).

- [ ] **Step 3: 구현** — `api/routers/classifications.py` 의 외부 SELECT WHERE 절 수정. 기존:
```python
         WHERE (%(classifications)s::text[] IS NULL OR l.classification = ANY(%(classifications)s::text[]))
```
다음으로 교체:
```python
         WHERE (
                 (%(classifications)s::text[] IS NULL AND l.classification <> 'disqualified')
                 OR (%(classifications)s::text[] IS NOT NULL AND l.classification = ANY(%(classifications)s::text[]))
               )
```
(의미: 필터 미지정 → disqualified 제외 / 필터 지정 → 요청 그대로 — disqualified 명시 시 노출.)

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_api_classifications.py -v` → PASS.

- [ ] **Step 5: Commit**
```bash
git add api/routers/classifications.py tests/test_api_classifications.py
git commit -m "feat(disqualify): /classifications 기본 disqualified 제외 (필터 명시 시만 노출)"
```

---

## Task 5: 프론트 필터 칩 + 생애주기 모달 한 줄

**Files:** Modify `web/src/pages/ClassificationsPage.tsx`, `web/src/data/llm-pipeline/lifecycle-story.ts`. (FE 테스트 없음 → build+lint+수동.)

- [ ] **Step 1: ClassificationsPage 칩 추가** — `web/src/pages/ClassificationsPage.tsx`:
  - `CLASSIFICATION_ORDER` 에 `"disqualified"` 추가: `["watch", "entry", "ignore", "disqualified"] as const`.
  - `CLASSIFICATION_LABELS` 에 추가: `disqualified: "자격 상실"`.
  - `CLASSIFICATION_TONES` 에 추가: `disqualified: "bg-tint-stone text-faint"`.
  - **default `classifications` 는 그대로 `["watch", "entry"]` 유지** (disqualified 는 사용자가 칩으로 켤 때만 요청 → 기본 숨김 유지).

- [ ] **Step 2: 생애주기 모달 ⑥에 강등 경로 한 줄** — `web/src/data/llm-pipeline/lifecycle-story.ts` 의 n:6 scene narration 끝에 덧붙임:
```
... 어느 방향으로든 바뀔 수 있어요(ignore→entry 도 가능). 그리고 미너비니 8조건 *자체* 를 잃으면 → '자격 상실(disqualified)'로 이탈해 분류 목록(active)에서 빠져요(평일 강등 점검이 처리).
```
(기존 narration 문장에 자연스럽게 이어붙이기.)

- [ ] **Step 3: 빌드 + lint** — `web/` 에서 `npm run build` → 0 type errors. `npm run lint` → 신규 변경 파일 에러 0.

- [ ] **Step 4: 수동 확인** — `npm run dev`:
  - `/classifications`: 기본은 watch/entry. "자격 상실" 칩 토글 시 disqualified 종목 노출(데이터 있으면).
  - `/docs/llm-pipeline` 모달 ⑥장면에 강등 이탈 문구 보임.

- [ ] **Step 5: Commit**
```bash
git add web/src/pages/ClassificationsPage.tsx web/src/data/llm-pipeline/lifecycle-story.ts
git commit -m "feat(disqualify): /classifications '자격 상실' 필터 칩 + 생애주기 모달 ⑥ 강등 경로 한 줄"
```

---

## Self-Review (작성자 점검)

**Spec coverage:**
- §1 메커니즘(강등 점검 맨 앞 + 멱등) → Task 2(load 멱등)·Task 3(단계+modes). ✓
- §2 disqualified 값 + VARCHAR(20) → Task 1. ✓
- §3 컴포넌트(schema/load/store/disqualify/modes/api/프론트/모달) → Task 1~5 전부. ✓
- §4 필터링(active 자동제외 + /classifications 기본제외) → active 는 기존 get_active_monitoring(entry/watch 필터)가 자동 처리(코드 무변경, Task 3 테스트가 간접 확인)·Task 4(API). ✓
- §5 엣지(dry_run·멱등·평일만) → Task 3 테스트(dry_run·멱등). 평일만=modes 만 수정(weekend 미변경). ✓
- §6 테스트 → 각 Task TDD + Task 4 API + Task 5 build/lint. ✓

**Placeholder scan:** 없음. 모든 코드/SQL/테스트 완전. modes import 라인 수정은 "weekend, daily_delta, ... 에 disqualify 추가"로 명시.

**Type/이름 consistency:** `insert_disqualification`(Task1) ↔ `disqualify.py`(Task3) 호출 일치(symbol/classified_at/market kwargs). `get_classified_losing_minervini`(Task2) 반환 `{symbol, market}` ↔ Task3 사용(`x["symbol"]`, `x["market"]`) 일치. classification 값 `'disqualified'` 전 Task 동일. API WHERE 파라미터명 `classifications` 기존과 동일.

**주의(실행자):** active 모니터링은 코드 변경 불요 — `get_active_monitoring` 이 이미 `classification in ('entry','watch')` 로 필터하므로 disqualified 는 자동 제외(트리거 대상 아님). 별도 작업 없음. ClassificationsPage 의 `CLASSIFICATION_ORDER` 가 `as const` 면 disqualified 추가 시 관련 타입이 따라오는지 tsc 가 확인.
