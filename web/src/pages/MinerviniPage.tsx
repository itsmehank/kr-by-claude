import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  CheckCircle2,
  Sparkles,
  ArrowUp,
  ArrowDown,
  Filter,
  PieChart,
} from "lucide-react";
import { api } from "../lib/api";
import type { MinerviniPassed } from "../lib/types";

const RS_OPTIONS = [0, 50, 70, 80, 90] as const;

type SortDir = "asc" | "desc";

function rsTone(rs: number): string {
  if (rs >= 90) return "text-success";
  if (rs >= 80) return "text-success";
  if (rs >= 70) return "text-amber";
  return "text-muted";
}

function formatNumber(n: number): string {
  return n.toLocaleString("ko-KR");
}

export default function MinerviniPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialMinRs = Number(searchParams.get("min_rs") ?? 70);

  const [minRs, setMinRs] = useState<number>(
    RS_OPTIONS.includes(initialMinRs as 0 | 50 | 70 | 80 | 90)
      ? initialMinRs
      : 70
  );
  const [date, setDate] = useState<string>("");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const queryKey = ["minervini-passed", minRs, date];
  const { data, isLoading, isError } = useQuery<MinerviniPassed[]>({
    queryKey,
    queryFn: () => {
      const params = new URLSearchParams({
        min_rs: String(minRs),
        limit: "500",
      });
      if (date) params.set("date", date);
      return api<MinerviniPassed[]>(`/indicators/minervini-passed?${params}`);
    },
  });

  const stocks = data ?? [];

  const sorted = useMemo(() => {
    return [...stocks].sort((a, b) =>
      sortDir === "desc" ? b.rs_rating - a.rs_rating : a.rs_rating - b.rs_rating
    );
  }, [stocks, sortDir]);

  const sectorBreakdown = useMemo(() => {
    const map = new Map<string, number>();
    for (const s of stocks) {
      const key = s.sector ?? "기타";
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10);
  }, [stocks]);

  const maxSectorCount = sectorBreakdown[0]?.[1] ?? 1;
  const total = stocks.length;

  function toggleSort() {
    setSortDir((d) => (d === "desc" ? "asc" : "desc"));
  }

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      {/* Header */}
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">Minervini</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            미너비니 통과 종목
          </h2>
        </div>
        <div className="text-right shrink-0 pl-12">
          {isLoading ? (
            <div className="text-muted">로딩 중…</div>
          ) : isError ? (
            <div className="text-danger">오류</div>
          ) : (
            <>
              <div className="num text-data-xl font-bold text-ink">
                {total.toLocaleString()}
              </div>
              <div className="text-data-xs text-muted mt-0.5">종목 통과</div>
            </>
          )}
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
          <div className="flex flex-col gap-1.5">
            <label className="caps">날짜</label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="border border-hairline rounded-lg px-3 py-1.5 text-data bg-cream focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="caps">최소 RS Rating</label>
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
        </div>
      </div>

      <div className="grid grid-cols-[1fr_280px] gap-6">
        {/* Main Table */}
        <section className="bento p-1 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-hairline">
                <th className="caps text-left px-4 py-3">티커</th>
                <th className="caps text-left px-4 py-3">종목명</th>
                <th className="caps text-left px-4 py-3">섹터</th>
                <th
                  className="caps text-right px-4 py-3 cursor-pointer select-none whitespace-nowrap"
                  onClick={toggleSort}
                >
                  <span className="inline-flex items-center gap-1">
                    RS
                    {sortDir === "desc" ? (
                      <ArrowDown size={11} className="text-accent" />
                    ) : (
                      <ArrowUp size={11} className="text-accent" />
                    )}
                  </span>
                </th>
                <th className="caps text-right px-4 py-3">종가</th>
                <th className="caps text-right px-4 py-3">거래량비</th>
                <th className="caps text-center px-4 py-3">PP</th>
                <th className="caps text-center px-4 py-3 w-20">차트</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-muted">
                    로딩 중…
                  </td>
                </tr>
              )}
              {isError && (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-danger">
                    데이터를 불러오지 못했습니다.
                  </td>
                </tr>
              )}
              {!isLoading && !isError && sorted.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-muted">
                    조건을 통과한 종목이 없습니다.
                  </td>
                </tr>
              )}
              {sorted.map((s) => (
                <tr
                  key={s.ticker}
                  className="row-clickable border-b border-hairline last:border-b-0"
                  onClick={() => navigate(`/chart/${s.ticker}`)}
                >
                  <td className="px-4 py-3 num text-data text-muted">
                    {s.ticker}
                  </td>
                  <td className="px-4 py-3 text-data text-ink font-medium whitespace-nowrap">
                    {s.name}
                  </td>
                  <td
                    className="px-4 py-3 text-data text-muted max-w-[140px] truncate"
                    title={s.sector ?? undefined}
                  >
                    {s.sector ?? "—"}
                  </td>
                  <td
                    className={`px-4 py-3 num text-data-md font-bold text-right ${rsTone(
                      s.rs_rating
                    )}`}
                  >
                    {s.rs_rating}
                  </td>
                  <td className="px-4 py-3 num text-data text-right text-muted">
                    ₩{formatNumber(s.adj_close)}
                  </td>
                  <td className="px-4 py-3 num text-data text-right text-muted">
                    {s.volume_ratio_50d != null
                      ? `${s.volume_ratio_50d.toFixed(2)}x`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {s.pocket_pivot_flag ? (
                      <CheckCircle2
                        size={16}
                        className="inline text-success"
                      />
                    ) : (
                      <span className="text-faint">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className="chip bg-tint-blue text-accent inline-flex">
                      <Sparkles size={11} />
                      열기
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        {/* Sector Breakdown */}
        <aside className="bento p-5 self-start sticky top-10">
          <div className="flex items-center gap-2.5 mb-4">
            <div className="p-2 rounded-xl bg-tint-amber">
              <PieChart size={16} className="text-amber" strokeWidth={2} />
            </div>
            <div>
              <div className="text-subhead font-bold text-ink">섹터 비중</div>
              <div className="text-data-xs text-muted mt-0.5">상위 10개</div>
            </div>
          </div>

          {sectorBreakdown.length === 0 ? (
            <div className="text-muted text-data">데이터 없음</div>
          ) : (
            <div className="space-y-3">
              {sectorBreakdown.map(([sector, count]) => {
                const pct = total > 0 ? ((count / total) * 100).toFixed(0) : "0";
                const barWidth = Math.round((count / maxSectorCount) * 100);
                return (
                  <div key={sector} className="space-y-1">
                    <div className="flex justify-between items-baseline text-data-xs">
                      <span
                        className="text-ink truncate max-w-[160px] font-medium"
                        title={sector}
                      >
                        {sector}
                      </span>
                      <span className="text-muted ml-2 shrink-0 num">
                        {count}
                        <span className="text-faint ml-1">({pct}%)</span>
                      </span>
                    </div>
                    <div className="h-1.5 bg-tint-stone rounded-full overflow-hidden">
                      <div
                        className="h-full bg-accent rounded-full transition-all duration-300"
                        style={{ width: `${barWidth}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
