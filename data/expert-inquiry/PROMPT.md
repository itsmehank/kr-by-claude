# 문의: 슈퍼 주도주(SK하이닉스)에 대한 주간 분류 entry 0회 — 판정 규칙 검증

당신은 이 프로젝트의 GitHub repo 와 Minervini·O'Neil 원서 PDF 에 접근할 수 있다.
DB 데이터는 접근 불가하므로, 필요한 관측 데이터는 첨부 파일 3개(CSV·사유 원문·주봉 차트)로 제공한다.

## 시스템 개요 (repo 에서 직접 확인 가능)

- Minervini Trend Template 결정론 필터 통과 종목을 **매주 토요일** LLM 이 분석해
  `entry / watch / ignore` 분류. 판정 규칙 전문: **`prompts/analyze_chart_v3.md`**
- 별도로 **평일** 경로가 watch 종목의 피벗 돌파를 감지해 매수 신호를 생성
  (`kr_pipeline/llm_runner/compute/trigger_gate.py` → `evaluate_pivot.py`)
- 이번 문의는 **주간 분류의 보수성**에 관한 것. 특히 다음 규칙 원문을 읽고 책과 대조해 달라:
  - `prompts/analyze_chart_v3.md:240` — `climax_run` 정의: "Price up ≥25% in 1–3 weeks;
    largest weekly price spread and heaviest volume of the current move"
  - `:241` — `late_stage_base`: "3rd or later base in the current Stage 2 advance"
  - `:242` — `extended_from_ma`: "Price > SMA-50 by more than 15%"
  - `:36`, `:291` — ignore 가이드 / `:127` — 경계 수렴 규칙(watch 로 수렴)

## 관측 결과 (2025-06 ~ 2026-06, SK하이닉스 000660 주간 백테스트 52주)

- 주가 **+1,039%** (207,500→2,363,000), RS Rating 평균 94 (범위 72~99), 전 기간 Trend Template 통과
- 시장: KOSPI confirmed_uptrend 220일 / correction 23일 (시장 컨텍스트 우호 — §3.5 하드룰 미발화)
- 분류: **entry 0 / watch 10 / ignore 37**
- risk_flags 빈도: climax_run 32주, extended_from_ma 33주(ignore 26+watch 7), late_stage_base 21주(ignore 18+watch 3)
- **핵심 모순 1**: climax_run 플래그 32주 중, prompt 자체의 정량 정의(1~3주 내 +25% —
  공정하게 max(1주,2주,3주 수익률)≥25% 로 채점)를 실제 충족한 주는 **11주뿐**
  (첨부 A 의 `meets_climax_def` 컬럼) — **21주는 정의 미충족인데 climax 로 판정**.
  정의의 나머지 요소(largest weekly spread / heaviest volume)도 첨부 A 의
  `week_spread_%`·`week_vol_vs_50wavg` 컬럼으로 행 단위 채점 가능하다
- **핵심 모순 2**: watch 가 잡은 피벗 5건은 전부 2~6거래일 내 실제 돌파 (피벗 산정은 정확):

| watch 주 | pivot | 돌파일 | 돌파일 거래량(50d평균 대비) |
|---|---|---|---|
| 2025-06-14 | 248,500 | +3일 | 1.41× |
| 2025-09-13 | 306,600 | +2일 | 1.32× |
| 2025-09-20 | 306,600 | +2일 | 1.31× |
| 2025-10-04 | 306,600 | +6일 | 2.08× |
| 2026-01-24 | 646,000 | +2일 | 0.82× |

## 첨부 데이터

- **A_weekly_classification_vs_indicators.csv** (47행): 분류 주별 — 분류/패턴/확신도/risk_flags +
  그 주 금요일 종가/RS rating/SMA50·200 이격%/52주고점 대비%/직전 1·2·3·10주 수익률 +
  그 주의 주봉 고저폭%(`week_spread_%`)·주간 거래량/50주평균(`week_vol_vs_50wavg`) +
  climax 플래그/정량 정의 충족 여부. → climax 정의의 세 요소(상승률·spread·volume)와
  extended 컷(SMA50 이격)을 전부 행 단위로 채점할 수 있다.
- **B_reasoning_samples.md**: 대표 6주(watch 3, ignore 3 — ignore 3주는 모두 *정의 미충족
  climax* 케이스)의 LLM 사유 원문 — 판정 논리 검증용.
- **C_weekly_chart_000660.png**: 주봉 차트 80주(~2026-06-01) — 베이스 카운트(질문 2)와
  climax 형태 판정(질문 1b)을 시각적으로 검증할 수 있다.

## 질문

1. **climax_run — 두 층으로 답해 달라**
   (a) *준수 실패*: 정량 정의(1~3주 +25%)를 충족하지 않은 21주에 climax 를 붙인 것은 명백한
   과대 적용으로 보인다. prompt 의 어떤 표현이 이 드리프트를 유발했을지, 그리고 정의 준수를
   강제할 prompt 수정안(문구 단위)을 제안해 달라.
   (b) *정의 적합성*: 정량 정의를 충족한 11주조차 — 1년 내내 추세가 지속된 주도주의 *진행 중*
   상승을 climax(말기 신호)로 부르는 것이 책의 climax run 정의(Minervini Stage 3 경고,
   O'Neil climax top)에 맞는가? 책은 climax 를 "장기 상승의 **말미**" 신호로 한정하는
   추가 조건(예: 상승 기간, 가속도, 이격 극단)을 두는가? 페이지 근거와 함께 정량 기준을
   제안해 달라.

2. **late_stage_base (21주)**: 책에서 base count 는 언제 리셋되는가(새 강세장 / follow-through
   이후)? 신고가 행진 중 base-on-base 는 카운트를 어떻게 다루나? 1년 내 4~5번째 베이스를
   일괄 late_stage 로 보는 현 동작이 타당한지 판정해 달라.

3. **extended_from_ma 15% (33주)**: SMA-50 대비 +15% 컷이 책 근거가 있는 수치인가?
   첨부 A 를 보면 강추세 구간에서 이 조건이 거의 상시 충족된다 — 주도주의 추세 구간에서
   이 기준의 예외/완화(또는 다른 기준선) 규칙이 책에 있는가?

4. **주간 스냅샷에서 entry 의 기대 빈도**: 토요일 1회 분석으로 "피벗 돌파 직후(buy point)"를
   포착하는 것은 구조적으로 드물 수밖에 없지 않은가? Minervini/O'Neil 실무에서 주말 리뷰의
   역할(후보 선정·watch 리스트)과 일중/일간 진입 판단의 역할 분담을 책 근거로 정리해 달라.
   — 우리 시스템도 평일 돌파 감지 경로가 따로 있으므로, "주간 entry 0 이 정상 범위"인지가
   궁금하다.

5. **놓친 주도주 재진입 기법**: 첫 돌파를 놓친 주도주에 대해 책이 제시하는 재진입 셋업
   (pocket pivot, 10주선/20일선 눌림목, base-on-base, 3-weeks-tight, 신고가 후 첫 풀백 등)
   중 *주간 분류 시스템*에 추가할 가치가 높은 것 2~3개를 골라, 각각의 정량 조건과 함께
   `prompts/analyze_chart_v3.md` 에 들어갈 규칙 문안(영문, 기존 § 형식에 맞춰)을 제안해 달라.

## 산출물 형식 요청

각 질문에 대해: (a) 책 인용(서명+페이지), (b) 정량 기준/규칙 문안,
(c) 현재 관측(32주 climax 등)의 타당성 판정.
가능하면 `prompts/analyze_chart_v3.md` 에 대한 **구체 수정 제안을 변경 전/후 텍스트**로 —
그대로 적용 가능한 형태가 가장 좋다.
