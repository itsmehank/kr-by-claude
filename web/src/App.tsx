import { Routes, Route, Link } from "react-router-dom";
import HomePage from "./pages/HomePage";
import HeatmapPage from "./pages/HeatmapPage";
import ChartPage from "./pages/ChartPage";
import MinerviniPage from "./pages/MinerviniPage";
import PromptPage from "./pages/PromptPage";

function App() {
  return (
    <div className="min-h-screen flex">
      <nav className="w-48 border-r p-4 space-y-2 bg-gray-50">
        <h1 className="font-bold mb-4">kr-by-claude</h1>
        <Link className="block" to="/">홈</Link>
        <Link className="block" to="/heatmap">히트맵</Link>
        <Link className="block" to="/chart">차트</Link>
        <Link className="block" to="/minervini">미너비니</Link>
        <Link className="block" to="/prompt">LLM 프롬프트</Link>
      </nav>
      <main className="flex-1 p-6">
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
