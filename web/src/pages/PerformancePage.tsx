import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  TrendingUp,
  Award,
  BarChart2,
  Percent,
} from "lucide-react";
import { api } from "../lib/api";
import type { PerformanceSignal } from "../lib/types";
import { Skeleton, SkeletonRow } from "../components/ui/Skeleton";

// ── Types ──────────────────────────────────────────────────────────────────

type Period = "1w" | "2w" | "4w" | "8w";

interface PerformanceStats {
  signal_count: number;
  avg_return_pct: number | null;
  avg_market_return_pct: number | null;
  outperform_pct: number | null;
  win_rate: number | null;
}

// NOTE: 행 타입은 lib/types.ts 의 PerformanceSignal 단일 정의를 사용.
// 과거 이 파일의 로컬 중복 정의가 market_return_*_pct 를 _pct 없이 적어
// 시장 수익률 컬럼이 항상 "—" 로 비어 보이는 계약 불일치를 만들었다.

// ── Helpers ────────────────────────────────────────────────────────────────

const PERIOD_OPTIONS: { value: Period; label: string; apiParam: string }[] = [
  { value: "1w", label: "1주", apiParam: "1w" },
  { value: "2w", label: "2주", apiParam: "2w" },
  { value: "4w", label: "4주", apiParam: "4w" },
  { value: "8w", label: "8주", apiParam: "8w" },
];

function fmtPct(n: number | null | undefined, digits = 2): string {
  if (n == null) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

function pctClass(n: number | null | undefined): string {
  if (n == null) return "text-muted";
  if (n > 0) return "text-success";
  if (n < 0) return "text-danger";
  return "text-muted";
}

function returnCell(n: number | null | undefined) {
  if (n == null) return <span className="text-faint">—</span>;
  return (
    <span className={`num font-semibold ${pctClass(n)}`}>{fmtPct(n)}</span>
  );
}

function returnCellForPeriod(row: PerformanceSignal, period: Period) {
  const key = `return_${period}_pct` as const satisfies keyof PerformanceSignal;
  return returnCell(row[key]);
}

function marketReturnForPeriod(row: PerformanceSignal, period: Period) {
  const key = `market_return_${period}_pct` as const satisfies keyof PerformanceSignal;
  return returnCell(row[key]);
}

// ── Stat Card ──────────────────────────────────────────────────────────────

interface StatCardProps {
  Icon: typeof TrendingUp;
  iconBg: string;
  iconColor: string;
  label: string;
  value: string;
  tone?: "up" | "down" | "neutral";
  loading: boolean;
}

function StatCard({
  Icon,
  iconBg,
  iconColor,
  label,
  value,
  tone = "neutral",
  loading,
}: StatCardProps) {
  const valueClass =
    tone === "up"
      ? "text-success"
      : tone === "down"
      ? "text-danger"
      : "text-ink";

  return (
    <div className="bento p-6">
      <div className="flex items-center justify-between mb-5">
        <div className={`p-2.5 rounded-xl ${iconBg}`}>
          <Icon size={18} className={iconColor} strokeWidth={2} />
        </div>
      </div>
      <div className="text-subhead text-muted font-medium mb-2">{label}</div>
      {loading ? (
        <Skeleton height={40} width="60%" />
      ) : (
        <div className={`num text-data-xl font-bold tracking-tight ${valueClass}`}>
          {value}
        </div>
      )}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function PerformancePage() {
  const navigate = useNavigate();
  const [period, setPeriod] = useState<Period>("2w");

  const statsQ = useQuery<PerformanceStats>({
    queryKey: ["performance-stats", period],
    queryFn: () =>
      api<PerformanceStats>(`/performance/stats?period=${period}`),
  });

  const signalsQ = useQuery<PerformanceSignal[]>({
    queryKey: ["performance-signals"],
    queryFn: () =>
      api<PerformanceSignal[]>("/performance/signals?limit=50"),
  });

  const stats = statsQ.data;
  const signals = signalsQ.data ?? [];

  const outperformTone =
    stats?.outperform_pct != null
      ? stats.outperform_pct > 0
        ? "up"
        : stats.outperform_pct < 0
        ? "down"
        : "neutral"
      : "neutral";

  const avgReturnTone =
    stats?.avg_return_pct != null
      ? stats.avg_return_pct > 0
        ? "up"
        : stats.avg_return_pct < 0
        ? "down"
        : "neutral"
      : "neutral";

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      {/* Header */}
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">Performance</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            시그널 성과
          </h2>
        </div>
        <div className="text-right shrink-0 pl-12">
          {statsQ.isLoading ? (
            <Skeleton height={32} width={60} />
          ) : statsQ.isError ? (
            <div className="text-danger text-data">오류</div>
          ) : (
            <>
              <div className="num text-data-xl font-bold text-ink">
                {stats?.signal_count ?? 0}
              </div>
              <div className="text-data-xs text-muted mt-0.5">
                시그널 ({period})
              </div>
            </>
          )}
        </div>
      </header>

      {/* Period Toggle */}
      <div className="flex items-center gap-2 mb-6">
        <div className="flex items-center gap-1.5 p-1 bg-tint-stone rounded-xl">
          {PERIOD_OPTIONS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setPeriod(value)}
              className={`px-4 py-1.5 rounded-lg text-data-xs font-semibold transition-colors ${
                period === value
                  ? "bg-paper shadow-bento text-ink"
                  : "text-muted hover:text-ink"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="text-data-xs text-faint">통계 기간</span>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5 mb-8">
        <StatCard
          Icon={BarChart2}
          iconBg="bg-tint-stone"
          iconColor="text-muted"
          label="시그널 수"
          value={stats?.signal_count != null ? String(stats.signal_count) : "—"}
          loading={statsQ.isLoading}
        />
        <StatCard
          Icon={TrendingUp}
          iconBg={
            avgReturnTone === "up"
              ? "bg-tint-mint"
              : avgReturnTone === "down"
              ? "bg-rose-50"
              : "bg-tint-stone"
          }
          iconColor={
            avgReturnTone === "up"
              ? "text-success"
              : avgReturnTone === "down"
              ? "text-danger"
              : "text-muted"
          }
          label="평균 수익률"
          value={fmtPct(stats?.avg_return_pct)}
          tone={avgReturnTone}
          loading={statsQ.isLoading}
        />
        <StatCard
          Icon={Award}
          iconBg="bg-tint-blue"
          iconColor="text-accent"
          label="시장 평균 (KOSPI+KOSDAQ)"
          value={fmtPct(stats?.avg_market_return_pct)}
          loading={statsQ.isLoading}
        />
        <StatCard
          Icon={Percent}
          iconBg={
            outperformTone === "up"
              ? "bg-tint-mint"
              : outperformTone === "down"
              ? "bg-rose-50"
              : "bg-tint-stone"
          }
          iconColor={
            outperformTone === "up"
              ? "text-success"
              : outperformTone === "down"
              ? "text-danger"
              : "text-muted"
          }
          label="시장 대비 초과수익"
          value={fmtPct(stats?.outperform_pct)}
          tone={outperformTone}
          loading={statsQ.isLoading}
        />
      </div>

      {/* Win Rate banner */}
      {!statsQ.isLoading && stats?.win_rate != null && (
        <div className="bento bento-tint-blue p-5 mb-8 flex items-center gap-4">
          <div className="p-3 rounded-xl bg-paper">
            <Award size={20} className="text-accent" />
          </div>
          <div>
            <div className="caps text-faint mb-1">Win Rate</div>
            <div className="num text-data-xl font-bold text-ink">
              {(stats.win_rate * 100).toFixed(1)}%
            </div>
          </div>
          <div className="ml-2 text-data-xs text-muted">
            {period} 기준 수익 시그널 비율
          </div>
        </div>
      )}

      {/* Signals Table */}
      <section className="bento p-0 overflow-hidden">
        <div className="flex items-center gap-2.5 p-5 border-b border-hairline">
          <div className="p-2 rounded-xl bg-tint-blue">
            <TrendingUp size={16} className="text-accent" strokeWidth={2} />
          </div>
          <div>
            <div className="text-subhead font-bold text-ink">시그널별 수익률</div>
            <div className="text-data-xs text-muted mt-0.5">최근 50개 시그널</div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-hairline bg-cream/50">
                <th className="caps text-left px-4 py-3 whitespace-nowrap">발생일</th>
                <th className="caps text-left px-4 py-3">종목</th>
                <th className="caps text-right px-4 py-3 whitespace-nowrap">진입가</th>
                <th className="caps text-right px-4 py-3 whitespace-nowrap">1주</th>
                <th className="caps text-right px-4 py-3 whitespace-nowrap">2주</th>
                <th className="caps text-right px-4 py-3 whitespace-nowrap">4주</th>
                <th className="caps text-right px-4 py-3 whitespace-nowrap">8주</th>
                <th className="caps text-right px-4 py-3 whitespace-nowrap text-faint">시장({period})</th>
              </tr>
            </thead>
            <tbody>
              {signalsQ.isLoading && (
                <tr>
                  <td colSpan={8} className="px-4 py-8">
                    <div className="space-y-1">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <SkeletonRow key={i} cols={8} />
                      ))}
                    </div>
                  </td>
                </tr>
              )}
              {signalsQ.isError && (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-danger text-data">
                    데이터를 불러오지 못했습니다.
                  </td>
                </tr>
              )}
              {!signalsQ.isLoading && !signalsQ.isError && signals.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center text-muted text-data">
                    성과 데이터가 없습니다.
                  </td>
                </tr>
              )}
              {signals.map((row) => (
                <tr
                  key={`${row.symbol}-${row.signal_at}`}
                  className="row-clickable border-b border-hairline last:border-b-0"
                  onClick={() => navigate(`/chart/${row.symbol}`)}
                >
                  <td className="px-4 py-3 num text-data-xs text-faint whitespace-nowrap">
                    {row.signal_at.slice(0, 10)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="num text-data text-muted font-medium">
                      {row.symbol}
                    </div>
                    {row.name && (
                      <div className="text-data-xs text-faint mt-0.5 max-w-[120px] truncate">
                        {row.name}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 num text-data text-muted text-right whitespace-nowrap">
                    ₩{row.entry_price.toLocaleString("ko-KR")}
                  </td>
                  <td className="px-4 py-3 text-right text-data">
                    {returnCellForPeriod(row, "1w")}
                  </td>
                  <td className="px-4 py-3 text-right text-data">
                    {returnCellForPeriod(row, "2w")}
                  </td>
                  <td className="px-4 py-3 text-right text-data">
                    {returnCellForPeriod(row, "4w")}
                  </td>
                  <td className="px-4 py-3 text-right text-data">
                    {returnCellForPeriod(row, "8w")}
                  </td>
                  <td className="px-4 py-3 text-right text-data text-faint">
                    {marketReturnForPeriod(row, period)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
