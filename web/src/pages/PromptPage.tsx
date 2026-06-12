import { useState, useMemo } from "react";
import { C6_W52LOW_MULT, C7_W52HIGH_MULT, C8_RS_RATING_MIN } from "../data/thresholds.generated";
import { todayKstISO } from "../lib/dates";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import * as Tooltip from "@radix-ui/react-tooltip";
import {
  File,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Package,
  Download,
  Search,
  ShieldAlert,
  Archive,
} from "lucide-react";
import { api, apiUrl } from "../lib/api";
import type { Stock, MinerviniPassed, MarketContext } from "../lib/types";

const ZIP_FILES = [
  { name: "README.md", desc: "분석 가이드 + 검증 모드 안내" },
  { name: "prompt_step1_analyze.md", desc: "Step 1 분류 프롬프트" },
  { name: "prompt_step2_entry_params.md", desc: "Step 2 진입 파라미터" },
  { name: "prompt_verify.md", desc: "🆕 분석 검증 프롬프트 (5 차원)" },
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
  { name: "analysis_result.json", desc: "🆕 시스템 LLM 분석 결과 (검증 대상, 분류 이력 있을 때만)" },
] as const;

const MINERVINI_CONDITIONS = [
  { id: "c1", label: "C1", desc: "추세 정렬" },
  { id: "c2", label: "C2", desc: "150 > 200" },
  { id: "c3", label: "C3", desc: "200 상승" },
  { id: "c4", label: "C4", desc: "50 > 150 > 200" },
  { id: "c5", label: "C5", desc: "종가 > 50" },
  { id: "c6", label: "C6", desc: `52w 저점 +${Math.round((C6_W52LOW_MULT - 1) * 100)}%` },
  { id: "c7", label: "C7", desc: `52w 고점 -${Math.round((1 - C7_W52HIGH_MULT) * 100)}%` },
  { id: "c8", label: "C8", desc: `RS ≥ ${C8_RS_RATING_MIN}` },
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
  return todayKstISO().replace(/-/g, "");
}

interface ConditionDetail {
  passed: boolean | null;
  description: string;
  values: Record<string, number>;
  margin_pct: number | null;
}

interface MinerviniDetailResponse {
  ticker: string;
  date: string;
  detail: Record<string, ConditionDetail>;
}

const CONDITION_VALUE_LABELS: Record<string, string> = {
  close: "종가",
  sma_50: "SMA 50",
  sma_150: "SMA 150",
  sma_200: "SMA 200",
  w52_high: "52w 고가",
  w52_low: "52w 저가",
  rs_rating: "RS Rating",
  threshold: "임계값",
};

function fmtNumber(v: number): string {
  if (Number.isInteger(v)) return v.toLocaleString();
  return v.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

interface ConditionChipProps {
  condKey: string;
  label: string;
  shortDesc: string;
  detail?: ConditionDetail;
}

function ConditionChip({ condKey, label, shortDesc, detail }: ConditionChipProps) {
  const state =
    detail == null
      ? "unknown"
      : detail.passed === true
      ? "pass"
      : detail.passed === false
      ? "fail"
      : "unknown";

  const tileClass =
    state === "pass"
      ? "bg-success-soft border-success/30 text-success"
      : state === "fail"
      ? "bg-danger-soft border-danger/30 text-danger"
      : "bg-tint-stone border-hairline text-faint";

  return (
    <Tooltip.Provider delayDuration={120} skipDelayDuration={300}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button
            type="button"
            className={`p-2 rounded-lg border text-center transition-all hover:shadow-bento cursor-help ${tileClass}`}
          >
            <div className="text-data-xs font-bold uppercase">{label}</div>
            <div className="text-data-xs mt-0.5 opacity-75 truncate">
              {shortDesc}
            </div>
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            sideOffset={8}
            className="z-50 max-w-xs rounded-xl bg-ink text-paper px-4 py-3 shadow-bento-hover"
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="caps text-paper/60">조건 {condKey}</span>
              {detail && (
                <span
                  className={`chip ${
                    state === "pass"
                      ? "bg-success/20 text-success"
                      : state === "fail"
                      ? "bg-danger/20 text-danger"
                      : "bg-paper/10 text-paper/60"
                  }`}
                >
                  {state === "pass"
                    ? "통과"
                    : state === "fail"
                    ? "미달"
                    : "미상"}
                </span>
              )}
            </div>
            <div className="text-data font-semibold mb-2">
              {detail?.description ?? shortDesc}
            </div>

            {detail?.margin_pct != null && (
              <div className="mb-3 pb-3 border-b border-paper/20 flex items-baseline justify-between">
                <span className="text-data-xs text-paper/60">여유 %</span>
                <span
                  className={`num text-data-md font-bold ${
                    detail.margin_pct >= 0 ? "text-success" : "text-danger"
                  }`}
                >
                  {detail.margin_pct >= 0 ? "+" : ""}
                  {detail.margin_pct.toFixed(2)}%
                </span>
              </div>
            )}

            {detail && Object.keys(detail.values).length > 0 && (
              <div className="space-y-1">
                {Object.entries(detail.values).map(([k, v]) => (
                  <div
                    key={k}
                    className="flex items-baseline justify-between gap-3 text-data-xs"
                  >
                    <span className="text-paper/60">
                      {CONDITION_VALUE_LABELS[k] ?? k}
                    </span>
                    <span className="num text-paper">{fmtNumber(v)}</span>
                  </div>
                ))}
              </div>
            )}

            {!detail && (
              <div className="text-data-xs text-paper/60 mt-1">
                상세 정보가 없습니다.
              </div>
            )}

            <Tooltip.Arrow className="fill-ink" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
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
  const detailQ = useQuery<MinerviniDetailResponse>({
    queryKey: ["minervini-detail", ticker],
    queryFn: () =>
      api<MinerviniDetailResponse>(`/indicators/minervini-detail/${ticker}`),
    enabled: !!ticker,
    staleTime: 60_000,
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
        <div className="flex items-baseline justify-between mb-3">
          <div className="caps">미너비니 8조건</div>
          <div className="text-data-xs text-faint">
            각 조건 hover · 여유 % 와 값 확인
          </div>
        </div>
        <div className="grid grid-cols-4 sm:grid-cols-8 gap-2">
          {MINERVINI_CONDITIONS.map((cond) => (
            <ConditionChip
              key={cond.id}
              condKey={cond.id}
              label={cond.label}
              shortDesc={cond.desc}
              detail={detailQ.data?.detail[cond.id]}
            />
          ))}
        </div>
        {detailQ.data && (
          <p className="mt-3 text-data-xs text-muted">
            기준일:{" "}
            <span className="num text-ink">{detailQ.data.date}</span>
            {minerviniEntry && (
              <span className="text-success ml-3 inline-flex items-center gap-1">
                <CheckCircle2 size={12} /> 미너비니 8조건 모두 통과 · RS{" "}
                {minerviniEntry.rs_rating}
              </span>
            )}
            {!minerviniEntry && !minerviniQ.isLoading && (
              <span className="text-muted ml-3 inline-flex items-center gap-1">
                <XCircle size={12} className="text-faint" /> 미달 조건 있음
              </span>
            )}
          </p>
        )}
        {detailQ.isLoading && (
          <p className="mt-3 text-data-xs text-faint">조건 상세 로딩 중…</p>
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

// ── Batch download card ────────────────────────────────────────────────────

const BATCH_RS_OPTIONS = [70, 80, 90] as const;

function BatchDownloadCard() {
  const [minRs, setMinRs] = useState<number>(80);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const listQ = useQuery<MinerviniPassed[]>({
    queryKey: ["minervini-batch-list", minRs],
    queryFn: () =>
      api<MinerviniPassed[]>(
        `/indicators/minervini-passed?min_rs=${minRs}&limit=200`
      ),
    staleTime: 60_000,
  });

  const stocks = listQ.data ?? [];
  const today = todayStr();

  function toggle(ticker: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(ticker)) next.delete(ticker);
      else next.add(ticker);
      return next;
    });
  }
  function selectAll() {
    setSelected(new Set(stocks.map((s) => s.ticker)));
  }
  function clearAll() {
    setSelected(new Set());
  }

  const tickerList = Array.from(selected);
  const downloadUrl =
    tickerList.length > 0
      ? apiUrl(`/prompts/batch.zip?tickers=${tickerList.join(",")}`)
      : null;

  return (
    <div className="bento p-5 space-y-4">
      <div className="flex items-center gap-2.5">
        <div className="p-2 rounded-xl bg-tint-amber">
          <Package size={16} className="text-amber" strokeWidth={2} />
        </div>
        <div className="flex-1">
          <div className="text-subhead font-bold text-ink">
            일괄 다운로드
          </div>
          <div className="text-data-xs text-muted mt-0.5">
            여러 종목의 분석 패키지를 한 ZIP으로 묶어 다운로드
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1.5">
          <label className="caps">RS 필터</label>
          <div className="flex rounded-lg border border-hairline overflow-hidden text-data font-semibold bg-cream">
            {BATCH_RS_OPTIONS.map((v) => (
              <button
                key={v}
                onClick={() => {
                  setMinRs(v);
                  setSelected(new Set());
                }}
                className={`px-3 py-1.5 transition-colors ${
                  minRs === v
                    ? "bg-accent text-white"
                    : "text-muted hover:text-ink hover:bg-paper"
                }`}
              >
                ≥{v}
              </button>
            ))}
          </div>
        </div>

        <div className="flex gap-2 ml-auto text-data-xs">
          <button
            onClick={selectAll}
            disabled={listQ.isLoading || stocks.length === 0}
            className="text-accent hover:underline font-medium disabled:opacity-50"
          >
            전체 선택
          </button>
          <span className="text-faint">·</span>
          <button
            onClick={clearAll}
            disabled={selected.size === 0}
            className="text-muted hover:text-ink hover:underline disabled:opacity-50"
          >
            선택 해제
          </button>
        </div>
      </div>

      {/* Selection summary + Download */}
      <div className="flex items-center justify-between gap-4 px-4 py-3 bg-tint-blue rounded-xl">
        <div className="text-data">
          <span className="text-muted">선택된 종목:</span>{" "}
          <span className="num font-bold text-ink">{selected.size}</span>
          <span className="text-muted"> / 전체 {stocks.length}개</span>
        </div>
        {downloadUrl ? (
          <a
            href={downloadUrl}
            download={`analysis-batch-${today}.zip`}
            className="flex items-center gap-2 px-4 py-2 bg-accent text-white rounded-xl text-data font-semibold hover:bg-accent-light transition-colors"
          >
            <Download size={16} strokeWidth={2} />
            ZIP 다운로드
          </a>
        ) : (
          <span className="chip bg-tint-stone text-muted">
            선택된 종목 없음
          </span>
        )}
      </div>

      {/* Stocks list */}
      <div>
        {listQ.isLoading && (
          <div className="text-muted py-4">로딩 중…</div>
        )}
        {listQ.isError && (
          <div className="text-danger py-4">로딩 실패</div>
        )}
        {!listQ.isLoading && stocks.length === 0 && (
          <div className="text-muted py-4">통과 종목 없음</div>
        )}
        {stocks.length > 0 && (
          <div className="max-h-80 overflow-y-auto space-y-0.5 border border-hairline rounded-xl">
            {stocks.map((s) => {
              const checked = selected.has(s.ticker);
              return (
                <label
                  key={s.ticker}
                  className={`flex items-center gap-3 px-3 py-2 cursor-pointer transition-colors ${
                    checked ? "bg-tint-blue" : "hover:bg-cream"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(s.ticker)}
                    className="w-4 h-4 accent-accent"
                  />
                  <span className="num text-data text-muted w-16 shrink-0">
                    {s.ticker}
                  </span>
                  <span
                    className="text-data text-ink flex-1 truncate"
                    title={s.name}
                  >
                    {s.name}
                  </span>
                  {s.sector && (
                    <span className="text-data-xs text-faint truncate max-w-[120px]">
                      {s.sector}
                    </span>
                  )}
                  <span className="num text-data-md font-semibold text-ink w-12 text-right shrink-0">
                    {s.rs_rating}
                  </span>
                </label>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Verify Download Button ──────────────────────────────────────────────────

interface VerifyDownloadButtonProps {
  ticker: string;
  today: string;
}

function VerifyDownloadButton({ ticker, today }: VerifyDownloadButtonProps) {
  const [freezeOrigin, setFreezeOrigin] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const handleVerifyDownload = async () => {
    setDownloading(true);
    setFreezeOrigin(null);
    try {
      const resp = await fetch(`/api/prompts/${ticker}.zip?mode=verify`);
      const origin = resp.headers.get("X-Freeze-Origin");
      setFreezeOrigin(origin);
      if (!resp.ok) return;
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `analysis-${ticker}-${today}-verify.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="space-y-2">
      <button
        onClick={handleVerifyDownload}
        disabled={downloading}
        className="w-full flex items-center justify-between gap-4 bento bento-clickable p-5 group hover:border-success disabled:opacity-60"
      >
        <div className="flex items-center gap-4">
          <div className="p-3 rounded-2xl bg-tint-mint text-success">
            <Archive size={20} strokeWidth={2} />
          </div>
          <div>
            <div className="text-subhead font-bold text-ink">
              검증용 패키지 (Frozen 우선)
            </div>
            <div className="text-data text-muted mt-0.5">
              분류 시점 원본 데이터 우선 반환 — 없으면 재빌드
            </div>
          </div>
        </div>
        <span className="chip bg-tint-mint text-success">
          {downloading ? "다운로드 중…" : "verify · ZIP"}
        </span>
      </button>

      {/* Warning banner: frozen not available */}
      {freezeOrigin === "rebuilt" && (
        <div className="flex items-start gap-2.5 px-4 py-3 bg-amber-50 border border-amber-200 rounded-xl text-data text-amber-800">
          <ShieldAlert size={16} className="shrink-0 mt-0.5 text-amber-600" />
          <div>
            <span className="font-semibold">원본 아님 (재빌드됨)</span>
            {" — "}
            분류 시점의 freeze 데이터가 없어 현재 시점으로 재빌드된 패키지입니다.
            재빌드본은 렌더 코드 변경 시 원본과 다를 수 있습니다.
          </div>
        </div>
      )}

      {/* Confirmation: frozen available */}
      {freezeOrigin === "frozen" && (
        <div className="flex items-center gap-2 px-4 py-2.5 bg-tint-mint rounded-xl text-data text-success">
          <CheckCircle2 size={14} />
          분류 시점 원본 freeze 데이터로 다운로드됐습니다.
        </div>
      )}
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────────

type PromptMode = "single" | "batch";

export default function PromptPage() {
  const { ticker } = useParams<{ ticker?: string }>();
  const navigate = useNavigate();
  const today = todayStr();
  const [mode, setMode] = useState<PromptMode>("single");

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
        <div className="flex rounded-lg border border-hairline overflow-hidden text-data font-semibold bg-cream">
          {(["single", "batch"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-4 py-2 transition-colors ${
                mode === m
                  ? "bg-accent text-white"
                  : "text-muted hover:text-ink hover:bg-paper"
              }`}
            >
              {m === "single" ? "단일" : "일괄"}
            </button>
          ))}
        </div>
      </header>

      {mode === "single" && (
        <>
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

              {/* Standard download */}
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
                  14~15 files · ZIP
                </span>
              </a>

              {/* Verify download (frozen 우선) */}
              <VerifyDownloadButton ticker={ticker} today={today} />

              <ZipContentsList />
            </div>
          )}
        </>
      )}

      {mode === "batch" && <BatchDownloadCard />}
    </div>
  );
}
