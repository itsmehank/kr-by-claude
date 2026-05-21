import { MermaidDiagram } from "../components/MermaidDiagram";
import { useState } from "react";
import {
  SIMULATION_DAYS,
  SIMULATION_ROWS,
  type SimDay,
  type SimModal,
  type SimRow,
} from "../data/llm-pipeline-simulation";
import { SimulationMatrix } from "./llm-pipeline/SimulationMatrix";
import { SimulationModal } from "./llm-pipeline/SimulationModal";


// ─────── 데이터 ───────────────────────────────────────────

interface PipelineStage {
  id: string;
  order: number;
  label: string;
  summary: string;
  targets: string;
  inputs: string[];
  outputs: string[];
  deterministic: string;
  llm: string | null;
  decisions?: string[];
  actions: string;
  sources: string[];
  codeRef: string;
}

const STAGES: PipelineStage[] = [
  {
    id: "weekend",
    order: 0,
    label: "주말 batch — 전체 재분류",
    summary:
      "결정론 통과 모든 종목을 토 새벽 LLM 으로 재분류 (전체 갱신). daily_delta 와 같은 prompt, 차이는 입력 필터.",
    targets:
      "토요일 03:20 cron. daily_indicators 의 직전 금요일 행 기준 minervini_pass=TRUE AND stocks.delisted_at IS NULL 전체.",
    inputs: ["daily_indicators", "weekly_indicators", "market_context_daily", "corporate_actions", "stocks"],
    outputs: ["weekly_classification (source='weekend')"],
    deterministic: "결정론 필터 — minervini_pass (Trend Template 8조건).",
    llm:
      "analyze_chart_v3.md prompt (daily_delta 와 동일). ZIP 13개 파일 (payload.json + 일/주봉 OHLCV + 차트 PNG + 시장 컨텍스트 + corporate actions + minervini detail 등). 9개 base 패턴 + 13 risk flag taxonomy.",
    decisions: ["entry", "watch", "ignore"],
    actions:
      "weekly_classification 에 INSERT (source='weekend'). ON CONFLICT (symbol, classified_at) DO NOTHING. 이전 분류가 있어도 새 row 추가 — '현재 분류'는 DISTINCT ON (symbol) ORDER BY classified_at DESC. Slack digest 알림 (entry/watch/ignore 카운트).",
    sources: [
      "Minervini Trend Template (8 conditions)",
      "O'Neil HMM base patterns",
    ],
    codeRef: "kr_pipeline/llm_runner/weekend.py + modes.py:run_weekend",
  },
  {
    id: "daily_delta",
    order: 1,
    label: "신규 후보 분류",
    summary:
      "오늘 새로 결정론 통과한 신규 종목만 LLM 분류 — weekend 와 같은 prompt, 신규 종목만 다룸.",
    targets:
      "daily_indicators 의 오늘 행 중 minervini_pass=TRUE + 최근 7일 내 분류 이력 없음 (= 신규 후보). weekend 와의 차이: weekend 는 결정론 통과 전체를 매주 재분석. daily_delta 는 그 사이 평일에 새로 결정론 통과한 종목만 빠르게 분류.",
    inputs: ["daily_indicators", "daily_prices", "weekly_indicators", "market_context_daily"],
    outputs: ["weekly_classification (source='daily_delta')"],
    deterministic: "결정론 필터 — minervini_pass + 신규성 (7일).",
    llm:
      "analyze_chart_v3.md prompt (weekend 와 동일) + zip 13개 파일 (payload.json + market_context + corporate_actions + minervini detail + daily/weekly chart 이미지 등). 9개 base 패턴 + 13 risk flag taxonomy 적용. 차이는 source 컬럼 ('daily_delta' vs 'weekend') 과 입력 필터 (신규성 추가).",
    decisions: ["watch", "entry", "ignore"],
    actions:
      "weekly_classification 에 INSERT (source='daily_delta'). watch/entry 는 evaluate_pivot 의 다음 평가 대상, ignore 는 7일 후 재진입 가능.",
    sources: ["Minervini Trend Template", "O'Neil HMM 'How to Read Charts Like a Pro'"],
    codeRef: "kr_pipeline/llm_runner/daily_delta.py",
  },
  {
    id: "evaluate_pivot",
    order: 2,
    label: "Watch/Entry 트리거 평가",
    summary: "활성 watch/entry 종목의 오늘 행동 (돌파/손절/추세) 매일 확인",
    targets:
      "weekly_classification 의 종목별 최신 분류가 watch 또는 entry + daily_indicators 의 오늘 행 있음 (close, volume, sma_50, avg_volume_20d 모두 NOT NULL + pivot_price NOT NULL).",
    inputs: ["weekly_classification", "daily_indicators"],
    outputs: ["trigger_evaluation_log"],
    deterministic:
      "결정론 트리거 게이트 (compute/trigger_gate.py): close < stop_loss 또는 close < sma_50 → invalidation. entry 종목: close > pivot AND volume >= avg_volume_50d (1.0×, 게이트는 거래량 죽지 않은 정도만 확인 — 1.4~1.5× 표준 / pocket pivot 예외 판정은 LLM 에 위임) → breakout. watch 종목: close >= pivot × 0.95 AND volume >= avg → promotion (책 근거 없음, 시스템 staging 트리거 — go_now 발생 금지, close > pivot 도달은 별도 breakout 트리거가 처리).",
    llm:
      "evaluate_pivot_trigger_v1.md prompt — 게이트 통과 종목만 호출. '이 트리거가 진짜인가, 가짜 신호인가, 보류인가' 판단.",
    decisions: ["go_now", "wait", "abort"],
    actions:
      "trigger_evaluation_log 에 INSERT. 분류 자체는 변경 안 함 (prompt 명시) — abort decision 이라도 weekly_classification 의 row 는 그대로 유지. 다음 토요일 weekend batch 에서 LLM 이 재분석 후 ignore 로 분류해야 비로소 강등됨. decision='go_now' 인 종목은 entry_params 가 자동 수집.",
    sources: [
      "O'Neil HMM ch.2 Volume Percent Change (1.5× breakout)",
      "Minervini buy/sell rules",
    ],
    codeRef: "kr_pipeline/llm_runner/evaluate_pivot.py + compute/trigger_gate.py",
  },
  {
    id: "entry_params",
    order: 3,
    label: "매수 계획 (entry_params)",
    summary: "오늘 trigger_evaluation_log 에 go_now 결정된 종목의 매수 계획 17 필드 작성",
    targets: "trigger_evaluation_log 의 오늘 행 중 decision='go_now'.",
    inputs: ["trigger_evaluation_log", "daily_indicators", "weekly_classification"],
    outputs: ["entry_params"],
    deterministic: "decision='go_now' 행 필터.",
    llm:
      "calculate_entry_params_v2_0.md prompt — entry_mode, trigger_price, entry_price, stop_loss + 기준, expected_target_price + %, RR, position_size_pct + 기준, breakout_volume_requirement, observed_breakout_volume_ratio, known_warnings, other_warnings, notes 17개 필드 계산.",
    actions:
      "entry_params 에 INSERT (PK: symbol + signal_at). performance 가 다음 단계에서 자동 추적.",
    sources: ["Minervini risk management (1-3% per trade)", "O'Neil HMM 'Buy at the Buy Point'"],
    codeRef: "kr_pipeline/llm_runner/entry_params.py",
  },
  {
    id: "performance",
    order: 4,
    label: "시그널 성과 추적",
    summary: "최근 90일 내 entry_params signal 의 1/2/4/8주 후 가격 및 시장 대비 수익률 추적",
    targets:
      "entry_params 의 signal_at 가 최근 90일 내. 8주 후까지만 추적 (price_8w 채워지면 종료).",
    inputs: ["entry_params", "daily_prices", "index_daily"],
    outputs: ["signal_performance"],
    deterministic:
      "signal_at 기준 +7/+14/+28/+56 일 후 daily_prices 의 close 조회. 시장 (KOSPI/KOSDAQ index_daily) 수익률도 함께.",
    llm: null,
    actions:
      "signal_performance 의 (symbol, signal_at) 행 UPSERT. 같은 종목의 여러 entry signal 은 signal_at 별 독립 추적.",
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
    go_now: { meaning: "entry 종목 진짜 돌파 + LLM 확인", next: "entry_params 자동 생성 → 매수 시그널 활성" },
    wait: { meaning: "돌파했지만 LLM 보류", next: "다음 날 재평가, entry_params 없음" },
    abort: { meaning: "가짜 돌파로 판정", next: "무시. 분류는 entry 유지" },
  },
  promotion: {
    go_now: null,
    wait: { meaning: "watch → pivot 95% 근접 staging — close 아직 pivot 미만, 정상 흐름", next: "다음 평일 게이트 재평가. close > pivot 도달 시 breakout 트리거로 별도 처리" },
    abort: { meaning: "base 무효화 신호 (sma_50 이탈 / distribution 누적)", next: "watch 유지하다 다음 weekend batch 에서 ignore 분류 후보" },
  },
  invalidation: {
    go_now: null,
    wait: null,
    abort: { meaning: "base 무효화 (close < stop_loss 또는 sma_50)", next: "다음 weekend/daily_delta 까지 재분류 정지" },
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
      <div className="flex items-center gap-3 mb-3">
        <span className="num text-data-xs text-faint shrink-0">{stage.order}</span>
        <span className="num text-data-xs bg-tint-violet text-accent px-2 py-0.5 rounded shrink-0">
          {stage.id}
        </span>
        <h3 className="text-subhead font-bold text-ink flex-1">{stage.label}</h3>
      </div>
      <p className="text-data text-muted mb-4">{stage.summary}</p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-data-xs">
        <div>
          <div className="caps text-faint mb-1">대상 종목</div>
          <p className="text-data text-ink leading-relaxed">{stage.targets}</p>
        </div>
        <div className="space-y-2">
          <div>
            <div className="caps text-faint mb-1">입력 테이블</div>
            <div className="flex flex-wrap gap-1">
              {stage.inputs.length === 0 ? (
                <span className="text-faint">없음</span>
              ) : (
                stage.inputs.map((t) => <TableChip key={t} name={t} />)
              )}
            </div>
          </div>
          <div>
            <div className="caps text-faint mb-1">출력 테이블</div>
            <div className="flex flex-wrap gap-1">
              {stage.outputs.map((t) => <TableChip key={t} name={t} />)}
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-data-xs">
        <div>
          <div className="caps text-faint mb-1">결정론 로직</div>
          <p className="text-data text-ink leading-relaxed">{stage.deterministic}</p>
        </div>
        <div>
          <div className="caps text-faint mb-1">LLM 로직</div>
          <p className="text-data text-ink leading-relaxed">
            {stage.llm ?? <span className="text-faint">LLM 호출 없음 (순수 계산)</span>}
          </p>
          {stage.decisions && (
            <div className="flex flex-wrap gap-1 mt-2">
              {stage.decisions.map((d) => <DecisionChip key={d} value={d} />)}
            </div>
          )}
        </div>
      </div>

      <div className="mt-4">
        <div className="caps text-faint mb-1">결과 액션</div>
        <p className="text-data text-ink leading-relaxed text-data-xs">{stage.actions}</p>
      </div>

      {stage.sources.length > 0 && (
        <div className="mt-4">
          <div className="caps text-faint mb-1">책 원전</div>
          <div className="flex flex-wrap gap-3">
            {stage.sources.map((s) => <SourceChip key={s} src={s} />)}
          </div>
        </div>
      )}

      <div className="mt-4 pt-3 border-t border-hairline">
        <div className="caps text-faint mb-1">코드 참조</div>
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
      <p className="text-data-xs text-muted mb-4">
        결정론 게이트가 트리거 유형을 결정 → LLM 이 어떻게 대응할지 결정. 두 차원의 조합으로 다음 액션이 정해짐.
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
