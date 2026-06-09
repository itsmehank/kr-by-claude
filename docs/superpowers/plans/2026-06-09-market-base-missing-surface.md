# performance 시장 base 누락 표면화 (⑥) Implementation Plan

> subagent-driven-development 으로 실행. 스텝은 체크박스.

**Goal:** performance.run 에서 거래일 시그널의 시장 base 지수가 없으면 조용한 NULL 대신 `log.warning` + run 결과 `market_base_missing` 목록으로 표면화(중단 없음). base 조회는 시그널당 lazy 1회.

**Tech:** Python/psycopg/Postgres/pytest. performance 는 LLM 미사용 → 결정론 테스트. `db` 픽스처, **db.commit 금지**(run()이 내부 commit 하므로 테스트는 시작 시 DELETE 정리), sentinel 2099.

**선행:** 설계 `docs/superpowers/specs/2026-06-09-market-base-missing-surface-design.md`. 현재 base 조회는 period 루프 안에서 매 기간(최대 4회) `index_daily WHERE index_code=%s AND date=%s (signal_date)`. end 는 `date<=target ORDER BY DESC`(유지).

---

## Task 1: lazy base 조회 + 누락 보고

**Files:** Modify `kr_pipeline/llm_runner/performance.py`; Create `tests/test_performance_market_base_missing.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_performance_market_base_missing.py
from datetime import date, datetime, timezone

def _seed_signal(cur, ticker, sig, afd, price_date, price=110.0):
    cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'x','KOSPI') ON CONFLICT DO NOTHING", (ticker,))
    cur.execute("DELETE FROM entry_params WHERE symbol=%s", (ticker,))  # run() commits → 시작 정리
    cur.execute("INSERT INTO entry_params (symbol,signal_at,entry_price,stop_loss,analyzed_for_date,"
                "trigger_evaluation_at,prior_classification_at) "
                "VALUES (%s,%s,100,92,%s,%s,%s) ON CONFLICT DO NOTHING", (ticker, sig, afd, sig, sig))
    cur.execute("INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,1000,1) ON CONFLICT DO NOTHING",
                (ticker, price_date, price, price, price, price, price))

def test_missing_market_base_is_reported_not_silent(db):
    from kr_pipeline.llm_runner import performance
    afd = date(2099, 6, 1)                                  # 거래일 가정 (KOSPI=1001)
    sig = datetime(2099, 6, 1, 5, 0, tzinfo=timezone.utc)
    as_of = date(2099, 6, 20)
    with db.cursor() as cur:
        cur.execute("DELETE FROM index_daily WHERE index_code='1001' AND date IN ('2099-06-01','2099-06-08')")  # base 없음 보장
        _seed_signal(cur, "MBM1", sig, afd, date(2099, 6, 8))   # afd+7 가격
    res = performance.run(db, as_of=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT price_1w, return_1w_pct, market_return_1w_pct FROM signal_performance WHERE symbol='MBM1' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None
    assert float(row[0]) == 110.0            # 종목 가격 정상
    assert abs(float(row[1]) - 10.0) < 0.01  # 종목 수익률 정상
    assert row[2] is None                    # market_return 은 NULL (base 없음)
    reported = {m["symbol"] for m in res.get("market_base_missing", [])}
    assert "MBM1" in reported                # 조용한 NULL 아니라 보고됨

def test_market_base_present_computes_and_no_report(db):
    from kr_pipeline.llm_runner import performance
    afd = date(2099, 7, 1)
    sig = datetime(2099, 7, 1, 5, 0, tzinfo=timezone.utc)
    as_of = date(2099, 7, 20)
    with db.cursor() as cur:
        _seed_signal(cur, "MBM2", sig, afd, date(2099, 7, 8), price=120.0)
        # base(7/1) + end(<=7/8) 지수 존재 → market_return 계산
        for d, c in [(date(2099,7,1), 1000.0), (date(2099,7,8), 1100.0)]:
            cur.execute("INSERT INTO index_daily (index_code,date,close) VALUES ('1001',%s,%s) ON CONFLICT DO NOTHING", (d, c))
    res = performance.run(db, as_of=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT market_return_1w_pct FROM signal_performance WHERE symbol='MBM2' AND signal_at=%s", (sig,))
        row = cur.fetchone()
    assert row is not None and row[0] is not None        # market_return 계산됨
    assert abs(float(row[0]) - 10.0) < 0.01              # (1100-1000)/1000 = 10%
    assert "MBM2" not in {m["symbol"] for m in res.get("market_base_missing", [])}
```
NOTE: `index_daily` 의 NOT NULL 컬럼을 확인해 INSERT 를 맞출 것(index_code,date,close 외 필수 있으면 추가). 첫 테스트는 base 행 부재를 DELETE 로 보장.

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_performance_market_base_missing.py -v` → `test_missing_market_base_is_reported_not_silent` FAIL(현재 `market_base_missing` 키 없음 → `res.get(...)` 빈 set → assert 실패).

- [ ] **Step 3: performance.py 수정**
  (a) 행 루프 시작 전 accumulator: `market_base_missing = []` (backfilled 옆).
  (b) 각 시그널 처리 시작부(signal_date 계산 근처)에 `base_close = None; base_fetched = False; base_missing = False`.
  (c) period 루프 안의 시장 base/end 블록을 교체 — base 는 lazy 1회:
```python
            if not base_fetched:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT close FROM index_daily WHERE index_code = %s AND date = %s",
                        (market_code, signal_date),
                    )
                    brow = cur.fetchone()
                base_fetched = True
                if brow:
                    base_close = float(brow[0])
                else:
                    base_missing = True
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT close FROM index_daily WHERE index_code = %s AND date <= %s "
                    "ORDER BY date DESC LIMIT 1",
                    (market_code, target_date),
                )
                end_row = cur.fetchone()
            if base_close is not None and end_row:
                updates[f"market_return_{period_name}_pct"] = (
                    (float(end_row[0]) - base_close) / base_close * 100
                )
```
  (d) period 루프 종료 후(해당 시그널) 보고:
```python
        if base_missing:
            log.warning("market base index missing — symbol=%s signal_date=%s code=%s",
                        symbol, signal_date, market_code)
            market_base_missing.append({
                "symbol": symbol,
                "signal_date": signal_date.isoformat(),
                "market_code": market_code,
            })
```
  (e) 반환: `return {"backfilled": backfilled, "market_base_missing": market_base_missing}`.

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_performance_market_base_missing.py -v` → 2 passed.

- [ ] **Step 5: 회귀** — `uv run pytest tests/test_llm_performance.py tests/test_performance_baseline_afd.py -v` → 통과(market_base_missing 키 추가는 additive; 기존 테스트가 base 지수를 시드하면 정상 계산, 안 하면 빈 보고).

- [ ] **Step 6: 커밋**
```bash
git add kr_pipeline/llm_runner/performance.py tests/test_performance_market_base_missing.py
git commit -m "fix(performance): 시장 base 지수 누락을 조용한 NULL 대신 경고+결과 보고 (lazy 단일 조회)"
```

## 범위 밖
end(target_date) 누락은 기존대로 silent(매우 드묾). base `=` vs end `<=` 비대칭은 정상. 기존 행 재계산 안 함.
