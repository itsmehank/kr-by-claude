import { useEffect, useMemo, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Trigger, TriggerDecision } from "../lib/types";
import {
  InfoTooltip,
  TRIGGER_TYPE_HELP,
  DECISION_HELP,
  VOLUME_RATIO_HELP,
  PIVOT_DELTA_HELP,
} from "../components/InfoTooltip";

const DECISIONS: { value: TriggerDecision | ""; label: string }[] = [
  { value: "", label: "전체" },
  { value: "go_now", label: "go_now" },
  { value: "wait", label: "wait" },
  { value: "abort", label: "abort" },
];

const TRIGGER_TYPES: { value: string; label: string }[] = [
  { value: "", label: "전체" },
  { value: "breakout", label: "breakout" },
  { value: "promotion", label: "promotion" },
  { value: "invalidation", label: "invalidation" },
];

function defaultFrom(): string {
  const d = new Date();
  d.setDate(d.getDate() - 7);
  return d.toISOString().slice(0, 10);
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function TriggersPage() {
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();

  const ticker = sp.get("ticker") ?? "";
  const decision = sp.get("decision") ?? "";
  const triggerType = sp.get("trigger_type") ?? "";
  const from = sp.get("from") ?? defaultFrom();
  const to = sp.get("to") ?? todayStr();

  // 종목 입력은 매 키 입력마다 fetch 하지 않도록 local state + Enter/blur 시 URL 반영
  const [tickerInput, setTickerInput] = useState(ticker);
  useEffect(() => {
    setTickerInput(ticker);
  }, [ticker]);

  function updateParam(key: string, value: string) {
    const next = new URLSearchParams(sp);
    if (value) next.set(key, value);
    else next.delete(key);
    setSp(next);
  }

  function commitTicker() {
    if (tickerInput !== ticker) updateParam("ticker", tickerInput.trim());
  }

  const q = useQuery<Trigger[]>({
    queryKey: ["triggers", { ticker, decision, triggerType, from, to }],
    queryFn: () => {
      const params = new URLSearchParams();
      if (ticker) params.set("ticker", ticker);
      if (decision) params.set("decision", decision);
      if (triggerType) params.set("trigger_type", triggerType);
      if (from) params.set("from", from);
      if (to) params.set("to", to);
      params.set("limit", "500");
      return api<Trigger[]>(`/triggers?${params.toString()}`);
    },
  });

  const groupedByDate = useMemo(() => {
    const map = new Map<string, Trigger[]>();
    for (const t of q.data ?? []) {
      const d = t.evaluated_at.slice(0, 10);
      const arr = map.get(d) ?? [];
      arr.push(t);
      map.set(d, arr);
    }
    return Array.from(map.entries()).sort(([a], [b]) => b.localeCompare(a));
  }, [q.data]);

  return (
    <div className="px-8 py-6">
      <h1 className="font-display text-display-md font-bold mb-6">트리거 이력</h1>

      <div className="flex flex-wrap gap-3 mb-6 items-end">
        <div>
          <label className="caps block mb-1">종목</label>
          <input
            type="text"
            value={tickerInput}
            placeholder="예: 005930"
            onChange={(e) => setTickerInput(e.target.value)}
            onBlur={commitTicker}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitTicker();
            }}
            className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
          />
        </div>
        <div>
          <label className="caps block mb-1">decision</label>
          <select
            value={decision}
            onChange={(e) => updateParam("decision", e.target.value)}
            className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
          >
            {DECISIONS.map((d) => (
              <option key={d.value} value={d.value}>{d.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="caps block mb-1">trigger_type</label>
          <select
            value={triggerType}
            onChange={(e) => updateParam("trigger_type", e.target.value)}
            className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
          >
            {TRIGGER_TYPES.map((d) => (
              <option key={d.value} value={d.value}>{d.label}</option>
            ))}
          </select>
        </div>
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
      </div>

      {q.isLoading && <div className="text-muted">불러오는 중…</div>}
      {q.isError && <div className="text-red-600">불러오기 실패</div>}
      {q.data && q.data.length === 0 && (
        <div className="text-muted">필터에 해당하는 트리거 평가 이력이 없습니다.</div>
      )}

      {groupedByDate.map(([date, rows]) => {
        const go = rows.filter((r) => r.decision === "go_now").length;
        const wait = rows.filter((r) => r.decision === "wait").length;
        const abort = rows.filter((r) => r.decision === "abort").length;
        return (
          <section key={date} className="mb-6 border border-hairline rounded-xl overflow-hidden">
            <header className="px-4 py-2 bg-paper flex justify-between text-data">
              <span className="font-semibold">{date}</span>
              <span className="text-muted">
                {rows.length} 건 · go {go} / wait {wait} / abort {abort}
              </span>
            </header>
            <table className="w-full text-data">
              <thead className="bg-paper/60 text-faint">
                <tr>
                  <th className="text-left px-3 py-1.5">종목</th>
                  <th className="text-left px-3 py-1.5">
                    트리거
                    <InfoTooltip>{TRIGGER_TYPE_HELP}</InfoTooltip>
                  </th>
                  <th className="text-left px-3 py-1.5">
                    decision
                    <InfoTooltip>{DECISION_HELP}</InfoTooltip>
                  </th>
                  <th className="text-right px-3 py-1.5">
                    거래량비
                    <InfoTooltip>{VOLUME_RATIO_HELP}</InfoTooltip>
                  </th>
                  <th className="text-right px-3 py-1.5">
                    pivot대비
                    <InfoTooltip>{PIVOT_DELTA_HELP}</InfoTooltip>
                  </th>
                  <th className="text-left px-3 py-1.5">reasoning</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr
                    key={`${t.symbol}-${t.evaluated_at}`}
                    onClick={() => navigate(`/chart/${t.symbol}`)}
                    className="border-t border-hairline cursor-pointer hover:bg-paper/40"
                  >
                    <td className="px-3 py-1.5 font-semibold">
                      {t.symbol} <span className="text-muted">{t.name}</span>
                    </td>
                    <td className="px-3 py-1.5">{t.trigger_type}</td>
                    <td className="px-3 py-1.5">
                      <DecisionPill decision={t.decision} />
                    </td>
                    <td className="px-3 py-1.5 text-right num">
                      {t.avg_volume_50d_ratio != null ? `${t.avg_volume_50d_ratio.toFixed(2)}×` : "—"}
                    </td>
                    <td className="px-3 py-1.5 text-right num">
                      {t.pivot_delta_pct != null
                        ? `${t.pivot_delta_pct >= 0 ? "+" : ""}${t.pivot_delta_pct.toFixed(2)}%`
                        : "—"}
                    </td>
                    <td className="px-3 py-1.5 text-muted truncate max-w-md" title={t.reasoning ?? ""}>
                      {t.reasoning ?? ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        );
      })}
    </div>
  );
}

function DecisionPill({ decision }: { decision: TriggerDecision }) {
  const cfg = {
    go_now: { bg: "bg-green-100", text: "text-green-800", dot: "bg-green-500" },
    wait:   { bg: "bg-yellow-100", text: "text-yellow-800", dot: "bg-yellow-500" },
    abort:  { bg: "bg-gray-200", text: "text-gray-700", dot: "bg-gray-500" },
  }[decision];
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded ${cfg.bg} ${cfg.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
      {decision}
    </span>
  );
}
