import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  ChevronDown,
  LineChart,
  RefreshCw,
  AlertTriangle,
} from "lucide-react";
import { api } from "../lib/api";
import type { Classification } from "../lib/types";
import { relativeTime, formatKst } from "../lib/utils";
import { Tooltip } from "../components/ui/Tooltip";


type SortOption = "classified_at_desc" | "confidence_desc";


interface Filters {
  lookback_days: number;
  classifications: string[];
  sources: string[];
  min_confidence: number;
  sort: SortOption;
}


const DEFAULT_FILTERS: Filters = {
  lookback_days: 14,
  classifications: ["watch", "entry"],
  sources: ["weekend", "daily-delta"],
  min_confidence: 0.0,
  sort: "classified_at_desc",
};

const CLASSIFICATION_ORDER = ["watch", "entry", "ignore"] as const;

const CLASSIFICATION_LABELS: Record<string, string> = {
  watch: "Watch",
  entry: "Entry",
  ignore: "Ignore",
};

const CLASSIFICATION_TONES: Record<string, string> = {
  watch: "bg-tint-blue text-accent",
  entry: "bg-success-soft text-success",
  ignore: "bg-tint-stone text-muted",
};


function buildQueryString(filters: Filters): string {
  const params = new URLSearchParams();
  params.set("lookback_days", String(filters.lookback_days));
  for (const c of filters.classifications) params.append("classifications", c);
  for (const s of filters.sources) params.append("sources", s);
  params.set("min_confidence", String(filters.min_confidence));
  params.set("sort", filters.sort);
  return params.toString();
}


function ClassificationChip({ classification }: { classification: string }) {
  const tone = CLASSIFICATION_TONES[classification] ?? "bg-tint-stone text-muted";
  const label = CLASSIFICATION_LABELS[classification] ?? classification;
  return <span className={`chip ${tone}`}>{label}</span>;
}


function RowHeader({
  row,
  expanded,
  onToggle,
}: {
  row: Classification;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      onClick={onToggle}
      className="flex items-center gap-3 px-4 py-3 hover:bg-cream cursor-pointer"
    >
      <span className="text-faint shrink-0">
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </span>
      <span className="num text-data text-ink shrink-0">{row.symbol}</span>
      <span className="text-data text-ink truncate flex-1 min-w-0">{row.name}</span>
      <ClassificationChip classification={row.classification} />
      {row.pattern && (
        <span className="text-data-xs text-muted">{row.pattern}</span>
      )}
      {row.confidence != null && (
        <span className="num text-data-xs text-faint shrink-0">
          conf {row.confidence.toFixed(2)}
        </span>
      )}
      <Tooltip
        content={
          <>
            <div className="num">분류: {formatKst(row.classified_at)}</div>
            {row.expires_at && (
              <div className="num">만료: {formatKst(row.expires_at)}</div>
            )}
            <div className="text-faint mt-1">(KST)</div>
          </>
        }
      >
        <span className="text-data-xs text-faint shrink-0 cursor-help underline decoration-dotted decoration-faint underline-offset-2">
          {relativeTime(row.classified_at)}
        </span>
      </Tooltip>
    </div>
  );
}


function RowDetails({ row }: { row: Classification }) {
  return (
    <div className="px-10 pb-4 space-y-3 bg-cream/50">
      <div className="grid grid-cols-2 gap-4 text-data-xs">
        {row.pivot_price != null && (
          <div>
            <div className="caps text-faint">Pivot</div>
            <div className="num text-data text-ink">
              {row.pivot_price.toLocaleString()}{" "}
              {row.pivot_basis && (
                <span className="text-data-xs text-faint">({row.pivot_basis})</span>
              )}
            </div>
          </div>
        )}
        {row.base_high != null && row.base_low != null && (
          <div>
            <div className="caps text-faint">Base</div>
            <div className="num text-data text-ink">
              {row.base_low.toLocaleString()} ~ {row.base_high.toLocaleString()}
              {row.base_depth_pct != null && (
                <span className="text-data-xs text-faint"> ({row.base_depth_pct.toFixed(1)}%)</span>
              )}
              {row.base_start_date && (
                <div className="text-data-xs text-faint">{row.base_start_date} 부터</div>
              )}
            </div>
          </div>
        )}
      </div>

      {row.risk_flags && row.risk_flags.length > 0 && (
        <div>
          <div className="caps text-faint mb-1">Risk Flags</div>
          <div className="flex flex-wrap gap-1">
            {row.risk_flags.map((flag) => (
              <span key={flag} className="chip bg-amber-soft text-amber">
                <AlertTriangle size={11} /> {flag}
              </span>
            ))}
          </div>
        </div>
      )}

      {row.reasoning && (
        <div>
          <div className="caps text-faint mb-1">Reasoning</div>
          <div className="text-data text-ink whitespace-pre-wrap bg-paper border border-hairline rounded-lg p-3 max-h-64 overflow-auto leading-relaxed">
            {row.reasoning}
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-data-xs text-faint num">
        <span>source: {row.source}</span>
        {row.llm_call_duration_s != null && (
          <span>duration: {row.llm_call_duration_s.toFixed(1)}s</span>
        )}
        {row.llm_input_tokens != null && (
          <span>in: {row.llm_input_tokens.toLocaleString()} tok</span>
        )}
        {row.llm_output_tokens != null && (
          <span>out: {row.llm_output_tokens.toLocaleString()} tok</span>
        )}
      </div>

      <Link
        to={`/chart/${row.symbol}`}
        onClick={(e) => e.stopPropagation()}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-accent text-white rounded-lg text-data-xs font-semibold hover:bg-accent-light"
      >
        <LineChart size={11} /> 차트 보기
      </Link>
    </div>
  );
}


function ClassificationGroup({
  classification,
  rows,
  expandedRows,
  onToggleRow,
}: {
  classification: string;
  rows: Classification[];
  expandedRows: Set<string>;
  onToggleRow: (symbol: string) => void;
}) {
  const [groupOpen, setGroupOpen] = useState(classification !== "ignore");

  if (rows.length === 0) return null;

  return (
    <section className="bento mb-4 overflow-hidden">
      <div
        onClick={() => setGroupOpen(!groupOpen)}
        className="flex items-center gap-2 px-4 py-3 cursor-pointer hover:bg-cream"
      >
        <span className="text-faint">
          {groupOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <ClassificationChip classification={classification} />
        <span className="text-data text-muted">{rows.length} 건</span>
      </div>
      {groupOpen && (
        <div className="border-t border-hairline">
          {rows.map((row, idx) => (
            <div
              key={row.symbol}
              className={idx < rows.length - 1 ? "border-b border-hairline" : ""}
            >
              <RowHeader
                row={row}
                expanded={expandedRows.has(row.symbol)}
                onToggle={() => onToggleRow(row.symbol)}
              />
              {expandedRows.has(row.symbol) && <RowDetails row={row} />}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}


export default function ClassificationsPage() {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  const qs = buildQueryString(filters);
  const q = useQuery<Classification[]>({
    queryKey: ["classifications", qs],
    queryFn: () => api<Classification[]>(`/classifications?${qs}`),
  });

  const rowsByClassification = useMemo(() => {
    const grouped: Record<string, Classification[]> = {
      watch: [],
      entry: [],
      ignore: [],
    };
    for (const row of q.data ?? []) {
      const c = grouped[row.classification] ?? (grouped[row.classification] = []);
      c.push(row);
    }
    return grouped;
  }, [q.data]);

  const counts = {
    watch: rowsByClassification.watch?.length ?? 0,
    entry: rowsByClassification.entry?.length ?? 0,
    ignore: rowsByClassification.ignore?.length ?? 0,
  };

  const toggleRow = (symbol: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  };

  const toggleClassification = (c: string) => {
    setFilters((prev) => ({
      ...prev,
      classifications: prev.classifications.includes(c)
        ? prev.classifications.filter((x) => x !== c)
        : [...prev.classifications, c],
    }));
  };

  const toggleSource = (s: string) => {
    setFilters((prev) => ({
      ...prev,
      sources: prev.sources.includes(s)
        ? prev.sources.filter((x) => x !== s)
        : [...prev.sources, s],
    }));
  };

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">Classifications</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            LLM 분류
          </h2>
          <div className="flex gap-2 mt-3">
            <span className="chip bg-tint-blue text-accent">Watch {counts.watch}</span>
            <span className="chip bg-success-soft text-success">Entry {counts.entry}</span>
            <span className="chip bg-tint-stone text-muted">Ignore {counts.ignore}</span>
          </div>
        </div>
        <button
          onClick={() => q.refetch()}
          className="flex items-center gap-1.5 text-data text-muted hover:text-ink"
        >
          <RefreshCw size={14} />
          새로고침
        </button>
      </header>

      <section className="bento p-4 mb-6">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex items-center gap-2">
            <span className="caps text-faint">최근</span>
            <select
              value={filters.lookback_days}
              onChange={(e) => setFilters({ ...filters, lookback_days: parseInt(e.target.value, 10) })}
              className="num text-data px-2 py-1 border border-hairline rounded-lg bg-paper"
            >
              <option value={7}>7일</option>
              <option value={14}>14일</option>
              <option value={30}>30일</option>
              <option value={90}>90일</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            <span className="caps text-faint">분류</span>
            {(["watch", "entry", "ignore"] as const).map((c) => (
              <label key={c} className="flex items-center gap-1 cursor-pointer text-data-xs">
                <input
                  type="checkbox"
                  checked={filters.classifications.includes(c)}
                  onChange={() => toggleClassification(c)}
                  className="accent-accent"
                />
                {CLASSIFICATION_LABELS[c]}
              </label>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <span className="caps text-faint">소스</span>
            {(["weekend", "daily-delta"] as const).map((s) => (
              <label key={s} className="flex items-center gap-1 cursor-pointer text-data-xs">
                <input
                  type="checkbox"
                  checked={filters.sources.includes(s)}
                  onChange={() => toggleSource(s)}
                  className="accent-accent"
                />
                {s}
              </label>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <span className="caps text-faint">최소 conf</span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={filters.min_confidence}
              onChange={(e) => setFilters({ ...filters, min_confidence: parseFloat(e.target.value) || 0 })}
              className="num text-data w-20 px-2 py-1 border border-hairline rounded-lg"
            />
          </div>

          <div className="flex items-center gap-2">
            <span className="caps text-faint">정렬</span>
            <select
              value={filters.sort}
              onChange={(e) => setFilters({ ...filters, sort: e.target.value as SortOption })}
              className="text-data px-2 py-1 border border-hairline rounded-lg bg-paper"
            >
              <option value="classified_at_desc">시각 최신</option>
              <option value="confidence_desc">Confidence</option>
            </select>
          </div>
        </div>
      </section>

      {q.isLoading && <div className="text-muted">로딩 중…</div>}
      {q.isError && <div className="text-danger">에러: {String(q.error)}</div>}
      {q.data && q.data.length === 0 && (
        <div className="bento p-8 text-center text-muted">
          최근 {filters.lookback_days}일간 분류 결과 없음.
          <div className="text-data-xs text-faint mt-2">
            /runner 에서 'LLM 주말 분류' 또는 'LLM 평일 전체 분석' 실행.
          </div>
        </div>
      )}
      {q.data && q.data.length > 0 && (
        <>
          {CLASSIFICATION_ORDER.map((c) => (
            <ClassificationGroup
              key={c}
              classification={c}
              rows={rowsByClassification[c] ?? []}
              expandedRows={expandedRows}
              onToggleRow={toggleRow}
            />
          ))}
        </>
      )}
    </div>
  );
}
