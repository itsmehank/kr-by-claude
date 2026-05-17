import { Routes, Route, NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  LayoutGrid,
  LineChart,
  Sparkles,
  FileArchive,
} from "lucide-react";
import HomePage from "./pages/HomePage";
import HeatmapPage from "./pages/HeatmapPage";
import ChartPage from "./pages/ChartPage";
import MinerviniPage from "./pages/MinerviniPage";
import PromptPage from "./pages/PromptPage";

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
  { to: "/prompt", label: "LLM Prompt", kr: "LLM 프롬프트", Icon: FileArchive },
];

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

        <div className="px-6 py-5 border-t border-hairline">
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
          <Route path="/prompt" element={<PromptPage />} />
          <Route path="/prompt/:ticker" element={<PromptPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
