# LLM 모델 A/B — Opus 4.8 vs Sonnet 4.6 (단계별)

> **평가 하네스 미보존 안내**: 본 평가에 쓴 스크립트(`scripts/replay_breakout_from_watch.py`·
> `replay_bfw_e2e.py`·`replay_entryparams_ab.py`)와 `call_claude(model=...)` 파라미터는
> 평가 전용 worktree 와 함께 폐기됨(미커밋). 이 문서는 **결과·결론 보존용**. 향후 단계별 모델
> 전환을 실제 반영하려면 `claude_cli.call_claude` 에 `--model` 배선을 다시 추가해야 함
> (단계 2 evaluate_pivot 만 Sonnet 후보 — 아래 종합 판정).

날짜: 2026-06-09. 브랜치: `worktree-breakout-from-watch`(§8.5/§3.5/build_for_5b 반영본).
목적: 세 프롬프트에서 Sonnet 4.6 이 Opus 4.8 과 동등한지 동일입력 A/B 로 측정 → 단계별 모델 결정.
⚠ 평가 전용 — 운영 config 미변경. 하니스: `call_claude(model=...)` (default None=운영 불변),
replay 스크립트 `--model`.

모델: Opus 4.8 = `claude-opus-4-8`(baseline) / Sonnet 4.6 = `claude-sonnet-4-6`.

---

## 단계 1 — calculate_entry_params (N=10, inline build_for_6 payload)

| 케이스 | 지표 | Opus 4.8 | Sonnet 4.6 | 판정 |
|---|---|---|---|---|
| flat_base_clean | trigger/stop/target/size/chase | 80080 / 74400 / 96000 / **10.0** / 5.0 | 동일 (전부 일정) | ✅ 일치 |
| cup_handle_clean | 〃 + warnings | 80080 / 74400 / 96000 / **10.0** / 5.0 (+absolute_stop_used, stop_distance) | 동일 | ✅ 일치 |
| late_stage_flag | suggested_weight_pct | **4.9 (10/10 일정)** | **4.9~7.0 (mean 6.16; 4.9×4 / 7.0×6)** | ❌ 분기 |
| 전체 | parse_fail / schema_violation | 0 / 0 | 0 / 0 | ✅ |

**판정: clean pass 아님 (Opus 유지 권고).**
- 가격류(trigger/stop/target ±0%), clean 케이스 size, chase clamp(5.0), JSON parse(0), schema(0)
  는 Sonnet 이 Opus 와 **완전 동일** — 기계적 산출은 동등.
- 그러나 **`late_stage_base` 리스크플래그의 size×0.7 보수화를 Sonnet 은 6/10 에서 미적용**(7.0 유지),
  Opus 는 4.9 로 10/10 결정적. = 안전 관련 보수화의 *적용 신뢰성*이 Sonnet 에서 불안정 →
  "position_size 동일 버킷" 기준 미충족. 리스크플래그가 흔한 운영 특성상 비-사소.

---

## 단계 2 — evaluate_pivot_trigger §3.5 (N=10, inline payload)

| 케이스 | 기대 | Opus 4.8 | Sonnet 4.6 | 판정 |
|---|---|---|---|---|
| valid_base_strong | go_now | go_now 10/10 | go_now 10/10 | ✅ |
| valid_base_weak | wait | wait 10/10 | wait 10/10 | ✅ |
| unfav_recovered | go_now | go_now 10/10 | go_now 10/10 | ✅ |
| unfav_still_down | wait | wait 10/10 | wait 10/10 | ✅ |
| marginal_clean | go_now | go_now 10/10 | go_now 10/10 | ✅ |
| marginal_remains | wait | wait 10/10 | wait 10/10 | ✅ |
| 전체 | — | 60/60, errors 0 | 60/60, errors 0 | ✅ |

**판정: clean PASS (Sonnet 전환 후보).** Sonnet 이 3사유 go_now/wait 변별을 Opus 와 동일하게
60/60 재현, parse 실패 0. 동기 사례 unfavorable_market 회복/미회복 분기도 정확.

---

## 단계 3 — analyze_chart_v3 (N=5 스크리닝, 이미지 패널; 비용상 N=10 미실행)

| 케이스 | 기대 | Opus 4.8 (errors) | Sonnet 4.6 (errors) | 일치 |
|---|---|---|---|---|
| 001820 climax | ignore | **ignore 5/5** (err 0), climax_flag 5 | **ignore 5/5** (err 0), climax_flag 5 | ✅ modal 일치 |
| 066620 handle-미형성 | watch+base_forming | watch 4/ignore 1, **base_forming 4/5** (err 0) | **watch 5/5, base_forming 5/5** (err 0) | ✅ (Sonnet 더 깨끗) |
| 002810 handle-미형성 | watch+base_forming | **watch 5/5, base_forming 5/5** (err 0) | **errors 4/5** → valid 1: watch(reason=valid_base_awaiting_breakout) | ⚠ 데이터 부족·1건 reason 불일치 |
| 005850 (agreement-only) | — | none 4/cup 1 (불안정, err 0) | **errors 3/5** → valid 2: watch | △ 둘 다 불안정 |
| **호출 실패 합계** | — | **0 / 20** | **7 / 20 (35%)** | ❌ |

**판정: clean pass 아님 (Opus 유지 권고).**
- **유효 응답에서 modal classification 은 일치**: 001820 ignore(=Opus), 066620 base_forming(5/5,
  Opus 4/5보다 깨끗). 분류 *품질* 자체는 성공 호출 한정 동등해 보임.
- **그러나 Sonnet 호출 실패율 35%(7/20) vs Opus 0%** — "parse/실패율 ≤ Opus" 기준 명확 미달.
  005850·002810 은 유효 표본이 2건·1건으로 줄어 base_forming 재현 확인 불가(002810 유효 1건은
  reason 이 valid_base_awaiting_breakout 로 불일치).
- ⚠ **caveat (귀속)**: 7건 실패는 JSON 파싱 실패가 아니라 **이미지 호출 600s 타임아웃 후 3회 재시도
  소진(`_ERROR`)** = 인프라성. Opus 런(직전, 0실패)과 달리 Sonnet 런에서 집중 발생 — 원인이
  모델 처리지연인지 일시적 API 혼잡인지 1회 측정으론 단정 불가. **재측정(다른 시간대 N=10) 시
  실패율 재확인 권고.** 단, 본 A/B 측정값으로는 기준 미달.

---

## 종합 판정 / 전환 권고

| 단계 | Opus 대비 결과 | 전환 권고 |
|---|---|---|
| 1. calculate_entry_params | 가격/clean/schema/parse 동일, **late_stage 보수화 6/10 누락** | **Opus 유지** (안전 보수화 신뢰성 미달) |
| 2. evaluate_pivot_trigger | **60/60 완전 동일**, parse 0 | **Sonnet 전환 후보** ✅ |
| 3. analyze_chart_v3 | 유효 응답 modal 일치하나 **호출 실패 35% vs 0%** | **Opus 유지** (재측정 후 재검토) |

**결론**: 세 단계 중 **단계 2(evaluate_pivot_trigger)만 Sonnet 전환 후보** — 텍스트 전용·경량·빈번
호출이라 품질 손실 0(60/60)으로 비용 절감 이점. 단계 1(안전 사이징)·단계 3(분류, 보수적 단계)은
Opus 유지. 단계 3 실패율은 인프라성 가능성 있어 다른 시간대 N=10 재측정으로 재확인 권장.

**운영 반영(별도 작업)**: 전환 결정 시 `call_claude(model=...)` 를 단계별 호출부에 배선
(evaluate_pivot.py 만 `model="claude-sonnet-4-6"`). 본 평가에서는 운영 config 미변경.

---

## 종합 판정 / 전환 권고

(단계별 결과 종합 후 작성)
