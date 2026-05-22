# LLM 분석 안내 페이지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/docs/llm-pipeline` 라우트에 LLM 분석 4 단계 (daily_delta / evaluate_pivot / entry_params / performance) 의 흐름·로직·조건·책 원전을 정적 정리한 안내 페이지를 추가. Mermaid 다이어그램 2개 + 단계별 카드 + 트리거 매트릭스 + 용어집 + FAQ.

**Architecture:** 페이지 1개 (`LlmPipelinePage.tsx`) 안에 typed 콘텐츠 (STAGES 상수) hardcode. Mermaid 다이어그램은 `MermaidDiagram` wrapper 컴포넌트 (mermaid 라이브러리를 dynamic import 로 lazy load) 통해 렌더. **DB / API / Backend 변경 없음.**

**Tech Stack:** TypeScript, React 19, react-router-dom, lucide-react, Tailwind, **mermaid** (신규 의존성, dynamic import).

**Spec:** `docs/superpowers/specs/2026-05-20-llm-pipeline-docs-page-design.md`

---

## ⚙️ Goal State

다음 모두 충족 시 종료:

1. 모든 task 체크박스 완료
2. `web/package.json` 에 `mermaid` 의존성 추가
3. `MermaidDiagram` 컴포넌트가 `web/src/components/MermaidDiagram.tsx` 에 존재 + dynamic import 패턴
4. `LlmPipelinePage` 가 `/docs/llm-pipeline` 라우트에 마운트, 7 섹션 (헤더 / 개요 / 단계별 카드 / 상태 전이도 / 매트릭스 / 용어집 / FAQ) 모두 렌더
5. 사이드바에 "LLM 분석 안내" 메뉴 노출
6. Frontend tsc 0 errors
7. Backend 영향 없음 (변경 없음)
8. 수동 검증: 페이지 진입 → Mermaid 다이어그램 2개 정상 렌더 + 모든 섹션 표시
9. `git status` clean

---

## 사전 조건

- HEAD: `355e3d7` (spec commit) 또는 이후
- npm 설치 가능 (web 디렉토리)
- 기존 사이드바 / 라우팅 패턴 (App.tsx) 정상

---

## Task 1: 의존성 + MermaidDiagram 컴포넌트

**Files:**
- Modify: `web/package.json` (자동, npm install 결과)
- Modify: `web/package-lock.json` (자동)
- Create: `web/src/components/MermaidDiagram.tsx`

### Step 1: mermaid 설치

```bash
cd ~/kr-by-claude/web
npm install mermaid
```

확인:
```bash
grep "mermaid" package.json
```

Expected: `"mermaid": "^11.x.x"` 또는 비슷 (가장 최신 호환 버전).

### Step 2: `MermaidDiagram` wrapper 컴포넌트

`web/src/components/MermaidDiagram.tsx` 신규:

```tsx
import { useEffect, useRef, useState } from "react";


interface MermaidDiagramProps {
  /** Mermaid diagram source (e.g., "graph LR\n  A --> B"). */
  chart: string;
  /** Optional id prefix (used for unique SVG id when multiple diagrams on one page). */
  idPrefix?: string;
}

let _mermaidPromise: Promise<typeof import("mermaid").default> | null = null;

function loadMermaid() {
  if (!_mermaidPromise) {
    _mermaidPromise = import("mermaid").then((mod) => {
      mod.default.initialize({
        startOnLoad: false,
        theme: "neutral",
        flowchart: { useMaxWidth: true, htmlLabels: true },
        themeVariables: {
          fontFamily: "inherit",
        },
      });
      return mod.default;
    });
  }
  return _mermaidPromise;
}


export function MermaidDiagram({ chart, idPrefix = "mermaid" }: MermaidDiagramProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const idRef = useRef(`${idPrefix}-${Math.random().toString(36).slice(2)}`);

  useEffect(() => {
    let cancelled = false;
    loadMermaid()
      .then(async (mermaid) => {
        if (cancelled || !ref.current) return;
        try {
          const { svg } = await mermaid.render(idRef.current, chart);
          if (cancelled || !ref.current) return;
          ref.current.innerHTML = svg;
          setError(null);
        } catch (e) {
          setError(String(e));
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [chart]);

  if (error) {
    return (
      <div className="text-danger text-data-xs num bg-paper border border-hairline rounded-lg p-3">
        Mermaid 렌더 실패: {error}
      </div>
    );
  }
  return <div ref={ref} className="mermaid-container overflow-x-auto" />;
}
```

핵심 설계:
- **Dynamic import** (`import("mermaid")`) — 페이지 첫 로드 시 mermaid 번들 (~1MB) 안 받음, 다이어그램 사용 페이지 진입 시에만
- **모듈 레벨 캐시** (`_mermaidPromise`) — 여러 다이어그램이 한 페이지에 있어도 mermaid 한 번만 import + initialize
- **unique id** (`Math.random()`) — 한 페이지에 다이어그램 여러 개일 때 SVG id 충돌 방지
- **취소 가드** (`cancelled`) — 컴포넌트 언마운트 시 stale write 방지

### Step 3: tsc

```bash
cd ~/kr-by-claude/web && npx tsc --noEmit
```

Expected: 0 errors.

### Step 4: Commit

```bash
cd ~/kr-by-claude
git add web/package.json web/package-lock.json web/src/components/MermaidDiagram.tsx
git commit -m "feat(web): MermaidDiagram wrapper (dynamic import 로 lazy load)"
```

NEVER add Co-Authored-By trailer.

---

## Task 2: LlmPipelinePage + 라우트 + 사이드바

**Files:**
- Create: `web/src/pages/LlmPipelinePage.tsx`
- Modify: `web/src/App.tsx`

### Step 1: `LlmPipelinePage.tsx` 본문 작성

`web/src/pages/LlmPipelinePage.tsx` 신규:

```tsx
import { MermaidDiagram } from "../components/MermaidDiagram";


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
    id: "daily_delta",
    order: 1,
    label: "신규 후보 분류",
    summary: "오늘 새로 minervini_pass 통과한 종목을 LLM 으로 1차 분류",
    targets:
      "daily_indicators 의 오늘 행 중 minervini_pass=TRUE AND drawdown_filter_pass=TRUE + 최근 7일 내 분류 이력 없음 (= 신규 후보).",
    inputs: ["daily_indicators", "daily_prices", "weekly_indicators", "market_context_daily"],
    outputs: ["weekly_classification"],
    deterministic: "결정론 필터 — minervini_pass + drawdown_filter + 신규성 (7일).",
    llm:
      "analyze_chart_v3.md prompt + zip 13개 파일 (payload.json + market_context + corporate_actions + minervini detail + daily/weekly chart 이미지 등). 9개 base 패턴 + 13 risk flag taxonomy 적용.",
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
      "결정론 트리거 게이트 (compute/trigger_gate.py): close < stop_loss 또는 close < sma_50 → invalidation. entry 종목: close > pivot AND volume >= 1.5× avg → breakout. watch 종목: close >= pivot × 0.95 AND volume >= avg → promotion.",
    llm:
      "evaluate_pivot_trigger_v1.md prompt — 게이트 통과 종목만 호출. '이 트리거가 진짜인가, 가짜 신호인가, 보류인가' 판단.",
    decisions: ["go_now", "wait", "abort"],
    actions:
      "trigger_evaluation_log 에 INSERT. 분류 자체는 변경 안 함 (prompt 명시). decision='go_now' 인 종목은 entry_params 가 자동 수집.",
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
    A["새 minervini_pass<br/>+ drawdown 통과<br/>종목"] -->|daily_delta| B[("weekly_classification<br/>watch / entry / ignore")]
    B -->|매일 활성 종목| C{"evaluate_pivot<br/>결정론 게이트"}
    C -->|"breakout / promotion /<br/>invalidation"| D["LLM 평가"]
    D -->|"go_now / wait / abort"| E[("trigger_evaluation_log")]
    E -->|"decision=go_now<br/>자동 수집"| F["entry_params<br/>LLM 호출"]
    F --> G[("entry_params<br/>매수 계획 17 필드")]
    G -->|매일 자동| H["performance<br/>1주/2주/4주/8주 추적"]
    H --> I[("signal_performance")]
`;

const DIAGRAM_STATE = `stateDiagram-v2
    [*] --> Unclassified: minervini_pass 통과
    Unclassified --> Watch: daily_delta watch
    Unclassified --> Entry: daily_delta entry
    Unclassified --> Ignore: daily_delta ignore
    Watch --> Watch: evaluate_pivot wait/abort
    Watch --> EntryParams: promotion + go_now
    Entry --> Entry: evaluate_pivot wait/abort
    Entry --> EntryParams: breakout + go_now
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
    go_now: { meaning: "watch → pivot 95% 도달 + LLM 진입 추천", next: "entry_params 자동 생성 (분류는 watch 유지)" },
    wait: { meaning: "근접했지만 LLM 보류", next: "다음 날 재평가" },
    abort: { meaning: "가짜 신호", next: "watch 유지, 무시" },
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
    a: "evaluate_pivot 의 prompt 가 명시적으로 '분류 재평가 금지' 정책. classification 은 weekend 또는 daily_delta 만 변경. evaluate_pivot 은 promotion 트리거 + go_now 결정 시 entry_params 만 생성 (분류는 watch 유지). 실질 매수 시그널은 entry_params 의 새 row 로 표현됨.",
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
  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      <header className="mb-8">
        <div className="caps text-faint mb-2">Documentation</div>
        <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
          LLM 분석 안내
        </h2>
        <p className="text-data-xs text-muted mt-3 leading-relaxed">
          평일 매일 실행되는 LLM full-daily 작업의 4 단계 흐름, 결정론 로직, LLM 로직, 책 원전 정리.
          시스템 이해 + 향후 수정의 기반.
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

      {/* ③ 종목 상태 전이도 */}
      <section className="bento p-6 mb-4">
        <h3 className="text-subhead font-bold text-ink mb-3">종목 상태 전이도</h3>
        <p className="text-data-xs text-muted mb-4 leading-relaxed">
          한 종목이 시스템 안에서 어떻게 상태가 바뀌어가는지. classification 컬럼은 자주 안 바뀌지만,
          entry_params row 생성이 실질 매수 시그널의 활성을 의미.
        </p>
        <MermaidDiagram chart={DIAGRAM_STATE} idPrefix="state" />
      </section>

      {/* ④ 트리거 × 결정 매트릭스 */}
      <TriggerDecisionMatrix />

      {/* ⑤ 용어집 */}
      <Glossary />

      {/* ⑥ FAQ */}
      <FaqSection />
    </div>
  );
}
```

### Step 2: `App.tsx` 변경

`web/src/App.tsx`:

1. 기존 lucide-react import 줄에 `BookOpen` 추가
2. 페이지 import 추가:
   ```tsx
   import LlmPipelinePage from "./pages/LlmPipelinePage";
   ```
3. `NAV_ITEMS` 의 "LLM 분류" 와 "분석 운영" 사이에 새 항목:
   ```tsx
   { to: "/docs/llm-pipeline", label: "LLM Pipeline Guide", kr: "LLM 분석 안내", Icon: BookOpen },
   ```
4. `<Routes>` 블록에 라우트 추가 (논리 위치):
   ```tsx
   <Route path="/docs/llm-pipeline" element={<LlmPipelinePage />} />
   ```

### Step 3: tsc

```bash
cd ~/kr-by-claude/web && npx tsc --noEmit
```

Expected: 0 errors.

만약 mermaid 의 타입 import 시 에러 나면 `@types/mermaid` 따로 설치 필요할 수 있음 (mermaid v11+ 는 보통 자체 타입 포함 — 확인 후 결정).

### Step 4: Commit

```bash
cd ~/kr-by-claude
git add web/src/pages/LlmPipelinePage.tsx web/src/App.tsx
git commit -m "feat(web): /docs/llm-pipeline LLM 분석 안내 페이지 + 사이드바 'LLM 분석 안내'"
```

---

## Task 3: Goal State 검증

- [ ] **Step 1: Frontend tsc**

```bash
cd ~/kr-by-claude/web && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 2: Backend 회귀**

```bash
cd ~/kr-by-claude
uv run pytest 2>&1 | tail -3
```

Expected: 영향 없음 (backend 코드 변경 0).

- [ ] **Step 3: uvicorn 재시작 + 페이지 접근 가능 확인**

```bash
pkill -f "uvicorn api.main" 2>/dev/null; sleep 1
cd ~/kr-by-claude
uv run uvicorn api.main:app --port 8000 --log-level warning > /tmp/uvicorn.log 2>&1 &
sleep 3
curl -s -o /dev/null -w "uvicorn: HTTP %{http_code}\n" http://localhost:8000/api/pipelines
```

Expected: HTTP 200 (백엔드 정상).

- [ ] **Step 4: 수동 브라우저 검증 (사용자)**

`http://localhost:5173/docs/llm-pipeline` 진입 후 다음 항목 확인:

1. 사이드바에 "LLM 분석 안내" 메뉴 노출 + 클릭 시 라우팅
2. 헤더 ("Documentation" / "LLM 분석 안내" / subtitle) 표시
3. ① 개요 섹션 — Mermaid 다이어그램 #1 (graph LR, 4 단계 데이터 흐름) 정상 렌더
4. ② 단계별 카드 4 개 (daily_delta / evaluate_pivot / entry_params / performance) 모두 표시
5. 각 카드 내 — id 배지, 대상 종목, 입력/출력 chip, 결정론, LLM, 결정 chip, 결과 액션, 책 원전, 코드 참조 모두 표시
6. ③ 상태 전이도 — Mermaid 다이어그램 #2 (stateDiagram-v2) 정상 렌더
7. ④ 트리거 × 결정 매트릭스 — 3×3 표 (invalidation/go_now 와 invalidation/wait 는 "적용 안 됨")
8. ⑤ 용어집 — 7 항목 (classification / signal / trigger_type / decision / 분류 변경 / dry-run / 90일 cutoff)
9. ⑥ FAQ — 4 항목 (watch 자동 승격, pivot 없는 watch, daily_delta vs weekend, dry-run DB 영향)
10. 페이지 첫 진입 시 mermaid 로딩 (몇 백 ms) 후 SVG 렌더 — error 없음

- [ ] **Step 5: git status**

```bash
git status
```

Expected: clean working tree (untracked `.claude/` 제외).

---

## Self-Review

✅ **Spec coverage**:
- 1. 라우팅 + 사이드바 → Task 2 Step 2
- 2. 페이지 구조 7 섹션 → Task 2 Step 1 (LlmPipelinePage 의 JSX 구조)
- 3. Mermaid 다이어그램 2개 → Task 2 Step 1 (DIAGRAM_DATA_FLOW + DIAGRAM_STATE) + Task 1 (MermaidDiagram wrapper)
- 4. 콘텐츠 데이터 구조 (STAGES) → Task 2 Step 1 (PipelineStage interface + STAGES)
- 5. 트리거 × 결정 매트릭스 → Task 2 Step 1 (TRIGGER_DECISION_MATRIX + TriggerDecisionMatrix 컴포넌트)
- 6. 용어집 → Task 2 Step 1 (GLOSSARY + Glossary 컴포넌트)
- 7. FAQ → Task 2 Step 1 (FAQ + FaqSection 컴포넌트)
- 8. 컴포넌트 분리 → Task 1 (MermaidDiagram) + Task 2 (LlmPipelinePage)
- 9. mermaid 의존성 + dynamic import → Task 1
- 10. Testing → Task 3 (tsc + 수동)
- 11. Out of scope — 명시적으로 제외

✅ **Placeholder scan**: TBD/TODO 없음. 모든 콘텐츠 (STAGES 4개, GLOSSARY 7개, FAQ 4개, 매트릭스 9 cell) 가 spec 그대로 옮겨짐.

✅ **Type consistency**:
- `PipelineStage` interface — 모든 4 stage 가 같은 필드 (id, order, label, summary, targets, inputs, outputs, deterministic, llm, decisions?, actions, sources, codeRef)
- `MatrixCell` interface — meaning + next 두 필드, 모든 cell 일관
- `STAGES` 의 id 값 ↔ STAGES 자체에만 등장 — 다른 파일에서 참조 안 함
- `MermaidDiagram` 의 props (chart, idPrefix) — Task 1 정의 + Task 2 사용 일치

⚠️ **알려진 한계**:
- mermaid v11+ 의 타입 import 가 dynamic 시 한 번 더 명시 필요할 수 있음 — Task 2 Step 3 의 tsc 단계에서 발견 시 보정.
- 콘텐츠 hardcode 라 시스템 변경 (예: WATCH_EXPIRES_WEEKS 제거) 시 페이지 수동 동기화 필요 — 의도적 (페이지 목적이 정적 안내).
