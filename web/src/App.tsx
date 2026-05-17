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
      <aside className="w-[260px] shrink-0 border-r border-hairline flex flex-col">
        <div className="px-8 pt-10 pb-12">
          <div className="caps text-faint mb-2">est. 2026</div>
          <h1 className="display text-display-md leading-none">
            kr<span className="italic font-light text-accent">·</span>by
            <span className="italic font-light text-accent">·</span>claude
          </h1>
          <div className="mt-2 text-data-xs text-muted font-mono">
            Korean equities · Minervini methodology
          </div>
        </div>

        <nav className="px-8 flex-1 space-y-px">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                [
                  "group block py-3 border-b border-hairline transition-colors",
                  isActive ? "text-ink" : "text-muted hover:text-ink",
                ].join(" ")
              }
            >
              {({ isActive }) => (
                <div className="flex items-baseline gap-3">
                  <span
                    className={[
                      "font-mono text-data-xs tabular-nums",
                      isActive ? "text-accent" : "text-faint",
                    ].join(" ")}
                  >
                    {item.index}
                  </span>
                  <div className="flex-1">
                    <div className="font-display text-headline leading-tight">
                      {item.kr}
                    </div>
                    <div className="caps text-data-xs mt-0.5 text-faint">
                      {item.label}
                    </div>
                  </div>
                  {isActive && (
                    <span className="text-accent font-display italic text-data-lg leading-none">
                      §
                    </span>
                  )}
                </div>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="px-8 py-6 border-t border-hairline">
          <div className="caps text-faint">colophon</div>
          <div className="mt-2 text-data-xs text-muted leading-relaxed">
            Pretendard · Cormorant Garamond · JetBrains Mono
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
