# w52_high/low 수정 고가·저가 기준 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `w52_high`/`w52_low` 를 수정종가가 아니라 **KRX 수정 고가/저가**의 52주 max/min 으로 계산하도록, `daily_prices`·`weekly_prices` 에 `adj_high`/`adj_low` 를 적재하고 지표 계산을 교체한다.

**Architecture:** 적재가 이미 pykrx `adjusted=True` 로 받아 버리던 수정 고가/저가를 보존(접근 B). 차트/CSV 캔들은 raw 유지, 수정값은 w52 지표에만. 백필은 ohlcv→weekly→indicators full-refresh.

**Tech Stack:** Python (pandas, psycopg, pykrx), PostgreSQL, pytest.

**설계:** `docs/superpowers/specs/2026-06-04-w52-adjusted-high-low-design.md`.

---

## 파일 구조 (수정)

| 파일 | 변경 |
|---|---|
| `kr_pipeline/db/schema.sql` | daily_prices·weekly_prices +adj_high/adj_low |
| `kr_pipeline/ohlcv/transform.py` | merge 보존 + to_price_rows 튜플 |
| `kr_pipeline/ohlcv/store.py` | upsert_daily_prices 컬럼 + update_adj_close_only→update_adj_prices |
| `kr_pipeline/ohlcv/modes.py` | full-refresh 행 튜플 + import |
| `kr_pipeline/weekly/load.py` | load_daily_for_ticker SELECT + load_index_daily 합성 |
| `kr_pipeline/weekly/transform.py` | aggregate_to_weekly + WEEKLY_COLUMNS + to_weekly_rows |
| `kr_pipeline/weekly/store.py` | upsert_weekly_prices 컬럼 |
| `kr_pipeline/indicators/load.py` | load_daily_prices·load_weekly_prices SELECT |
| `kr_pipeline/indicators/compute/high_low.py` | w52_high_low 시그니처 |
| `kr_pipeline/indicators/modes.py` | w52_high_low 호출부(일·주) |
| 테스트 | test_ohlcv_transform / test_ohlcv_store / test_weekly_transform / test_indicators_high_low |

---

## Task 0: 검증 게이트 — pykrx 가 고가/저가를 보정하는가 (차단성)

**Files:** 없음(실측). **KRX 자격증명(`KRX_ID`/`KRX_PW`) 필요** — 이 환경에 없으면 사용자에게 실행 요청.

- [ ] **Step 1: 실측**

Run (자격증명 환경에서):
```bash
uv run python -c "
from kr_pipeline.ohlcv.fetch import _fetch_one
from datetime import date
raw = _fetch_one('001130', date(2024,5,1), date(2024,6,28), adjusted=False)
adj = _fetch_one('001130', date(2024,5,1), date(2024,6,28), adjusted=True)
m = raw.merge(adj, on='date', suffixes=('_raw','_adj'))
d = m[m['high_raw'] != m['high_adj']]
print('고가 다른 행:', len(d))
print(d[['date','high_raw','high_adj']].head().to_string(index=False))
"
```
Expected (접근 B 유효): `고가 다른 행: > 0` (raw.high ≠ adj.high).

- [ ] **Step 2: 분기 결정**
  - 고가 다른 행 > 0 → **이 계획대로 진행**(adj df의 high/low 가 KRX 수정값).
  - 고가가 동일(종가만 보정) → **중단·보고**. Task 2 의 merge 를 파생식(`adj_high = raw_high × adj_close/close`)으로 바꾸는 폴백 설계 필요(설계 §검증 게이트). 이 경우 controller 에 에스컬레이션.

(커밋 없음 — 검증만.)

---

## Task 1: 스키마 — adj_high/adj_low 컬럼 추가

**Files:**
- Modify: `kr_pipeline/db/schema.sql` (daily_prices ~line 20, weekly_prices ~line 65)
- 적용: kr_pipeline, kr_test 양쪽 DB

- [ ] **Step 1: schema.sql 수정**

`daily_prices` 의 `adj_close NUMERIC(12,4) NOT NULL,` 다음 줄에 추가:
```sql
    adj_high      NUMERIC(12,4),
    adj_low       NUMERIC(12,4),
```
`weekly_prices` 의 `adj_close NUMERIC(12,4) NOT NULL,` 다음 줄에도 동일하게 추가.

- [ ] **Step 2: 양쪽 DB 마이그레이션**

Run:
```bash
for DB in kr_pipeline kr_test; do
  psql "$DB" -c "ALTER TABLE daily_prices  ADD COLUMN IF NOT EXISTS adj_high NUMERIC(12,4);
                 ALTER TABLE daily_prices  ADD COLUMN IF NOT EXISTS adj_low  NUMERIC(12,4);
                 ALTER TABLE weekly_prices ADD COLUMN IF NOT EXISTS adj_high NUMERIC(12,4);
                 ALTER TABLE weekly_prices ADD COLUMN IF NOT EXISTS adj_low  NUMERIC(12,4);"
done
```
Expected: `ALTER TABLE` × 4 per DB, 에러 없음.

- [ ] **Step 3: 확인**

Run: `psql kr_test -c "\d daily_prices" | grep -E "adj_high|adj_low"`
Expected: `adj_high | numeric(12,4)` 와 `adj_low | numeric(12,4)` 두 줄.

- [ ] **Step 4: Commit**
```bash
git add kr_pipeline/db/schema.sql
git commit -m "feat(w52): daily/weekly_prices 에 adj_high/adj_low 컬럼 추가 (양쪽 DB)"
```
(커밋 메시지에 Co-Authored-By 트레일러 금지.)

---

## Task 2: 적재 transform — 수정 고가/저가 보존

**Files:**
- Modify: `kr_pipeline/ohlcv/transform.py`
- Test: `tests/test_ohlcv_transform.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_ohlcv_transform.py` 의 `_ohlcv_row` 헬퍼는 그대로 두고, 기존 테스트 3개를 아래로 교체(merge가 adj 의 high/low 를 보존, 없으면 raw fallback; to_price_rows 11-튜플):
```python
def test_merge_keeps_adjusted_high_low():
    raw = pd.DataFrame([
        _ohlcv_row(date(2026, 5, 12), 70000, 71000, 69500, 70500, 1000, 70_500_000),
    ])
    adj = pd.DataFrame([
        {"date": date(2026, 5, 12), "open": 35000.0, "high": 35500.0,
         "low": 34750.0, "close": 35250.0, "volume": 2000, "value": 70_500_000},
    ])
    merged = merge_raw_and_adjusted(raw, adj)
    assert merged.iloc[0]["adj_close"] == 35250.0
    assert merged.iloc[0]["adj_high"] == 35500.0
    assert merged.iloc[0]["adj_low"] == 34750.0
    # raw OHLC 는 그대로
    assert merged.iloc[0]["high"] == 71000
    assert merged.iloc[0]["low"] == 69500


def test_merge_falls_back_to_raw_when_adjusted_missing():
    raw = pd.DataFrame([
        _ohlcv_row(date(2026, 5, 12), 70000, 71000, 69500, 70500, 1000, 70_500_000),
    ])
    adj = pd.DataFrame(columns=["date", "close"])
    merged = merge_raw_and_adjusted(raw, adj)
    assert merged.iloc[0]["adj_close"] == 70500
    assert merged.iloc[0]["adj_high"] == 71000   # raw high fallback
    assert merged.iloc[0]["adj_low"] == 69500     # raw low fallback


def test_to_price_rows_includes_adj_high_low():
    merged = pd.DataFrame([{
        "date": date(2026, 5, 12),
        "open": 70000, "high": 71000, "low": 69500, "close": 70500,
        "adj_close": 35250.0, "adj_high": 35500.0, "adj_low": 34750.0,
        "volume": 1000, "value": 70_500_000,
    }])
    rows = to_price_rows("005930", merged)
    assert rows == [(
        "005930", date(2026, 5, 12), 70000, 71000, 69500, 70500,
        35250.0, 35500.0, 34750.0, 1000, 70_500_000
    )]
```

- [ ] **Step 2: 실패 확인**
Run: `uv run pytest tests/test_ohlcv_transform.py -v`
Expected: FAIL (adj_high KeyError / 튜플 길이 불일치)

- [ ] **Step 3: 구현**

`kr_pipeline/ohlcv/transform.py` 를 교체:
```python
import pandas as pd


def merge_raw_and_adjusted(raw: pd.DataFrame, adjusted: pd.DataFrame) -> pd.DataFrame:
    """raw(원가 OHLCV) + adjusted(수정 OHLC) → raw + adj_close/adj_high/adj_low.

    adjusted 에 high/low 가 있으면 보존(KRX 수정 고가/저가), 없으면 raw 값으로 fallback.
    adjusted 가 누락된 날짜도 raw 로 fallback.
    """
    if raw.empty:
        return raw.assign(
            adj_close=pd.Series(dtype=float),
            adj_high=pd.Series(dtype=float),
            adj_low=pd.Series(dtype=float),
        )

    rename = {"close": "adj_close"}
    if "high" in adjusted.columns:
        rename["high"] = "adj_high"
    if "low" in adjusted.columns:
        rename["low"] = "adj_low"
    adj = adjusted.rename(columns=rename)[["date"] + list(rename.values())]
    merged = raw.merge(adj, on="date", how="left")

    merged["adj_close"] = merged["adj_close"].fillna(merged["close"]).astype(float)
    if "adj_high" not in merged.columns:
        merged["adj_high"] = merged["high"]
    merged["adj_high"] = merged["adj_high"].fillna(merged["high"]).astype(float)
    if "adj_low" not in merged.columns:
        merged["adj_low"] = merged["low"]
    merged["adj_low"] = merged["adj_low"].fillna(merged["low"]).astype(float)
    return merged


def to_price_rows(ticker: str, merged: pd.DataFrame) -> list[tuple]:
    """daily_prices executemany 용 tuple 리스트."""
    return [
        (
            ticker,
            r["date"],
            int(r["open"]),
            int(r["high"]),
            int(r["low"]),
            int(r["close"]),
            float(r["adj_close"]),
            float(r["adj_high"]),
            float(r["adj_low"]),
            int(r["volume"]),
            int(r["value"]),
        )
        for _, r in merged.iterrows()
    ]
```

- [ ] **Step 4: 통과 확인**
Run: `uv run pytest tests/test_ohlcv_transform.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**
```bash
git add kr_pipeline/ohlcv/transform.py tests/test_ohlcv_transform.py
git commit -m "feat(w52): merge_raw_and_adjusted 가 adj_high/adj_low 보존"
```

---

## Task 3: 적재 store — upsert + adj 갱신 함수 확장

**Files:**
- Modify: `kr_pipeline/ohlcv/store.py`
- Test: `tests/test_ohlcv_store.py`

- [ ] **Step 1: 실패 테스트 작성/갱신**

`tests/test_ohlcv_store.py` 를 먼저 읽어 기존 `db` 픽스처와 행 튜플 구조를 확인하고, daily_prices INSERT 튜플에 adj_high/adj_low(adj_close 다음 2개)를 추가한다. full-refresh 테스트는 함수명 `update_adj_prices` 와 5-튜플 `(ticker, date, adj_close, adj_high, adj_low)` 로 갱신. 신규 검증 테스트 추가:
```python
def test_update_adj_prices_updates_high_low(db):
    from kr_pipeline.ohlcv.store import upsert_daily_prices, update_adj_prices
    from datetime import date
    # 종목 seed (기존 테스트의 _seed_stock 등 파일 패턴 사용)
    _seed_stock(db, "005930")
    upsert_daily_prices(db, [(
        "005930", date(2026,5,12), 70000, 71000, 69500, 70500,
        35250.0, 35500.0, 34750.0, 1000, 70_500_000
    )])
    update_adj_prices(db, [("005930", date(2026,5,12), 30000.0, 30300.0, 29800.0)])
    with db.cursor() as cur:
        cur.execute("SELECT adj_close, adj_high, adj_low FROM daily_prices "
                    "WHERE ticker='005930' AND date='2026-05-12'")
        assert cur.fetchone() == (30000.0, 30300.0, 29800.0)
```
(파일 상단 import/픽스처/`_seed_stock` 헬퍼명은 실제 파일에 맞춰 사용. 기존 `update_adj_close_only` 참조 테스트는 새 이름·튜플로 일괄 갱신.)

- [ ] **Step 2: 실패 확인**
Run: `uv run pytest tests/test_ohlcv_store.py -v`
Expected: FAIL (update_adj_prices 없음 / 컬럼 수 불일치)

- [ ] **Step 3: 구현**

`store.py` 의 `upsert_daily_prices` INSERT 를 교체:
```python
            INSERT INTO daily_prices
              (ticker, date, open, high, low, close, adj_close, adj_high, adj_low, volume, value, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ticker, date) DO UPDATE
               SET open = EXCLUDED.open,
                   high = EXCLUDED.high,
                   low = EXCLUDED.low,
                   close = EXCLUDED.close,
                   adj_close = EXCLUDED.adj_close,
                   adj_high = EXCLUDED.adj_high,
                   adj_low = EXCLUDED.adj_low,
                   volume = EXCLUDED.volume,
                   value = EXCLUDED.value,
                   updated_at = NOW()
```
`update_adj_close_only` 를 `update_adj_prices` 로 이름·본문 교체:
```python
def update_adj_prices(conn: Connection, rows: list[tuple]) -> int:
    """full-refresh: (ticker, date, adj_close, adj_high, adj_low) 튜플로 수정 OHLC 3종 갱신.

    TEMP TABLE + JOIN-UPDATE. 매칭 없는 행은 무시.
    """
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
                PRIMARY KEY (ticker, date)
            ) ON COMMIT DROP
        """)
        cur.executemany(
            "INSERT INTO _adj_updates (ticker, date, adj_close, adj_high, adj_low) "
            "VALUES (%s, %s, %s, %s, %s)",
            rows,
        )
        cur.execute("""
            UPDATE daily_prices d
               SET adj_close = u.adj_close,
                   adj_high = u.adj_high,
                   adj_low = u.adj_low,
                   updated_at = NOW()
              FROM _adj_updates u
             WHERE d.ticker = u.ticker AND d.date = u.date
        """)
        affected = cur.rowcount
    return affected
```

- [ ] **Step 4: 통과 확인**
Run: `uv run pytest tests/test_ohlcv_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add kr_pipeline/ohlcv/store.py tests/test_ohlcv_store.py
git commit -m "feat(w52): upsert_daily_prices adj_high/low + update_adj_close_only→update_adj_prices"
```

---

## Task 4: ohlcv modes — full-refresh 행 튜플 + import

**Files:**
- Modify: `kr_pipeline/ohlcv/modes.py` (import line 11, full-refresh _process_ticker ~line 200)

- [ ] **Step 1: import 교체 (line 11)**
```python
from kr_pipeline.ohlcv.store import upsert_daily_prices, update_adj_prices, upsert_index_daily
```

- [ ] **Step 2: full-refresh 행 튜플 교체 (~line 197-201)**
```python
        adj = fetch_adj_only(ticker, start, end)
        if adj.empty:
            return 0
        rows = [
            (ticker, r["date"], float(r["close"]), float(r["high"]), float(r["low"]))
            for _, r in adj.iterrows()
        ]
        affected = update_adj_prices(conn, rows)
```
(`fetch_adj_only` 는 adjusted OHLC 전체 반환 — high/low 존재. 증분 경로(line 166-168)는 Task 2/3 의 merge/to_price_rows/upsert 로 자동 반영, 변경 없음.)

- [ ] **Step 3: 무결성 확인**
Run: `uv run python -c "import kr_pipeline.ohlcv.modes; print('ok')"`
Expected: `ok`
Run: `grep -n "update_adj_close_only" kr_pipeline/` → 결과 없음(모두 update_adj_prices 로 교체).

- [ ] **Step 4: Commit**
```bash
git add kr_pipeline/ohlcv/modes.py
git commit -m "feat(w52): full-refresh 가 adj_high/adj_low 갱신"
```

---

## Task 5: 주봉 집계 — adj_high(max)/adj_low(min)

**Files:**
- Modify: `kr_pipeline/weekly/load.py` (load_daily_for_ticker SELECT, load_index_daily 합성)
- Modify: `kr_pipeline/weekly/transform.py` (WEEKLY_COLUMNS, aggregate_to_weekly, to_weekly_rows)
- Modify: `kr_pipeline/weekly/store.py` (upsert_weekly_prices)
- Test: `tests/test_weekly_transform.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_weekly_transform.py` 를 읽어 기존 입력 헬퍼 패턴 확인 후, 입력 daily 에 adj_high/adj_low 를 포함시키고 주간 집계를 검증하는 테스트 추가:
```python
def test_aggregate_adj_high_is_week_max_adj_low_is_week_min():
    daily = pd.DataFrame([
        {"date": date(2026,5,11), "open":100,"high":110,"low":95,"close":105,
         "adj_close":52.0,"adj_high":55.0,"adj_low":47.5,"volume":10,"value":1000},
        {"date": date(2026,5,12), "open":105,"high":120,"low":100,"close":118,
         "adj_close":59.0,"adj_high":60.0,"adj_low":50.0,"volume":20,"value":2000},
    ])
    wk = aggregate_to_weekly(daily)
    assert wk.iloc[0]["adj_high"] == 60.0   # max(55, 60)
    assert wk.iloc[0]["adj_low"] == 47.5    # min(47.5, 50)
    assert wk.iloc[0]["adj_close"] == 59.0  # last


def test_to_weekly_rows_includes_adj_high_low():
    wk = pd.DataFrame([{
        "week_end_date": date(2026,5,15), "open":100,"high":120,"low":95,"close":118,
        "adj_close":59.0,"adj_high":60.0,"adj_low":47.5,"volume":30,"value":3000,"trading_days":2,
    }])
    rows = to_weekly_rows("005930", wk)
    assert rows == [(
        "005930", date(2026,5,15), 100, 120, 95, 118, 59.0, 60.0, 47.5, 30, 3000, 2
    )]
```

- [ ] **Step 2: 실패 확인**
Run: `uv run pytest tests/test_weekly_transform.py -v`
Expected: FAIL (adj_high KeyError / 튜플 길이)

- [ ] **Step 3: 구현 — transform.py**

`WEEKLY_COLUMNS` 교체:
```python
WEEKLY_COLUMNS = [
    "week_end_date", "open", "high", "low", "close",
    "adj_close", "adj_high", "adj_low", "volume", "value", "trading_days",
]
```
`aggregate_to_weekly` 의 agg dict 에 추가(`"adj_close": grouped["adj_close"].last(),` 다음):
```python
        "adj_high":      grouped["adj_high"].max(),
        "adj_low":       grouped["adj_low"].min(),
```
`to_weekly_rows` 튜플 교체(adj_close 다음 2개):
```python
        (
            ticker,
            r["week_end_date"],
            int(r["open"]),
            int(r["high"]),
            int(r["low"]),
            int(r["close"]),
            float(r["adj_close"]),
            float(r["adj_high"]),
            float(r["adj_low"]),
            int(r["volume"]),
            int(r["value"]),
            int(r["trading_days"]),
        )
```
(`to_weekly_index_rows` 는 변경 없음 — 지수는 adj 미사용.)

- [ ] **Step 4: 구현 — weekly/load.py**

`load_daily_for_ticker` SELECT 에 adj_high/adj_low 추가:
```python
            SELECT date, open, high, low, close, adj_close, adj_high, adj_low, volume, value
              FROM daily_prices
```
`load_index_daily` 는 지수에 adj 가 없으므로, 현재 `adj_close=close` 합성하는 지점 옆에 합성 추가(SELECT 직후 df 가공부):
```python
    df["adj_close"] = df["close"]
    df["adj_high"] = df["high"]
    df["adj_low"] = df["low"]
```
(정확한 합성 위치는 파일에서 `adj_close` 합성 라인을 찾아 그 옆에 추가.)

- [ ] **Step 5: 구현 — weekly/store.py**

`upsert_weekly_prices` INSERT 컬럼/VALUES/SET 에 adj_high/adj_low 추가(adj_close 다음):
```python
              (ticker, week_end_date, open, high, low, close, adj_close, adj_high, adj_low, volume, value, trading_days, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ticker, week_end_date) DO UPDATE
               SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                   close = EXCLUDED.close, adj_close = EXCLUDED.adj_close,
                   adj_high = EXCLUDED.adj_high, adj_low = EXCLUDED.adj_low,
                   volume = EXCLUDED.volume, value = EXCLUDED.value,
                   trading_days = EXCLUDED.trading_days, updated_at = NOW()
```

- [ ] **Step 6: 통과 + 무결성**
Run: `uv run pytest tests/test_weekly_transform.py -v` → PASS
Run: `uv run python -c "import kr_pipeline.weekly.modes; print('ok')"` → ok

- [ ] **Step 7: Commit**
```bash
git add kr_pipeline/weekly/transform.py kr_pipeline/weekly/load.py kr_pipeline/weekly/store.py tests/test_weekly_transform.py
git commit -m "feat(w52): 주봉 adj_high(주중max)/adj_low(주중min) 집계·적재"
```

---

## Task 6: 지표 계산 — w52 를 수정 고가/저가 기준으로 (핵심)

**Files:**
- Modify: `kr_pipeline/indicators/load.py` (load_daily_prices, load_weekly_prices)
- Modify: `kr_pipeline/indicators/compute/high_low.py` (w52_high_low)
- Modify: `kr_pipeline/indicators/modes.py` (호출부 line 174, 502)
- Test: `tests/test_indicators_high_low.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_indicators_high_low.py` 의 w52_high_low 테스트를 2-입력 시그니처로 교체(pct_from_high_low 테스트는 불변):
```python
def test_w52_high_is_max_of_adj_high_low_is_min_of_adj_low():
    high_s = pd.Series([10.0, 20.0, 30.0, 25.0, 15.0])
    low_s  = pd.Series([8.0, 18.0, 28.0, 23.0, 13.0])
    h, l = w52_high_low(high_s, low_s, window=3)
    assert pd.isna(h.iloc[0]) and pd.isna(l.iloc[0])
    assert h.iloc[2] == 30.0   # max(10,20,30)
    assert l.iloc[2] == 8.0    # min(8,18,28)
    assert h.iloc[4] == 30.0   # max(30,25,15)
    assert l.iloc[4] == 13.0   # min(28,23,13)


def test_w52_high_low_window_252_default():
    high_s = pd.Series(range(300), dtype=float)
    low_s = pd.Series(range(300), dtype=float)
    h, l = w52_high_low(high_s, low_s)
    assert h.isna().iloc[:251].all()
    assert h.iloc[251] == 251.0
    assert l.iloc[251] == 0.0


def test_w52_high_low_insufficient_history():
    s = pd.Series([10.0, 20.0])
    h, l = w52_high_low(s, s, window=5)
    assert h.isna().all() and l.isna().all()


def test_w52_high_low_preserves_index():
    idx = pd.date_range("2026-01-01", periods=5)
    high_s = pd.Series([10.0, 20.0, 30.0, 25.0, 15.0], index=idx)
    low_s = pd.Series([8.0, 18.0, 28.0, 23.0, 13.0], index=idx)
    h, l = w52_high_low(high_s, low_s, window=3)
    assert list(h.index) == list(idx) and list(l.index) == list(idx)
```
(기존 `test_high_low_basic`, `test_high_low_window_size_252_default`, `test_high_low_insufficient_history`, `test_high_low_preserves_index` 4개는 위로 교체. pct 테스트 2개는 유지.)

- [ ] **Step 2: 실패 확인**
Run: `uv run pytest tests/test_indicators_high_low.py -v`
Expected: FAIL (w52_high_low 인자 2개 시그니처 불일치)

- [ ] **Step 3: 구현 — high_low.py**

`w52_high_low` 교체:
```python
def w52_high_low(
    adj_high: pd.Series,
    adj_low: pd.Series,
    window: int = 252,
) -> tuple[pd.Series, pd.Series]:
    """52주(기본 252영업일) 수정 고가 rolling max / 수정 저가 rolling min."""
    high = adj_high.rolling(window=window, min_periods=window).max()
    low = adj_low.rolling(window=window, min_periods=window).min()
    return high, low
```
(`pct_from_high_low` 불변.)

- [ ] **Step 4: 구현 — load.py**

`load_daily_prices` SELECT·캐스팅에 adj_high/adj_low 추가:
```python
            SELECT date, adj_close, adj_high, adj_low, close, volume
              FROM daily_prices
```
그리고 `if not df.empty:` 블록에:
```python
        df["adj_high"] = df["adj_high"].astype(float)
        df["adj_low"] = df["adj_low"].astype(float)
```
`load_weekly_prices` 도 동일(`SELECT week_end_date AS date, adj_close, adj_high, adj_low, close, volume`) + 캐스팅 2줄 추가.

- [ ] **Step 5: 구현 — modes.py 호출부**

daily(line 174):
```python
    w52h, w52l = w52_high_low(df["adj_high"], df["adj_low"], window=252)
```
weekly(line 502):
```python
    w52h, w52l = w52_high_low(df["adj_high"], df["adj_low"], window=52)
```
(`adj_close` 변수는 기존대로 SMA·rs_line 등에 계속 사용. df 에 adj_high/adj_low 가 로드됨.)

- [ ] **Step 6: 통과 + 무결성**
Run: `uv run pytest tests/test_indicators_high_low.py -v` → PASS
Run: `uv run python -c "import kr_pipeline.indicators.modes; print('ok')"` → ok
Run: `uv run pytest tests/ -q 2>&1 | tail -5` → fail 수 베이스라인(약 26) 대비 증가 없음. 증가 시 해당 테스트가 구 시그니처/컬럼 참조하는지 점검·갱신.

- [ ] **Step 7: Commit**
```bash
git add kr_pipeline/indicators/load.py kr_pipeline/indicators/compute/high_low.py kr_pipeline/indicators/modes.py tests/test_indicators_high_low.py
git commit -m "feat(w52): w52_high/low 를 수정 고가/저가 기준으로 (지표 계산 교체)"
```

---

## Task 7: threshold-change-checklist 의존성 맵

**Files:**
- Create: `docs/superpowers/specs/2026-06-04-w52-threshold-change-checklist.md`

- [ ] **Step 1: 작성**

`docs/superpowers/threshold-change-checklist.md` 템플릿 형식으로 작성. 최소 포함:
```markdown
# w52 수정 고가/저가 — threshold-change-checklist (2026-06-04)

## 변경
- 상수 값 변경 없음. 단 C6/C7 입력인 w52_high/w52_low 정의 변경(수정종가 → 수정 고가/저가).

## 축 1 — 소비 고정 상수/룰
- C7_W52HIGH_MULT(0.75): w52_high 가 장중 고가 기준으로 (종가보다) 높아짐 → "현재가 ≥ w52_high×0.75"
  통과가 약간 빡빡해짐. 후보 수 재검증(Task 8).
- C6_W52LOW_MULT(1.25): w52_low 가 (종가보다) 낮아질 수 있음 → "현재가 ≥ w52_low×1.25" 영향.
- minervini_pass: C6·C7 변화 → 통과 분포 이동 → 히스토리 재계산 필요(Task 8).

## 축 2 — prompt 임계 텍스트
- analyze_chart_v3.md 의 "52주 고가/저가" 서술 검토 — 정의 변경 텍스트 동기화 필요 여부 확인.

## 충돌 점검
- RS Line(비율)·시장레벨 룰과 무관. 충돌 없음.
```

- [ ] **Step 2: Commit**
```bash
git add docs/superpowers/specs/2026-06-04-w52-threshold-change-checklist.md
git commit -m "docs(w52): threshold-change-checklist 의존성 맵"
```

---

## Task 8: 백필 + 검증 (운영 — 머지·배포 후)

**Files:** 없음(실행). production kr_pipeline 데이터 변경 — 머지 후 수행.

- [ ] **Step 1: 전체 테스트 그린**
Run: `uv run pytest tests/ -q 2>&1 | tail -5`
Expected: 베이스라인(약 26) 대비 신규 실패 없음.

- [ ] **Step 2: 백필 순서대로 실행**
Run:
```bash
uv run python -m kr_pipeline.ohlcv      --mode full-refresh
uv run python -m kr_pipeline.weekly     --mode full-refresh
uv run python -m kr_pipeline.indicators --target weekly --mode full-refresh
uv run python -m kr_pipeline.indicators --target daily  --mode full-refresh
```
Expected: 각 단계 failures=0. (ohlcv full-refresh 는 KRX 자격증명 필요·네트워크 재fetch.)

- [ ] **Step 3: 검증**
Run:
```bash
psql kr_pipeline -P pager=off -c "
SELECT COUNT(*) FILTER (WHERE adj_high IS NULL) AS null_high,
       COUNT(*) FILTER (WHERE adj_high < adj_low) AS inverted,
       COUNT(*) total
  FROM daily_prices WHERE date=(SELECT MAX(date) FROM daily_prices);"
psql kr_pipeline -P pager=off -c "
SELECT COUNT(*) FILTER (WHERE minervini_pass) AS mn_pass
  FROM daily_indicators WHERE date=(SELECT MAX(date) FROM daily_indicators);"
```
Expected: null_high ≈ 0(백필 후), inverted = 0(adj_high ≥ adj_low), minervini_pass 합리적 범위(이전 대비 약간 변동).

- [ ] **Step 4: 검증 결과 기록 + Commit**
설계 문서에 재계산 검증 수치 한 줄 기록 후:
```bash
git add docs/superpowers/specs/2026-06-04-w52-adjusted-high-low-design.md
git commit -m "docs(w52): 백필 검증 수치 기록"
```

---

## Self-Review

- **Spec 커버리지**: 검증게이트=Task0, 스키마=Task1, 적재(증분 transform/store)=Task2-3, 적재(full-refresh)=Task4, 주봉=Task5, 지표(핵심)=Task6, 차트/CSV 불변(비목표, task 없음 — 의도적), SSOT/checklist=Task7, 백필=Task8. 전 항목 매핑.
- **타입 일관성**: 함수명 `update_adj_prices`(Task3·4 동일), `w52_high_low(adj_high, adj_low, window)`(Task6 정의·호출 일치), 컬럼명 `adj_high`/`adj_low` 전 task 동일. to_price_rows 11-튜플 / to_weekly_rows 12-튜플 / update_adj_prices 5-튜플 일관.
- **Plain-code 확인 필요(착수 시)**: test_ohlcv_store.py·test_weekly_transform.py 의 기존 픽스처/헬퍼명, load_index_daily 의 adj_close 합성 라인 위치 — 각 Task 착수 시 파일 상단 확인 후 맞춤(계획에 명시).
- **차단성**: Task 0 실측 결과가 음성이면 접근 A 폴백(설계 §검증 게이트) — Task 2 merge 만 파생식으로 교체, 나머지 구조 동일.
