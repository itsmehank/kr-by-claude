// 5 stage 깊은 카드 데이터 (spec audit §3.1-3.5)
import {
  GATE_BREAKOUT_VOL_MULT,
  BREAKOUT_VOL_FLOOR,
} from "../thresholds.generated";

export interface StageDetail {
  id: string;
  num: number;
  label: string;
  schedule: string;
  inputFilter: string;
  inputFilterCodeRef: string;
  deterministicLogic: string | null;
  promptFile: string;
  promptLines: number;
  promptSummary: string;
  outputTable: string;
  outputColumns: string;
  insertPolicy: string;
  sideEffects: string;
  bookCitations: Array<{
    book: string;
    chapter?: string;
    englishQuote: string;
    koreanSummary: string;
  }>;
  codeRefs: string[];
  notes?: string;
}

export const STAGE_DETAILS: StageDetail[] = [
  {
    id: "weekend",
    num: 1,
    label: "weekend stage",
    schedule: "토 03:20 (KST), cron `20 3 * * 6`",
    inputFilter: `target_date 동적 결정 (load.py:18-24):
- as_of 가 토요일이면 MAX(date) <= as_of 로 직전 금요일 행 사용
- as_of=None 이면 daily_indicators 의 전체 MAX(date)

종목 필터 SQL (load.py:26-39):

SELECT i.ticker, s.market
  FROM daily_indicators i
  JOIN stocks s ON s.ticker = i.ticker
 WHERE i.date = %s
   AND i.minervini_pass = TRUE
   AND s.delisted_at IS NULL
 ORDER BY i.ticker`,
    inputFilterCodeRef: "kr_pipeline/llm_runner/load.py:get_qualifying_tickers",
    deterministicLogic: null,
    promptFile: "prompts/analyze_chart_v3.md",
    promptLines: 309,
    promptSummary:
      "Stage 2 확인 → 시장 컨텍스트 (downtrend/correction 시 watch 강제) → base 패턴 식별 → risk flags 적용 → pivot 산출. 출력: classification + pattern + pivot + risk_flags + confidence + reasoning VCP 패턴일 때 추가 출력: contraction_count (Ts 개수, 2-6) + contraction_depths_pct (수축 깊이 수열) — Minervini footprint 검증성.",
    outputTable: "weekly_classification (kr_pipeline/db/schema.sql:256)",
    outputColumns:
      "symbol, classified_at, analyzed_for_date, market, classification, pattern, pivot_price, pivot_basis, base_high, base_low, base_depth_pct, base_start_date, risk_flags (JSONB), confidence, reasoning, source='weekend', llm_call_duration_s, llm_input_tokens, llm_output_tokens, created_at",
    insertPolicy:
      "ON CONFLICT (symbol, classified_at) DO NOTHING — append-only. '현재 분류' 조회는 DISTINCT ON (symbol) ORDER BY symbol, classified_at DESC.",
    sideEffects:
      "notify_weekend_digest() — Slack digest 알림 (entry/watch/ignore 카운트). End-of-run 1회 retry (weekend.py:66-76) — daily_delta/evaluate_pivot/entry_params 와 다른 정책. 단일 종목 디버깅: weekend.py:38-39 ticker 인자.",
    bookCitations: [
      {
        book: "Minervini, *Trade Like a Stock Market Wizard*",
        chapter: "Ch.5 'Trend Template'",
        englishQuote: "A stock must meet all eight criteria of the Trend Template...",
        koreanSummary: "8조건 모두 충족 종목만 가능 (§4 참조).",
      },
    ],
    codeRefs: [
      "kr_pipeline/llm_runner/modes.py:run_weekend",
      "kr_pipeline/llm_runner/load.py:get_qualifying_tickers",
      "kr_pipeline/llm_runner/weekend.py",
    ],
  },
  {
    id: "daily_delta",
    num: 2,
    label: "daily_delta stage",
    schedule: "평일 20:00 (KST), `llm-full-daily` 1단계",
    inputFilter: `신규 후보 — 오늘 결정론 통과 + 최근 7일 분류 없음 (compute/delta.py:22-37):

SELECT i.ticker
  FROM daily_indicators i
  JOIN stocks s ON s.ticker = i.ticker
 WHERE i.date = %s
   AND i.minervini_pass = TRUE
   AND s.delisted_at IS NULL
   AND NOT EXISTS (
     SELECT 1 FROM weekly_classification wc
      WHERE wc.symbol = i.ticker
        AND wc.classified_at >= %s
   )
 ORDER BY i.ticker

상수: RECENT_WINDOW_DAYS = 7 (compute/delta.py:12)`,
    inputFilterCodeRef: "kr_pipeline/llm_runner/compute/delta.py:find_new_tickers",
    deterministicLogic: null,
    promptFile: "prompts/analyze_chart_v3.md (weekend 와 동일)",
    promptLines: 309,
    promptSummary:
      "weekend 와 동일 prompt. 차이는 입력 필터 (신규 조건) 와 source 컬럼만.",
    outputTable: "weekly_classification",
    outputColumns: "weekend 와 동일 + source='daily_delta'",
    insertPolicy: "weekend 와 동일",
    sideEffects:
      "retry 없음 — weekend 와 다름. 실패 종목은 log only, 다음 평일 cron 에서 후보가 되면 재처리. 전문가 자문 (2026-05-22) 확인 — 데이터 일관성 관점에서 합리적 (대량 batch 아님, 자연 복구).",
    bookCitations: [
      {
        book: "Minervini, *Trade Like a Stock Market Wizard*",
        chapter: "Ch.5 'Trend Template'",
        englishQuote: "A stock must meet all eight criteria of the Trend Template...",
        koreanSummary: "weekend 와 동일 prompt 사용.",
      },
    ],
    codeRefs: [
      "kr_pipeline/llm_runner/compute/delta.py:find_new_tickers",
      "kr_pipeline/llm_runner/daily_delta.py",
    ],
  },
  {
    id: "evaluate_pivot",
    num: 3,
    label: "evaluate_pivot stage",
    schedule: "평일 20:00 (KST), `llm-full-daily` 2단계",
    inputFilter: `3 단계로 구성:

1) Active 종목 조회 (load.py:48-57):
SELECT DISTINCT ON (symbol)
       symbol, classified_at, market, classification, pattern,
       pivot_price, base_low, base_high
  FROM weekly_classification
 ORDER BY symbol, classified_at DESC

2) classification 필터 — Python 리스트 컴프리헨션 (load.py:72):
return [
    {...} for r in rows
    if r[3] in ("entry", "watch")
]

3) 오늘 시장 데이터 조인 + 6 필수 컬럼 NULL 체크 (evaluate_pivot.py:36-40):
if not all(
    a.get(k) is not None
    for k in ("close", "pivot_price", "volume", "avg_volume_50d",
              "stop_loss", "sma_50")
):
    continue

stop_loss = weekly_classification.base_low alias (load.py:109).`,
    inputFilterCodeRef: "kr_pipeline/llm_runner/load.py:get_active_with_current",
    deterministicLogic: `결정론 게이트 (compute/trigger_gate.py:18-52):

# 임계 상수
BREAKOUT_VOLUME_MULTIPLIER = 1.0   # 1.5×→1.0× 완화 (2026-05-21)
PROMOTION_THRESHOLD_RATIO = 0.95   # 시스템 자체 설계, 책 근거 없음

def evaluate(*, close, pivot_price, volume, avg_volume_50d,
             stop_loss, sma_50, classification):
    # 1) 하향 트리거 우선
    if close < stop_loss:
        return "invalidation"
    if close < sma_50:
        return "invalidation"

    # 2) entry: pivot 돌파 + 거래량 >= 평균
    if classification == "entry":
        if close > pivot_price and volume >= avg_volume_50d * 1.0:
            return "breakout"

    # 3) watch: pivot 95% 근접 + 거래량 >= 평균 (staging)
    if classification == "watch":
        if close >= pivot_price * 0.95 and volume >= avg_volume_50d:
            return "promotion"

    return None`,
    promptFile: "prompts/evaluate_pivot_trigger_v1.md",
    promptLines: 127,
    promptSummary: `inline JSON payload (ZIP 아님). build_for_5b 응답:
- symbol, market, evaluation_date, trigger_type
- prior_analysis: classified_at, days_since_classification, classification, pattern, pivot_price, pivot_basis, base_high, base_low, base_depth_pct, risk_flags, reasoning
- recent_daily_ohlcv_20d: 최근 20영업일
- current_metrics: close, volume, avg_volume_50d, volume_ratio, sma_50, sma_21 (≈ 20-day line)
- recent_evaluation_history: 최근 7일 (5b) 이력

Trigger 별 결정 규칙:
- breakout: go_now/wait/abort (${BREAKOUT_VOL_FLOOR.toFixed(1)}× / 일중 상단 / distribution / SMA-21 가드)
- invalidation: abort/wait (SMA-50 이탈 + SMA-21 보조)
- promotion: go_now 발생 안 함 (staging 신호)`,
    outputTable: "trigger_evaluation_log (kr_pipeline/db/schema.sql:293)",
    outputColumns:
      "symbol, evaluated_at, trigger_type, close, volume, pivot_price, decision, confidence, reasoning, abort_reason, prior_classification_at, llm_call_duration_s, llm_input_tokens, llm_output_tokens, created_at",
    insertPolicy:
      "분류는 변경 안 함 (prompt §1). abort decision 이라도 weekly_classification 그대로. 다음 weekend batch 에서 재분류 시 갱신.",
    sideEffects: "retry 없음",
    bookCitations: [
      {
        book: "O'Neil, *How to Make Money in Stocks*",
        chapter: "Ch.2 'Volume Percent Change'",
        englishQuote:
          "Volume should rise 40 to 50% or more above its average daily volume on the day a stock breaks out of its base.",
        koreanSummary:
          `돌파일 거래량 평균 대비 40-50% 이상. 코드는 LLM prompt 에서 정밀 판정 (${BREAKOUT_VOL_FLOOR.toFixed(1)}×), 게이트는 ${GATE_BREAKOUT_VOL_MULT.toFixed(1)}× 로 사전 배제 최소화 (§9 변경 이력).`,
      },
      {
        book: "Minervini, *Think & Trade Like a Champion*",
        chapter: "Ch.1 'WATCH THE 20-DAY LINE SOON AFTER A BASE BREAKOUT'",
        englishQuote:
          "If price closes below the 20-day moving average soon after a proper VCP breakout, the probability of success before getting stopped out is cut in about half.",
        koreanSummary:
          "돌파 직후 20일선 종가 이탈 시 성공률 약 절반으로 감소. 단 책 단서: 단독 무의미, 추가 위반 동반 시 의미.",
      },
    ],
    codeRefs: [
      "kr_pipeline/llm_runner/evaluate_pivot.py",
      "kr_pipeline/llm_runner/load.py:get_active_with_current",
      "kr_pipeline/llm_runner/compute/trigger_gate.py",
      "kr_pipeline/llm_runner/compute/payload_lite.py:build_for_5b",
    ],
  },
  {
    id: "entry_params",
    num: 4,
    label: "entry_params stage",
    schedule: "평일 20:00 (KST), `llm-full-daily` 3단계",
    inputFilter: `🚨 promotion staging 안전장치 포함 (entry_params.py:34-43):

SELECT symbol, evaluated_at, prior_classification_at
  FROM trigger_evaluation_log
 WHERE (evaluated_at AT TIME ZONE 'UTC')::date = %s
   AND decision = 'go_now'
   AND trigger_type = 'breakout'    -- ← 안전장치
 ORDER BY evaluated_at

trigger_type='breakout' 필터로 promotion + go_now 조합이 매수 시그널로 진입 차단 (이중 방어 — prompt §3.3 + 코드).`,
    inputFilterCodeRef: "kr_pipeline/llm_runner/entry_params.py:34-43",
    deterministicLogic: null,
    promptFile: "prompts/calculate_entry_params_v2_0.md",
    promptLines: 580,
    promptSummary: `entry_mode 감지 (prompt §0.5):
- prior_analysis.reasoning 에 "pocket_pivot" 텍스트 → entry_mode = "pocket_pivot"
- 없으면 → entry_mode = "pivot_breakout"
- 정의 값 2개: pivot_breakout | pocket_pivot

dual stop_loss reporting (prompt §2.1-2.4):
- Standard: max(absolute -7.0, logical from base_low) — 더 타이트
- Pocket pivot: max(sma50_pct, logical, absolute -5.5) — 더 타이트
- 모두 floor -10.0 으로 clamp

position_size_pct (prompt §3.1-3.3):
- Base tier (pattern + entry_mode 별 5-15%)
- Risk flag multipliers (cumulative): 대부분 × 0.7, unfavorable_market_context × 0.5
- confidence < 0.7 시 × 0.7
- 최종 clamp [3.0, 25.0]`,
    outputTable: "entry_params (kr_pipeline/db/schema.sql:321)",
    outputColumns: `17 필드:
1. entry_mode (pivot_breakout / pocket_pivot)
2. trigger_price (pivot × 1.001, IBD practice)
3. entry_price
4. stop_loss (절대 가격)
5. stop_loss_pct_from_pivot
6. stop_loss_pct_from_current_price
7. stop_loss_basis (logical / absolute / sma50)
8. expected_target_price
9. expected_target_pct
10. risk_reward_ratio
11. position_size_pct (3-25%)
12. position_size_basis
13. breakout_volume_requirement (ge_1.3x / 1.4x / 1.5x_50day_avg / 1.5x_strict(#74) / pocket_pivot_signature)
14. observed_breakout_volume_ratio
15. known_warnings (JSONB 15 화이트리스트)
16. other_warnings
17. notes (50-600자)`,
    insertPolicy: "PK: (symbol, signal_at)",
    sideEffects: "retry 없음",
    bookCitations: [
      {
        book: "O'Neil, *How to Make Money in Stocks*",
        chapter: "Ch.2-3 'Buy at the Buy Point'",
        englishQuote:
          "Make your buy as the stock is going through its exact pivot point... Do not pursue a stock more than 5% past its pivot point.",
        koreanSummary: "pivot 근처 진입, 5% 추격 한도.",
      },
      {
        book: "Minervini, *Trade Like a Stock Market Wizard*",
        chapter: "'Risk Management'",
        englishQuote: "Risk 1 to 3% of your total portfolio per trade.",
        koreanSummary: "거래당 자본의 1-3% 위험.",
      },
      {
        book: "Morales & Kacher, *Trade Like an O'Neil Disciple*",
        chapter: "Ch.5 'Pocket Pivot'",
        englishQuote:
          "A pocket pivot is an early entry signal that occurs within a base, before the standard pivot point breakout. Pocket pivots should only be bought when they occur above the 50-day moving average ... Except in very rare cases, such as in the aftermath of the crash of late 2008.",
        koreanSummary:
          "Pocket pivot entry 패턴. 필수 조건: 종가가 50일 이동평균 위 (TLOND p.132). 책은 '2008 폭락 직후' 같은 매우 드문 예외를 허용하나, 본 시스템은 §3.5 시장 방향 룰이 그 경우를 watch 로 강제하므로 의도적으로 예외를 두지 않음 (conservative-by-design, 책 위반 아님). 거래량은 직전 10거래일 중 하락일 최대 거래량 초과.",
      },
    ],
    codeRefs: [
      "kr_pipeline/llm_runner/entry_params.py",
      "kr_pipeline/llm_runner/store.py:insert_entry_params",
    ],
  },
  {
    id: "performance",
    num: 5,
    label: "performance stage",
    schedule: "두 실행 경로: 평일 20:00 (full-daily 4단계) + 매일 23:00 (`llm-performance` cron)",
    inputFilter: `지난 90일 entry_params 시그널 + 부분 missing (performance.py:27-40):

SELECT ep.symbol, ep.signal_at, ep.entry_price,
       sp.price_1w, sp.price_2w, sp.price_4w, sp.price_8w,
       sp.market_return_1w_pct, sp.market_return_2w_pct,
       sp.market_return_4w_pct, sp.market_return_8w_pct
  FROM entry_params ep
  LEFT JOIN signal_performance sp
    ON sp.symbol = ep.symbol AND sp.signal_at = ep.signal_at
 WHERE ep.signal_at::date >= %s - INTERVAL '90 days'
   AND ep.signal_at::date <= %s`,
    inputFilterCodeRef: "kr_pipeline/llm_runner/performance.py:27-40",
    deterministicLogic: `LLM 없음. 가격 backfill 만.

기간: PERIODS = [("1w", 7), ("2w", 14), ("4w", 28), ("8w", 56)]  # 달력일

가격 조회 fallback (휴장일 대비):
SELECT adj_close FROM daily_prices
 WHERE ticker = %s AND date <= %s
 ORDER BY date DESC LIMIT 1

market_code: KOSPI=1001, KOSDAQ=2001 (performance.py:59)

계산식:
- return_Nw_pct = (future_price - entry_price) / entry_price * 100
- market_return_Nw_pct = (end_index - base_index) / base_index * 100
- α (alpha) = 종목 - 시장 — UI 계산, DB 직접 저장 안 됨

Skip 조건:
- target_date > as_of (미래 데이터 없음)
- 가격 + 시장수익률 둘 다 이미 있으면 skip`,
    promptFile: "— (LLM 없음)",
    promptLines: 0,
    promptSummary: "LLM 호출 없음. 순수 가격 조회 backfill.",
    outputTable: "signal_performance (kr_pipeline/db/schema.sql:362)",
    outputColumns: "price_1w/2w/4w/8w, return_*_pct, market_return_*_pct, entry_price, updated_at",
    insertPolicy:
      "UPSERT: INSERT ... ON CONFLICT (symbol, signal_at) DO UPDATE SET ..., updated_at = NOW(). 가격이 이미 있으면 시장 수익률만 채우는 부분 갱신 가능.",
    sideEffects: "없음. LLM 호출 없음.",
    bookCitations: [],
    codeRefs: ["kr_pipeline/llm_runner/performance.py"],
    notes: "성과 추적은 시스템 자체 설계 — 책 근거 없음.",
  },
];
