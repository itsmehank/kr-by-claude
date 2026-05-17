import { useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  CheckCircle2,
  Image as ImageIcon,
  FileArchive,
  Settings2,
} from "lucide-react";
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

// ── Sub-components ─────────────────────────────────────────────────────────

interface ToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  color: string;
  label: string;
}

function Toggle({ checked, onChange, color, label }: ToggleProps) {
  return (
    <label className="flex items-center gap-2 cursor-pointer text-data px-3 py-1.5 rounded-lg border border-hairline hover:border-accent transition-colors bg-cream">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="w-4 h-4"
        style={{ accentColor: color }}
      />
      <span className="font-semibold" style={{ color }}>
        {label}
      </span>
    </label>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

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

  const { data: quickList } = useQuery<MinerviniPassed[]>({
    queryKey: ["minervini-passed-chart-select"],
    queryFn: () =>
      api<MinerviniPassed[]>("/indicators/minervini-passed?limit=20"),
    staleTime: 5 * 60 * 1000,
  });

  const { data: stockMeta } = useQuery<Stock>({
    queryKey: ["stock", ticker],
    queryFn: () => api<Stock>(`/stocks/${ticker}`),
    enabled: !!ticker,
  });

  const {
    data: chartData,
    isLoading: chartLoading,
    isError: chartError,
  } = useQuery<DailyIndicator[]>({
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

  const latestData =
    chartData && chartData.length > 0 ? chartData[chartData.length - 1] : null;

  return (
    <div className="px-10 py-10 max-w-[1240px] mx-auto">
      {/* Header */}
      <header className="flex items-end justify-between mb-8">
        <div>
          <div className="caps text-faint mb-2">Chart</div>
          <h2 className="font-display text-display-xl font-bold tracking-tight leading-none">
            차트
          </h2>
        </div>
      </header>

      {/* Controls */}
      <div className="bento p-5 mb-5">
        <div className="flex flex-wrap items-end gap-4">
          {/* Ticker input */}
          <form
            onSubmit={handleTickerSubmit}
            className="flex flex-col gap-1.5"
          >
            <label className="caps">종목 코드</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={inputTicker}
                onChange={(e) => setInputTicker(e.target.value)}
                placeholder="예: 005930"
                className="border border-hairline rounded-lg px-3 py-2 text-data bg-cream w-52 focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
              />
              <button
                type="submit"
                className="px-4 py-2 bg-accent text-white rounded-lg text-data font-semibold hover:bg-accent-light transition-colors"
              >
                이동
              </button>
            </div>
          </form>

          {/* Quick select */}
          {quickList && quickList.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <label className="caps">RS 상위 종목</label>
              <select
                value={ticker ?? ""}
                onChange={(e) => {
                  if (e.target.value) navigate(`/chart/${e.target.value}`);
                }}
                className="border border-hairline rounded-lg px-3 py-2 text-data bg-cream focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent"
              >
                <option value="">선택…</option>
                {quickList.map((s) => (
                  <option key={s.ticker} value={s.ticker}>
                    {s.ticker} · {s.name} · RS {s.rs_rating}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Daily/Weekly toggle */}
          <div className="flex flex-col gap-1.5">
            <label className="caps">시간 단위</label>
            <div className="flex rounded-lg border border-hairline overflow-hidden text-data font-semibold bg-cream">
              <button className="px-4 py-2 bg-accent text-white">일간</button>
              <button
                className="px-4 py-2 text-faint cursor-not-allowed"
                disabled
                title="준비중"
              >
                주간
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Stock meta */}
      {ticker && (
        <div className="bento p-5 mb-5">
          <div className="flex flex-wrap items-center gap-6">
            <div className="flex items-baseline gap-3">
              <span className="num font-bold text-data-lg text-ink">
                {ticker}
              </span>
              {stockMeta ? (
                <span className="text-headline font-semibold text-ink">
                  {stockMeta.name}
                </span>
              ) : (
                <span className="text-muted">…</span>
              )}
              {stockMeta?.market && (
                <span className="chip bg-tint-stone text-muted">
                  {stockMeta.market}
                </span>
              )}
              {stockMeta?.sector && (
                <span className="chip bg-tint-blue text-accent">
                  {stockMeta.sector}
                </span>
              )}
            </div>

            {latestData ? (
              <div className="flex items-center gap-6 ml-auto">
                <div>
                  <div className="caps text-faint">종가</div>
                  <div className="num text-data-md font-semibold mt-0.5">
                    ₩{latestData.adj_close.toLocaleString("ko-KR")}
                  </div>
                </div>
                {latestData.rs_rating != null && (
                  <div>
                    <div className="caps text-faint">RS</div>
                    <div
                      className={`num text-data-md font-bold mt-0.5 ${
                        latestData.rs_rating >= 90
                          ? "text-success"
                          : latestData.rs_rating >= 70
                          ? "text-amber"
                          : "text-muted"
                      }`}
                    >
                      {latestData.rs_rating}
                    </div>
                  </div>
                )}
                {latestData.minervini_pass && (
                  <span className="chip bg-success-soft text-success inline-flex items-center gap-1.5">
                    <CheckCircle2 size={14} />
                    Minervini
                  </span>
                )}
              </div>
            ) : chartLoading ? (
              <span className="text-muted ml-auto">로딩 중…</span>
            ) : null}
          </div>
        </div>
      )}

      {/* Chart */}
      {!ticker ? (
        <div className="bento p-16 text-center">
          <LineChart
            size={48}
            className="text-faint mx-auto mb-4"
            strokeWidth={1.5}
          />
          <p className="text-headline font-semibold text-ink mb-1">
            종목을 선택해주세요
          </p>
          <p className="text-data text-muted">
            종목코드를 입력하거나 RS 상위 종목에서 선택하세요
          </p>
        </div>
      ) : chartLoading ? (
        <div className="bento p-16 text-center text-muted">
          차트 데이터 로딩 중…
        </div>
      ) : chartError ? (
        <div className="bento p-16 text-center text-danger">
          데이터를 불러오지 못했습니다.
        </div>
      ) : chartData && chartData.length > 0 ? (
        <div className="bento p-2 mb-5 overflow-hidden">
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
        <div className="bento p-16 text-center text-muted">
          표시할 데이터가 없습니다.
        </div>
      )}

      {/* Toggles */}
      {ticker && (
        <div className="bento p-5 mb-5">
          <div className="flex items-center gap-2.5 mb-4">
            <div className="p-2 rounded-xl bg-tint-violet">
              <Settings2 size={16} className="text-accent" strokeWidth={2} />
            </div>
            <div className="text-subhead font-bold text-ink">차트 옵션</div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Toggle
              checked={showSMA50}
              onChange={setShowSMA50}
              color="#ea580c"
              label="SMA 50"
            />
            <Toggle
              checked={showSMA150}
              onChange={setShowSMA150}
              color="#2563eb"
              label="SMA 150"
            />
            <Toggle
              checked={showSMA200}
              onChange={setShowSMA200}
              color="#dc2626"
              label="SMA 200"
            />
            <Toggle
              checked={showSMA10}
              onChange={setShowSMA10}
              color="#9333ea"
              label="SMA 10"
            />
            <Toggle
              checked={show52wHigh}
              onChange={setShow52wHigh}
              color="#15803d"
              label="52w High"
            />
            <Toggle
              checked={show52wLow}
              onChange={setShow52wLow}
              color="#db2777"
              label="52w Low"
            />
            <Toggle
              checked={showPocketPivot}
              onChange={setShowPocketPivot}
              color="#15803d"
              label="Pocket Pivot"
            />
            <Toggle
              checked={showDistributionDay}
              onChange={setShowDistributionDay}
              color="#dc2626"
              label="Distribution Day"
            />
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
            className="flex items-center gap-2 px-4 py-2.5 bg-paper border border-hairline rounded-xl text-data font-semibold text-ink hover:border-accent transition-colors"
          >
            <ImageIcon size={16} strokeWidth={2} />
            PNG 다운로드
          </a>
          <Link
            to={`/prompt/${ticker}`}
            className="flex items-center gap-2 px-4 py-2.5 bg-accent text-white rounded-xl text-data font-semibold hover:bg-accent-light transition-colors"
          >
            <FileArchive size={16} strokeWidth={2} />
            LLM 프롬프트 ZIP
          </Link>
        </div>
      )}
    </div>
  );
}
