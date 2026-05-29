// 11 테이블 한 줄 설명 + 컬럼 요약 (StageCard 입출력에 등장하는 것만)
// 근거: kr_pipeline/db/schema.sql

export interface TableInfo {
  name: string;
  short: string;              // 한 줄 친절 설명 (카드 본문에 표시)
  summary: string;            // fold 안 도입 한 줄 (각 행의 의미 + 적재 주기 등)
  keyColumns: string[];       // 핵심 컬럼 list (각 한 항목)
  note?: string;              // 추가 비고 (옵션)
  pkey: string;               // primary key (engineering 정보, fold 안)
}

export const TABLES: Record<string, TableInfo> = {
  daily_indicators: {
    name: "daily_indicators",
    short: "종목별 매일 지표값 — SMA·RS·거래량 평균·각종 flag 등.",
    summary: "종목 × 날짜별로 모든 지표가 한 행에 정리.",
    keyColumns: [
      "close (종가)",
      "sma_50 / sma_150 / sma_200 (이동평균)",
      "rs_rating (상대 강도, 0-99)",
      "avg_volume_50d (50일 거래량 평균)",
      "volume_ratio_50d (당일 / 50일 평균)",
      "pocket_pivot_flag (포켓 피벗 발생 여부)",
      "distribution_day_flag (종목 distribution day 여부)",
      "minervini_pass (Trend Template 8조건 통과)",
    ],
    note: "매일 cron 으로 적재.",
    pkey: "(ticker, date)",
  },
  weekly_indicators: {
    name: "weekly_indicators",
    short: "종목별 주봉 지표 — 일봉으로부터 W-FRI 리샘플.",
    summary: "일봉 daily_indicators 를 주봉으로 집계.",
    keyColumns: [
      "weekly close (주간 종가)",
      "weekly volume (주간 거래량 합)",
      "weekly RS (주간 상대 강도)",
      "sma_10w (10주 이동평균)",
    ],
    pkey: "(ticker, week_end_date)",
  },
  daily_prices: {
    name: "daily_prices",
    short: "종목별 일봉 OHLCV 원시 — 모든 지표의 출발점.",
    summary: "종목 × 날짜별 시·고·저·종가 + 거래량 + 수정종가.",
    keyColumns: [
      "open, high, low, close",
      "adj_close (수정종가, 분할·배당 보정)",
      "volume",
    ],
    pkey: "(ticker, date)",
  },
  index_daily: {
    name: "index_daily",
    short: "KOSPI / KOSDAQ 지수 일봉.",
    summary: "지수 × 날짜별 OHLCV — 시장 컨텍스트·종목 성과 비교의 기준.",
    keyColumns: [
      "KOSPI 코드 '1001', KOSDAQ '2001'",
      "open, high, low, close, volume",
    ],
    pkey: "(index_code, date)",
  },
  market_context_daily: {
    name: "market_context_daily",
    short: "시장 전체 상태 (uptrend / correction / downtrend / rally_attempt).",
    summary: "지수 × 날짜별 시장 진단 — LLM 의 시장 컨텍스트 입력.",
    keyColumns: [
      "current_status (4-enum: confirmed_uptrend / correction / downtrend / rally_attempt)",
      "distribution_day_count_last_25 (최근 25 세션 distribution 카운트)",
      "last_follow_through_day (마지막 FTD 발생일)",
      "days_since_follow_through (FTD 이후 경과일)",
      "pct_stocks_above_200d_ma (200일선 위 종목 비율)",
    ],
    pkey: "(date, index_code)",
  },
  corporate_actions: {
    name: "corporate_actions",
    short: "기업 행위 — 액면분할·합병·배당 등.",
    summary: "종목 × 날짜별 코퍼릿 이벤트. 차트·지표가 분할 직후 왜곡되지 않도록 보정.",
    keyColumns: [
      "event_type (액면분할·합병·배당·자본감소 등)",
      "ratio (e.g. '1:5')",
      "event_date",
      "dart_rcept_no (DART 접수번호)",
    ],
    note: "DART API 로 수집.",
    pkey: "(ticker, event_date, event_type, dart_rcept_no)",
  },
  stocks: {
    name: "stocks",
    short: "KRX 종목 마스터 — 이름·시장·섹터·상장폐지 여부.",
    summary: "한국거래소의 모든 종목 식별 정보.",
    keyColumns: [
      "ticker (종목코드)",
      "name (종목명)",
      "market ('KOSPI' / 'KOSDAQ')",
      "sector",
      "delisted_at (NULL = 상장 중)",
    ],
    pkey: "(ticker)",
  },
  weekly_classification: {
    name: "weekly_classification",
    short: "LLM 의 종목 정성 분류 결과 — entry / watch / ignore.",
    summary: "종목 × 분류시각별 행. *append-only* = 이전 분류 보존, 새 분류는 새 행 추가. '현재 분류' = 가장 최근 행.",
    keyColumns: [
      "classification ('entry' / 'watch' / 'ignore')",
      "confidence (0.0-1.0)",
      "pattern (9 base 패턴 중 하나)",
      "pivot_price (책 정의 매수 기준가)",
      "base_depth_pct (base 깊이 %)",
      "risk_flags (JSONB, 13 risk flag 중 부분집합)",
      "source ('weekend' / 'daily_delta')",
      "classified_at",
    ],
    pkey: "(symbol, classified_at)",
  },
  trigger_evaluation_log: {
    name: "trigger_evaluation_log",
    short: "평일 매일 watch/entry 종목의 LLM 트리거 평가 결과.",
    summary: "종목 × 평가시각별 행. 분류는 변경 안 함 (append-only 로그).",
    keyColumns: [
      "trigger_type ('breakout' / 'promotion' / 'invalidation')",
      "decision ('go_now' / 'wait' / 'abort')",
      "evaluated_at",
    ],
    pkey: "(symbol, evaluated_at)",
  },
  entry_params: {
    name: "entry_params",
    short: "실질 매수 시그널 — LLM 이 산출한 18 필드 매수 계획.",
    summary: "go_now 결정된 종목의 매수 계획. 자세한 18 필드는 위 'AI 가 채우는 매수 계획 18 필드' fold 참조.",
    keyColumns: [
      "entry_mode ('pivot_breakout' / 'pocket_pivot')",
      "pivot_price, trigger_price",
      "stop_loss + 손절 % (pivot 기준 / 현재가 기준 두 값)",
      "expected_target_price + 목표 %",
      "suggested_weight_pct (포지션 사이즈 %)",
      "signal_at (시그널 발생 시각)",
    ],
    pkey: "(symbol, signal_at)",
  },
  signal_performance: {
    name: "signal_performance",
    short: "entry_params 시그널의 사후 성과 — 1주·2주·4주·8주 후 가격 + 시장 대비.",
    summary: "시그널 × 시점별 추적. 8주 후 데이터 채워지면 사실상 추적 종료. 90일 cutoff.",
    keyColumns: [
      "price_1w / price_2w / price_4w / price_8w",
      "market_return_1w / 2w / 4w / 8w (같은 기간 KOSPI/KOSDAQ 변화)",
    ],
    pkey: "(symbol, signal_at)",
  },
};
