# entry_params 프롬프트↔store 계약 버그 수정 설계

날짜: 2026-06-07
대상(변경): `kr_pipeline/db/schema.sql`, `kr_pipeline/llm_runner/store.py`(`insert_entry_params` + 신규 `_normalize_entry_params`), `kr_pipeline/llm_runner/llm/claude_cli.py`(`_mock_calculate_entry_params`), `kr_pipeline/llm_runner/entry_params.py`(dry-run 분기에서 정규화 검증)
대상(무변경·검증만): `api/routers/signals.py`, `kr_pipeline/llm_runner/performance.py`, `kr_pipeline/llm_runner/slack.py`, `prompts/calculate_entry_params_v2_0.md`, web

## 배경 / 문제

평일 (6) `calculate_entry_params` 단계가 **사실상 깨져 있다**(실측: `entry_params` 0행, `signal_performance` 0행).

- 프롬프트 §9 출력 스키마(17필드)와 `store.insert_entry_params`(`store.py:274-298`)가 **서로 다른 시기에 다른 이름으로 작성**됨. store 가 읽는 14개 키가 전부 **하드인덱싱**(`result["x"]`).
- 6개 키가 §9 와 불일치: 2개 리네임(`stop_loss`↔§9 `stop_loss_price`, `position_size_pct`↔§9 `suggested_weight_pct`), 4개 §9 부재(`entry_price`, `stop_loss_basis`, `risk_reward_ratio`, `position_size_basis`).
- 실 LLM 이 §9 대로 응답하면 `result["entry_price"]`(`store.py:279`)에서 첫 `KeyError` → 종목별 `try/except`(`entry_params.py:75-78`)에 삼켜져 실패·rollback → **0행**.
- dry-run mock `_mock_calculate_entry_params`(`claude_cli.py:86-110`)는 **store 의 코드 키명**을 써서 통과 → 버그를 가림. 게다가 dry-run 은 INSERT 자체를 건너뛰므로(`entry_params.py:95-97` "skipping DB insert" 후 `return`) 계약을 한 번도 실행하지 않는다. **버그가 오래 숨은 이유**: dry-run 은 insert 안 함 + 실 실행은 KeyError 를 조용히 삼킴.

§9 는 신중히 설계된 스키마이고 깨진 쪽은 "받는 store" 이므로, **받는 쪽에 정규화 계층**을 두어 §9→저장 컬럼으로 매핑·파생한다.

## 목표

(6) 단계가 실 LLM(§9) 출력으로 **entry_params 에 정상 저장**되게 한다(0행 탈출). 계산 가능한 값은 코드가 도출하고, mock 을 §9 로 맞춰 dry-run 이 실제를 대표하게 한다.

## 핵심 결정 (브레인스토밍 합의)

1. **(가) 정규화 계층** — §9 를 진실로 삼고 store 를 맞춤(프롬프트 무변경).
2. **(다) §9-only 5필드 전부 컬럼 추가** — pivot_price, current_price, pattern_basis, entry_window_days, max_chase_pct_from_pivot.
3. **계산 가능값은 코드** — risk_reward_ratio 는 LLM 아닌 코드 도출.

## 비목표 (Non-goals)

- 프롬프트 §9 출력 스키마 변경(LLM 동작 불변).
- 기존 행 마이그레이션(0행 → 불필요).
- 5 신규 컬럼을 `signals.py` API/web 에 노출(별도 후속; 이번엔 DB 저장까지).
- daily_delta/evaluate_pivot 의 다른 허점(1a/1c/2c 등)·entry_price 산식 고도화.

## 아키텍처

### 1. 스키마 — `kr_pipeline/db/schema.sql`

`entry_params` CREATE TABLE 정의에 5컬럼 추가:
```sql
  pivot_price                NUMERIC(12, 4),
  current_price              NUMERIC(12, 4),
  pattern_basis              VARCHAR(30),
  entry_window_days          SMALLINT,
  max_chase_pct_from_pivot   NUMERIC(6, 2),
```
**그리고** 기존 마이그레이션 패턴(`schema.sql:300-308` weekly_classification 등)을 따라 idempotent ALTER 추가:
```sql
ALTER TABLE entry_params ADD COLUMN IF NOT EXISTS pivot_price NUMERIC(12,4);
ALTER TABLE entry_params ADD COLUMN IF NOT EXISTS current_price NUMERIC(12,4);
ALTER TABLE entry_params ADD COLUMN IF NOT EXISTS pattern_basis VARCHAR(30);
ALTER TABLE entry_params ADD COLUMN IF NOT EXISTS entry_window_days SMALLINT;
ALTER TABLE entry_params ADD COLUMN IF NOT EXISTS max_chase_pct_from_pivot NUMERIC(6,2);
```
**이유**: `CREATE TABLE IF NOT EXISTS` 는 기존 테이블에 컬럼을 안 붙인다. 테스트 DB(kr_test)는 conftest 가 매 세션 `psql -f schema.sql`(`conftest.py:25`) → ALTER IF NOT EXISTS 로 자동 반영. 프로덕션(kr_pipeline)은 머지 후 `psql -f schema.sql` 수동 적용(메모리 [[schema_manual_apply_both_dbs]] 규칙).

### 2. 정규화 함수 — `_normalize_entry_params(result: dict) -> dict` (store.py 신규)

§9 LLM 출력 → 저장용 dict. 매핑:

| 저장 컬럼 | 소스 |
|---|---|
| entry_mode | `result["entry_mode"]` |
| pivot_price | `result["pivot_price"]` (신규) |
| trigger_price | `result["trigger_price"]` |
| current_price | `result["current_price"]` (신규) |
| entry_price | `result["trigger_price"]` (파생: §1.1 "보통 trigger_price") |
| stop_loss | `result["stop_loss_price"]` (리네임) |
| stop_loss_pct_from_pivot | `result["stop_loss_pct_from_pivot"]` |
| stop_loss_pct_from_current_price | `result["stop_loss_pct_from_current_price"]` |
| stop_loss_basis | None (§9 부재) |
| expected_target_price | `result["expected_target_price"]` |
| expected_target_pct | `result["expected_target_pct"]` |
| risk_reward_ratio | 계산: `expected_target_pct / abs(stop_loss_pct_from_current_price)`, 분모 0/None 이면 None. **결과가 `NUMERIC(5,2)` 범위(±999.99) 밖이면 None** (비정상 손절%로 인한 INSERT 오버플로=조용한 실패 재발 방지) |
| position_size_pct | `result["suggested_weight_pct"]` (리네임) |
| position_size_basis | None (§9 부재) |
| pattern_basis | `result["pattern_basis"]` (신규) |
| entry_window_days | `result["entry_window_days"]` (신규) |
| max_chase_pct_from_pivot | `result["max_chase_pct_from_pivot"]` (신규) |
| breakout_volume_requirement | `result["breakout_volume_requirement"]` |
| observed_breakout_volume_ratio | `result["observed_breakout_volume_ratio"]` (null 허용) |
| known_warnings | `result.get("known_warnings", [])` |
| other_warnings | `result.get("other_warnings")` |
| notes | `result.get("notes")` |

**검증(필수 §9 키 존재)**: `entry_mode, pivot_price, trigger_price, current_price, stop_loss_price, stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, suggested_weight_pct, expected_target_price, expected_target_pct, pattern_basis, entry_window_days, max_chase_pct_from_pivot, breakout_volume_requirement, observed_breakout_volume_ratio` 중 **키 자체가 없으면**(값 null 은 허용) `ValueError(f"entry_params schema drift: missing §9 field '{k}'")`. → 한 종목만 조용히 죽지 않고 원인이 로그(`entry_params.py:76` `log.warning(... %s failed: %s)`)에 명확히 드러남.

### 3. `store.insert_entry_params` 수정
서두에서 `norm = _normalize_entry_params(result)` 호출, INSERT 컬럼·VALUES 에 신규 5컬럼 추가, 모든 값은 `norm[...]` 에서(하드인덱싱 제거). `llm_meta`·`trigger_evaluation_at`·`prior_classification_at` 인자는 그대로.

### 4. dry-run 정규화 검증 — `entry_params.py`
dry-run 분기(`:95-97`)는 INSERT 를 건너뛰되, `return` 전에 `_normalize_entry_params(result)` 를 호출해 **§9 정합을 검증**하고 정규화된 진입 plan 을 로그한다(insert 는 여전히 skip). → dry-run 이 실제 계약을 실행하므로 앞으로 §9↔store 가 어긋나면 dry-run 에서 즉시 드러난다(현재처럼 조용히 0행 되는 일 차단). mock 이 §9 형태이므로 이 검증을 통과한다.

### 5. mock `_mock_calculate_entry_params` → §9 스키마
출력 키를 §9 로 교체: `entry_mode, pivot_price, trigger_price, current_price, stop_loss_price, stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, suggested_weight_pct, expected_target_price, expected_target_pct, pattern_basis, entry_window_days, max_chase_pct_from_pivot, breakout_volume_requirement, observed_breakout_volume_ratio, known_warnings, other_warnings, notes`. 코드 전용 키(entry_price/stop_loss/risk_reward_ratio/position_size_pct/position_size_basis/stop_loss_basis) 제거. → dry-run 이 정규화 계층을 실제로 통과(버그를 가렸던 원인 제거).

## 데이터 흐름

LLM(§9) → `_normalize_entry_params`(매핑·계산·검증) → `insert_entry_params` INSERT(신규 5컬럼 포함) → entry_params 행 저장. 이후 `performance.py` 가 그 행의 entry_price(=trigger_price, non-null)로 백테스트, `slack.notify_signal` 알림.

## 에러 처리 / 영향 평가 (검증)

- 정규화 검증 실패 → 그 종목 실패하되 로그 명확(조용한 0행 방지).
- `signals.py:27` (유일 활성 API 소비자): **명시 컬럼 SELECT(r[0..16], 신규 5컬럼 미포함)** → 무영향. `entry_price=float(r[7])`·`stop_loss=float(r[8])` 가 NULL 비보호인데, 정규화가 entry_price=trigger_price·stop_loss=stop_loss_price 로 **non-null 보장** → 안전(현재 0행이라 어차피 빈 응답).
- `performance.py`·`slack.py`·web(정적 문서): 무변경, 수정 후 비로소 정상 동작.
- 5 신규 컬럼은 **끝에 append** → positional 위험 없음.

## 테스트

- **`_normalize_entry_params` 단위**: ① 리네임(stop_loss_price→stop_loss, suggested_weight_pct→position_size_pct) ② risk_reward 계산(목표20/손절6.9→≈2.9; 분모 0→None; **범위초과(예 손절0.01)→None**) ③ entry_price==trigger_price ④ 신규 5필드 통과 ⑤ basis None ⑥ **필수 §9 키 누락 시 ValueError**(키별).
- **store INSERT 라운드트립**(db fixture, 결정적): §9-shape mock(또는 `_mock_calculate_entry_params` 출력)을 `insert_entry_params(conn, symbol, signal_at, result=<§9 dict>, ...)` 에 넣고 → SELECT 로 **1행 저장 + 신규 5컬럼·entry_price·stop_loss·risk_reward 값** 확인. (현재 0행 → 이 경로가 §9 출력으로 저장됨을 증명 = 0행 탈출. dry-run 은 insert 를 건너뛰므로 라운드트립은 insert 함수를 직접 호출해 검증.)
- **mock=§9 정합**: `_mock_calculate_entry_params()` 의 키 집합이 §9 필수 키를 모두 포함하고 코드 전용 키를 안 냄 → `_normalize_entry_params` 통과(KeyError/ValueError 없음).
- **회귀**: base 대비 신규 실패 0. schema.sql ALTER 가 kr_test 에 적용돼 INSERT 성공(신규 5컬럼 존재).

## 파일 변경 예상

- 변경: `schema.sql`(CREATE 5컬럼 + ALTER ×5), `store.py`(`_normalize_entry_params` 신규 + `insert_entry_params` 수정), `claude_cli.py`(mock §9 교체), `entry_params.py`(dry-run 분기에서 `_normalize_entry_params` 검증 호출, insert 는 계속 skip).
- 무변경(검증): `signals.py`, `performance.py`, `slack.py`, `prompts/calculate_entry_params_v2_0.md`, web.
- 테스트: `tests/` 에 normalize 단위 + insert 라운드트립(결정적).

## 후속 (별도 후보)

- 신규 5컬럼을 `signals.py`/web 에 노출.
- pivot/stop/target sanity 검증(stop<entry<target 등).
- entry_price intraday 보정(현재 = trigger_price 단순).
