# breakout_from_watch — watch 정당한 돌파 누락 갭 해소 (검증/귀속)

날짜: 2026-06-08. 브랜치: `worktree-breakout-from-watch`.

## 문제 / 해법

결정론 게이트가 `breakout` 을 `classification=="entry"` 에만 발화 → 시장 사유 등으로
entry 에서 강등됐던(=pivot 유효) watch 의 거래량 동반 pivot 돌파를 최대 `promotion`
(go_now 금지)으로만 잡아, 토요일 weekend 재분류까지 정당한 돌파를 체계적으로 누락.

해법: 트리거 차단을 게이트에서 하지 않고, pivot 이 유효한 watch 사유에 한해
`breakout_from_watch` 로 LLM 정밀판정(evaluate_pivot §3.5)에 넘긴다. 추격(>pivot+5%)
방지는 게이트가 아니라 calculate_entry_params 5% 룰(`extended_from_pivot_already`)이 담당.
(시스템 원칙: loose gates, LLM/param precision.)

## 변경 파일

| 단계 | 파일 | 변경 |
|---|---|---|
| 1 | `compute/trigger_gate.py` | `breakout_from_watch` 트리거 + `fresh_cross` + `ALLOWED_WATCH_REASONS` + prev_close/watch_reason 인자. 평가순서 invalidation→entry breakout→breakout_from_watch→promotion→None |
| 5a | `load.py`, `evaluate_pivot.py` | `get_active_with_current` prev_close 조회, `get_active_monitoring` watch_reason. 게이트에 prev_close/watch_reason 전달 |
| 5b | `db/schema.sql`, `store.py` | `weekly_classification`·`classification_backfill` 에 `watch_reason VARCHAR(40)` (ALTER IF NOT EXISTS). 두 insert 에 `_watch_reason()`(watch 일 때만 저장) |
| 3 | `prompts/analyze_chart_v3.md` | §8.5 watch_reason enum + 경계(pivot 정의요소 완성) + D4 제외우선 + 스키마/제약 |
| 2 | `prompts/evaluate_pivot_trigger_v1.md` | §3.5 breakout_from_watch 케이스, §2 입력 갱신, §3.3 promotion "다음 평일 처리" 가정 정정(entry 만 참) |
| 4 | `entry_params.py`, `prompts/calculate_entry_params_v2_0.md` | 후보 SQL `trigger_type IN (breakout, breakout_from_watch)`. §7 finding-C: breakout_from_watch 의 stale `unfavorable_market_context` 미적용 |
| 5b | `compute/payload_lite.py` | build_for_5b prior_analysis 에 watch_reason |

## 의존성 맵 (threshold-change-checklist 2축) — trigger_gate 소비처 변경

thresholds.py 값 추가/변경 없음(`GATE_BREAKOUT_VOL_MULT=1.0` echo). 소비처(trigger_gate) 수정으로 맵 작성.

**1단계 파생신호**: `GATE_BREAKOUT_VOL_MULT(1.0)` → 기존 `breakout` + 신규 `breakout_from_watch`.
`GATE_PROMOTION_PRICE_RATIO(0.95)` → `promotion`(값 불변, 같은 watch 분기 공존).

**2단계 소비룰**: trigger_type 소비처 — `entry_params.py`(SQL IN 절 확장), `evaluate_pivot_trigger`
(§3.5 추가), `store.insert_trigger_log`(값만 추가, VARCHAR(20)에 19자 적합), `payload_lite`(이력).

**3단계 고정상수 2축**:

| 상수 | 축1 환산 | 축2 영향 | 책정합 | 후속 |
|---|---|---|---|---|
| `GATE_BREAKOUT_VOL_MULT=1.0` | 부분(느슨필터 설계값) | 있음(신규 트리거에도 동일 적용→발화 모집단 확대) | EXTENDS(게이트 느슨, LLM 1.4× 정밀) | echo·동일 1.0 재사용. 게이트 철학 보존, 추격은 param 5%룰 — 근거 있는 결정(B-수치 아님) |
| `GATE_PROMOTION_PRICE_RATIO=0.95` | 불가(가격비율) | 있음(상호작용: fresh_cross 면 promotion 조건 동시충족) | PRESERVES | 분기 배타: breakout_from_watch 우선·선점(결정 2). = 보정 |
| evaluate_pivot 1.4~1.5× 텍스트 | — | 있음(§3.5 동일 표준검증 재사용) | PRESERVES(O'Neil/Minervini) | 동일 텍스트 echo, §3.5 케이스만 추가 |

**소비 경계(1줄)**: `trigger_type {breakout, breakout_from_watch} → trigger_evaluation_log → entry_params SQL(go_now AND trigger_type IN(...)) → calculate_entry_params`.

## Design-judgment 귀속 (책 인용 아님 — 시스템 자체)

- `breakout_from_watch`(트리거), `watch_reason`(enum), `valid_base_awaiting_breakout`,
  `fresh_cross`(prev_close≤pivot ∧ close>pivot), `ALLOWED_WATCH_REASONS` 집합.
- **pivot 대비 ±5% 밴드 (entry/valid_base_awaiting_breakout/extended 경계)**:
  `< pivot×0.95` → valid_base_awaiting_breakout, `[pivot×0.95, pivot×1.05]` → entry,
  `> pivot×1.05` → extended. **0.95** = 게이트 promotion 임계 정합; **1.05** = 그 대칭,
  O'Neil/Minervini "pivot +5% 이내 매수" 추격 한계. "imminent within ~5 trading days" 의
  가격거리 proxy. extended 는 pivot 대비로 판정(extended_from_ma=50일선 대비와 dimension 분리).
- **marginal_tt 기준**: §2 의 "조건 통과 마진 < 3% 가 3개 이상" — 기존 §2 규칙 echo(신규 아님).
- **책 echo(신규 아님)**: 거래량 게이트 1.0×(`GATE_BREAKOUT_VOL_MULT`), 표준 돌파 1.4~1.5×(O'Neil/Minervini).

## 검증 결과

- 게이트 단위테스트: `tests/test_llm_compute_trigger_gate.py` 11→20 (신규 9, TDD).
- 통합(DB): `tests/test_breakout_from_watch_integration.py` 4 — watch_reason 저장·조회,
  prev_close, fresh ALLOWED→breakout_from_watch, base_forming→promotion, 후보 SQL IN 절.
- **전체 회귀(worktree↔main 실측)**: 양쪽 동일 **25 실패**(사전존재 baseline, 집합 diff 0),
  worktree +13 통과(신규 테스트). **net 신규 실패 0**.
- prompt-freeze/drift: `test_api_prompts_verify_frozen`·`test_pipeline_drift`·
  `test_prompt_threshold_drift` 통과. analyze_chart 추가는 SSOT-THRESHOLDS 블록 밖이라 drift 무영향.
- 스키마: `kr_pipeline`·`kr_test` 양쪽 `psql -f` 적용, `watch_reason` 컬럼 확인.

## 관문 2 — LLM replay 결과 (2026-06-08, 실제 claude 호출)

스크립트: `scripts/replay_breakout_from_watch.py`(2-A 분류), `scripts/replay_bfw_e2e.py`(2-B 평가).
build_for_5b 확장(market_context/conditions_met/conditions_detail/rs_rating, **현재 as-of 값**) 반영 후 실행.

**2-A 분류 안정성 (analyze_chart_v3, N=10):**
| 케이스 | 기대 | 실측 | 판정 |
|---|---|---|---|
| 066620 handle-미형성 cup | watch + base_forming | watch 10/10, **base_forming 10/10**, not_formed 10/10 | ✅ |
| 002810 handle-미형성 cup | watch + base_forming | watch 10/10, **base_forming 10/10** | ✅ |
| 001820 climax | ignore | ignore 9/10(+null 1), climax_run 9/10 | ✅ (≥9) |
| 005850 watch 유지 | watch | **ignore 7/watch 3** — 미달 | ⚠ stale 베이스라인(아래) |

**005850 귀속 (base vs 내 프롬프트 동일입력 비교)**: base(§8.5 없음) ignore 6/watch 3, 내 프롬프트
ignore 7/watch 3 — **통계적 동일(ignore-heavy ~67-70%)**. 불안정은 §8.5 아니라 **데이터 드리프트**
(phase2-i watch 10/10 은 옛 스냅샷; 종목 상승으로 현재 climax/ignore 경계 이동). **net 회귀 0.**
watch 일 때 watch_reason=base_forming 정확. → "005850 watch 유지" 기준은 현재 데이터에서 stale
(어느 프롬프트로도 미충족) — 회귀 아님. 후속: 안정적 watch 종목으로 재-베이스라인.

**2-B e2e (evaluate_pivot_trigger §3.5, inline payload, N=10):**
| watch_reason | 조건 | 기대 | 실측 |
|---|---|---|---|
| valid_base_awaiting_breakout | 표준검증 충족 | go_now | **go_now 10/10** ✅ |
| valid_base_awaiting_breakout | vol 1.15× | wait | **wait 10/10** ✅ |
| unfavorable_market | 시장 confirmed_uptrend | go_now | **go_now 10/10** ✅ |
| unfavorable_market | 시장 downtrend | wait | **wait 10/10** ✅ |
| marginal_tt | margin 8% (clean) | go_now | **go_now 10/10** ✅ |
| marginal_tt | margin 1.2% (<3%) | wait | **wait 10/10** ✅ |

→ 3사유 변별 60/60 결정적. 동기 사례 unfavorable_market 회복기 go_now 실증. errors 0.

## (A) build_for_5b 확장 (관문 2 중 발견 → 반영)

§3.5 unfavorable_market/marginal_tt 분기가 참조하는 입력이 기존 build_for_5b 에 없어
(market_context/conditions/rs_rating 부재) go_now 도달 불가(inert)였던 갭 발견. build_for_5b 에
`market_context`(build_market_context) + `conditions_met`/`conditions_detail`(build_minervini_detail)
+ `rs_rating` 추가(**현재 as-of**, 분류시점 스냅샷 금지). additive(기존 소비자 비파괴),
echo(신규 임계 아님). evaluate_pivot_trigger §2/§3.5 문서 동기화. drift/freeze 재검증 통과.

## 미검증 / 후속

- **LLM 분류 회귀(005850 watch, climax ignore, handle-미형성 cup→base_forming)**: analyze_chart_v3
  §8.5 추가가 LLM 의 entry/watch/ignore 결정을 흔들지 않는지는 *replay 검증 하네스(live LLM 호출)*
  필요 — 본 작업에서 미실행. 머지 전 replay 권장. (정적 검토: §8.5 는 분류 기준이 아니라
  *사유 태깅* + 임박 경계 명료화로 추가적이나, 5% 임박 proxy 가 경계 entry↔watch 를 미세 이동시킬
  여지 있어 replay 로 확인 필요.)
- web UI `LlmPipelinePage.tsx` 트리거 매트릭스에 breakout_from_watch 미반영(설명 문서 — 범위 밖).
- 백필 종목 watch_reason=NULL 하위호환: breakout_from_watch 비대상(promotion 유지)으로 안전.
