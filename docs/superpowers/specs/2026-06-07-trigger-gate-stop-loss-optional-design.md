# 트리거 게이트 stop_loss(base_low) 선택화 설계

날짜: 2026-06-07
대상: `kr_pipeline/llm_runner/compute/trigger_gate.py`, `kr_pipeline/llm_runner/evaluate_pivot.py`, `kr_pipeline/llm_runner/load.py`

## 배경 / 문제

평일 트리거 모니터링은 active(entry/watch) 분류를 매일 점검해 breakout/invalidation/promotion 신호를 낸다. 흐름:
- `load.get_active_with_current`(`load.py:139`): enriched dict 에 `"stop_loss": a.get("base_low", 0)`. base_low 는 `weekly_classification` 의 nullable 컬럼이고 `get_active_monitoring`(`load.py:73`)이 `float 또는 None` 으로 항상 키에 넣으므로, **base_low 가 NULL 이면 stop_loss = None**(`, 0` 기본값은 키가 항상 존재해 발동 안 함 — 죽은 코드).
- `evaluate_pivot.run`(`:20`) 입구 가드: `close, pivot_price, volume, avg_volume_50d, stop_loss, sma_50` 가 **하나라도 None 이면 그 종목 skip**.
- 따라서 **base_low 만 NULL 인 종목은 트리거 평가에서 통째로 제외**된다(breakout/promotion 도 안 봄).

문제: breakout 은 `pivot_price`+거래량만, promotion 도 `pivot_price`만 필요하고 base_low(stop_loss)는 invalidation 체크 한 곳(`trigger_gate.py:49` `close < stop_loss`)에만 쓰인다. 그런데 가드가 stop_loss 를 **필수**로 요구해, "pivot 은 있는데 base_low 만 NULL 인" entry 종목이 생기면 **돌파 신호를 부당하게 놓친다**.

**현재 영향 = 0**(실측: active watch 15 중 base_low NULL 8개는 모두 pivot_price 도 NULL 이라 어차피 제외가 맞음, entry 0). 하지만 "pivot 있고 base_low 만 NULL" 발생 시 신호 손실 — 잠재 버그를 예방한다.

## 목표

base_low(stop_loss) 가 없어도 pivot 기반 트리거(breakout/promotion)와 sma_50 invalidation 은 정상 평가되게 한다. base_low 가 있을 때만 그 invalidation 체크를 적용한다.

## 비목표

- breakout/promotion/sma_50 invalidation 로직 자체 변경.
- base_low 를 NOT NULL 로 만들거나 LLM 이 항상 내게 강제(별도 영역).
- 다른 LLM 단계 허점(B/C/D 후속 후보).

## 아키텍처 (변경 3곳)

1. **`trigger_gate.py` `evaluate`**: stop_loss 를 선택적으로.
   - 시그니처: `stop_loss: float` → `stop_loss: float | None`.
   - `if close < stop_loss:` → `if stop_loss is not None and close < stop_loss:` (base_low 없으면 이 invalidation 만 건너뜀; `close < sma_50` invalidation·breakout·promotion 은 그대로).
2. **`evaluate_pivot.py` `run`** 입구 가드: 필수 키 목록에서 `stop_loss` 제거 → `("close", "pivot_price", "volume", "avg_volume_50d", "sma_50")`. (pivot_price 는 유지 — breakout/promotion 필수. pivot_price NULL 종목은 종전대로 제외.) `evaluate_gate(..., stop_loss=a["stop_loss"], ...)` 호출은 그대로(키 항상 존재, None 가능 — trigger_gate 가 None 처리).
3. **`load.py:139`**: `"stop_loss": a.get("base_low")` (오해 소지 `, 0` 제거 — 어차피 키 존재라 0 안 나옴).

## 데이터 흐름 / 영향

`a["stop_loss"]` 는 **trigger_gate 호출에만** 소비된다(검증: `_process_one` 은 symbol 만 넘겨 `build_for_5b` 가 DB 에서 base_low 를 독립적으로 다시 읽음 — enriched dict 의 stop_loss 안 씀). trigger_gate.evaluate 의 유일 호출자는 evaluate_pivot. → None 이 흘러가 문제 될 하류 없음.

## 에러 처리 / 엣지

- base_low NULL → stop_loss None → 가드 통과(pivot 등 있으면) → trigger_gate 가 stop_loss invalidation 만 skip.
- pivot_price NULL → 가드에서 종전대로 제외(breakout/promotion 불가라 올바름).
- 기존 동작 보존: stop_loss 가 float 면 `is not None` True → invalidation 판정 종전과 동일.

## 테스트

- **`trigger_gate.evaluate` 단위(순수함수)**: ① `stop_loss=None` + close 가 (없는)stop 아래여도 stop invalidation 안 일어남; 단 `close < sma_50` invalidation 은 발동, entry 의 breakout(pivot 돌파+거래량)도 정상 발동. ② `stop_loss=<float>` + `close < stop_loss` → invalidation(기존 동작 보존). 기존 7개 테스트(stop_loss=양수)는 불변.
- **가드(evaluate_pivot)**: base_low NULL + pivot_price/close/sma_50 등 존재하는 active entry 종목이 **skip 되지 않고 평가**됨(DB 시드: weekly_classification entry + base_low NULL + pivot 있음 + daily_indicators 오늘 데이터 → breakout 감지되어 trigger_evaluation_log/처리 경로 진입). pivot_price NULL 종목은 skip 유지.
- **회귀**: 기존 `test_llm_compute_trigger_gate.py`(7) 통과, base 대비 신규 실패 0.

## 파일 변경 예상

- 변경: `trigger_gate.py`(시그니처+조건), `evaluate_pivot.py`(가드 1줄), `load.py`(:139 1줄).
- 테스트: `tests/test_llm_compute_trigger_gate.py`(None 케이스 추가), `tests/test_llm_store_load.py` 또는 신규(가드/enriched stop_loss=None 경로).
