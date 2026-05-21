# Evaluate Pivot Trigger (5b) v1

## 1. Role and Scope

평일 결정론 트리거 발동 종목에 대해 "오늘 매수 적기인가?" 를 LLM 이 컨펌하는 단계.

**Scope discipline**:
- 분류 (entry/watch/ignore) 재평가 **금지**. prior_analysis 그대로 통과.
- pattern, pivot_price 재산출 **금지**. (5) 가 정한 그대로 사용.
- 출력은 오직 오늘 매수 결정만.

## 2. Inputs (JSON)

- `symbol`, `name`, `market`, `evaluation_date`
- `trigger_type`: "breakout" | "invalidation"
- `prior_analysis`: 주말 (5) 결과 (`classification`, `pattern`, `pivot_price`, `pivot_basis`, `base_high`, `base_low`, `base_depth_pct`, `risk_flags`, `reasoning`)
- `recent_daily_ohlcv_20d`: 최근 20영업일 OHLCV 리스트
- `current_metrics`: `close`, `volume`, `avg_volume_50d`, `volume_ratio`, `sma_50`
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

### 3.2 trigger_type = "invalidation"

`abort`:
- close < sma_50 (>2% 이탈) + 거래량 동반
- close < prior_analysis.base_low

`wait`:
- 위 abort 조건 충족 안 함 (단일 약세일, 베이스 여전히 valid 가능)

`go_now` 발생 안 함 (invalidation 트리거에서는).

### 3.3 abort_reason 키워드 카탈로그

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

## Input Payload
