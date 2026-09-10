> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# #161 — 구조 저점 손절 참조: Phase A 사실·판정·보류(2026-09-10)

> 코드·상수·문서 변경 0(본 기록 문서만). LLM 0. 판정은 전문가(원칙 2-2), 사실은 CC 조사.
> 상태: **보류(deferred)** — wake trigger = **#175 와 동일 조건(P0 완료 + go_now ≥ 20 축적)** 후 재개 검토(2026-09-10 갱신 — #175 도 보류됨).
> #175 Phase A 결과(기존 결정론 핸들 검출기 조사·판정·보류): `docs/superpowers/plans/2026-09-10-issue175-structural-low-output.md`.

## 0. 판정(전문가, 2026-09-10)

- 현행 고정 8%(매입가 기준, `TRADE_STOP_INITIAL_PCT`)는 book **상한**(HMMS 7~8% / TTLC ≤10%)의 일률
  적용으로 **위반 아님**. 구조 손절(패턴별 지지 저점)은 책이 선호하는 참조점이나, 상한 이내 고정값은
  허용 범위 내 **설계 선택**(governance 3-5 book-fidelity 교정 대상 아님).
- "진입 부적합"(핸들 깊이 > 12% → faulty → watch)은 A 프롬프트 §4 Gate3 에 **기구현** 확인 → #161 범위에
  추가할 것 없음.
- 갈래 판정 원문(전문가 회신, 2026-09-10 — 원칙 1-2 원문 보존):
  - **갈래 1 — 결정론으로 가능한 것만**(플랫베이스 base_low + 포켓피봇 PP저점). 책 참조점이 정확히
    존재하고 결정론. 손절 = 구조저점×0.995 와 −8% 중 덜 깊은 쪽. 크기 = 1.25% ÷ 실제 손절폭(상한 25%).
    저장본 영향 범위: 플랫베이스 24행·PP 13행. 백테스트·시그널·관리 동시. cwh·VCP 는 8% 유지 → 신규
    출력(#175) 의존. **방법론 세션 권고안이었음.**
  - **갈래 2 — LLM 보고 % 기반 손절**(`measurements.handle_depth_pct` 로 핸들 저점 역산): 손절가에 LLM
    변동성 유입으로 **채택 불가**.
  - **갈래 3 — 보류.** 진입 부적합 기구현, 구조 손절 실효 범위 소(cwh ~19%·flat ~33%), go_now 0건으로
    production 영향 0. 구조 저점 출력(#175) 확보 후 재개.
  - **사용자 결정: 갈래 3 채택(2026-09-10), #175 등록.**
- 재개 시 즉시 구현 가능: **flat_base(base_low = 베이스 저점 자체)·pocket pivot(PP일 저점·SMA50, 일봉에서
  결정론 산출)**. cwh·VCP·3C 는 신규 출력(handle_low·last_contraction_low·cheat_low)에 의존.

## 1. 책 근거(확정, 전문가)

손절 참조점 = 패턴별 지지 저점: 핸들 저점(cup w/ handle, HMMS) / 베이스 저점(flat base, 조정 ≤10~15%) /
마지막 수축 저점(VCP, TLSMW) / cheat 저점(3C) / PP일 저점·SMA50(pocket pivot). **컵 바닥(base_low)은 어느
저자도 손절 참조로 쓰지 않음**(컵 깊이 12~33% 정상). 상한: 매입가 −8%(HMMS), Minervini ≤10%. 진입 부적합:
핸들 깊이 > 8~12% = improper(HMMS) [book-mandated, 값은 범위 내 design].

## 2. Phase A 사실(2026-09-10 회신)

### A1. A 프롬프트 가격 수준 출력 필드

| 필드 | 존재 | 정의(§) | 패턴별 산출 | 저장 컬럼 |
|---|---|---|---|---|
| pivot_price / pivot_basis | 있음 | §4.7 표(패턴별 기준 고점 + 0.1) | 전 패턴(none·ignore null) | weekly_classification.pivot_price·pivot_basis |
| base_high / base_low / base_depth_pct / base_start_date | 있음 | §4.7 "베이스 구간의 high/low" | 전 패턴 공통(패턴별 구분 없음) | 동명 컬럼 |
| handle_high | 없음(파생) | cwh 는 pivot_basis=handle_high → pivot − 0.1 | cwh | 없음 |
| handle_low | **없음** | — | — | 없음 |
| handle_depth_pct | 있음(% 만, LLM 보고) | §4 measurements | cwh | measurements JSONB |
| contraction_low | **없음** | contraction_depths_pct(%) 배열만 | vcp | measurements JSONB |
| cheat_low | **없음** | 3c_cheat 는 pivot_basis=cheat_pivot(고점)만 | — | 없음 |
| PP일 저점 | 없음(출력 아님) | 구 calc 가 daily low 로 계산 | — | 없음 |

§4.7 원문: "stop_loss 출력 안 함 — (6) 가 base_low + pivot 받아서 산출", "3c_cheat refinement 안 함".

### A2. (pivot − base_low)/pivot 분포 — weekly_classification entry/watch 유효 253행

| 패턴 | n | Q1 | 중앙 | Q3 | ≤8% | ≤12% |
|---|---|---|---|---|---|---|
| cup_with_handle | 150 | 18.3 | 21.8 | 30.1 | 0.7% | 3.3% |
| cup_without_handle | 68 | 21.7 | 25.9 | 30.0 | 0 | 0 |
| flat_base | 24 | 3.5 | 10.8 | 13.6 | 33.3% | 70.8% |
| double_bottom | 6 | 19.7 | 25.0 | 28.1 | 0 | 0 |
| vcp | 5 | 19.2 | 23.2 | 27.2 | 0 | 0 |

3c_cheat 저장 행 0. pocket_pivot 은 entry_mode(trigger log 13행). backtest_classification(2021~24): cwh 1,312행
중앙 22.4%(≤8% 0.9%·≤12% 5.2%), flat_base 416행 중앙 12.0%(≤8% 19.0%·≤12% 50.5%).

### A3. 구 logical 스탑 정의(plan #153 §2 보존)와 logical binding 행

```
pivot_breakout: logical = (base_low × 0.995 − pivot)/pivot × 100; binding = logical if > absolute(−7.0/−5.5)
                clamp [−10.0, −5.0], 경고 absolute_stop_used_due_to_wide_handle (logical < −10)
pocket_pivot:   logical = (PP_low × 0.995 − pivot)/pivot; binding = max(sma50, logical, absolute)
```
09-08 표는 미저장 → 구 calc(ea814dd) 로 trigger_evaluation_log 전 행 재계산(스크래치패드 a3_rows.json;
build_for_6 가 최신 분류를 읽어 스냅샷과 불일치 가능): 197행 중 calc 135(absolute 116·logical 19). 09-07
이전 128행: absolute 110·logical 18. **pivot_breakout logical 8행** = 002810 ×7(cwh, 거리 6.24%, flags
handle_quality·narrow_base) + 230360 ×1(3.37%). pocket_pivot logical 10행(PP_low 기준, base_low 거리 12.1~25.7%).

### A4. 백테스트 참조 경로

WatchRow = backtest_classification 의 pivot_price·base_low·watch_reason. base_low 는 trigger gate invalidation
(close < base_low)에만 사용, 포지션 스탑은 avg × (1 − 8%). measurements JSONB 동일 테이블 → handle_depth_pct
는 SELECT 추가만으로 참조 가능. 가격 저점(handle_low 등)은 어느 테이블에도 없음 → 출력 신설 전 참조 불가.

### A5. 관리 경로

entry_params 에 base_low·handle_low 없음(pivot_price·stop_loss·stop_loss_basis·pattern_basis 만). #162 링크로
넘기려면 entry_params 컬럼 신설 필요. 대안: entry_params.prior_classification_at 로 weekly_classification 조인.

### A6. 핸들 깊이

가격 기반(handle_high − handle_low) **불가**(출력 없음). 대체 2종:

| 원천 | 대상 | n | 중앙 | Q3 | >8% | >12% |
|---|---|---|---|---|---|---|
| LLM 보고 measurements.handle_depth_pct | cwh entry/watch 225행 | 113 | 12.1 | 16.8 | 81.4% | 51.3% |
| 결정론 compute_handle_quality(gates.py — 룰 발화 시만 triggered_rules 에 handle_high/low 저장) | 발화 36행 | 36 | 11.6 | 14.7 | 58.3% | 36.1% |

결정론 값은 핸들 길이 중앙 25일, 표본에 4~9월 5개월짜리 "핸들" 존재 — heuristic 창 한계. backtest cwh 2,350행:
값 1,039, >8% 761(73.2%), >12% 396(38.1%).

### A7. 현 프롬프트 규범(있음)

§4 Handle quality(HMMS p.116 8~12%·10주선 위·상단 절반·wedging), §4 Gate3(적법 = 길이 ≥5일 ∧ 상단절반 ∧ 50일선
위 ∧ down drift ∧ 깊이 ≤HANDLE_DEPTH_BULL_MAX_PCT 12% / faulty → handle_status=faulty·risk_flags handle_quality·
watch, faulty→none 금지), risk_flags `handle_quality`·`faulty_pivot`, 컵 깊이 33/50/하드캡 50, flat_base ≤15%.
상수: HANDLE_DEPTH_BULL_MIN/MAX 8/12 [book-anchor], HANDLE_LEGIT_MIN_DAYS 5, HANDLE_DEEP_RATIO 0.33 [heuristic,
책과 reconcile 미완], CUP_DEPTH_MAX 33/50, FLAT_BASE_DEPTH_MAX 15.

## 3. 관측 기록(판정 아님 — #161 범위 밖, governance 3-3)

- cwh 225행 handle_status: faulty 89 · legitimate 24 · not_formed 92 · null 20.
- HANDLE_DEEP_RATIO 0.33 [heuristic] 은 책 8~12% 절대치와 reconcile 미완(thresholds docstring 자기 표기) —
  핸들 판정 검토 여지. 기록만.

## 4. 후속(착수 금지)

- **#175** 패턴별 구조 저점 가격 출력 신설(handle_low·last_contraction_low·cheat_low) — #161 전제.
  설계 갈래 (a) LLM 출력 / (b) 결정론 산출(compute_handle_quality 확장) / (c) 혼합(LLM 구간 날짜 → 코드 저점
  가격) — 판정 대기, (c) 가 governance 4-1 취지에 가장 부합할 가능성.
- #174 계좌 자본·매수 웹 폼(제품 기능), #165 시장 국면 전환.
