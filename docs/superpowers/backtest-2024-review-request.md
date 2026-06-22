# 2024 주말분류 백테스트 — 외부 리뷰 요청

이 문서는 GitHub로 연결된 외부 리뷰어(web Claude project)에게 전달하기 위한 것입니다.
repo의 main 브랜치에 접근할 수 있으니, 아래에 인용한 소스 파일을 직접 열어 교차 검증해 주세요.

## 0. 한 줄 요약 / 리뷰 요청

8종목 × 2024 매주 토요일을 라이브와 동일한 프롬프트(`prompts/analyze_chart_v3.md`)로 분류한
백테스트에서 **191건 중 `entry`가 0건**이었고, `watch`(164)는 평균 +12주 +33.7%로 예측력이 있었으나
한 번도 actionable 신호로 전환되지 않았습니다. **이 동작이 (a) 설계 의도대로 올바른 것인지, (b) 게이트가
과도하게 보수적이어서 고쳐야 할 결함인지** 판단과 개선안을 받고 싶습니다. 특히 4개 이슈(아래 §3)를
프롬프트·게이트 코드와 대조해 검토해 주세요.

## 1. 방법 (재현 가능)

- **대상 8종목** (유형별 대표, 일봉으로 추출): 삼양식품(003230,①상승), 인화정공(101930,①상승),
  가온칩스(399720,②돌파실패), 에이팩트(200470,②돌파실패), 실리콘투(257720,③클라이맥스),
  노루홀딩스(000320,④횡보), 윙입푸드(900340,⑤변동성), HD현대일렉트릭(267260,⑥장기추세).
- **실행**: `python -m kr_pipeline.llm_runner --mode=backfill --start=2024-01-06 --end=2024-12-28
  --tickers=...` → `classification_backfill` 테이블에 적재(191건, 실패 0). 각 토요일 시점
  `on_date<=as_of`로 과거 데이터만 사용(look-ahead 없음). 라이브와 동일 프롬프트.
- **게이트**: backfill은 `kr_pipeline/llm_runner/load.py:get_qualifying_tickers`의 결정론 필터
  (`minervini_pass ∧ rs_line_not_declining_7m`)를 통과한 종목만 LLM에 전달.
- **채점**: 각 분류 시점 대비 +4주/+12주 수정종가 수익률. 쿼리=`scripts/backtest_2024_analysis.sql`.
- **상세 데이터·표**: `docs/superpowers/backtest-2024-results.md` (종목별 타임라인·판정 분포 포함).
- ⚠ LLM 비결정성: 재실행 시 판정이 조금씩 달라질 수 있어 정확한 일치가 아니라 패턴으로 해석.

## 2. 결과 요약

판정 분포: **entry 0 / watch 164 / ignore 27** (총 191).

| 판정 | n | 평균 +4주 | 평균 +12주 |
|---|---|---|---|
| watch | 164 | +10.1% | **+33.7%** |
| ignore | 27 | +16.7% | +18.2% |
| entry | 0 | — | — |

`watch_reason` 분포: `base_forming` 115 / `extended` 42 / `valid_base_awaiting_breakout` 2 /
`unfavorable_market` 4 / `marginal_tt` 1.

2024 시장상황(52 토요일, `market_context_daily.current_status`): confirmed_uptrend **16** /
downtrend 22 / correction 11 / rally_attempt 3 → **36/52가 비우호적**.

## 3. 검토 대상 이슈 4건 (근거 + 소스 위치 + 질문)

### 이슈 1 — `entry`가 191건 중 0건 (구조적 미발생)
**근거**: 전 종목·전 시점에서 entry 미발생. 가장 큰 승자(실리콘투 이후 +135%, 삼양식품 +44%,
인화정공 +27%, HD현대일렉트릭 +37%)조차 전부 watch. `watch_reason`은 `base_forming`/`extended`가 지배.

**원인 가설 2가지** (리뷰어가 어느 쪽인지/혼합인지 판단 요청):
1. **시장방향 게이트 (`prompts/analyze_chart_v3.md` §3.5, line 99–104)**: `current_status`가
   downtrend/correction/rally_attempt면 entry를 강제로 watch로 강등 + `unfavorable_market_context`.
   2024는 36/52 토요일이 비우호적 → 그 주들은 setup이 완벽해도 entry 불가. **단, 우호적 16토요일에도
   entry가 0이었음** → 시장게이트만으론 완전히 설명 안 됨.
2. **타이밍 정의 (§3.2, line 43)**: entry = "proper buy point now/imminent(~5거래일 내)". 주 단위
   토요일 스냅샷은 돌파일(주중)을 놓쳐 "base_forming(미완)" 또는 "extended(이미 지나감)"로만 보임.
   `valid_base_awaiting_breakout`이 2건뿐 → 돌파 직전 포착이 거의 안 됨.

**볼 파일**: `prompts/analyze_chart_v3.md` §3.2/§3.5/§3.7(pocket pivot, line 187–203)/§4.7;
`kr_pipeline/llm_runner/store.py`(insert_classification + apply_phase1_gates 후처리 강등);
`kr_pipeline/llm_runner/backfill.py`(주말 스냅샷, on_date).

**질문**:
- (a) weekly 한정 백테스트에서 entry=0은 *예상된* 결과인가? entry는 본래 평일 daily_delta 경로
  (돌파 당일)에서 나오도록 설계된 것인가?
- (b) 우호적 시장 16토요일에도 entry가 0인 것은 setup 타이밍 탓인가, 아니면 게이트가 과보수적인가?
- (c) `valid_base_awaiting_breakout`(2건)이 entry로 승격되는 실제 경로/조건이 존재하는가?

### 이슈 2 — watch의 예측력 vs 기회비용
**근거**: watch 평균 +12주 +33.7%. 승자가 전부 watch(실리콘투 +135% 등). 시스템은 **종목 선별은
잘했지만** 한 번도 commit하지 않음 → 모든 상승을 watch로만 관망.

**질문**: 이건 "보수적이지만 안전"으로 수용할 것인가, 아니면 watch 중 일부를 actionable
(예: pivot 도달 시 알림/승격)로 전환하는 메커니즘이 필요한가? 현재 watch→entry 승격은
어느 경로(daily_delta?)에서 일어나며, weekly만으로는 영원히 watch에 갇히는가?

### 이슈 3 — `ignore=climax_run`이 지속 추세에 과민
**근거**: ignore 27건 전부 `climax_run` 플래그. 진짜 천정엔 적중(가온칩스 2월 ignore→이후 −29%;
실리콘투·삼양 후반 ignore가 −12~−27% 직전 포착). 그러나 **강한 지속 추세주에 조기 발동**:
HD현대일렉트릭은 2~5월 내내 ignore였으나 이후 **+59~+127%** 추가 상승; 실리콘투 초반(5월) ignore도
이후 +33~+60%.

**볼 파일**: `prompts/analyze_chart_v3.md` §5.1/§6.1(climax 정의)·line 130/136(climax shape 휴리스틱과
verdict 분리 규칙)·§3.3 marginal(line 78–80); risk_flags 산출부.

**질문**: 고RS·장기 지속 추세(예: §3.5의 시장 우호 + RS_line 신고가 + 다중 베이스)에서 `climax_run`
조기 발동을 줄일 조건(예: 추세 지속성/RS 가중, "extended는 watch지 ignore 아님" 규칙의 강화)이
타당한가? §6.1 climax 기준이 "직전 급등 + 단일봉 초대형 거래량"인데, 완만하지만 큰 추세를
과대탐지하는 것은 아닌가?

### 이슈 4 — 무너지는 베이스에 de-rating(강등 경로) 없음
**근거**: 에이팩트(②돌파실패)는 −53%까지 하락하는 동안 계속 `watch / base_forming`. ignore=climax
규율상 "topping(§6.2)"은 ignore지만 실제로는 거의 발동 안 함(전체 ignore 27건 모두 climax). 즉
**서서히 무너지는 베이스(climax 아님)는 게이트 탈락 전까지 경고가 없음**.

**볼 파일**: `prompts/analyze_chart_v3.md` §6.2(topping/Stage 3→4); `kr_pipeline/llm_runner/store.py`
및 status/disqualify 경로(`kr_pipeline/llm_runner/disqualify.py`, `load.py:get_classified_losing_minervini`).

**질문**: §6.2 topping→ignore가 백테스트에서 한 번도 발동하지 않은 것은 정상인가(기준이 너무 좁은가)?
무너지는 베이스(distribution 누적·하위 베이스 이탈)에 대한 단계적 경고/강등이 필요한가?

## 4. 받고 싶은 산출물

1. 이슈 1~4 각각에 대해: **결함인가 / 의도된 동작인가** 판정 + 근거.
2. 결함이라면, 어떤 파일(프롬프트 섹션 / store.py 게이트 / thresholds.py)을 어떻게 바꿔야 하는지
   구체안. (단, 변경 시 `docs/superpowers/threshold-change-checklist.md`의 의존성 맵 점검 필요.)
3. 이 백테스트 설계 자체의 맹점(weekly 한정, 8종목, 단일 연도, forward-return 정의 등)에 대한 지적.
4. 추가로 돌려볼 만한 백테스트(다른 유형/연도/평일 daily_delta 경로 포함) 제안.

## 5. 참고 파일 맵

- 결과 데이터·표: `docs/superpowers/backtest-2024-results.md`
- 재현 쿼리: `scripts/backtest_2024_analysis.sql`
- 프롬프트(판정 규칙): `prompts/analyze_chart_v3.md`
- 결정론 게이트: `kr_pipeline/llm_runner/load.py`
- 분류 후처리 게이트: `kr_pipeline/llm_runner/store.py`
- 백필 실행 경로: `kr_pipeline/llm_runner/backfill.py`
- 임계 상수(SSOT): `kr_pipeline/common/thresholds.py`
- 임계 변경 체크리스트: `docs/superpowers/threshold-change-checklist.md`
