import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, BarChart2, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import { api } from "../lib/api";
import type { MinerviniPassed } from "../lib/types";

const RS_OPTIONS = [0, 50, 70, 80, 90] as const;

type SortDir = "asc" | "desc";

function rsColor(rs: number): string {
  if (rs >= 90) return "text-green-600 font-bold";
  if (rs >= 80) return "text-green-500";
  if (rs >= 70) return "text-yellow-500";
  return "text-gray-400";
}

function formatNumber(n: number): string {
  return n.toLocaleString("ko-KR");
}

export default function MinerviniPage() {
  const navigate = useNavigate();
  const [minRs, setMinRs] = useState<number>(70);
  const [date, setDate] = useState<string>("");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const queryKey = ["minervini-passed", minRs, date];
  const { data, isLoading, isError } = useQuery<MinerviniPassed[]>({
    queryKey,
    queryFn: () => {
      const params = new URLSearchParams({ min_rs: String(minRs), limit: "500" });
      if (date) params.set("date", date);
      return api<MinerviniPassed[]>(`/indicators/minervini-passed?${params}`);
    },
  });

  const stocks = data ?? [];

  // Sorted list
  const sorted = useMemo(() => {
    return [...stocks].sort((a, b) =>
      sortDir === "desc" ? b.rs_rating - a.rs_rating : a.rs_rating - b.rs_rating
    );
  }, [stocks, sortDir]);

  // Sector breakdown
  const sectorBreakdown = useMemo(() => {
    const map = new Map<string, number>();
    for (const s of stocks) {
      const key = s.sector ?? "기타";
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return [...map.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10);
  }, [stocks]);

  const maxSectorCount = sectorBreakdown[0]?.[1] ?? 1;
  const total = stocks.length;

  function toggleSort() {
    setSortDir((d) => (d === "desc" ? "asc" : "desc"));
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <BarChart2 className="text-indigo-600" size={24} />
        <h2 className="text-2xl font-bold">미너비니 통과 종목</h2>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-6 bg-gray-50 rounded-xl p-4 border border-gray-200">
        {/* Date */}
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-500">날짜 (선택)</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
        </div>

        {/* RS Slider */}
        <div className="flex flex-col gap-1 min-w-[200px]">
          <label className="text-xs font-medium text-gray-500">
            최소 RS Rating: <span className="text-indigo-600 font-bold">{minRs}</span>
          </label>
          <div className="flex gap-2">
            {RS_OPTIONS.map((v) => (
              <button
                key={v}
                onClick={() => setMinRs(v)}
                className={`px-3 py-1 rounded-lg text-xs font-semibold border transition-colors ${
                  minRs === v
                    ? "bg-indigo-600 text-white border-indigo-600"
                    : "bg-white text-gray-600 border-gray-300 hover:border-indigo-400"
                }`}
              >
                {v}
              </button>
            ))}
          </div>
        </div>

        {/* Stat */}
        <div className="ml-auto text-right">
          {isLoading ? (
            <span className="text-sm text-gray-400">로딩 중...</span>
          ) : isError ? (
            <span className="text-sm text-red-500">데이터 오류</span>
          ) : (
            <div>
              <span className="text-2xl font-bold text-indigo-700">{total}</span>
              <span className="text-sm text-gray-500 ml-1">개 종목</span>
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-col xl:flex-row gap-6">
        {/* Main Table */}
        <div className="flex-1 overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-gray-100 text-gray-600 text-left">
                <th className="px-3 py-2 rounded-tl-lg">티커</th>
                <th className="px-3 py-2">종목명</th>
                <th className="px-3 py-2 max-w-[120px]">섹터</th>
                <th className="px-3 py-2 cursor-pointer select-none whitespace-nowrap" onClick={toggleSort}>
                  <span className="flex items-center gap-1">
                    RS
                    {sortDir === "desc" ? (
                      <ArrowDown size={13} className="text-indigo-500" />
                    ) : (
                      <ArrowUp size={13} className="text-indigo-500" />
                    )}
                    <ArrowUpDown size={11} className="text-gray-400" />
                  </span>
                </th>
                <th className="px-3 py-2 text-right">종가</th>
                <th className="px-3 py-2 text-right">거래량비</th>
                <th className="px-3 py-2 text-center">PP</th>
                <th className="px-3 py-2 rounded-tr-lg text-center">차트</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={8} className="px-3 py-10 text-center text-gray-400">
                    데이터 로딩 중...
                  </td>
                </tr>
              )}
              {isError && (
                <tr>
                  <td colSpan={8} className="px-3 py-10 text-center text-red-500">
                    데이터를 불러오지 못했습니다.
                  </td>
                </tr>
              )}
              {!isLoading && !isError && sorted.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-10 text-center text-gray-400">
                    조건을 통과한 종목이 없습니다.
                  </td>
                </tr>
              )}
              {sorted.map((s, idx) => (
                <tr
                  key={s.ticker}
                  className={`border-b border-gray-100 hover:bg-indigo-50 transition-colors ${
                    idx % 2 === 0 ? "bg-white" : "bg-gray-50/50"
                  }`}
                >
                  <td className="px-3 py-2 font-mono text-xs text-gray-700">{s.ticker}</td>
                  <td className="px-3 py-2 font-medium text-gray-800 whitespace-nowrap">{s.name}</td>
                  <td className="px-3 py-2 text-gray-500 max-w-[120px] truncate" title={s.sector ?? undefined}>
                    {s.sector ?? "—"}
                  </td>
                  <td className={`px-3 py-2 font-mono font-semibold ${rsColor(s.rs_rating)}`}>
                    {s.rs_rating}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-gray-700">
                    {formatNumber(s.adj_close)}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-600">
                    {s.volume_ratio_50d != null ? `${s.volume_ratio_50d.toFixed(2)}x` : "—"}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {s.pocket_pivot_flag ? (
                      <CheckCircle2 size={16} className="inline text-green-500" />
                    ) : (
                      <span className="text-gray-300">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <button
                      onClick={() => navigate(`/chart/${s.ticker}`)}
                      className="px-2.5 py-1 rounded-md bg-indigo-100 text-indigo-700 text-xs font-semibold hover:bg-indigo-200 transition-colors"
                    >
                      차트
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Sector Breakdown */}
        {sectorBreakdown.length > 0 && (
          <div className="xl:w-72 shrink-0">
            <div className="bg-gray-50 rounded-xl border border-gray-200 p-4">
              <h3 className="text-sm font-bold text-gray-700 mb-3">섹터 비중 (Top 10)</h3>
              <div className="space-y-2.5">
                {sectorBreakdown.map(([sector, count]) => {
                  const pct = total > 0 ? ((count / total) * 100).toFixed(0) : "0";
                  const barWidth = Math.round((count / maxSectorCount) * 100);
                  return (
                    <div key={sector} className="space-y-0.5">
                      <div className="flex justify-between text-xs">
                        <span className="text-gray-700 truncate max-w-[160px]" title={sector}>
                          {sector}
                        </span>
                        <span className="text-gray-500 ml-2 shrink-0">
                          {count} ({pct}%)
                        </span>
                      </div>
                      <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-indigo-400 rounded-full transition-all duration-300"
                          style={{ width: `${barWidth}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
