import { Routes, Route, NavLink } from "react-router-dom";
import HomePage from "./pages/HomePage";
import HeatmapPage from "./pages/HeatmapPage";
import ChartPage from "./pages/ChartPage";
import MinerviniPage from "./pages/MinerviniPage";
import PromptPage from "./pages/PromptPage";

interface NavItem {
  to: string;
  label: string;
  kr: string;
  index: string;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", kr: "총괄", index: "01" },
  { to: "/heatmap", label: "Sectors", kr: "섹터 히트맵", index: "02" },
  { to: "/chart", label: "Chart", kr: "차트", index: "03" },
  { to: "/minervini", label: "Minervini", kr: "미너비니", index: "04" },
  { to: "/prompt", label: "LLM Prompt", kr: "LLM 프롬프트", index: "05" },
];

function App() {
  return (
    <div className="min-h-screen flex bg-cream">
      <aside className="w-[240px] shrink-0 border-r border-hairline flex flex-col">
        <div className="px-6 pt-8 pb-10">
          <h1 className="display text-display-md tracking-tight leading-none">
            kr-by-claude
          </h1>
          <div className="caps text-faint mt-2">
            korean equities · v0.1
          </div>
        </div>

        <nav className="px-3 flex-1 space-y-0.5">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                [
                  "group block px-3 py-2.5 rounded-md transition-colors",
                  isActive
                    ? "bg-accent-soft text-ink"
                    : "text-muted hover:text-ink hover:bg-paper",
                ].join(" ")
              }
            >
              {({ isActive }) => (
                <div className="flex items-baseline gap-3">
                  <span
                    className={[
                      "num text-data-xs",
                      isActive ? "text-accent" : "text-faint",
                    ].join(" ")}
                  >
                    {item.index}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-subhead font-semibold leading-tight">
                      {item.kr}
                    </div>
                    <div className="caps text-data-xs mt-0.5 text-faint group-hover:text-muted">
                      {item.label}
                    </div>
                  </div>
                </div>
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
