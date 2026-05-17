import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { TrendingUp, AlertCircle, Activity } from "lucide-react";
import { api } from "../lib/api";
import type { Stock, MinerviniPassed, MarketContext, PipelineRun } from "../lib/types";
import { cn } from "../lib/utils";

// ── Helpers ────────────────────────────────────────────────────────────────

function statusColors(status: string): string {
  if (status === "confirmed_uptrend" || status === "uptrend_under_pressure") {
    return "bg-green-50 text-green-700";
  }
  if (status === "downtrend" || status === "correction") {
    return "bg-red-50 text-red-700";
  }
  return "bg-gray-50 text-gray-700";
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    confirmed_uptrend: "Confirmed Uptrend",
    uptrend_under_pressure: "Uptrend Under Pressure",
    downtrend: "Downtrend",
    correction: "Correction",
  };
  return map[status] ?? status;
}

function runStatusColors(status: string): string {
  if (status === "success") return "text-green-700 bg-green-50";
  if (status === "failed") return "text-red-700 bg-red-50";
  if (status === "running") return "text-blue-700 bg-blue-50";
  return "text-gray-700 bg-gray-50";
}

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "방금 전";
  if (mins < 60) return `${mins}분 전`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  return `${days}일 전`;
}

// ── Sub-components ─────────────────────────────────────────────────────────

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  sub?: string;
}

function StatCard({ icon, label, value, sub }: StatCardProps) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 flex flex-col gap-2 shadow-sm">
      <div className="flex items-center gap-2 text-gray-500 text-sm font-medium">
        {icon}
        {label}
      </div>
      <div className="text-3xl font-bold text-gray-900">{value}</div>
      {sub && <div className="text-xs text-gray-400">{sub}</div>}
    </div>
  );
}

interface MarketCardProps {
  context: MarketContext;
  title: string;
}

function MarketCard({ context, title }: MarketCardProps) {
  const colorClass = statusColors(context.current_status);
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm flex-1">
      <div className="text-sm font-semibold text-gray-500 mb-2">{title}</div>
      <div className={cn("inline-block px-2 py-0.5 rounded text-sm font-medium mb-3", colorClass)}>
        {statusLabel(context.current_status)}
      </div>
      <div className="grid grid-cols-2 gap-y-2 text-sm">
        <span className="text-gray-500">Distribution Days</span>
        <span className="font-semibold text-gray-800">{context.distribution_day_count_last_25_sessions}</span>
        <span className="text-gray-500">Breadth (SMA200)</span>
        <span className="font-semibold text-gray-800">
          {context.pct_stocks_above_200d_ma != null
            ? `${context.pct_stocks_above_200d_ma.toFixed(1)}%`
            : "—"}
        </span>
        <span className="text-gray-500">Follow-through</span>
        <span className="font-semibold text-gray-800">
          {context.last_follow_through_day ?? "—"}
          {context.days_since_follow_through != null && (
            <span className="text-gray-400 text-xs ml-1">({context.days_since_follow_through}d)</span>
          )}
        </span>
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function HomePage() {
  const navigate = useNavigate();

  const stocksQ = useQuery<Stock[]>({
    queryKey: ["snapshot", "stocks"],
    queryFn: () => api<Stock[]>("/stocks?limit=10000"),
  });

  const minerviniQ = useQuery<MinerviniPassed[]>({
    queryKey: ["snapshot", "minervini70"],
    queryFn: () => api<MinerviniPassed[]>("/indicators/minervini-passed?min_rs=70&limit=10000"),
  });

  const minervini80Q = useQuery<MinerviniPassed[]>({
    queryKey: ["snapshot", "minervini80"],
    queryFn: () => api<MinerviniPassed[]>("/indicators/minervini-passed?min_rs=80&limit=10000"),
  });

  const marketQ = useQuery<MarketContext[]>({
    queryKey: ["market-context"],
    queryFn: () => api<MarketContext[]>("/market-context"),
  });

  const topRsQ = useQuery<MinerviniPassed[]>({
    queryKey: ["top-rs"],
    queryFn: () => api<MinerviniPassed[]>("/indicators/minervini-passed?min_rs=70&limit=10"),
  });

  const runsQ = useQuery<PipelineRun[]>({
    queryKey: ["recent-runs"],
    queryFn: () => api<PipelineRun[]>("/runs?limit=10"),
  });

  const kospi = marketQ.data?.find((m) => m.index_code === "1001");
  const kosdaq = marketQ.data?.find((m) => m.index_code === "2001");

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      <h2 className="text-2xl font-bold text-gray-900">홈</h2>

      {/* ── Today's Snapshot ── */}
      <section>
        <h3 className="text-base font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Today's Snapshot
        </h3>
        <div className="grid grid-cols-3 gap-4">
          <StatCard
            icon={<Activity size={15} />}
            label="전체 종목"
            value={stocksQ.isLoading ? "…" : stocksQ.isError ? "오류" : (stocksQ.data?.length ?? 0).toLocaleString()}
            sub="Active stocks"
          />
          <StatCard
            icon={<TrendingUp size={15} />}
            label="미너비니 통과 (RS≥70)"
            value={minerviniQ.isLoading ? "…" : minerviniQ.isError ? "오류" : (minerviniQ.data?.length ?? 0).toLocaleString()}
            sub="Passed today"
          />
          <StatCard
            icon={<TrendingUp size={15} />}
            label="미너비니 통과 (RS≥80)"
            value={minervini80Q.isLoading ? "…" : minervini80Q.isError ? "오류" : (minervini80Q.data?.length ?? 0).toLocaleString()}
            sub="High RS threshold"
          />
        </div>
      </section>

      {/* ── Market Status ── */}
      <section>
        <h3 className="text-base font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Market Status
        </h3>
        {marketQ.isLoading && <div className="text-gray-400">Loading...</div>}
        {marketQ.isError && (
          <div className="flex items-center gap-2 text-red-600 text-sm">
            <AlertCircle size={15} /> Failed to load
          </div>
        )}
        {marketQ.data && (
          <div className="flex gap-4">
            {kospi ? (
              <MarketCard context={kospi} title="KOSPI (1001)" />
            ) : (
              <div className="flex-1 bg-gray-50 border border-gray-200 rounded-xl p-5 text-gray-400 text-sm">
                KOSPI 데이터 없음
              </div>
            )}
            {kosdaq ? (
              <MarketCard context={kosdaq} title="KOSDAQ (2001)" />
            ) : (
              <div className="flex-1 bg-gray-50 border border-gray-200 rounded-xl p-5 text-gray-400 text-sm">
                KOSDAQ 데이터 없음
              </div>
            )}
          </div>
        )}
      </section>

      {/* ── Bottom two tables ── */}
      <div className="grid grid-cols-2 gap-6">
        {/* Top 10 by RS Rating */}
        <section>
          <h3 className="text-base font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Top 10 by RS Rating
          </h3>
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
            {topRsQ.isLoading && (
              <div className="p-4 text-gray-400 text-sm">Loading...</div>
            )}
            {topRsQ.isError && (
              <div className="p-4 text-red-600 text-sm flex items-center gap-2">
                <AlertCircle size={14} /> Failed to load
              </div>
            )}
            {topRsQ.data && topRsQ.data.length === 0 && (
              <div className="p-4 text-gray-400 text-sm">No data</div>
            )}
            {topRsQ.data && topRsQ.data.length > 0 && (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
                  <tr>
                    <th className="px-3 py-2 text-left">#</th>
                    <th className="px-3 py-2 text-left">Ticker</th>
                    <th className="px-3 py-2 text-left">종목명</th>
                    <th className="px-3 py-2 text-right">RS</th>
                    <th className="px-3 py-2 text-right">Close</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {topRsQ.data.map((row, i) => (
                    <tr
                      key={row.ticker}
                      className="hover:bg-blue-50 cursor-pointer transition-colors"
                      onClick={() => navigate(`/chart/${row.ticker}`)}
                    >
                      <td className="px-3 py-2 text-gray-400">{i + 1}</td>
                      <td className="px-3 py-2 font-mono font-semibold text-blue-700">{row.ticker}</td>
                      <td className="px-3 py-2 text-gray-700 truncate max-w-[100px]" title={row.name}>
                        {row.name}
                      </td>
                      <td className="px-3 py-2 text-right font-semibold text-gray-900">{row.rs_rating}</td>
                      <td className="px-3 py-2 text-right text-gray-700">
                        {row.adj_close.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>

        {/* Recent Pipeline Runs */}
        <section>
          <h3 className="text-base font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Recent Pipeline Runs
          </h3>
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
            {runsQ.isLoading && (
              <div className="p-4 text-gray-400 text-sm">Loading...</div>
            )}
            {runsQ.isError && (
              <div className="p-4 text-red-600 text-sm flex items-center gap-2">
                <AlertCircle size={14} /> Failed to load
              </div>
            )}
            {runsQ.data && runsQ.data.length === 0 && (
              <div className="p-4 text-gray-400 text-sm">No data</div>
            )}
            {runsQ.data && runsQ.data.length > 0 && (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
                  <tr>
                    <th className="px-3 py-2 text-left">ID</th>
                    <th className="px-3 py-2 text-left">Pipeline</th>
                    <th className="px-3 py-2 text-left">Status</th>
                    <th className="px-3 py-2 text-right">Rows</th>
                    <th className="px-3 py-2 text-right">Started</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {runsQ.data.map((run) => (
                    <tr key={run.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-3 py-2 text-gray-400 font-mono">{run.id}</td>
                      <td className="px-3 py-2 text-gray-700">
                        <div>{run.pipeline}</div>
                        <div className="text-xs text-gray-400">{run.mode}</div>
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={cn(
                            "inline-block px-2 py-0.5 rounded text-xs font-medium",
                            runStatusColors(run.status)
                          )}
                        >
                          {run.status}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right text-gray-700">
                        {run.rows_affected != null ? run.rows_affected.toLocaleString() : "—"}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-400 text-xs whitespace-nowrap">
                        {relativeTime(run.started_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
