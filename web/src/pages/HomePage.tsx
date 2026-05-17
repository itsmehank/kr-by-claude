import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type {
  Stock,
  MinerviniPassed,
  MarketContext,
  PipelineRun,
} from "../lib/types";

// ── Helpers ────────────────────────────────────────────────────────────────

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    confirmed_uptrend: "Confirmed Uptrend",
    uptrend_under_pressure: "Uptrend, Under Pressure",
    downtrend: "Downtrend",
    correction: "Correction",
    rally_attempt: "Rally Attempt",
  };
  return map[status] ?? status;
}

function statusTone(status: string): "up" | "down" | "neutral" {
  if (status === "confirmed_uptrend" || status === "rally_attempt") return "up";
  if (status === "downtrend" || status === "correction") return "down";
  return "neutral";
}

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function todayParts() {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const weekday = d.toLocaleDateString("en-US", { weekday: "long" });
  return { yyyy, mm, dd, weekday };
}

// ── Sub-components ─────────────────────────────────────────────────────────

interface SnapshotCellProps {
  value: number | null | undefined;
  loading: boolean;
  error: boolean;
  label: string;
  emphasis?: boolean;
}

function SnapshotCell({
  value,
  loading,
  error,
  label,
  emphasis,
}: SnapshotCellProps) {
  let display: string;
  if (loading) display = "—";
  else if (error) display = "err";
  else display = (value ?? 0).toLocaleString();
  return (
    <div className="px-10 py-8">
      <div
        className={[
          "num text-data-xl tracking-tight",
          emphasis ? "text-accent" : "text-ink",
        ].join(" ")}
      >
        {display}
      </div>
      <div className="caps mt-3">{label}</div>
    </div>
  );
}

interface MarketCellProps {
  context: MarketContext | undefined;
  title: string;
  code: string;
}

function MarketCell({ context, title, code }: MarketCellProps) {
  if (!context) {
    return (
      <div className="px-10 py-8 bg-paper/40">
        <div className="flex items-baseline justify-between mb-6">
          <div>
            <div className="font-display text-display-md leading-none">{title}</div>
            <div className="caps text-faint mt-2">Index · {code}</div>
          </div>
        </div>
        <div className="text-data text-faint italic font-display">
          No data available
        </div>
      </div>
    );
  }

  const tone = statusTone(context.current_status);
  const arrow = tone === "up" ? "↗" : tone === "down" ? "↘" : "→";
  const statusColor =
    tone === "down"
      ? "text-accent"
      : tone === "up"
      ? "text-success"
      : "text-muted";

  return (
    <div className="px-10 py-8 bg-paper/40">
      <div className="flex items-baseline justify-between mb-1">
        <div className="font-display text-display-md leading-none">{title}</div>
        <div className={["num text-data-lg", statusColor].join(" ")}>
          {arrow}
        </div>
      </div>
      <div className="caps text-faint mb-6">Index · {code}</div>

      <div
        className={[
          "font-display italic text-headline mb-8 border-l-2 pl-3",
          tone === "down"
            ? "text-accent border-accent"
            : tone === "up"
            ? "text-ink border-success"
            : "text-muted border-hairline",
        ].join(" ")}
      >
        {statusLabel(context.current_status)}
      </div>

      <dl className="grid grid-cols-[1fr_auto] gap-y-3 items-baseline">
        <dt className="caps">Distribution Days · 25d</dt>
        <dd className="num text-data-md">
          {context.distribution_day_count_last_25_sessions ?? "—"}
        </dd>

        <dt className="caps">Breadth · &gt; SMA-200</dt>
        <dd className="num text-data-md">
          {context.pct_stocks_above_200d_ma != null
            ? `${context.pct_stocks_above_200d_ma.toFixed(1)}%`
            : "—"}
        </dd>

        <dt className="caps">Last Follow-through</dt>
        <dd className="num text-data">
          {context.last_follow_through_day ?? "—"}
          {context.days_since_follow_through != null && (
            <span className="text-faint ml-2">
              {context.days_since_follow_through}d
            </span>
          )}
        </dd>
      </dl>
    </div>
  );
}

interface RunStatusProps {
  status: string;
}
function RunStatus({ status }: RunStatusProps) {
  if (status === "success") {
    return (
      <span className="caps text-success inline-flex items-center gap-1.5">
        <span className="text-data">✓</span>
        success
      </span>
    );
  }
  if (status === "failed" || status === "error") {
    return (
      <span className="caps text-accent inline-flex items-center gap-1.5">
        <span className="text-data">✗</span>
        {status}
      </span>
    );
  }
  if (status === "running") {
    return (
      <span className="caps text-warning inline-flex items-center gap-1.5">
        <span className="text-data animate-pulse">●</span>
        running
      </span>
    );
  }
  return <span className="caps text-muted">{status}</span>;
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function HomePage() {
  const navigate = useNavigate();
  const { yyyy, mm, dd, weekday } = todayParts();

  const stocksQ = useQuery<Stock[]>({
    queryKey: ["snapshot", "stocks"],
    queryFn: () => api<Stock[]>("/stocks?limit=10000"),
  });
  const minerviniQ = useQuery<MinerviniPassed[]>({
    queryKey: ["snapshot", "minervini70"],
    queryFn: () =>
      api<MinerviniPassed[]>("/indicators/minervini-passed?min_rs=70&limit=10000"),
  });
  const minervini80Q = useQuery<MinerviniPassed[]>({
    queryKey: ["snapshot", "minervini80"],
    queryFn: () =>
      api<MinerviniPassed[]>("/indicators/minervini-passed?min_rs=80&limit=10000"),
  });
  const marketQ = useQuery<MarketContext[]>({
    queryKey: ["market-context"],
    queryFn: () => api<MarketContext[]>("/market-context"),
  });
  const topRsQ = useQuery<MinerviniPassed[]>({
    queryKey: ["top-rs"],
    queryFn: () =>
      api<MinerviniPassed[]>("/indicators/minervini-passed?min_rs=70&limit=10"),
  });
  const runsQ = useQuery<PipelineRun[]>({
    queryKey: ["recent-runs"],
    queryFn: () => api<PipelineRun[]>("/runs?limit=8"),
  });

  const kospi = marketQ.data?.find((m) => m.index_code === "1001");
  const kosdaq = marketQ.data?.find((m) => m.index_code === "2001");

  return (
    <div className="px-16 py-12 max-w-[1140px] mx-auto">
      {/* ── Masthead ───────────────────────────────────────────────────── */}
      <header className="flex items-end justify-between pb-8 mb-16 border-b border-hairline">
        <div>
          <div className="caps text-faint mb-4">
            No. 001 · Daily Brief
          </div>
          <h2 className="display text-display-xl leading-[0.95] tracking-tight">
            Today's
            <br />
            Overview
            <span className="italic font-light text-accent">.</span>
          </h2>
        </div>
        <div className="text-right shrink-0 pl-12">
          <div className="caps text-faint">Date</div>
          <div className="num text-data-md mt-1.5">
            {yyyy} · {mm} · {dd}
          </div>
          <div className="caps text-faint mt-5">Weekday</div>
          <div className="font-display italic text-data-md mt-1">
            {weekday}
          </div>
        </div>
      </header>

      {/* ── Today's Snapshot ──────────────────────────────────────────── */}
      <section className="mb-20">
        <div className="flex items-baseline justify-between mb-5">
          <div className="caps">Today's Snapshot</div>
          <div className="caps text-faint">3 metrics</div>
        </div>
        <div className="grid grid-cols-3 border-y border-hairline divide-x divide-hairline">
          <SnapshotCell
            value={stocksQ.data?.length}
            loading={stocksQ.isLoading}
            error={stocksQ.isError}
            label="Active stocks · 활성 종목"
          />
          <SnapshotCell
            value={minerviniQ.data?.length}
            loading={minerviniQ.isLoading}
            error={minerviniQ.isError}
            label="Minervini pass · RS ≥ 70"
          />
          <SnapshotCell
            value={minervini80Q.data?.length}
            loading={minervini80Q.isLoading}
            error={minervini80Q.isError}
            label="High RS · ≥ 80"
            emphasis
          />
        </div>
      </section>

      {/* ── Market Context ────────────────────────────────────────────── */}
      <section className="mb-20">
        <div className="flex items-baseline justify-between mb-5">
          <div className="caps">Market Context</div>
          <div className="caps text-faint">Korea · KOSPI · KOSDAQ</div>
        </div>
        {marketQ.isLoading && (
          <div className="border border-hairline px-10 py-8 text-faint italic font-display">
            Loading market data…
          </div>
        )}
        {marketQ.isError && (
          <div className="border border-hairline px-10 py-8 text-accent font-display italic">
            Failed to load market context.
          </div>
        )}
        {marketQ.data && (
          <div className="grid grid-cols-2 border border-hairline divide-x divide-hairline">
            <MarketCell context={kospi} title="KOSPI" code="1001" />
            <MarketCell context={kosdaq} title="KOSDAQ" code="2001" />
          </div>
        )}
      </section>

      {/* ── Bottom row ───────────────────────────────────────────────── */}
      <div className="grid grid-cols-[7fr_5fr] gap-12">
        {/* Top RS */}
        <section>
          <div className="flex items-baseline justify-between mb-5">
            <div className="caps">Top Ten · RS Rating</div>
            <div className="caps text-faint">Minervini ✓</div>
          </div>
          {topRsQ.isLoading && (
            <div className="text-faint italic font-display">Loading…</div>
          )}
          {topRsQ.isError && (
            <div className="text-accent italic font-display">
              Failed to load.
            </div>
          )}
          {topRsQ.data && topRsQ.data.length === 0 && (
            <div className="text-faint italic font-display">
              No qualifying stocks today.
            </div>
          )}
          {topRsQ.data && topRsQ.data.length > 0 && (
            <table className="w-full">
              <thead>
                <tr className="border-y border-hairline">
                  <th className="caps text-left py-2.5 w-8">№</th>
                  <th className="caps text-left py-2.5">Ticker</th>
                  <th className="caps text-left py-2.5">종목명</th>
                  <th className="caps text-right py-2.5">RS</th>
                  <th className="caps text-right py-2.5">Close</th>
                </tr>
              </thead>
              <tbody>
                {topRsQ.data.map((row, i) => (
                  <tr
                    key={row.ticker}
                    className="row-clickable border-b border-hairline last:border-b-0"
                    onClick={() => navigate(`/chart/${row.ticker}`)}
                  >
                    <td className="py-3 num text-data-xs text-faint">
                      {String(i + 1).padStart(2, "0")}
                    </td>
                    <td className="py-3 num text-data">{row.ticker}</td>
                    <td
                      className="py-3 text-data truncate max-w-[140px]"
                      title={row.name}
                    >
                      {row.name}
                    </td>
                    <td className="py-3 num text-data text-right font-medium">
                      {row.rs_rating}
                    </td>
                    <td className="py-3 num text-data text-right text-muted">
                      {row.adj_close.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {/* Recent Runs */}
        <section>
          <div className="flex items-baseline justify-between mb-5">
            <div className="caps">Pipeline Runs</div>
            <div className="caps text-faint">latest 8</div>
          </div>
          {runsQ.isLoading && (
            <div className="text-faint italic font-display">Loading…</div>
          )}
          {runsQ.isError && (
            <div className="text-accent italic font-display">Failed to load.</div>
          )}
          {runsQ.data && runsQ.data.length === 0 && (
            <div className="text-faint italic font-display">No recent runs.</div>
          )}
          {runsQ.data && runsQ.data.length > 0 && (
            <table className="w-full">
              <thead>
                <tr className="border-y border-hairline">
                  <th className="caps text-left py-2.5 w-8">ID</th>
                  <th className="caps text-left py-2.5">Pipeline</th>
                  <th className="caps text-left py-2.5">Status</th>
                  <th className="caps text-right py-2.5">Rows</th>
                </tr>
              </thead>
              <tbody>
                {runsQ.data.map((run) => (
                  <tr
                    key={run.id}
                    className="border-b border-hairline last:border-b-0"
                  >
                    <td className="py-3 num text-data-xs text-faint">
                      {run.id}
                    </td>
                    <td className="py-3">
                      <div className="text-data">{run.pipeline}</div>
                      <div className="caps text-faint mt-0.5">
                        {run.mode} · {relativeTime(run.started_at)}
                      </div>
                    </td>
                    <td className="py-3">
                      <RunStatus status={run.status} />
                    </td>
                    <td className="py-3 num text-data text-right text-muted">
                      {run.rows_affected != null
                        ? run.rows_affected.toLocaleString()
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      {/* ── Footer rule ──────────────────────────────────────────────── */}
      <footer className="mt-24 pt-6 border-t border-hairline flex justify-between items-baseline">
        <div className="caps text-faint">
          kr-by-claude · Korean equities daily brief
        </div>
        <div className="caps text-faint">
          {yyyy}.{mm}.{dd} ·{" "}
          <span className="font-display italic">vol I</span>
        </div>
      </footer>
    </div>
  );
}
