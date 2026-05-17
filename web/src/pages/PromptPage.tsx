import { useState, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { File, CheckCircle2, XCircle, AlertCircle, Package } from "lucide-react";
import { api, apiUrl } from "../lib/api";
import type { Stock, MinerviniPassed, MarketContext } from "../lib/types";
import { cn } from "../lib/utils";

// ── Constants ──────────────────────────────────────────────────────────────

const ZIP_FILES = [
  "README.md",
  "prompt_step1_analyze.md",
  "prompt_step2_entry_params.md",
  "payload.json",
  "market_context.json",
  "corporate_actions.json",
  "minervini.json",
  "daily.csv",
  "weekly.csv",
  "kospi_daily.csv",
  "kospi_weekly.csv",
  "daily_chart.png",
  "weekly_chart.png",
] as const;

const MINERVINI_CONDITIONS = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"] as const;

// ── Helpers ────────────────────────────────────────────────────────────────

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    confirmed_uptrend: "Confirmed Uptrend",
    uptrend_under_pressure: "Uptrend Under Pressure",
    downtrend: "Downtrend",
    correction: "Correction",
  };
  return map[status] ?? status;
}

function statusColors(status: string): string {
  if (status === "confirmed_uptrend" || status === "uptrend_under_pressure") {
    return "bg-green-50 text-green-700 border-green-200";
  }
  if (status === "downtrend" || status === "correction") {
    return "bg-red-50 text-red-700 border-red-200";
  }
  return "bg-gray-50 text-gray-700 border-gray-200";
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10).replace(/-/g, "");
}

// ── Sub-components ─────────────────────────────────────────────────────────

interface ConditionChipProps {
  label: string;
  state: "pass" | "fail" | "unknown";
}

function ConditionChip({ label, state }: ConditionChipProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center w-9 h-9 rounded-lg text-xs font-bold border",
        state === "pass" && "bg-green-100 text-green-800 border-green-300",
        state === "fail" && "bg-red-100 text-red-700 border-red-200",
        state === "unknown" && "bg-gray-100 text-gray-400 border-gray-200"
      )}
      title={label}
    >
      {label.toUpperCase()}
    </span>
  );
}

interface StockOptionProps {
  stock: Stock;
  onSelect: (ticker: string) => void;
}

function StockOption({ stock, onSelect }: StockOptionProps) {
  return (
    <button
      className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-blue-50 transition-colors"
      onClick={() => onSelect(stock.ticker)}
    >
      <span className="font-mono font-semibold text-blue-700 w-20 shrink-0">{stock.ticker}</span>
      <span className="text-gray-700 truncate">{stock.name}</span>
      <span className="ml-auto text-xs text-gray-400 shrink-0">{stock.market}</span>
    </button>
  );
}

// ── Stock Picker ───────────────────────────────────────────────────────────

interface StockPickerProps {
  selectedTicker: string | undefined;
  onSelect: (ticker: string) => void;
}

function StockPicker({ selectedTicker, onSelect }: StockPickerProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const stocksQ = useQuery<Stock[]>({
    queryKey: ["stocks-all"],
    queryFn: () => api<Stock[]>("/stocks?limit=10000"),
    staleTime: 5 * 60 * 1000,
  });

  const filtered = useMemo(() => {
    if (!stocksQ.data) return [];
    const q = query.trim().toLowerCase();
    if (!q) return stocksQ.data.slice(0, 20);
    return stocksQ.data
      .filter(
        (s) =>
          s.ticker.toLowerCase().includes(q) ||
          s.name.toLowerCase().includes(q)
      )
      .slice(0, 20);
  }, [stocksQ.data, query]);

  const handleSelect = (ticker: string) => {
    setQuery("");
    setOpen(false);
    onSelect(ticker);
  };

  return (
    <div className="relative">
      <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1.5">
        종목 선택
      </label>
      <div className="relative">
        <input
          type="text"
          value={open ? query : (selectedTicker ?? "")}
          placeholder="티커 또는 종목명 검색…"
          className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 pr-10"
          onFocus={() => {
            setOpen(true);
            setQuery("");
          }}
          onChange={(e) => setQuery(e.target.value)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
        />
        {stocksQ.isLoading && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 text-xs">
            로딩…
          </span>
        )}
      </div>

      {open && (
        <div className="absolute z-10 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden max-h-64 overflow-y-auto">
          {stocksQ.isError && (
            <div className="px-3 py-2 text-sm text-red-500">종목 목록 오류</div>
          )}
          {!stocksQ.isError && filtered.length === 0 && (
            <div className="px-3 py-2 text-sm text-gray-400">검색 결과 없음</div>
          )}
          {filtered.map((s) => (
            <StockOption key={s.ticker} stock={s} onSelect={handleSelect} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Preview Card ───────────────────────────────────────────────────────────

interface PreviewCardProps {
  ticker: string;
}

function PreviewCard({ ticker }: PreviewCardProps) {
  const stockQ = useQuery<Stock>({
    queryKey: ["stock", ticker],
    queryFn: () => api<Stock>(`/stocks/${ticker}`),
    enabled: !!ticker,
  });

  const minerviniQ = useQuery<MinerviniPassed[]>({
    queryKey: ["minervini-all-prompt"],
    queryFn: () => api<MinerviniPassed[]>("/indicators/minervini-passed?limit=1000"),
    staleTime: 5 * 60 * 1000,
  });

  const marketQ = useQuery<MarketContext[]>({
    queryKey: ["market-context"],
    queryFn: () => api<MarketContext[]>("/market-context"),
    staleTime: 5 * 60 * 1000,
  });

  const stock = stockQ.data;
  const minerviniEntry = minerviniQ.data?.find((m) => m.ticker === ticker);
  const marketEntry = stock
    ? marketQ.data?.find((m) =>
        stock.market === "KOSDAQ" ? m.index_code === "2001" : m.index_code === "1001"
      )
    : undefined;

  const isLoading = stockQ.isLoading;
  const isError = stockQ.isError;

  if (isLoading) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm text-gray-400 text-sm">
        종목 정보 불러오는 중…
      </div>
    );
  }

  if (isError || !stock) {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm flex items-center gap-2 text-red-600 text-sm">
        <AlertCircle size={15} /> 종목 정보를 불러오지 못했습니다.
      </div>
    );
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-6 py-5 border-b border-gray-100">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-mono font-bold text-xl text-blue-700">{stock.ticker}</span>
              <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600 font-medium">
                {stock.market}
              </span>
            </div>
            <div className="text-lg font-semibold text-gray-900">{stock.name}</div>
            {stock.sector && (
              <div className="text-sm text-gray-500 mt-0.5">{stock.sector}</div>
            )}
          </div>

          {/* Market status badge */}
          {marketEntry && (
            <div
              className={cn(
                "shrink-0 px-3 py-1.5 rounded-lg border text-xs font-semibold",
                statusColors(marketEntry.current_status)
              )}
            >
              {stock.market === "KOSDAQ" ? "KOSDAQ" : "KOSPI"}{" "}
              {statusLabel(marketEntry.current_status)}
            </div>
          )}
        </div>
      </div>

      {/* 8 Minervini Conditions */}
      <div className="px-6 py-4 border-b border-gray-100">
        <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
          미너비니 8조건
        </div>
        <div className="flex flex-wrap gap-2">
          {MINERVINI_CONDITIONS.map((cond) => {
            let state: "pass" | "fail" | "unknown" = "unknown";
            if (minerviniEntry) {
              // If found in minervini-passed, all conditions pass for this entry
              state = "pass";
            }
            return (
              <ConditionChip key={cond} label={cond} state={state} />
            );
          })}
        </div>
        {!minerviniQ.isLoading && !minerviniEntry && (
          <p className="mt-2 text-xs text-gray-400 flex items-center gap-1">
            <XCircle size={12} /> 현재 미너비니 통과 목록에 없음
          </p>
        )}
        {!minerviniQ.isLoading && minerviniEntry && (
          <p className="mt-2 text-xs text-green-600 flex items-center gap-1">
            <CheckCircle2 size={12} /> 미너비니 통과
            {minerviniEntry.rs_rating != null && (
              <span className="text-gray-500 ml-1">RS {minerviniEntry.rs_rating}</span>
            )}
          </p>
        )}
      </div>

      {/* Ready callout */}
      <div className="px-6 py-4">
        <div className="flex items-center gap-2 bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-sm text-green-800 font-medium">
          <span className="text-base">🟢</span>
          ZIP 다운로드 준비됨 — {ticker}
        </div>
      </div>
    </div>
  );
}

// ── ZIP Contents List ──────────────────────────────────────────────────────

function ZipContentsList() {
  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-2">
        <Package size={16} className="text-gray-500" />
        <span className="text-sm font-semibold text-gray-700">ZIP 파일 구성 ({ZIP_FILES.length}개)</span>
      </div>
      <ul className="divide-y divide-gray-100">
        {ZIP_FILES.map((fname) => (
          <li key={fname} className="flex items-center gap-3 px-5 py-2.5">
            <File size={14} className="text-gray-400 shrink-0" />
            <span className="font-mono text-sm text-gray-700">{fname}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function PromptPage() {
  const { ticker } = useParams<{ ticker?: string }>();
  const navigate = useNavigate();
  const today = todayStr();

  const handleSelect = (selected: string) => {
    navigate(`/prompt/${selected}`);
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <h2 className="text-2xl font-bold text-gray-900">LLM 프롬프트 ZIP</h2>

      {/* Stock Picker */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
        <StockPicker selectedTicker={ticker} onSelect={handleSelect} />
      </div>

      {/* No ticker selected */}
      {!ticker && (
        <div className="bg-gray-50 border border-dashed border-gray-300 rounded-xl p-10 text-center text-gray-400 text-sm">
          종목을 선택해주세요
        </div>
      )}

      {/* Preview + Download */}
      {ticker && (
        <>
          <PreviewCard ticker={ticker} />

          {/* Download Button */}
          <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm flex items-center justify-between gap-4">
            <div>
              <div className="text-sm font-semibold text-gray-700 mb-0.5">분석 패키지 다운로드</div>
              <div className="text-xs text-gray-400">
                analysis-{ticker}-{today}.zip
              </div>
            </div>
            <a
              href={apiUrl(`/prompts/${ticker}.zip`)}
              download={`analysis-${ticker}-${today}.zip`}
              className={cn(
                "flex items-center gap-2 px-5 py-2.5 rounded-lg font-semibold text-sm text-white",
                "bg-blue-600 hover:bg-blue-700 active:bg-blue-800 transition-colors shadow-sm"
              )}
            >
              <span>📦</span>
              Download analysis-{ticker}-{today}.zip
            </a>
          </div>

          {/* ZIP Contents */}
          <ZipContentsList />
        </>
      )}
    </div>
  );
}
