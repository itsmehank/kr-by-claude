# P0 adj_open·adj_volume 1급화 + 가드 수정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수정 시가/거래량(adj_open·adj_volume)을 daily_prices·weekly_prices의 1급 컬럼으로 적재하고, indicators가 그것을 읽게 하며, 정합성 가드의 거래량 비교를 보정 vs 보정으로 바로잡는다.

**Architecture:** 이미 존재하는 adj_high/adj_low 적재·갱신 패턴을 그대로 미러해 adj_open·adj_volume을 pykrx adjusted 값에서 "줍는다". indicators는 `split_adjusted_volume` 재계산을 폐기하고 stored adj_volume을 읽으며(함수 삭제), 가드는 `daily_prices.adj_volume` vs `daily_indicators.volume`을 비교한다.

**Tech Stack:** Python(pytest), psycopg, pandas, pykrx. DB: PostgreSQL(kr_pipeline·kr_test).

**Spec:** `docs/superpowers/specs/2026-06-04-adj-volume-open-firstclass-design.md`

---

## File Structure / 변경 지도

- `kr_pipeline/db/schema.sql` — daily_prices·weekly_prices에 adj_open/adj_volume 추가 (+ 양쪽 DB ALTER).
- `kr_pipeline/ohlcv/transform.py` — merge에 adj_open/adj_volume 줍기, to_price_rows 튜플 확장.
- `kr_pipeline/ohlcv/store.py` — upsert_daily_prices 컬럼, update_adj_prices(+2컬럼).
- `kr_pipeline/ohlcv/modes.py` — _run_full_refresh row 빌드 +2.
- `kr_pipeline/weekly/load.py` — daily SELECT +2.
- `kr_pipeline/weekly/transform.py` — WEEKLY_COLUMNS·집계·to_weekly_rows +2.
- `kr_pipeline/weekly/store.py` — upsert_weekly_prices +2.
- `kr_pipeline/indicators/load.py` — adj_volume 로드, raw close/volume 제거.
- `kr_pipeline/indicators/modes.py` — stored adj_volume 읽기, split_adjusted_volume 호출/ import 제거.
- `kr_pipeline/indicators/compute/volume.py` — split_adjusted_volume 함수 삭제.
- `api/services/integrity_guard.py` — 거래량 비교 adj_volume 기반.
- 테스트: test_ohlcv_transform / test_ohlcv_store(또는 modes) / test_weekly_transform / test_indicators_volume / test_indicators(load·modes·integration) / test 가드.

**컬럼 순서 규약**: 모든 곳에서 `adj_open`, `adj_volume`을 **adj_low 다음**에 배치(튜플·INSERT·SELECT 일관).

pytest는 repo 루트 `uv run pytest`. baseline isolation fail(~31)은 base↔HEAD 비교로 회귀 판정(절대 수 아님).

---

### Task 1: 스키마 — adj_open/adj_volume 컬럼 추가 (양쪽 DB)

**Files:**
- Modify: `kr_pipeline/db/schema.sql`
- Test: `tests/test_schema_ohlcv.py` (없으면 신규 — 아래 Step 1 참조)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_schema_ohlcv.py` (없으면 생성, 있으면 함수 추가):

```python
def test_daily_weekly_prices_have_adj_open_volume(db):
    with db.cursor() as cur:
        for tbl in ("daily_prices", "weekly_prices"):
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name=%s AND column_name = ANY(%s)",
                (tbl, ["adj_open", "adj_volume"]),
            )
            cols = {r[0] for r in cur.fetchall()}
            assert cols == {"adj_open", "adj_volume"}, f"{tbl} missing: {{'adj_open','adj_volume'}} - {cols}"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_schema_ohlcv.py::test_daily_weekly_prices_have_adj_open_volume -v`
Expected: FAIL (컬럼 없음).

- [ ] **Step 3: schema.sql 수정**

`kr_pipeline/db/schema.sql` daily_prices CREATE 블록에서 `adj_low NUMERIC(12,4),`(22줄) 다음에 추가:

```sql
    adj_open      NUMERIC(12,4),
    adj_volume    NUMERIC(20,2),
```

weekly_prices CREATE 블록 `adj_low NUMERIC(12,4),`(69줄) 다음에 동일 2줄 추가.

- [ ] **Step 4: 양쪽 DB ALTER 적용**

Run (kr_pipeline·kr_test 각각):
```bash
for DB in kr_pipeline kr_test; do
  psql -d $DB -c "ALTER TABLE daily_prices  ADD COLUMN IF NOT EXISTS adj_open NUMERIC(12,4);
                  ALTER TABLE daily_prices  ADD COLUMN IF NOT EXISTS adj_volume NUMERIC(20,2);
                  ALTER TABLE weekly_prices ADD COLUMN IF NOT EXISTS adj_open NUMERIC(12,4);
                  ALTER TABLE weekly_prices ADD COLUMN IF NOT EXISTS adj_volume NUMERIC(20,2);"
done
```
Expected: ALTER TABLE × 4 per DB (또는 NOTICE already exists).

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_schema_ohlcv.py::test_daily_weekly_prices_have_adj_open_volume -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/db/schema.sql tests/test_schema_ohlcv.py
git commit -m "feat(adj): daily/weekly_prices 에 adj_open/adj_volume 컬럼 추가 (양쪽 DB)"
```

---

### Task 2: ohlcv 증분 적재 — merge + to_price_rows + upsert

**Files:**
- Modify: `kr_pipeline/ohlcv/transform.py`, `kr_pipeline/ohlcv/store.py`
- Test: `tests/test_ohlcv_transform.py`, `tests/test_ohlcv_store.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_ohlcv_transform.py`에 추가:

```python
def test_merge_picks_adj_open_and_adj_volume():
    import pandas as pd
    from kr_pipeline.ohlcv.transform import merge_raw_and_adjusted
    raw = pd.DataFrame({"date": ["2025-01-02"], "open": [100], "high": [110], "low": [90],
                        "close": [105], "volume": [1000], "value": [105000]})
    adj = pd.DataFrame({"date": ["2025-01-02"], "open": [20], "high": [22], "low": [18],
                        "close": [21], "volume": [5000]})
    m = merge_raw_and_adjusted(raw, adj)
    assert float(m.loc[0, "adj_open"]) == 20.0
    assert float(m.loc[0, "adj_volume"]) == 5000.0


def test_merge_adj_open_volume_fallback_to_raw_when_missing():
    import pandas as pd
    from kr_pipeline.ohlcv.transform import merge_raw_and_adjusted
    raw = pd.DataFrame({"date": ["2025-01-02"], "open": [100], "high": [110], "low": [90],
                        "close": [105], "volume": [1000], "value": [105000]})
    adj = pd.DataFrame({"date": ["2025-01-02"], "close": [105]})  # high/low/open/volume 없음
    m = merge_raw_and_adjusted(raw, adj)
    assert float(m.loc[0, "adj_open"]) == 100.0
    assert float(m.loc[0, "adj_volume"]) == 1000.0
```

`tests/test_ohlcv_store.py`에 추가:

```python
def test_upsert_daily_prices_stores_adj_open_volume(db):
    from kr_pipeline.ohlcv.store import upsert_daily_prices
    from datetime import date
    with db.cursor() as cur:
        cur.execute("DELETE FROM daily_prices WHERE ticker='ADJ1'")
    db.commit()
    # 튜플 순서: ticker,date,open,high,low,close,adj_close,adj_high,adj_low,adj_open,adj_volume,volume,value
    rows = [("ADJ1", date(2025,1,2), 100,110,90,105, 21.0, 22.0, 18.0, 20.0, 5000.0, 1000, 105000)]
    upsert_daily_prices(db, rows)
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT adj_open, adj_volume FROM daily_prices WHERE ticker='ADJ1' AND date=%s", (date(2025,1,2),))
            r = cur.fetchone()
        assert float(r[0]) == 20.0 and float(r[1]) == 5000.0
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker='ADJ1'")
        db.commit()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_ohlcv_transform.py -k adj_open tests/test_ohlcv_store.py::test_upsert_daily_prices_stores_adj_open_volume -v`
Expected: FAIL (adj_open/adj_volume 미생성, upsert 튜플 길이 불일치).

- [ ] **Step 3: transform.merge_raw_and_adjusted 수정**

`kr_pipeline/ohlcv/transform.py`의 rename 구성부에 open/volume 추가. 현재:
```python
    rename = {"close": "adj_close"}
    if "high" in adjusted.columns:
        rename["high"] = "adj_high"
    if "low" in adjusted.columns:
        rename["low"] = "adj_low"
```
다음으로 확장:
```python
    rename = {"close": "adj_close"}
    if "open" in adjusted.columns:
        rename["open"] = "adj_open"
    if "high" in adjusted.columns:
        rename["high"] = "adj_high"
    if "low" in adjusted.columns:
        rename["low"] = "adj_low"
    if "volume" in adjusted.columns:
        rename["volume"] = "adj_volume"
```
그리고 fallback 블록(adj_high/adj_low fillna 다음)에 추가:
```python
    if "adj_open" not in merged.columns:
        merged["adj_open"] = merged["open"]
    merged["adj_open"] = merged["adj_open"].fillna(merged["open"]).astype(float)
    if "adj_volume" not in merged.columns:
        merged["adj_volume"] = merged["volume"]
    merged["adj_volume"] = merged["adj_volume"].fillna(merged["volume"]).astype(float)
```
또한 `raw.empty` early-return의 assign에 `adj_open=pd.Series(dtype=float), adj_volume=pd.Series(dtype=float)` 추가.

- [ ] **Step 4: to_price_rows 튜플 확장**

`to_price_rows`의 튜플에서 `float(r["adj_low"]),` 다음에 추가:
```python
            float(r["adj_open"]),
            float(r["adj_volume"]),
```
(순서: ... adj_close, adj_high, adj_low, **adj_open, adj_volume**, volume, value)

- [ ] **Step 5: upsert_daily_prices 컬럼 확장**

`kr_pipeline/ohlcv/store.py` `upsert_daily_prices`의 INSERT를 다음으로:
```python
            INSERT INTO daily_prices
              (ticker, date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ticker, date) DO UPDATE
               SET open = EXCLUDED.open,
                   high = EXCLUDED.high,
                   low = EXCLUDED.low,
                   close = EXCLUDED.close,
                   adj_close = EXCLUDED.adj_close,
                   adj_high = EXCLUDED.adj_high,
                   adj_low = EXCLUDED.adj_low,
                   adj_open = EXCLUDED.adj_open,
                   adj_volume = EXCLUDED.adj_volume,
                   volume = EXCLUDED.volume,
                   value = EXCLUDED.value,
                   updated_at = NOW()
```

- [ ] **Step 6: 통과 확인 + 기존 transform/store 테스트 회귀**

Run: `uv run pytest tests/test_ohlcv_transform.py tests/test_ohlcv_store.py -v`
Expected: 신규 PASS, 기존도 PASS(튜플 기대값 쓰는 기존 테스트가 있으면 새 컬럼 반영해 수정).

- [ ] **Step 7: Commit**

```bash
git add kr_pipeline/ohlcv/transform.py kr_pipeline/ohlcv/store.py tests/test_ohlcv_transform.py tests/test_ohlcv_store.py
git commit -m "feat(adj): ohlcv 증분 적재가 adj_open/adj_volume 줍기"
```

---

### Task 3: ohlcv full-refresh — update_adj_prices + modes row 빌드

**Files:**
- Modify: `kr_pipeline/ohlcv/store.py`, `kr_pipeline/ohlcv/modes.py`
- Test: `tests/test_ohlcv_store.py`, `tests/test_ohlcv_modes.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_ohlcv_store.py`에 추가:

```python
def test_update_adj_prices_updates_adj_open_volume(db):
    from kr_pipeline.ohlcv.store import upsert_daily_prices, update_adj_prices
    from datetime import date
    d = date(2025, 1, 3)
    with db.cursor() as cur:
        cur.execute("DELETE FROM daily_prices WHERE ticker='ADJ2'")
    db.commit()
    upsert_daily_prices(db, [("ADJ2", d, 100,110,90,105, 105.0,110.0,90.0,100.0,1000.0,1000,105000)])
    db.commit()
    # (ticker,date,adj_close,adj_high,adj_low,adj_open,adj_volume)
    update_adj_prices(db, [("ADJ2", d, 21.0, 22.0, 18.0, 20.0, 5000.0)])
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute("SELECT adj_close,adj_high,adj_low,adj_open,adj_volume FROM daily_prices WHERE ticker='ADJ2' AND date=%s",(d,))
            r = cur.fetchone()
        assert [float(x) for x in r] == [21.0, 22.0, 18.0, 20.0, 5000.0]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker='ADJ2'")
        db.commit()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_ohlcv_store.py::test_update_adj_prices_updates_adj_open_volume -v`
Expected: FAIL (튜플 길이/컬럼 불일치).

- [ ] **Step 3: update_adj_prices 확장**

`kr_pipeline/ohlcv/store.py` `update_adj_prices`를 다음으로 (temp table + INSERT + UPDATE 모두 +2):

```python
def update_adj_prices(conn: Connection, rows: list[tuple]) -> int:
    """full-refresh: (ticker, date, adj_close, adj_high, adj_low, adj_open, adj_volume) 튜플로 수정 OHLCV 갱신."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TEMP TABLE _adj_updates (
                ticker     VARCHAR(10)   NOT NULL,
                date       DATE          NOT NULL,
                adj_close  NUMERIC(12,4) NOT NULL,
                adj_high   NUMERIC(12,4),
                adj_low    NUMERIC(12,4),
                adj_open   NUMERIC(12,4),
                adj_volume NUMERIC(20,2),
                PRIMARY KEY (ticker, date)
            ) ON COMMIT DROP
        """)
        cur.executemany(
            "INSERT INTO _adj_updates (ticker, date, adj_close, adj_high, adj_low, adj_open, adj_volume) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
        cur.execute("""
            UPDATE daily_prices d
               SET adj_close = u.adj_close,
                   adj_high = u.adj_high,
                   adj_low = u.adj_low,
                   adj_open = u.adj_open,
                   adj_volume = u.adj_volume,
                   updated_at = NOW()
              FROM _adj_updates u
             WHERE d.ticker = u.ticker AND d.date = u.date
        """)
        affected = cur.rowcount
    return affected
```

- [ ] **Step 4: modes._run_full_refresh row 빌드 +2**

`kr_pipeline/ohlcv/modes.py` `_run_full_refresh._process_ticker`의 row 컴프리헨션을 다음으로:
```python
        rows = [
            (ticker, r["date"], float(r["close"]), float(r["high"]), float(r["low"]),
             float(r["open"]), float(r["volume"]))
            for _, r in adj.iterrows()
        ]
```
(fetch_adj_only가 adjusted df를 주므로 r["open"]=adj_open, r["volume"]=adj_volume.)

- [ ] **Step 5: 통과 + 회귀**

Run: `uv run pytest tests/test_ohlcv_store.py tests/test_ohlcv_modes.py -v`
Expected: 신규 PASS. 기존 full-refresh mock 테스트가 row 튜플 길이를 보면 새 길이(7)로 갱신.

- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/ohlcv/store.py kr_pipeline/ohlcv/modes.py tests/test_ohlcv_store.py tests/test_ohlcv_modes.py
git commit -m "feat(adj): full-refresh 가 adj_open/adj_volume 갱신 (분할 재동기화)"
```

---

### Task 4: weekly — load + 집계 + store

**Files:**
- Modify: `kr_pipeline/weekly/load.py`, `kr_pipeline/weekly/transform.py`, `kr_pipeline/weekly/store.py`
- Test: `tests/test_weekly_transform.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_weekly_transform.py`에 추가:

```python
def test_weekly_aggregates_adj_open_first_and_adj_volume_sum():
    import pandas as pd
    from kr_pipeline.weekly.transform import aggregate_to_weekly
    daily = pd.DataFrame({
        "date": ["2025-01-06", "2025-01-07", "2025-01-08"],  # 같은 주(월~수)
        "open": [100,101,102], "high": [110,111,112], "low": [90,91,92], "close": [105,106,107],
        "adj_close": [105.0,106.0,107.0], "adj_high": [110.0,111.0,112.0], "adj_low": [90.0,91.0,92.0],
        "adj_open": [100.0,101.0,102.0], "adj_volume": [1000.0,2000.0,3000.0],
        "volume": [1000,2000,3000], "value": [1,2,3],
    })
    w = aggregate_to_weekly(daily)
    assert float(w.loc[0, "adj_open"]) == 100.0      # 주 첫날
    assert float(w.loc[0, "adj_volume"]) == 6000.0   # 합
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_weekly_transform.py::test_weekly_aggregates_adj_open_first_and_adj_volume_sum -v`
Expected: FAIL (KeyError adj_open / 컬럼 없음).

- [ ] **Step 3: weekly/load.py SELECT 확장**

`kr_pipeline/weekly/load.py`의 daily SELECT를:
```python
            SELECT date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value
              FROM daily_prices
```

- [ ] **Step 4: transform — WEEKLY_COLUMNS·집계·to_weekly_rows**

`kr_pipeline/weekly/transform.py`:
- `WEEKLY_COLUMNS`에 `"adj_low",` 다음 `"adj_open", "adj_volume",` 추가:
```python
WEEKLY_COLUMNS = [
    "week_end_date", "open", "high", "low", "close",
    "adj_close", "adj_high", "adj_low", "adj_open", "adj_volume", "volume", "value", "trading_days",
]
```
- `agg` dict에서 `"adj_low": grouped["adj_low"].min(),` 다음 추가:
```python
        "adj_open":      grouped["adj_open"].first(),
        "adj_volume":    grouped["adj_volume"].sum(min_count=1),
```
- 상단 numeric coerce 루프(`for col in ("volume","value")`)에 `"adj_volume"` 추가 → `for col in ("volume", "value", "adj_volume"):`
- `to_weekly_rows` 튜플에서 `float(r["adj_low"]),` 다음:
```python
            float(r["adj_open"]),
            float(r["adj_volume"]),
```

- [ ] **Step 5: weekly/store.py upsert 확장**

`kr_pipeline/weekly/store.py` `upsert_weekly_prices` INSERT 컬럼/VALUES/SET에 `adj_open, adj_volume` 추가 (adj_low 다음, 튜플 순서 일치):
```python
            INSERT INTO weekly_prices
              (ticker, week_end_date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value, trading_days, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ticker, week_end_date) DO UPDATE
               SET ... (기존) ...,
                   adj_open = EXCLUDED.adj_open,
                   adj_volume = EXCLUDED.adj_volume,
                   ...
```
(기존 SET 절에 adj_open/adj_volume 두 줄 추가.)

- [ ] **Step 6: 통과 + 회귀**

Run: `uv run pytest tests/test_weekly_transform.py -v`
Expected: 신규 PASS. 기존 집계 테스트가 컬럼 목록/튜플을 보면 갱신.

- [ ] **Step 7: Commit**

```bash
git add kr_pipeline/weekly/load.py kr_pipeline/weekly/transform.py kr_pipeline/weekly/store.py tests/test_weekly_transform.py
git commit -m "feat(adj): weekly 집계가 adj_open(첫날)/adj_volume(합) 적재"
```

---

### Task 5: indicators — stored adj_volume 읽기 + split_adjusted_volume 제거

**Files:**
- Modify: `kr_pipeline/indicators/load.py`, `kr_pipeline/indicators/modes.py`, `kr_pipeline/indicators/compute/volume.py`
- Test: `tests/test_indicators_volume.py`, indicators fixtures

- [ ] **Step 1: split_adjusted_volume 테스트 제거 + 회귀 테스트 작성**

`tests/test_indicators_volume.py`:
- import에서 `split_adjusted_volume` 제거.
- `test_split_adjusted_volume_basic`, `test_split_adjusted_volume_no_split` 두 함수 삭제.

`tests/test_indicators_volume.py`에 "modes가 stored adj_volume를 쓰는지"는 통합 테스트(test_indicators_integration)에서 검증하므로, 여기선 함수 제거만.

- [ ] **Step 2: 실패 확인 (import 에러)**

Run: `uv run pytest tests/test_indicators_volume.py -v`
Expected: 이 시점엔 아직 modes/compute가 함수를 export하므로, 테스트는 import 제거로 통과. 대신 modes가 함수를 import하는 한 compute 삭제 시 깨짐 → Step 3에서 동시 처리.

- [ ] **Step 3: load.py — adj_volume 로드, raw close/volume 제거**

`kr_pipeline/indicators/load.py` `load_daily_prices` SELECT/astype:
```python
            SELECT date, adj_close, adj_high, adj_low, adj_volume
              FROM daily_prices
```
astype 블록: `close`/`volume` 줄 제거, 추가 `df["adj_volume"] = df["adj_volume"].astype(float)`.
`load_weekly_prices`도 동일(`SELECT week_end_date AS date, adj_close, adj_high, adj_low, adj_volume`, astype 갱신).

- [ ] **Step 4: modes.py — stored adj_volume 사용 + import 제거**

`kr_pipeline/indicators/modes.py`:
- import(25-26줄)에서 `split_adjusted_volume,` 제거 → `from kr_pipeline.indicators.compute.volume import (avg_volume, volume_ratio, ...)`.
- daily(현 150-153줄) `close = df["close"]; volume_raw = df["volume"]; adj_volume = split_adjusted_volume(volume_raw, close, adj_close)` →
```python
    adj_volume = df["adj_volume"]
```
- weekly(현 489-491줄) 동일 교체.
(나머지 avg_volume/pocket_pivot 등은 adj_volume 입력 그대로.)

- [ ] **Step 5: compute/volume.py — split_adjusted_volume 함수 삭제**

`kr_pipeline/indicators/compute/volume.py`에서 `def split_adjusted_volume(...)`(16-23줄) 함수 블록 삭제.

- [ ] **Step 6: indicators 테스트 fixture에 adj_volume 채우기**

indicators가 daily_prices/weekly_prices를 읽는 테스트(`tests/test_indicators_integration.py`, `tests/test_indicators_modes.py`가 있으면)에서 price 행 INSERT에 **adj_volume = volume × close/adj_close** (구 파생식과 동일 값)와 adj_open을 채운다. 예: 기존 INSERT가
`INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,adj_high,adj_low,volume,value)` 라면
`adj_open, adj_volume` 컬럼/값을 추가(adj_volume은 volume*close/adj_close로 계산해 상수로 기입). 이렇게 하면 회귀 결과(avg_volume 등)가 기존과 동일.

- [ ] **Step 7: 통과 + 회귀**

Run: `uv run pytest tests/test_indicators_volume.py tests/test_indicators_integration.py -v`
Expected: 신규/회귀 PASS. (test_indicators_integration이 baseline isolation fail이면, 단독 실행 결과가 base와 동일한지 비교 — 새로 깨뜨리지 않음.)

- [ ] **Step 8: Commit**

```bash
git add kr_pipeline/indicators/load.py kr_pipeline/indicators/modes.py kr_pipeline/indicators/compute/volume.py tests/test_indicators_volume.py tests/test_indicators_integration.py
git commit -m "feat(adj): indicators 가 stored adj_volume 읽기 + split_adjusted_volume 제거"
```

---

### Task 6: 정합성 가드 — 보정 vs 보정 비교

**Files:**
- Modify: `api/services/integrity_guard.py`
- Test: `tests/test_api_integrity_guard.py` (없으면 신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_api_integrity_guard.py`(없으면 생성):

```python
def test_guard_compares_adj_volume_not_raw(db):
    """daily_prices.adj_volume == daily_indicators.volume 이면 통과(원시 volume 과 무관)."""
    from datetime import date
    from api.services.integrity_guard import check_data_integrity, DataIntegrityError
    import pytest
    d = date(2023, 2, 1)  # 실데이터 이전(격리)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('IG1','I','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM daily_prices WHERE ticker='IG1'")
        cur.execute("DELETE FROM daily_indicators WHERE ticker='IG1'")
        # raw volume 1000, adj_volume 5000 (×5), indicators.volume 5000 → 보정끼리 일치
        cur.execute("""INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,adj_high,adj_low,adj_open,adj_volume,volume,value)
                       VALUES ('IG1',%s,100,110,90,105,21,22,18,20,5000,1000,1)""",(d,))
        cur.execute("""INSERT INTO daily_indicators (ticker,date,adj_close,volume) VALUES ('IG1',%s,21,5000)""",(d,))
    db.commit()
    try:
        res = check_data_integrity(db, "IG1", d)  # raise 안 하면 OK
        assert res.ok
        # adj_volume 어긋나면 검출
        with db.cursor() as cur:
            cur.execute("UPDATE daily_indicators SET volume=9999 WHERE ticker='IG1' AND date=%s",(d,))
        db.commit()
        with pytest.raises(DataIntegrityError):
            check_data_integrity(db, "IG1", d)
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker='IG1'")
            cur.execute("DELETE FROM daily_indicators WHERE ticker='IG1'")
        db.commit()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_integrity_guard.py::test_guard_compares_adj_volume_not_raw -v`
Expected: FAIL (가드가 p.volume(1000) vs i.volume(5000) 비교 → 첫 단계에서 이미 raise).

- [ ] **Step 3: integrity_guard.py 수정**

`api/services/integrity_guard.py`:
- SELECT(68줄): `p.adj_close, p.volume, i.adj_close, i.volume` → `p.adj_close, p.adj_volume, i.adj_close, i.volume`.
- 언팩: `actual_date, p_close, p_volume, i_close, i_volume = row` (변수명 유지, 의미는 p_volume=adj_volume).
- 거래량 비교(104-106줄)는 그대로(`p_volume_i` vs `i_volume_f`) 두되, 이제 둘 다 보정값. DataIntegrityError의 column 인자를 `"volume"` 유지(메시지상 adj 명시는 선택). `p_volume`이 NULL이면 기존 `if p_volume is not None` 가드로 스킵.
- 주석/docstring을 "adj_volume(보정) vs indicators.volume(보정) 비교"로 갱신.

- [ ] **Step 4: 통과 + 회귀**

Run: `uv run pytest tests/test_api_integrity_guard.py tests/test_api_zip_builder.py -v`
Expected: 신규 PASS, zip_builder(가드 호출) 회귀 없음.

- [ ] **Step 5: Commit**

```bash
git add api/services/integrity_guard.py tests/test_api_integrity_guard.py
git commit -m "fix(adj): 정합성 가드가 adj_volume(보정) vs indicators.volume 비교"
```

---

### Task 7: 전체 회귀 + baseline 점검

- [ ] **Step 1: 변경 영역 테스트**

Run: `uv run pytest tests/test_ohlcv_transform.py tests/test_ohlcv_store.py tests/test_ohlcv_modes.py tests/test_weekly_transform.py tests/test_indicators_volume.py tests/test_api_integrity_guard.py tests/test_schema_ohlcv.py -v`
Expected: 모두 PASS.

- [ ] **Step 2: 전체 스위트 baseline 비교**

Run: `uv run pytest tests/ -q 2>&1 | tail -1`
그리고 base(HEAD~N) 비교: `git stash; git checkout <P0-base-sha>; uv run pytest tests/ -q 2>&1 | tail -1; git checkout -` — **실패 수가 base 대비 늘지 않았는지** 확인.
Expected: 신규 실패 0 (사전 ~31 유지).

- [ ] **Step 3: 백필 안내 (코드 머지 후 운영 1회, KRX 자격증명 필요)**

`ohlcv full-refresh → weekly full-refresh → indicators full-refresh` 순서로 실행해야 adj_open/adj_volume(+adj_high/low) 가 채워짐. **백필 전 indicators 단독 실행 금지** (adj_* NULL → 후보 0 붕괴). 이 백필은 머지 후 별도 운영 단계(이 플랜 범위 밖, 사용자/동료가 실행).

---

## Self-Review (작성자 점검)

**1. Spec coverage**
- 스키마 adj_open/adj_volume(양쪽 DB) → Task 1 ✓
- pykrx에서 줍기(merge/to_price_rows/upsert) → Task 2 ✓
- 신선도 경로(update_adj_prices/full-refresh) → Task 3 ✓
- weekly 일관(첫날 adj_open/합 adj_volume) → Task 4 ✓
- indicators stored adj_volume 읽기 + split_adjusted_volume 제거 → Task 5 ✓
- 가드 보정 vs 보정 + NULL-safe → Task 6 ✓
- 비목표(LLM/표시 불변) → 어느 task도 chart_render/csv_builder/payload 안 건드림 ✓
- 백필 순서·baseline → Task 7 ✓

**2. Placeholder scan:** 코드 스텝에 실제 코드 포함. (Task 4 Step 5의 "...(기존)..."는 기존 SET 절 보존을 의미 — adj_open/adj_volume 두 줄만 추가하라는 지시로 명확.)

**3. Type consistency:** 컬럼 순서 규약(adj_open, adj_volume = adj_low 다음)을 튜플(to_price_rows/to_weekly_rows)·INSERT(upsert)·update_adj_prices·SELECT(weekly/load, indicators/load) 전부에서 동일 적용. update_adj_prices 튜플 (ticker,date,adj_close,adj_high,adj_low,adj_open,adj_volume) ↔ modes row 빌드 순서 일치. 가드 SELECT p.adj_volume ↔ 비교 변수 일치.
