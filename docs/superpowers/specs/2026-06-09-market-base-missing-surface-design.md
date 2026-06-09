# performance 시장 base 누락 표면화 (⑥) — 설계

날짜: 2026-06-09. 브랜치: `worktree-perf-market-base-missing`.

## 문제
`performance.run` 은 시그널의 시장 대비 수익률(market_return)을 계산할 때, 기준일(`signal_date`,
= `analyzed_for_date` 또는 signal_at UTC 날짜 — 항상 **거래일**)의 지수값을 base 로 쓴다:
`SELECT close FROM index_daily WHERE index_code=%s AND date = signal_date` (정확일치).
거래일이면 일봉(daily_indicators/daily_prices)이 있으므로 그 날의 지수(index_daily)도 **반드시
있어야 정상**이다. 그런데 만약 없으면(=지수 적재 누락) `base_row=None` → 그 시그널의
market_return 이 **모든 기간에서 조용히 NULL** 로 남는다. 종목 수익률은 정상 계산되어 표가 채워진
듯 보이므로, **데이터 적재 사고를 알아채지 못한다.**

(참고: end 값은 `date <= target_date ORDER BY date DESC`(근사) — target_date 는 임의 달력일이라
이게 맞다. base 의 정확일치도 맞다. 비대칭은 정상. 문제는 "조용한 NULL".)

## 목표 / 범위
- 거래일 시그널인데 시장 base 지수가 없으면 → **`log.warning` + run 결과에 보고**(중단 없음).
  daily_delta 의 `integrity_skipped` 패턴과 동일한 결.
- market_return 은 계속 NULL(값 조작 안 함). 종목 가격·수익률은 정상.
- **forward-only**: 기존 행 재계산 안 함.
- 범위 밖: base `=` vs end `<=` 비대칭(정상), end 누락(극히 드묾 — 기존대로 silent), 기존 행 재계산.

## 설계

### 동작 — base 지연(lazy) 단일 조회 + 루프 후 1회 보고
현재 base 조회는 period 루프 **안**에서 기간마다(최대 4회) 일어나고, 종목 price_row 가 있는
기간에서만 도달한다. 이를 다음으로 바꾼다:
- 시그널 처리 시작 시 `base_close = None`, `base_fetched = False`, `base_missing = False`.
- period 루프에서 market_return 계산 지점(= price_row 확보 후)에 도달했을 때, `base_fetched` 가
  False 면 그때 base 를 **1회** 조회(`index_daily WHERE index_code AND date = signal_date`):
  - `base_fetched = True`. 결과가 있으면 `base_close = float(...)`, 없으면 `base_missing = True`.
- market_return 계산은 `base_close is not None AND end_row` 일 때만(기존과 동일, base_close 변수 사용).
- 루프 종료 후: `base_missing` 이면 → `log.warning("market base index missing: %s %s code=%s", symbol, signal_date, market_code)` + `market_base_missing.append({"symbol":..., "signal_date": signal_date.isoformat(), "market_code":...})`.

→ 효과: base 가 **실제로 필요했던**(price 존재한 기간이 있던) 시그널에서 누락 시에만 보고.
  가격 자체가 없거나(다른 문제), 전부 미도래/이미 채워진 시그널은 조회·보고 안 함(스푸리어스 방지).
  base 조회 시그널당 **최대 1회**(중복 4→1).

### 결과 dict
`run()` 반환을 `{"backfilled": N}` → `{"backfilled": N, "market_base_missing": [ {...}, ... ]}` 로 확장.
additive — `__main__` 의 결과 소비(rows_affected 등)와 run_tracking 비파괴.

### 불변
end(target_date) 근사조회, UPSERT(symbol, signal_at), skip-filled 최적화, 90일 윈도, signal_date
산출(analyzed_for_date 우선) — 모두 그대로.

## 테스트 (결정론, LLM 없음; db 픽스처, db.commit 금지, sentinel 2099)
1. **base 누락 보고**: 종목 가격은 target 에 있고 `index_daily` 에 signal_date base 없음(2099) →
   price_1w/return_1w 계산됨 + **market_return_1w NULL** + `result["market_base_missing"]` 에 그
   시그널 1건 보고.
2. **정상**: `index_daily` 에 signal_date(base)·target(end) 둘 다 있음 → market_return 계산됨 +
   `result["market_base_missing"]` 비어있음.
3. (회귀) 기존 `tests/test_llm_performance.py` 통과.

## 영향받는 파일
- `kr_pipeline/llm_runner/performance.py` (run 함수)
- `tests/test_performance_market_base_missing.py` (신규)
