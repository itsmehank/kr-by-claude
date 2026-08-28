import { Fragment, useCallback, useEffect, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api } from "../lib/api";
import { nDaysAgoKstISO, todayKstISO } from "../lib/dates";
import type {
  ReviewResponse,
  ReviewRow,
  ReviewTrigger,
  StockRowsResponse,
  TriggerDecision,
} from "../lib/types";
import Sparkline from "../components/Sparkline";
import StockStreakRow from "../components/StockStreakRow";
import StockDetailPanel from "../components/StockDetailPanel";
import { SourceChip } from "../components/SourceChip";

const pct = (v: number | null) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;

const SOURCES: { value: string; label: string }[] = [
  { value: "", label: "전체" },
  { value: "weekend", label: "weekend" },
  { value: "daily_delta", label: "daily_delta" },
  { value: "backfill", label: "backfill(백필)" },
];

const TRIGGERED_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "전체" },
  { value: "true", label: "발동" },
  { value: "false", label: "미발동" },
];

const CLASSIFICATIONS: { value: string; label: string }[] = [
  { value: "", label: "전체" },
  { value: "entry", label: "entry" },
  { value: "watch", label: "watch" },
];

const PATTERNS: { value: string; label: string }[] = [
  { value: "", label: "전체" },
  { value: "cup_with_handle", label: "cup_with_handle" },
  { value: "cup_without_handle", label: "cup_without_handle" },
  { value: "double_bottom", label: "double_bottom" },
  { value: "flat_base", label: "flat_base" },
  { value: "vcp", label: "vcp" },
  { value: "none", label: "none" },
];

// 상태(묶음 종결 여부) — 종목 행 뷰 전용 필터(스펙 §5).
const STOCK_STATUSES: { value: string; label: string }[] = [
  { value: "", label: "전체" },
  { value: "open", label: "진행중" },
  { value: "closed", label: "닫힘" },
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
  const classification = sp.get("classification") ?? "";
  const pattern = sp.get("pattern") ?? "";
  const ticker = sp.get("ticker") ?? "";
  const includePivotNull = sp.get("include_pivot_null") === "true";
  const status = sp.get("status") ?? "";
  // 기본 뷰 = 종목 행. view=analysis 만 분석 단위 표로 전환하고, 구 view=timeline 을 포함한
  // 그 외 값은 전부 기본(종목 행) 뷰로 떨어진다 — 에러 없음(스펙 §5, 결정 5).
  const isAnalysisView = sp.get("view") === "analysis";

  // 종목 입력은 매 키 입력마다 fetch 하지 않도록 local state + Enter/blur 시 URL 반영
  // (TriggersPage.tsx:58-73 패턴 그대로).
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

  const analysisQuery = useQuery<ReviewResponse>({
    queryKey: [
      "review",
      { from, to, triggered, source, classification, pattern, ticker, includePivotNull },
    ],
    queryFn: () => {
      const p = new URLSearchParams({ from, to, limit: "500" });
      if (triggered) p.set("triggered", triggered);
      if (source) p.set("source", source);
      if (classification) p.set("classification", classification);
      if (pattern) p.set("pattern", pattern);
      if (ticker) p.set("ticker", ticker);
      if (includePivotNull) p.set("include_pivot_null", "true");
      return api<ReviewResponse>(`/review/analyses?${p.toString()}`);
    },
    enabled: isAnalysisView,
  });

  const stockQuery = useQuery<StockRowsResponse>({
    queryKey: ["review-stocks", { from, to, source, ticker, status }],
    queryFn: () => {
      const p = new URLSearchParams({ from, to, limit: "500" });
      if (source) p.set("source", source);
      if (ticker) p.set("ticker", ticker);
      if (status) p.set("status", status);
      return api<StockRowsResponse>(`/review/stocks?${p.toString()}`);
    },
    enabled: !isAnalysisView,
  });

  const rows = analysisQuery.data?.rows ?? [];
  const stockRows = stockQuery.data?.rows ?? [];

  // 상세 패널 선택 — derive 방식(설계 v3 §1): 필터 변경으로 목록에서 빠지면 첫 행 폴백.
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const selectedRow =
    stockRows.find((r) => r.symbol === selectedSymbol) ?? stockRows[0] ?? null;
  const handleSelect = useCallback((symbol: string) => setSelectedSymbol(symbol), []);
  const activeQuery = isAnalysisView ? analysisQuery : stockQuery;
  const orphanCount = isAnalysisView
    ? analysisQuery.data?.orphan_trigger_count
    : stockQuery.data?.orphan_trigger_count;

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
        {isAnalysisView && (
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
        )}
        {isAnalysisView && (
          <div>
            <label className="caps block mb-1">분류</label>
            <select
              value={classification}
              onChange={(e) => updateParam("classification", e.target.value)}
              className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
            >
              {CLASSIFICATIONS.map((c) => (
                <option key={c.value} value={c.value}>{c.label}</option>
              ))}
            </select>
          </div>
        )}
        {isAnalysisView && (
          <div>
            <label className="caps block mb-1">패턴</label>
            <select
              value={pattern}
              onChange={(e) => updateParam("pattern", e.target.value)}
              className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
            >
              {PATTERNS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </div>
        )}
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
        {!isAnalysisView && (
          <div>
            <label className="caps block mb-1">상태</label>
            <select
              value={status}
              onChange={(e) => updateParam("status", e.target.value)}
              className="px-3 py-1.5 border border-hairline rounded-lg bg-cream text-data"
            >
              {STOCK_STATUSES.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>
        )}
        {isAnalysisView && (
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
        )}
        <div className="flex items-center gap-1 rounded-lg border border-hairline overflow-hidden text-data-xs mb-0.5">
          <button
            type="button"
            onClick={() => updateParam("view", "")}
            className={`px-3 py-1.5 ${!isAnalysisView ? "bg-accent text-white" : "bg-cream text-muted hover:text-ink"}`}
          >
            종목 행 보기
          </button>
          <button
            type="button"
            onClick={() => updateParam("view", "analysis")}
            className={`px-3 py-1.5 ${isAnalysisView ? "bg-accent text-white" : "bg-cream text-muted hover:text-ink"}`}
          >
            분석 단위 보기
          </button>
        </div>
      </div>

      {activeQuery.isLoading && <div className="text-muted">불러오는 중…</div>}
      {activeQuery.isError && <div className="text-danger">불러오기 실패</div>}

      {!isAnalysisView && stockQuery.data && stockRows.length === 0 && (
        <div className="text-muted">필터에 해당하는 종목이 없습니다.</div>
      )}
      {isAnalysisView && analysisQuery.data && rows.length === 0 && (
        <div className="text-muted">필터에 해당하는 분석 회고 행이 없습니다.</div>
      )}

      {!isAnalysisView && selectedRow && <StockDetailPanel row={selectedRow} to={to} />}

      {!isAnalysisView && stockRows.length > 0 && (
        <section className="mb-6 border border-hairline rounded-xl overflow-hidden">
          <table className="w-full text-data">
            <thead className="bg-paper/60 text-faint">
              <tr>
                <th className="text-left px-3 py-1.5">종목</th>
                <th
                  className="text-left px-3 py-1.5"
                  title="가장 최근 관찰 묶음이 진행중인지, 닫혔는지(닫힌 사유: ignore·실격)"
                >
                  최근 묶음 상태
                </th>
                <th
                  className="text-right px-3 py-1.5"
                  title="조회 기간과 겹치는 관찰 묶음(연속 유효 분석 구간) 개수"
                >
                  묶음 수
                </th>
                <th className="text-right px-3 py-1.5">최근 pivot</th>
                <th
                  className="text-left px-3 py-1.5"
                  title="돌파=돌파 후 T+5/T+20 수익률 · 관찰/대기=pivot 대비 최고 도달률 · 베이스 형성 중=pivot 미확정(숫자 없음)"
                >
                  성과
                </th>
                <th className="text-left px-3 py-1.5">그래프</th>
              </tr>
            </thead>
            <tbody>
              {stockRows.map((row) => (
                <StockStreakRow
                  key={row.symbol}
                  row={row}
                  to={to}
                  selected={selectedRow?.symbol === row.symbol}
                  onSelect={handleSelect}
                />
              ))}
            </tbody>
          </table>
        </section>
      )}

      {isAnalysisView && rows.length > 0 && (
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
                        <SourceChip backfilled={row.backfilled} source={row.source} />
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

      {orphanCount != null && orphanCount > 0 && (
        <div className="text-data-xs text-muted mt-2">
          귀속 불가 트리거 {orphanCount}건 (재분석으로 대체된 기록)
        </div>
      )}
    </div>
  );
}
