import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { SectorHeatmap, MinerviniPassed } from "../lib/types";

// ── helpers ──────────────────────────────────────────────────────────────────

function tileClasses(avg: number | null): string {
  if (avg === null) return "bg-gray-100 text-gray-500";
  if (avg >= 80) return "bg-green-500 text-white";
  if (avg >= 60) return "bg-green-200 text-green-900";
  if (avg >= 40) return "bg-gray-200 text-gray-700";
  if (avg >= 20) return "bg-red-200 text-red-900";
  return "bg-red-500 text-white";
}

// ── sub-components ────────────────────────────────────────────────────────────

interface SectorTileProps {
  sector: SectorHeatmap;
  selected: boolean;
  onClick: () => void;
}

function SectorTile({ sector, selected, onClick }: SectorTileProps) {
  const base = tileClasses(sector.avg_rs_rating);
  const ring = selected ? "ring-2 ring-offset-1 ring-blue-500" : "";
  return (
    <button
      onClick={onClick}
      className={`${base} ${ring} rounded-lg p-3 flex flex-col gap-1 text-left cursor-pointer hover:opacity-90 transition-opacity`}
    >
      <span className="text-xs font-medium truncate w-full" title={sector.sector}>
        {sector.sector}
      </span>
      <span className="text-2xl font-bold leading-none">
        {sector.avg_rs_rating !== null ? Math.round(sector.avg_rs_rating) : "—"}
      </span>
      <span className="text-xs opacity-80">
        {sector.minervini_pass_count}/{sector.stock_count}
      </span>
    </button>
  );
}

// ── main page ─────────────────────────────────────────────────────────────────

const RS_OPTIONS = [0, 40, 60, 70, 80, 90] as const;

export default function HeatmapPage() {
  const navigate = useNavigate();

  // filter state
  const [date, setDate] = useState<string>("");
  const [minRs, setMinRs] = useState<number>(0);
  const [mineOnly, setMineOnly] = useState<boolean>(false);

  // selected sector for drilldown
  const [selectedSector, setSelectedSector] = useState<string | null>(null);

  // ── query: sectors ──
  const sectorsQuery = useQuery<SectorHeatmap[]>({
    queryKey: ["heatmap-sectors", date],
    queryFn: () => {
      const qs = date ? `?date_=${encodeURIComponent(date)}` : "";
      return api<SectorHeatmap[]>(`/heatmap/sectors${qs}`);
    },
  });

  // ── query: minervini passed (for drilldown) ──
  const minerviniQuery = useQuery<MinerviniPassed[]>({
    queryKey: ["minervini-passed-all"],
    queryFn: () => api<MinerviniPassed[]>("/indicators/minervini-passed?min_rs=0&limit=200"),
    enabled: selectedSector !== null,
  });

  // ── client-side filters on sectors ──
  const sectors: SectorHeatmap[] = (sectorsQuery.data ?? []).filter((s) => {
    if (minRs > 0 && (s.avg_rs_rating === null || s.avg_rs_rating < minRs)) return false;
    if (mineOnly && s.minervini_pass_rate <= 0) return false;
    return true;
  });

  // ── drilldown stocks ──
  const drilldownStocks: MinerviniPassed[] = (minerviniQuery.data ?? []).filter(
    (it) => it.sector === selectedSector
  );

  const handleTileClick = (sector: string) => {
    setSelectedSector((prev) => (prev === sector ? null : sector));
  };

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">섹터 히트맵</h2>

      {/* ── Filters ── */}
      <div className="flex flex-wrap items-end gap-4 bg-gray-50 border rounded-lg p-4">
        {/* Date picker */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600">날짜 (선택)</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
          {date && (
            <button
              onClick={() => setDate("")}
              className="text-xs text-blue-500 hover:underline text-left"
            >
              초기화
            </button>
          )}
        </div>

        {/* RS threshold */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600">최소 RS</label>
          <select
            value={minRs}
            onChange={(e) => setMinRs(Number(e.target.value))}
            className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
          >
            {RS_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {v === 0 ? "전체" : `≥ ${v}`}
              </option>
            ))}
          </select>
        </div>

        {/* Minervini checkbox */}
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={mineOnly}
            onChange={(e) => setMineOnly(e.target.checked)}
            className="w-4 h-4 accent-blue-500"
          />
          미너비니 통과만
        </label>
      </div>

      {/* ── Sector grid ── */}
      {sectorsQuery.isLoading && (
        <p className="text-gray-500 text-sm">불러오는 중…</p>
      )}
      {sectorsQuery.isError && (
        <p className="text-red-500 text-sm">
          데이터를 불러오지 못했습니다: {String(sectorsQuery.error)}
        </p>
      )}
      {sectorsQuery.isSuccess && sectors.length === 0 && (
        <p className="text-gray-500 text-sm">조건에 맞는 섹터가 없습니다.</p>
      )}
      {sectorsQuery.isSuccess && sectors.length > 0 && (
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-7 gap-2">
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

      {/* ── Drilldown ── */}
      {selectedSector && (
        <div className="space-y-3 border-t pt-4">
          <h3 className="text-lg font-semibold">
            {selectedSector} — {drilldownStocks.length}개 종목
          </h3>

          {minerviniQuery.isLoading && (
            <p className="text-gray-500 text-sm">종목 불러오는 중…</p>
          )}
          {minerviniQuery.isError && (
            <p className="text-red-500 text-sm">
              종목 데이터를 불러오지 못했습니다: {String(minerviniQuery.error)}
            </p>
          )}
          {minerviniQuery.isSuccess && drilldownStocks.length === 0 && (
            <p className="text-gray-500 text-sm">미너비니 통과 종목이 없습니다.</p>
          )}
          {minerviniQuery.isSuccess && drilldownStocks.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="bg-gray-100 text-gray-600 text-left">
                    <th className="px-3 py-2 font-medium">티커</th>
                    <th className="px-3 py-2 font-medium">종목명</th>
                    <th className="px-3 py-2 font-medium text-right">RS</th>
                    <th className="px-3 py-2 font-medium text-right">종가</th>
                    <th className="px-3 py-2 font-medium text-center">미너비니</th>
                  </tr>
                </thead>
                <tbody>
                  {drilldownStocks
                    .slice()
                    .sort((a, b) => b.rs_rating - a.rs_rating)
                    .map((stock) => (
                      <tr
                        key={stock.ticker}
                        onClick={() => navigate(`/chart/${stock.ticker}`)}
                        className="border-t hover:bg-blue-50 cursor-pointer transition-colors"
                      >
                        <td className="px-3 py-2 font-mono font-medium text-blue-600">
                          {stock.ticker}
                        </td>
                        <td className="px-3 py-2">{stock.name}</td>
                        <td className="px-3 py-2 text-right font-semibold">
                          {Math.round(stock.rs_rating)}
                        </td>
                        <td className="px-3 py-2 text-right">
                          {stock.adj_close.toLocaleString()}
                        </td>
                        <td className="px-3 py-2 text-center">
                          {stock.pocket_pivot_flag ? "✓" : "—"}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
