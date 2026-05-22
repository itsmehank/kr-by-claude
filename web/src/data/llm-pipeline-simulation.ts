// LLM 분석 안내 페이지의 1주일 시뮬레이션 정적 데이터.
// 10 종목 × 8 날짜 (토 W1 → 다음 토 W2). 코드 / prompt 의 실제 동작에 기반한 가상 시나리오.

export type SimClassification = "entry" | "watch" | "ignore";
export type SimTrigger = "breakout" | "promotion" | "invalidation";
export type SimDecision = "go_now" | "wait" | "abort";

export interface SimDay {
  date: string;       // YYYY-MM-DD
  label: string;      // "토 (W1)" / "월" / "다음 토 (W2)"
  stage: "weekend" | "daily-pipeline" | "market-closed" | null;
}

export interface SimModalRow {
  label: string;
  value: string;
}

export interface SimModal {
  title: string;
  inputs: SimModalRow[];
  outputs: SimModalRow[];
  reasoning: string;
  impact: string;
}

export interface SimCell {
  classification?: SimClassification;
  trigger?: SimTrigger;
  decision?: SimDecision;
  newlyDiscovered?: boolean;   // daily_delta 첫 등장
  reanalyzed?: boolean;         // weekend 재분석 (W 배지)
  notIncluded?: boolean;        // 결정론 미통과 종목 (회색)
  modal?: SimModal;
}

export interface SimRow {
  symbol: string;
  note?: string;
  cells: Record<string, SimCell>;  // date → cell
}

export const SIMULATION_DAYS: SimDay[] = [
  { date: "2026-05-16", label: "토 (W1)", stage: "weekend" },
  { date: "2026-05-17", label: "일",      stage: "market-closed" },
  { date: "2026-05-18", label: "월",      stage: "daily-pipeline" },
  { date: "2026-05-19", label: "화",      stage: "daily-pipeline" },
  { date: "2026-05-20", label: "수",      stage: "daily-pipeline" },
  { date: "2026-05-21", label: "목",      stage: "daily-pipeline" },
  { date: "2026-05-22", label: "금",      stage: "daily-pipeline" },
  { date: "2026-05-23", label: "토 (W2)", stage: "weekend" },
];

export const SIMULATION_ROWS: SimRow[] = [
  // ── SYM_001: entry → 월 breakout/go_now → 토 W2 entry 유지
  {
    symbol: "SYM_001",
    cells: {
      "2026-05-16": {
        classification: "entry",
        reanalyzed: true,
        modal: {
          title: "SYM_001 · 토 (W1) · weekend batch · 분류 = entry",
          inputs: [
            { label: "결정론 필터", value: "minervini_pass=TRUE (Trend Template 8조건)" },
            { label: "패턴 분석", value: "cup_with_handle (handle 완성)" },
            { label: "시장 상태", value: "confirmed_uptrend, distribution_day_count=2" },
            { label: "RS Rating", value: "92" },
          ],
          outputs: [
            { label: "classification", value: "entry" },
            { label: "pattern", value: "cup_with_handle" },
            { label: "pivot_price", value: "84,500" },
            { label: "base_low (= stop_loss)", value: "76,200" },
            { label: "confidence", value: "0.88" },
          ],
          reasoning:
            "Stage 2 강함, cup 형성 35주, handle 7거래일 tight contraction. pivot 84,500 (handle high + 0.1). RS Line 52w high 선행. 거래량 contraction 양호. 위험 플래그 없음.",
          impact:
            "다음 평일부터 evaluate_pivot 의 active 대상. close > pivot + volume ≥ 1.5× avg 시 breakout 트리거.",
        },
      },
      "2026-05-18": {
        trigger: "breakout",
        decision: "go_now",
        modal: {
          title: "SYM_001 · 월 · evaluate_pivot · breakout → go_now",
          inputs: [
            { label: "현재 분류", value: "entry (토 W1)" },
            { label: "pivot_price", value: "84,500" },
            { label: "오늘 close", value: "85,200" },
            { label: "오늘 volume", value: "12,150,000 (1.82× avg_volume_20d)" },
            { label: "결정론 게이트", value: "close > pivot AND volume ≥ avg (1.0×) → breakout (정밀 1.5× 선호치는 LLM)" },
          ],
          outputs: [
            { label: "decision", value: "go_now" },
            { label: "confidence", value: "0.84" },
            { label: "abort_reason", value: "null" },
          ],
          reasoning:
            "Pivot 명확 돌파, 거래량 1.82× (1.4× 기준 충족), 종가 일중 range 상단. 최근 3일 distribution day 없음. handle 깨끗.",
          impact:
            "entry_params 단계로 진행 → 17 필드 매수 계획 생성. 분류는 entry 유지.",
        },
      },
      "2026-05-23": {
        classification: "entry",
        reanalyzed: true,
        modal: {
          title: "SYM_001 · 토 (W2) · weekend batch · 분류 = entry (유지)",
          inputs: [
            { label: "이전 분류", value: "entry (지난주 W1)" },
            { label: "이번 주 행동", value: "월요일 breakout + go_now → 매수 시그널 활성" },
            { label: "stage", value: "stage 2 유지" },
          ],
          outputs: [
            { label: "classification", value: "entry (유지)" },
            { label: "confidence", value: "0.87" },
          ],
          reasoning: "Pivot 돌파 후 정상 흐름. 매수 시그널 entry_params 에 기록됨. base 무효화 신호 없음.",
          impact: "다음 주에도 active. 추가 트리거는 매도/추가매수 신호로 작동.",
        },
      },
    },
  },

  // ── SYM_002: watch → 화 promotion/wait → 토 W2 entry 승격
  {
    symbol: "SYM_002",
    cells: {
      "2026-05-16": {
        classification: "watch",
        reanalyzed: true,
        modal: {
          title: "SYM_002 · 토 (W1) · weekend batch · 분류 = watch",
          inputs: [
            { label: "패턴", value: "flat_base 형성 중 (handle 미완성)" },
            { label: "pivot_price 후보", value: "80,000" },
            { label: "현재 close", value: "72,300 (pivot 의 약 90%)" },
            { label: "RS Rating", value: "78" },
          ],
          outputs: [
            { label: "classification", value: "watch" },
            { label: "pivot_price", value: "80,000" },
            { label: "confidence", value: "0.72" },
          ],
          reasoning:
            "Stage 2 진입, base 형성 중. pivot 도달 임박이지만 거래량 패턴 아직 보강 필요. 평일 promotion 트리거 대기.",
          impact:
            "evaluate_pivot 의 watch 대상. close ≥ pivot × 0.95 + volume ≥ avg 시 promotion 트리거.",
        },
      },
      "2026-05-19": {
        trigger: "promotion",
        decision: "wait",
        modal: {
          title: "SYM_002 · 화 · evaluate_pivot · promotion → wait",
          inputs: [
            { label: "현재 분류", value: "watch" },
            { label: "pivot_price", value: "80,000" },
            { label: "오늘 close", value: "76,500 (pivot 의 95.6%)" },
            { label: "오늘 volume", value: "3,420,000 (1.05× avg)" },
            { label: "결정론 게이트", value: "close ≥ pivot × 0.95 AND volume ≥ avg → promotion" },
          ],
          outputs: [
            { label: "decision", value: "wait" },
            { label: "confidence", value: "0.62" },
            { label: "abort_reason", value: "null" },
          ],
          reasoning:
            "pivot 95% 도달 + 거래량 1.0× — 게이트는 통과했지만 거래량이 1.4× 기준에 못 미침. 종가 일중 range 중간. 한두 일 더 보기.",
          impact:
            "분류는 watch 유지. trigger_evaluation_log 에 기록. 다음 평일 다시 게이트 평가.",
        },
      },
      "2026-05-23": {
        classification: "entry",
        reanalyzed: true,
        modal: {
          title: "SYM_002 · 토 (W2) · weekend batch · 분류 변경 watch → entry",
          inputs: [
            { label: "이전 분류", value: "watch (지난주 W1)" },
            { label: "이번 주 행동", value: "화요일 promotion + wait — 그 후 거래량 점진적 증가" },
            { label: "주간 마감 close", value: "81,200 (pivot 80,000 위)" },
            { label: "handle 형성", value: "완성됨" },
          ],
          outputs: [
            { label: "classification", value: "entry (승격)" },
            { label: "pivot_price", value: "80,000 (유지)" },
            { label: "confidence", value: "0.81" },
          ],
          reasoning:
            "Base 완성 + handle tight. 주간 mark 가 pivot 위. RS Line 강화. 다음 주 breakout 가능성 높음 — entry 분류 새 row INSERT.",
          impact:
            "다음 주부터 evaluate_pivot 의 breakout 게이트 대상 (watch 의 promotion 게이트 아님).",
        },
      },
    },
  },

  // ── SYM_003: watch → 변화 없음 → 토 W2 watch 유지
  {
    symbol: "SYM_003",
    cells: {
      "2026-05-16": {
        classification: "watch",
        reanalyzed: true,
        modal: {
          title: "SYM_003 · 토 (W1) · weekend batch · 분류 = watch",
          inputs: [
            { label: "패턴", value: "base 형성 초기 (depth 만 완성, length 부족)" },
            { label: "pivot_price 후보", value: "없음 (미정)" },
            { label: "RS Rating", value: "71" },
          ],
          outputs: [
            { label: "classification", value: "watch" },
            { label: "pivot_price", value: "null (base 미완성)" },
            { label: "confidence", value: "0.55" },
          ],
          reasoning: "Stage 2 진입했지만 base 가 5주 미만으로 짧음. 더 발전 필요. RS Line 도 아직 약함.",
          impact:
            "pivot_price=null 이므로 evaluate_pivot 의 결정론 게이트 자동 skip (필수 컬럼 NULL). 매일 평가에서 빠짐.",
        },
      },
      "2026-05-23": {
        classification: "watch",
        reanalyzed: true,
        modal: {
          title: "SYM_003 · 토 (W2) · weekend batch · 분류 = watch (유지)",
          inputs: [
            { label: "이번 주 변화", value: "거의 없음 (base 형성 지속)" },
            { label: "현재 close", value: "지난주 +1.2%" },
          ],
          outputs: [
            { label: "classification", value: "watch (유지)" },
            { label: "confidence", value: "0.58" },
          ],
          reasoning: "Base 7주로 성장, 아직 handle 형성 안 됨. RS Line 점진 강화. pivot 후보 아직 미정.",
          impact: "다음 주 weekend 까지 watch. pivot 확정되면 evaluate_pivot 대상으로 합류.",
        },
      },
    },
  },

  // ── SYM_004: entry → 수 invalidation/abort → 토 W2 ignore 강등
  {
    symbol: "SYM_004",
    cells: {
      "2026-05-16": {
        classification: "entry",
        reanalyzed: true,
        modal: {
          title: "SYM_004 · 토 (W1) · weekend batch · 분류 = entry",
          inputs: [
            { label: "패턴", value: "vcp (4 contractions)" },
            { label: "pivot_price", value: "152,000" },
            { label: "base_low (stop_loss)", value: "138,000" },
            { label: "RS Rating", value: "85" },
          ],
          outputs: [
            { label: "classification", value: "entry" },
            { label: "pattern", value: "vcp" },
            { label: "pivot_price", value: "152,000" },
            { label: "confidence", value: "0.82" },
          ],
          reasoning: "VCP 완성. tight 한 4번째 contraction. 거래량 점진 감소. pivot 152,000.",
          impact: "evaluate_pivot 의 entry 게이트. close > pivot + volume ≥ avg (1.0×) 시 breakout 트리거 (매수 확정 1.5× 는 LLM).",
        },
      },
      "2026-05-20": {
        trigger: "invalidation",
        decision: "abort",
        modal: {
          title: "SYM_004 · 수 · evaluate_pivot · invalidation → abort",
          inputs: [
            { label: "현재 분류", value: "entry" },
            { label: "stop_loss (= base_low)", value: "138,000" },
            { label: "sma_50", value: "145,200" },
            { label: "오늘 close", value: "141,800" },
            { label: "결정론 게이트", value: "close < sma_50 → invalidation" },
            { label: "오늘 volume", value: "5,820,000 (1.62× avg, distribution)" },
          ],
          outputs: [
            { label: "decision", value: "abort" },
            { label: "confidence", value: "0.79" },
            { label: "abort_reason", value: "sma50_breach_distribution_volume" },
          ],
          reasoning:
            "Close < sma_50 (2.34% 이탈) + 거래량 1.62× distribution. base 신뢰 상실. 추가 매수 금지.",
          impact:
            "**분류는 entry 그대로**. trigger_evaluation_log 에 abort 기록. 토 W2 weekend batch 가 재분석해야 비로소 ignore 로 강등 가능.",
        },
      },
      "2026-05-23": {
        classification: "ignore",
        reanalyzed: true,
        modal: {
          title: "SYM_004 · 토 (W2) · weekend batch · 분류 변경 entry → ignore",
          inputs: [
            { label: "이전 분류", value: "entry (지난주 W1)" },
            { label: "이번 주 행동", value: "수요일 invalidation + abort 기록" },
            { label: "주간 마감 close", value: "140,500 (pivot 아래 7.6%)" },
            { label: "sma_50 위치", value: "여전히 close > sma_50 회복 못 함" },
          ],
          outputs: [
            { label: "classification", value: "ignore (강등)" },
            { label: "confidence", value: "0.74" },
            { label: "risk_flags", value: '["base_broken"]' },
          ],
          reasoning:
            "VCP base 가 sma_50 이탈로 무효화. 추세 손상. stage 2 종료 가능성. 새 base 형성까지 ignore.",
          impact: "evaluate_pivot 의 평가 대상에서 빠짐. 새 base 형성 시 다시 weekend 가 watch/entry 로 승격.",
        },
      },
    },
  },

  // ── SYM_005: ignore → 변화 없음 → 토 W2 ignore 유지
  {
    symbol: "SYM_005",
    cells: {
      "2026-05-16": {
        classification: "ignore",
        reanalyzed: true,
        modal: {
          title: "SYM_005 · 토 (W1) · weekend batch · 분류 = ignore",
          inputs: [
            { label: "패턴", value: "climax_run" },
            { label: "RS Rating", value: "98 (과열)" },
            { label: "52w high 대비", value: "+62% (climax)" },
          ],
          outputs: [
            { label: "classification", value: "ignore" },
            { label: "pattern", value: "climax_run" },
            { label: "confidence", value: "0.81" },
            { label: "risk_flags", value: '["climax_run", "wide_and_loose", "late_stage_base"]' },
          ],
          reasoning:
            "최근 12주간 +85% 상승 후 wide-and-loose 흔들림. 매수 적기 아님 (이미 진행). climax 위험 명확.",
          impact: "evaluate_pivot 대상 아님 (ignore). 다음 weekend 에서 stage 변경 시 재진입 가능.",
        },
      },
      "2026-05-23": {
        classification: "ignore",
        reanalyzed: true,
        modal: {
          title: "SYM_005 · 토 (W2) · weekend batch · 분류 = ignore (유지)",
          inputs: [
            { label: "이번 주 변화", value: "-8.2% (high volatility)" },
            { label: "stage", value: "여전히 climax 진행 또는 phase 3 진입" },
          ],
          outputs: [
            { label: "classification", value: "ignore (유지)" },
            { label: "confidence", value: "0.83" },
          ],
          reasoning: "Climax run 지속. 새 base 형성 아직 안 됨. 변동성만 큼.",
          impact: "ignore 유지.",
        },
      },
    },
  },

  // ── SYM_006: 화 daily_delta entry → 목 breakout/go_now → 토 W2 entry 유지
  {
    symbol: "SYM_006",
    cells: {
      "2026-05-19": {
        classification: "entry",
        newlyDiscovered: true,
        modal: {
          title: "SYM_006 · 화 · daily_delta · 신규 분류 = entry",
          inputs: [
            { label: "트리거", value: "오늘 새로 minervini_pass 통과 (Trend Template 8조건)" },
            { label: "최근 7일 분류 이력", value: "없음 (신규)" },
            { label: "패턴", value: "cup_with_handle (handle 7거래일 완성)" },
            { label: "pivot_price 후보", value: "98,500" },
          ],
          outputs: [
            { label: "classification", value: "entry" },
            { label: "pattern", value: "cup_with_handle" },
            { label: "pivot_price", value: "98,500" },
            { label: "confidence", value: "0.83" },
          ],
          reasoning:
            "Cup 32주 + handle 7거래일 tight. Stage 2 강함. RS Line 강세. pivot 명확. 위험 플래그 없음. analyze_chart_v3 prompt (weekend 와 동일) — 신규 후보로 즉시 entry 분류.",
          impact:
            "이 시점부터 evaluate_pivot 의 active 대상. 다음 평일부터 breakout 게이트 평가.",
        },
      },
      "2026-05-21": {
        trigger: "breakout",
        decision: "go_now",
        modal: {
          title: "SYM_006 · 목 · evaluate_pivot · breakout → go_now",
          inputs: [
            { label: "현재 분류", value: "entry (화요일 daily_delta)" },
            { label: "pivot_price", value: "98,500" },
            { label: "오늘 close", value: "99,800" },
            { label: "오늘 volume", value: "4,250,000 (1.93× avg_volume_20d)" },
          ],
          outputs: [
            { label: "decision", value: "go_now" },
            { label: "confidence", value: "0.87" },
          ],
          reasoning:
            "Pivot 돌파 +1.3% + 거래량 1.93× (1.4× 기준 초과). 종가 일중 range 상단. handle 깨끗.",
          impact: "entry_params 단계로 진행 → 매수 계획 생성.",
        },
      },
      "2026-05-23": {
        classification: "entry",
        reanalyzed: true,
        modal: {
          title: "SYM_006 · 토 (W2) · weekend batch · 분류 = entry (유지)",
          inputs: [
            { label: "이전 분류", value: "entry (화 daily_delta)" },
            { label: "이번 주 행동", value: "목요일 breakout + go_now" },
          ],
          outputs: [
            { label: "classification", value: "entry (유지)" },
            { label: "confidence", value: "0.85" },
          ],
          reasoning: "Pivot 돌파 후 정상 진입 상태. 추가 변화 없음.",
          impact: "다음 주에도 active.",
        },
      },
    },
  },

  // ── SYM_007: 수 daily_delta watch
  {
    symbol: "SYM_007",
    cells: {
      "2026-05-20": {
        classification: "watch",
        newlyDiscovered: true,
        modal: {
          title: "SYM_007 · 수 · daily_delta · 신규 분류 = watch",
          inputs: [
            { label: "트리거", value: "오늘 새로 결정론 통과 (minervini_pass)" },
            { label: "패턴", value: "flat_base 형성 초기 (4주)" },
            { label: "RS Rating", value: "73" },
          ],
          outputs: [
            { label: "classification", value: "watch" },
            { label: "pattern", value: "flat_base" },
            { label: "pivot_price", value: "null (base 미완성)" },
            { label: "confidence", value: "0.61" },
          ],
          reasoning:
            "Stage 2 진입했지만 base 짧음 (4주). 더 발전 필요. handle 미형성. watch 분류로 대기.",
          impact: "pivot null 이므로 evaluate_pivot skip. 다음 weekend 까지 watch.",
        },
      },
      "2026-05-23": {
        classification: "watch",
        reanalyzed: true,
        modal: {
          title: "SYM_007 · 토 (W2) · weekend batch · 분류 = watch (유지)",
          inputs: [
            { label: "이전 분류", value: "watch (수 daily_delta)" },
            { label: "이번 주 변화", value: "base 5주로 성장, 아직 handle 미형성" },
          ],
          outputs: [
            { label: "classification", value: "watch (유지)" },
            { label: "confidence", value: "0.64" },
          ],
          reasoning: "Base 발전 중이지만 미완성. pivot 후보 아직 미정.",
          impact: "watch 유지.",
        },
      },
    },
  },

  // ── SYM_008: 목 daily_delta ignore
  {
    symbol: "SYM_008",
    cells: {
      "2026-05-21": {
        classification: "ignore",
        newlyDiscovered: true,
        modal: {
          title: "SYM_008 · 목 · daily_delta · 신규 분류 = ignore",
          inputs: [
            { label: "트리거", value: "오늘 새로 결정론 통과" },
            { label: "패턴", value: "late_stage_base (5번째 base)" },
            { label: "RS Rating", value: "76" },
          ],
          outputs: [
            { label: "classification", value: "ignore" },
            { label: "pattern", value: "late_stage_base" },
            { label: "confidence", value: "0.78" },
            { label: "risk_flags", value: '["late_stage_base"]' },
          ],
          reasoning:
            "Stage 2 후반. 5번째 base — 실패 확률 높음 (Minervini: 1-2번째 base 가 가장 안전). watch 도 위험.",
          impact: "ignore. 7일 후 (다음 weekend 또는 daily_delta) 까지 재진입 가능 (조건 충족 시).",
        },
      },
      "2026-05-23": {
        classification: "ignore",
        reanalyzed: true,
        modal: {
          title: "SYM_008 · 토 (W2) · weekend batch · 분류 = ignore (유지)",
          inputs: [
            { label: "이전 분류", value: "ignore (목 daily_delta)" },
            { label: "이번 주 변화", value: "거의 없음" },
          ],
          outputs: [
            { label: "classification", value: "ignore (유지)" },
          ],
          reasoning: "late_stage_base 위험 그대로.",
          impact: "ignore 유지.",
        },
      },
    },
  },
];

SIMULATION_ROWS.push(
  {
    symbol: "SYM_009",
    note: "결정론 미통과 — minervini_pass=FALSE (예: 가격 < sma_50)",
    cells: {
      "2026-05-16": { notIncluded: true },
      "2026-05-23": { notIncluded: true },
    },
  },
  {
    symbol: "SYM_010",
    note: "결정론 미통과 — minervini_pass=FALSE (예: SMA200 하락추세, Stage 4)",
    cells: {
      "2026-05-16": { notIncluded: true },
      "2026-05-23": { notIncluded: true },
    },
  },
);
