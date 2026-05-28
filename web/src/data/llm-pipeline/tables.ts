// 11 테이블 한 줄 설명 + 컬럼 요약 (StageCard 입출력에 등장하는 것만)
// 근거: kr_pipeline/db/schema.sql

export interface TableInfo {
  name: string;
  short: string;       // 한 줄 친절 설명 (카드 본문에 그대로 표시)
  details: string;     // fold 안 컬럼 요약 (2-3 문장, 핵심 컬럼 명시)
  pkey: string;        // primary key (engineering 정보, fold 안)
}

export const TABLES: Record<string, TableInfo> = {
  daily_indicators: {
    name: "daily_indicators",
    short: "종목별 매일 지표값 — SMA·RS·거래량 평균·각종 flag 등.",
    details:
      "종목 × 날짜별 모든 지표 한 행. 핵심 컬럼: close, sma_50/150/200, rs_rating, avg_volume_50d, volume_ratio_50d, pocket_pivot_flag, distribution_day_flag, minervini_pass (Trend Template 8조건 통과 여부). 매일 cron 으로 적재.",
    pkey: "(ticker, date)",
  },
  weekly_indicators: {
    name: "weekly_indicators",
    short: "종목별 주봉 지표 — 일봉으로부터 W-FRI 리샘플.",
    details:
      "종목 × 주별 지표. 일봉 daily_indicators 를 주봉으로 집계. 핵심 컬럼: weekly close, weekly volume, weekly RS, sma_10w (= 10주 이동평균).",
    pkey: "(ticker, week_end_date)",
  },
  daily_prices: {
    name: "daily_prices",
    short: "종목별 일봉 OHLCV 원시 — 모든 지표의 출발점.",
    details:
      "종목 × 날짜별 시·고·저·종가 + 거래량. 수정종가도 별도 컬럼. 핵심 컬럼: open, high, low, close, adj_close, volume.",
    pkey: "(ticker, date)",
  },
  index_daily: {
    name: "index_daily",
    short: "KOSPI / KOSDAQ 지수 일봉.",
    details:
      "지수 × 날짜별 OHLCV. KOSPI 코드 '1001', KOSDAQ '2001'. 시장 컨텍스트·종목 성과 비교의 기준.",
    pkey: "(index_code, date)",
  },
  market_context_daily: {
    name: "market_context_daily",
    short: "시장 전체 상태 (uptrend / correction / downtrend / rally_attempt).",
    details:
      "지수 × 날짜별 시장 진단. 핵심 컬럼: current_status (4-enum), distribution_day_count_last_25, last_follow_through_day, days_since_follow_through, pct_stocks_above_200d_ma. LLM 의 시장 컨텍스트 입력.",
    pkey: "(date, index_code)",
  },
  corporate_actions: {
    name: "corporate_actions",
    short: "기업 행위 — 액면분할·합병·배당 등.",
    details:
      "종목 × 날짜별 코퍼릿 이벤트 (e.g. 액면분할 1:5). 차트·지표가 분할 직후 왜곡되지 않도록 보정. DART API 로 수집.",
    pkey: "(ticker, event_date, event_type)",
  },
  stocks: {
    name: "stocks",
    short: "KRX 종목 마스터 — 이름·시장·섹터·상장폐지 여부.",
    details:
      "한국거래소의 모든 종목 식별 정보. 핵심 컬럼: ticker, name, market (KOSPI/KOSDAQ), sector, delisted_at (NULL = 상장 중).",
    pkey: "(ticker)",
  },
  weekly_classification: {
    name: "weekly_classification",
    short: "LLM 의 종목 정성 분류 결과 — entry / watch / ignore.",
    details:
      "종목 × 분류시각별 행. *append-only* = 이전 분류 보존, 새 분류는 새 행 추가. '현재 분류' = 가장 최근 행. 핵심 컬럼: classification (entry/watch/ignore), confidence, pattern, pivot_price, base_depth_pct, risk_flags, source (weekend/daily_delta), classified_at.",
    pkey: "(symbol, classified_at)",
  },
  trigger_evaluation_log: {
    name: "trigger_evaluation_log",
    short: "평일 매일 watch/entry 종목의 LLM 트리거 평가 결과.",
    details:
      "종목 × 평가시각별 행. 결정론 게이트가 감지한 트리거 (breakout/promotion/invalidation) 와 LLM 의 결정 (go_now/wait/abort) 기록. 분류는 변경 안 함 (append-only 로그).",
    pkey: "(symbol, evaluated_at)",
  },
  entry_params: {
    name: "entry_params",
    short: "실질 매수 시그널 — LLM 이 산출한 18 필드 매수 계획.",
    details:
      "go_now 결정된 종목의 entry_mode·pivot_price·trigger_price·stop_loss·target·position size·breakout 거래량 요건 등 18 필드 (자세한 풀이는 카드 안 fold). signal_at = 매수 시그널 발생 시각.",
    pkey: "(symbol, signal_at)",
  },
  signal_performance: {
    name: "signal_performance",
    short: "entry_params 시그널의 사후 성과 — 1주·2주·4주·8주 후 가격 + 시장 대비.",
    details:
      "시그널 × 시점별 추적. 핵심 컬럼: price_1w / price_2w / price_4w / price_8w + 같은 기간 KOSPI/KOSDAQ 변화. 8주 후 데이터 채워지면 사실상 추적 종료. 90일 cutoff.",
    pkey: "(symbol, signal_at)",
  },
};
