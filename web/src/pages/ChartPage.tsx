import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, TrendingUp } from "lucide-react";
import { api, apiUrl } from "../lib/api";
import type { DailyIndicator, Stock, MinerviniPassed } from "../lib/types";
import { PriceChart } from "../components/charts/PriceChart";

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

function startStr(): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 1);
  return d.toISOString().slice(0, 10);
}

export default function ChartPage() {
  const { ticker } = useParams<{ ticker?: string }>();
  const navigate = useNavigate();

  const [inputTicker, setInputTicker] = useState("");
  const [showSMA10, setShowSMA10] = useState(false);
  const [showSMA50, setShowSMA50] = useState(true);
  const [showSMA150, setShowSMA150] = useState(true);
  const [showSMA200, setShowSMA200] = useState(true);
  const [show52wHigh, setShow52wHigh] = useState(true);
  const [show52wLow, setShow52wLow] = useState(true);
  const [showPocketPivot, setShowPocketPivot] = useState(false);
  const [showDistributionDay, setShowDistributionDay] = useState(false);

  // Quick-select list from minervini-passed
  const { data: quickList } = useQuery<MinerviniPassed[]>({
    queryKey: ["minervini-passed-chart-select"],
    queryFn: () => api<MinerviniPassed[]>("/indicators/minervini-passed?limit=20"),
    staleTime: 5 * 60 * 1000,
  });

  // Stock meta
  const { data: stockMeta } = useQuery<Stock>({
    queryKey: ["stock", ticker],
    queryFn: () => api<Stock>(`/stocks/${ticker}`),
    enabled: !!ticker,
  });

  // Chart data
  const { data: chartData, isLoading: chartLoading, isError: chartError } = useQuery<DailyIndicator[]>({
    queryKey: ["daily-indicators", ticker],
    queryFn: () =>
      api<DailyIndicator[]>(
        `/indicators/daily/${ticker}?start=${startStr()}&end=${todayStr()}`
      ),
    enabled: !!ticker,
  });

  function handleTickerSubmit(e: React.FormEvent) {
    e.preventDefault();
    const t = inputTicker.trim();
    if (t) {
      navigate(`/chart/${t}`);
      setInputTicker("");
    }
  }

  const latestData = chartData && chartData.length > 0 ? chartData[chartData.length - 1] : null;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <TrendingUp className="text-indigo-600" size={24} />
        <h2 className="text-2xl font-bold">차트</h2>
      </div>

      {/* Controls bar */}
      <div className="flex flex-wrap items-center gap-3 bg-gray-50 rounded-xl p-4 border border-gray-200">
        {/* Ticker input */}
        <form onSubmit={handleTickerSubmit} className="flex gap-2">
          <input
            type="text"
            value={inputTicker}
            onChange={(e) => setInputTicker(e.target.value)}
            placeholder="종목코드 입력 (예: 005930)"
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm w-52 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
          <button
            type="submit"
            className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
          >
            이동
          </button>
        </form>

        {/* Quick select */}
        {quickList && quickList.length > 0 && (
          <select
            value={ticker ?? ""}
            onChange={(e) => {
              if (e.target.value) navigate(`/chart/${e.target.value}`);
            }}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
          >
            <option value="">RS 상위 종목 선택</option>
            {quickList.map((s) => (
              <option key={s.ticker} value={s.ticker}>
                {s.ticker} {s.name} (RS {s.rs_rating})
              </option>
            ))}
          </select>
        )}

        {/* Daily/Weekly toggle */}
        <div className="flex rounded-lg border border-gray-300 overflow-hidden text-sm font-medium">
          <button className="px-3 py-1.5 bg-indigo-600 text-white">일간</button>
          <button
            className="px-3 py-1.5 bg-white text-gray-400 cursor-not-allowed"
            disabled
            title="준비중"
          >
            주간
          </button>
        </div>
      </div>

      {/* Stock meta strip */}
      {ticker && (
        <div className="flex flex-wrap items-center gap-4 px-4 py-3 bg-white rounded-xl border border-gray-200">
          <div>
            <span className="font-mono font-bold text-gray-800 text-lg">{ticker}</span>
            {stockMeta ? (
              <span className="ml-2 text-gray-600">{stockMeta.name}</span>
            ) : (
              <span className="ml-2 text-gray-400">...</span>
            )}
            {stockMeta?.sector && (
              <span className="ml-2 text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
                {stockMeta.sector}
              </span>
            )}
          </div>

          {latestData ? (
            <>
              <div className="flex items-center gap-1 text-sm">
                <span className="text-gray-500">종가</span>
                <span className="font-mono font-semibold text-gray-800">
                  {latestData.adj_close.toLocaleString("ko-KR")}
                </span>
              </div>
              {latestData.rs_rating != null && (
                <div className="flex items-center gap-1 text-sm">
                  <span className="text-gray-500">RS</span>
                  <span
                    className={`font-mono font-semibold ${
                      latestData.rs_rating >= 90
                        ? "text-green-600"
                        : latestData.rs_rating >= 70
                        ? "text-yellow-600"
                        : "text-gray-500"
                    }`}
                  >
                    {latestData.rs_rating}
                  </span>
                </div>
              )}
              {latestData.minervini_pass && (
                <div className="flex items-center gap-1 text-sm text-green-600">
                  <CheckCircle2 size={15} />
                  <span className="font-medium">Minervini</span>
                </div>
              )}
            </>
          ) : chartLoading ? (
            <span className="text-sm text-gray-400">로딩 중...</span>
          ) : null}
        </div>
      )}

      {/* Chart area */}
      {!ticker ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400 border border-dashed border-gray-300 rounded-xl">
          <TrendingUp size={48} className="mb-3 opacity-30" />
          <p className="text-lg">종목을 선택해주세요</p>
          <p className="text-sm mt-1">종목코드를 입력하거나 RS 상위 종목에서 선택하세요</p>
        </div>
      ) : chartLoading ? (
        <div className="flex items-center justify-center py-20 text-gray-400">
          <span>차트 데이터 로딩 중...</span>
        </div>
      ) : chartError ? (
        <div className="flex items-center justify-center py-20 text-red-500">
          <span>데이터를 불러오지 못했습니다.</span>
        </div>
      ) : chartData && chartData.length > 0 ? (
        <div className="rounded-xl border border-gray-200 overflow-hidden">
          <PriceChart
            data={chartData}
            showSMA10={showSMA10}
            showSMA50={showSMA50}
            showSMA150={showSMA150}
            showSMA200={showSMA200}
            show52wHigh={show52wHigh}
            show52wLow={show52wLow}
            showPocketPivot={showPocketPivot}
            showDistributionDay={showDistributionDay}
            height={500}
          />
        </div>
      ) : (
        <div className="flex items-center justify-center py-20 text-gray-400">
          <span>표시할 데이터가 없습니다.</span>
        </div>
      )}

      {/* Toggle checkboxes */}
      {ticker && (
        <div className="bg-gray-50 rounded-xl border border-gray-200 p-4 space-y-3">
          <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wide">차트 옵션</h3>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            {/* SMA toggles */}
            <label className="flex items-center gap-2 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={showSMA50}
                onChange={(e) => setShowSMA50(e.target.checked)}
                className="accent-orange-500"
              />
              <span className="text-orange-600 font-medium">SMA 50</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={showSMA150}
                onChange={(e) => setShowSMA150(e.target.checked)}
                className="accent-blue-500"
              />
              <span className="text-blue-600 font-medium">SMA 150</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={showSMA200}
                onChange={(e) => setShowSMA200(e.target.checked)}
                className="accent-red-500"
              />
              <span className="text-red-600 font-medium">SMA 200</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={showSMA10}
                onChange={(e) => setShowSMA10(e.target.checked)}
                className="accent-purple-500"
              />
              <span className="text-purple-600 font-medium">SMA 10</span>
            </label>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            {/* 52w & markers */}
            <label className="flex items-center gap-2 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={show52wHigh}
                onChange={(e) => setShow52wHigh(e.target.checked)}
                className="accent-green-500"
              />
              <span className="text-green-700 font-medium">52w High</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={show52wLow}
                onChange={(e) => setShow52wLow(e.target.checked)}
                className="accent-pink-500"
              />
              <span className="text-pink-600 font-medium">52w Low</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={showPocketPivot}
                onChange={(e) => setShowPocketPivot(e.target.checked)}
                className="accent-green-500"
              />
              <span className="text-green-700 font-medium">Pocket Pivot</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer text-sm">
              <input
                type="checkbox"
                checked={showDistributionDay}
                onChange={(e) => setShowDistributionDay(e.target.checked)}
                className="accent-red-500"
              />
              <span className="text-red-600 font-medium">Distribution Day</span>
            </label>
          </div>
        </div>
      )}

      {/* Action buttons */}
      {ticker && (
        <div className="flex gap-3">
          <a
            href={apiUrl(`/render/${ticker}/daily.png`)}
            target="_blank"
            download
            className="flex items-center gap-2 px-4 py-2 bg-gray-800 text-white rounded-lg text-sm font-medium hover:bg-gray-700 transition-colors"
          >
            PNG 다운로드
          </a>
          <Link
            to={`/prompt/${ticker}`}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
          >
            LLM 프롬프트
          </Link>
        </div>
      )}
    </div>
  );
}
