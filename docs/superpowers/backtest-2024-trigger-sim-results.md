# 2024 결정론 트리거 + P&L 시뮬레이션 — 결과

실행일: 2026-06-23 · 도구: `kr_pipeline/backtest/` (읽기전용·결정론, `python -m kr_pipeline.backtest`)
엔진: 프로덕션 `trigger_gate.evaluate` 그대로 호출 · 입력: `classification_backfill`(2024 8종목 watch) + 일봉/지수

## ⚠️ 범위 라벨 (먼저 읽을 것)

본 결과는 **8종목 워치리스트 한정, 결정론 트리거의 하한(lower-bound) 추정**이다.
**제외**: (a) 평일 `daily_delta`가 주중 발굴하는 *신규* 후보, (b) `evaluate_pivot` LLM 트리거 확인·abort,
(c) `entry_params` LLM 포지션 사이징. → **"시스템 전체 수익성"이 아니다.** "이 패널에서 결정론 트리거 층이
어떻게 행동하나"의 존재증명이지 일반화가 아니다.

사전 고정 규칙: 진입=발화일 종가(하루 슬리피지 없는 근사), 청산=`trigger_gate` invalidation
(`close<base_low`/`close<sma_50`, **거래량 미고려 → LLM invalidation보다 빨리 파는 보수적 청산**),
재진입=active pivot(토요일) 갱신 후만, look-ahead 차단. 채점=**시장대비 초과수익**(보유기간 KOSPI/KOSDAQ 차감).

## 입력 분류 (164 watch 행)

| 구분 | 건수 | 트리거 발화 | 비고 |
|---|---|---|---|
| 프로덕션 적격(unfavorable_market·valid_base_awaiting_breakout·marginal_tt) | 7 | **4 트레이드** | 시스템이 실제로 했을 행동 |
| shadow(extended 9 + base_forming 5, pivot有) | 14 | 2 트레이드 | 게이트 우회 가정 |
| census(pivot 없음) | 143 | — | 구조적 매수불가(미완성 base) |

(ignore 27건은 watch 아님 → 본 시뮬 비대상. promotion 발화 176회 = 적격 watch가 pivot 95~100% 근접했으나 못 넘음.)

거래량 단위: 게이트의 `avg_volume_50d`가 **수정 거래량(adj)** 기준이므로 numerator도 `daily_prices.adj_volume`
사용(프로덕션 `daily_indicators.volume`와 동일). raw 사용 시 기업행위 종목(인화정공 raw=0.2×adj, 윙입푸드
=4×adj) 오발화 — 최종 리뷰에서 교정(cf. `payload_raw_vs_adj_volume_mismatch`). 교정 후 4 프로덕션·2 shadow
트레이드는 불변, promotion 카운트만 118→176 변동.

## 1. 프로덕션 (적격 7행 → 4 트레이드) — 모두 sma_50 추세이탈로 청산

| 종목 | watch_reason | 진입 | 청산 | P&L | **시장초과** | binding |
|---|---|---|---|---|---|---|
| 실리콘투 257720 | valid_base_awaiting_breakout | 2024-02-21 @10,400 | 2024-07-25 @42,400 | **+307.7%** | **+315.4%** | sma_50 |
| HD현대일렉트릭 267260 | valid_base_awaiting_breakout | 2024-01-08 @92,800 | 2024-07-22 @294,000 | **+216.8%** | **+209.2%** | sma_50 |
| 인화정공 101930 | unfavorable_market | 2024-06-14 @2,812 | 2024-08-13 @4,100 | **+45.8%** | +57.1% | sma_50 |
| 노루홀딩스 000320 | unfavorable_market | 2025-02-13 @13,990 | 2025-03-31 @13,620 | −2.6% | +1.3% | sma_50 |

→ 4 트레이드 중 **3 대형 승리 + 1 소폭 손실**. 시장초과 평균 ≈ **+146%**. 전부 추세이탈(sma_50)로 청산.

## 2. shadow (비적격 pivot有 14행 → 2 트레이드, 사유별 분리)

| 사유 | 발화 | 결과 |
|---|---|---|
| **extended (9행)** | **0** | 발화 없음 |
| **base_forming (5행)** | 2 | 실리콘투 +294.4%(초과 +305.0%) / 노루홀딩스 −3.4%(초과 +1.5%) |

(shadow = "게이트가 막지 않았다면"의 가정, 시스템이 한 일 아님.)

## 3. 해석 (이슈 1·2·4에 대한 답)

**이슈 1 (entry=0) 해소.** "entry 분류 0"이 "매수 없음"을 뜻하지 않았다. **actionable 매수는 watch에 붙은
pivot의 `breakout_from_watch` 트리거**에서 나오며, 적격 7행이 발화한 4 트레이드가 2024 대형 상승
(실리콘투 +308%·HD현대 +217%·인화정공 +46%)을 **실제로 포착**했다. 트리거 층은 의도대로 작동.

**이슈 3 (climax 과민) — 보유자에겐 무의미.** HD현대는 **1월 breakout_from_watch로 진입해 7월까지
추세이탈 전 보유**(+217%). 직전 라운드에서 우려한 2~5월 climax-ignore 들은 **신규 진입만 막을 뿐 보유
포지션을 청산시키지 않는다** → 이미 진입한 사람에겐 그 상승을 다 가져간다. climax-ignore "상승 놓침"
우려는 트리거 진입 + 추세 보유 구조에선 대부분 무의미함이 확인됨.

**이슈 2 (과보수?) — 증거 없음. 차단은 구조적으로 정당.**
- **extended shadow = 0 발화**: 게이트를 우회해도 `fresh_cross`(어제 pivot 이하→오늘 돌파) 가격조건이
  성립 안 함(이미 +5% 위 추격 구간) → **추격 차단이 가격조건 자체로 정당.** "막아서 못 번 돈" 아님.
- **base_forming shadow**: 유일한 +수익(실리콘투 +294%)은 **프로덕션이 이미 잡은 같은 상승**(다른 pivot
  날짜일 뿐, 추가로 놓친 돈이 아님). 책(O'Neil, 핸들 shakeout 전 매수 금지)상 미완성 베이스 매수 차단이
  방법론적으로 옳다 — **+수익이어도 "과보수 증거"가 아니라 "미완성 베이스 우연 적중".**
- **census 143**: watch의 대부분이 **pivot 미확정 = 구조적으로 매수 대상이 아님**(base forming). 이게
  이슈 2의 진짜 답 — "watch가 돈을 못 벌었다"가 아니라 "watch 대부분이 설계상 매수 신호 경로 밖".

**종합**: 결정론 트리거 층은 (이 패널에서) 큰 상승을 포착했고, 적격 게이트가 막은 것들(extended/base_forming)은
가격조건·방법론상 막은 게 정당했다. **분류 층·트리거 층·게이트 모두 결함 신호 없음.**

## 4. 한계

- **소표본**: 6 트레이드(프로덕션 4 + shadow 2), 8종목·2024·큐레이션 패널 → 방향성 존재증명, 일반화 아님.
- **하한 추정**: 신규후보·LLM 확인·사이징 제외(범위 라벨). 실제 시스템 P&L과 다를 수 있음.
- **청산 보수성**: `trigger_gate` invalidation은 거래량 미고려 → LLM invalidation보다 빨리 청산
  (P&L 하한에 부합). 전 트레이드 binding=sma_50(base_low 청산 0건).
- **진입 근사**: 발화일 종가 진입 = 하루 슬리피지 없는 가정(실제는 다음날 entry_params 산출).
- **입력 비결정성**: 엔진은 결정론이나, 입력 pivot_price/base_low는 **저장된 1회 LLM 분류본** 고정.
- 노루홀딩스 2건은 2024 watch가 **2025-02에 트리거** → forward 가격(2025) 의존, 2025-03-31 데이터 말미 청산.

## 재현

```bash
uv run python -m kr_pipeline.backtest        # JSON: production/shadow/census + 트레이드별 pnl/excess/binding
uv run pytest tests/test_backtest_trigger_sim.py -q   # 13 단위테스트
```
