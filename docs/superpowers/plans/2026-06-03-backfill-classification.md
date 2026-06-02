# 과거 백필/백테스트 분류 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `--mode=backfill --date=과거` 로 그 시점의 minervini 통과 종목을 (②의 on_date 로 과거 차트를 써서) LLM 분류해 별도 `classification_backfill` 테이블에 멱등 적재한다 — 라이브 분류는 오염 없음.

**Architecture:** `weekly_classification` 미러 테이블(PK `(symbol, analyzed_for_date)`)을 만들고, `store.insert_backfill_classification` 로 라이브와 동일 게이트를 적용해 저장. 신규 `backfill.py` 가 후보(이미 백필된 건 제외) 루프를 돌며 `build_analysis_zip(on_date=as_of)` → `call_claude` → 저장. `__main__.py` 에 `backfill` 모드 추가(`--date` 필수). 라이브 러너·소비처 무변경 → 별도 테이블이라 구조적 격리.

**Tech Stack:** Python (psycopg), PostgreSQL, pytest. 기존 daily_delta.py / store.insert_classification 패턴 재사용.

**테스트 규약 (CLAUDE.md):** `uv run pytest tests/` — 사전 isolation fail 약 26개 baseline, 늘리지 않을 것. 개별: `uv run pytest tests/<file>::<test> -v`. real DB, 고유 ticker + try/finally 정리.

---

### Task 1: classification_backfill 테이블

**Files:**
- Modify: `kr_pipeline/db/schema.sql` (CREATE TABLE 추가)
- Test: `tests/test_schema_backfill.py` (신규)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_schema_backfill.py` 신규 생성

```python
def test_classification_backfill_table_exists_with_pk(db):
    with db.cursor() as cur:
        # 테이블 존재
        cur.execute("SELECT to_regclass('public.classification_backfill')")
        assert cur.fetchone()[0] is not None, "classification_backfill 테이블 없음"
        # PK = (symbol, analyzed_for_date)
        cur.execute(
            """SELECT a.attname
                 FROM pg_index i
                 JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = 'classification_backfill'::regclass AND i.indisprimary
                ORDER BY a.attname"""
        )
        pk_cols = sorted(r[0] for r in cur.fetchall())
    assert pk_cols == ["analyzed_for_date", "symbol"], f"PK 불일치: {pk_cols}"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_schema_backfill.py -v`
Expected: FAIL — to_regclass 가 None (테이블 없음).

- [ ] **Step 3: 구현** — `kr_pipeline/db/schema.sql` 의 weekly_classification 정의 블록 다음에 추가

```sql
CREATE TABLE IF NOT EXISTS classification_backfill (
  symbol               VARCHAR(10) NOT NULL,
  classified_at        TIMESTAMPTZ NOT NULL,
  analyzed_for_date    DATE NOT NULL,
  market               VARCHAR(10) NOT NULL,
  classification       VARCHAR(20) NOT NULL,
  pattern              VARCHAR(50),
  pivot_price          NUMERIC(12, 4),
  pivot_basis          VARCHAR(30),
  base_high            NUMERIC(12, 4),
  base_low             NUMERIC(12, 4),
  base_depth_pct       NUMERIC(5, 2),
  base_start_date      DATE,
  risk_flags           JSONB,
  confidence           NUMERIC(3, 2),
  reasoning            TEXT,
  source               VARCHAR(20) NOT NULL,
  llm_call_duration_s  NUMERIC(8, 2),
  llm_input_tokens     INTEGER,
  llm_output_tokens    INTEGER,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  triggered_rules      JSONB,
  measurements         JSONB,
  PRIMARY KEY (symbol, analyzed_for_date)
);
```

그리고 **DB에 적용**: `psql postgresql://localhost/kr_pipeline -f kr_pipeline/db/schema.sql` (schema.sql 은 IF NOT EXISTS 라 멱등) 또는 위 CREATE 문만 직접 실행. 적용 확인: `psql postgresql://localhost/kr_pipeline -c "\d classification_backfill"`.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_schema_backfill.py -v`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/db/schema.sql tests/test_schema_backfill.py
git commit -m "feat(backfill): classification_backfill 테이블 (weekly_classification 미러, PK symbol+analyzed_for_date)"
```

---

### Task 2: store.insert_backfill_classification

**Files:**
- Modify: `kr_pipeline/llm_runner/store.py` (신규 함수 추가)
- Test: `tests/test_llm_backfill.py` (신규)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_backfill.py` 신규 생성

```python
from datetime import datetime, date, timezone


def _result(cls="watch", pivot=100.0):
    return {
        "classification": cls, "pattern": "flat_base", "pivot_price": pivot,
        "pivot_basis": "range_high", "base_high": pivot, "base_low": pivot * 0.9,
        "base_depth_pct": 8.0, "base_start_date": "2025-08-01", "risk_flags": [],
        "confidence": 0.7, "reasoning": "t",
    }


def test_insert_backfill_classification_basic(db):
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BKF1','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF1'")
    db.commit()
    insert_backfill_classification(
        db, symbol="BKF1", classified_at=datetime(2026, 6, 3, 1, tzinfo=timezone.utc),
        market="KOSPI", result=_result("watch"), source="backfill",
        llm_meta={"duration_s": 10.0, "input_tokens": 100, "output_tokens": 50},
        analyzed_for_date=date(2025, 9, 30),
    )
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT classification, analyzed_for_date, source FROM classification_backfill WHERE symbol='BKF1'"
            )
            rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "watch"
        assert rows[0][1] == date(2025, 9, 30)
        assert rows[0][2] == "backfill"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF1'")
        db.commit()


def test_insert_backfill_idempotent_on_symbol_analyzed_for_date(db):
    """같은 (symbol, analyzed_for_date) 재삽입 → ON CONFLICT DO NOTHING (1행 유지, 덮어쓰기 안 함)."""
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BKF2','B','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF2'")
    db.commit()
    afd = date(2025, 9, 30)
    insert_backfill_classification(db, symbol="BKF2", classified_at=datetime(2026, 6, 3, 1, tzinfo=timezone.utc),
                                   market="KOSPI", result=_result("watch", 111.0), source="backfill",
                                   llm_meta={"duration_s": 1, "input_tokens": 1, "output_tokens": 1},
                                   analyzed_for_date=afd)
    db.commit()
    # 두 번째: 같은 afd, 다른 classified_at/결과 → skip 되어야
    insert_backfill_classification(db, symbol="BKF2", classified_at=datetime(2026, 6, 3, 2, tzinfo=timezone.utc),
                                   market="KOSPI", result=_result("ignore", 999.0), source="backfill",
                                   llm_meta={"duration_s": 1, "input_tokens": 1, "output_tokens": 1},
                                   analyzed_for_date=afd)
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT count(*), max(classification) FROM classification_backfill WHERE symbol='BKF2'")
            cnt, cls = cur.fetchone()
        assert cnt == 1               # 멱등: 1행
        assert cls == "watch"          # 첫 삽입 유지(덮어쓰기 안 함)
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='BKF2'")
        db.commit()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_llm_backfill.py -v`
Expected: FAIL — `ImportError: cannot import name 'insert_backfill_classification'`.

- [ ] **Step 3: 구현** — `store.py` 에 함수 추가 (기존 `insert_classification` 바로 아래). `apply_phase1_gates` 와 `copy`/`json`/`log` 는 이미 import 됨.

```python
def insert_backfill_classification(
    conn: Connection,
    *,
    symbol: str,
    classified_at: datetime,
    market: str,
    result: dict,
    source: str,
    llm_meta: dict,
    analyzed_for_date: date,
) -> None:
    """백필 분류 결과를 classification_backfill 에 INSERT (멱등: symbol+analyzed_for_date).

    insert_classification 과 동일하게 Phase 1 2-A 후처리 게이트 적용. freeze 는 만들지 않음.
    """
    _original = copy.deepcopy(result)
    try:
        result, triggered_rules = apply_phase1_gates(conn, symbol, classified_at, result)
    except Exception as e:
        log.warning(
            "[phase1-gate] backfill failed symbol=%s — 게이트 미적용 원본 저장 (fail-soft): %s",
            symbol, e,
        )
        result = _original
        triggered_rules = None

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO classification_backfill
              (symbol, classified_at, analyzed_for_date, market, classification, pattern,
               pivot_price, pivot_basis, base_high, base_low, base_depth_pct, base_start_date,
               risk_flags, confidence, reasoning,
               source,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens,
               triggered_rules,
               measurements)
            VALUES (%s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    %s, %s, %s,
                    %s,
                    %s)
            ON CONFLICT (symbol, analyzed_for_date) DO NOTHING
            """,
            (
                symbol,
                classified_at,
                analyzed_for_date,
                market,
                result["classification"],
                result.get("pattern"),
                result.get("pivot_price"),
                result.get("pivot_basis"),
                result.get("base_high"),
                result.get("base_low"),
                result.get("base_depth_pct"),
                result.get("base_start_date"),
                json.dumps(result.get("risk_flags", [])),
                result.get("confidence"),
                result.get("reasoning"),
                source,
                llm_meta.get("duration_s"),
                llm_meta.get("input_tokens"),
                llm_meta.get("output_tokens"),
                json.dumps(triggered_rules) if triggered_rules is not None else None,
                json.dumps(result.get("measurements")) if result.get("measurements") is not None else None,
            ),
        )
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_llm_backfill.py -v`
Expected: 두 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/store.py tests/test_llm_backfill.py
git commit -m "feat(backfill): store.insert_backfill_classification (게이트 적용, 멱등 ON CONFLICT)"
```

---

### Task 3: backfill.py — run + _process_one

**Files:**
- Create: `kr_pipeline/llm_runner/backfill.py`
- Test: `tests/test_llm_backfill.py` (추가)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_backfill.py` 끝에 추가

LLM·ZIP 실호출을 피하려 `call_claude` 와 `build_analysis_zip` 를 monkeypatch 한다. on_date 결선은 build_analysis_zip 이 받은 on_date 를 기록해 검증.

```python
def test_backfill_run_inserts_and_wires_on_date(db, monkeypatch):
    import kr_pipeline.llm_runner.backfill as bf
    from datetime import date as _date
    # 실데이터 시작(2024-05-17) 이전 날짜 → get_qualifying_tickers 가 우리가 심은 종목만 반환(격리).
    as_of = _date(2024, 1, 2)
    with db.cursor() as cur:
        cur.execute("DELETE FROM classification_backfill WHERE analyzed_for_date=%s", (as_of,))
        for t in ("BKR1", "BKR2"):
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'B','KOSPI') ON CONFLICT DO NOTHING", (t,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s AND date=%s", (t, as_of))
            cur.execute(
                """INSERT INTO daily_indicators (ticker, date, minervini_pass, adj_close)
                   VALUES (%s,%s,TRUE,1000.0)""",
                (t, as_of),
            )
    db.commit()
    seen_on_date = []
    monkeypatch.setattr(bf, "build_analysis_zip",
                        lambda conn, symbol, on_date=None: seen_on_date.append(on_date) or b"zip")
    monkeypatch.setattr(bf, "call_claude",
                        lambda **kwargs: _result("watch"))
    try:
        res = bf.run(db, dry_run=False, as_of=as_of)
        assert res["processed"] == 2                       # 격리: 정확히 BKR1/BKR2
        # 모든 zip 호출이 on_date=as_of 로 결선됐는지 (②)
        assert seen_on_date and all(d == as_of for d in seen_on_date)
        with db.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM classification_backfill WHERE analyzed_for_date=%s", (as_of,))
            assert cur.fetchone()[0] == 2
        # 멱등: 재실행 시 신규 0 (후보에서 제외)
        res2 = bf.run(db, dry_run=False, as_of=as_of)
        assert res2["processed"] == 0
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE analyzed_for_date=%s", (as_of,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker IN ('BKR1','BKR2') AND date=%s", (as_of,))
        db.commit()
```

> 구현자 주의: `_result` 헬퍼는 Task 2 테스트에서 이미 같은 파일에 정의됨. **as_of=2024-01-02 는 실데이터 시작(2024-05-17) 이전**이라 `get_qualifying_tickers(as_of)` 가 그날 우리가 심은 BKR1/BKR2 만 반환 → 정확한 건수 단언과 깨끗한 정리가 가능. (만약 환경에 2024-01-02 데이터가 있다면 더 이른 빈 날짜로 조정.) `daily_indicators` NOT NULL 컬럼이 더 있으면 보강(adj_close 외). `get_qualifying_tickers` 는 `WHERE i.date = (MAX date ≤ as_of)` 이므로, 그날 우리가 심은 행이 그 자체로 MAX 가 됨.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_llm_backfill.py::test_backfill_run_inserts_and_wires_on_date -v`
Expected: FAIL — `ModuleNotFoundError: kr_pipeline.llm_runner.backfill`.

- [ ] **Step 3: 구현** — `kr_pipeline/llm_runner/backfill.py` 신규 (daily_delta.py 패턴 기반, freeze 없음)

```python
"""과거 백필/백테스트 — 단일 as_of 시점의 minervini 통과 종목 분류 → classification_backfill.

라이브와 같은 프롬프트(analyze_chart_v3.md), ②의 on_date 로 과거 차트 사용.
멱등: 이미 그 as_of 로 백필된 종목은 후보에서 제외. freeze 저장 없음.
"""
from __future__ import annotations

import logging
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from psycopg import Connection

from api.services.zip_builder import build_analysis_zip
from kr_pipeline.llm_runner.llm.claude_cli import call_claude
from kr_pipeline.llm_runner.load import get_qualifying_tickers
from kr_pipeline.llm_runner.store import insert_backfill_classification

log = logging.getLogger("kr_pipeline.llm_runner.backfill")


def _already_backfilled(conn: Connection, as_of: date) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol FROM classification_backfill WHERE analyzed_for_date = %s",
            (as_of,),
        )
        return {r[0] for r in cur.fetchall()}


def run(conn: Connection, *, dry_run: bool = False, as_of: date | None = None,
        limit: int | None = None) -> dict:
    if as_of is None:
        as_of = date.today()

    candidates = get_qualifying_tickers(conn, as_of=as_of)
    done = _already_backfilled(conn, as_of)
    candidates = [c for c in candidates if c["symbol"] not in done]
    if limit:
        candidates = candidates[:limit]

    log.info("backfill: %d candidate(s) as_of=%s (already done %d)", len(candidates), as_of, len(done))

    processed = 0
    failed: list[str] = []
    for c in candidates:
        symbol = c["symbol"]
        market = c["market"]
        try:
            _process_one(conn, symbol, market, dry_run=dry_run, as_of=as_of)
            processed += 1
            conn.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("backfill %s failed: %s", symbol, e)
            failed.append(symbol)
            conn.rollback()

    return {
        "processed": processed,
        "candidates": len(candidates),
        "failures": len(failed),
        "failed_tickers": failed,
        "as_of": str(as_of),
    }


def _process_one(conn: Connection, symbol: str, market: str, *, dry_run: bool, as_of: date) -> None:
    started = datetime.now(timezone.utc)
    zip_bytes = build_analysis_zip(conn, symbol, on_date=as_of)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(zip_bytes)
        zip_path = f.name
    try:
        result = call_claude(
            prompt_file="analyze_chart_v3.md",
            attachments=[zip_path],
            dry_run=dry_run,
        )
    finally:
        Path(zip_path).unlink(missing_ok=True)

    finished = datetime.now(timezone.utc)

    if dry_run:
        log.info("dry-run: skipping backfill insert for %s (%s)", symbol, result.get("classification"))
        return

    insert_backfill_classification(
        conn,
        symbol=symbol,
        classified_at=finished,
        market=market,
        result=result,
        source="backfill",
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": None, "output_tokens": None},
        analyzed_for_date=as_of,
    )
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_llm_backfill.py -v`
Expected: 3개 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/backfill.py tests/test_llm_backfill.py
git commit -m "feat(backfill): backfill.run + _process_one (on_date 결선, 멱등 후보 제외, freeze 없음)"
```

---

### Task 4: __main__ 에 backfill 모드 + --date 필수

**Files:**
- Modify: `kr_pipeline/llm_runner/__main__.py`
- Test: `tests/test_llm_backfill.py` (추가)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_backfill.py` 끝에 추가

```python
def test_backfill_mode_requires_date():
    import sys, pytest
    from kr_pipeline.llm_runner.__main__ import main
    argv = sys.argv
    sys.argv = ["prog", "--mode=backfill"]  # --date 없음
    try:
        with pytest.raises(SystemExit):  # argparse parser.error → SystemExit
            main()
    finally:
        sys.argv = argv
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_llm_backfill.py::test_backfill_mode_requires_date -v`
Expected: FAIL — backfill 이 choices 에 없어 argparse 가 다른 에러를 내거나, 추가 전이라 통과 안 함. (구현 후 SystemExit 로 통과.)

- [ ] **Step 3: 구현** — `__main__.py` 3곳 수정

(a) `--mode` choices 에 `"backfill"` 추가 (약 33행):
```python
        choices=["weekend", "daily-delta", "evaluate", "entry", "performance", "full-daily", "backfill"],
```

(b) `PIPELINE_DB_NAME_BY_MODE` 에 추가 (약 18-25행 dict):
```python
    "backfill": "llm_backfill",
```

(c) `--date` 필수 검증 — 기존 `--ticker` 검증 블록(약 44-49행) 다음에 추가:
```python
    if args.mode == "backfill" and not args.date:
        parser.error("--date is required with --mode=backfill (과거 기준일 없는 백필은 무의미).")
```

(d) import 에 backfill 추가 (약 11-13행 `from kr_pipeline.llm_runner import (...)` 에 `backfill` 추가):
```python
from kr_pipeline.llm_runner import (
    weekend, daily_delta, evaluate_pivot, entry_params, performance, backfill,
)
```

(e) 실행 분기에 추가 (약 80행 `elif args.mode == "daily-delta":` 류 사이):
```python
            elif args.mode == "backfill":
                result = backfill.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
```

- [ ] **Step 4: 통과 확인 + 회귀**

Run: `uv run pytest tests/test_llm_backfill.py -v`
Expected: 신규 PASS. (전체 backfill 테스트 4개 PASS.)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/__main__.py tests/test_llm_backfill.py
git commit -m "feat(backfill): --mode=backfill 라우팅 + --date 필수 검증 + llm_backfill 추적"
```

---

### Task 5: 격리 회귀 테스트 — 백필 행이 라이브 뷰에 안 보임

**Files:**
- Test: `tests/test_api_classifications.py` (추가)

- [ ] **Step 1: 테스트 작성** — `tests/test_api_classifications.py` 끝에 추가

```python
def test_backfill_rows_not_in_live_classifications(client, db):
    """classification_backfill 에만 있는 종목은 /api/classifications(weekly_classification)에 안 뜬다."""
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='ISOLBKF'")
            cur.execute("DELETE FROM weekly_classification WHERE symbol='ISOLBKF'")
            cur.execute("DELETE FROM stocks WHERE ticker='ISOLBKF'")
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('ISOLBKF','Iso','KOSPI')")
            # 백필 테이블에만 watch 행 (라이브엔 없음)
            cur.execute(
                """INSERT INTO classification_backfill
                     (symbol, classified_at, analyzed_for_date, market, classification, source)
                   VALUES ('ISOLBKF', NOW(), CURRENT_DATE - 1, 'KOSPI', 'watch', 'backfill')"""
            )
        db.commit()
        r = client.get("/api/classifications?lookback_days=30&classifications=watch&classifications=entry")
        syms = {row["symbol"] for row in r.json()}
        assert "ISOLBKF" not in syms, "백필 행이 라이브 분류 API에 누수됨"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='ISOLBKF'")
            cur.execute("DELETE FROM stocks WHERE ticker='ISOLBKF'")
        db.commit()
        app.dependency_overrides.pop(get_conn, None)
```

- [ ] **Step 2: 통과 확인**

Run: `uv run pytest tests/test_api_classifications.py::test_backfill_rows_not_in_live_classifications -v`
Expected: PASS (별도 테이블이라 라이브 API가 조회 안 함 → 누수 없음).

> 이 테스트는 격리가 "구조적으로" 보장됨을 회귀로 못박는다. (프로덕션 코드 변경 없음 — 테스트만.)

- [ ] **Step 3: 커밋**

```bash
git add tests/test_api_classifications.py
git commit -m "test(backfill): 백필 행이 라이브 /api/classifications 에 안 보임(격리) 회귀"
```

---

### Task 6: 전체 회귀 + baseline 점검

**Files:** 없음 (검증만)

- [ ] **Step 1: 전체 테스트**

Run: `uv run pytest tests/ -q`
Expected: 신규 테스트 전부 PASS. 실패는 사전 baseline(~26 isolation fail) 이내 — 그 수가 늘지 않았는지 확인.

- [ ] **Step 2: 라이브 무변경 확인**

Run: `grep -rn "build_analysis_zip(conn, symbol)" kr_pipeline/llm_runner/weekend.py kr_pipeline/llm_runner/daily_delta.py`
Expected: 두 라이브 러너는 여전히 on_date 없이 호출(백필 도입이 라이브를 안 바꿈).

- [ ] **Step 3: 최종 커밋 체인 확인**

Run: `git log --oneline main..HEAD`
Expected: Task 1~5 커밋 존재.

---

## 자기 점검 결과 (작성자)

- **스펙 커버리지**: 테이블=T1, 저장(게이트·멱등)=T2, run/_process_one(후보제외·on_date·freeze없음)=T3, --mode/--date필수/추적=T4, 격리=T5, 회귀=T6. 적재·멱등·격리·on_date결선·--date필수·스키마 테스트 모두 매핑됨.
- **placeholder**: 없음. monkeypatch 로 LLM/ZIP 실호출 회피(구체 코드). daily_indicators NOT NULL 보강은 구현자 확인(① 검증된 패턴).
- **타입 일관성**: `insert_backfill_classification` 시그니처(analyzed_for_date: date 필수)가 T2 정의와 T3 호출 일치. `backfill.run`/`_process_one` 시그니처 일관. `build_analysis_zip(..., on_date=as_of)` 가 ②의 시그니처와 일치. monkeypatch 대상이 backfill 모듈 네임스페이스(`bf.build_analysis_zip`, `bf.call_claude`)와 일치.
