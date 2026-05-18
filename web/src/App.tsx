import { useMemo } from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  LayoutGrid,
  LineChart,
  Sparkles,
  FileArchive,
  Zap,
  TrendingUp,
  Wrench,
} from "lucide-react";
import HomePage from "./pages/HomePage";
import HeatmapPage from "./pages/HeatmapPage";
import ChartPage from "./pages/ChartPage";
import MinerviniPage from "./pages/MinerviniPage";
import PromptPage from "./pages/PromptPage";
import SignalsPage from "./pages/SignalsPage";
import PerformancePage from "./pages/PerformancePage";
import RunnerPage from "./pages/RunnerPage";
import { api } from "./lib/api";
import type { PipelineRun } from "./lib/types";
import { relativeTime, stalenessLevel } from "./lib/utils";

interface NavItem {
  to: string;
  label: string;
  kr: string;
  Icon: typeof LayoutDashboard;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", kr: "총괄", Icon: LayoutDashboard },
  { to: "/heatmap", label: "Sectors", kr: "섹터 히트맵", Icon: LayoutGrid },
  { to: "/chart", label: "Chart", kr: "차트", Icon: LineChart },
  { to: "/minervini", label: "Minervini", kr: "미너비니", Icon: Sparkles },
  { to: "/signals", label: "Signals", kr: "시그널", Icon: Zap },
  { to: "/performance", label: "Performance", kr: "시그널 성과", Icon: TrendingUp },
  { to: "/runner", label: "Runner", kr: "분석 운영", Icon: Wrench },
  { to: "/prompt", label: "LLM Prompt", kr: "LLM 프롬프트", Icon: FileArchive },
];

const PIPELINE_LABELS: Record<string, string> = {
  ohlcv: "OHLCV",
  weekly: "Weekly",
  indicators_daily: "Indicators (D)",
  indicators_weekly: "Indicators (W)",
  market_context: "Market Ctx",
  corporate_actions: "Corp Actions",
  universe: "Universe",
};

function SystemStatus() {
  const runsQ = useQuery<PipelineRun[]>({
    queryKey: ["system-status-runs"],
    queryFn: () => api<PipelineRun[]>("/runs?limit=50"),
    staleTime: 60_000,
  });

  const latestByPipeline = useMemo(() => {
    if (!runsQ.data) return [];
    const map = new Map<string, PipelineRun>();
    for (const r of runsQ.data) {
      if (!map.has(r.pipeline)) map.set(r.pipeline, r);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [runsQ.data]);

  if (runsQ.isLoading)
    return (
      <div className="px-6 py-4 border-t border-hairline">
        <div className="caps text-faint">시스템 상태</div>
        <div className="text-data-xs text-faint mt-2">로딩 중…</div>
      </div>
    );
  if (latestByPipeline.length === 0) return null;

  return (
    <div className="px-6 py-4 border-t border-hairline">
      <div className="caps text-faint mb-2">시스템 상태</div>
      <div className="space-y-1.5 text-data-xs">
        {latestByPipeline.map(([pipeline, run]) => {
          const ts = run.finished_at ?? run.started_at;
          const level = stalenessLevel(ts);
          const dotClass =
            level === "fresh"
              ? "bg-success"
              : level === "stale"
              ? "bg-warning"
              : "bg-danger";
          return (
            <div
              key={pipeline}
              className="flex items-baseline justify-between gap-2"
            >
              <span className="text-muted truncate flex items-center gap-1.5 min-w-0">
                <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${dotClass}`} />
                <span className="truncate">
                  {PIPELINE_LABELS[pipeline] ?? pipeline}
                </span>
              </span>
              <span className="num text-faint shrink-0">
                {relativeTime(ts)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function App() {
  return (
    <div className="min-h-screen flex bg-cream">
      <aside className="w-[244px] shrink-0 flex flex-col bg-cream border-r border-hairline">
        <div className="px-6 pt-8 pb-8">
          <h1 className="font-display text-display-md font-bold tracking-tight leading-none">
            kr-by-claude
          </h1>
          <div className="text-data-xs text-muted mt-2 leading-relaxed">
            Korean equities · v0.1
          </div>
        </div>

        <nav className="px-3 flex-1 space-y-1">
          {NAV_ITEMS.map(({ to, label, kr, Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                [
                  "group flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all",
                  isActive
                    ? "bg-paper shadow-bento text-ink"
                    : "text-muted hover:bg-paper/60 hover:text-ink",
                ].join(" ")
              }
            >
              {({ isActive }) => (
                <>
                  <Icon
                    size={18}
                    className={isActive ? "text-accent" : "text-faint"}
                    strokeWidth={1.75}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-subhead font-semibold leading-tight">
                      {kr}
                    </div>
                    <div className="text-data-xs text-faint mt-0.5">
                      {label}
                    </div>
                  </div>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <SystemStatus />

        <div className="px-6 py-4 border-t border-hairline">
          <div className="caps text-faint">Methodology</div>
          <div className="mt-1.5 text-data-xs text-muted leading-relaxed">
            Minervini Trend Template · O'Neil CAN SLIM
          </div>
        </div>
      </aside>

      <main className="flex-1 overflow-x-hidden">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/heatmap" element={<HeatmapPage />} />
          <Route path="/chart" element={<ChartPage />} />
          <Route path="/chart/:ticker" element={<ChartPage />} />
          <Route path="/minervini" element={<MinerviniPage />} />
          <Route path="/signals" element={<SignalsPage />} />
          <Route path="/performance" element={<PerformancePage />} />
          <Route path="/runner" element={<RunnerPage />} />
          <Route path="/prompt" element={<PromptPage />} />
          <Route path="/prompt/:ticker" element={<PromptPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
