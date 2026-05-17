import { useState, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  File,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Package,
  Download,
  Search,
} from "lucide-react";
import { api, apiUrl } from "../lib/api";
import type { Stock, MinerviniPassed, MarketContext } from "../lib/types";

const ZIP_FILES = [
  { name: "README.md", desc: "분석 가이드" },
  { name: "prompt_step1_analyze.md", desc: "Step 1 분류 프롬프트" },
  { name: "prompt_step2_entry_params.md", desc: "Step 2 진입 파라미터" },
  { name: "payload.json", desc: "통합 페이로드" },
  { name: "market_context.json", desc: "시장 컨텍스트" },
  { name: "corporate_actions.json", desc: "기업 행위" },
  { name: "minervini.json", desc: "8조건 상세" },
  { name: "daily.csv", desc: "일봉 시계열" },
  { name: "weekly.csv", desc: "주봉 시계열" },
  { name: "kospi_daily.csv", desc: "KOSPI 일봉" },
  { name: "kospi_weekly.csv", desc: "KOSPI 주봉" },
  { name: "daily_chart.png", desc: "일봉 차트" },
  { name: "weekly_chart.png", desc: "주봉 차트" },
] as const;

const MINERVINI_CONDITIONS = [
  { id: "c1", label: "C1", desc: "추세 정렬" },
  { id: "c2", label: "C2", desc: "150 > 200" },
  { id: "c3", label: "C3", desc: "200 상승" },
  { id: "c4", label: "C4", desc: "50 > 150 > 200" },
  { id: "c5", label: "C5", desc: "종가 > 50" },
  { id: "c6", label: "C6", desc: "52w 저점 +25%" },
  { id: "c7", label: "C7", desc: "52w 고점 -25%" },
  { id: "c8", label: "C8", desc: "RS ≥ 70" },
] as const;

function statusKr(status: string): string {
  const map: Record<string, string> = {
    confirmed_uptrend: "상승 추세 확정",
    uptrend_under_pressure: "상승 압박",
    downtrend: "하락 추세",
    correction: "조정",
    rally_attempt: "반등 시도",
  };
  return map[status] ?? status;
}

function statusTone(status: string): "up" | "down" | "neutral" {
  if (status === "confirmed_uptrend" || status === "rally_attempt") return "up";
  if (status === "downtrend" || status === "correction") return "down";
  return "neutral";
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10).replace(/-/g, "");
}

// ── Stock Picker ────────────────────────────────────────────────────────────

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
      <label className="caps mb-2 block">종목 선택</label>
      <div className="relative">
        <Search
          size={16}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-faint pointer-events-none"
        />
        <input
          type="text"
          value={open ? query : selectedTicker ?? ""}
          placeholder="티커 또는 종목명 검색…"
          className="w-full border border-hairline rounded-xl pl-10 pr-3 py-3 text-data bg-cream focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
          onFocus={() => {
            setOpen(true);
            setQuery("");
          }}
          onChange={(e) => setQuery(e.target.value)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
        />
      </div>

      {open && (
        <div className="absolute z-10 mt-1.5 w-full bg-paper border border-hairline rounded-xl shadow-bento overflow-hidden max-h-64 overflow-y-auto">
          {stocksQ.isError && (
            <div className="px-4 py-3 text-data text-danger">목록 오류</div>
          )}
          {!stocksQ.isError && filtered.length === 0 && (
            <div className="px-4 py-3 text-data text-muted">
              검색 결과 없음
            </div>
          )}
          {filtered.map((s) => (
            <button
              key={s.ticker}
              className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-tint-blue transition-colors"
              onClick={() => handleSelect(s.ticker)}
            >
              <span className="num text-data text-accent font-semibold w-20 shrink-0">
                {s.ticker}
              </span>
              <span className="text-data text-ink truncate">{s.name}</span>
              <span className="ml-auto text-data-xs text-faint shrink-0">
                {s.market}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Preview Card ────────────────────────────────────────────────────────────

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
    queryFn: () =>
      api<MinerviniPassed[]>("/indicators/minervini-passed?limit=1000"),
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
        stock.market === "KOSDAQ"
          ? m.index_code === "2001"
          : m.index_code === "1001"
      )
    : undefined;

  if (stockQ.isLoading) {
    return <div className="bento p-6 text-muted">종목 정보 로딩 중…</div>;
  }

  if (stockQ.isError || !stock) {
    return (
      <div className="bento p-6 flex items-center gap-2 text-danger">
        <AlertCircle size={16} /> 종목 정보를 불러오지 못했습니다.
      </div>
    );
  }

  const tone = marketEntry ? statusTone(marketEntry.current_status) : "neutral";
  const toneClass =
    tone === "up"
      ? "bg-success-soft text-success"
      : tone === "down"
      ? "bg-danger-soft text-danger"
      : "bg-tint-stone text-muted";

  return (
    <div className="bento overflow-hidden">
      {/* Header */}
      <div className="px-6 py-5 border-b border-hairline">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="num font-bold text-data-lg text-ink">
                {stock.ticker}
              </span>
              <span className="chip bg-tint-stone text-muted">
                {stock.market}
              </span>
            </div>
            <div className="text-display-md font-bold text-ink leading-tight">
              {stock.name}
            </div>
            {stock.sector && (
              <div className="text-data text-muted mt-1">{stock.sector}</div>
            )}
          </div>

          {marketEntry && (
            <span className={`chip ${toneClass} shrink-0`}>
              {stock.market === "KOSDAQ" ? "KOSDAQ" : "KOSPI"} ·{" "}
              {statusKr(marketEntry.current_status)}
            </span>
          )}
        </div>
      </div>

      {/* 8 conditions */}
      <div className="px-6 py-5 border-b border-hairline">
        <div className="caps mb-3">미너비니 8조건</div>
        <div className="grid grid-cols-4 sm:grid-cols-8 gap-2">
          {MINERVINI_CONDITIONS.map((cond) => {
            const passed = !!minerviniEntry;
            return (
              <div
                key={cond.id}
                className={`p-2 rounded-lg border text-center ${
                  passed
                    ? "bg-success-soft border-success/30 text-success"
                    : "bg-tint-stone border-hairline text-faint"
                }`}
                title={cond.desc}
              >
                <div className="text-data-xs font-bold">{cond.label}</div>
                <div className="text-data-xs mt-0.5 opacity-75 truncate">
                  {cond.desc}
                </div>
              </div>
            );
          })}
        </div>
        {!minerviniQ.isLoading && !minerviniEntry && (
          <p className="mt-3 text-data-xs text-muted flex items-center gap-1.5">
            <XCircle size={13} className="text-faint" />
            현재 미너비니 통과 목록에 없음
          </p>
        )}
        {!minerviniQ.isLoading && minerviniEntry && (
          <p className="mt-3 text-data-xs text-success flex items-center gap-1.5">
            <CheckCircle2 size={13} />
            미너비니 8조건 모두 통과
            {minerviniEntry.rs_rating != null && (
              <span className="text-muted ml-1">· RS {minerviniEntry.rs_rating}</span>
            )}
          </p>
        )}
      </div>

      {/* Ready */}
      <div className="px-6 py-4 bg-tint-mint">
        <div className="flex items-center gap-2 text-success font-semibold">
          <CheckCircle2 size={16} />
          ZIP 다운로드 준비 완료
        </div>
      </div>
    </div>
  );
}

// ── ZIP Contents ────────────────────────────────────────────────────────────

function ZipContentsList() {
  return (
    <div className="bento overflow-hidden">
      <div className="px-5 py-4 border-b border-hairline flex items-center gap-2.5">
        <div className="p-2 rounded-xl bg-tint-blue">
          <Package size={16} className="text-accent" strokeWidth={2} />
        </div>
        <div>
          <div className="text-subhead font-bold text-ink">
            ZIP 파일 구성
          </div>
          <div className="text-data-xs text-muted mt-0.5">
            {ZIP_FILES.length}개 파일
          </div>
        </div>
      </div>
      <ul className="divide-y divide-hairline">
        {ZIP_FILES.map((f) => (
          <li
            key={f.name}
            className="flex items-center gap-3 px-5 py-2.5"
          >
            <File size={14} className="text-faint shrink-0" strokeWidth={2} />
            <span className="num text-data text-ink">{f.name}</span>
            <span className="ml-auto text-data-xs text-muted">{f.desc}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────────

export default function PromptPage() {
  const { ticker } = useParams<{ ticker?: string }>();
  const navigate = useNavigate();
  const today = todayStr();

  const handleSelect = (selected: string) => {
    navigate(`/prompt/${selected}`);
  };

  return (
    <div className="px-10 py-10 max-w-[920px] mx-auto">
      {/* Header */}
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">LLM Prompt</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            분석 패키지
          </h2>
        </div>
      </header>

      {/* Picker */}
      <div className="bento p-5 mb-5">
        <StockPicker selectedTicker={ticker} onSelect={handleSelect} />
      </div>

      {/* Empty */}
      {!ticker && (
        <div className="bento p-12 text-center">
          <Package
            size={40}
            className="text-faint mx-auto mb-3"
            strokeWidth={1.5}
          />
          <p className="text-headline font-semibold text-ink mb-1">
            종목을 선택해주세요
          </p>
          <p className="text-data text-muted">
            검색하거나 위 입력란을 클릭해 종목 목록을 보세요
          </p>
        </div>
      )}

      {/* Preview + Download */}
      {ticker && (
        <div className="space-y-5">
          <PreviewCard ticker={ticker} />

          {/* Download button */}
          <a
            href={apiUrl(`/prompts/${ticker}.zip`)}
            download={`analysis-${ticker}-${today}.zip`}
            className="flex items-center justify-between gap-4 bento bento-clickable p-5 group hover:border-accent"
          >
            <div className="flex items-center gap-4">
              <div className="p-3 rounded-2xl bg-accent text-white">
                <Download size={20} strokeWidth={2} />
              </div>
              <div>
                <div className="text-subhead font-bold text-ink">
                  분석 패키지 다운로드
                </div>
                <div className="num text-data text-muted mt-0.5">
                  analysis-{ticker}-{today}.zip
                </div>
              </div>
            </div>
            <span className="chip bg-tint-blue text-accent">
              13 files · ZIP
            </span>
          </a>

          <ZipContentsList />
        </div>
      )}
    </div>
  );
}
