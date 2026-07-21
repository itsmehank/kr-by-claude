import { useEffect, useMemo, useState } from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  LayoutGrid,
  LineChart,
  Sparkles,
  FileArchive,
  Zap,
  Briefcase,
  TrendingUp,
  Wrench,
  ListChecks,
  BookOpen,
  Library,
  Activity,
  ShieldCheck,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import HomePage from "./pages/HomePage";
import HeatmapPage from "./pages/HeatmapPage";
import ChartPage from "./pages/ChartPage";
import MinerviniPage from "./pages/MinerviniPage";
import PromptPage from "./pages/PromptPage";
import SignalsPage from "./pages/SignalsPage";
import PositionsPage from "./pages/PositionsPage";
import PerformancePage from "./pages/PerformancePage";
import RunnerPage from "./pages/RunnerPage";
import ClassificationsPage from "./pages/ClassificationsPage";
import TriggersPage from "./pages/TriggersPage";
import LlmPipelinePage from "./pages/LlmPipelinePage";
import LlmPipelineAuditPage from "./pages/LlmPipelineAuditPage";
import PipelinePage from "./pages/PipelinePage";
import LibraryPage from "./pages/LibraryPage";
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
  // ─── 조회 도구 ───────────────────────────────
  { to: "/", label: "Overview", kr: "총괄", Icon: LayoutDashboard },
  { to: "/heatmap", label: "Sectors", kr: "섹터 히트맵", Icon: LayoutGrid },
  { to: "/chart", label: "Chart", kr: "차트", Icon: LineChart },

  // ─── 분석 파이프라인 (단계 순) ───────────────
  { to: "/minervini", label: "Minervini", kr: "미너비니", Icon: Sparkles },
  { to: "/classifications", label: "Classifications", kr: "LLM 분류", Icon: ListChecks },
  { to: "/triggers", label: "Triggers", kr: "트리거 이력", Icon: Activity },
  { to: "/signals", label: "Signals", kr: "시그널", Icon: Zap },
  { to: "/positions", label: "Positions", kr: "포지션", Icon: Briefcase },
  { to: "/performance", label: "Performance", kr: "시그널 성과", Icon: TrendingUp },

  // ─── 메타 문서 / 운영 ──────────────────────
  { to: "/library", label: "Library", kr: "자료실", Icon: Library },
  { to: "/docs/llm-pipeline", label: "LLM Pipeline Guide", kr: "LLM 분석 안내", Icon: BookOpen },
  { to: "/docs/llm-pipeline/audit", label: "LLM Audit", kr: "LLM 분석 검증", Icon: ShieldCheck },
  { to: "/prompt", label: "LLM Prompt", kr: "LLM 프롬프트", Icon: FileArchive },
  { to: "/runner", label: "Runner", kr: "분석 운영", Icon: Wrench },
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

const SIDEBAR_COLLAPSED_KEY = "kr-by-claude.sidebar-collapsed";

function useSidebarCollapsed() {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  });
  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
  }, [collapsed]);
  return [collapsed, setCollapsed] as const;
}

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
  const [collapsed, setCollapsed] = useSidebarCollapsed();

  return (
    <div className="min-h-screen flex bg-cream">
      <aside
        className={`${
          collapsed ? "w-[68px]" : "w-[244px]"
        } shrink-0 flex flex-col bg-cream border-r border-hairline transition-[width] duration-200 ease-out`}
      >
        <div
          className={`flex items-start gap-2 ${
            collapsed ? "px-3 pt-6 pb-6 justify-center" : "px-6 pt-8 pb-8"
          }`}
        >
          {!collapsed && (
            <div className="flex-1 min-w-0">
              <h1 className="font-display text-display-md font-bold tracking-tight leading-none">
                kr-by-claude
              </h1>
              <div className="text-data-xs text-muted mt-2 leading-relaxed">
                Korean equities · v0.1
              </div>
            </div>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            className="p-1.5 rounded-lg text-faint hover:text-ink hover:bg-paper/60 transition-colors shrink-0"
            aria-label={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
            title={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
          >
            {collapsed ? (
              <PanelLeftOpen size={18} strokeWidth={1.75} />
            ) : (
              <PanelLeftClose size={18} strokeWidth={1.75} />
            )}
          </button>
        </div>

        <nav className={`${collapsed ? "px-2" : "px-3"} flex-1 space-y-1`}>
          {NAV_ITEMS.map(({ to, label, kr, Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              title={collapsed ? `${kr} · ${label}` : undefined}
              className={({ isActive }) =>
                [
                  "group relative flex items-center rounded-xl transition-all",
                  collapsed ? "justify-center px-2 py-2.5" : "gap-3 px-3 py-2.5",
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
                  {!collapsed && (
                    <div className="flex-1 min-w-0">
                      <div className="text-subhead font-semibold leading-tight">
                        {kr}
                      </div>
                      <div className="text-data-xs text-faint mt-0.5">
                        {label}
                      </div>
                    </div>
                  )}
                  {collapsed && (
                    <span className="pointer-events-none absolute left-full ml-2 z-50 whitespace-nowrap rounded-lg bg-ink text-paper text-data-xs px-2.5 py-1.5 opacity-0 group-hover:opacity-100 transition-opacity shadow-bento">
                      <span className="font-semibold">{kr}</span>
                      <span className="text-faint ml-1.5">{label}</span>
                    </span>
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {!collapsed && <SystemStatus />}

        {!collapsed && (
          <div className="px-6 py-4 border-t border-hairline">
            <div className="caps text-faint">Methodology</div>
            <div className="mt-1.5 text-data-xs text-muted leading-relaxed">
              Minervini Trend Template · O'Neil CAN SLIM
            </div>
          </div>
        )}
      </aside>

      <main className="flex-1 overflow-x-hidden">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/heatmap" element={<HeatmapPage />} />
          <Route path="/chart" element={<ChartPage />} />
          <Route path="/chart/:ticker" element={<ChartPage />} />
          <Route path="/minervini" element={<MinerviniPage />} />
          <Route path="/signals" element={<SignalsPage />} />
          <Route path="/positions" element={<PositionsPage />} />
          <Route path="/performance" element={<PerformancePage />} />
          <Route path="/classifications" element={<ClassificationsPage />} />
          <Route path="/triggers" element={<TriggersPage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/docs/llm-pipeline" element={<LlmPipelinePage />} />
          <Route path="/docs/llm-pipeline/audit" element={<LlmPipelineAuditPage />} />
          <Route path="/runner" element={<RunnerPage />} />
          <Route path="/runner/:pipelineId" element={<PipelinePage />} />
          <Route path="/prompt" element={<PromptPage />} />
          <Route path="/prompt/:ticker" element={<PromptPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
