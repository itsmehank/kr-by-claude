# Evaluate Pivot Trigger (5b) v1

## 1. Role and Scope

평일 결정론 트리거 발동 종목에 대해 "오늘 매수 적기인가?" 를 LLM 이 컨펌하는 단계.

**Scope discipline**:
- 분류 (entry/watch/ignore) 재평가 **금지**. prior_analysis 그대로 통과.
- pattern, pivot_price 재산출 **금지**. (5) 가 정한 그대로 사용.
- 출력은 오직 오늘 매수 결정만.

<!-- SSOT-THRESHOLDS -->
이 값들은 `kr_pipeline/common/thresholds.py` 와 동기화됨 (tests/test_prompt_threshold_drift.py 가 검증).
(#22) 정량 게이트는 코드 선계산(`computed_gates`, gate_precompute.py) — 아래 값은 그 계산 기준.
- BREAKOUT_VOL_FLOOR = 1.4
- GATE_PROMOTION_PRICE_RATIO = 0.95
- BREAKOUT_VOL_WAIT_FLOOR = 1.2
- SPREAD_WIDE_LOOSE_MULT = 1.5
- SMA50_BREACH_RATIO = 0.98
- STOCK_DIST_CLEAN_WINDOW_DAYS = 3
- STOCK_DIST_ABORT_WINDOW_DAYS = 5
- STOCK_DIST_ABORT_COUNT_5D = 3
- MARKET_DIST_DEMOTION_COUNT_25S = 5
- TT_MARGIN_MARGINAL_PCT = 3.0
- TT_MARGINAL_DEMOTION_COUNT = 3
<!-- /SSOT-THRESHOLDS -->

## 2. Inputs (JSON)

**가격 데이터 규약:** 제공되는 모든 가격(OHLCV·차트·지표·current_metrics)은 수정주가(split-adjusted) 기준입니다. 분할/액면병합은 이미 반영되어 있으므로 가격 단차로 오인하지 마세요.

- `symbol`, `name`, `market`, `evaluation_date`
- `trigger_type`: "breakout" | "breakout_from_watch" | "invalidation" | "promotion"
- `prior_analysis`: 주말 (5) 결과 (`classified_at`, **`days_since_classification`** (분류 후 경과일), `classification`, `pattern`, `pivot_price`, `pivot_basis`, `base_high`, `base_low`, `base_depth_pct`, `risk_flags`, `reasoning`, **`watch_reason`** (watch 분류 사유 — reasoning 서술 참고용. §3.5 회복 게이트는 사유-독립(#22)이라 판정에는 미사용))
- `recent_daily_ohlcv_20d`: 최근 20영업일 OHLCV 리스트 — 각 행에 **`distribution_day_flag`**(종목 분배일, 결정론 산출) 포함
- `current_metrics`: `close`, `volume`, `avg_volume_50d`, `volume_ratio`, `sma_50`, **`sma_21`** (≈ 20-day line, Minervini *Think & Trade Like a Champion* Ch.1 의 "20-day line" 가드용)
- `market_context`: **현재(평가일 as-of)** 시장 상태 — `current_status`(confirmed_uptrend / rally_attempt / downtrend / correction), `distribution_day_count_last_25_sessions` 등. (§3.5 회복 게이트의 원천 입력 — 판정 자체는 `computed_gates.market_recovery_ok`. 분류시점 아님 — *오늘* 시장.)
- `conditions_met` / `conditions_detail`: **현재** Minervini Trend Template 8조건 boolean + 조건별 통과 마진. (§3.5 회복 게이트의 원천 입력 — 판정 자체는 `computed_gates.tt_recovery_ok`.)
- `rs_rating`: **현재** RS Rating.
- `computed_gates`: **(#22) 정량 게이트 결정론 선계산** — §3 게이트 판정 규약의 authoritative 입력.
  - `price_above_pivot` (close > pivot_price)
  - `volume_ratio`, `volume_band` ("pass" >1.4× / "wait_band" 1.2~1.4× / "below" <1.2×)
  - `close_range_pos`, `close_upper_third`, `close_middle_third` (일중 range 내 종가 위치)
  - `spread_ratio_vs_avg`, `spread_wide_loose` (직전 19거래일 평균 range 대비 오늘 spread, >1.5× = wide)
  - `dist_days_last_3`, `no_dist_3d`, `dist_days_last_5`, `dist_3plus_5d` (종목 분배일 창 카운트)
  - `low_below_base_low`, `close_below_sma50_breach` (close < sma_50×0.98), `close_below_sma21`
  - `market_dist_count`, `market_recovery_ok` (시장 회복: confirmed_uptrend **이고** 시장 분배일 < 강등 임계 5)
  - `tt_all_passed`, `tt_marginal_count`, `tt_recovery_ok` (TT 회복: 8조건 all pass **이고** marginal(<3%) 조건 < 3개)
  - `ohlcv_last_date` (일중값 소스 행 날짜 — halt 직후 current_metrics 와 날짜가 다를 수 있음)
  - 값 `null` = 입력 결측으로 미산출.
- `recent_evaluation_history`: 최근 7일 (5b) 이력 (있을 때만)

## 3. Decision Logic

**게이트 판정 규약 (#22)**: 정량 게이트(가격·거래량·종가 위치·spread·분배일 카운트·이평선
이격·시장/TT 회복)는 `computed_gates` 가 **authoritative** — OHLCV·지표·flag 로 직접
재계산하지 말 것(analyze_chart_v3 §6 의 column-is-authoritative 관례와 동일. 결정론 코드
산출값 — LLM 자체 기준 사용 금지). per-row `distribution_day_flag` 와 원시 OHLCV 는
reasoning 서술의 참고용(reference-only)이며 게이트 재판정에 사용 금지. `computed_gates`
값이 `null` 인 게이트는 미산출로 취급 — **go_now 에 필요한 게이트가 null 이면 go_now 금지**
(wait 로). 결정(go_now/wait/abort)과 비산술 판단(거래량 동반의 의미, squat 회복 여지,
'돌파 직후' 여부, confidence)은 여전히 LLM 몫이다.

### 3.1 trigger_type = "breakout"

`go_now` 조건 (모두 충족 — 전부 `computed_gates` 값 그대로 사용):
- `price_above_pivot == true` (결정론 게이트 이미 확인. 재확인)
- `volume_band == "pass"` (책 근거: O'Neil HTMMIS Ch.2 "Volume Percent Change")
- `close_upper_third == true` (no intraday weakness)
- `spread_wide_loose == false` (wide-and-loose 아님)
- `no_dist_3d == true` (최근 3일 distribution day 없음)

`wait` 조건:
- `volume_band == "wait_band"` (부족하지만 abort 까지는 아님)
- `close_middle_third == true` (weak finish)
- `spread_ratio_vs_avg` 가 wide 임계 부근 경계 (borderline wide — 재량 판단)

`abort` 조건:
- `low_below_base_low == true` (base_low 이탈)
- `close_below_sma50_breach == true` + 거래량 동반 (sma_50 명확 이탈)
- `dist_3plus_5d == true` (최근 5일 distribution day 3+)
- **돌파 직후 20일선 가드 위반** (Minervini *TTLC* Ch.1 "WATCH THE 20-DAY LINE
  SOON AFTER A BASE BREAKOUT"): `days_since_classification` 이 작아 "돌파
  직후 (soon after)" 로 판단되고 (대략 분류 후 4주 이내), `close_below_sma21
  == true` + 거래량 동반/추가 위반 (예: `dist_days_last_5` 누적,
  `spread_wide_loose == true` 등). **단독 sma_21 이탈은 wait 로** — 책이 "단독으론
  의미 없다 (not significant on its own)" 명시.

### 3.2 trigger_type = "invalidation"

`abort`:
- `close_below_sma50_breach == true` (>2% 이탈) + 거래량 동반
- close < prior_analysis.base_low
- **돌파 직후 20일선 가드 추가 적용** (Minervini *TTLC* Ch.1): invalidation
  트리거는 sma_50 이탈 시점에 발동되지만, `days_since_classification` 이 작아
  "돌파 직후" 인 종목에서 `close_below_sma21 == true` 도 이미 위반 + 거래량 동반 시
  abort 신뢰성 증가 (Minervini "성공률 약 절반으로 줄어든다 / cut in about
  half" 표현).

`wait`:
- 위 abort 조건 충족 안 함 (단일 약세일, 베이스 여전히 valid 가능)
- 단독 sma_21 종가 이탈만으로는 wait (책: 단독 무의미)
- 단 squat (되밀림) 가능성 — 며칠~10일 reversal recovery 여지 (Minervini
  *TLSMW* Ch.10).

`go_now` 발생 안 함 (invalidation 트리거에서는).

### 3.3 trigger_type = "promotion"

watch → entry 승격 staging (시스템 자체 설계, 책 근거 없음).
이 시점에 close 는 pivot 의 95% 이상 도달했지만 **아직 pivot 미만일 수
있음** → 매수 부적절. 분류 변경 역시 다음 weekend batch 의 LLM
재분석이 처리하므로, 이 단계에서 결정해서는 안 됨.

`go_now` 발생 안 함 (promotion 트리거에서는).
- **분류별 후속 경로 차이 (중요)**: classification 이 **entry** 인 종목이 close > pivot
  하면 다음 평일 `breakout` 트리거가 별도로 발생해 처리된다. 그러나 **watch** 종목은
  게이트가 breakout 을 발화하지 않으므로 다음 평일 자동 처리가 *일어나지 않는다* —
  watch 의 정당한 돌파는 별도 `trigger_type == "breakout_from_watch"` (§3.5) 가 담당한다
  (단, pivot 유효 사유에 한함). 따라서 promotion 의 "다음에 처리됨" 보장은 entry 경로에만
  성립한다.
- promotion → go_now → entry_params 직행은 pivot 미만 매수를 유발하므로
  금지. 어떤 강도의 거래량이나 인트라데이 강세에서도 `go_now` 반환 금지.

`wait`:
- 거래량/일중 강도 검토 결과 베이스 신뢰성 유지.
- 다음 평일 게이트 평가 또는 다음 weekend batch 의 entry 분류 검토 대기.

`abort`:
- 베이스 무효화 신호 (sma_50 이탈, distribution 누적, base_low 이탈 등).
- 다음 weekend batch 에서 ignore 로 분류될 후보.

### 3.4 abort_reason 키워드 카탈로그

abort 시 다음 중 하나로 정형화:

- `sma50_breach_distribution_volume` — 50일선 명확 이탈 + 거래량 동반
- `sma50_breach_low_volume` — 50일선 이탈, 거래량 적음
- `stop_loss_breach` — base_low 또는 stop level 이탈
- `base_depth_exceeded` — base_depth_pct > 33%
- `distribution_pattern_clear` — 최근 5일 distribution 3+
- `volume_insufficient_intraday_weak` — 오늘 거래량 부족 + 일중 약세
- `spread_wide_loose` — spread wide-and-loose
- `consecutive_weak_days` — 연속 약세 (단일 일시적 아님)

위 외의 사유는 위 키워드 중 가장 가까운 것 선택. 새 키워드 만들지 말 것.

### 3.5 trigger_type = "breakout_from_watch"

watch 분류였으나 pivot 이 유효한 사유(`prior_analysis.watch_reason ∈
{unfavorable_market, marginal_tt, valid_base_awaiting_breakout}`)에서 오늘 거래량 동반
pivot fresh 돌파가 발생한 경우. 기존엔 promotion 으로만 잡혀 토요일 weekend 재분류까지
정당한 돌파를 놓쳤던 갭을 메운다. **분류는 여전히 변경하지 않는다** (§1 scope) — entry_params
직행 여부만 결정.

**공통 표준 돌파 검증 (§3.1 의 go_now 조건과 동일 — `computed_gates`, 먼저 적용)**:
- `price_above_pivot == true` (게이트 fresh_cross 이미 확인. 재확인)
- `volume_band == "pass"` (O'Neil HTMMIS Ch.2)
- `close_upper_third == true` (no intraday weakness)
- `spread_wide_loose == false`
- `no_dist_3d == true`

**회복 게이트 (사유-독립 — watch_reason 무관, `go_now` 는 항상 둘 다 충족 필수):**

- `computed_gates.market_recovery_ok == true` — 시장 회복: `confirmed_uptrend` 이고 시장
  분배일이 강등 임계 미만으로 해소 (analyze_chart_v3 §3.5 의 강등 임계와 co-anchored —
  SSOT MARKET_DIST_DEMOTION_COUNT_25S. status 라벨은 강등 임계 수준의 분배일과 공존
  가능하므로 라벨만으로 회복 판정 금지 — 코드가 둘 다 확인한 값).
- `computed_gates.tt_recovery_ok == true` — Trend Template 회복: 8조건 all pass 이고
  marginal(<3%) 조건 수가 강등 임계 미만 (analyze_chart_v3 §2 의 marginal_tt 강등 기준과
  co-anchored — SSOT TT_MARGINAL_DEMOTION_COUNT).

watch_reason 에 어떤 사유가 기록됐든 **둘 다** 요구한다 — 복수 사유가 동시 성립했는데
하나만 기록된 경우(예: marginal_tt + 시장불안이 `unfavorable_market` 로만 기록)의 재확인
누락(거울 갭)을 구조적으로 차단 (#22, #29 의 flag 조건부 방식 supersede). `watch_reason`·
`risk_flags` 는 reasoning 서술 참고용으로만 사용하고 게이트 판정 근거로 쓰지 말 것.
회복 게이트 미충족(또는 null) → 표준 검증을 충족해도 `wait`.

**공통**: 표준 검증 미충족 → `wait` (`volume_band == "wait_band"` / `close_middle_third` 등)
또는 `abort` (`low_below_base_low` / `close_below_sma50_breach` + 거래량 동반 /
`dist_3plus_5d` — §3.1 abort 조건과 동일).
**돌파 직후 20일선 가드(§3.1)도 동일 적용.**

abort_reason 은 §3.4 카탈로그 사용 (신규 키워드 금지).

## 4. Output Schema

Strict JSON only. No commentary, no markdown:

```json
{
  "decision": "go_now",
  "confidence": 0.78,
  "reasoning": "Pivot 돌파 + 거래량 1.57x + 종가 상단 마감",
  "abort_reason": null
}
```

- `decision`: "go_now" | "wait" | "abort"
- `confidence`: 0.0~1.0
- `reasoning`: ≤200자 한국어
- `abort_reason`: abort 시 §3.4 카탈로그 키워드, 그 외 null

## 5. Constraints

- abort 는 신중히. 단일 약세일은 wait 으로 (베이스 여전히 valid 가능).
- pivot/base/pattern 재산출 금지.
- 새 키워드 만들지 말 것 (§3.4 카탈로그 외).
- reasoning ≤200자 한국어.
- Use ONLY the provided input payload. Do NOT use web search, external lookups, news, or earnings calendars — no information beyond the provided inputs, and no future information.

## Input Payload
