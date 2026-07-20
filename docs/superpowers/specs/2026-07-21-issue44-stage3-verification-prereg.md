# 사전등록 — Stage3(D4) climax/topping 결정론 게이트 재생 검증 + T4 민감도 + 제3안 카운터 (#44 Task 8)

2026-07-21. 측정 실행 **전에** 지표 정의·해석 밴드를 고정한다(사후 해석 방지 관례 —
`docs/superpowers/specs/2026-07-20-issue44-e1-indeterminacy-prereg.md` 와 동일 형식).

근거: `docs/superpowers/plans/2026-07-20-issue44-climax-topping-migration.md` D4
("검증은 0단계 방법론 + D5 규약별 민감도 + 제3안 발생률 카운터. 소급 재분류 없음") +
D3(강제율 상한 사전등록 + 활성화 유예) + D5①(T4 창 규약 "Task 8 민감도 후 확정") 이행.

## 1. 원칙

- **LLM 재실행 0회** — `find_anchor` / `compute_climax_gates` / `compute_topping_gates`
  (순수 함수, `kr_pipeline/llm_runner/compute/climax_topping.py`)만 재생한다.
- production DB(`kr_pipeline`)는 **read-only**(SELECT 만) — 재생은 DB 에 아무것도 쓰지 않는다.
- 재생 산출물을 기존 LLM 산출물(`classification`)과 대조하되 **소급 재분류는 하지
  않는다**(D4 명시). 대조는 정합률 측정 목적에 한정.
- 데이터 구성은 production 경로(`api.services.payload_builder`)의 비공개 헬퍼를
  그대로 import 해 재사용한다(`_fetch_weekly_full` / `_fetch_daily_ohlcv` /
  `_fetch_indicators_recent` / `_dist_count_25s`) — 이 리포 관례상 허용(0단계 선례:
  `scripts/stage0_replay_5b_gates.py` 가 `kr_pipeline.llm_runner.compute.payload_lite`
  등 내부 함수를 동일하게 재사용).

## 2. 모집단

- 대상 테이블: `backtest_classification` 의 **(symbol, analyzed_for_date) 전 행**.
  실측 확인(2026-07-21, read-only): **4,252건 · 214종목 · 2021-01-02~2024-12-28**.
  classification 분포 참고: ignore 273 / entry 15 / watch 3,964.
- 각 행에 대해 `on_date = analyzed_for_date` 로 production 과 동일하게:
  - `weekly_full = _fetch_weekly_full(conn, symbol, on_date)` (전 이력, zero-bar 제외)
  - `daily60 = _fetch_daily_ohlcv(conn, symbol, on_date, days=60)`, `daily20 = daily60[-20:]`
    (`compute_climax_gates` 가 소비하는 것과 동일한 슬라이스)
  - `ind60 = _fetch_indicators_recent(conn, symbol, on_date, days=60)` → `_dist_count_25s(ind60)`
  - `anchor = find_anchor(weekly_full)`
  - `climax = compute_climax_gates(weekly_full, daily20, anchor)`
  - `topping = compute_topping_gates(weekly_full, dist_count_25s, anchor)`
- DB 조회 실패/예외 건은 `build_errors` 로 유형별 계수하고 분모에서 제외
  (`rows_replayed_ok` 로 별도 보고 — 0단계 관례).

## 3. 지표 (측정 전 고정)

### ① §6.1 발화 후보율 (E1 미고려 — 상한 추정)

- P1 = `maturity_ok is True`, P2 = `p2_accel_ok is True`,
  트리거 = `t1_max_spread_now / t2_max_volume_now / t3_gap_up_today / t4_ok`(max variant)
  중 하나라도 `True`, scope = `scope_active is True`.
- **candidate** = P1 ∧ P2 ∧ 트리거≥1 ∧ scope 전부 성립(quality_flag=True 행은
  p2_accel_ok/scope_active 가 애초에 None 이라 자동 제외 — §5 한계 참조).
- rate = `|candidate| / rows_replayed_ok`. candidate 건의 기존 `classification` 분포(③) 병기.

### ② §6.2 발화율(G0+T-B / G0+T-D분배일 분지별)

- G0 = `g0_below_10w is True`, TB = `tb_ok is True`, TD = `td_dist_ok is True`,
  품질 = `quality_flag(topping) is not True`.
- `branch_B` = G0 ∧ 품질 ∧ TB. `branch_D` = G0 ∧ 품질 ∧ TD.
  `branch_either` = G0 ∧ 품질 ∧ (TB ∨ TD).
- **would_force**(강제율 — `gates.py` 의 `6_2_topping_shadow` 자격 조건과 동일 재현) =
  `branch_either ∧ (기존 classification != 'ignore')`. rate = `|would_force| / rows_replayed_ok`.
  (기존 classification=='ignore' 인 행은 강등해도 의미 없어 gates.py 가 이미 제외 — D3 조건 그대로.)

### ③ 게이트 발화 건의 기존 LLM 분류 분포 (패턴 판정 — 건별 비교 아님)

- `candidate`(①) 집합과 `branch_either`(②) 집합 각각에서 기존 `classification`
  (entry/watch/ignore) 분포를 집계. `branch_either` 에 대해서는 **ignore 정합률**
  (`classification=='ignore'` 비율)을 별도 산출 — 해석 밴드(§4)의 판정 대상.

### ④ anchor 안정성

- **표본**: 전 4,252행 중 무작위 500행(`random.Random(seed=44).sample` — 재현 가능,
  재생 성공 건 모집단에서 추출).
- 표본 각 행에 대해 `weekly_full` 을 **독립적으로 2회 재조회**(DB 왕복 2회) 후
  `find_anchor` 를 각각 실행 → 두 결과 dict 완전 일치 여부. 불일치 0건 = 결정론 확인.
- **anchor 연령 분포**: `baseline=="anchored"` 인 행의 `weeks_since` 로 min/p25/p50/p75/max.

### ⑤ T4 민감도 (D5① 확정 대상)

- **max variant**(현재 구현) = `compute_climax_gates` 가 반환하는 `t4_ok`
  (종점 고정, 길이 7~15 전부 검사한 상승일 비율의 max ≥ `CLIMAX_UP_DAYS_PCT`).
- **고정 10일 variant** = 동일 `daily20` 입력에서 trailing 정확히 10거래일
  (`CLIMAX_UP_DAYS_WINDOW_MIN`=7·`MAX`=15 사이의 단일 값 10 채택 — 두 경계의 중간,
  현재 max 스캔 범위에 포함되는 값)의 상승일 비율 ≥ `CLIMAX_UP_DAYS_PCT`(70%).
  상승일 비교 가능 일수(`len(daily20)-1`) < 10 이면 None(데이터 부족).
- 두 variant 각각 발화율 = `true / (true + false)`(None 제외 분모) + **발화율 차이(%p)**.

### ⑥ left_censored / no_transition / anchored 비율

- `anchor` 의 세 baseline 모드 분포(`rows_replayed_ok` 분모).

### 품질 분리 집계 (한계 대응 — 이슈 #49)

- `quality_flag`(climax) / `quality_flag`(topping) 각각 True/False 비율을 전체
  모집단 기준으로 별도 보고(adj 품질 영향을 발화율 지표와 분리 — §5).

## 4. 해석 밴드 (측정 전 등록)

- **§6.2 ignore 정합률**(③, `branch_either` 대상): **≥60% = 정합(통과)** /
  **30~60% = 규약 재검토 신호** / **<30% = 게이트 결함 의심(구현 재검토)**.
- **§6.1 후보율**(①) **>30% = 과발화 의심**.
- **anchor 재실행 불일치**(④) **>0건 = 실패(결정론 위반)** — 즉시 조사 대상(코드 버그
  또는 DB 비결정 소스, 예: 동일 시각 read 사이의 데이터 변경).
- **T4 확정 규칙**(⑤): 두 variant 발화율 차이 **<2%p → max 채택**(D5① 잠정안 유지,
  이 사전등록으로 확정) / **≥2%p → 양쪽 수치를 보고하고 확정을 사용자 결정으로 이관**
  (이 문서는 판정하지 않음 — §7 에 "사용자 결정 대기"로 명시).
- **강제율(would_force) 상한 등록**: `6_2_topping_shadow` 활성화 시 예상 강제율
  **상한 5%**. 측정치가 5% 초과 시 게이트/프롬프트 재검토 경보(구현 결함 또는 T-B/T-D
  임계 재검토 신호) — **단, 활성화 자체(shadow→실제 강등 전환)는 이 계획 범위 밖이며
  이 사전등록은 그 결정을 유예한다**(D3 그대로).

## 5. 한계 (측정 전 명시)

- **E1 미고려**: base 카운트 판정(P1 후기 완화 12주·E1 자체)은 LLM 잔류(D2)라 재생이
  반영할 수 없다. ①의 §6.1 후보율은 **실제 LLM 발화의 상한**이다 — E1 이 판정 불능이거나
  base 카운트가 조건을 깨면 후보라도 실발화하지 않는다.
- **adj 품질(#49) 영향**: quality_flag=True 인 행은 해당 게이트가 애초에 None 이 되어
  후보/발화 집합에서 자연 제외된다(별도 필터 불필요) — 다만 quality_flag 비율 자체를
  병기해 모집단 중 얼마가 판정 대상에서 원천 제외됐는지 투명화한다(품질 방향 왜곡과
  게이트 설계 결함을 구분하기 위함).
- 재생은 트리거 재생(0단계)이 아니라 **게이트 산술 재생**이므로 0단계의 abort 체인
  미시뮬레이션 한계는 적용되지 않는다(관련 없음, 명시적으로 배제).
- ③ 정합률은 **패턴 판정**(집합 단위 분포 비교)이며 건별로 "같은 근거로 ignore 를
  냈는가"를 확인하지 않는다(reasoning 텍스트 미검사 — E1 prereg 의 M4 류 텍스트
  판독과는 별개 측정).
- ④ anchor 안정성은 순수 함수 실행이라 이론상 100% 확실하지만, DB 왕복 재조회를
  포함해 "입력 재구성부터" 검증한다(코드 결정론뿐 아니라 조회 결정론도 포함).

## 6. 절차

1. 이 문서 커밋(측정 전 고정 증빙) → 2. `scripts/stage3_replay_climax_topping.py`
   실행(read-only) → 3. 결과를 이 문서 **§8 에 append**(본문 §1~7 무수정) + 밴드 적용
   판정 기술(T4 ≥2%p 갈림이면 "사용자 결정 대기"로 명시) → 4. 커밋(스크립트+결과+append,
   명시 경로·이슈 본문만·트레일러 금지).

## 7. 제3안(watch_reason) 발생률 — 실전 관측 지표 등록 (이 태스크에서 측정하지 않음)

- **백테스트 재생으로 측정 불가한 사유**: `backtest_classification` 은 Task 9(프롬프트
  §8.5 enum 개정) **이전** LLM 산출물이라 `watch_reason='suspected_climax_stage_indeterminate'`
  가 원천적으로 존재할 수 없다. 실측 확인(2026-07-21, read-only):
  현재 `watch_reason` 분포는 `base_forming`(2,614) / `extended`(844) /
  `unfavorable_market`(402) / `NULL`(290) / `valid_base_awaiting_breakout`(71) /
  `marginal_tt`(31) 6종뿐 — 해당 값 0건.
- **LLM 재실행 금지 규약**(E1 prereg §1 과 동일 원칙) — 소급 재실행으로 이 값을
  인위적으로 만들어내지 않는다. 제3안 발생률은 **실전 관측 지표**로만 등록한다.
- **실전 전환 후 집계 절차** (Task 9 배포 이후 적용):
  1. `weekly_classification`(및 `classification_backfill`)에서 배포일(`deployed_at`)
     이후 분류만 대상으로:
     `count(*) FILTER (WHERE watch_reason='suspected_climax_stage_indeterminate')
      / count(*) FILTER (WHERE classified_at >= deployed_at)` 를 주 단위로 집계.
  2. `verdict_original`(Task 7) 과 대조해 제3안이 실제로 promotion 을 막았는지
     (trigger_gate.ALLOWED_WATCH_REASONS 비포함 하드블록 작동 여부)도 병기.
  3. 판독 밴드는 **이 문서가 사전 확정하지 않는다** — 실전 트리거·전제 충족 분포가
     백테스트 모집단과 다를 수 있어 사전 등록이 무의미하다. 최초 4주 관측치를
     기준선으로 삼아 **별도 후속 사전등록**에서 밴드를 확정한다(이 계획 범위 밖).

---
