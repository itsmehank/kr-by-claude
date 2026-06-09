# performance 기준일 보정 (B) — signal_at → analyzed_for_date Implementation Plan

> **For agentic workers:** subagent-driven-development 으로 태스크 단위 실행. 스텝은 체크박스.

**Goal:** performance(성과 측정)의 기준일을 "분석 실행 시각(`signal_at`)"이 아니라 "분석이 사용한 데이터 날짜(`analyzed_for_date`)"로 바꿔, 오전(전날 데이터) 실행분의 1/2/4/8주 수익률이 하루 밀리지 않게 한다.

**Architecture:** `performance.run` 의 `signal_date = signal_at.date()` 산출을 `analyzed_for_date or signal_at.date()` 로 교체(legacy NULL 은 fallback). 90일 윈도도 `COALESCE(analyzed_for_date, signal_at::date)` 로. forward-only(기존 행 재계산 안 함; 영향받는 기존 행 ≈ 0 — entry_params 가 과거 사실상 0행이었음). signal_performance PK(symbol, signal_at) 불변.

**Tech:** Python/psycopg/Postgres/pytest. performance 는 LLM 미사용 → 전부 결정론 테스트. `db` 픽스처(rollback), **db.commit() 금지**(같은 커넥션 가시성), seed 는 ON CONFLICT DO NOTHING, sentinel 2099 날짜.

---

## Task 1: performance 기준일을 analyzed_for_date 로

**Files:** Modify `kr_pipeline/llm_runner/performance.py`; Create `tests/test_performance_baseline_afd.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_performance_baseline_afd.py
from datetime import date, datetime, timezone

def test_baseline_uses_analyzed_for_date(db):
    from kr_pipeline.llm_runner import performance
    afd = date(2099, 3, 2)
    sig = datetime(2099, 3, 3, 1, 0, tzinfo=timezone.utc)
    as_of = date(2099, 3, 20)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('PB1','x','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,analyzed_for_date,"
                    "trigger_evaluation_at,prior_classification_at) "
                    "VALUES ('PB1',%s,100,92,%s,%s,%s) ON CONFLICT DO NOTHING", (sig, afd, sig, sig))
        cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                    "VALUES ('PB1',%s,110,110,110,110,110,1000,1) ON CONFLICT DO NOTHING", (date(2099,3,9),))   # afd+7
        cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                    "VALUES ('PB1',%s,200,200,200,200,200,1000,1) ON CONFLICT DO NOTHING", (date(2099,3,10),))  # signal_at+7 (함정)
    performance.run(db, as_of=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT price_1w, return_1w_pct FROM signal_performance WHERE symbol='PB1' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None
    assert float(row[0]) == 110.0
    assert abs(float(row[1]) - 10.0) < 0.01

def test_baseline_fallback_to_signal_at_when_afd_null(db):
    from kr_pipeline.llm_runner import performance
    sig = datetime(2099, 4, 3, 1, 0, tzinfo=timezone.utc)
    as_of = date(2099, 4, 20)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('PB2','x','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,"
                    "trigger_evaluation_at,prior_classification_at) "
                    "VALUES ('PB2',%s,100,92,%s,%s) ON CONFLICT DO NOTHING", (sig, sig, sig))   # analyzed_for_date NULL
        cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                    "VALUES ('PB2',%s,130,130,130,130,130,1000,1) ON CONFLICT DO NOTHING", (date(2099,4,10),))  # signal_at+7
    performance.run(db, as_of=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT price_1w FROM signal_performance WHERE symbol='PB2' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None and float(row[0]) == 130.0
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_performance_baseline_afd.py -v` → `test_baseline_uses_analyzed_for_date` FAIL(price_1w=200, signal_at 3/3+7=3/10 기준).

- [ ] **Step 3: performance.py 수정**
  (a) entry_params 조회 SELECT 컬럼에 `ep.analyzed_for_date` 추가(`ep.signal_at,` 다음, `ep.entry_price,` 앞). 90일 윈도 두 조건의 `ep.signal_at::date` → `COALESCE(ep.analyzed_for_date, ep.signal_at::date)`.
  (b) 행 언패킹 튜플에 `analyzed_for_date` 를 `signal_at` 다음에 추가. `signal_date = signal_at.astimezone(timezone.utc).date()` → `signal_date = analyzed_for_date or signal_at.astimezone(timezone.utc).date()`. 나머지(target_date, 시장 base, UPSERT) 불변.

  수정 후 SELECT 예:
```python
            SELECT ep.symbol, ep.signal_at, ep.analyzed_for_date, ep.entry_price,
                   sp.price_1w, sp.price_2w, sp.price_4w, sp.price_8w,
                   sp.market_return_1w_pct, sp.market_return_2w_pct,
                   sp.market_return_4w_pct, sp.market_return_8w_pct
              FROM entry_params ep
              LEFT JOIN signal_performance sp
                ON sp.symbol = ep.symbol AND sp.signal_at = ep.signal_at
             WHERE COALESCE(ep.analyzed_for_date, ep.signal_at::date) >= %s - INTERVAL '90 days'
               AND COALESCE(ep.analyzed_for_date, ep.signal_at::date) <= %s
```
  언패킹 예:
```python
    for (symbol, signal_at, analyzed_for_date, entry_price,
         p1w, p2w, p4w, p8w,
         mr1w, mr2w, mr4w, mr8w) in rows:
        ...
        signal_date = analyzed_for_date or signal_at.astimezone(timezone.utc).date()
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_performance_baseline_afd.py -v` → 2 passed.

- [ ] **Step 5: 회귀** — `uv run pytest tests/test_llm_performance.py -v` → 통과(기존 테스트는 analyzed_for_date 없이 시드 → NULL fallback → 동일 동작).

- [ ] **Step 6: 커밋**
```bash
git add kr_pipeline/llm_runner/performance.py tests/test_performance_baseline_afd.py
git commit -m "fix(performance): 성과 기준일을 analyzed_for_date(데이터 날짜)로 (signal_at fallback)"
```

## 범위 밖
- 기존 signal_performance 행 재계산(forward-only). 시장 base exact-date 매칭 견고화(별개 이슈).
