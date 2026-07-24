# #74 cup_without_handle 수용 — 구현 스펙 + 의존성 맵 (2026-07-24)

> **상태: 승인 — 구현 착수 (2026-07-24 사용자 게이트)** — 독립 설계 리뷰
> + 스펙 재검토(차단 2·자체 1·권고 8 반영) 완료본. 준거: 이슈 #74(외부
> red-team A 권고, 사용자 확정 07-22) + 독립 리뷰 2회(07-24).
> 관례: TDD·구현 후 독립 리뷰·머지 게이트. **배포 원자성: 프롬프트+코드+
> web 동기를 단일 PR 로 원자 배포**(프롬프트 선행 배포 시 보수 장치 없이
> 라이브 노출 — 금지).

## 1. 변경 요약 (6항)

| # | 항목 | 위치 |
|---|---|---|
| 1 | taxonomy `cup_without_handle` 신설 | prompt §4·§4.7·§8.6·§9 + store `_PIVOT_TABLE_BASES` + web 동기 |
| 2 | Gate3 분기: 컵 완성+핸들<5일 → 신 패턴 | prompt §4 Gate3·§8.5 |
| 3 | strict 1.5× 돌파 거래량 (결정론 인터셉트) | `evaluate_pivot.py` (#45 전례) |
| 4 | 사이징: flag `no_handle_shakeout_absent` ×0.7 | `entry_params_calc.py` |
| 5 | 이중 진입 방지 (상향 트리거 한정) | `evaluate_pivot.py` + `trade_management.store` |
| 6 | 사전등록 F1~F4 (원문 불변) + 측정 규약 부록 | 본 문서 §6 |

## 2. taxonomy·Gate3 (리뷰 차단③ 해소 — 경계 정량화)

- **§4 정의 블록**: 컵 기준은 cup_with_handle 과 동일(U자·7~45주·depth
  ≤CUP_DEPTH_MAX(33%)/베어 회복 50%·선행상승 ≥30%) — 핸들 요소 없음.
  태그: **book-mandated** (HMMS 5대 모델 장 — cup-without-handle 명명 실재).
  Gate2 V자 배제는 **완화 없이 그대로 적용**(변경 없음).
- **Gate3 재분기** (길이 우선 규칙 유지, :165 대체):
  - 핸들 ≥ HANDLE_LEGIT_MIN_DAYS(5일) → `cup_with_handle` (기존 그대로,
    pivot=handle_high — 핸들이 완성되면 그쪽이 우월 pivot)
  - 핸들 < 5일(0일 = 시도 없음 포함) + **우측 회복 완료** →
    `pattern=cup_without_handle`, pivot = **컵 내 절대 고점** + KR tick
    관례(§7). classification 은 §8.5 가격 밴드 그대로: <0.95×pivot =
    watch(`valid_base_awaiting_breakout`) / 0.95~1.05 = entry / >1.05 =
    extended. (구 :165 의 `handle_status=not_formed` + 일괄 watch 는 이
    분기에서 폐기 — 핸들 미형성이 더는 base 미완성이 아님)
  - 우측 회복 미완 → **`pattern=cup_with_handle` + `handle_status=not_formed`
    + `base_forming`** (구 :165 라벨 연속성 유지 — pattern_changed sanity·
    코호트 통계 연속, 재검토 차단 A-①).
- **우측 회복 완료 (신설 경계, design-judgment)**: 컵 바닥 이후 우측 구간의
  **최고 종가 ≥ pivot × CUP_NH_RECOVERY_MIN(0.90)** — **도달치 기준(래칫)**:
  한번 완성이면 이후 조정으로 현재가가 0.90 아래로 밀려도 완성 상태 유지,
  현재가의 위치 판정은 §8.5 가격 밴드가 담당(재검토 차단 A-③ — 주간
  flip-flop 차단). + U자 바닥 rounding 완성(LLM 형상 판정). 근거: base
  "상반부" 관례 — 핸들 정상 깊이 상한 12%(§4 handle depth)와 정합하는 상단
  존(~10%). **프롬프트 전용값**(코드 비소비) — SSOT 비등재 원칙(#19 전례),
  A↔재분류 flip-flop 은 F-부록 관측 대상.
- **:540 base_forming 재작성**(리뷰 비차단 12 + 재검토 차단 A-②):
  "cup 완성+handle 미형성" 예시를 **"cup 우측 회복 미완(최고 종가 <
  CUP_NH_RECOVERY_MIN×cup high)"** 예시로 교체(D4 우선 규칙의 앵커 유지),
  이탤릭 근거 문장은 *shakeout 부재 리스크는 배제가 아니라 보수 장치
  (§3·§4)로 흡수한다* 로 교체.
- **§4.7 pivot 표 행 추가** + `pivot_basis="cup_high"` 신설: §9 enum ·
  `store._PIVOT_TABLE_BASES` 에 등록(+tick 사후검증 적용 — 리뷰 비차단 7).
- §7 :511 대비 문장에 "cup_without_handle 은 high of the cup" 병기(비차단 6).

## 3. strict 1.5× 돌파 거래량 (리뷰 차단① 해소 — 인터셉트 지점 교정)

- **지점 = `evaluate_pivot.py` 결정론 인터셉트**(#45 extended 전례·기록
  기계 재사용): 트리거 발화(breakout·breakout_from_watch — **주말 entry
  분류분 breakout 포함**) 후, `pattern == cup_without_handle` 이고
  `volume_ratio < BREAKOUT_VOL_PREFERRED(1.5)` 면 LLM 미호출 +
  `wait_reason='volume_below_strict_no_handle'` 기록(원값 volume_ratio·
  close·pivot 동반 — F4 측정 재료). volume 또는 avg_volume_50d 결측 시
  인터셉트 **비발동**(기존 LLM 경로 — 결측을 차단 근거로 쓰지 않음, 보수는
  §6 warning 이 담당).
- **인터셉트 체인 순서: dedupe(§5) → extended(#45) → strict** —
  보유 억제분·extended 차단분이 F4 분모("strict 에서만 차단")에 오염되지
  않게(재검토 권고 3 — dedupe 최선행: 보유자에겐 extended wait 기록도 노이즈).
- grace band(1.2~1.4 wait)·1.4 floor 는 이 패턴에 **비적용**(강한 쪽 단일
  기준). 발화 임계 자체(GATE_BREAKOUT_VOL_MULT=1.0)는 불변 — 발화 후
  차단 방식(#45 동형, 보수화만).
- entry_params_calc §6: 이 패턴이면 `vol_req="ge_1.5x_strict"` 표기.
  1.4~1.5 warning 은 B 인터셉트 선행으로 도달 불가(동일 데이터) — 유지.
- 주말 A-경로 §8 :519(1.4~1.5×)에 패턴 각주 추가: cup_without_handle 은
  **돌파를 근거로 entry 판정할 때에 한해** 1.5× 미만이면 entry 로 판정하지
  말 것(재검토 권고 8 — 돌파 전 밴드 내(0.95~1.05) entry 는 §8.5 밴드
  규칙 그대로, 거래량 조건 비적용). 실매수는 B 가 막지만 A/B 서사 일관성.
- **pocket pivot 우회 차단**: `_PP_BASE_PATTERNS`·§4.5 에 cup_without_handle
  **의도적 미포함** 명기(비차단 10) — PP 시그니처로 strict 우회 불가.

## 4. 사이징 (리뷰 차단② 해소 — 수치 전제 정정)

- `calculate_entry_params` 에서 `pattern == cup_without_handle` 이면
  `no_handle_shakeout_absent` 를 raw_flags 에 **결정론 주입**(멱등).
- `_FLAG_MULT["no_handle_shakeout_absent"] = 0.7` + `_MULT_WARNING`
  (`size_reduced_due_to_no_handle_shakeout`) + `_WARNING_PRIORITY` 등록.
- **실효 사이징 = 7.0(fallback 티어) × 0.7 = 4.9pp** — 표준 경로 티어
  실물(15/10/5risky/7fallback, :37) 재확인. 정정 이력: 설계 문답 당시
  pocket 상수(10/7/5) 오인 → 사용자 결정(이중 페널티 수용, 예외 코드 없음)
  의 취지 유지·수치만 3.5→4.9pp 정정(#80 본문 동시 정정, 07-24).
- `_STANDARD_PATTERNS` 에 **추가하지 않음** — flag 상시 주입으로 no_flags
  항상 False = standard 티어 도달 불능(dead code). 사유 주석 명기(리뷰 차단②).
- `RISK_FLAGS_TAXONOMY`(§5/store) 에 **넣지 않음** — C단계 로컬 주입 전용,
  LLM 이 emit 하면 store 가 drop(현행 동작 유지). 프롬프트에 flag 명 비노출
  (비차단 8).

## 5. 이중 진입 방지 (리뷰 차단④ 해소 — 범위 한정)

- `evaluate_pivot` 의 **상향 트리거(breakout·breakout_from_watch·promotion)
  한정**: 해당 티커에 open position 존재(`trade_management.store` 조회) 시
  트리거 억제 + 억제 행 기록(`suppressed_position_held`).
  **invalidation(손절·50일선 이탈)은 억제하지 않음** — 보유자 필수 신호.
- 범위 판단: 이슈 원문은 "동일 base" 단위이나 base 식별 매칭이 취약 →
  **티커 단위 상위집합**(보수). 패턴 무관 전 종목 적용 — B v3 확정(단순
  abort·피라미딩 없음)과 정합해 보유 중 상향 재트리거는 전부 노이즈.
  이슈 스코프(동일 base) 초과분은 게이트에서 확정.

## 6. 사전등록 F1~F4 — 외부 검토 원문 (불변 등록)

```
[사전등록] cup_without_handle 수용 검증 — A 채택 시
대상: pattern=cup_without_handle 로 진입한 전체 트레이드 (코호트 태그 필수)
비교군: 동일 기간 pattern=cup_with_handle 진입
지표 (모두 저장본 1회 분석, 재실행 비교 금지):
  F1. 스탑아웃률(진입 후 8주 내): no-handle 코호트가 with-handle 대비
      +15pp 초과 OR 1.5배 초과 → 보수 장치 불충분 판정
  F2. 조기실패율: 돌파 후 +5% 미달 상태에서 pivot 하회 복귀 비율
      — with-handle 대비 2배 초과 → 판정 동일
  F3. 손실 규율: no-handle 코호트 단독으로 평균 실현손실 ≤9% /
      중앙값 <10% hard 기준 위반 → 즉시 재검토
  F4. (반대방향 오류 감지) strict 1.5× 거래량 floor 에서만 차단된
      no-handle 후보 중 이후 20%+ 상승 비율 — 과반 초과 시
      보수 장치가 과도 판정 (완화 검토, 단 F1~F3 통과 전제)
판정: F1~F3 중 어느 하나 발화 → 장치 강화(사이징 ×0.5 등) 1회 시도,
      재발화 시 B로 회귀. F1~F3 무발화 + F4 발화 → grace band 복원 검토.
표본: 최소 코호트 크기는 measurement-based 로 recall 감사 프레임에서 산정.
```

### 6.1 측정 규약 부록 (리뷰 차단⑤ 해소 — 원문 비수정, 조작화만)

- **코호트 이중 정의**: ⓐ 체결 코호트 = `positions` 와 (symbol,
  go_now 행의 `analyzed_for_date`±1영업일) join(수동 기록 규약 — #47,
  앵커 = 신호일). ⓑ **신호 코호트** = go_now 행 기준 OHLCV 가상 추적
  (진입가=신호일 종가) — 체결 0건 구간에도 F1~F3 을 신호 기준으로 병행
  판정(주 판정은 체결 코호트, 신호 코호트는 체결 표본 부족 시 대체 +
  항상 병행 보고).
- **F1**: 스탑아웃 = 손절가 터치, 창 = 진입 후 8주. 손절가 = **go_now 행의
  `entry_params.stop_loss_price`**(신호·체결 코호트 공통 — 실제 규율과
  단일 정의, 재검토 권고 5), 그 값 결측 시에만 TRADE_STOP_INITIAL_PCT
  −8% 폴백(폴백 사용 행 태그).
- **F2**: 창 = 진입 후 8주(F1 동일), "조기실패" = 종가 기준 pivot 하회
  복귀 AND 최고 도달 < 진입가×1.05. **F3**: 실현손실 = **손실 트레이드
  한정** 평균/중앙값(청산가 = 실제, 신호 코호트는 8주 창 종료가 —
  재검토 권고 6).
- **F4**: 분모 = `wait_reason='volume_below_strict_no_handle'` **행 단위**
  (동일 종목 복수 행 허용 — 차단 이벤트가 단위), 기준가 = 차단 당시
  pivot, 창 = 차단 후 8주, "20%+ 상승" = 최고가 ≥ pivot×1.20.
  **경로 비대칭 기록**(재검토 권고 4): breakout_from_watch 는 fresh_cross
  탓에 차단 다음날 재발화가 구조적으로 제한, entry 경로 breakout 은 매일
  발화 가능 → 행 단위 분모가 entry-분류 종목을 과대표집. 판독 시 행 단위
  + **종목-에피소드 단위 병행 보고**. 보유 억제분(§5)은 체인 선행으로
  분모 비포함.
- **판정 시점**: 첫 판독 = 코호트 최소 크기 도달 시(recall 감사 프레임
  — go_now ≥20 선례 #45). 그 전 관측치는 참고 보고만.

## 7. 의존성 맵 (threshold-change-checklist — 상수별 행 2축 판정)

**1단계(파생 신호)**: strict 인터셉트 → `wait_reason='volume_below_strict_no_handle'`
행 / flag 주입 → `no_handle_shakeout_absent` → 사이징·경고 / 신 pattern 값 →
분류·pivot_basis·트리거 경로 전파.

**2단계(소비 룰)**: evaluate_pivot 인터셉트 체인(신규 dedupe → #45 extended →
신규 strict) / entry_params_calc 티어·배수·vol_req / trigger_gate(발화 —
GATE_BREAKOUT_VOL_MULT) / prompt §8.5 밴드·D4.

**3단계(룰 내부 고정 상수) — 상수별 2축**:

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| BREAKOUT_VOL_PREFERRED=1.5 (신규 소비: strict floor) | 가능(배수) | **있음** — 이 패턴의 유일 통과 기준이 됨. 1.5 는 기존 "선호" 값의 승격 재사용(신규 수치 아님) | PRESERVES(O'Neil 40~50%+ 서술의 시스템 최소치) | 값 불변·소비 추가 — F4 가 과도성 감시(B-수치 = F4 판독) |
| BREAKOUT_VOL_FLOOR=1.4 / WAIT_FLOOR=1.2 | 가능 | **미미** — 이 패턴 한정 비적용(타 패턴 경로 불변). 비적용이 명시적 분기라 상호작용 없음 | EXTENDS | 모니터링(근거: 분기 조건이 pattern 등가 비교 단일 지점) |
| GATE_BREAKOUT_VOL_MULT=1.0 (발화) | 가능 | **미미** — 발화 집합 불변, 발화 후 차단만 추가(#45 동형·보수화만) | EXTENDS | 모니터링(근거: 발화 임계 비접촉 — F4 분모가 발화 후 차단분을 전수 포착) |
| PIVOT_EXTENDED_BAND_MULT=1.05 (#45 인터셉트) | 가능 | **있음** — 인터셉트 순서가 F4 분모를 결정(extended 선행 안 하면 코호트 오염) | EXTENDS | 순서 명문화(§3) + 테스트로 고정 |
| HANDLE_LEGIT_MIN_DAYS=5 (Gate3 경계) | 불가(일수) | **있음** — with/without 분기점으로 역할 확장(구: watch 강등점). 5일 자체는 불변 | design-judgment(HMMS 예외 하한 채택 기존 태그) | **B-수치**: F1~F3 첫 판독에 경계 의존성 검토 동반(비교군 정의가 이 경계에 의존 — 규칙 형식 정정, 자체 검토 C) |
| GATE_PROMOTION_PRICE_RATIO=0.95 (§8.5 밴드·promotion 발화 겸용) | 가능(비율) | **있음** — 신설 0.90 과 이중 경계 형성(0.90~0.95 = watch 대기존), promotion 발화 임계 겸용이라 신 패턴 watch→entry 승격도 이 값이 결정 | design-judgment(§8.5 명기 — promotion 임계와 정합 설계) | 값 불변 — 이중 경계 상호작용은 CUP_NH 행의 B-수치(flip-flop·경계 분포 판독)에 통합(재검토 차단 B) |
| ENTRY_WEIGHT_PCT_MIN=3.0 (사이징 하한) | 가능 | **미미** — F1~F3 발화 시 ×0.5 강화해도 7.0×0.5=3.5 > 3.0 (하한 비충돌 여유 확인) | EXTENDS | 모니터링(근거: 강화 1회 시나리오까지 하한 여유 실측 — 재검토 권고) |
| CUP_NH_RECOVERY_MIN=0.90 (신설, 프롬프트 전용) | 가능(비율) | **있음** — base_forming↔신 패턴 경계. 0.95(§8.5 밴드)와 이중 경계 형성: 0.90~0.95 = watch 대기존 | design-judgment(핸들 깊이 12% 존과 정합) | **B-수치**: 재분류 flip-flop 률·경계 분포를 첫 판독에 동반(코드 비소비 — SSOT 비등재, #19 전례) |
| `_FLAG_MULT` 0.7 (신설 값) | 가능 | **있음** — 실효 4.9pp 를 결정(티어 7.0 fallback 과 곱) | design-judgment(Minervini pilot 보수화 표 관례) | F1~F3 발화 시 ×0.5 강화 1회(사전등록 §6 판정 규칙이 후속을 이미 등록) |
| `_SIZE_FALLBACK_STD`=7.0 (소비) | 가능 | **있음** — flag 주입이 이 티어를 상시 선택(standard 10.0 도달 불능 — dead code 사유로 _STANDARD_PATTERNS 비등재) | EXTENDS | 값 불변 — #80(이중 구조 전면 재검토)로 이관 |
| TRADE_STOP_INITIAL_PCT=−8% (F1 측정 소비) | 가능 | **미미** — 측정 정의로만 소비(동작 비접촉) | PRESERVES(O'Neil 7~8%) | 모니터링(근거: 읽기 전용 소비) |

**소비 경계(1줄)**: 주말 A 분류(pattern·pivot) → 평일 B(trigger_gate 발화 →
evaluate_pivot 인터셉트 체인) → C(entry_params_calc 사이징) → go_now 신호 /
positions(수동) — 신 패턴은 이 4층을 전부 통과하며, 각 층의 변경이 위 행들.

## 8. 비변경·테스트·동기화

- **비변경**: Gate2 V 배제, 발화 임계, 타 패턴 경로 전부, `handle_quality`
  backstop(pattern≠cup_with_handle 자동 skip — 리뷰 확인), §6.1/§6.2 게이트.
- **TDD 목록**: ① Gate3 분기·§8 각주·:540 재작성·§4 블록의 프롬프트
  텍스트 검증(tests/test_prompt_* 드리프트 관례 — **LLM 행동 검증은
  재실행 비교 금지 규율상 불가, 텍스트 검증까지가 한계** 명기) ② strict
  인터셉트(1.49 차단·1.5 통과·체인 순서 dedupe→extended→strict·타 패턴
  비적용·**volume/avg 결측 시 비발동 폴백**) ③ flag 주입 멱등+4.9pp 실효
  +**`size_reduced_due_to_no_handle_shakeout` 경고 방출·우선순위 등재**
  ④ dedupe(상향 한정 — breakout·breakout_from_watch·**promotion 각각
  억제 케이스**·invalidation 비억제·**억제 행 기록값 스키마**) ⑤
  pivot_basis cup_high +tick 사후검증 ⑥ vol_req="ge_1.5x_strict" 표기.
- **수동 동기화 목록**(비차단 9 + 재검토 권고 7): `verify_analysis_v1.md:12`
  패턴 카운트, analyze §Forbidden :678 "9→10-value", web `base-patterns.ts`·
  `entry-params-fields.ts:35`(vol_req enum)·`stages.ts:270`·
  **`ClassificationsPage.tsx:68` PATTERN_DESCRIPTIONS**·
  **`prompt-explanations.ts:28,37` "9 base 패턴" 카운트 2곳**.
  `scripts/remeasure_phase2i.py:19` 는 superseded 주석(구 Gate3 기대문).
  thresholds.py 변경 없음(신설 상수 0 — 프롬프트 전용값 원칙) → export
  재실행 불요.
- **F1~F4 배포**: 본 문서 §6 이 등록본. 구현 PR 머지 시점부터 코호트 발생.
