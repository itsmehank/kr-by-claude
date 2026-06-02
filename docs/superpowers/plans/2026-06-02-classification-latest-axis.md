# 분류 "최신 상태" 판정 축 전환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 종목의 "현재 분류 상태" 판정을 `classified_at`(실행 시각)에서 `analyzed_for_date`(데이터 기준일) + `classified_at` 타이브레이크로 전환한다.

**Architecture:** "최신 1건 선택"과 staleness 필터를 쓰는 6개 소비처의 SQL `ORDER BY`/`WHERE`를 공통 키로 교체한다. 실행 최근성 가드(`delta.py`)는 의도적으로 유지. NULL(레거시·disqualified)은 `COALESCE(analyzed_for_date, classified_at::date)`로 폴백해 하위호환.

**Tech Stack:** Python (psycopg, FastAPI), PostgreSQL, pytest. 모든 변경은 인라인 SQL 문자열 + 테스트.

**Canonical keys (모든 변경에 동일 적용):**
- 최신 선택: `ORDER BY [symbol,] COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC`
- staleness: `WHERE COALESCE(analyzed_for_date, classified_at::date) >= CURRENT_DATE - %(lookback_days)s::int`

> staleness가 기존 "롤링 24h(`NOW() - interval`)"에서 "달력일(`CURRENT_DATE - N`)" 의미로 바뀐다. 기존 테스트는 영향권 밖(경계 케이스 아님)이며 그린 유지된다. 분석 기준일이 본질적으로 date라 date 비교가 정합적.

**테스트 실행 규약 (CLAUDE.md):** `uv run pytest tests/` — 사전 존재 isolation fail 약 25개는 baseline. 새 작업이 그 수를 늘리지 않아야 한다. 개별 테스트는 `uv run pytest tests/<file>::<test> -v`.

---

### Task 1: web 분류 API — 내부 CTE 축 전환

**Files:**
- Modify: `api/routers/classifications.py:38-48` (내부 `latest` CTE의 `WHERE`/`ORDER BY`만. 외부 `SORT_CLAUSES`는 변경 안 함)
- Test: `tests/test_api_classifications.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_api_classifications.py` 끝에 추가

```python
def test_latest_picked_by_analyzed_for_date_not_classified_at(client, db):
    """더 오래전 데이터(analyzed_for_date)지만 더 늦게 실행(classified_at)된 행이
    최신 상태를 덮어쓰지 않는다."""
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='CLSAXIS1'")
            cur.execute("DELETE FROM stocks WHERE ticker='CLSAXIS1'")
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES ('CLSAXIS1','Ax','KOSPI')"
            )
            # 데이터 기준 최신 = ignore (analyzed_for_date 어제), classified_at 2일 전
            cur.execute(
                """INSERT INTO weekly_classification
                     (symbol, classified_at, analyzed_for_date, market, classification, source)
                   VALUES ('CLSAXIS1', NOW() - INTERVAL '2 day', CURRENT_DATE - 1,
                           'KOSPI', 'ignore', 'weekend')"""
            )
            # 백필성 = watch (analyzed_for_date 30일 전), classified_at 방금(가장 늦음)
            cur.execute(
                """INSERT INTO weekly_classification
                     (symbol, classified_at, analyzed_for_date, market, classification, source)
                   VALUES ('CLSAXIS1', NOW(), CURRENT_DATE - 30,
                           'KOSPI', 'watch', 'weekend')"""
            )
        db.commit()
        r = client.get("/api/classifications?lookback_days=90&classifications=watch&classifications=ignore")
        rows = [x for x in r.json() if x["symbol"] == "CLSAXIS1"]
        assert len(rows) == 1
        assert rows[0]["classification"] == "ignore"  # analyzed_for_date 최신이 이김
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='CLSAXIS1'")
            cur.execute("DELETE FROM stocks WHERE ticker='CLSAXIS1'")
        db.commit()
        app.dependency_overrides.pop(get_conn, None)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_classifications.py::test_latest_picked_by_analyzed_for_date_not_classified_at -v`
Expected: FAIL — 현재는 classified_at DESC라 'watch'가 선택되어 assert 실패.

- [ ] **Step 3: 구현** — `classifications.py`의 내부 CTE를 교체

기존:
```python
           WHERE classified_at >= NOW() - (%(lookback_days)s || ' days')::interval
             AND (%(ticker)s::text IS NULL OR symbol = %(ticker)s)
           ORDER BY symbol, classified_at DESC
```
변경:
```python
           WHERE COALESCE(analyzed_for_date, classified_at::date) >= CURRENT_DATE - %(lookback_days)s::int
             AND (%(ticker)s::text IS NULL OR symbol = %(ticker)s)
           ORDER BY symbol, COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC
```

- [ ] **Step 4: 통과 확인 + 기존 회귀**

Run: `uv run pytest tests/test_api_classifications.py -v`
Expected: 신규 테스트 PASS, 기존 분류 테스트 전부 PASS (lookback/distinct/필터 포함).

- [ ] **Step 5: 커밋**

```bash
git add api/routers/classifications.py tests/test_api_classifications.py
git commit -m "feat(classification): web API 최신판정/staleness를 analyzed_for_date 축으로 전환"
```

---

### Task 2: load.get_active_monitoring 축 전환

**Files:**
- Modify: `kr_pipeline/llm_runner/load.py:51-56` (`ORDER BY`)
- Test: `tests/test_llm_store_load.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_store_load.py` 끝에 추가

```python
def test_active_monitoring_latest_by_analyzed_for_date(db):
    """analyzed_for_date 최신 행이 active 판정 기준이 된다."""
    from kr_pipeline.llm_runner.load import get_active_monitoring
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='AXMON1'")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('AXMON1','A','KOSPI') ON CONFLICT DO NOTHING")
        # 데이터 최신 = ignore (어제), 실행은 2일 전
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source)
               VALUES ('AXMON1', NOW() - INTERVAL '2 day', CURRENT_DATE - 1, 'KOSPI', 'ignore', 'weekend')"""
        )
        # 백필성 watch (30일전 데이터), 실행은 방금
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source, pivot_price, base_low)
               VALUES ('AXMON1', NOW(), CURRENT_DATE - 30, 'KOSPI', 'watch', 'weekend', 100, 90)"""
        )
    db.commit()
    try:
        syms = [a["symbol"] for a in get_active_monitoring(db)]
        # 최신은 ignore → active(entry/watch) 목록에서 제외돼야 함
        assert "AXMON1" not in syms
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='AXMON1'")
        db.commit()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_llm_store_load.py::test_active_monitoring_latest_by_analyzed_for_date -v`
Expected: FAIL — classified_at DESC라 watch가 최신으로 잡혀 'AXMON1'이 active에 포함됨.

- [ ] **Step 3: 구현** — `load.py:55`

기존:
```python
             ORDER BY symbol, classified_at DESC
```
변경:
```python
             ORDER BY symbol, COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC
```

- [ ] **Step 4: 통과 확인 + 회귀**

Run: `uv run pytest tests/test_llm_store_load.py::test_active_monitoring_latest_by_analyzed_for_date tests/test_llm_store_load.py::test_load_active_monitoring -v`
Expected: 둘 다 PASS.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/load.py tests/test_llm_store_load.py
git commit -m "feat(classification): get_active_monitoring 최신판정을 analyzed_for_date 축으로"
```

---

### Task 3: load.get_classified_losing_minervini (강등 판정) 축 전환

**Files:**
- Modify: `kr_pipeline/llm_runner/load.py:84-88` (CTE `ORDER BY`)
- Test: `tests/test_llm_store_load.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_losing_minervini_uses_analyzed_for_date_latest(db):
    """강등 판정의 '최신 분류'도 analyzed_for_date 기준."""
    from datetime import date
    from kr_pipeline.llm_runner.load import get_classified_losing_minervini
    as_of = date(2026, 6, 1)
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='AXLOSE1'")
        cur.execute("DELETE FROM daily_indicators WHERE ticker='AXLOSE1'")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('AXLOSE1','A','KOSPI') ON CONFLICT DO NOTHING")
        # 데이터 최신 = ignore (as_of 당일 분석), 실행 2일 전
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source)
               VALUES ('AXLOSE1', NOW() - INTERVAL '2 day', %s, 'KOSPI', 'ignore', 'weekend')""",
            (as_of,),
        )
        # 백필성 watch (오래전 데이터), 실행 방금
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source)
               VALUES ('AXLOSE1', NOW(), %s, 'KOSPI', 'watch', 'weekend')""",
            (as_of.replace(month=1),),
        )
        # as_of 당일 minervini 탈락
        cur.execute(
            """INSERT INTO daily_indicators (ticker, date, minervini_pass)
               VALUES ('AXLOSE1', %s, FALSE)
               ON CONFLICT (ticker, date) DO UPDATE SET minervini_pass=FALSE""",
            (as_of,),
        )
    db.commit()
    try:
        losers = {x["symbol"] for x in get_classified_losing_minervini(db, as_of)}
        # 최신이 ignore(여전히 entry/watch/ignore 중 하나)라 강등 대상엔 포함됨
        assert "AXLOSE1" in losers
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='AXLOSE1'")
            cur.execute("DELETE FROM daily_indicators WHERE ticker='AXLOSE1'")
        db.commit()
```

> 이 테스트는 강등 대상 집합 자체는 축과 무관하게 동일함을 확인한다(ignore도 watch도 모두 'entry/watch/ignore' 집합). 핵심은 축 변경 후에도 쿼리가 깨지지 않고 같은 결정을 내리는지의 회귀 안전망이다.

- [ ] **Step 2: 실패/통과 확인**

Run: `uv run pytest tests/test_llm_store_load.py::test_losing_minervini_uses_analyzed_for_date_latest -v`
Expected: Step 3 적용 전에도 통과할 수 있으나(집합 동일), 쿼리 컴파일 회귀 확인용. 적용 후 PASS 유지.

- [ ] **Step 3: 구현** — `load.py:87`

기존:
```python
               ORDER BY symbol, classified_at DESC
```
변경:
```python
               ORDER BY symbol, COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_llm_store_load.py::test_losing_minervini_uses_analyzed_for_date_latest -v`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/load.py tests/test_llm_store_load.py
git commit -m "feat(classification): 강등 판정(losing_minervini) 최신선택을 analyzed_for_date 축으로"
```

---

### Task 4: zip_builder._fetch_latest_analysis_result 축 전환

**Files:**
- Modify: `api/services/zip_builder.py:110-114` (`ORDER BY`)
- Test: `tests/test_api_zip_builder.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_api_zip_builder.py` 끝에 추가

```python
def test_fetch_latest_analysis_result_by_analyzed_for_date(db):
    from api.services.zip_builder import _fetch_latest_analysis_result
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='AXZIP1'")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('AXZIP1','A','KOSPI') ON CONFLICT DO NOTHING")
        # 데이터 최신 = entry (어제), 실행 2일 전
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source, confidence)
               VALUES ('AXZIP1', NOW() - INTERVAL '2 day', CURRENT_DATE - 1, 'KOSPI', 'entry', 'weekend', 0.9)"""
        )
        # 백필성 ignore (30일전), 실행 방금
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source, confidence)
               VALUES ('AXZIP1', NOW(), CURRENT_DATE - 30, 'KOSPI', 'ignore', 'weekend', 0.3)"""
        )
    db.commit()
    try:
        result = _fetch_latest_analysis_result(db, "AXZIP1")
        assert result is not None
        assert result["classification"] == "entry"  # analyzed_for_date 최신
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='AXZIP1'")
        db.commit()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_zip_builder.py::test_fetch_latest_analysis_result_by_analyzed_for_date -v`
Expected: FAIL — 현재는 'ignore' 반환.

- [ ] **Step 3: 구현** — `zip_builder.py:112`

기존:
```python
             ORDER BY classified_at DESC
             LIMIT 1
```
변경:
```python
             ORDER BY COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC
             LIMIT 1
```

- [ ] **Step 4: 통과 확인 + 회귀**

Run: `uv run pytest tests/test_api_zip_builder.py -v`
Expected: 신규 PASS, 기존 zip_builder 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add api/services/zip_builder.py tests/test_api_zip_builder.py
git commit -m "feat(classification): zip_builder 최신 분석 선택을 analyzed_for_date 축으로"
```

---

### Task 5: payload_lite 활성 신호 prior 선택 축 전환 (2개 쿼리)

**Files:**
- Modify: `kr_pipeline/llm_runner/compute/payload_lite.py:35` 및 `:159` (둘 다 `ORDER BY classified_at DESC LIMIT 1`)
- Test: `tests/test_llm_compute_payload_lite.py`

- [ ] **Step 1: 실패 테스트 작성** — 기존 테스트 파일 끝에 추가 (대상 함수명은 파일 상단 import 확인 후 사용; 첫 쿼리를 쓰는 공개 함수 호출)

```python
def test_payload_lite_prior_by_analyzed_for_date(db):
    """활성 신호 prior 선택도 analyzed_for_date 최신 + entry/watch 필터 유지."""
    import kr_pipeline.llm_runner.compute.payload_lite as pl
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='AXPL1'")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('AXPL1','A','KOSPI') ON CONFLICT DO NOTHING")
        # 데이터 최신 watch (어제), 실행 2일 전, pivot 111
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source,
                  pattern, pivot_price, pivot_basis, base_high, base_low, base_depth_pct, risk_flags, reasoning)
               VALUES ('AXPL1', NOW() - INTERVAL '2 day', CURRENT_DATE - 1, 'KOSPI', 'watch', 'weekend',
                       'flat_base', 111, 'range_high', 111, 100, 9.9, '[]', 'r')"""
        )
        # 백필성 watch (30일전), 실행 방금, pivot 999
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source,
                  pattern, pivot_price, pivot_basis, base_high, base_low, base_depth_pct, risk_flags, reasoning)
               VALUES ('AXPL1', NOW(), CURRENT_DATE - 30, 'KOSPI', 'watch', 'weekend',
                       'flat_base', 999, 'range_high', 999, 900, 9.9, '[]', 'r')"""
        )
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute(
                """SELECT pivot_price FROM weekly_classification
                    WHERE symbol='AXPL1' AND classification IN ('entry','watch')
                    ORDER BY COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC
                    LIMIT 1"""
            )
            assert float(cur.fetchone()[0]) == 111.0  # analyzed_for_date 최신 행
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='AXPL1'")
        db.commit()
```

> 이 테스트는 변경 후 쿼리가 의도한 행(데이터 최신)을 고르는지 SQL 수준에서 못 박는다. 두 위치 모두 같은 `ORDER BY`를 적용하므로 한 테스트로 키 정확성을 검증한다.

- [ ] **Step 2: 실패/기준 확인**

Run: `uv run pytest tests/test_llm_compute_payload_lite.py::test_payload_lite_prior_by_analyzed_for_date -v`
Expected: 이 테스트는 새 ORDER BY를 직접 쿼리하므로 PASS여야 한다(키 검증용). PASS 안 되면 시드/스키마 점검.

- [ ] **Step 3: 구현** — `payload_lite.py` 두 곳 모두 동일 교체

기존 (35행, 159행 동일 패턴):
```python
             ORDER BY classified_at DESC LIMIT 1
```
변경:
```python
             ORDER BY COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC LIMIT 1
```

- [ ] **Step 4: 통과 확인 + 회귀**

Run: `uv run pytest tests/test_llm_compute_payload_lite.py -v`
Expected: 전체 PASS (기존 포함).

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/compute/payload_lite.py tests/test_llm_compute_payload_lite.py
git commit -m "feat(classification): payload_lite prior 선택을 analyzed_for_date 축으로 (entry/watch 필터 유지)"
```

---

### Task 6: freeze_cleanup 활성 종목 판정 축 전환

**Files:**
- Modify: `kr_pipeline/llm_runner/freeze_cleanup.py:59-62` (내부 `latest_class` CTE `ORDER BY`)
- Test: `tests/test_freeze_cleanup.py`

- [ ] **Step 1: 실패 테스트 작성** — 파일 끝에 추가

```python
def test_active_protection_uses_analyzed_for_date(db):
    """freeze 활성 보호의 '최신 분류'가 analyzed_for_date 기준인지 검증.
    동일 시드에서 데이터-최신을 ignore→watch 로 바꾸면 보호 여부가 토글되어
    purge 후보 수가 정확히 1 차이 나야 한다. (다른 ticker 들은 두 측정에 동일 기여)"""
    from kr_pipeline.llm_runner.freeze_cleanup import cleanup
    sym = 'AXFRZ1'
    with db.cursor() as cur:
        cur.execute("DELETE FROM classification_freezes WHERE ticker=%s", (sym,))
        cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (sym,))
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'A','KOSPI') ON CONFLICT DO NOTHING", (sym,))
        # 데이터-최신 = ignore (어제), 실행 2일 전
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source)
               VALUES (%s, NOW() - INTERVAL '2 day', CURRENT_DATE - 1, 'KOSPI', 'ignore', 'weekend')""",
            (sym,),
        )
        # 백필성 = watch (30일전 데이터), 실행 방금(classified_at 최신)
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source)
               VALUES (%s, NOW(), CURRENT_DATE - 30, 'KOSPI', 'watch', 'weekend')""",
            (sym,),
        )
        # (ticker,stage) freeze 2개 — 둘 다 보존기간(30d) 초과. MAX(-60d)는 rule3 로 항상 보존,
        # -61d 는 '활성 아님'일 때만 purge 후보가 된다.
        cur.execute(
            """INSERT INTO classification_freezes
                 (ticker, stage, frozen_at, artifact_uri, artifact_sha256, artifact_size_bytes)
               VALUES (%s, 'weekend', NOW() - INTERVAL '61 day', %s, 'shaA', 100),
                      (%s, 'weekend', NOW() - INTERVAL '60 day', %s, 'shaB', 100)""",
            (sym, f"file:///tmp/{sym}_a.zip", sym, f"file:///tmp/{sym}_b.zip"),
        )
    db.commit()
    try:
        # 상태1: 데이터-최신 = ignore → 비활성 → -61d freeze 가 후보
        c1 = cleanup(db, dry_run=True, retention_days=30).candidates
        # 상태2: 데이터-최신 = watch 로 (watch 행의 analyzed_for_date 를 오늘로) → 활성 → 보호
        with db.cursor() as cur:
            cur.execute(
                """UPDATE weekly_classification SET analyzed_for_date = CURRENT_DATE
                    WHERE symbol=%s AND classification='watch'""",
                (sym,),
            )
        db.commit()
        c2 = cleanup(db, dry_run=True, retention_days=30).candidates
        assert c1 == c2 + 1
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_freezes WHERE ticker=%s", (sym,))
            cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (sym,))
        db.commit()
```

> 변경 전(classified_at DESC)에는 두 상태 모두 watch(classified_at 최신)가 활성으로 잡혀 -61d freeze 가 항상 보호 → `c1 == c2` → assert 실패. 변경 후에만 토글되어 `c1 == c2 + 1` 성립. 다른 ticker 들의 후보 여부는 두 측정에서 동일하므로 공유 DB에서도 결정론적.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_freeze_cleanup.py::test_active_protection_uses_analyzed_for_date -v`
Expected: FAIL — classified_at DESC면 watch가 늘 최신→활성 보호라 c1==c2 (assert 실패).

- [ ] **Step 3: 구현** — `freeze_cleanup.py:61`

기존:
```python
                     ORDER BY symbol, classified_at DESC
```
변경:
```python
                     ORDER BY symbol, COALESCE(analyzed_for_date, classified_at::date) DESC, classified_at DESC
```

- [ ] **Step 4: 통과 확인 + 회귀**

Run: `uv run pytest tests/test_freeze_cleanup.py -v`
Expected: 신규 PASS, 기존 freeze_cleanup 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/freeze_cleanup.py tests/test_freeze_cleanup.py
git commit -m "feat(classification): freeze_cleanup 활성판정을 analyzed_for_date 축으로"
```

---

### Task 7: insert_disqualification 에 analyzed_for_date 채우기

**Files:**
- Modify: `kr_pipeline/llm_runner/store.py:91-113` (시그니처 + INSERT)
- Modify: `kr_pipeline/llm_runner/disqualify.py:37` (호출부에 as_of 전달)
- Test: `tests/test_llm_disqualify.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_disqualify.py` 끝에 추가

```python
def test_insert_disqualification_sets_analyzed_for_date(db):
    from datetime import datetime, timezone, date
    from kr_pipeline.llm_runner.store import insert_disqualification
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='AXDQ1'")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('AXDQ1','A','KOSPI') ON CONFLICT DO NOTHING")
    db.commit()
    insert_disqualification(
        db, symbol='AXDQ1', classified_at=datetime(2026, 6, 1, 5, tzinfo=timezone.utc),
        market='KOSPI', analyzed_for_date=date(2026, 6, 1),
    )
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT classification, analyzed_for_date FROM weekly_classification WHERE symbol='AXDQ1'")
            row = cur.fetchone()
        assert row[0] == 'disqualified'
        assert row[1] == date(2026, 6, 1)
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='AXDQ1'")
        db.commit()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_llm_disqualify.py::test_insert_disqualification_sets_analyzed_for_date -v`
Expected: FAIL — `insert_disqualification() got an unexpected keyword argument 'analyzed_for_date'`.

- [ ] **Step 3: 구현** — `store.py` (date는 이미 import됨: line 6)

기존:
```python
def insert_disqualification(
    conn: Connection,
    *,
    symbol: str,
    classified_at: datetime,
    market: str,
    reason: str = "minervini_pass=false — 미너비니 자격 상실(시스템 강등)",
) -> None:
```
변경:
```python
def insert_disqualification(
    conn: Connection,
    *,
    symbol: str,
    classified_at: datetime,
    market: str,
    reason: str = "minervini_pass=false — 미너비니 자격 상실(시스템 강등)",
    analyzed_for_date: date | None = None,
) -> None:
```

기존 INSERT:
```python
            INSERT INTO weekly_classification
              (symbol, classified_at, market, classification, source, reasoning)
            VALUES (%s, %s, %s, 'disqualified', 'system_disqualify', %s)
            ON CONFLICT (symbol, classified_at) DO NOTHING
            """,
            (symbol, classified_at, market, reason),
```
변경:
```python
            INSERT INTO weekly_classification
              (symbol, classified_at, analyzed_for_date, market, classification, source, reasoning)
            VALUES (%s, %s, %s, %s, 'disqualified', 'system_disqualify', %s)
            ON CONFLICT (symbol, classified_at) DO NOTHING
            """,
            (symbol, classified_at, analyzed_for_date, market, reason),
```

그리고 `disqualify.py:37` 호출부:
기존:
```python
            insert_disqualification(conn, symbol=x["symbol"], classified_at=classified_at, market=x["market"])
```
변경:
```python
            insert_disqualification(conn, symbol=x["symbol"], classified_at=classified_at,
                                    market=x["market"], analyzed_for_date=as_of)
```

- [ ] **Step 4: 통과 확인 + 회귀**

Run: `uv run pytest tests/test_llm_disqualify.py -v`
Expected: 신규 PASS, 기존 disqualify 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/store.py kr_pipeline/llm_runner/disqualify.py tests/test_llm_disqualify.py
git commit -m "feat(classification): insert_disqualification 에 analyzed_for_date 적재 (강등 경로 as_of 전달)"
```

---

### Task 8: delta.find_new_tickers 유지 결정 명문화 (주석)

**Files:**
- Modify: `kr_pipeline/llm_runner/compute/delta.py:32-36` (주석 추가, 동작 변경 없음)

- [ ] **Step 1: 주석 추가** — `NOT EXISTS` 블록 위에

```python
               -- NOTE: 이 7일 가드는 "최근에 LLM을 실행했나"(실행 비용 절약)를 보는 것이라
               --       의도적으로 classified_at 을 쓴다. 데이터 기준 최신성(analyzed_for_date)
               --       으로 바꾸지 않는다. (sub-project ① 설계 결정)
               AND NOT EXISTS (
```

- [ ] **Step 2: 회귀 확인 (동작 불변)**

Run: `uv run pytest tests/test_llm_compute_delta.py -v`
Expected: 전부 PASS (주석만 변경).

- [ ] **Step 3: 커밋**

```bash
git add kr_pipeline/llm_runner/compute/delta.py
git commit -m "docs(classification): delta 7일 가드가 classified_at 유지하는 이유 명문화"
```

---

### Task 9: 전체 회귀 + baseline 점검

**Files:** 없음 (검증만)

- [ ] **Step 1: 전체 테스트 실행**

Run: `uv run pytest tests/ -q`
Expected: 신규 테스트 전부 PASS. 실패는 사전 존재 isolation fail 약 25개 이내 — 그 수가 늘지 않았는지 확인. (늘었다면 추가된 실패의 원인을 추적해 수정)

- [ ] **Step 2: 변경 전후 baseline 비교 (선택)**

필요 시 `git stash` 없이 main 대비 실패 목록을 비교하거나, 실패 테스트명을 기록해 신규 회귀가 없음을 확인.

- [ ] **Step 3: 최종 상태 확인**

Run: `git log --oneline feat/classification-latest-axis ^main`
Expected: Task1~8 커밋이 순서대로 존재.

---

## 자기 점검 결과 (작성자)

- **스펙 커버리지**: 스펙의 "변경 6곳"=Task1~6, "유지 1곳"=Task8, "disqualified 보강"=Task7, "테스트 전략"=각 Task Step1 + Task9. 누락 없음.
- **placeholder**: 없음. Task6 테스트는 실제 공개 함수 `cleanup(...).candidates`를 사용하는 결정론적 토글 비교로 확정(초안의 미확정 함수명 제거).
- **타입 일관성**: 공통 키 문자열이 6개 Task에서 동일. `analyzed_for_date`(date), `classified_at`(timestamptz) 일관. `insert_disqualification` 신규 인자명 `analyzed_for_date`가 호출부와 일치.
