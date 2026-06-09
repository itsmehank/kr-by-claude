# performance 기업행위(분할) 수익률 보정 (⑦) — 설계

날짜: 2026-06-09. 브랜치: `worktree-perf-corp-action-return`.

## 문제
`performance.run` 의 수익률 = `(adj_close[target] − entry_price) / entry_price`.
- `entry_price`(=trigger_price)는 **신호 시점 기준 수정주가**(프롬프트가 LLM 에 "모든 가격 수정주가"로
  전달 → 신호 시점엔 그 날 adj≈raw 라 사실상 raw 신호일 가격 단위).
- `adj_close[target]`는 **현재(최신 적재) 재보정** 기준.
신호 이후 분할이 생기면 adj_close 전체가 재-베이스되는데 stored entry_price 는 옛 기준 → 분모/분자
기준 불일치 → 수익률 왜곡(예: 2:1 분할 시 −50% 처럼 보임).

## 해법 — trigger 앵커 보정
수익률은 비율 → 분자·분모가 **계산 시점 같은 기준**이면 정확. 보정계수
`f = adj_close[signal_date] / close[signal_date]`(둘 다 daily_prices 에 존재, NOT NULL)로
`adjusted_entry = entry_price × f` 를 만들어 **현재 수정 시계열로 환산**.
- `return_{period}_pct = (adj_close[target] − adjusted_entry) / adjusted_entry × 100`.
- `signal_performance.entry_price` 에 **adjusted_entry 저장**(표 자기정합: entry·price·return 동일 기준).

검산(2:1 분할, signal<split<target): close[sig]=100, entry≈100, adj_close[sig]_now=50 → f=0.5 →
adjusted_entry=50. adj_close[target]=60 → return=(60−50)/50=+20%(정확). 기존 raw: −40%(오류).

## 설계 (구현 정밀화 반영)
- 시그널당 `adj_entry=None`, `adj_entry_fetched=False`.
- **lazy**: `prices[period] is None` 분기(= return 계산 = 첫 INSERT 시점)에서 처음으로
  `SELECT close, adj_close FROM daily_prices WHERE ticker=%s AND date=signal_date` 1회 →
  `f = adj_close/close`(close 유효 시), `adj_entry = entry_price × f`; close=0/행없음 → `f=1`
  (adj_entry = entry_price, = 현 동작 무회귀).
- return 분모 = `adj_entry`. UPSERT 의 entry_price positional = `adj_entry if adj_entry is not None
  else float(entry_price)` (INSERT 는 항상 price-None 분기를 거쳐 adj_entry 계산됨; UPDATE 경로에선
  entry_price 가 SET 에 없어 무시 → 안전).
- market_return(⑥ base 로직), end `<=`, skip-filled, UPSERT 키, 90일 윈도, signal_date 산출 불변.

## 소비처 안전 (확인됨)
- `api/routers/performance.py /summary`: return_pct·market_return_pct 집계만 → fix 로 정확해짐.
- `/signals`: entry_price + return 표시(기간 price 미표시) → adjusted 저장 시 정합, 무분할 케이스 동일.

## 범위 밖
- **forward-only**(기존 행 재계산 안 함; 영향 ≈ 0). 드문 mid-window 분할의 cross-period 저장 price
  drift 수용(각 return_pct 는 개별 정확). 현금배당은 adj 에서 제외(기존 정책) — f 는 분할/주식배당만.

## 영향 파일
- `kr_pipeline/llm_runner/performance.py`
- `tests/test_performance_corp_action_return.py` (신규)
