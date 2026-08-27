import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { TriggerDecision } from "../lib/types";
import {
  buildStockTimeline,
  type TimelineAnalysisEvent,
  type TimelineRow,
  type TimelineTriggerEvent,
} from "../lib/stockTimeline";

// ReviewPage.tsx 의 DecisionPill 을 로컬 복제 — 이 코드베이스의 확립된 관례
// (TriggersPage.tsx:261, ReviewPage.tsx 모두 페이지/컴포넌트별 로컬 복제, export 공유 아님).
function DecisionPill({ decision }: { decision: TriggerDecision }) {
  const cfg = ({
    go_now: { bg: "bg-green-100", text: "text-green-800", dot: "bg-green-500" },
    wait: { bg: "bg-yellow-100", text: "text-yellow-800", dot: "bg-yellow-500" },
    abort: { bg: "bg-gray-200", text: "text-gray-700", dot: "bg-gray-500" },
  } as Record<string, { bg: string; text: string; dot: string }>)[decision] ?? {
    bg: "bg-tint-stone",
    text: "text-muted",
    dot: "bg-gray-400",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded ${cfg.bg} ${cfg.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
      {decision}
    </span>
  );
}

function AnalysisCard({ event }: { event: TimelineAnalysisEvent }) {
  const row = event.row;
  const transitioned = event.classificationChanged || event.pivotChanged;
  const pivotDisplay =
    event.pivotChanged
      ? `${event.previousPivotPrice != null ? event.previousPivotPrice.toLocaleString() : "—"} → ${
          row.pivot_price != null ? row.pivot_price.toLocaleString() : "—"
        }`
      : row.pivot_price != null
        ? row.pivot_price.toLocaleString()
        : "—";

  return (
    <div
      className={`rounded-lg border px-3 py-2 ${
        transitioned ? "border-accent bg-accent-soft" : "border-hairline bg-paper"
      }`}
    >
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="num text-data-xs text-muted">{row.key_date}</span>
          <span className="chip bg-tint-stone text-muted text-data-xs">{row.source}</span>
          {row.backfilled && (
            <span
              className="chip bg-tint-stone text-muted text-data-xs"
              title="백필 — 현재 프롬프트로 재생성된 합성 이력(당시 실전 실행 아님)"
            >
              백필
            </span>
          )}
          <span className="font-semibold">{row.classification}</span>
          {row.pattern && <span className="text-muted text-data-xs">{row.pattern}</span>}
        </div>
        <div className="num text-data-xs">{pivotDisplay}</div>
      </div>
      {transitioned && (
        <div className="mt-1 text-data-xs text-accent">
          ⇅ 상태 전환
          {event.classificationChanged ? " · 분류 변경" : ""}
          {event.pivotChanged ? " · pivot 변경" : ""}
        </div>
      )}
    </div>
  );
}

function TriggerCard({
  event,
  isOpen,
  onToggle,
}: {
  event: TimelineTriggerEvent;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const t = event.trigger;
  return (
    <div className="rounded-lg border border-hairline bg-cream/60 px-3 py-2">
      <div className="flex items-center justify-between gap-2 flex-wrap text-data-xs">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="num text-muted">{t.d}</span>
          <span>{t.trigger_type}</span>
          <DecisionPill decision={t.decision} />
        </div>
        <div className="flex items-center gap-3 num">
          <span>close {t.close != null ? t.close.toLocaleString() : "—"}</span>
          <span>pivot {t.pivot_price != null ? t.pivot_price.toLocaleString() : "—"}</span>
        </div>
      </div>
      {t.reasoning && (
        <button
          type="button"
          onClick={onToggle}
          className="mt-1 flex items-start gap-1 text-left w-full hover:text-ink text-data-xs text-muted"
        >
          <span className="shrink-0 mt-0.5">
            {isOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
          </span>
          {/* min-w-0: 좁은 컬럼(상세 패널 우측)에서도 truncate 가 가로 오버플로우 없이 동작 */}
          <span className={isOpen ? "whitespace-pre-wrap" : "min-w-0 flex-1 truncate"}>{t.reasoning}</span>
        </button>
      )}
    </div>
  );
}

export default function StockTimeline({ rows }: { rows: TimelineRow[] }) {
  const [openReasoning, setOpenReasoning] = useState<Set<string>>(new Set());
  const toggle = (key: string) =>
    setOpenReasoning((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const events = buildStockTimeline(rows);

  if (events.length === 0) {
    return <div className="text-muted text-data-xs py-2">타임라인에 표시할 이벤트가 없습니다.</div>;
  }

  return (
    <div className="flex flex-col gap-2">
      {events.map((event, idx) => {
        if (event.kind === "analysis") {
          const key = `analysis-${event.row.symbol}-${event.row.classified_at}-${idx}`;
          return <AnalysisCard key={key} event={event} />;
        }
        const key = `trigger-${event.symbol}-${event.trigger.evaluated_at}-${event.trigger.trigger_type}-${idx}`;
        return (
          <TriggerCard key={key} event={event} isOpen={openReasoning.has(key)} onToggle={() => toggle(key)} />
        );
      })}
    </div>
  );
}
