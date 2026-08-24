import { Fragment, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api } from "../lib/api";
import { nDaysAgoKstISO, todayKstISO } from "../lib/dates";
import type { ReviewResponse, ReviewRow, ReviewTrigger, TriggerDecision } from "../lib/types";
import Sparkline from "../components/Sparkline";

const pct = (v: number | null) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;

const SOURCES: { value: string; label: string }[] = [
  { value: "", label: "전체" },
  { value: "weekend", label: "weekend" },
  { value: "daily_delta", label: "daily_delta" },
];

const TRIGGERED_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "전체" },
  { value: "true", label: "발동" },
  { value: "false", label: "미발동" },
];

// 상태 셀 tone — TriggersPage 의 DecisionPill 톤 관례를 상태 축(§1)에 맞춰 복제.
const STATUS_TONES: Record<string, { bg: string; text: string; dot: string }> = {
  "돌파-완료": { bg: "bg-success-soft", text: "text-success", dot: "bg-success" },
  "돌파-진행중": { bg: "bg-tint-blue", text: "text-accent", dot: "bg-accent" },
  staging: { bg: "bg-amber-soft", text: "text-amber", dot: "bg-amber-500" },
  미발동: { bg: "bg-tint-stone", text: "text-muted", dot: "bg-gray-400" },
};

function statusLabel(row: ReviewRow): string {
  if (row.status === "staging" && row.max_reach_pct != null && row.max_reach_pct >= 0) {
    return "staging (pivot 상회)";
  }
  return row.status;
}

function StatusPill({ row }: { row: ReviewRow }) {
  const cfg = STATUS_TONES[row.status] ?? { bg: "bg-tint-stone", text: "text-muted", dot: "bg-gray-400" };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded ${cfg.bg} ${cfg.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
      {statusLabel(row)}
    </span>
  );
}

// TriggersPage 의 DecisionPill 을 로컬 복제 (export 되지 않은 비공개 컴포넌트).
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

function TriggerTimeline({ triggers }: { triggers: ReviewTrigger[] }) {
  const [openReasoning, setOpenReasoning] = useState<Set<string>>(new Set());
  const toggle = (key: string) =>
    setOpenReasoning((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  if (triggers.length === 0) {
    return <div className="text-muted text-data-xs py-2">귀속된 트리거 없음.</div>;
  }

  return (
    <table className="w-full text-data-xs">
      <thead className="text-faint">
        <tr>
          <th className="text-left px-3 py-1">날짜(D)</th>
          <th className="text-left px-3 py-1">유형</th>
          <th className="text-left px-3 py-1">decision</th>
          <th className="text-right px-3 py-1">close</th>
          <th className="text-right px-3 py-1">pivot</th>
          <th className="text-left px-3 py-1">reasoning</th>
        </tr>
      </thead>
      <tbody>
        {triggers.map((t) => {
          const key = `${t.evaluated_at}-${t.trigger_type}`;
          const isOpen = openReasoning.has(key);
          return (
            <tr key={key} className="border-t border-hairline align-top">
              <td className="px-3 py-1 num">{t.d}</td>
              <td className="px-3 py-1">{t.trigger_type}</td>
              <td className="px-3 py-1">
                <DecisionPill decision={t.decision} />
              </td>
              <td className="px-3 py-1 text-right num">
                {t.close != null ? t.close.toLocaleString() : "—"}
              </td>
              <td className="px-3 py-1 pr-4 text-right num">
                {t.pivot_price != null ? t.pivot_price.toLocaleString() : "—"}
              </td>
              <td className="px-3 py-1 text-muted">
                {t.reasoning ? (
                  <button
                    type="button"
                    onClick={() => toggle(key)}
                    className="flex items-start gap-1 text-left w-full hover:text-ink"
                  >
                    <span className="shrink-0 mt-0.5">
                      {isOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                    </span>
                    <span className={isOpen ? "whitespace-pre-wrap" : "truncate max-w-md"}>
                      {t.reasoning}
                    </span>
                  </button>
                ) : (
                  ""
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default function ReviewPage() {
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  function toggleExpanded(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const from = sp.get("from") ?? nDaysAgoKstISO(28);
  const to = sp.get("to") ?? todayKstISO();
  const triggered = sp.get("triggered") ?? "";
  const source = sp.get("source") ?? "";
  const includePivotNull = sp.get("include_pivot_null") === "true";

  function updateParam(key: string, value: string) {
    const next = new URLSearchParams(sp);
    if (value) next.set(key, value);
    else next.delete(key);
    setSp(next);
  }

  const q = useQuery<ReviewResponse>({
    queryKey: ["review", { from, to, triggered, source, includePivotNull }],
    queryFn: () => {
      const p = new URLSearchParams({ from, to, limit: "500" });
      if (triggered) p.set("triggered", triggered);
      if (source) p.set("source", source);
      if (includePivotNull) p.set("include_pivot_null", "true");
      return api<ReviewResponse>(`/review/analyses?${p.toString()}`);
    },
  });

  const rows = q.data?.rows ?? [];

  return (
    <div className="px-8 py-6">
      <h1 className="font-display text-display-md font-bold mb-6">분석 회고</h1>

      <div className="flex flex-wrap gap-3 mb-6 items-end">
        <div>
          <label className="caps block mb-1">from</label>
          <input
            type="date"
            value={from}
            onChange={(e) => updateParam("from", e.target.value)}
            className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
          />
        </div>
        <div>
          <label className="caps block mb-1">to</label>
          <input
            type="date"
            value={to}
            onChange={(e) => updateParam("to", e.target.value)}
            className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
          />
        </div>
        <div>
          <label className="caps block mb-1">유형</label>
          <select
            value={source}
            onChange={(e) => updateParam("source", e.target.value)}
            className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
          >
            {SOURCES.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="caps block mb-1">발동 여부</label>
          <select
            value={triggered}
            onChange={(e) => updateParam("triggered", e.target.value)}
            className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
          >
            {TRIGGERED_OPTIONS.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="flex items-center gap-1.5 cursor-pointer text-data-xs mb-2">
            <input
              type="checkbox"
              checked={includePivotNull}
              onChange={(e) => updateParam("include_pivot_null", e.target.checked ? "true" : "")}
              className="accent-accent"
            />
            pivot 없는 분석 포함
          </label>
        </div>
      </div>

      {q.isLoading && <div className="text-muted">불러오는 중…</div>}
      {q.isError && <div className="text-danger">불러오기 실패</div>}
      {q.data && rows.length === 0 && (
        <div className="text-muted">필터에 해당하는 분석 회고 행이 없습니다.</div>
      )}

      {rows.length > 0 && (
        <section className="mb-6 border border-hairline rounded-xl overflow-hidden">
          <table className="w-full text-data">
            <thead className="bg-paper/60 text-faint">
              <tr>
                <th className="text-left px-3 py-1.5">종목</th>
                <th className="text-left px-3 py-1.5">분석일</th>
                <th className="text-left px-3 py-1.5">분류·패턴</th>
                <th className="text-right px-3 py-1.5">pivot</th>
                <th className="text-left px-3 py-1.5">상태</th>
                <th className="text-right px-3 py-1.5">T+5</th>
                <th className="text-right px-3 py-1.5">T+20 / 최고도달</th>
                <th className="text-left px-3 py-1.5">스파크라인</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const key = `${row.symbol}-${row.classified_at}`;
                const isOpen = expanded.has(key);
                const isTriggered = row.first_breakout_at != null;
                const showCorpActionBadge =
                  row.corp_action_flag && (row.status === "미발동" || row.status === "staging");
                return (
                  <Fragment key={key}>
                    <tr
                      onClick={() => toggleExpanded(key)}
                      className="border-t border-hairline align-top hover:bg-paper/40 cursor-pointer"
                    >
                      <td className="px-3 py-1.5">
                        <div className="flex items-center gap-1.5">
                          <span className="text-faint shrink-0">
                            {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                          </span>
                          <span
                            className="font-semibold hover:underline"
                            onClick={(e) => {
                              e.stopPropagation();
                              navigate(`/chart/${row.symbol}`);
                            }}
                          >
                            {row.symbol}
                          </span>
                          <span className="text-muted">{row.name}</span>
                        </div>
                      </td>
                      <td className="px-3 py-1.5">
                        <div className="num">{row.key_date}</div>
                        <span className="chip bg-tint-stone text-muted text-data-xs">{row.source}</span>
                      </td>
                      <td className="px-3 py-1.5">
                        <div>{row.classification}</div>
                        {row.pattern && <div className="text-muted text-data-xs">{row.pattern}</div>}
                      </td>
                      <td className="px-3 py-1.5 text-right num">
                        {row.pivot_price != null ? row.pivot_price.toLocaleString() : "—"}
                      </td>
                      <td className="px-3 py-1.5">
                        <StatusPill row={row} />
                        {isTriggered && (
                          <div className="mt-1 flex items-center gap-1.5 text-data-xs text-muted">
                            <span className="num">{row.first_breakout_at}</span>
                            {row.first_breakout_decision && (
                              <DecisionPill decision={row.first_breakout_decision} />
                            )}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-1.5 text-right num">{pct(row.t5_pct)}</td>
                      <td className="px-3 py-1.5 text-right num">
                        {isTriggered ? pct(row.t20_pct) : pct(row.max_reach_pct)}
                        {showCorpActionBadge && (
                          <span
                            className="ml-1.5 chip bg-amber-soft text-amber text-data-xs"
                            title="구간 내 기업행위 발생 — 가격 왜곡 가능"
                          >
                            ⚠ 기업행위
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-1.5">
                        <Sparkline values={row.spark} baseline={row.pivot_baseline} />
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="border-t border-hairline bg-cream/50">
                        <td colSpan={8} className="px-6 py-2">
                          <TriggerTimeline triggers={row.triggers} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      {q.data && q.data.orphan_trigger_count > 0 && (
        <div className="text-data-xs text-muted mt-2">
          귀속 불가 트리거 {q.data.orphan_trigger_count}건 (재분석으로 대체된 기록)
        </div>
      )}
    </div>
  );
}
