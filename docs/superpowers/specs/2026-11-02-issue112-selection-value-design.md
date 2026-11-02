# #112 — 2차 필터(LLM 분류) 선별 가치 forward return 측정 (설계, 탐색 등급)

> 상태: 방법 고정 2026-11-02(실행 전 기입). 증거 규율 `2026-08-14-evidence-tier-amendment-v2.md`.
> 표본 A·B·C 는 전부 기열람 → 본 측정은 **탐색 등급 고정**(채택 근거 불가, 다음 가설 설계 재료).
> 산출물 `exploratory_` 접두 + LOOK_LOG 1행. 전 과정 읽기 전용(SELECT + JSON) — 신규 LLM 0·KRX 0.

## 1. 질문

같은 1차 스크리너 통과분 중 LLM 이 **고른 것(entry+watch)** 이 **버린 것(ignore)** 보다
분류 이후 시장 대비 더 올랐는가. (방어 효과가 아닌 **정보 가치** — 포함 여부의 예측력.)

## 2. 데이터

- `backtest_classification` 6,023셀(실측 2026-11-02): watch 5,702 / ignore 295 / entry 26.
  전부 토요일(`analyzed_for_date` dow=6), 2017-07-01 ~ 2024-12-28.
- 가격 `daily_prices.adj_close`(NULL 0), 지수 `index_daily`(1001 KOSPI / 2001 KOSDAQ,
  `backtest_classification.market` 기준 — `phases.INDEX_OF`).
- 표본 귀속: 종목이 `FROZEN_SAMPLE`(A) / `FROZEN_SAMPLE_B`(B) 이고 2021-01-01~2024-12-31 → A/B,
  `FROZEN_SAMPLE_C` 이고 2017-07-01~2020-12-31 → C. 어느 것에도 안 맞는 셀은 `unassigned` 로 보고(기대 0).

## 3. 측정 (#111 §2.2 와 동일 관례)

- 기준가: 분류일(토) **다음 관측행**(보통 월요일) `adj_close` = T+1. 종료가: T+1 로부터 그 종목
  시계열 기준 **20 / 40 / 65 관측행 뒤**(4·8·13주). 주 horizon = 20.
- 초과수익(%p) = 종목 수익률(%) − 같은 두 날짜 지수 수익률(%) (단리 차).
- 결손(T+1 없음·행 수 미달·지수 결측)은 그 horizon 에서 제외 + 제외 건수 보고.

## 4. 산출

1. **주 비교**: 선별군(entry+watch) vs 기각군(ignore) 의 평균 초과수익 **차이**(선별 − 기각)와
   종목 클러스터 부트스트랩 95% CI(B=10,000, seed=20260721, 종목 복원추출 → 양 군 (합,개수) 재집계 →
   차이). 각 군 단독 평균·중앙값·CI 도 보고. 해석 어휘: 차이 CI 하한>0 "선별 가치 단서" / 0 포함
   "구분 불가" / 상한<0 "역선별 단서" — **탐색 등급이므로 판정이 아니라 단서**.
2. **표본별**: A / B / C 분리 + 풀링. 구간 의존성 확인.
3. **기각 사유별 분해**(부가): `risk_flags` 우선순위 reverse_split_distortion > climax_run >
   topping_distribution > 기타 로 단일 라벨. 각 라벨 군 vs 선별군 차이. reverse_split 은 데이터 결함이라
   별도 표기.
4. **entry 단독**(n=26) 참고 표기만.
5. 부가 기술 통계: 양수 비율, 중앙값.

## 5. 한계 (보고서 명시)

- 생존 편향: 백테스트 분류는 상폐 종목을 거의 포함하지 않음(실측 상폐 2종목). #180 ②-2 전까지 불가피.
- ignore 295 중 climax 242·topping 51 — "천장 종목을 버린 것"이 선별 가치의 본질. 기각군은 소수라
  CI 가 넓다.
- watch 는 "매수"가 아니라 "관찰"이므로 트리거 층 성과와 다른 측정이다.
- 프롬프트 버전 혼재(2026-06-24~08-12 생성, `prompt_version` NULL) — 버전별 분해 불가.

## 6. 구현

- 순수 함수 `kr_pipeline/backtest/selection_value.py`(테스트 `tests/test_selection_value_112.py`),
  러너 `scripts/exploratory_issue112_selection_value.py`, 산출물
  `data/backtest/exploratory_issue112_selection_value_YYYYMMDD.json`.
- 부트스트랩은 `minervini_forward.agg_bootstrap_ci` 와 같은 rng 관례(`random.Random(seed)`,
  sorted tickers 에서 `rng.choice`).
