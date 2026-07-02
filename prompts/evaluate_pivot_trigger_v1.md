# Evaluate Pivot Trigger (5b) v1

## 1. Role and Scope

평일 결정론 트리거 발동 종목에 대해 "오늘 매수 적기인가?" 를 LLM 이 컨펌하는 단계.

**Scope discipline**:
- 분류 (entry/watch/ignore) 재평가 **금지**. prior_analysis 그대로 통과.
- pattern, pivot_price 재산출 **금지**. (5) 가 정한 그대로 사용.
- 출력은 오직 오늘 매수 결정만.

## 2. Inputs (JSON)

**가격 데이터 규약:** 제공되는 모든 가격(OHLCV·차트·지표·current_metrics)은 수정주가(split-adjusted) 기준입니다. 분할/액면병합은 이미 반영되어 있으므로 가격 단차로 오인하지 마세요.

- `symbol`, `name`, `market`, `evaluation_date`
- `trigger_type`: "breakout" | "breakout_from_watch" | "invalidation" | "promotion"
- `prior_analysis`: 주말 (5) 결과 (`classified_at`, **`days_since_classification`** (분류 후 경과일), `classification`, `pattern`, `pivot_price`, `pivot_basis`, `base_high`, `base_low`, `base_depth_pct`, `risk_flags`, `reasoning`, **`watch_reason`** (watch 분류 사유 — `trigger_type == "breakout_from_watch"` 일 때 §3.5 분기 결정에 사용; 그 외 무관))
- `recent_daily_ohlcv_20d`: 최근 20영업일 OHLCV 리스트
- `current_metrics`: `close`, `volume`, `avg_volume_50d`, `volume_ratio`, `sma_50`, **`sma_21`** (≈ 20-day line, Minervini *Think & Trade Like a Champion* Ch.1 의 "20-day line" 가드용)
- `market_context`: **현재(평가일 as-of)** 시장 상태 — `current_status`(confirmed_uptrend / rally_attempt / downtrend / correction), `distribution_day_count_last_25_sessions` 등. (§3.5 `unfavorable_market` 분기 입력. 분류시점 아님 — *오늘* 시장.)
- `conditions_met` / `conditions_detail`: **현재** Minervini Trend Template 8조건 boolean + 조건별 통과 마진. (§3.5 `marginal_tt` 분기 입력.)
- `rs_rating`: **현재** RS Rating.
- `recent_evaluation_history`: 최근 7일 (5b) 이력 (있을 때만)

## 3. Decision Logic

### 3.1 trigger_type = "breakout"

`go_now` 조건 (모두 충족):
- close > pivot_price (결정론 게이트 이미 확인. 재확인)
- volume > avg_volume_50d × 1.4 (책 근거: O'Neil HTMMIS Ch.2 "Volume Percent Change")
- 종가가 일중 range 의 상단 1/3 (no intraday weakness)
- spread (high − low) wide-and-loose 아님 (최대 평균 range 의 1.5x)
- 최근 3일 distribution day 없음

`wait` 조건:
- volume 1.2~1.4× 사이 (부족하지만 abort 까지는 아님)
- 종가가 일중 range 중간 1/3 (weak finish)
- spread borderline wide

`abort` 조건:
- base_low 이탈 (today's low < base_low)
- sma_50 명확 이탈 (close < sma_50 × 0.98 + 거래량 동반)
- 최근 5일 distribution day 3+ 발생
- **돌파 직후 20일선 가드 위반** (Minervini *TTLC* Ch.1 "WATCH THE 20-DAY LINE
  SOON AFTER A BASE BREAKOUT"): `days_since_classification` 이 작아 "돌파
  직후 (soon after)" 로 판단되고 (대략 분류 후 4주 이내), `close < sma_21`
  종가 이탈 + 거래량 동반/추가 위반 (예: 직전 며칠 distribution 누적,
  spread wide-and-loose 등). **단독 sma_21 이탈은 wait 로** — 책이 "단독으론
  의미 없다 (not significant on its own)" 명시.

### 3.2 trigger_type = "invalidation"

`abort`:
- close < sma_50 (>2% 이탈) + 거래량 동반
- close < prior_analysis.base_low
- **돌파 직후 20일선 가드 추가 적용** (Minervini *TTLC* Ch.1): invalidation
  트리거는 sma_50 이탈 시점에 발동되지만, `days_since_classification` 이 작아
  "돌파 직후" 인 종목에서 `close < sma_21` 도 이미 위반 + 거래량 동반 시
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

**공통 표준 돌파 검증 (§3.1 과 동일 — 먼저 적용)**:
- close > pivot_price (게이트 fresh_cross 이미 확인. 재확인)
- volume > avg_volume_50d × 1.4 (O'Neil HTMMIS Ch.2)
- 종가가 일중 range 상단 1/3 (no intraday weakness)
- spread wide-and-loose 아님 (≤ 평균 range 1.5x)
- 최근 3일 distribution day 없음

**watch_reason 별 추가 게이트 (go_now 허용 조건):**

- `valid_base_awaiting_breakout`: 위 공통 표준 검증 충족 시 `go_now`.
  (base 가 이미 신뢰 가능 — entry 와 동등 취급.)
- `unfavorable_market`: 강등 사유가 시장이었으므로 **`market_context.current_status ==
  "confirmed_uptrend"` (회복) 일 때만** `go_now`. 여전히 downtrend/correction/미확인
  rally_attempt 면 표준 검증을 충족해도 `wait` (시장이 아직 안 받쳐줌). ⚠ `watch_reason`
  값 자체를 회복 근거로 쓰지 말 것 — 반드시 입력 `market_context`(현재 값)로 판단.
- `marginal_tt`: 강등 사유가 marginal Trend Template 이었으므로 **현재 `conditions_met` 8개가
  모두 true 이고 `conditions_detail` 상 경계(마진 <3%)가 해소(clean)됐을 때만** `go_now`.
  아직 여러 조건이 marginal 이면 `wait`.

**공통**: 위 표준 검증 미충족 → `wait` (거래량 1.2~1.4× / 중간 1/3 마감 등) 또는 `abort`
(base_low 이탈 / sma_50 명확 이탈 / distribution 누적 — §3.1 abort 조건과 동일).
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
- `abort_reason`: abort 시 §3.3 카탈로그 키워드, 그 외 null

## 5. Constraints

- abort 는 신중히. 단일 약세일은 wait 으로 (베이스 여전히 valid 가능).
- pivot/base/pattern 재산출 금지.
- 새 키워드 만들지 말 것 (§3.3 카탈로그 외).
- reasoning ≤200자 한국어.
- Use ONLY the provided input payload. Do NOT use web search, external lookups, news, or earnings calendars — no information beyond the provided inputs, and no future information.

## Input Payload
