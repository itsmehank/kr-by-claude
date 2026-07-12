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
import { GATE_BREAKOUT_VOL_MULT, GATE_PROMOTION_PRICE_RATIO, BREAKOUT_VOL_FLOOR, BREAKOUT_VOL_PREFERRED } from "../data/thresholds.generated";
import { ENTRY_PARAMS_FIELDS, FIELD_CATEGORIES } from "../data/llm-pipeline/entry-params-fields";
import { ListFold } from "./llm-pipeline/ListFold";
import { TableExplainerList } from "./llm-pipeline/TableExplainerList";
import { TREND_TEMPLATE_CONDITIONS } from "../data/llm-pipeline/trend-template";
import { BASE_PATTERNS } from "../data/llm-pipeline-audit/base-patterns";
import { RISK_FLAGS } from "../data/llm-pipeline-audit/risk-flags";
import { ZIP_FILES } from "../data/llm-pipeline-audit/zip-files";
import { GLOSSARY } from "../data/llm-pipeline/glossary";
import { renderRich } from "./llm-pipeline/renderRich";
import { PROMPT_EXPLANATIONS, STAGE_TO_PROMPT } from "../data/llm-pipeline/prompt-explanations";
import { LifeCycleStoryModal } from "./llm-pipeline/LifeCycleStoryModal";


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
      "한 주에 한 번, 토요일 새벽 3시 20분에 자동 실행됩니다.\n\n결정론 1차 필터를 통과한 *모든* 한국 종목을 AI(LLM)가 차트와 함께 재분석해서 [[entry]] / [[watch]] / [[ignore]] 중 하나로 분류합니다.\n\n분류 결과는 weekly_classification 테이블에 새 행으로 쌓입니다 (이전 분류는 그대로 보존).",
    inputs: ["daily_indicators", "weekly_indicators", "market_context_daily", "corporate_actions", "stocks"],
    outputs: ["weekly_classification"],
    deterministicSummary:
      "AI 호출 전 1차 필터 — **[[minervini_pass]] = TRUE** 인 종목만 선별합니다.\n\n*minervini_pass* 는 Minervini Trend Template 의 8 조건을 *모두* 통과했는지를 한 컬럼으로 나타낸 boolean — 8 조건 중 하나라도 실패하면 FALSE.\n\n상장폐지된 종목 (stocks.delisted_at) 은 자동 제외.\n\n→ 8 조건의 정확한 내용은 *아래* 'Trend Template 8 조건 모두 보기' fold 참조.",
    deterministicDetail:
      "SQL 조건:\n  WHERE minervini_pass = TRUE\n    AND stocks.delisted_at IS NULL\n\n기준 행: 직전 금요일자 daily_indicators.\ncron 시각: 토 03:20 KST.\n\n💡 minervini_pass 컬럼은 daily_indicators 가 적재될 때 함께 계산 — 8 조건 모두 충족 시에만 TRUE (아래 '8 조건 모두 보기' fold 참조).",
    llmSummary:
      "각 종목별로 13 개의 파일이 든 ZIP 묶음 (차트 PNG·일/주봉 OHLCV·시장 컨텍스트·corporate actions·minervini 진단 등) 을 만들어 AI 에게 보내고, analyze_chart_v3.md prompt 의 지시를 따라 '[[base]] 패턴 + risk flag + 분류' 를 받습니다. AI 는 9 종 [[base]] 패턴과 13 종 risk flag 만 사용하도록 제약돼 있습니다.",
    llmShowsLists: {
      eightConditions: true,
      thirteenZipFiles: true,
      nineBasePatterns: true,
      thirteenRiskFlags: true,
    },
    decisions: ["entry", "watch", "ignore"],
    actionSummary:
      "분류 결과를 weekly_classification 테이블에 *새 행* 으로 추가합니다 (이전 분류는 지우지 않고 누적). 같은 종목·같은 시각의 중복은 자동 무시.\n\n분석이 끝나면 [[entry]]/[[watch]]/[[ignore]] 카운트를 Slack 으로 요약 알림 ([[Slack digest|digest]]).",
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
      "평일 매일 20:00 자동 실행됩니다.\n\nweekend 와 같은 AI prompt + 같은 ZIP 구조를 쓰지만, 대상이 다릅니다 — 결정론 필터를 *오늘 새로 통과한* 종목만.\n\n즉 다음 주 토 weekend 까지 기다리지 않고 신규 후보를 즉시 분류해서 watch/entry 풀에 합류시키는 *빠른 반응* 단계입니다.",
    inputs: ["daily_indicators", "daily_prices", "weekly_indicators", "market_context_daily"],
    outputs: ["weekly_classification"],
    deterministicSummary:
      "1차 필터는 weekend 와 동일 — **[[minervini_pass]] = TRUE** (= Trend Template 8 조건 모두 통과).\n\n추가로 *신규성* 조건: 최근 7일 안에 분류된 적이 없는 종목만 (이미 weekend 나 다른 daily_delta 에서 분류된 종목은 제외).\n\n7일 cool-down 으로 같은 종목 반복 분석 방지.",
    deterministicDetail:
      "SQL 조건:\n  WHERE minervini_pass = TRUE\n    AND NOT EXISTS (\n        SELECT 1 FROM weekly_classification\n         WHERE symbol = ticker\n           AND classified_at >= today - INTERVAL '7 days'\n    )\n\n기준 행: 오늘자 daily_indicators.\n\n💡 minervini_pass 의 의미는 weekend 카드의 '8 조건 모두 보기' fold 참조.",
    llmSummary:
      "weekend 와 정확히 같은 prompt (analyze_chart_v3.md) + 같은 ZIP 13 파일. 차이는 source 컬럼 ('daily_delta' vs 'weekend') 과 입력 풀의 신규성 필터.",
    llmShowsLists: {
      thirteenZipFiles: true,
      nineBasePatterns: true,
      thirteenRiskFlags: true,
    },
    decisions: ["entry", "watch", "ignore"],
    actionSummary:
      "weekly_classification 에 새 행으로 INSERT (source='daily_delta'). [[watch]]/[[entry]] 분류된 종목은 다음 평일부터 evaluate_pivot 의 평가 대상. [[ignore]] 분류된 종목은 7일 후 다시 신규 후보로 재진입 가능.",
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
      "이미 [[watch]] 또는 [[entry]] 로 분류된 활성 종목들의 오늘 가격·거래량을 매일 점검합니다.\n\n종가가 [[pivot]] 을 돌파했는지, 손절선을 깼는지, 50일 이동평균에서 이탈했는지 등을 *결정론 게이트* 가 먼저 검사해 이벤트 유형 ([[breakout]] / [[promotion]] / [[invalidation]]) 을 결정합니다.\n\n이벤트가 잡힌 종목만 AI 에게 '진짜 신호인가 가짜 신호인가' 묻습니다.",
    inputs: ["weekly_classification", "daily_indicators"],
    outputs: ["trigger_evaluation_log"],
    deterministicSummary:
      `세 가지 트리거를 결정론 룰로 잡습니다 — ① 종가 > pivot AND 거래량 ≥ 평균 (${GATE_BREAKOUT_VOL_MULT.toFixed(1)}×) → [[breakout]] (돌파), ② 종가 ≥ pivot × ${GATE_PROMOTION_PRICE_RATIO} → [[promotion]] (돌파 직전 staging), ③ 종가 < 손절선 또는 종가 < SMA-50 → [[invalidation]] ([[base]] 무효화). 거래량 기준은 게이트의 1.0× = '거래량이 죽지 않은 정도만' 확인이고, 책 표준 ${BREAKOUT_VOL_FLOOR}~${BREAKOUT_VOL_PREFERRED}× 와 [[pocket_pivot|pocket pivot]] 예외는 AI 가 판단합니다.`,
    deterministicDetail:
      "compute/trigger_gate.py 의 룰: pivot_price IS NULL 인 종목은 skip. close < stop_loss OR close < sma_50 → invalidation 우선 적용. 그 외 close > pivot AND volume >= avg_volume_50d × GATE_BREAKOUT_VOL_MULT → breakout. promotion 은 watch 분류 종목에만, close >= pivot × GATE_PROMOTION_PRICE_RATIO AND volume >= avg 일 때.",
    llmSummary:
      "evaluate_pivot_trigger_v1.md prompt — 게이트가 잡은 트리거 유형을 입력으로 받고 '[[go_now]] (지금 사라) / [[wait]] (기다려) / [[abort]] (가짜·무효)' 중 하나를 결정.\n\n*중요*: 이 단계는 분류 자체를 바꾸지 않습니다. abort 가 나와도 분류는 그대로 유지 — 다음 토 weekend 에서 AI 가 다시 보고 분류를 [[ignore]] 로 강등해야 비로소 강등.",
    decisions: ["go_now", "wait", "abort"],
    actionSummary:
      "결과를 trigger_evaluation_log 에 새 행으로 기록 (분류는 변경 안 함).\n\ndecision='[[go_now]]' + trigger_type='[[breakout]]' 인 종목은 다음 단계 (entry_params) 가 자동으로 매수 계획을 작성합니다.\n\n[[promotion]] 트리거에서는 [[go_now]] 가 *나오지 않도록* prompt 와 코드 양쪽에 안전장치가 있습니다 (실질 매수는 종가가 [[pivot]] 위로 올라간 진짜 [[breakout]] 으로만).",
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
      "evaluate_pivot 에서 [[go_now]] 결정을 받은 *진짜 매수 시그널* 종목에 대해 AI 가 18 개 필드의 매수 계획을 작성합니다.\n\n진입 가격·[[stop loss|손절선]]·목표가·포지션 사이즈·돌파 거래량 요건 등 매수에 필요한 모든 숫자를 한 행으로 정리.\n\n이게 시스템의 *최종 산출물* 입니다 — 사용자는 entry_params 행을 보고 실제 매수 여부를 결정.",
    inputs: ["trigger_evaluation_log", "daily_indicators", "weekly_classification"],
    outputs: ["entry_params"],
    deterministicSummary:
      "오늘자 trigger_evaluation_log 에서 decision='go_now' AND trigger_type='breakout' 행만 추출 (promotion·invalidation·abort 는 entry_params 진입 차단).",
    deterministicDetail:
      "SELECT FROM trigger_evaluation_log WHERE evaluated_at::date = today AND decision='go_now' AND trigger_type='breakout'. 이 조건이 'watch staging' 이 매수로 새지 않게 막는 안전장치.",
    llmSummary:
      "결정론 함수 entry_params_calc (#21 — 구 calculate_entry_params_v2_0.md 프롬프트를 코드로 대체) — 17 필드를 책 룰 (O'Neil 7-8% 손절, Minervini 1-3% 거래당 위험, 5% chase 제한 등) 에 맞춰 계산. [[entry_mode]] 가 [[pivot_breakout]] 인지 [[pocket_pivot]] 인지에 따라 손절·사이징 룰이 다릅니다.",
    llmShowsLists: {
      eighteenFields: true,
    },
    actionSummary:
      "entry_params 테이블에 새 행으로 INSERT (PK: symbol + signal_at). 이 행이 곧 '활성 매수 시그널'. [[performance|성과 추적]] 단계가 자동으로 이 시그널의 1주·2주·4주·8주 후 가격을 추적합니다.",
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
      "AI 호출 없는 순수 계산 단계입니다.\n\n최근 90일 안에 발생한 매수 시그널 (entry_params) 들의 1주·2주·4주·8주 후 가격을 daily_prices 에서 조회해 수익률을 계산.\n\n같은 기간의 시장 (KOSPI 또는 KOSDAQ) 수익률도 함께 기록해 *시장 대비 알파* 도 측정.\n\n8주 데이터가 모두 채워지면 추적이 사실상 끝납니다.",
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
    W["주말 batch<br/>토 03:20<br/>결정론 통과 전체 재분류"] -->|새 행 추가| B[("분류 결과 테이블<br/>weekly_classification<br/>watch / entry / ignore")]
    A["평일 신규 분류<br/>— daily_delta<br/>오늘 새로 통과한 종목만"] -->|새 행 추가| B
    B -->|매일 활성 종목 선별<br/>— 최신 분류만| C{"평일 트리거 평가<br/>— 결정론 게이트"}
    C -->|돌파 / 직전 staging<br/>/ base 무효| D["AI 평가"]
    D -->|go_now / wait / abort| E[("트리거 평가 로그<br/>trigger_evaluation_log")]
    E -->|go_now AND 진짜 돌파<br/>— staging 차단 안전장치| F["매수 계획 작성<br/>— AI 호출"]
    F --> G[("매수 계획 테이블<br/>entry_params<br/>18 필드 매수 시그널")]
    G -->|매일 자동| H["성과 추적<br/>1주·2주·4주·8주 후"]
    H --> I[("성과 테이블<br/>signal_performance")]
`;

const DIAGRAM_STATE = `stateDiagram-v2
    [*] --> 후보전: 결정론 8조건 통과
    후보전 --> Watch: 주말/평일 AI 분류 (watch)
    후보전 --> Entry: 주말/평일 AI 분류 (entry)
    후보전 --> Ignore: 주말/평일 AI 분류 (ignore)
    Watch --> Watch: 평일 평가 wait/abort (분류 유지)
    Watch --> Entry: 다음 주말 재분석 시 승격
    Entry --> Entry: 평일 평가 wait/abort (분류 유지)
    Entry --> 매수계획: 진짜 돌파 + go_now
    Entry --> Ignore: 다음 주말 재분석 시 강등
    매수계획 --> 성과추적: 자동 시작
    성과추적 --> [*]: 시그널 발생 90일 후 종료
    Ignore --> [*]: 7일 후 다시 신규 후보 가능
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
      next: "매수 계획 (entry_params) 자동 생성. 사용자가 행을 보고 실제 매수 결정.",
    },
    wait: {
      meaning: `돌파했지만 AI 가 보류 — 약한 신호 (예: 거래량이 ${BREAKOUT_VOL_FLOOR}× 미만, base 가 약간 wide) 일 가능성.`,
      next: "매수 계획 생성 안 됨. 다음 평일에 재평가. entry 분류는 그대로 유지.",
    },
    abort: {
      meaning: "돌파처럼 보였으나 AI 가 가짜로 판정 — 예: 다음날 즉시 되돌림 우려 / 시장 약세 중복.",
      next: "매수 계획 안 만듦. 분류 자체는 entry 유지. 다음 토 weekend 의 재분석이 base 무효 판단 시 비로소 ignore 강등.",
    },
  },
  promotion: {
    go_now: null,  // 시스템 안전장치 — promotion 에서 go_now 발생 금지
    wait: {
      meaning: "watch 종목이 pivot 의 95% 까지 도달 — 돌파 직전 staging 상태. 거래량은 평균 이상. close 는 아직 pivot 미만이라 매수 신호 아님.",
      next: "다음 평일에 게이트가 다시 평가. 종가가 pivot 위로 올라가면 별도 breakout 트리거로 처리.",
    },
    abort: {
      meaning: "base 가 깨질 조짐 — SMA-50 이탈, distribution day 누적 등. AI 가 위험 신호로 판단.",
      next: "watch 분류 유지 (분류 변경 안 함). 다음 토 weekend 에서 ignore 로 강등될 후보.",
    },
  },
  invalidation: {
    go_now: null,
    wait: null,
    abort: {
      meaning: "base 가 무효화 — 종가가 손절선 또는 SMA-50 아래로 이탈. AI 호출 없이 결정론으로 abort 확정.",
      next: "분류는 entry/watch 그대로 유지하지만, 다음 weekend 또는 daily_delta 재분류 까지 평가 사이클에서 사실상 제외.",
    },
  },
};


// FAQ

const FAQ: { q: string; a: string }[] = [
  {
    q: "Watch 가 evaluate_pivot 의 LLM 결정으로 자동 entry 로 승격되지 않는 이유?",
    a:
      "평일 트리거 평가 단계 (evaluate_pivot) 의 prompt 가 *분류 변경 금지* 정책을 명시합니다 — classification 은 매주 토 weekend 또는 평일 신규 분류 (daily_delta) 에서만 변경. promotion 트리거는 '돌파 직전 staging' 일 뿐 매수 신호가 아니며 (prompt §3.3), go_now 가 발생하지 않도록 코드 안전장치도 적용 (entry_params 자동 수집은 trigger_type='breakout' 인 행만). watch 종목이 실제 매수로 가려면 다음 평일 종가가 pivot 위로 올라가는 *진짜 돌파* 가 별도로 발생해야 합니다.",
  },
  {
    q: "Pivot 이 없는 watch 종목은 어떻게 되나?",
    a:
      "evaluate_pivot 의 결정론 게이트가 pivot_price 가 NULL 인 종목을 skip — 매일 평가 사이클에서 빠집니다. 다음 토 weekend 또는 daily_delta 가 그 종목을 재분류해서 pivot 을 새로 부여할 때까지 정지 상태로 대기.",
  },
  {
    q: "daily_delta 와 weekend batch 의 차이?",
    a:
      "두 단계는 *같은 prompt (analyze_chart_v3.md) + 같은 ZIP 13 파일* 을 씁니다. 차이는 대상 풀: daily_delta = 신규 (최근 7일 안에 분류된 적 없는 결정론 통과 종목), weekend = 결정론 통과 전체 (이미 분류된 종목도 재분석). daily_delta 는 평일 매일 20:00 (LLM 4 단계의 첫 단계), weekend 는 토 03:20 (주 1회 전체 결산).",
  },
  {
    q: "dry-run 모드는 DB 에 영향이 있나?",
    a:
      "전혀 없습니다 — mock LLM 응답을 받아 응답 파싱·검증까지는 진행하지만, DB 저장 직전에 가드가 INSERT 를 skip 합니다. weekly_classification / trigger_evaluation_log / entry_params 어느 테이블도 변하지 않습니다.",
  },
  {
    q: "weekend 와 daily_delta 가 같은 prompt 라면 둘 다 필요한가?",
    a:
      "시점이 다릅니다. weekend = 매주 한 번 *전체 결산* (모든 결정론 통과 종목 재분류 → 이전 분류와 다를 수 있음, 예: entry → ignore). daily_delta = 평일에 *새로 결정론 통과한 종목만* 즉시 분류 (7일을 기다리지 않고 조기 포착). 결과적으로 모든 결정론 통과 종목은 주 1회 weekend 로 재분석되고, 그 사이 신규는 daily_delta 로 즉시 합류.",
  },
  {
    q: "evaluate_pivot 의 abort 가 종목 분류를 ignore 로 바꾸나?",
    a:
      "아니요. evaluate_pivot 은 trigger_evaluation_log 에 한 행 기록할 뿐, weekly_classification 의 분류는 그대로 둡니다. abort 가 매일 누적되어도 분류는 여전히 entry/watch. 다음 토 weekend 의 AI 가 *재분석* 후 base 가 깨졌다고 판단하면 비로소 ignore 로 재분류.",
  },
  {
    q: "한 종목이 한 주에 여러 번 분류될 수 있나?",
    a:
      "가능합니다. 예: 토 weekend 에 분류 (entry 재분석). 다만 그다음 평일 daily_delta 는 같은 종목을 다시 분류하지 못합니다 (최근 7일 안에 분류 이력이 있어 '신규' 조건 미충족). 다음 주 토 weekend 에서 또 재분석되어 새 행 추가. 결국 한 종목은 weekend 마다 *주 1회 재분석* 되고, daily_delta 는 *진짜 신규* 만 받습니다.",
  },
];


// ─────── 컴포넌트 ───────────────────────────────────────────

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
      <p className="text-data text-muted mb-5 leading-relaxed">{renderRich(stage.intro)}</p>

      {/* 입출력 테이블 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-5">
        <TableExplainerList names={stage.inputs} label="📥 입력 테이블" />
        <TableExplainerList names={stage.outputs} label="📤 출력 테이블" />
      </div>

      {/* 결정론 룰 */}
      <div className="mb-5">
        <div className="caps text-faint mb-1">⚙️ 결정론 룰</div>
        <p className="text-data text-ink leading-relaxed">{renderRich(stage.deterministicSummary)}</p>
        {stage.deterministicDetail && (
          <ListFold label="결정론 룰 SQL·상세 보기">
            <div>{renderRich(stage.deterministicDetail)}</div>
          </ListFold>
        )}
        {stage.llmShowsLists?.eightConditions && (
          <ListFold label="Trend Template 8 조건 모두 보기" count={TREND_TEMPLATE_CONDITIONS.length}>
            <div className="mb-3 text-muted">
              <span className="text-ink font-semibold">minervini_pass = TRUE</span> 는 곧 *아래 8 조건을 모두 통과* 함을 뜻합니다.
              Minervini <em>Trade Like a Stock Market Wizard</em> Ch.5 의 추세 식별 기준.
            </div>
            <ol className="space-y-3 list-decimal list-inside">
              {TREND_TEMPLATE_CONDITIONS.map((c) => (
                <li key={c.num} className="text-ink">
                  <span className="font-semibold">{c.shortLabel}</span>
                  <div className="ml-5 mt-1 text-muted">
                    {c.meaning}
                  </div>
                  <div className="ml-5 mt-1 text-faint text-data-xs">
                    <span className="num">{c.rule}</span>
                    {c.threshold && <span> · {c.threshold}</span>}
                  </div>
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
            <p className="text-data text-ink leading-relaxed">{renderRich(stage.llmSummary)}</p>
            {stage.decisions && (
              <div className="flex flex-wrap gap-1 mt-2">
                {stage.decisions.map((d) => <DecisionChip key={d} value={d} />)}
              </div>
            )}
            {(() => {
              const promptKey = STAGE_TO_PROMPT[stage.id];
              if (!promptKey) return null;
              const exp = PROMPT_EXPLANATIONS[promptKey];
              if (!exp) return null;
              return (
                <ListFold label={`이 prompt 가 정확히 뭐 하는지 — ${exp.filename}`}>
                  <div className="space-y-4">
                    <div>
                      <div className="text-ink font-semibold mb-1">📝 역할</div>
                      <div>{exp.role}</div>
                    </div>
                    <div>
                      <div className="text-ink font-semibold mb-1">📥 AI 가 받는 자료</div>
                      <ul className="list-disc list-inside space-y-1 ml-2">
                        {exp.input.map((item, i) => (
                          <li key={i}>{item}</li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <div className="text-ink font-semibold mb-1">📤 AI 가 만드는 결과</div>
                      <ul className="list-disc list-inside space-y-1 ml-2">
                        {exp.output.map((item, i) => (
                          <li key={i}>{item}</li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <div className="text-ink font-semibold mb-1">📖 핵심 룰</div>
                      <ul className="space-y-2 ml-2">
                        {exp.keyRules.map((rule, i) => (
                          <li key={i} className="flex">
                            <span className="text-faint mr-2">·</span>
                            <span dangerouslySetInnerHTML={{ __html: rule.replace(/\*\*([^*]+)\*\*/g, "<strong class=\"text-ink\">$1</strong>") }} />
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </ListFold>
              );
            })()}
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
        <p className="text-data text-ink leading-relaxed">{renderRich(stage.actionSummary)}</p>
        {stage.actionDetail && (
          <ListFold label="SQL INSERT / 엔지니어링 상세 보기">
            <div>{renderRich(stage.actionDetail)}</div>
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
        9 칸 중 *적용 안 됨* 3 칸은 시스템 안전장치 (promotion·invalidation 에서 매수 시그널 직행 차단).
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
  const [storyOpen, setStoryOpen] = useState(false);

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
        <p className="text-data text-muted mt-3 leading-relaxed">
          이 시스템이 매일·매주 한국 주식을 어떻게 자동 분류하고 매수 시그널까지
          만드는지 단계별로 보여줍니다. 결정론 1차 필터 → AI 분류 → 평일 트리거
          평가 → 매수 계획 → 사후 성과 추적 의 5 단계 흐름과 책 원전 (Minervini /
          O'Neil) 근거. 가상 10 종목이 한 주 동안 어떻게 처리되는지 시뮬레이션도 함께.
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
              <li><span className="text-ink">5 단계 파이프라인</span> — 결정론 1차 필터 (Minervini Trend Template 8 조건) → AI 분류 → 평일 트리거 평가 → 매수 계획 작성 → 사후 성과 추적.</li>
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

      <section className="bento p-6 mb-4">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h3 className="text-subhead font-bold text-ink mb-1">🎬 종목 생애주기 따라가기</h3>
            <p className="text-data text-muted">가상 종목 한 개의 일생(상장 → 분류 → 진입 → 손절·이탈)을 9장면 이야기로. 초보도 시스템 구조가 한눈에.</p>
          </div>
          <button onClick={() => setStoryOpen(true)}
            className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold shrink-0">이야기 시작 →</button>
        </div>
      </section>

      {/* ① 개요 + 데이터 흐름도 */}
      <section className="bento p-6 mb-4">
        <h3 className="text-subhead font-bold text-ink mb-3">개요 — 자동 흐름 한눈에</h3>
        <p className="text-data-xs text-muted mb-3 leading-relaxed">
          한 종목이 새로 결정론 8조건을 통과한 순간부터 *매수 시그널 생성 + 8주 성과 추적* 까지의 자동 흐름.
          평일 20:00 cron 이 4 단계를 순차 실행 (신규 분류 → 평일 평가 → 매수 계획 → 성과 추적), 매주 토 03:20 에는 전체 재분류 (weekend batch) 가 한 번 더.
        </p>
        <details className="mb-3 group">
          <summary className="cursor-pointer text-data-xs text-ink font-semibold select-none list-none">
            <span className="group-open:hidden">📖 이 그림 읽는 법 ▼</span>
            <span className="hidden group-open:inline">📖 이 그림 읽는 법 ▲</span>
          </summary>
          <div className="mt-2 text-data-xs text-muted leading-relaxed">
            <ul className="list-disc list-inside space-y-1">
              <li><strong>둥근 사각형</strong> 은 *처리 단계* (cron 또는 AI 호출). 화살표 라벨은 *조건/트리거*.</li>
              <li><strong>원통형</strong> 은 *데이터 테이블* (DB 에 저장되는 결과).</li>
              <li><strong>다이아몬드</strong> 는 *결정론 게이트* (코드 룰로 분기).</li>
              <li>전체 흐름은 왼쪽 → 오른쪽. 같은 테이블에 여러 단계가 행을 추가할 수 있음 (예: 분류 테이블 ← 주말 + 평일).</li>
            </ul>
          </div>
        </details>
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
      <LifeCycleStoryModal open={storyOpen} onClose={() => setStoryOpen(false)} />

      {/* ④ 종목 상태 전이도 */}
      <section className="bento p-6 mb-4">
        <h3 className="text-subhead font-bold text-ink mb-3">종목 상태 전이도</h3>
        <p className="text-data-xs text-muted mb-3 leading-relaxed">
          한 종목이 시스템 안에서 *어떤 상태* (분류) 로 시작해 어떻게 변하는지. 분류 자체는 잘 안 바뀌고
          (평일 평가는 분류 변경 안 함), *매수 계획 테이블 (entry_params) 에 행이 생기는 순간* 이 실질
          매수 시그널 활성을 의미합니다.
        </p>
        <details className="mb-3 group">
          <summary className="cursor-pointer text-data-xs text-ink font-semibold select-none list-none">
            <span className="group-open:hidden">📖 이 그림 읽는 법 ▼</span>
            <span className="hidden group-open:inline">📖 이 그림 읽는 법 ▲</span>
          </summary>
          <div className="mt-2 text-data-xs text-muted leading-relaxed">
            <ul className="list-disc list-inside space-y-1">
              <li>각 박스는 *상태* (분류 또는 활성). 화살표 라벨은 *전이 조건* (어떤 사건으로 상태가 바뀌나).</li>
              <li>Self-loop (자기로 돌아가는 화살표) 는 *상태 유지* — 예: Entry → Entry (평일 평가에서 wait/abort 나와도 entry 분류 유지).</li>
              <li>[*] 는 시스템 진입/종료 — 결정론 8조건 통과 시 진입, 90일 후 (성과 추적 종료) 또는 7일 후 (Ignore 재진입 가능) 종료.</li>
            </ul>
          </div>
        </details>
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
