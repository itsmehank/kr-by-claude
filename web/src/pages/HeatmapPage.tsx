import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { LayoutGrid, Filter, X, ChevronRight } from "lucide-react";
import { api } from "../lib/api";
import type { SectorHeatmap, MinerviniPassed } from "../lib/types";

// ── period ──────────────────────────────────────────────────────────────────

const PERIODS = [
  { id: "1d", label: "1일" },
  { id: "1w", label: "1주" },
  { id: "1m", label: "1개월" },
  { id: "3m", label: "3개월" },
  { id: "6m", label: "6개월" },
  { id: "12m", label: "12개월" },
] as const;
type PeriodId = (typeof PERIODS)[number]["id"];

// ── color mapping by return ─────────────────────────────────────────────────

interface TileStyle {
  bg: string;
  text: string;
  border: string;
}

function tileStyle(ret: number | null): TileStyle {
  if (ret === null) {
    return { bg: "bg-tint-stone", text: "text-faint", border: "border-hairline" };
  }
  if (ret >= 20)
    return {
      bg: "bg-success",
      text: "text-white",
      border: "border-success",
    };
  if (ret >= 10)
    return {
      bg: "bg-tint-mint",
      text: "text-success",
      border: "border-success/30",
    };
  if (ret >= 0)
    return {
      bg: "bg-success-soft",
      text: "text-success",
      border: "border-success/20",
    };
  if (ret >= -10)
    return {
      bg: "bg-danger-soft",
      text: "text-danger",
      border: "border-danger/20",
    };
  if (ret >= -20)
    return {
      bg: "bg-tint-rose",
      text: "text-danger",
      border: "border-danger/30",
    };
  return {
    bg: "bg-danger",
    text: "text-white",
    border: "border-danger",
  };
}

function fmtPct(v: number | null): string {
  if (v === null) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

// ── components ──────────────────────────────────────────────────────────────

interface SectorTileProps {
  sector: SectorHeatmap;
  selected: boolean;
  onClick: () => void;
}

function SectorTile({ sector, selected, onClick }: SectorTileProps) {
  const style = tileStyle(sector.avg_return_pct);
  return (
    <button
      onClick={onClick}
      className={`${style.bg} ${style.text} ${style.border} ${
        selected ? "ring-2 ring-accent ring-offset-2 ring-offset-cream" : ""
      } rounded-2xl border p-4 flex flex-col gap-1 text-left transition-all hover:shadow-bento active:scale-[0.98]`}
    >
      <span
        className="text-data-xs font-semibold truncate w-full opacity-90"
        title={sector.sector}
      >
        {sector.sector}
      </span>
      <span className="num text-data-lg font-bold leading-none mt-1.5">
        {fmtPct(sector.avg_return_pct)}
      </span>
      <div className="flex items-baseline justify-between text-data-xs opacity-80 mt-1.5">
        <span>
          RS{" "}
          <span className="num font-semibold">
            {sector.avg_rs_rating !== null
              ? Math.round(sector.avg_rs_rating)
              : "—"}
          </span>
        </span>
        <span className="num">
          {sector.minervini_pass_count}/{sector.stock_count}
        </span>
      </div>
    </button>
  );
}

// ── main page ──────────────────────────────────────────────────────────────

const RS_OPTIONS = [0, 40, 60, 70, 80, 90] as const;

export default function HeatmapPage() {
  const navigate = useNavigate();

  const [period, setPeriod] = useState<PeriodId>("1m");
  const [date, setDate] = useState<string>("");
  const [minRs, setMinRs] = useState<number>(0);
  const [mineOnly, setMineOnly] = useState<boolean>(false);
  const [selectedSector, setSelectedSector] = useState<string | null>(null);

  const sectorsQuery = useQuery<SectorHeatmap[]>({
    queryKey: ["heatmap-sectors", date, period],
    queryFn: () => {
      const params = new URLSearchParams({ period });
      if (date) params.set("date_", date);
      return api<SectorHeatmap[]>(`/heatmap/sectors?${params}`);
    },
  });

  const minerviniQuery = useQuery<MinerviniPassed[]>({
    queryKey: ["minervini-passed-all"],
    queryFn: () =>
      api<MinerviniPassed[]>("/indicators/minervini-passed?min_rs=0&limit=500"),
    enabled: selectedSector !== null,
  });

  const sectors: SectorHeatmap[] = (sectorsQuery.data ?? [])
    .filter((s) => {
      if (minRs > 0 && (s.avg_rs_rating === null || s.avg_rs_rating < minRs))
        return false;
      if (mineOnly && s.minervini_pass_rate <= 0) return false;
      return true;
    })
    // sort by return desc (강한 sector 먼저)
    .sort((a, b) => {
      if (a.avg_return_pct === null) return 1;
      if (b.avg_return_pct === null) return -1;
      return b.avg_return_pct - a.avg_return_pct;
    });

  const drilldownStocks: MinerviniPassed[] = (minerviniQuery.data ?? [])
    .filter((it) => it.sector === selectedSector)
    .sort((a, b) => b.rs_rating - a.rs_rating);

  const handleTileClick = (sector: string) => {
    setSelectedSector((prev) => (prev === sector ? null : sector));
  };

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      {/* Header */}
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">Sectors</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            섹터 히트맵
          </h2>
        </div>
        <div className="text-right shrink-0 pl-12">
          <div className="text-data-xs text-muted">
            총 {sectorsQuery.data?.length ?? 0}개 섹터
          </div>
        </div>
      </header>

      {/* Filters */}
      <div className="bento p-5 mb-6">
        <div className="flex items-center gap-2.5 mb-4">
          <div className="p-2 rounded-xl bg-tint-blue">
            <Filter size={16} className="text-accent" strokeWidth={2} />
          </div>
          <div className="text-subhead font-bold text-ink">필터</div>
        </div>

        <div className="flex flex-wrap items-end gap-5">
          {/* Period */}
          <div className="flex flex-col gap-1.5">
            <label className="caps">기간</label>
            <div className="flex rounded-lg border border-hairline overflow-hidden text-data font-semibold bg-cream">
              {PERIODS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setPeriod(p.id)}
                  className={`px-3 py-1.5 transition-colors ${
                    period === p.id
                      ? "bg-accent text-white"
                      : "text-muted hover:text-ink hover:bg-paper"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Date */}
          <div className="flex flex-col gap-1.5">
            <label className="caps">기준일</label>
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                className="border border-hairline rounded-lg px-3 py-1.5 text-data bg-cream focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
              />
              {date && (
                <button
                  onClick={() => setDate("")}
                  className="text-faint hover:text-ink transition-colors"
                  title="초기화"
                >
                  <X size={16} />
                </button>
              )}
            </div>
          </div>

          {/* RS threshold */}
          <div className="flex flex-col gap-1.5">
            <label className="caps">최소 RS</label>
            <div className="flex gap-1.5">
              {RS_OPTIONS.map((v) => (
                <button
                  key={v}
                  onClick={() => setMinRs(v)}
                  className={`px-3 py-1.5 rounded-lg text-data-xs font-semibold transition-colors ${
                    minRs === v
                      ? "bg-accent text-white"
                      : "bg-cream border border-hairline text-muted hover:border-accent hover:text-ink"
                  }`}
                >
                  {v === 0 ? "전체" : `≥${v}`}
                </button>
              ))}
            </div>
          </div>

          {/* Minervini checkbox */}
          <label className="flex items-center gap-2 text-data cursor-pointer pb-1.5">
            <input
              type="checkbox"
              checked={mineOnly}
              onChange={(e) => setMineOnly(e.target.checked)}
              className="w-4 h-4 accent-accent"
            />
            <span className="text-ink font-medium">미너비니 통과만</span>
          </label>
        </div>
      </div>

      {/* Sector grid */}
      <section className="mb-6">
        <div className="flex items-baseline justify-between mb-4">
          <div className="text-subhead font-bold text-ink">
            섹터별 수익률
            <span className="text-data-xs text-muted ml-2 font-normal">
              · {PERIODS.find((p) => p.id === period)?.label}
            </span>
          </div>
          <div className="caps text-faint">
            색상: 수익률 · 빨강 ≤ 회색 ≤ 초록
          </div>
        </div>

        {sectorsQuery.isLoading && (
          <div className="bento p-8 text-center text-muted">로딩 중…</div>
        )}
        {sectorsQuery.isError && (
          <div className="bento p-8 text-center text-danger">
            데이터 불러오기 실패
          </div>
        )}
        {sectorsQuery.isSuccess && sectors.length === 0 && (
          <div className="bento p-8 text-center text-muted">
            조건에 맞는 섹터가 없습니다.
          </div>
        )}
        {sectorsQuery.isSuccess && sectors.length > 0 && (
          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-7 gap-3">
            {sectors.map((s) => (
              <SectorTile
                key={s.sector}
                sector={s}
                selected={selectedSector === s.sector}
                onClick={() => handleTileClick(s.sector)}
              />
            ))}
          </div>
        )}
      </section>

      {/* Drilldown */}
      {selectedSector && (
        <section className="bento p-6">
          <div className="flex items-center gap-2.5 mb-5">
            <div className="p-2 rounded-xl bg-tint-amber">
              <LayoutGrid size={16} className="text-amber" strokeWidth={2} />
            </div>
            <div className="flex-1">
              <div className="text-subhead font-bold text-ink">
                {selectedSector}
              </div>
              <div className="text-data-xs text-muted mt-0.5">
                {drilldownStocks.length}개 종목
              </div>
            </div>
            <button
              onClick={() => setSelectedSector(null)}
              className="text-faint hover:text-ink transition-colors"
            >
              <X size={18} />
            </button>
          </div>

          {minerviniQuery.isLoading && (
            <div className="text-muted py-4">로딩 중…</div>
          )}
          {minerviniQuery.isError && (
            <div className="text-danger py-4">로딩 실패</div>
          )}
          {minerviniQuery.isSuccess && drilldownStocks.length === 0 && (
            <div className="text-muted py-4">
              미너비니 통과 종목이 없습니다.
            </div>
          )}
          {drilldownStocks.length > 0 && (
            <div className="space-y-0.5">
              {drilldownStocks.map((stock) => (
                <button
                  key={stock.ticker}
                  onClick={() => navigate(`/chart/${stock.ticker}`)}
                  className="row-clickable w-full px-3 py-2.5 flex items-center gap-4"
                >
                  <div className="num text-data text-muted w-16 shrink-0 text-left">
                    {stock.ticker}
                  </div>
                  <div className="text-data text-ink flex-1 text-left truncate">
                    {stock.name}
                  </div>
                  <div className="num text-data-md font-semibold text-ink w-12 text-right">
                    {Math.round(stock.rs_rating)}
                  </div>
                  <div className="num text-data text-muted w-24 text-right">
                    ₩{stock.adj_close.toLocaleString()}
                  </div>
                  {stock.pocket_pivot_flag && (
                    <span className="chip bg-success-soft text-success">PP</span>
                  )}
                  <ChevronRight size={16} className="text-faint shrink-0" />
                </button>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
