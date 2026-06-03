import { useMemo, useState } from "react";
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
import type {
  DailyIndicator,
  Stock,
  MinerviniPassed,
  WeeklyIndicator,
  Classification,
  Signal,
  Trigger,
} from "../lib/types";
import {
  PriceChart,
  type PriceChartBar,
  type TriggerOverlayEvent,
} from "../components/charts/PriceChart";
import { ChartMetaBar } from "../components/ChartMetaBar";
import { ClassificationCard } from "../components/panels/ClassificationCard";
import { IndicatorsCard } from "../components/panels/IndicatorsCard";
import { EntrySignalCard } from "../components/panels/EntrySignalCard";
import { PerformanceCard } from "../components/panels/PerformanceCard";
import { TriggerHistoryTable } from "../components/panels/TriggerHistoryTable";
import { StockSearch } from "../components/StockSearch";

const PERIODS = [
  { id: "1W", label: "1주", days: 7 },
  { id: "1M", label: "1개월", days: 30 },
  { id: "3M", label: "3개월", days: 90 },
  { id: "6M", label: "6개월", days: 180 },
  { id: "1Y", label: "1년", days: 365 },
  { id: "2Y", label: "2년", days: 730 },
  { id: "MAX", label: "전체", days: 3650 },
] as const;
type PeriodId = (typeof PERIODS)[number]["id"];

type Timeframe = "daily" | "weekly";

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

function startForPeriod(period: PeriodId): string {
  const p = PERIODS.find((x) => x.id === period)!;
  const d = new Date();
  d.setDate(d.getDate() - p.days);
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

// ── Adapters: API row → PriceChartBar ──────────────────────────────────────

function dailyToBar(d: DailyIndicator): PriceChartBar {
  return {
    date: d.date,
    open: d.open,
    high: d.high,
    low: d.low,
    close: d.close,
    adj_close: d.adj_close,
    volume: d.volume,
    avg_volume_50d: d.avg_volume_50d,
    sma_short: d.sma_50,
    sma_mid: d.sma_150,
    sma_long: d.sma_200,
    sma_extra: d.sma_10,
    w52_high: d.w52_high,
    w52_low: d.w52_low,
    pocket_pivot_flag: d.pocket_pivot_flag,
    distribution_day_flag: d.distribution_day_flag,
  };
}

function weeklyToBar(w: WeeklyIndicator): PriceChartBar {
  return {
    date: w.date,
    open: w.open,
    high: w.high,
    low: w.low,
    close: w.close,
    adj_close: w.adj_close,
    volume: w.volume,
    avg_volume_50d: null, // weekly indicators 에는 avg_volume_50d 없음
    sma_short: w.sma_10w,
    sma_mid: w.sma_30w,
    sma_long: w.sma_40w,
    sma_extra: null,
    w52_high: w.w52_high,
    w52_low: w.w52_low,
    pocket_pivot_flag: null,
    distribution_day_flag: null,
  };
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function ChartPage() {
  const { ticker } = useParams<{ ticker?: string }>();
  const navigate = useNavigate();

  const [timeframe, setTimeframe] = useState<Timeframe>("daily");
  const [period, setPeriod] = useState<PeriodId>("6M");

  const [showSMAShort, setShowSMAShort] = useState(true);
  const [showSMAMid, setShowSMAMid] = useState(true);
  const [showSMALong, setShowSMALong] = useState(true);
  const [showSMAExtra, setShowSMAExtra] = useState(false);
  const [show52wHigh, setShow52wHigh] = useState(false);
  const [show52wLow, setShow52wLow] = useState(false);
  const [showVolume, setShowVolume] = useState(true);
  const [showVolumeSMA, setShowVolumeSMA] = useState(true);
  const [showPocketPivot, setShowPocketPivot] = useState(false);
  const [showDistributionDay, setShowDistributionDay] = useState(false);
  const [showPivotStop, setShowPivotStop] = useState(true);
  const [showTriggerMarkers, setShowTriggerMarkers] = useState(true);

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

  // Daily query
  const dailyQ = useQuery<DailyIndicator[]>({
    queryKey: ["daily-indicators", ticker, period],
    queryFn: () =>
      api<DailyIndicator[]>(
        `/indicators/daily/${ticker}?start=${startForPeriod(
          period
        )}&end=${todayStr()}`
      ),
    enabled: !!ticker && timeframe === "daily",
  });

  // Weekly query
  const weeklyQ = useQuery<WeeklyIndicator[]>({
    queryKey: ["weekly-indicators", ticker, period],
    queryFn: () =>
      api<WeeklyIndicator[]>(
        `/indicators/weekly/${ticker}?start=${startForPeriod(
          period
        )}&end=${todayStr()}`
      ),
    enabled: !!ticker && timeframe === "weekly",
  });

  const classificationQ = useQuery<Classification[]>({
    queryKey: ["chart-classification", ticker],
    queryFn: () =>
      api<Classification[]>(
        `/classifications?ticker=${ticker}&lookback_days=60&limit=1`,
      ),
    enabled: !!ticker,
  });

  const signalQ = useQuery<Signal[]>({
    queryKey: ["chart-signal", ticker],
    queryFn: () => api<Signal[]>(`/signals?ticker=${ticker}&days=60`),
    enabled: !!ticker,
  });

  const triggerQ = useQuery<Trigger[]>({
    queryKey: ["chart-triggers", ticker],
    queryFn: () => api<Trigger[]>(`/triggers?ticker=${ticker}&limit=50`),
    enabled: !!ticker,
  });

  const chartLoading = timeframe === "daily" ? dailyQ.isLoading : weeklyQ.isLoading;
  const chartError = timeframe === "daily" ? dailyQ.isError : weeklyQ.isError;
  const rawData = timeframe === "daily" ? dailyQ.data : weeklyQ.data;

  const bars = useMemo<PriceChartBar[]>(() => {
    if (!rawData) return [];
    return timeframe === "daily"
      ? (rawData as DailyIndicator[]).map(dailyToBar)
      : (rawData as WeeklyIndicator[]).map(weeklyToBar);
  }, [rawData, timeframe]);

  const pivotPrice = classificationQ.data?.[0]?.pivot_price ?? null;
  const stopLoss = signalQ.data?.[0]?.stop_loss ?? null;

  const triggerEvents = useMemo<TriggerOverlayEvent[]>(() => {
    return (triggerQ.data ?? []).map((t) => ({
      date: t.evaluated_at.slice(0, 10),
      decision: t.decision,
      triggerType: t.trigger_type,
      close: t.close,
      reasoning: t.reasoning,
    }));
  }, [triggerQ.data]);

  const smaLabels =
    timeframe === "daily"
      ? { short: "SMA 50", mid: "SMA 150", long: "SMA 200", extra: "SMA 10" }
      : { short: "SMA 10W", mid: "SMA 30W", long: "SMA 40W", extra: "—" };

  const latestBar = bars.length > 0 ? bars[bars.length - 1] : null;
  const latestMeta =
    timeframe === "daily"
      ? (dailyQ.data?.[dailyQ.data.length - 1] as DailyIndicator | undefined)
      : (weeklyQ.data?.[weeklyQ.data.length - 1] as WeeklyIndicator | undefined);

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
          <div className="flex flex-col gap-1.5">
            <label className="caps">종목 검색</label>
            <StockSearch onSelect={(t) => navigate(`/chart/${t}`)} />
          </div>

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
            <label className="caps">봉 종류</label>
            <div className="flex rounded-lg border border-hairline overflow-hidden text-data font-semibold bg-cream">
              {(["daily", "weekly"] as const).map((tf) => (
                <button
                  key={tf}
                  onClick={() => setTimeframe(tf)}
                  className={`px-4 py-2 transition-colors ${
                    timeframe === tf
                      ? "bg-accent text-white"
                      : "text-muted hover:text-ink hover:bg-paper"
                  }`}
                >
                  {tf === "daily" ? "일봉" : "주봉"}
                </button>
              ))}
            </div>
          </div>

          {/* Period toggle */}
          <div className="flex flex-col gap-1.5">
            <label className="caps">기간</label>
            <div className="flex rounded-lg border border-hairline overflow-hidden text-data font-semibold bg-cream">
              {PERIODS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setPeriod(p.id)}
                  className={`px-3 py-2 transition-colors ${
                    period === p.id
                      ? "bg-accent text-white"
                      : "text-muted hover:text-ink hover:bg-paper"
                  }`}
                >
                  {p.label}
                </button>
              ))}
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

            {latestBar ? (
              <div className="flex items-center gap-6 ml-auto">
                <div>
                  <div className="caps text-faint">종가</div>
                  <div className="num text-data-md font-semibold mt-0.5">
                    ₩{latestBar.adj_close.toLocaleString("ko-KR")}
                  </div>
                </div>
                {latestMeta?.rs_rating != null && (
                  <div>
                    <div className="caps text-faint">RS</div>
                    <div
                      className={`num text-data-md font-bold mt-0.5 ${
                        latestMeta.rs_rating >= 90
                          ? "text-success"
                          : latestMeta.rs_rating >= 70
                          ? "text-amber"
                          : "text-muted"
                      }`}
                    >
                      {latestMeta.rs_rating}
                    </div>
                  </div>
                )}
                {latestMeta?.minervini_pass && (
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
      ) : bars.length > 0 ? (
        <>
          {ticker && (
            <ChartMetaBar
              ticker={ticker}
              market={stockMeta?.market ?? null}
            />
          )}
          <div className="bento p-2 mb-5 overflow-hidden">
            <PriceChart
              data={bars}
              timeframeLabel={timeframe === "daily" ? "Daily" : "Weekly"}
              smaShortLabel={smaLabels.short}
              smaMidLabel={smaLabels.mid}
              smaLongLabel={smaLabels.long}
              showSMAShort={showSMAShort}
              showSMAMid={showSMAMid}
              showSMALong={showSMALong}
              showSMAExtra={timeframe === "daily" ? showSMAExtra : false}
              show52wHigh={show52wHigh}
              show52wLow={show52wLow}
              showVolume={showVolume}
              showVolumeSMA={showVolumeSMA && timeframe === "daily"}
              showPocketPivot={showPocketPivot && timeframe === "daily"}
              showDistributionDay={showDistributionDay && timeframe === "daily"}
              height={600}
              pivotPrice={pivotPrice}
              stopLoss={stopLoss}
              showPivotStop={showPivotStop}
              showTriggerMarkers={showTriggerMarkers}
              triggerEvents={triggerEvents}
            />
          </div>
        </>
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
              checked={showSMAShort}
              onChange={setShowSMAShort}
              color="#ea580c"
              label={smaLabels.short}
            />
            <Toggle
              checked={showSMAMid}
              onChange={setShowSMAMid}
              color="#2563eb"
              label={smaLabels.mid}
            />
            <Toggle
              checked={showSMALong}
              onChange={setShowSMALong}
              color="#dc2626"
              label={smaLabels.long}
            />
            {timeframe === "daily" && (
              <Toggle
                checked={showSMAExtra}
                onChange={setShowSMAExtra}
                color="#9333ea"
                label="SMA 10"
              />
            )}
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
              checked={showVolume}
              onChange={setShowVolume}
              color="#525252"
              label="거래량"
            />
            {timeframe === "daily" && (
              <Toggle
                checked={showVolumeSMA}
                onChange={setShowVolumeSMA}
                color="#525252"
                label="거래량 SMA 50"
              />
            )}
            {timeframe === "daily" && (
              <>
                <Toggle
                  checked={showPocketPivot}
                  onChange={setShowPocketPivot}
                  color="#16a34a"
                  label="Pocket Pivot"
                />
                <Toggle
                  checked={showDistributionDay}
                  onChange={setShowDistributionDay}
                  color="#dc2626"
                  label="Distribution Day"
                />
              </>
            )}
            <Toggle
              checked={showPivotStop}
              onChange={setShowPivotStop}
              color="#2563eb"
              label="Pivot/Stop 선"
            />
            <Toggle
              checked={showTriggerMarkers}
              onChange={setShowTriggerMarkers}
              color="#16a34a"
              label="트리거 마커"
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

      {ticker && (
        <section className="mt-8 grid grid-cols-1 lg:grid-cols-2 gap-4">
          <ClassificationCard ticker={ticker} />
          <IndicatorsCard ticker={ticker} />
          <EntrySignalCard ticker={ticker} />
          <PerformanceCard ticker={ticker} />
          <div className="lg:col-span-2">
            <TriggerHistoryTable ticker={ticker} />
          </div>
        </section>
      )}
    </div>
  );
}
