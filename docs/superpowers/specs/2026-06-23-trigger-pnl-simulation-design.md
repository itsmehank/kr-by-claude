# 2024 결정론 트리거 + P&L 시뮬레이션 (shadow 비교) — 설계

작성일: 2026-06-23

## 목적

2024 주말분류 백테스트(8종목, `classification_backfill` 191건)의 후속. 주말 분류층 backtest는
3층 중 1층만 측정했고, **actionability(매수 트리거)·청산·P&L**이 미측정으로 남았다(이슈 1·2·4의 진짜 답).
이 프로젝트는 가진 watch pivot에 **프로덕션 `trigger_gate.evaluate`를 그대로 적용**해 일봉으로 replay,
매수 트리거 발화·모의 진입→청산 P&L(시장대비)을 **결정론으로** 측정한다.

**명시적 범위 라벨 (결과 문서 최상단에 박을 것)**: 본 시뮬은 **8종목 워치리스트 한정, 결정론 트리거의
하한(lower-bound) 추정**이다. 제외: (a) 평일 `daily_delta`가 주중 발굴하는 *신규* 후보, (b) `evaluate_pivot`
LLM 트리거 확인·abort, (c) `entry_params` LLM 포지션 사이징. "시스템 전체 수익성"이 아니다.

## 비범위 (YAGNI)

- 완전 5단계 LLM replay((A)-full) — 트리거-적격 watch가 7건뿐이라 현 단계 불필요. 본 시뮬이
  "트리거 층이 흥미롭다"를 보이면 후속으로 분리.
- 프로덕션 테이블 쓰기·LLM 호출·샌드박스 격리 인프라 — 본 시뮬은 읽기전용·결정론이라 불필요.
- §6.1/프롬프트/thresholds 변경 — 직전 라운드에서 분류층 단일-층 결함 0건 확정, 변경 근거 없음.

## 핵심 원칙

- **전부 읽기전용·결정론·LLM 0.** 입력 테이블(`classification_backfill`, `daily_prices`,
  `daily_indicators`, `index_daily`)을 읽기만 하고 프로덕션 테이블에 쓰지 않는다.
- **프로덕션 함수 재사용**: 트리거 판정은 `kr_pipeline.llm_runner.compute.trigger_gate.evaluate`를
  그대로 import해 호출(로직 재구현 금지 — 표류·미세오차 방지).
- **격리**: 신설 `kr_pipeline/backtest/`는 프로덕션을 *읽기만* 하고, 프로덕션 파이프라인(cron/modes 등)은
  backtest 를 절대 import 하지 않는다(감사/분석 인프라는 운영 경로를 결합/차단하지 않는다는 원칙).

## 대상

8종목 × 2024(2024-01-06~12-28 분류 + forward 가격은 2025 데이터까지):
003230 삼양식품, 101930 인화정공, 399720 가온칩스, 200470 에이팩트, 257720 실리콘투,
000320 노루홀딩스, 900340 윙입푸드, 267260 HD현대일렉트릭.

## 입력 분류 (프로덕션 / shadow / census)

`classification_backfill`의 watch 행을 watch_reason·pivot_price 유무로 3분류:

| 구분 | watch_reason | 건수 | 트리거 시뮬? |
|---|---|---|---|
| **프로덕션 적격** | unfavorable_market(4) / valid_base_awaiting_breakout(2) / marginal_tt(1) | 7 | YES (시스템이 실제로 했을 행동) |
| **shadow** | extended(pivot有 9) / base_forming(pivot有 5) | 14 | YES (게이트 우회 가정) |
| **census(비actionable)** | pivot 없음 또는 미완성 base 등 | 170 | NO (census로 건수만 표기) |

(건수는 직전 측정 기준 근사 — 구현 시 쿼리로 확정. `trigger_gate`의 ALLOWED_WATCH_REASONS =
{unfavorable_market, marginal_tt, valid_base_awaiting_breakout}.)

## 시뮬레이션 모델 (사전 고정 규칙)

8종목 각각 2024 거래일을 일별 walk하며 이벤트 구동:

- **active pivot**: 직전 토요일 분류 행의 `pivot_price`(+`base_low`=stop, +`watch_reason`). 매 토요일 갱신.
- **promotion 카운트(진입 안 함)**: `trigger_gate.evaluate`는 watch에 `promotion`(close가 pivot의
  95~100% 구간)도 반환. promotion은 책 근거 없는 staging이라 **매수 아님**(`evaluate_pivot §3.3`) → 진입
  미발생. 단 **발화 횟수는 census에 기록** → "적격 watch가 pivot 근처까진 갔으나 끝내 못 넘은" 횟수가
  보여 이슈 2 해석에 도움.
- **트리거 판정(매일)**: `trigger_gate.evaluate(close, pivot_price, volume, avg_volume_50d,
  stop_loss=base_low, sma_50, classification='watch', prev_close, watch_reason)` →
  `breakout_from_watch` / `invalidation` / `promotion` / None. 입력은 **그날(`date<=as_of`)까지만**.
- **진입**: `breakout_from_watch` 발화일 **종가**에 진입.
  - 각주(프로덕션 7건에도 적용): 실제 시스템은 트리거 다음날 `entry_params`가 매수가 산출 → 종가 진입은
    **"하루 슬리피지 없는 근사"**.
- **청산(사전 고정)**: 진입 후 `close < base_low` 또는 `close < sma_50` 첫날 **종가**에 청산.
  목표가 없음(ride-to-stop, 책 정합). **트레이드별로 어느 조건이 binding이었는지 기록**
  (sma_50 vs base_low — 채점엔 미사용, 사후분석용 데이터. 청산 규칙 자체는 변경 금지).
  - 각주(결과 문서): `trigger_gate.evaluate`의 invalidation은 `close<sma_50`/`close<base_low`만 보고
    **거래량을 보지 않는다**(LLM `evaluate_pivot §3.2`는 거래량 동반을 함께 봄). 따라서 본 시뮬 청산은
    LLM invalidation보다 **거래량 없는 이탈에도 더 빨리 파는 보수적 청산** = P&L 하한에 부합(진입도 게이트
    결정론 기준이라 일관). "왜 실제보다 일찍 팔았나" 오해 방지용으로 명시.
- **재진입 상한(사전 고정)**: 청산 후 **active pivot이 새 토요일 분류로 갱신되어야** 재진입 가능.
  같은 pivot에서 반복 진입↔청산(톱니) 금지 — 한 셋업이 다중 트레이드로 부풀려지는 노이즈 차단.
- **look-ahead 차단**: 진입·청산 판정은 그날까지의 일봉만 사용. 트리거~청산 사이 미래가격으로 진입/청산
  결정 금지.

## 채점 metric (사전 고정)

- 트레이드별 P&L: `(exit_close/entry_close - 1)` %.
- **시장대비 초과수익**: 같은 보유기간 동안 해당 종목 시장지수(KOSPI/KOSDAQ, `index_daily`) 수익률을
  차감 → 절대수익이 2024 시장 흐름에 오염되는 것 방지. **이게 1차 채점 기준.**
- forward-return(+4/+12주)은 보조지표로만, 채점 기준 아님.
- 집계: 프로덕션(7)/shadow(14) **두 칸 분리**, shadow는 **사유별(extended/base_forming) 분리**.

## 해석 규율 (결과 문서에 사전 명시)

- 프로덕션/shadow 결과를 **한 표에 섞지 말 것**. shadow는 "게이트 우회 가정"이지 "시스템이 한 일" 아님.
- **shadow 사유별 분리 해석**:
  - `extended`(9): pivot +5% 위 추격 구간. `trigger_gate`의 `fresh_cross`(어제 pivot 이하→오늘 돌파)
    조건상 **대부분 자연 불발 예상**. extended가 shadow에서 0~소수 발화면 = "추격 차단이 가격 조건
    자체로도 정당"(이슈 2에 강한 답). "막아서 못 번 돈"이 아니라 "막아서 피한 위험"일 수 있음.
  - `base_forming`(5): pivot 미확정(핸들 등 정의요소 미완성, `§8.5`)인데 우연히 채워진 경우 → shadow
    트리거는 **미완성 베이스 위 발화**. 여기서 **+수익이 나와도 "미완성 베이스에서 운 좋게 맞은 것"이지
    시스템이 놓친 정당한 기회가 아니다** — 책(O'Neil HMMS, 핸들 shakeout 전 매수 금지)상 막은 게 방법론적으로
    옳다. **base_forming shadow가 +수익이어도 "과보수 증거"로 읽지 말 것.**
  - → **합산 한 숫자로 "과보수 확정" 금지.** 사유별로 "위험 회피였나 vs 기회 손실이었나"를 본다.
- **census(170)**: "watch가 돈을 못 벌었다"가 아니라 "watch 대부분이 **구조적으로 매수 대상이 아니었다**
  (pivot 미확정·미완성 base = 매수 신호 경로가 설계상 막힘)" = 이슈 2의 진짜 답(결함 아닌 설계).
- **표본 한계**: 적격 7 + shadow 14 = 21건, 8종목·2024·큐레이션 패널 → "트리거 층의 행동 방향"을
  보는 존재증명이지 일반화·"과보수 여부 확정"이 아님.
- **비결정성**: 엔진은 결정론이라 단일-run 캐비엇 불필요. 단 입력 `pivot_price`/`base_low`는 **저장된
  1회 LLM 분류본**이므로, 결과는 "그 입력 고정 하의 결정론 산출"이라는 각주.

## 컴포넌트 (모듈 경계)

신설 패키지 `kr_pipeline/backtest/`:

- `trigger_sim.py` — 코어(테스트가능, 순수 함수 중심):
  - `load_watchlist(conn, tickers, start, end) -> list[WatchRow]`: classification_backfill에서 watch 행 로드.
  - `load_daily_series(conn, ticker, ...) -> list[DayBar]`: 일봉(adj_close, volume, sma_50, avg_volume_50d, prev_close).
  - `simulate(watch_rows, day_bars, *, mode='production'|'shadow') -> list[Trade]`: 일별 walk +
    `trigger_gate.evaluate` 호출 + 진입/청산/재진입상한/look-ahead. `Trade` = {ticker, entry_date,
    entry_close, exit_date, exit_close, pnl_pct, binding_exit, watch_reason, ...}.
  - `market_relative(trade, index_series) -> float`: 보유기간 지수수익 차감.
- `__main__.py` (또는 `scripts/`의 얇은 래퍼) — CLI: 8종목/2024 실행 → 결과 표·census 출력 + 결과 문서용 데이터.
- 프로덕션 모듈 import는 `trigger_gate.evaluate` 한 방향만(역방향 import 금지).

## 테스트 (TDD)

`tests/test_backtest_trigger_sim.py` — 합성 가격 시리즈로 단위테스트:

1. fresh cross(어제 pivot 이하→오늘 종가>pivot) + 거래량≥avg×1.0 → `breakout_from_watch` 진입.
2. 종가>pivot이나 거래량 미달 → 미발화(진입 없음).
3. extended형(이미 pivot 위에서 시작, fresh_cross 불성립) → 미발화(자연 차단) 확인.
4. 진입 후 `close<sma_50` → 청산, `binding_exit='sma_50'`.
5. 진입 후 `close<base_low`(>sma_50) → 청산, `binding_exit='base_low'`.
6. 청산 후 같은 pivot 재돌파 → **재진입 안 함**(pivot 갱신 전); 새 pivot 갱신 후 재돌파 → 재진입.
7. look-ahead 가드: 진입/청산 판정이 미래 bar를 참조하지 않음(시리즈를 진입일까지 잘라도 동일 결과).
8. market_relative: 보유기간 지수수익 차감 계산.

`trigger_gate.evaluate`는 프로덕션 기검증이므로 재테스트 안 함 — 호출 결선만 검증.

## 산출물

- 코어 모듈 + 테스트(위).
- 결과 문서 `docs/superpowers/backtest-2024-trigger-sim-results.md`: 범위 라벨(하한) → 프로덕션(7) 표 →
  shadow(14) 표(사유별) → census(170) → 시장대비 초과수익 요약 → 해석(이슈 1·2·4에 대한 답) → 한계.

## 의존성·영향

- thresholds 변경 없음 → threshold-change-checklist 비대상.
- 프로덕션 코드 변경 없음(신설 패키지만 추가, 역import 0). 기존 테스트 baseline 영향 0.
