// LLM Payload ZIP 14~15 파일 (spec audit §7) — zip_builder.py

export interface ZipFile {
  num: number;
  filename: string;
  content: string;
  codeRef: string;
}

export const ZIP_FILES: ZipFile[] = [
  {
    num: 1,
    filename: "README.md",
    content: "2 단계 워크플로우 안내 (Step 1 분류 → Step 2 entry_params)",
    codeRef: "zip_builder.py:21 (README_TEMPLATE)",
  },
  {
    num: 2,
    filename: "prompt_step1_analyze.md",
    content: "analyze_chart_v3.md 사본",
    codeRef: "zip_builder.py:88",
  },
  {
    num: 3,
    filename: "prompt_step2_entry_params.md",
    content: "calculate_entry_params_v2_0.md 사본",
    codeRef: "zip_builder.py:89",
  },
  {
    num: 4,
    filename: "payload.json",
    content: "통합 핵심 데이터 (LLM 입력 핵심)",
    codeRef: "payload_builder.py",
  },
  {
    num: 5,
    filename: "market_context.json",
    content: "시장 컨텍스트 (current_status, distribution_day_count, follow-through day)",
    codeRef: "market_context",
  },
  {
    num: 6,
    filename: "corporate_actions.json",
    content: "액면분할 / reverse split / 자본감소 이력",
    codeRef: "corporate_actions",
  },
  {
    num: 7,
    filename: "minervini.json",
    content: "8 조건 detail (c1-c8 + values + margin_pct, 일봉 기준)",
    codeRef: "minervini_detail_builder.py",
  },
  {
    num: 8,
    filename: "daily.csv",
    content: "종목 60 거래일 OHLCV + 지표",
    codeRef: "csv_builder.py (days=60)",
  },
  {
    num: 9,
    filename: "weekly.csv",
    content: "종목 104 주 OHLCV + 지표",
    codeRef: "csv_builder.py (weeks=104)",
  },
  {
    num: 10,
    filename: "market_index_daily.csv",
    content: "종목 시장의 인덱스 일봉 (KOSPI=1001 또는 KOSDAQ=2001)",
    codeRef: "csv_builder.py (lookback=60)",
  },
  {
    num: 11,
    filename: "market_index_weekly.csv",
    content: "같은 인덱스 주봉",
    codeRef: "csv_builder.py (lookback=104)",
  },
  {
    num: 12,
    filename: "daily_chart.png",
    content: "일봉 차트 이미지 (range_days=365)",
    codeRef: "chart_render.render_daily_chart",
  },
  {
    num: 13,
    filename: "weekly_chart.png",
    content: "주봉 차트 이미지 (range_weeks=104)",
    codeRef: "chart_render.render_weekly_chart",
  },
  {
    num: 14,
    filename: "prompt_verify.md",
    content: "분석 검증 prompt (v1) — 다른 LLM 에 1차 분석 결과 검증 요청용. 5 차원 (분류·패턴·pivot·risk_flag·reasoning) 평가",
    codeRef: "zip_builder.py + prompts/verify_analysis_v1.md",
  },
  {
    num: 15,
    filename: "analysis_result.json",
    content: "weekly_classification 의 최신 분류 1건 (검증 대상). 종목에 분류 이력 있을 때만 포함",
    codeRef: "zip_builder.py:_fetch_latest_analysis_result",
  },
];

export const README_BODY = `# LLM 분석 패키지

이 ZIP 는 종목 {ticker} 의 LLM 분석을 위한 통합 패키지입니다.

## 2 단계 워크플로우

1. **Step 1**: \`prompt_step1_analyze.md\` 와 함께 다음을 입력:
   - \`payload.json\` (텍스트로)
   - \`daily_chart.png\`, \`weekly_chart.png\` (이미지)
   - LLM 출력: classification (entry/watch/ignore) + pattern + pivot + risk_flags

2. **Step 2** (Step 1 결과가 \`entry\` 일 때만): \`prompt_step2_entry_params.md\` 와 함께:
   - \`payload.json\` + Step 1 결과를 \`prior_analysis\` 로 포함
   - \`daily_chart.png\`, \`weekly_chart.png\`
   - LLM 출력: 17 필드 매수 계획

## 파일 목록

- \`payload.json\`: 통합 페이로드 (LLM 입력 핵심)
- \`market_context.json\`: 시장 컨텍스트 (audit)
- \`corporate_actions.json\`: 기업행위 이력 (audit)
- \`minervini.json\`: 8 조건 detail (보조)
- \`daily.csv\` / \`weekly.csv\`: 종목 시계열 (사람용)
- \`market_index_daily.csv\` / \`market_index_weekly.csv\`: 종목 시장 인덱스 시계열 (audit)
- \`daily_chart.png\` / \`weekly_chart.png\`: 차트 이미지 (LLM 멀티모달 입력)
`;
