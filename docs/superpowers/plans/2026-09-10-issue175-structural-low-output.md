> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# #175 — 패턴별 구조 저점 가격 출력 신설: Phase A(기존 결정론 핸들 검출기 조사)·판정·보류(2026-09-10)

> 코드·상수·문서 변경 0(본 기록 문서만). LLM 0. 판정은 전문가·사용자(원칙 2-2), 사실은 CC 조사.
> 상태: **보류(deferred)** — wake trigger = P0 완료 + go_now ≥ 20 축적 후 재개 검토. 재개 시 선택지 A(재설계)부터.
> 설계 제약(확정): 출력은 **결정론(갈래 b)** — LLM 출력(a·c)은 과거 저장본에 부재 → 백테스트 파리티 불가(#153 통일 역행).

## 0. 판정 원문(전문가, 2026-09-10)

- 현 `compute_handle_quality` 는 핸들 시작 규칙(컵 바닥 이후 고가가 pivot 에 닿은 첫날 → 분류일)이 HMMS 핸들
  정의(우측 림 → 하향 드리프트 ≥1~2주 → 깊이 8~12%)와 **다름**. 커버리지 25%(56/225)·26%(617/2,350), LLM
  handle_depth_pct 와 >3pp 불일치 40%·54%, 창 상한 없음(최대 98일·185일), `high ≥ pivot` 조건으로 핸들
  고점=림인 경우 영구 미검출.
- **확장 불가, 재설계 필요.** 재설계 시 시작점·창 상한 규칙은 design-judgment. pivot_basis None 33~44% 는
  재설계로도 미해결.
- VCP·3C 결정론 탐지 코드 없음 — 신규 작성 필요.
- 선택지 A(재설계) / B(보류) / C(LLM 보고 깊이 사용 — 손절가에 LLM 변동성 유입, 채택 불가 유지).
- **사용자 결정(2026-09-10): B. #175 보류.**
- A2 스케일 불일치 33행(기업행위 후 adj 재스케일 vs 저장 pivot)은 **데이터 무결성 관측**으로 기록. 재계산 시
  동일 어긋남.

## 1. 책 핸들 정의(HMMS, 전문가 확정)

≥1~2주 / 컵 상단 절반 / 10주선 위 / 하향 드리프트 / 깊이 8~12% / 거래량 감소.

## 2. Phase A 사실(2026-09-10 회신 전문)

### A1. `compute_handle_quality` 알고리즘(kr_pipeline/llm_runner/compute/handle_quality.py, gates.py `apply_phase1_gates` 가 저장 직전 1회 호출)

- 전제(미충족 시 skip·log만): pattern=cup_with_handle, **pivot_basis=handle_high**, base_start_date·pivot_price·
  base_depth_pct 존재, base_depth_pct>0.
- 입력 창: daily_prices(adj 우선) ⨝ daily_indicators(sma_50·distribution_day_flag), `base_start_date ≤ date <
  classified_at`(백테스트는 analyzed_for_date+1). 행 수 < BASE_MIN_DAYS(5)+HANDLE_MIN_DAYS(3) → skip.
- 핸들 시작: 창 내 **최저 low 봉(컵 바닥)** 이후 첫 `high ≥ pivot_price` 봉 = 우측 림. 그 봉부터 창 끝까지가
  handle_rows(림 봉 포함), 그 앞이 base_rows. 림 미회복 → skip. handle_rows<3 / base_rows<5 → skip.
- 핸들 끝: **창 끝 = classified_at 직전 거래일. 상한 규칙 없음.**
- 산출식: handle_high = pivot_price(LLM pivot 그대로), handle_low = min(handle_rows.low),
  handle_depth_pct = (hh−hl)/hh×100(장중 high/low 기준).
- 룰 발화 = (A) ratio_a = depth/base_depth_pct > HANDLE_DEEP_RATIO 0.33 ∨ (B) 핸들 평균거래량/베이스
  평균거래량 > HANDLE_VOLUME_NOT_CONTRACTING_RATIO 0.80 ∨ (분배) 핸들 구간 distribution day ≥1. 미발화 시 값
  폐기(None). 발화 시만 risk_flags `handle_quality` 주입 + verdict floor watch + conf cap 0.60(extended 면 0.50)
  + triggered_rules.2E_tier 에 metrics(handle_start/end·high/low·ratio) 저장. 가중(위치 <0.33·MA50 아래)은 기록만.
- 상수 태그: HANDLE_DEEP_RATIO 0.33·HANDLE_VOLUME_NOT_CONTRACTING_RATIO 0.80·HANDLE_MIN_DAYS 3·BASE_MIN_DAYS 5·
  HANDLE_POSITION_LOW_RATIO 0.33 = 전부 **[heuristic]**(0.33 은 "책 8~12% 와 reconcile 미완" 자기 표기). 책 밴드
  HANDLE_DEPTH_BULL_MIN/MAX 8/12·HANDLE_LEGIT_MIN_DAYS 5 는 [book-anchor]이나 **이 검출기는 소비하지 않음**
  (프롬프트 Gate3 만 소비).

### A2. 조건 없이 전 cwh 행 재실행 커버리지(발화 조건 제외, 검출 로직 동일 — 스크래치패드 hq_survey_175.py)

| 표 | 행 | 검출 | 실패 사유 |
|---|---|---|---|
| weekly_classification cwh entry/watch | 225 | **56** | pivot_basis None 75 · 우측 림 미회복 70 · 핸들 창 <3일 11 · range_high 5 · cup_high 7 · base 창 <5일 1 |
| backtest_classification cwh entry/watch | 2,350 | **617** | pivot_basis None 1,037 · 우측 림 미회복 557 · 핸들 창 <3일 60 · range_high 67 · base 창 11 · pivot/depth 결측 1 |

backtest 검출 617 중 **33행(12종목: 000990·005490·006490·006740·031860·090150·105550·189300·206640·207760·
214370·260970)은 pivot_price 가 현재 adj 가격과 스케일이 달라 음수 깊이**(예 090150 pivot 4,887 vs low
39,330). 이하 backtest 수치는 이를 제외한 584행.

### A3. 검출 깊이 vs LLM handle_depth_pct

| 표 | 양쪽 값 | \|차\| 중앙 | ≤1pp | ≤3pp | >3pp | 방향(>3pp) |
|---|---|---|---|---|---|---|
| weekly | 40 | 1.5pp | 18 | 24 | 16 | 검출>LLM 8 · 검출<LLM 8 |
| backtest(clean) | 522 | 3.3pp | 134 | 242 | 280 | 검출>LLM 74 · 검출<LLM 206 |

큰 불일치 표본(weekly): 010400(08-18, 07-22~08-14 18일, 12.2 vs 25.9 faulty) · 033560(15일, 3.0 vs 14.3) ·
137080(7일, 2.9 vs 13.6) · 900260(36일, 18.1 vs 7.4) · 278470(4일, 4.8 vs 13.4). backtest: 002710(3일 1.9 vs
22.7) · 206650(46일 26.7 vs 8.4 legitimate) · 082740(3일 4.1 vs 22.0) · 101160(22일 3.4 vs 20.3) · 042370(91일
22.3 vs 5.8 not_formed). 검출기는 "pivot 이후 최저 low"를 핸들로 잡아 LLM 이 본 핸들 구간과 시작점이 다른
경우가 반복(사실, 원인 판정 아님).

### A4. 핸들 길이 분포·상한

| 표 | 최소 | Q1 | 중앙 | Q3 | 최대 | >10일 | >20일 | >60일 |
|---|---|---|---|---|---|---|---|---|
| weekly 56 | 4 | 7 | 14 | 30 | 98 | 36 | 20 | 5 |
| backtest 584 | 3 | 9 | 15 | 29 | 185 | 388 | 215 | 54 |

**현 코드에 상한 없음.** 하한 HANDLE_MIN_DAYS 3(heuristic), 책 1~2주(HANDLE_LEGIT_MIN_DAYS 5) 미참조. 최장
066620 2026-04-16~09-08(98일), backtest 109860 2018-09-03~2019-06-07(185일). 검출 깊이: weekly 중앙 9.1(>8% 31·
>12% 18), backtest 중앙 7.1(>8% 269·>12% 144).

### A5. VCP·3C 결정론 탐지 코드 — **없음**

compute 디렉토리(climax_topping·delta·entry_params_calc·failed_breakout·gate_precompute·handle_quality·
payload_lite·recent_transition·trigger_gate·tt_marginal)에 수축 구간·cheat 구간 탐지 함수 없음. entry_params_calc
의 3c_cheat 는 상류 라벨 특칙 분기만. contraction_count·contraction_depths_pct 는 LLM 출력을 measurements JSONB 에
병합 저장만.

### A6. 저장 경로

- computed_gates(B, #22)는 DB 컬럼이 아닌 payload 필드. A 경로 결정론 산출은 `store.insert_classification` /
  `insert_backfill_classification`(classification_backfill·backtest_classification·recall_audit 공용)이 저장 직전
  `apply_phase1_gates` 호출 → **triggered_rules JSONB**(+risk_flags 주입, verdict_original 보존). 세 테이블 모두
  triggered_rules·measurements 보유.
- 신규 검출값도 같은 insert 시점 훅 가능. 컬럼/JSONB 신설은 운영 규칙 4(양쪽 DB).
- **저장본 in-place 재계산 경로 없음**(UPDATE 코드 없음, 스크립트는 읽기 전용 재생만). 입력이 결정론이라 멱등
  재계산은 가능하나 스케일 불일치 33행은 동일하게 어긋남.

## 3. 후속(착수 금지)

- **#177** `compute_handle_quality` 강등의 정당성 검토(원칙 1-3·1-1 판정 대상 후보) — 발화 36건 조사 요청 4항.
  → **#177 Phase B(2026-09-10)**: 같은 검출기에 책 경계 2건(조건 A 깊이비 제거·핸들 하한 5일) 적용 —
  `plans/2026-09-10-issue177-handle-quality-book-bounds.md`. 시작점·창 상한 재설계는 여전히 본 이슈(#175) 범위.
- #161(보류, wake 동일 조건) · #165 · #174.
