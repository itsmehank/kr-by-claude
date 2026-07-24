// 주식·책·시스템 용어집 — LlmPipelinePage 의 Glossary 섹션 + TermTooltip 둘 다 사용.

export interface GlossaryEntry {
  term: string;
  meaning: string;
}

export const GLOSSARY: GlossaryEntry[] = [
  // ─── 분류·시그널 차원 (현 분류 ↔ 활성 매수 시그널 구분) ───
  { term: "classification", meaning: "AI 의 종목 정성 분류 — entry / watch / ignore 중 하나. weekly_classification.classification 컬럼. 자주 안 바뀜 (주 1회 weekend 또는 평일 신규 분류 시에만)." },
  { term: "signal (매수 시그널)", meaning: "entry_params 테이블의 새 행 — 실질 매수 활성 여부. classification 과 별개 차원 — 분류는 'AI 가 보기에 좋은 종목인가', 시그널은 '지금 이 가격에 사도 되나'." },
  { term: "현재 분류", meaning: "weekly_classification 의 한 종목의 가장 최근 행. SQL: DISTINCT ON (symbol) ORDER BY classified_at DESC. UPDATE 하지 않고 새 행 누적." },
  { term: "분류 변경", meaning: "weekly_classification 에 새 행이 추가되어 '현재 분류' 가 바뀌는 것. weekend 또는 daily_delta 만 변경 가능. 평일 트리거 평가 (evaluate_pivot) 는 분류 변경 안 함." },

  // ─── 책 용어 — 패턴·매수 기준 ───
  { term: "Trend Template (8조건)", meaning: "Minervini *TLSMW Ch.5* 의 강세 종목 식별 8 기준. 가격이 SMA-50/150/200 위, SMA 정렬, 200일선 상승 추세, 52주 고점 25% 이내, 52주 저점 25% 이상, RS Rating ≥70 등. 시스템의 1차 결정론 필터." },
  { term: "RS Rating", meaning: "Relative Strength Rating (상대 강도). 전체 종목 대비 가격 상승률의 백분위 (0-99). 70 이상이 책 기준 (Minervini), 80+ 가 O'Neil 선호. 같은 종목 풀 안에서의 *상대* 측정." },
  { term: "base (베이스)", meaning: "주가가 옆으로 정리되는 구간 — 컵·평평한 박스·VCP·이중바닥 등 10 종. 돌파 전의 매수 준비 단계." },
  { term: "pivot (피벗)", meaning: "책에서 권하는 *정확한 매수 기준가*. 패턴별로 다르게 정의 — cup_with_handle 은 손잡이 고점, flat_base 는 범위 상단 등." },
  { term: "breakout (돌파)", meaning: "종가가 pivot 위로 올라간 사건. 거래량 동반이면 진짜 돌파, 아니면 가짜 돌파 가능성." },
  { term: "pocket pivot (포켓 피벗)", meaning: "Morales/Kacher *TLOND Ch.5* 의 *조기 매수 신호*. base 안에서 거래량이 직전 10일 중 하락일 최대 거래량을 초과 + 종가가 SMA-50 위. 표준 pivot 돌파 *전* 의 매수 기회." },
  { term: "3c_cheat (cheat 진입)", meaning: "Minervini *TLSMW Ch.10* 의 *cup 형성 중 조기 매수 지점* — cup 아랫쪽 1/3 또는 가운데 1/3 의 small pause. 표준 handle 보다 일찍 진입." },
  { term: "VCP (Volatility Contraction Pattern)", meaning: "Minervini 의 핵심 패턴 — 연속된 *수축* (각 수축이 직전의 약 절반) + 거래량 동반 수축, 2-6 회 (보통 2-4)." },

  // ─── 시장 컨텍스트 용어 ───
  { term: "distribution day", meaning: "*기관 매도일* — 시장 지수 종가 ≥0.2% 하락 + 거래량이 전일보다 증가. 25 세션 내 5+ 누적이면 시장 약세 경고. 시장 distribution 과 종목 distribution 은 별개 (종목은 -0.2% + 1.0× 50일평균)." },
  { term: "follow-through day (FTD)", meaning: "조정 끝 강세 전환 확인 신호 — 저점 후 3-15일째 (최적 4-7일) 의 시장 지수가 +1.4% 이상 상승 + 전일 대비 거래량 증가. confirmed_uptrend 진입의 필수 조건." },
  { term: "confirmed_uptrend / correction / downtrend / rally_attempt", meaning: "시장 4-enum 상태. market_context_daily.current_status. uptrend = 매수 적기, correction/downtrend = 매수 자제, rally_attempt = FTD 대기." },
  { term: "Stage 2", meaning: "Minervini 의 종목 사이클 4 단계 중 *기관 누적 + 상승* 구간. 매수 적기. Stage 1=base, Stage 3=배포/정점, Stage 4=하락." },

  // ─── 트리거 / 결정 / 사이징 ───
  { term: "trigger (트리거)", meaning: "결정론 게이트가 감지한 *오늘의 이벤트* — breakout / promotion / invalidation 셋 중 하나." },
  { term: "decision (AI 결정)", meaning: "evaluate_pivot 의 LLM 응답 — go_now (지금 사라) / wait (기다려) / abort (가짜·무효) 셋 중 하나. 트리거 + 결정 9 조합 매트릭스." },
  { term: "go_now / wait / abort", meaning: "AI 의 트리거 대응 결정 3종. go_now 만이 매수 계획 생성으로 연결. 단 promotion·invalidation 에선 go_now 차단 (안전장치)." },
  { term: "entry / watch / ignore", meaning: "AI 의 분류 3종. entry = 매수 적합, watch = 베이스 형성 중 (돌파 대기), ignore = 부적합 (pattern·market·risk 사유)." },
  { term: "disqualified", meaning: "시스템 강등 — LLM 분류가 아님. 분류(entry/watch/ignore)된 종목이 미너비니 결정론 필터를 탈락하면 평일 disqualify 스윕이 자동 기록하는 4번째 분류 값. 패턴·확신도 없음." },
  { term: "stop loss (손절선)", meaning: "이 가격 아래로 종가가 떨어지면 즉시 매도하는 안전 장치. O'Neil 룰: pivot 대비 -7~-8% 절대 한계 / Minervini 룰: 기대 수익의 절반." },
  { term: "risk-reward (RR)", meaning: "기대 수익 ÷ 손실 한도 비율. 예: 손절 -5%, 목표 +20% → RR = 4.0. 일반적으로 ≥3.0 권장." },

  // ─── 시스템 용어 ───
  { term: "결정론 게이트 (deterministic gate)", meaning: "AI 호출 *전* 의 코드 룰 1차 필터. 단순 SQL/계산으로 종목을 거름. AI 호출 비용을 줄이고 잡음 차단." },
  { term: "prompt", meaning: "AI 에게 주는 지시문 (markdown 파일). 본 시스템은 3 prompt 사용 — analyze_chart_v3 (분류), evaluate_pivot_trigger (트리거 평가), calculate_entry_params (매수 계획)." },
  { term: "ZIP 13 파일", meaning: "AI 가 종목 1건 분석 시 받는 자료 묶음 — 차트 PNG, 일/주봉 CSV, 시장 컨텍스트, corporate actions, minervini 진단 등 13 개 파일." },
  { term: "weekend batch", meaning: "토 03:20 cron 으로 실행되는 *전체 재분류* — 결정론 통과한 모든 종목을 AI 가 다시 평가. weekly_classification 에 source='weekend' 로 행 추가." },
  { term: "daily_delta", meaning: "평일 매일 *신규 후보만* AI 분류 — 최근 7일 안에 분류된 적 없는 새 종목. weekly_classification 에 source='daily_delta' 로 행 추가." },
  { term: "신규 종목 (7일 cool-down)", meaning: "결정론 통과 + 최근 7일 안에 분류 이력 없음. daily_delta 의 대상 조건. 같은 종목 반복 분석 방지 + ignore 후 재진입 허용." },
  { term: "append-only (추가만)", meaning: "DB 에 UPDATE 하지 않고 새 행만 추가하는 설계. 분류 이력 보존 + 시점별 추적 가능. '현재 상태' 는 가장 최근 행으로 조회." },
  { term: "cron", meaning: "정해진 시각에 자동 실행되는 작업 스케줄러 (Linux 표준). 본 시스템은 평일 20:00 (LLM 4 단계) + 토 03:20 (weekend) + 19:30 (데이터 적재) 등." },
  { term: "dry-run", meaning: "AI 호출은 mock 응답으로 대체 + DB INSERT 도 skip. 코드 흐름 검증용 read-only 모드." },
  { term: "Slack digest", meaning: "weekend batch 완료 후 entry/watch/ignore 카운트를 Slack 채널에 요약 알림. 사용자에게 *오늘 무슨 일이 있었나* 한눈에 보고." },
  { term: "OHLCV", meaning: "Open / High / Low / Close / Volume — 시·고·저·종가 + 거래량. 일봉/주봉 데이터의 표준 5 필드." },
  { term: "SMA (이동평균)", meaning: "Simple Moving Average — N일 평균 종가. SMA-50 / SMA-150 / SMA-200 이 Trend Template 의 핵심 지표." },
];


// O(1) 조회용 Map — TermTooltip 이 사용.
// key 는 term 의 정규화된 lookup key (소문자, 공백 → underscore).
// 같은 의미를 다른 key 로도 접근하기 위한 alias 도 함께 등록.
export const GLOSSARY_MAP: Record<string, string> = (() => {
  const map: Record<string, string> = {};
  for (const g of GLOSSARY) {
    // 정규화: 첫 단어를 key 로
    const primary = g.term.split(" ")[0].split("/")[0].trim();
    map[primary] = g.meaning;
    // 전체 term 으로도 등록
    map[g.term] = g.meaning;
  }
  // 자주 쓰이는 alias 직접 등록
  const aliases: [string, string][] = [
    ["entry_mode", "AI 의 매수 진입 모드 — 'pivot_breakout' (표준 돌파) 또는 'pocket_pivot' (포켓 피벗) 중 하나."],
    ["pivot_breakout", "표준 매수 모드 — 종가가 pivot 가격 위로 올라가고 거래량이 50일 평균의 1.4-1.5× 이상."],
    ["pocket_pivot", "Morales/Kacher 의 *조기 매수 신호* — base 안에서 거래량이 직전 10일 중 하락일 최대 거래량 초과 + 종가 SMA-50 위 (TLOND Ch.5)."],
    ["go_now", "AI 의 매수 결정 — '지금 사라' (진짜 돌파 + 시장 OK)."],
    ["wait", "AI 의 매수 결정 — '기다려' (트리거 잡혔으나 약한 신호)."],
    ["abort", "AI 의 매수 결정 — '가짜·무효' (트리거 무시)."],
    ["entry", "AI 분류 — '매수 적합'. weekly_classification.classification = 'entry'."],
    ["watch", "AI 분류 — '베이스 형성 중, 돌파 대기'. weekly_classification.classification = 'watch'."],
    ["ignore", "AI 분류 — '부적합' (패턴 결함·시장 부적합·risk 등)."],
    ["pivot", "책에서 권하는 *정확한 매수 기준가*. 패턴별로 다르게 정의."],
    ["breakout", "종가가 pivot 위로 올라간 사건. 거래량 동반이면 진짜 돌파."],
    ["promotion", "watch 종목이 pivot 의 95% 까지 도달 — 돌파 직전 staging."],
    ["invalidation", "base 무효화 — 종가가 손절선/SMA-50 아래로."],
    ["base", "주가가 옆으로 정리되는 구간 — 컵·평평한 박스·VCP 등 10 종."],
    ["Stage 2", "Minervini 의 종목 사이클 4 단계 중 *기관 누적 + 상승* 구간. 매수 적기."],
    ["distribution day", "기관 매도일 — 시장 지수 ≥0.2% 하락 + 거래량 전일보다 증가."],
    ["FTD", "Follow-Through Day — 조정 끝 강세 전환 확인 신호."],
    ["minervini_pass", "Minervini Trend Template 8 조건을 모두 통과한 종목 표시 (boolean). daily_indicators.minervini_pass = TRUE."],
    ["RS Rating", "Relative Strength Rating — 전체 종목 대비 가격 상승률 백분위 (0-99). 70+ 가 책 기준."],
    ["confirmed_uptrend", "시장 4-enum 상태 중 *매수 적기* — FTD 발생 후 강세 지속."],
    ["correction", "시장 4-enum 상태 중 *조정* — 매수 자제."],
    ["downtrend", "시장 4-enum 상태 중 *하락 추세* — 매수 자제."],
    ["rally_attempt", "시장 4-enum 상태 중 *반등 시도* — FTD 대기."],
    ["SMA-50", "50일 단순 이동평균. 단기 추세 지표."],
    ["SMA-200", "200일 단순 이동평균. 장기 추세 지표."],
    ["stop loss", "손절선 — 이 가격 아래로 떨어지면 즉시 매도. O'Neil: pivot 대비 -7~-8% 한계."],
  ];
  for (const [k, v] of aliases) {
    if (!map[k]) map[k] = v;
  }
  return map;
})();
