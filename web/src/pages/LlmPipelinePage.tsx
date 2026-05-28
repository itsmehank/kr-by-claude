import { MermaidDiagram } from "../components/MermaidDiagram";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  SIMULATION_DAYS,
  SIMULATION_ROWS,
  type SimDay,
  type SimModal,
  type SimRow,
} from "../data/llm-pipeline-simulation";
import { SimulationMatrix } from "./llm-pipeline/SimulationMatrix";
import { SimulationModal } from "./llm-pipeline/SimulationModal";
import { GATE_BREAKOUT_VOL_MULT } from "../data/thresholds.generated";
import { ENTRY_PARAMS_FIELDS, FIELD_CATEGORIES } from "../data/llm-pipeline/entry-params-fields";
import { ListFold } from "./llm-pipeline/ListFold";
import { TableExplainerList } from "./llm-pipeline/TableExplainerList";
import { MINERVINI_CONDITIONS as TT_CONDITIONS } from "../data/llm-pipeline-audit/minervini";
import { BASE_PATTERNS } from "../data/llm-pipeline-audit/base-patterns";
import { RISK_FLAGS } from "../data/llm-pipeline-audit/risk-flags";
import { ZIP_FILES } from "../data/llm-pipeline-audit/zip-files";


// ─────── 데이터 ───────────────────────────────────────────

interface PipelineStage {
  id: string;
  order: number;
  label: string;
  // 친절 본문 (한 단락) — 이 단계가 무엇을 왜 하는가
  intro: string;
  // 결정론 룰 친절 풀이
  deterministicSummary: string;
  deterministicDetail?: string; // fold 안 SQL/정확 조건
  // LLM 로직 친절 풀이
  llmSummary: string | null;     // null = 이 단계 LLM 미사용
  llmShowsLists?: {
    eightConditions?: boolean;  // Trend Template 8 조건 fold
    nineBasePatterns?: boolean;
    thirteenRiskFlags?: boolean;
    thirteenZipFiles?: boolean;
    eighteenFields?: boolean;
  };
  decisions?: string[];
  // 결과 액션
  actionSummary: string;
  actionDetail?: string;        // fold 안 SQL INSERT/UPSERT/digest 상세
  // 입출력 테이블
  inputs: string[];
  outputs: string[];
  // 책 근거 + 코드 참조 (기존 유지)
  sources: string[];
  codeRef: string;
}

const STAGES: PipelineStage[] = [
  // ─── Stage 0: 주말 batch ─────────────────────────────
  {
    id: "weekend",
    order: 0,
    label: "주말 batch — 매주 토 03:20 자동 전체 재분류",
    intro:
      "한 주에 한 번, 토요일 새벽 3시 20분에 자동 실행됩니다. 결정론 1차 필터를 통과한 *모든* 한국 종목을 AI(LLM)가 차트와 함께 재분석해서 entry / watch / ignore 중 하나로 분류합니다. 분류 결과는 weekly_classification 테이블에 새 행으로 쌓입니다 (이전 분류는 그대로 보존).",
    inputs: ["daily_indicators", "weekly_indicators", "market_context_daily", "corporate_actions", "stocks"],
    outputs: ["weekly_classification"],
    deterministicSummary:
      "AI 호출 전 1차 필터로 'Minervini Trend Template 8 조건' 을 통과한 종목만 선별합니다 (= minervini_pass 컬럼이 TRUE). 상장폐지된 종목 (stocks.delisted_at) 은 자동 제외.",
    deterministicDetail:
      "직전 금요일자 daily_indicators 행을 기준으로 minervini_pass=TRUE AND stocks.delisted_at IS NULL 조건의 종목 전체를 풀로 만듭니다. cron 시각은 토 03:20 KST.",
    llmSummary:
      "각 종목별로 13 개의 파일이 든 ZIP 묶음 (차트 PNG·일/주봉 OHLCV·시장 컨텍스트·corporate actions·minervini 진단 등) 을 만들어 AI 에게 보내고, analyze_chart_v3.md prompt 의 지시를 따라 'base 패턴 + risk flag + 분류' 를 받습니다. AI 는 9 종 base 패턴과 13 종 risk flag 만 사용하도록 제약돼 있습니다.",
    llmShowsLists: {
      eightConditions: true,
      thirteenZipFiles: true,
      nineBasePatterns: true,
      thirteenRiskFlags: true,
    },
    decisions: ["entry", "watch", "ignore"],
    actionSummary:
      "분류 결과를 weekly_classification 테이블에 *새 행* 으로 추가합니다 (이전 분류는 지우지 않고 누적). 같은 종목·같은 시각의 중복은 자동 무시. 분석이 끝나면 entry/watch/ignore 카운트를 Slack 으로 요약 알림 (digest).",
    actionDetail:
      "SQL 패턴: INSERT INTO weekly_classification (...) VALUES (...) ON CONFLICT (symbol, classified_at) DO NOTHING. '현재 분류' 를 조회할 땐 DISTINCT ON (symbol) ORDER BY classified_at DESC. 즉 append-only 설계 — UPDATE 하지 않고 새 행을 쌓고, 최신 행이 '현재 상태'.",
    sources: [
      "Minervini Trend Template (8 conditions)",
      "O'Neil HMM base patterns",
    ],
    codeRef: "kr_pipeline/llm_runner/weekend.py + modes.py:run_weekend",
  },

  // ─── Stage 1: 신규 후보 분류 ──────────────────────────
  {
    id: "daily_delta",
    order: 1,
    label: "신규 후보 분류 — 평일 매일 새 종목만",
    intro:
      "평일 매일 20:00 자동 실행됩니다. weekend 와 같은 AI prompt + 같은 ZIP 구조를 쓰지만, 대상이 다릅니다 — 결정론 필터를 *오늘 새로 통과한* 종목만. 즉 다음 주 토 weekend 까지 기다리지 않고 신규 후보를 즉시 분류해서 watch/entry 풀에 합류시키는 *빠른 반응* 단계입니다.",
    inputs: ["daily_indicators", "daily_prices", "weekly_indicators", "market_context_daily"],
    outputs: ["weekly_classification"],
    deterministicSummary:
      "1차 필터는 동일 — Trend Template 8 조건 통과 (minervini_pass=TRUE). 추가로 *신규성* 조건: 최근 7일 안에 분류된 적이 없는 종목만 (이미 weekend 나 다른 daily_delta 에서 분류된 종목은 제외).",
    deterministicDetail:
      "daily_indicators 의 오늘 행 기준 minervini_pass=TRUE + NOT EXISTS (SELECT 1 FROM weekly_classification WHERE symbol = ticker AND classified_at >= today - INTERVAL '7 days'). 7일 cool-down 으로 같은 종목 반복 분석 방지.",
    llmSummary:
      "weekend 와 정확히 같은 prompt (analyze_chart_v3.md) + 같은 ZIP 13 파일. 차이는 source 컬럼 ('daily_delta' vs 'weekend') 과 입력 풀의 신규성 필터.",
    llmShowsLists: {
      thirteenZipFiles: true,
      nineBasePatterns: true,
      thirteenRiskFlags: true,
    },
    decisions: ["entry", "watch", "ignore"],
    actionSummary:
      "weekly_classification 에 새 행으로 INSERT (source='daily_delta'). watch/entry 분류된 종목은 다음 평일부터 evaluate_pivot 의 평가 대상. ignore 분류된 종목은 7일 후 다시 신규 후보로 재진입 가능.",
    actionDetail:
      "INSERT INTO weekly_classification (..., source='daily_delta') VALUES (...) ON CONFLICT (symbol, classified_at) DO NOTHING. weekend 와 동일한 append-only.",
    sources: ["Minervini Trend Template", "O'Neil HMM 'How to Read Charts Like a Pro'"],
    codeRef: "kr_pipeline/llm_runner/daily_delta.py",
  },

  // ─── Stage 2: 평일 트리거 평가 ────────────────────────
  {
    id: "evaluate_pivot",
    order: 2,
    label: "평일 트리거 평가 — watch/entry 종목의 오늘 행동 점검",
    intro:
      "이미 watch 또는 entry 로 분류된 활성 종목들의 오늘 가격·거래량을 매일 점검합니다. 종가가 pivot 을 돌파했는지, 손절선을 깼는지, 50일 이동평균에서 이탈했는지 등을 *결정론 게이트* 가 먼저 검사해 이벤트 유형 (breakout / promotion / invalidation) 을 결정합니다. 이벤트가 잡힌 종목만 AI 에게 '진짜 신호인가 가짜 신호인가' 묻습니다.",
    inputs: ["weekly_classification", "daily_indicators"],
    outputs: ["trigger_evaluation_log"],
    deterministicSummary:
      `세 가지 트리거를 결정론 룰로 잡습니다 — ① 종가 > pivot AND 거래량 ≥ 평균 (${GATE_BREAKOUT_VOL_MULT.toFixed(1)}×) → breakout (돌파), ② 종가 ≥ pivot × 0.95 → promotion (돌파 직전 staging), ③ 종가 < 손절선 또는 종가 < SMA-50 → invalidation (base 무효화). 거래량 기준은 게이트의 1.0× = '거래량이 죽지 않은 정도만' 확인이고, 책 표준 1.4~1.5× 와 pocket pivot 예외는 AI 가 판단합니다.`,
    deterministicDetail:
      "compute/trigger_gate.py 의 룰: pivot_price IS NULL 인 종목은 skip. close < stop_loss OR close < sma_50 → invalidation 우선 적용. 그 외 close > pivot AND volume >= avg_volume_50d × GATE_BREAKOUT_VOL_MULT → breakout. promotion 은 watch 분류 종목에만, close >= pivot × 0.95 AND volume >= avg 일 때.",
    llmSummary:
      "evaluate_pivot_trigger_v1.md prompt — 게이트가 잡은 트리거 유형을 입력으로 받고 'go_now (지금 사라) / wait (기다려) / abort (가짜·무효)' 중 하나를 결정. *중요*: 이 단계는 분류 자체를 바꾸지 않습니다. abort 가 나와도 분류는 그대로 유지 — 다음 토 weekend 에서 AI 가 다시 보고 분류를 ignore 로 강등해야 비로소 강등.",
    decisions: ["go_now", "wait", "abort"],
    actionSummary:
      "결과를 trigger_evaluation_log 에 새 행으로 기록 (분류는 변경 안 함). decision='go_now' + trigger_type='breakout' 인 종목은 다음 단계 (entry_params) 가 자동으로 매수 계획을 작성합니다. promotion 트리거에서는 go_now 가 *나오지 않도록* prompt 와 코드 양쪽에 안전장치가 있습니다 (실질 매수는 종가가 pivot 위로 올라간 진짜 breakout 으로만).",
    actionDetail:
      "INSERT INTO trigger_evaluation_log (symbol, evaluated_at, trigger_type, decision, ...) VALUES (...). entry_params 다음 단계의 SQL 은 WHERE decision='go_now' AND trigger_type='breakout' 으로 staging 신호 분리.",
    sources: [
      "O'Neil HMM ch.2 Volume Percent Change (1.5× breakout)",
      "Minervini buy/sell rules",
    ],
    codeRef: "kr_pipeline/llm_runner/evaluate_pivot.py + compute/trigger_gate.py",
  },

  // ─── Stage 3: 매수 계획 ───────────────────────────────
  {
    id: "entry_params",
    order: 3,
    label: "매수 계획 (entry_params) — go_now 종목의 실제 매수 파라미터",
    intro:
      "evaluate_pivot 에서 go_now 결정을 받은 *진짜 매수 시그널* 종목에 대해 AI 가 18 개 필드의 매수 계획을 작성합니다. 진입 가격·손절선·목표가·포지션 사이즈·돌파 거래량 요건 등 매수에 필요한 모든 숫자를 한 행으로 정리. 이게 시스템의 *최종 산출물* 입니다 — 사용자는 entry_params 행을 보고 실제 매수 여부를 결정.",
    inputs: ["trigger_evaluation_log", "daily_indicators", "weekly_classification"],
    outputs: ["entry_params"],
    deterministicSummary:
      "오늘자 trigger_evaluation_log 에서 decision='go_now' AND trigger_type='breakout' 행만 추출 (promotion·invalidation·abort 는 entry_params 진입 차단).",
    deterministicDetail:
      "SELECT FROM trigger_evaluation_log WHERE evaluated_at::date = today AND decision='go_now' AND trigger_type='breakout'. 이 조건이 'watch staging' 이 매수로 새지 않게 막는 안전장치.",
    llmSummary:
      "calculate_entry_params_v2_0.md prompt — 18 필드를 책 룰 (O'Neil 7-8% 손절, Minervini 1-3% 거래당 위험, 5% chase 제한 등) 에 맞춰 계산. entry_mode 가 pivot_breakout 인지 pocket_pivot 인지에 따라 손절·사이징 룰이 다릅니다.",
    llmShowsLists: {
      eighteenFields: true,
    },
    actionSummary:
      "entry_params 테이블에 새 행으로 INSERT (PK: symbol + signal_at). 이 행이 곧 '활성 매수 시그널'. performance 단계가 자동으로 이 시그널의 1주·2주·4주·8주 후 가격을 추적합니다.",
    actionDetail:
      "INSERT INTO entry_params (symbol, signal_at, entry_mode, pivot_price, ..., notes, known_warnings, other_warnings) VALUES (...). PK 충돌 (같은 종목·같은 시각) 은 거의 없으나 안전장치로 ON CONFLICT DO NOTHING.",
    sources: ["Minervini risk management (1-3% per trade)", "O'Neil HMM 'Buy at the Buy Point'"],
    codeRef: "kr_pipeline/llm_runner/entry_params.py",
  },

  // ─── Stage 4: 성과 추적 ───────────────────────────────
  {
    id: "performance",
    order: 4,
    label: "성과 추적 — 시그널의 1주/2주/4주/8주 후 수익률",
    intro:
      "AI 호출 없는 순수 계산 단계입니다. 최근 90일 안에 발생한 매수 시그널 (entry_params) 들의 1주·2주·4주·8주 후 가격을 daily_prices 에서 조회해 수익률을 계산. 같은 기간의 시장 (KOSPI 또는 KOSDAQ) 수익률도 함께 기록해 *시장 대비 알파* 도 측정. 8주 데이터가 모두 채워지면 추적이 사실상 끝납니다.",
    inputs: ["entry_params", "daily_prices", "index_daily"],
    outputs: ["signal_performance"],
    deterministicSummary:
      "entry_params 의 signal_at 가 최근 90일 안인 행에 대해 +7 / +14 / +28 / +56 일 후 종가를 조회. 90일 cutoff 는 8주 추적 + 안전 마진.",
    deterministicDetail:
      "SELECT FROM entry_params WHERE signal_at >= today - 90 days. 각 행에 대해 daily_prices 에서 +7d/+14d/+28d/+56d close 조회. 같은 시점의 index_daily (해당 시장의 지수) 종가도 조회해 시장 대비 차이 계산.",
    llmSummary: null,
    actionSummary:
      "signal_performance 테이블에 (symbol, signal_at) 키로 UPSERT. 같은 종목의 여러 시그널은 signal_at 별로 독립 추적 — 같은 종목이 한 달 사이 두 번 entry_params 를 받았다면 두 시그널 각각 추적.",
    actionDetail:
      "INSERT INTO signal_performance (symbol, signal_at, price_1w, price_2w, price_4w, price_8w, market_return_1w, ...) VALUES (...) ON CONFLICT (symbol, signal_at) DO UPDATE SET ... — 점진적으로 데이터가 채워지므로 UPSERT.",
    sources: [],
    codeRef: "kr_pipeline/llm_runner/performance.py",
  },
];


// Mermaid diagram sources

const DIAGRAM_DATA_FLOW = `graph LR
    W["weekend batch<br/>(토 03:20, 전체 재분류)"] -->|source='weekend'| B[("weekly_classification<br/>watch / entry / ignore")]
    A["daily_delta<br/>(평일, 신규만)"] -->|source='daily_delta'| B
    B -->|매일 활성 종목<br/>DISTINCT ON| C{"evaluate_pivot<br/>결정론 게이트"}
    C -->|"breakout / promotion /<br/>invalidation"| D["LLM 평가"]
    D -->|"go_now / wait / abort"| E[("trigger_evaluation_log")]
    E -->|"decision='go_now'<br/>AND trigger_type='breakout'<br/>(promotion staging 안전장치)"| F["entry_params<br/>LLM 호출"]
    F --> G[("entry_params<br/>매수 계획 17 필드")]
    G -->|매일 자동| H["performance<br/>1주/2주/4주/8주 추적"]
    H --> I[("signal_performance")]
`;

const DIAGRAM_STATE = `stateDiagram-v2
    [*] --> Unclassified: minervini_pass 통과
    Unclassified --> Watch: weekend/daily_delta watch
    Unclassified --> Entry: weekend/daily_delta entry
    Unclassified --> Ignore: weekend/daily_delta ignore
    Watch --> Watch: evaluate_pivot wait/abort (분류 유지)
    Watch --> Entry: weekend batch 재분석 시 승격
    Entry --> Entry: evaluate_pivot wait/abort (분류 유지)
    Entry --> EntryParams: breakout + go_now
    Entry --> Ignore: weekend batch 재분석 시 강등
    EntryParams --> Performance: 자동 추적
    Performance --> [*]: 90일 cutoff
    Ignore --> [*]: 7일 후 후보 재진입 가능
`;


// 트리거 × 결정 매트릭스

interface MatrixCell {
  meaning: string;
  next: string;
}

const TRIGGER_DECISION_MATRIX: Record<string, Record<string, MatrixCell | null>> = {
  breakout: {
    go_now: {
      meaning: "종가가 pivot 을 돌파하고 거래량도 살아있음. AI 가 '진짜 돌파' 로 확인.",
      next: "→ 매수 계획 (entry_params) 자동 생성. 사용자가 행을 보고 실제 매수 결정.",
    },
    wait: {
      meaning: "돌파했지만 AI 가 보류 — 약한 신호 (예: 거래량이 1.4× 미만, base 가 약간 wide) 일 가능성.",
      next: "→ 매수 계획 생성 안 됨. 다음 평일에 재평가. entry 분류는 그대로 유지.",
    },
    abort: {
      meaning: "돌파처럼 보였으나 AI 가 가짜로 판정 — 예: 다음날 즉시 되돌림 우려 / 시장 약세 중복.",
      next: "→ 매수 계획 안 만듦. 분류 자체는 entry 유지. 다음 토 weekend 의 재분석이 base 무효 판단 시 비로소 ignore 강등.",
    },
  },
  promotion: {
    go_now: null,  // 시스템 안전장치 — promotion 에서 go_now 발생 금지
    wait: {
      meaning: "watch 종목이 pivot 의 95% 까지 도달 — 돌파 직전 staging 상태. 거래량은 평균 이상. close 는 아직 pivot 미만이라 매수 신호 아님.",
      next: "→ 다음 평일에 게이트가 다시 평가. 종가가 pivot 위로 올라가면 별도 breakout 트리거로 처리.",
    },
    abort: {
      meaning: "base 가 깨질 조짐 — SMA-50 이탈, distribution day 누적 등. AI 가 위험 신호로 판단.",
      next: "→ watch 분류 유지 (분류 변경 안 함). 다음 토 weekend 에서 ignore 로 강등될 후보.",
    },
  },
  invalidation: {
    go_now: null,
    wait: null,
    abort: {
      meaning: "base 가 무효화 — 종가가 손절선 또는 SMA-50 아래로 이탈. AI 호출 없이 결정론으로 abort 확정.",
      next: "→ 분류는 entry/watch 그대로 유지하지만, 다음 weekend 또는 daily_delta 재분류 까지 평가 사이클에서 사실상 제외.",
    },
  },
};


// 용어집

const GLOSSARY: { term: string; meaning: string }[] = [
  {
    term: "weekend batch",
    meaning: "토 03:20 cron 으로 실행되는 LLM 분석 — 결정론 통과 모든 종목 재분류. weekly_classification 에 source='weekend' 로 INSERT.",
  },
  {
    term: "결정론 필터",
    meaning: "minervini_pass (Minervini Trend Template 8조건 통과). LLM 호출 전 무료 필터. daily_indicators 컬럼 직접 SELECT.",
  },
  {
    term: "신규 종목 (daily_delta)",
    meaning: "결정론 통과 + 최근 7일 분류 이력 없음. 평일 daily_delta 의 대상.",
  },
  {
    term: "재분석 (weekend)",
    meaning: "이미 분류된 종목도 weekend batch 마다 같은 prompt 로 다시 분류. 이전 분류와 다를 수 있음 (예: entry → ignore).",
  },
  {
    term: "현재 분류",
    meaning: "DISTINCT ON (symbol) ORDER BY classified_at DESC — 가장 최근 weekly_classification row 가 곧 '현재 상태'. UPDATE 안 함, append-only 설계.",
  },
  {
    term: "classification",
    meaning: "watch / entry / ignore — LLM 의 종목 정성 평가. weekly_classification.classification 컬럼. 자주 안 바뀜.",
  },
  {
    term: "signal",
    meaning: "entry_params 의 새 row — 실질 매수 시그널. classification 과 별개 차원.",
  },
  {
    term: "trigger_type",
    meaning: "breakout / promotion / invalidation — 결정론 게이트가 감지한 오늘의 이벤트.",
  },
  {
    term: "decision",
    meaning: "go_now / wait / abort — LLM 이 그 트리거에 대해 내린 행동 결정.",
  },
  {
    term: "분류 변경",
    meaning: "weekly_classification.classification 의 변경. weekend batch 또는 daily_delta 의 신규 후보 재진입 시에만. evaluate_pivot 은 분류 변경 안 함.",
  },
  {
    term: "dry-run",
    meaning: "LLM 호출은 mock 응답, DB INSERT 도 skip. read-only 검증 모드.",
  },
  {
    term: "90일 cutoff",
    meaning: "performance 가 추적하는 signal 의 기간 한계. signal_at 가 90일 이전이면 추적 안 함. 8주 데이터 채워지면 사실상 종료.",
  },
];


// FAQ

const FAQ: { q: string; a: string }[] = [
  {
    q: "Watch 가 evaluate_pivot 의 LLM 결정으로 자동 entry 로 승격되지 않는 이유?",
    a: "evaluate_pivot 의 prompt 가 명시적으로 '분류 재평가 금지' 정책. classification 은 weekend 또는 daily_delta 만 변경. promotion 트리거는 staging 신호일 뿐 매수 시그널이 아니며 (prompt §3.3), go_now 가 발생하지 않도록 코드 안전장치도 적용 (entry_params 는 trigger_type='breakout' 만 수집). watch 종목이 실제 매수되려면 다음 평일 close > pivot 으로 breakout 트리거가 별도 발생해야 함.",
  },
  {
    q: "Pivot 없는 watch 종목은 어떻게 되나?",
    a: "evaluate_pivot 의 결정론 게이트가 pivot_price IS NULL 인 종목을 skip. 매일 평가 사이클에서 빠짐. 다음 weekend 또는 daily_delta 재분류 까지 정지 상태.",
  },
  {
    q: "daily_delta 와 weekend batch 의 차이?",
    a: "둘 다 같은 prompt (analyze_chart_v3.md) + 같은 zip. 차이는 대상 풀: daily_delta = 신규 (7일 내 분류 없는 minervini 통과), weekend = 전체 minervini 통과 (재분류 가능). daily_delta 는 평일 매일 (full-daily 의 첫 단계), weekend 는 토요일 03:20.",
  },
  {
    q: "dry-run 시 DB 영향은?",
    a: "0. mock LLM 응답 받고 응답 파싱까지는 진행 (검증), 그러나 store 호출 직전 가드로 INSERT skip. weekly_classification / trigger_evaluation_log / entry_params 모두 영향 없음.",
  },
  {
    q: "주말 batch 와 daily_delta 가 같은 prompt 라면 둘 다 필요한가?",
    a: "시점이 다름. weekend = 매주 한 번 전체 결산 (시각차 확보, 분류 갱신). daily_delta = 평일에 새로 결정론 통과한 종목을 7일 기다리지 않고 즉시 분류 (조기 포착). 결과적으로 모든 minervini 통과 종목은 주 1회 weekend 로 재분류되고, 그 사이 신규는 daily_delta 로 즉시 합류.",
  },
  {
    q: "evaluate_pivot 의 abort 가 종목 분류를 ignore 로 바꾸나?",
    a: "아니오. evaluate_pivot 은 trigger_evaluation_log 만 INSERT. weekly_classification 의 row 는 그대로. abort 가 누적되어도 분류는 entry 로 유지됨. 다음 weekend batch 에서 LLM 이 base 가 깨졌다고 판단하면 비로소 ignore 로 재분류.",
  },
  {
    q: "한 종목이 한 주에 여러 번 분류될 수 있나?",
    a: "가능. 예: 토 weekend (entry 재분석). 다음 평일에 daily_delta 가 같은 종목을 다시 분류할 수는 없음 (최근 7일 분류 이력 있어서 신규 아님). 다만 다음 주 토 weekend 에서 또 재분석되어 row 가 추가. 결국 한 종목은 weekend 마다 매주 1번 재분석.",
  },
];


// ─────── 컴포넌트 ───────────────────────────────────────────

function TableChip({ name }: { name: string }) {
  return (
    <span className="num text-data-xs bg-tint-stone text-muted px-2 py-0.5 rounded">
      {name}
    </span>
  );
}

function SourceChip({ src }: { src: string }) {
  return (
    <span className="text-data-xs text-faint italic">
      📖 {src}
    </span>
  );
}

function DecisionChip({ value }: { value: string }) {
  const colorMap: Record<string, string> = {
    watch: "bg-tint-blue text-accent",
    entry: "bg-success-soft text-success",
    ignore: "bg-tint-stone text-muted",
    go_now: "bg-success-soft text-success",
    wait: "bg-amber-soft text-amber",
    abort: "bg-tint-stone text-muted",
  };
  const cls = colorMap[value] ?? "bg-tint-stone text-muted";
  return <span className={`chip ${cls}`}>{value}</span>;
}


function StageCard({ stage }: { stage: PipelineStage }) {
  return (
    <section className="bento p-6 mb-4">
      {/* 헤더 */}
      <div className="flex items-center gap-3 mb-3">
        <span className="num text-data-xs text-faint shrink-0">{stage.order}</span>
        <span className="num text-data-xs bg-tint-violet text-accent px-2 py-0.5 rounded shrink-0">
          {stage.id}
        </span>
        <h3 className="text-subhead font-bold text-ink flex-1">{stage.label}</h3>
      </div>

      {/* 친절 본문 */}
      <p className="text-data text-muted mb-5 leading-relaxed">{stage.intro}</p>

      {/* 입출력 테이블 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-5">
        <TableExplainerList names={stage.inputs} label="📥 입력 테이블" />
        <TableExplainerList names={stage.outputs} label="📤 출력 테이블" />
      </div>

      {/* 결정론 룰 */}
      <div className="mb-5">
        <div className="caps text-faint mb-1">⚙️ 결정론 룰</div>
        <p className="text-data text-ink leading-relaxed">{stage.deterministicSummary}</p>
        {stage.deterministicDetail && (
          <ListFold label="결정론 룰 SQL·상세 보기">
            <div className="whitespace-pre-wrap">{stage.deterministicDetail}</div>
          </ListFold>
        )}
        {stage.llmShowsLists?.eightConditions && (
          <ListFold label="Trend Template 8 조건 모두 보기" count={TT_CONDITIONS.length}>
            <ol className="space-y-2 list-decimal list-inside">
              {TT_CONDITIONS.map((c) => (
                <li key={c.num}>
                  <span className="text-ink font-semibold">{c.korean}</span>
                  {c.threshold && <span className="text-muted"> — {c.threshold}</span>}
                </li>
              ))}
            </ol>
          </ListFold>
        )}
      </div>

      {/* AI (LLM) 로직 */}
      <div className="mb-5">
        <div className="caps text-faint mb-1">🧠 AI (LLM) 로직</div>
        {stage.llmSummary == null ? (
          <p className="text-data text-faint">이 단계는 AI 호출 없음 (순수 계산).</p>
        ) : (
          <>
            <p className="text-data text-ink leading-relaxed">{stage.llmSummary}</p>
            {stage.decisions && (
              <div className="flex flex-wrap gap-1 mt-2">
                {stage.decisions.map((d) => <DecisionChip key={d} value={d} />)}
              </div>
            )}
            {stage.llmShowsLists?.thirteenZipFiles && (
              <ListFold label="AI 가 받는 자료 — ZIP 13 파일 모두 보기" count={ZIP_FILES.length}>
                <ol className="space-y-2 list-decimal list-inside">
                  {ZIP_FILES.map((z) => (
                    <li key={z.num}>
                      <span className="num text-ink font-semibold">{z.filename}</span>
                      <span className="text-muted"> — {z.content}</span>
                    </li>
                  ))}
                </ol>
              </ListFold>
            )}
            {stage.llmShowsLists?.nineBasePatterns && (
              <ListFold label="AI 가 식별하는 9 base 패턴 모두 보기" count={BASE_PATTERNS.length}>
                <ul className="space-y-2">
                  {BASE_PATTERNS.map((p) => (
                    <li key={p.id}>
                      <span className="num text-ink font-semibold">{p.id}</span>
                      <span className="text-muted"> — {p.definition}</span>
                    </li>
                  ))}
                </ul>
              </ListFold>
            )}
            {stage.llmShowsLists?.thirteenRiskFlags && (
              <ListFold label="AI 가 사용하는 13 risk flag 모두 보기" count={RISK_FLAGS.length}>
                <ul className="space-y-2">
                  {RISK_FLAGS.map((r) => (
                    <li key={r.id}>
                      <span className="num text-ink font-semibold">{r.id}</span>
                      <span className="text-muted"> — {r.definition}</span>
                    </li>
                  ))}
                </ul>
              </ListFold>
            )}
            {stage.llmShowsLists?.eighteenFields && (
              <ListFold label="AI 가 채우는 매수 계획 18 필드 모두 보기" count={ENTRY_PARAMS_FIELDS.length}>
                <div className="space-y-3">
                  {(Object.keys(FIELD_CATEGORIES) as (keyof typeof FIELD_CATEGORIES)[]).map((cat) => {
                    const fields = ENTRY_PARAMS_FIELDS.filter((f) => f.category === cat);
                    if (fields.length === 0) return null;
                    return (
                      <div key={cat}>
                        <div className="text-ink font-semibold mb-1">
                          {FIELD_CATEGORIES[cat].emoji} {FIELD_CATEGORIES[cat].label} ({fields.length})
                        </div>
                        <ul className="space-y-1 pl-4">
                          {fields.map((f) => (
                            <li key={f.name}>
                              <span className="num text-ink">{f.name}</span>
                              <span className="text-muted"> — {f.what}</span>
                              <div className="text-faint text-data-xs ml-3">제약: {f.constraint}</div>
                            </li>
                          ))}
                        </ul>
                      </div>
                    );
                  })}
                </div>
              </ListFold>
            )}
          </>
        )}
      </div>

      {/* 결과 액션 */}
      <div className="mb-5">
        <div className="caps text-faint mb-1">✅ 결과 액션</div>
        <p className="text-data text-ink leading-relaxed">{stage.actionSummary}</p>
        {stage.actionDetail && (
          <ListFold label="SQL INSERT / 엔지니어링 상세 보기">
            <div className="whitespace-pre-wrap">{stage.actionDetail}</div>
          </ListFold>
        )}
      </div>

      {/* 책 근거 + 코드 참조 (기존 유지) */}
      {stage.sources.length > 0 && (
        <div className="mb-4">
          <div className="caps text-faint mb-1">📖 책 근거</div>
          <div className="flex flex-wrap gap-3">
            {stage.sources.map((s) => <SourceChip key={s} src={s} />)}
          </div>
        </div>
      )}

      <div className="pt-3 border-t border-hairline">
        <div className="caps text-faint mb-1">💻 코드 참조</div>
        <code className="num text-data-xs bg-cream px-2 py-1 rounded">{stage.codeRef}</code>
      </div>
    </section>
  );
}


function TriggerDecisionMatrix() {
  const triggers = ["breakout", "promotion", "invalidation"];
  const decisions = ["go_now", "wait", "abort"];
  return (
    <section className="bento p-6 mb-4">
      <h3 className="text-subhead font-bold text-ink mb-3">트리거 × LLM 결정 매트릭스</h3>
      <p className="text-data-xs text-muted mb-4 leading-relaxed">
        evaluate_pivot 단계에서 무슨 일이 일어나는지 한눈에 보는 표입니다.
        세로축은 결정론 게이트가 잡은 *오늘의 이벤트* — <span className="num text-ink">breakout</span> (돌파),{" "}
        <span className="num text-ink">promotion</span> (돌파 직전 staging),{" "}
        <span className="num text-ink">invalidation</span> (base 무효화).
        가로축은 그 이벤트에 대해 AI 가 내린 결정 — <span className="num text-ink">go_now</span> (지금 사라),{" "}
        <span className="num text-ink">wait</span> (기다려),{" "}
        <span className="num text-ink">abort</span> (가짜·무효).
        9 칸 중 *적용 안 됨* 4 칸은 시스템 안전장치 (promotion·invalidation 에서 매수 시그널 직행 차단).
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-data-xs">
          <thead>
            <tr className="border-b border-hairline">
              <th className="caps text-left py-2 px-3">Trigger ↓ / Decision →</th>
              {decisions.map((d) => (
                <th key={d} className="caps text-left py-2 px-3">
                  <DecisionChip value={d} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {triggers.map((t) => (
              <tr key={t} className="border-b border-hairline last:border-b-0">
                <td className="py-2 px-3 align-top">
                  <span className="num text-data text-ink">{t}</span>
                </td>
                {decisions.map((d) => {
                  const cell = TRIGGER_DECISION_MATRIX[t]?.[d];
                  return (
                    <td key={d} className="py-2 px-3 align-top">
                      {cell ? (
                        <>
                          <div className="text-data text-ink">{cell.meaning}</div>
                          <div className="text-data-xs text-muted mt-1">→ {cell.next}</div>
                        </>
                      ) : (
                        <span className="text-faint">(적용 안 됨)</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}


function Glossary() {
  return (
    <section className="bento p-6 mb-4">
      <h3 className="text-subhead font-bold text-ink mb-3">용어집</h3>
      <dl className="space-y-3">
        {GLOSSARY.map((g) => (
          <div key={g.term}>
            <dt className="text-data text-ink font-semibold">{g.term}</dt>
            <dd className="text-data-xs text-muted mt-1 leading-relaxed">{g.meaning}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}


function FaqSection() {
  return (
    <section className="bento p-6 mb-4">
      <h3 className="text-subhead font-bold text-ink mb-3">자주 묻는 질문</h3>
      <div className="space-y-4">
        {FAQ.map((f, i) => (
          <div key={i}>
            <div className="text-data text-ink font-semibold mb-1">Q. {f.q}</div>
            <p className="text-data-xs text-muted leading-relaxed">{f.a}</p>
          </div>
        ))}
      </div>
    </section>
  );
}


export default function LlmPipelinePage() {
  const [activeModal, setActiveModal] = useState<SimModal | null>(null);

  function handleCellClick(row: SimRow, day: SimDay) {
    const cell = row.cells[day.date];
    if (cell?.modal) setActiveModal(cell.modal);
  }

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      <header className="mb-8">
        <div className="caps text-faint mb-2">Documentation</div>
        <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
          LLM 분석 안내
        </h2>
        <p className="text-data-xs text-muted mt-3 leading-relaxed">
          평일 4단계 (daily_delta → evaluate_pivot → entry_params → performance) 와
          주말 1단계 (weekend batch) 의 흐름, 결정론 로직, LLM 로직, 책 원전 정리.
          + 10 종목 1주일 시뮬레이션으로 처음 보는 사용자도 흐름 이해 가능.
        </p>
      </header>

      <details className="mb-8 group">
        <summary className="cursor-pointer select-none px-5 py-3 bg-cream border border-hairline rounded-xl text-data text-ink font-semibold hover:bg-tint-stone transition-colors list-none flex items-center justify-between">
          <span>이 페이지는 처음인가요? 📖</span>
          <span className="text-faint font-normal text-data-xs ml-3 group-open:hidden">클릭해서 안내 펼치기 ▼</span>
          <span className="text-faint font-normal text-data-xs ml-3 hidden group-open:inline">접기 ▲</span>
        </summary>
        <div className="mt-3 px-5 py-5 bg-cream border border-hairline rounded-xl text-data text-muted leading-relaxed space-y-5">
          <p>
            이 시스템은 매일 자동으로 한국 주식 (KOSPI/KOSDAQ) 을 훑어 <span className="text-ink font-semibold">살 만한 후보</span> 를 골라줍니다.
            단순 룰 하나만 적용하는 게 아니라, <span className="text-ink font-semibold">"기계가 1차로 거르고, AI 가 차트를 보고 최종 판단"</span> 하는
            2단계 방식입니다. 이 페이지는 그 <em>전체 흐름</em> 을 단계별로 보여주고, 가상 10 종목이 1주일 동안
            어떻게 분류·평가되는지 <span className="text-ink font-semibold">시뮬레이션 매트릭스</span> 로 보여줍니다.
          </p>

          <div>
            <div className="text-ink font-semibold mb-2">무엇을 볼 수 있나요?</div>
            <ul className="space-y-1.5 list-disc list-inside pl-1">
              <li><span className="text-ink">5 단계 파이프라인</span> — 결정론 1차 필터 → AI 분류 → 매수 조건 평가 → 매수 파라미터 산출 → 사후 성과 측정.</li>
              <li><span className="text-ink">10 종목 × 5일 시뮬레이션</span> — 매일 어떤 신호가 떠서 무엇으로 변하는지 셀을 클릭해 확인.</li>
              <li><span className="text-ink">각 단계의 입력·출력·책 근거</span> — <em>"왜 이렇게 동작하나"</em> 를 책 원전 (Minervini / O'Neil) 까지 연결.</li>
            </ul>
          </div>

          <div>
            <div className="text-ink font-semibold mb-2">핵심 용어 빠른 이해</div>
            <ul className="space-y-1.5 list-disc list-inside pl-1">
              <li><span className="text-ink">결정론</span> — 사람이 미리 정한 명확한 룰 (예: <em>"거래량이 평균 이상이어야 통과"</em>).</li>
              <li><span className="text-ink">LLM (AI)</span> — 차트·지표·뉴스 등을 받아 판단하는 AI 모델. <em>"이 종목은 entry / watch / ignore"</em> 같은 결정을 내림.</li>
              <li><span className="text-ink">base 패턴</span> — 주가가 옆으로 가다가 돌파 직전인 <em>모양</em> (컵·평평한 박스·VCP 등 9 종).</li>
              <li><span className="text-ink">Minervini / O'Neil</span> — 본 시스템이 따르는 두 미국 성장주 투자 대가. 룰 대부분이 그들의 책에서 옴.</li>
            </ul>
          </div>

          <div className="pt-3 border-t border-hairline">
            <span className="text-faint">자매 페이지 — </span>
            <em>룰이 책과 얼마나 정확히 맞는지</em> 한 줄씩 검증하고 싶다면 →{" "}
            <Link to="/docs/llm-pipeline/audit" className="text-accent font-semibold hover:underline">
              LLM 분석 검증
            </Link>
          </div>
        </div>
      </details>

      {/* ① 개요 + 데이터 흐름도 */}
      <section className="bento p-6 mb-4">
        <h3 className="text-subhead font-bold text-ink mb-3">개요 — 4 단계 데이터 흐름</h3>
        <p className="text-data-xs text-muted mb-4 leading-relaxed">
          한 종목이 새로 minervini_pass 를 통과한 순간부터 매수 시그널 생성 + 8주 성과 추적까지의 자동 흐름.
          평일 20:00 cron 이 4 단계를 순차 실행. 단계마다 다른 종목 풀을 다룸 — 자세한 조건은 아래 각 카드에.
        </p>
        <MermaidDiagram chart={DIAGRAM_DATA_FLOW} idPrefix="flow" />
      </section>

      {/* ② 단계별 카드 */}
      {STAGES.map((stage) => (
        <StageCard key={stage.id} stage={stage} />
      ))}

      {/* ③ 1주일 시뮬레이션 */}
      <section className="bento p-6 mb-4">
        <h3 className="text-subhead font-bold text-ink mb-3">
          1주일 시뮬레이션 — 10 종목이 어떻게 처리되나
        </h3>
        <p className="text-data-xs text-muted mb-4 leading-relaxed">
          토(W1) → 다음 토(W2) 8 일 동안 10 종목 각각이 weekend / daily_delta / evaluate_pivot 에서 어떻게 처리되는지.
          각 셀 클릭 시 LLM 입력 / 출력 / reasoning / 영향 상세.
        </p>
        <SimulationMatrix
          days={SIMULATION_DAYS}
          rows={SIMULATION_ROWS}
          onCellClick={handleCellClick}
        />
      </section>

      <SimulationModal
        open={activeModal != null}
        modal={activeModal}
        onClose={() => setActiveModal(null)}
      />

      {/* ④ 종목 상태 전이도 */}
      <section className="bento p-6 mb-4">
        <h3 className="text-subhead font-bold text-ink mb-3">종목 상태 전이도</h3>
        <p className="text-data-xs text-muted mb-4 leading-relaxed">
          한 종목이 시스템 안에서 어떻게 상태가 바뀌어가는지. classification 컬럼은 자주 안 바뀌지만,
          entry_params row 생성이 실질 매수 시그널의 활성을 의미.
        </p>
        <MermaidDiagram chart={DIAGRAM_STATE} idPrefix="state" />
      </section>

      {/* ⑤ 트리거 × 결정 매트릭스 */}
      <TriggerDecisionMatrix />

      {/* ⑥ 용어집 */}
      <Glossary />

      {/* ⑦ FAQ */}
      <FaqSection />
    </div>
  );
}
