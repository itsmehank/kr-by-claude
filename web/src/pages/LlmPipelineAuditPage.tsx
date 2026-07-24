import { MermaidDiagram } from "../components/MermaidDiagram";
import { Link } from "react-router-dom";
import { Section } from "./llm-pipeline-audit/Section";
import { TableOfContents } from "./llm-pipeline-audit/TableOfContents";
import { StageCardDeep } from "./llm-pipeline-audit/StageCardDeep";
import { ConditionTable } from "./llm-pipeline-audit/ConditionTable";
import { PatternCards } from "./llm-pipeline-audit/PatternCards";
import { RiskFlagTable } from "./llm-pipeline-audit/RiskFlagTable";
import { CollapsiblePrompt } from "./llm-pipeline-audit/CollapsiblePrompt";
import { BookCitation } from "./llm-pipeline-audit/BookCitation";

import { CRON_SCHEDULE, CRON_CODE_REF } from "../data/llm-pipeline-audit/cron";
import { ZIP_FILES, README_BODY } from "../data/llm-pipeline-audit/zip-files";
import { STAGE_DETAILS } from "../data/llm-pipeline-audit/stages";
import {
  CHANGE_LOG,
  REVIEW_ITEMS,
  FUTURE_MONITORING,
} from "../data/llm-pipeline-audit/change-log";

import { ANALYZE_CHART_V3 } from "../data/prompts/analyze-chart-v3";
import { EVALUATE_PIVOT_TRIGGER_V1 } from "../data/prompts/evaluate-pivot-trigger-v1";
import { CALCULATE_ENTRY_PARAMS_V2_0 } from "../data/prompts/calculate-entry-params-v2-0";

const SYSTEM_FLOW_DIAGRAM = `graph LR
  WEEKEND["weekend batch<br/>(토 03:20)<br/>minervini_pass 전체 재분류"] -->|source='weekend'| WC[("weekly_classification<br/>watch / entry / ignore<br/>append-only")]
  DD["daily_delta<br/>(평일 20:00, 신규만)<br/>minervini_pass + 최근 7일 미분류"] -->|source='daily_delta'| WC
  WC -->|매일 active 종목<br/>DISTINCT ON| EV{"evaluate_pivot<br/>결정론 게이트"}
  EV -->|"breakout / promotion /<br/>invalidation"| LLM["LLM 평가<br/>(go_now/wait/abort)"]
  LLM --> TEL[("trigger_evaluation_log<br/>append-only")]
  TEL -->|"decision='go_now'<br/>AND trigger_type='breakout'<br/>(promotion staging 안전장치)"| EP["entry_params<br/>LLM 호출"]
  EP --> EPR[("entry_params<br/>17 필드 매수 계획")]
  EPR -->|매일 자동| PF["performance<br/>가격 backfill"]
  PF --> SP[("signal_performance<br/>1w/2w/4w/8w 수익률 + α")]
`;

export default function LlmPipelineAuditPage() {
  return (
    <div className="px-8 py-8 max-w-[1400px] mx-auto">
      <header className="mb-8">
        <div className="caps text-faint mb-2">Audit Documentation</div>
        <h1 className="font-display text-display-xl font-bold tracking-tight">
          LLM 분석 검증
        </h1>
        <p className="text-data text-muted mt-3 leading-relaxed">
          Minervini / O'Neil 책 전문가가 한 페이지만 보고 시스템 전체
          (스케줄링 / 5 stage / Minervini 8조건 / 10 base 패턴 / 13 risk_flag /
          ZIP 13 / 3 prompt / 변경 이력) 를 line-by-line 검증할 수 있는 페이지.
        </p>
      </header>

      <details className="mb-8 group">
        <summary className="cursor-pointer select-none px-5 py-3 bg-cream border border-hairline rounded-xl text-data text-ink font-semibold hover:bg-tint-stone transition-colors list-none flex items-center justify-between">
          <span>이 페이지는 무엇인가요? 🔍</span>
          <span className="text-faint font-normal text-data-xs ml-3 group-open:hidden">클릭해서 안내 펼치기 ▼</span>
          <span className="text-faint font-normal text-data-xs ml-3 hidden group-open:inline">접기 ▲</span>
        </summary>
        <div className="mt-3 px-5 py-5 bg-cream border border-hairline rounded-xl text-data text-muted leading-relaxed space-y-5">
          <p>
            <em>"이 시스템이 정말 책에 충실한가?"</em> 를 <span className="text-ink font-semibold">한 줄씩 대조해 검증</span> 할 수 있는 페이지입니다.
            Minervini <em>Trade Like a Stock Market Wizard</em> · <em>Think and Trade Like a Champion</em>,
            O'Neil <em>How to Make Money in Stocks</em> · <em>Trade Like an O'Neil Disciple</em> 네 권의 인용과,
            본 시스템의 실제 룰·정의·임계값을 <span className="text-ink font-semibold">나란히</span> 보여줍니다.
          </p>

          <div>
            <div className="text-ink font-semibold mb-2">무엇을 볼 수 있나요?</div>
            <ul className="space-y-1.5 list-disc list-inside pl-1">
              <li><span className="text-ink">Minervini Trend Template 8 조건</span> — 추세 강도를 판정하는 8 기준 (이동평균 배열, 신고가 근접 등).</li>
              <li><span className="text-ink">10 base 패턴 정의</span> — flat_base · cup_with_handle · cup_without_handle · VCP · double_bottom 등 책이 정의한 모든 base 모양.</li>
              <li><span className="text-ink">13 risk flag</span> — 매수 적합도를 깎는 위험 신호 (climax_run · late_stage_base · faulty_pivot 등).</li>
              <li><span className="text-ink">3 prompt 본문 전체</span> — AI 가 실제로 받는 지시문 (analyze_chart_v3 / evaluate_pivot_trigger / calculate_entry_params).</li>
              <li><span className="text-ink">변경 이력</span> — 룰이 언제·왜·어떻게 바뀌었는지 letter 별 (A, B, ..., K) 추적.</li>
            </ul>
          </div>

          <div>
            <div className="text-ink font-semibold mb-2">누가 보면 좋은가요?</div>
            <ul className="space-y-1.5 list-disc list-inside pl-1">
              <li>책 전문가가 <em>"이 룰의 책 출처가 정확한가"</em> 를 확인할 때</li>
              <li><em>"왜 이 임계값을 1.4× → 1.5× 로 바꿨나"</em> 같은 의사결정 맥락을 추적하고 싶을 때</li>
              <li>새 룰을 추가하기 전에 <em>책이 무엇을 권장하나</em> 를 한 화면에서 비교하고 싶을 때</li>
            </ul>
          </div>

          <div>
            <div className="text-ink font-semibold mb-2">핵심 용어 빠른 이해</div>
            <ul className="space-y-1.5 list-disc list-inside pl-1">
              <li><span className="text-ink">prompt</span> — AI 에게 주는 지시문 (예: <em>"이 차트를 분석해 entry/watch/ignore 중 하나로 분류해줘"</em>). 본 시스템은 3 prompt 사용.</li>
              <li><span className="text-ink">risk flag</span> — 매수에 부적합한 위험 신호. 13 종 고정 목록만 사용.</li>
              <li><span className="text-ink">base 패턴</span> — 주가가 옆으로 정리되는 모양. 10 종 분류.</li>
              <li><span className="text-ink">book quote / English quote</span> — 룰의 책 원문 인용. "Why" 를 책 페이지·문장 단위로 추적 가능.</li>
            </ul>
          </div>

          <div className="pt-3 border-t border-hairline">
            <span className="text-faint">자매 페이지 — </span>
            <em>시스템이 어떻게 동작하는지</em> 가상 종목 시뮬레이션으로 흐름을 따라가보고 싶다면 →{" "}
            <Link to="/docs/llm-pipeline" className="text-accent font-semibold hover:underline">
              LLM 분석 안내
            </Link>
          </div>
        </div>
      </details>

      <div className="flex gap-8">
        <aside className="hidden lg:block w-64 shrink-0">
          <TableOfContents />
        </aside>

        <main className="flex-1 min-w-0">
          {/* §1 시스템 개요 */}
          <Section id="overview" title="1. 시스템 개요">
            <p className="text-data text-muted mb-4">
              주말 1 단계 (전체 재분류) + 평일 4 단계 (신규 분류 → 트리거 평가 →
              매수 계획 → 성과 추적).
            </p>
            <MermaidDiagram chart={SYSTEM_FLOW_DIAGRAM} idPrefix="audit-flow" />
            <div className="mt-4 p-4 bg-cream border border-hairline rounded-xl text-data text-muted">
              <div className="caps text-faint mb-2">핵심 설계 철학</div>
              결정론 게이트는 싸고 느슨한 사전 필터 — 명백한 비후보만 제거.
              정밀 임계 (1.4~1.5× 표준, pocket pivot 예외, 일중 강도 등) 와
              예외 판단은 LLM 이 차트와 함께 수행. 게이트를 책 표준에 맞추면
              (1) LLM 이 무력화되고 (2) 책이 인정한 예외 (pocket pivot, 시장 맥락) 가
              사전 배제되는 false negative 발생.
            </div>
          </Section>

          {/* §2 실행 스케줄 */}
          <Section id="schedule" title="2. 실행 스케줄">
            <p className="text-data-xs text-muted mb-3">
              <code className="num">{CRON_CODE_REF}</code>
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-data border-collapse">
                <thead>
                  <tr className="border-b border-hairline text-faint">
                    <th className="text-left py-2 pr-3">Pipeline</th>
                    <th className="text-left py-2 pr-3">Cron</th>
                    <th className="text-left py-2 pr-3">KST 시각</th>
                    <th className="text-left py-2 pr-3">실행 단계</th>
                    <th className="text-left py-2">LLM 호출</th>
                  </tr>
                </thead>
                <tbody>
                  {CRON_SCHEDULE.map((c) => (
                    <tr key={c.pipeline} className="border-b border-hairline align-top">
                      <td className="py-2 pr-3"><code className="num">{c.pipeline}</code></td>
                      <td className="py-2 pr-3"><code className="num text-data-xs">{c.cron}</code></td>
                      <td className="py-2 pr-3 text-data-xs">{c.kstTime}</td>
                      <td className="py-2 pr-3 text-data-xs">{c.stages}</td>
                      <td className="py-2 text-data-xs">{c.llmCalls}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          {/* §3 단계별 상세 */}
          <Section id="stages" title="3. 단계별 상세">
            {STAGE_DETAILS.map((stage) => (
              <StageCardDeep key={stage.id} stage={stage} />
            ))}
          </Section>

          {/* §4 Minervini 8조건 */}
          <Section id="minervini-8" title="4. Minervini Trend Template 8조건">
            <ConditionTable />
            <div className="mt-4">
              <BookCitation
                book="Minervini, *Trade Like a Stock Market Wizard*"
                chapter="Ch.5 'Trend Template'"
                englishQuote="A stock must meet all eight criteria of the Trend Template..."
                koreanSummary="8조건 모두 충족 종목만 LLM 분석 대상."
              />
            </div>
          </Section>

          {/* §5 Base 패턴 */}
          <Section id="base-patterns" title="5. Base 패턴 9개 (analyze_chart_v3.md §4)">
            <PatternCards />
          </Section>

          {/* §6 Risk Flags */}
          <Section id="risk-flags" title="6. Risk Flags 13개 (analyze_chart_v3.md §6)">
            <RiskFlagTable />
          </Section>

          {/* §7 ZIP Payload */}
          <Section id="zip-payload" title="7. LLM Payload — ZIP 13 파일">
            <h4 className="caps text-faint mb-2">7.1 파일 목록</h4>
            <div className="overflow-x-auto mb-4">
              <table className="w-full text-data border-collapse">
                <thead>
                  <tr className="border-b border-hairline text-faint">
                    <th className="text-left py-2 pr-3">#</th>
                    <th className="text-left py-2 pr-3">파일명</th>
                    <th className="text-left py-2 pr-3">내용</th>
                    <th className="text-left py-2">코드 ref</th>
                  </tr>
                </thead>
                <tbody>
                  {ZIP_FILES.map((f) => (
                    <tr key={f.num} className="border-b border-hairline align-top">
                      <td className="py-2 pr-3 num text-faint">{f.num}</td>
                      <td className="py-2 pr-3"><code className="num text-data-xs">{f.filename}</code></td>
                      <td className="py-2 pr-3 text-data-xs text-muted">{f.content}</td>
                      <td className="py-2 text-data-xs">
                        <code className="num bg-tint-stone px-1 rounded">{f.codeRef}</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <h4 className="caps text-faint mb-2">7.2 종목 시장별 인덱스 선택</h4>
            <p className="text-data-xs text-muted mb-4">
              <code className="num">zip_builder.py:75</code> —{" "}
              <code className="num">index_code = INDEX_CODE_MAP.get(market, "1001")</code>:
              종목 market 에 따라 KOSPI(1001) 또는 KOSDAQ(2001) 의 인덱스 사용.
              파일명 <code className="num">market_index_*</code> 로 시장 중립적 표기.
            </p>

            <h4 className="caps text-faint mb-2">7.3 README 본문</h4>
            <pre className="bg-cream border border-hairline rounded-xl p-3 text-data-xs overflow-auto max-h-[400px]">
              <code className="num">{README_BODY}</code>
            </pre>
          </Section>

          {/* §8 Prompt 전체 */}
          <Section id="prompts" title="8. Prompt 전체 (3개)">
            <CollapsiblePrompt
              summary="1. analyze_chart_v3.md (weekend + daily_delta 공통, 309 행)"
              content={ANALYZE_CHART_V3}
            />
            <CollapsiblePrompt
              summary="2. evaluate_pivot_trigger_v1.md (evaluate_pivot, 127 행)"
              content={EVALUATE_PIVOT_TRIGGER_V1}
            />
            <CollapsiblePrompt
              summary="3. calculate_entry_params_v2_0.md (entry_params, 580 행)"
              content={CALCULATE_ENTRY_PARAMS_V2_0}
            />
          </Section>

          {/* §9 변경 이력 */}
          <Section id="change-log" title="9. 비일관성 / 변경 이력">
            <h4 className="caps text-faint mb-2">9.1 최근 변경</h4>
            <div className="space-y-4 mb-6">
              {CHANGE_LOG.map((entry) => (
                <div key={entry.letter} className="bg-cream border border-hairline rounded-xl p-4">
                  <div className="flex items-baseline gap-3 mb-2">
                    <span className="text-data-xs font-semibold text-accent">{entry.letter}.</span>
                    <span className="text-data font-semibold text-ink">{entry.title}</span>
                    <span className="text-data-xs text-faint ml-auto">
                      {entry.date} · <code className="num">{entry.commit}</code>
                    </span>
                  </div>
                  <p className="text-data-xs text-muted mb-2">{entry.rationale}</p>
                  <ul className="text-data-xs text-muted space-y-1 list-disc list-inside">
                    {entry.changes.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            <h4 className="caps text-faint mb-2">9.2 검토 사항 (모두 해결)</h4>
            <ul className="space-y-2 mb-6">
              {REVIEW_ITEMS.map((item, i) => (
                <li key={i} className="flex gap-3 text-data-xs">
                  <span
                    className={
                      item.status === "resolved"
                        ? "text-green-700 font-semibold shrink-0"
                        : "text-yellow-700 font-semibold shrink-0"
                    }
                  >
                    {item.status === "resolved" ? "✓" : "○"}
                  </span>
                  <div>
                    <span className="font-semibold text-ink">{item.title}</span>
                    <div className="text-muted mt-0.5">{item.detail}</div>
                  </div>
                </li>
              ))}
            </ul>

            <h4 className="caps text-faint mb-2">9.3 향후 모니터링</h4>
            <ul className="space-y-1 text-data-xs text-muted list-disc list-inside">
              {FUTURE_MONITORING.map((m, i) => (
                <li key={i}>{m}</li>
              ))}
            </ul>
          </Section>
        </main>
      </div>
    </div>
  );
}
