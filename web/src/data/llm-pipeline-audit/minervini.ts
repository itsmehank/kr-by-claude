// Minervini Trend Template 8조건 (spec audit §4)

export interface MinerviniCondition {
  num: number;
  korean: string;
  threshold: string;
  codeRef: string;
  englishOriginal: string;
  note?: string;
}

export const MINERVINI_PASS_FORMULA = `
minervini_pass = (
    minervini_c1 IS TRUE AND minervini_c2 IS TRUE AND
    minervini_c3 IS TRUE AND minervini_c4 IS TRUE AND
    minervini_c5 IS TRUE AND minervini_c6 IS TRUE AND
    minervini_c7 IS TRUE AND (rs_rating >= 70)
)
`.trim();

export const MINERVINI_PASS_REF = "kr_pipeline/indicators/store.py:91-96 (SQL UPDATE SET)";

export const MINERVINI_CONDITIONS: MinerviniCondition[] = [
  {
    num: 1,
    korean: "close > sma_150 AND sma_150 > sma_200",
    threshold: "—",
    codeRef: "minervini.py:27",
    englishOriginal: "Price > MA150 AND MA150 > MA200",
  },
  {
    num: 2,
    korean: "sma_150 > sma_200",
    threshold: "—",
    codeRef: "minervini.py:29",
    englishOriginal: "MA150 > MA200",
  },
  {
    num: 3,
    korean: "오늘 sma_200 > 22거래일 전 sma_200",
    threshold: "22 거래일 (default)",
    codeRef: "minervini.py:31-32",
    englishOriginal: "MA200 trending up for ≥1 month (≥22 trading days)",
    note: "sma_200_lookback=22 default 인자. '연속 상승' 이 아니라 한 번 비교.",
  },
  {
    num: 4,
    korean: "sma_50 > sma_150 AND sma_150 > sma_200",
    threshold: "—",
    codeRef: "minervini.py:34",
    englishOriginal: "MA50 > MA150 > MA200",
  },
  {
    num: 5,
    korean: "close > sma_50",
    threshold: "—",
    codeRef: "minervini.py:36",
    englishOriginal: "Price > MA50",
  },
  {
    num: 6,
    korean: "close ≥ w52_low × 1.25",
    threshold: "1.25×",
    codeRef: "minervini.py:38",
    englishOriginal:
      "Price ≥ 52w-low × 1.25 (TTLC Ch.6 — 최신작) / × 1.30 (TLSMW Ch.5)",
    note: "두 저작 간 버전 차이 — TTLC Ch.6 (+25%) 와 TLSMW Ch.5 (+30%) 모두 책 근거. 우리는 최신작 채택.",
  },
  {
    num: 7,
    korean: "close ≥ w52_high × 0.75",
    threshold: "0.75×",
    codeRef: "minervini.py:40",
    englishOriginal: "Price ≥ 52w-high × 0.75 (within 25% of 52w high)",
  },
  {
    num: 8,
    korean: "rs_rating ≥ 70",
    threshold: "70",
    codeRef: "store.py:91 (SQL UPDATE SET)",
    englishOriginal: "RS Rating ≥ 70",
    note: "RS Rating 개념은 O'Neil HMMS, 임계 70은 Minervini TLSMW Ch.5 — c1-c7 과 함께 minervini_pass 의 8 번째 조건.",
  },
];

export const NAN_POLICY = `
입력 중 하나라도 NaN 이면 조건도 NaN (boolean 강제 안 함, minervini.py:42-55).
SMA 데이터 부족 종목은 minervini_pass = NULL → 게이트 통과 안 함.
`.trim();

export const WEEKLY_MINERVINI_NOTE = `
weekly_indicators 에도 동일 8조건 + minervini_pass 계산 (store.py:168-182).
LLM payload 의 minervini.json 은 일봉 기준 (minervini_detail_builder.py).
`.trim();
