# performance 기업행위 수익률 보정 (⑦) Implementation Plan

> subagent-driven-development 으로 실행.

**Goal:** performance 수익률 분모를 raw entry_price → adjusted_entry(= entry_price × adj_close[signal_date]/close[signal_date])로 보정해, 신호 이후 분할 시 수익률 왜곡 제거. signal_performance.entry_price 에도 adjusted_entry 저장.

**Tech:** Python/psycopg/Postgres/pytest. LLM 미사용 → 결정론. db 픽스처, **db.commit 금지**(run() 내부 commit → 테스트는 시작 시 DELETE 정리), sentinel 2099.

**선행:** 설계 `docs/superpowers/specs/2026-06-09-corp-action-return-design.md`. 현재 return: `if prices[period_name] is None: updates[price]=future_price; updates[return]=(future_price - float(entry_price))/float(entry_price)*100`. UPSERT 는 `(symbol, signal_at, float(entry_price), *updates)`. future_price = adj_close[target].

---

## Task 1: trigger 앵커 보정

**Files:** Modify `kr_pipeline/llm_runner/performance.py`; Create `tests/test_performance_corp_action_return.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_performance_corp_action_return.py
from datetime import date, datetime, timezone

def _seed(cur, ticker, sig, afd, sig_close, sig_adj, target_date, target_adj):
    cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'x','KOSPI') ON CONFLICT DO NOTHING", (ticker,))
    cur.execute("DELETE FROM entry_params WHERE symbol=%s", (ticker,))
    cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,analyzed_for_date,"
                "trigger_evaluation_at,prior_classification_at) "
                "VALUES (%s,%s,100,92,%s,%s,%s) ON CONFLICT DO NOTHING", (ticker, sig, afd, sig, sig))
    # signal_date 의 원본/수정 (보정계수 f = sig_adj/sig_close)
    cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,1000,1) ON CONFLICT DO NOTHING",
                (ticker, afd, sig_close, sig_close, sig_close, sig_close, sig_adj))
    # target 의 수정 종가 (수익률 분자)
    cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,1000,1) ON CONFLICT DO NOTHING",
                (ticker, target_date, target_adj, target_adj, target_adj, target_adj, target_adj))

def test_split_adjusts_entry_denominator(db):
    """신호일 close=100/adj=50(분할 반영) → adjusted_entry=50; target adj=60 → return=+20%(raw 였으면 -40%)."""
    from kr_pipeline.llm_runner import performance
    afd = date(2099, 3, 2); sig = datetime(2099, 3, 2, 5, 0, tzinfo=timezone.utc); as_of = date(2099, 3, 20)
    with db.cursor() as cur:
        _seed(cur, "CAR1", sig, afd, sig_close=100, sig_adj=50, target_date=date(2099,3,9), target_adj=60)
    performance.run(db, as_of=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT entry_price, return_1w_pct FROM signal_performance WHERE symbol='CAR1' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None
    assert abs(float(row[0]) - 50.0) < 0.01      # adjusted_entry 저장
    assert abs(float(row[1]) - 20.0) < 0.01      # (60-50)/50 = +20% (raw 였으면 -40)

def test_no_adjustment_unchanged(db):
    """adj==close(보정 없음) → adjusted_entry=entry_price=100; target adj=110 → +10%(기존과 동일)."""
    from kr_pipeline.llm_runner import performance
    afd = date(2099, 4, 2); sig = datetime(2099, 4, 2, 5, 0, tzinfo=timezone.utc); as_of = date(2099, 4, 20)
    with db.cursor() as cur:
        _seed(cur, "CAR2", sig, afd, sig_close=100, sig_adj=100, target_date=date(2099,4,9), target_adj=110)
    performance.run(db, as_of=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT entry_price, return_1w_pct FROM signal_performance WHERE symbol='CAR2' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None
    assert abs(float(row[0]) - 100.0) < 0.01
    assert abs(float(row[1]) - 10.0) < 0.01
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_performance_corp_action_return.py -v` → `test_split_adjusts_entry_denominator` FAIL(현재 raw: entry_price=100, return_1w=-40).

- [ ] **Step 3: performance.py 수정**
  (a) 각 시그널 본문(`signal_date` 계산 근처, period 루프 전)에 `adj_entry = None; adj_entry_fetched = False`.
  (b) `if prices[period_name] is None:` 분기 안, return 계산 **전**에 lazy 보정계수:
```python
                if not adj_entry_fetched:
                    adj_entry_fetched = True
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT close, adj_close FROM daily_prices WHERE ticker = %s AND date = %s",
                            (symbol, signal_date),
                        )
                        arow = cur.fetchone()
                    if arow and arow[0] and float(arow[0]) != 0:
                        adj_entry = float(entry_price) * (float(arow[1]) / float(arow[0]))
                    else:
                        adj_entry = float(entry_price)   # f=1 fallback (무회귀)
                updates[f"price_{period_name}"] = future_price
                updates[f"return_{period_name}_pct"] = (
                    (future_price - adj_entry) / adj_entry * 100
                )
```
  (즉 기존 `updates[price]/updates[return]` 두 줄을 위 블록으로 교체. else 분기는 그대로.)
  (c) UPSERT 의 entry_price positional 을 교체: `float(entry_price)` → `(adj_entry if adj_entry is not None else float(entry_price))`. (INSERT 컬럼 entry_price 값. DO UPDATE SET 에는 entry_price 없음 — 그대로.)

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_performance_corp_action_return.py -v` → 2 passed.

- [ ] **Step 5: 회귀** — `uv run pytest tests/test_llm_performance.py tests/test_performance_baseline_afd.py tests/test_performance_market_base_missing.py -v` → 통과(기존 테스트는 adj==close 로 시드하거나 adj_close 만 신경 → f=1 또는 동일 동작; 만약 기존 테스트가 adj_close≠close 로 시드해 깨지면 그 테스트의 기대값이 raw 가정인지 확인 후 보고).

- [ ] **Step 6: 커밋**
```bash
git add kr_pipeline/llm_runner/performance.py tests/test_performance_corp_action_return.py
git commit -m "fix(performance): 수익률 분모를 trigger 앵커 보정(adjusted_entry)으로 — 분할 왜곡 제거"
```

## 범위 밖
forward-only, skip-filled 유지, cross-period drift 수용, 현금배당 제외(기존 정책).
