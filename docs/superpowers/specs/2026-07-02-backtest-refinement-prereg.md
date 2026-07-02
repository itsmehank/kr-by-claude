# 백테스트 개선 1~3 — 사전등록 (2026-07-02)

수익성·강건성 백테스트(`2026-06-23-profitability-robustness-backtest-design.md`) 1차 결과
(`backtest-profitability-results.md`) 이후 개선 3건. **본 문서의 판정 기준·파라미터는
결과 산출 전 고정** — 결과를 보고 바꾸지 않는다(§7 규율 동일).

입력 데이터: 동결 100종목 트레이드 66건(1차 결과와 동일 산출 경로 `run_analysis`,
LLM 재분류 없음 — 분류층은 그대로, 트리거·집계층만 개선).

---

## 1. 하락기 진입 33건 LLM 트리거 확인 감사

### 목적
1차 결과의 §7.2 트레이드 층은 시장 비게이팅 결정론 근사("하한")였다. 실제 시스템은
매수 직전 LLM 트리거 확인(`evaluate_pivot_trigger_v1.md`)에서 §3.5 시장 게이트를
재적용한다(프롬프트 §3.5 분기 확인됨: unfavorable_market + 하락국면 → wait).
**시뮬이 만든 하락·조정기 진입 33건 중 실제 시스템이라면 몇 건을 막았는지 실측**해
"하한"을 추정치로 바꾼다.

### 방법
- 대상: 66 트레이드 중 진입일 국면 ∈ {downtrend, correction} = **33건**
  (재현: `run_analysis` 동일 경로, 결정론이라 동일 33건 보장).
- 각 건: `as_of = entry_date`(트리거 발화일), `trigger_type = "breakout_from_watch"`,
  **prior_analysis = 그 트레이드를 만든 backtest_classification watch 행 주입**
  (pivot_sat 기준; `classified_at` 주입값 = `analyzed_for_date` — 백필 실행시각은 무의미).
- 호출: `build_for_5b(prior_row=주입)` → `call_claude("evaluate_pivot_trigger_v1.md")`.
  모델 = 기본 핀(sonnet), llm_model 자동 기록.
- 저장: **`data/backtest/trigger_audit_20260702.json` 파일** — production
  `trigger_evaluation_log` 는 읽기만(과거 윈도 빈 리스트), 쓰기 0건.
- 멱등: 파일에 이미 있는 (ticker, entry_date) skip — 사용량 한도 resume 가능.
- LLM 비결정성 규율: **1회 실행 → 저장 → 해석. 재실행 비교 금지**(백테스트 §5.1 동일).

### 선결 검증 (실행 전)
- 페이로드 덤프 1건: 텍스트 내 날짜 토큰 max ≤ as_of (§1 방식). prior_analysis 가
  주입 행과 일치하는지 확인.

### 사전등록 판정 기준
- `G = go_now 건수 / 33` (wait·abort = 차단으로 간주).
- **G ≤ 0.5** → 트리거 확인 층이 하락·조정기 진입의 과반을 차단 = actionable 경로의
  게이트 방어 입증. 실전 하락기 노출 추정 = 33 × G 건.
- **G > 0.5** → 트리거 확인 층의 시장 방어 미작동 — §3.5 프롬프트 재검토 대상.
- 부가 기대(참고, 판정 아님): watch_reason=unfavorable_market 건은 프롬프트 규칙상
  전건 wait 기대. 이탈 건은 reasoning 기록.
- 한계 명시: 감사 페이로드의 recent_evaluation_history 는 빈 리스트(과거 윈도에
  production 로그 없음) — 실전보다 정보가 적은 조건. LLM 1회 실행 비결정성.

## 2. 결정론 보정 패키지 (전부 결정론, LLM 0회)

1차 결과의 현실성 격차 교정. **주 결과 = 보정 후 66건**(2025 절단 제외는 민감도).

### 2.1 5% 추격 룰
- 진입 조건에 `entry_close ≤ pivot_price × 1.05` 추가(초과 시 그 신호 소멸, 같은
  pivot 재진입 금지 유지). 실제 시스템의 `max_chase_pct_from_pivot=5.0` 반영.
- 상수는 백테스트 모듈 로컬(`MAX_CHASE_PCT = 5.0`) — thresholds.py 무접촉
  (분석 전용, production 임계 아님).

### 2.2 거래 비용
- 매도 증권거래세(농특세 포함, KOSPI/KOSDAQ 총률 동일): **매도일 연도 기준**
  2021·2022 = 0.23%, 2023 = 0.20%, 2024 = 0.18%, 2025 = 0.15%.
- 수수료: 왕복 0.03%(편도 0.015%).
- 슬리피지: 0(종가 체결 가정 유지 — 2.3 밴드가 체결 불확실성 커버).
- `pnl_net = pnl_gross − (매도세율 + 0.03%)`, excess 도 net 기준 재계산.

### 2.3 청산가 밴드
- 하한(현행) = 청산일 종가 체결.
- 상한(낙관) = 같은 청산일에 stop 레벨 체결. 단 갭다운(당일 고가 < stop)이면 당일
  시가 체결. stop = base_low 청산이면 base_low, sma_50 청산이면 당일 sma_50.
- 보고: 국면별 mean excess 를 [하한, 상한] 밴드로.

### 2.4 2025 절단 제외 민감도
- entry_date > 2024-12-31 인 7건 제외한 59건 재집계(민감도, 주 결과 아님).

### 2.5 부트스트랩 CI
- **종목 클러스터 부트스트랩**(트레이드가 종목 내 상관 — 종목 단위 복원추출 후 해당
  종목 트레이드 전부 포함), B = 10,000, **seed = 20260702**, 95% percentile CI.
- 대상: 전체·국면별 mean excess (보정 후 기준).
- 해석 기준(사전등록): 전체 mean excess 95% CI 가 0 을 포함하면 "시장 초과 미입증"
  으로 보고(1차 결과의 점추정 +2.6% 서사 교정).

### 2.6 스펙 §6 미이행 지표 메꿈
- 국면별 payoff ratio(평균이익/|평균손실|), 트레이드별 보유 중 최대낙폭
  (entry_close 대비 보유기간 최저 close, %), promotion 발화 수 보고.

## 3. 플라시보 대조군 (결정론, LLM 0회)

### 목적
"pivot 돌파 타이밍이 무작위 진입 대비 가치를 더하나"를 분리 측정(종목 선정 효과와
타이밍 효과의 분리).

### 설계
- 각 실제 트레이드(보정 후 집합)와 짝: **같은 종목, 같은 보유 거래일수**, 진입일만
  무작위(그 종목의 2021-01-01~2024-12-31 거래일 중 uniform, 보유기간이 데이터 내에
  들어가는 날만). 청산 = 진입일 + 같은 보유 거래일수의 종가(규칙 청산 아님 — 보유기간
  매칭 event-study 표준). 비용 §2.2 동일 적용.
- 반복 N = 1,000 세트, **seed = 20260702**.
- 통계량: 실제 mean excess(보정 후)가 플라시보 mean excess 분포에서 차지하는 백분위.

### 사전등록 판정 기준
- one-sided p < 0.05 (실제 > 플라시보 95백분위) → "돌파 타이밍이 무작위 대비 유의".
- p ≥ 0.05 → "타이밍 가치 미입증(종목 선정 효과와 구분 불가)"으로 보고.

## 4. 실행 순서·격리 요약

1. blocker 수정: `build_for_5b(prior_row=)` 주입 파라미터(TDD, 기본 경로 불변) +
   `evaluate_pivot_trigger_v1.md` 외부정보 금지 1줄(판정 로직 무변경).
2. 감사(§1) → 33 호출, 파일 저장, production 테이블 쓰기 0.
3. 보정 패키지(§2) → 플라시보(§3) — 전부 결정론.
4. `backtest-profitability-results.md` 에 통합 반영.

변경 파일 격리: production 코드 변경은 payload_lite(추가 파라미터, 기본 동작 불변)와
프롬프트 1줄뿐. 나머지는 kr_pipeline/backtest/ 전용.
