import { useEffect, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  createSeriesMarkers,
  ColorType,
  CrosshairMode,
} from "lightweight-charts";
import type {
  Time,
  SeriesMarker,
  MouseEventParams,
  IChartApi,
} from "lightweight-charts";
import { ChartOverlayBands } from "./ChartOverlayBands";
import type { BandSegment } from "./overlayBands";

// 날짜에 한국어 요일 추가: "2026-05-20" → "2026-05-20 (수)"
function withWeekday(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  const wd = ["일", "월", "화", "수", "목", "금", "토"][d.getDay()];
  return `${iso} (${wd})`;
}

export interface PriceChartBar {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  adj_close: number;
  volume: number | null;
  avg_volume_50d: number | null;
  sma_short: number | null; // 50 (daily) | 10w (weekly)
  sma_mid: number | null; //  150 (daily) | 30w (weekly)
  sma_long: number | null; //  200 (daily) | 40w (weekly)
  sma_extra: number | null; // 10 (daily) | n/a (weekly)
  w52_high: number | null;
  w52_low: number | null;
  pocket_pivot_flag: boolean | null;
  distribution_day_flag: boolean | null;
  minervini_pass?: boolean | null;
}

export interface TriggerOverlayEvent {
  date: string; // YYYY-MM-DD (matches PriceChartBar.date)
  decision: "go_now" | "wait" | "abort";
  triggerType: string;
  close: number | null;
  reasoning: string | null;
}

export interface PriceChartProps {
  data: PriceChartBar[];
  timeframeLabel?: string;
  smaShortLabel?: string;
  smaMidLabel?: string;
  smaLongLabel?: string;
  showSMAShort?: boolean;
  showSMAMid?: boolean;
  showSMALong?: boolean;
  showSMAExtra?: boolean;
  show52wHigh?: boolean;
  show52wLow?: boolean;
  showVolume?: boolean;
  showVolumeSMA?: boolean;
  showPocketPivot?: boolean;
  showDistributionDay?: boolean;
  height?: number;
  // 신규 overlay
  pivotPrice?: number | null;
  stopLoss?: number | null;
  showPivotStop?: boolean;
  showTriggerMarkers?: boolean;
  triggerEvents?: TriggerOverlayEvent[];
  showClassificationBands?: boolean;
  bandSegments?: BandSegment[];
}

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  date: string;
  ohlc:
    | { open: number; high: number; low: number; close: number }
    | null;
  volume: number | null;
  volumeSMA: number | null;
}

const HIDDEN_TOOLTIP: TooltipState = {
  visible: false,
  x: 0,
  y: 0,
  date: "",
  ohlc: null,
  volume: null,
  volumeSMA: null,
};

export function PriceChart({
  data,
  timeframeLabel = "Daily",
  smaShortLabel: _smaShortLabel = "SMA 50",
  smaMidLabel: _smaMidLabel = "SMA 150",
  smaLongLabel: _smaLongLabel = "SMA 200",
  showSMAShort = true,
  showSMAMid = true,
  showSMALong = true,
  showSMAExtra = false,
  show52wHigh = false,
  show52wLow = false,
  showVolume = true,
  showVolumeSMA = true,
  showPocketPivot = false,
  showDistributionDay = false,
  height = 600,
  pivotPrice = null,
  stopLoss = null,
  showPivotStop = true,
  showTriggerMarkers = true,
  triggerEvents = [],
  showClassificationBands = false,
  bandSegments = [],
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<TooltipState>(HIDDEN_TOOLTIP);
  const [chartApi, setChartApi] = useState<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#18181b",
        fontFamily:
          '"Pretendard Variable", Pretendard, -apple-system, BlinkMacSystemFont, system-ui, sans-serif',
      },
      grid: {
        vertLines: { color: "#f5f5f4" },
        horzLines: { color: "#e4e4e7" },
      },
      timeScale: {
        timeVisible: false,
        secondsVisible: false,
        borderColor: "#e4e4e7",
      },
      rightPriceScale: {
        borderColor: "#e4e4e7",
      },
      crosshair: {
        mode: CrosshairMode.Magnet,
        vertLine: { color: "#a1a1aa", style: 3, width: 1 },
        horzLine: { color: "#a1a1aa", style: 3, width: 1 },
      },
    });
    setChartApi(chart);

    // ── Main pane (0): Candlestick ──
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#16a34a",
      downColor: "#dc2626",
      borderUpColor: "#16a34a",
      borderDownColor: "#dc2626",
      wickUpColor: "#16a34a",
      wickDownColor: "#dc2626",
    });

    const ohlcData = data
      .filter(
        (d) =>
          d.open != null && d.high != null && d.low != null && d.close != null
      )
      .map((d) => ({
        time: d.date as Time,
        open: d.open!,
        high: d.high!,
        low: d.low!,
        close: d.close!,
      }));
    candleSeries.setData(ohlcData);

    function addLine(
      field: keyof PriceChartBar,
      color: string,
      style: 0 | 1 | 2 | 3 = 0
    ) {
      const series = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        lineStyle: style,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      series.setData(
        data
          .filter((d) => d[field] != null)
          .map((d) => ({
            time: d.date as Time,
            value: d[field] as number,
          }))
      );
    }

    if (showSMAExtra) addLine("sma_extra", "#9333ea");
    if (showSMAShort) addLine("sma_short", "#ea580c");
    if (showSMAMid) addLine("sma_mid", "#2563eb");
    if (showSMALong) addLine("sma_long", "#dc2626");
    if (show52wHigh) addLine("w52_high", "#15803d", 2);
    if (show52wLow) addLine("w52_low", "#db2777", 2);

    // ── Pivot / Stop loss horizontal lines ──
    if (showPivotStop && pivotPrice != null && data.length > 0) {
      const pivotSeries = chart.addSeries(LineSeries, {
        color: "#2563eb",
        lineWidth: 1,
        lineStyle: 2, // dashed
        priceLineVisible: false,
        lastValueVisible: true,
        title: "pivot",
      });
      pivotSeries.setData(
        data.map((d) => ({ time: d.date as Time, value: pivotPrice })),
      );
    }

    if (showPivotStop && stopLoss != null && data.length > 0) {
      const stopSeries = chart.addSeries(LineSeries, {
        color: "#dc2626",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        title: "stop",
      });
      stopSeries.setData(
        data.map((d) => ({ time: d.date as Time, value: stopLoss })),
      );
    }

    // ── Pane 1: Volume + SMA50V ──
    let volumeSeries: ReturnType<typeof chart.addSeries> | null = null;
    let volSmaSeries: ReturnType<typeof chart.addSeries> | null = null;

    if (showVolume) {
      volumeSeries = chart.addSeries(
        HistogramSeries,
        {
          priceFormat: { type: "volume" },
          priceScaleId: "",
          color: "#a1a1aa",
          lastValueVisible: false,
        },
        1
      );
      const volData = data
        .filter((d) => d.volume != null)
        .map((d) => ({
          time: d.date as Time,
          value: d.volume!,
          color:
            (d.close ?? 0) >= (d.open ?? 0)
              ? "rgba(22,163,74,0.45)"
              : "rgba(220,38,38,0.45)",
        }));
      volumeSeries.setData(volData);

      if (showVolumeSMA) {
        volSmaSeries = chart.addSeries(
          LineSeries,
          {
            color: "#525252",
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
            priceScaleId: "",
          },
          1
        );
        volSmaSeries.setData(
          data
            .filter((d) => d.avg_volume_50d != null)
            .map((d) => ({
              time: d.date as Time,
              value: d.avg_volume_50d!,
            }))
        );
      }
    }

    // ── Markers ──
    const markers: SeriesMarker<Time>[] = [];
    if (showPocketPivot) {
      data
        .filter((d) => d.pocket_pivot_flag)
        .forEach((d) =>
          markers.push({
            time: d.date as Time,
            position: "belowBar",
            color: "#16a34a",
            shape: "arrowUp",
            text: "PP",
          })
        );
    }
    if (showDistributionDay) {
      data
        .filter((d) => d.distribution_day_flag)
        .forEach((d) =>
          markers.push({
            time: d.date as Time,
            position: "aboveBar",
            color: "#dc2626",
            shape: "arrowDown",
            text: "DD",
          })
        );
    }
    // Trigger evaluation markers
    if (showTriggerMarkers && triggerEvents.length > 0) {
      const colorByDecision: Record<TriggerOverlayEvent["decision"], string> = {
        go_now: "#16a34a",
        wait: "#ca8a04",
        abort: "#6b7280",
      };
      for (const e of triggerEvents) {
        markers.push({
          time: e.date as Time,
          position: "aboveBar",
          color: colorByDecision[e.decision],
          shape: "circle",
          text: e.decision,
        });
      }
    }
    if (markers.length > 0) {
      markers.sort((a, b) => String(a.time).localeCompare(String(b.time)));
      createSeriesMarkers(candleSeries, markers);
    }

    // ── Tooltip via crosshair ──
    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      if (
        !param.point ||
        !param.time ||
        param.point.x < 0 ||
        param.point.y < 0
      ) {
        setTooltip(HIDDEN_TOOLTIP);
        return;
      }

      const ohlc = param.seriesData.get(candleSeries) as
        | { open: number; high: number; low: number; close: number }
        | undefined;
      const vol = volumeSeries
        ? (param.seriesData.get(volumeSeries) as { value: number } | undefined)
        : undefined;
      const volSma = volSmaSeries
        ? (param.seriesData.get(volSmaSeries) as { value: number } | undefined)
        : undefined;

      if (!ohlc) {
        setTooltip(HIDDEN_TOOLTIP);
        return;
      }

      const wrapper = wrapperRef.current;
      const rectWidth = wrapper?.clientWidth ?? 0;
      const tooltipWidth = 220;

      setTooltip({
        visible: true,
        x:
          param.point.x + 14 + tooltipWidth > rectWidth
            ? param.point.x - tooltipWidth - 14
            : param.point.x + 14,
        y: Math.max(8, param.point.y - 80),
        date: String(param.time),
        ohlc: {
          open: ohlc.open,
          high: ohlc.high,
          low: ohlc.low,
          close: ohlc.close,
        },
        volume: vol?.value ?? null,
        volumeSMA: volSma?.value ?? null,
      });
    });

    chart.timeScale().fitContent();

    const resize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    resize();
    window.addEventListener("resize", resize);

    return () => {
      window.removeEventListener("resize", resize);
      setChartApi(null);
      chart.remove();
    };
  }, [
    data,
    showSMAExtra,
    showSMAShort,
    showSMAMid,
    showSMALong,
    show52wHigh,
    show52wLow,
    showVolume,
    showVolumeSMA,
    showPocketPivot,
    showDistributionDay,
    height,
    // 신규
    pivotPrice,
    stopLoss,
    showPivotStop,
    showTriggerMarkers,
    triggerEvents,
  ]);

  const ohlcDeltaPct =
    tooltip.ohlc && tooltip.ohlc.open > 0
      ? ((tooltip.ohlc.close - tooltip.ohlc.open) / tooltip.ohlc.open) * 100
      : null;
  const volDeltaPct =
    tooltip.volume != null && tooltip.volumeSMA != null && tooltip.volumeSMA > 0
      ? ((tooltip.volume - tooltip.volumeSMA) / tooltip.volumeSMA) * 100
      : null;

  return (
    <div ref={wrapperRef} className="relative">
      <div ref={containerRef} style={{ width: "100%" }} />
      <ChartOverlayBands
        chart={chartApi}
        containerRef={containerRef}
        segments={bandSegments ?? []}
        visible={showClassificationBands ?? false}
      />

      {tooltip.visible && tooltip.ohlc && (
        <div
          className="absolute pointer-events-none bg-paper border border-hairline shadow-bento-hover rounded-xl px-3 py-2.5 z-10 w-[220px]"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          <div className="flex items-baseline justify-between mb-2">
            <div className="num text-data-xs text-muted">{withWeekday(tooltip.date)}</div>
            <div className="caps text-faint">{timeframeLabel}</div>
          </div>

          <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 mb-2">
            <div className="flex items-baseline justify-between">
              <span className="text-data-xs text-muted">시가</span>
              <span className="num text-data text-ink">
                {tooltip.ohlc.open.toLocaleString()}
              </span>
            </div>
            <div className="flex items-baseline justify-between">
              <span className="text-data-xs text-muted">고가</span>
              <span className="num text-data text-success">
                {tooltip.ohlc.high.toLocaleString()}
              </span>
            </div>
            <div className="flex items-baseline justify-between">
              <span className="text-data-xs text-muted">저가</span>
              <span className="num text-data text-danger">
                {tooltip.ohlc.low.toLocaleString()}
              </span>
            </div>
            <div className="flex items-baseline justify-between">
              <span className="text-data-xs text-muted">종가</span>
              <span
                className={`num text-data font-semibold ${
                  tooltip.ohlc.close >= tooltip.ohlc.open
                    ? "text-success"
                    : "text-danger"
                }`}
              >
                {tooltip.ohlc.close.toLocaleString()}
              </span>
            </div>
          </div>

          {ohlcDeltaPct != null && (
            <div className="flex items-baseline justify-between border-t border-hairline pt-1.5 mb-1.5">
              <span className="text-data-xs text-muted">등락</span>
              <span
                className={`num text-data font-semibold ${
                  ohlcDeltaPct >= 0 ? "text-success" : "text-danger"
                }`}
              >
                {ohlcDeltaPct >= 0 ? "+" : ""}
                {ohlcDeltaPct.toFixed(2)}%
              </span>
            </div>
          )}

          {tooltip.volume != null && (
            <div className="border-t border-hairline pt-2 mt-1.5">
              <div className="flex items-baseline justify-between mb-1">
                <span className="caps">거래량</span>
                <span className="num text-data text-ink font-semibold">
                  {tooltip.volume.toLocaleString()}
                </span>
              </div>
              {volDeltaPct != null && (
                <div className="flex items-baseline justify-between">
                  <span className="text-data-xs text-muted">
                    SMA-50 대비
                  </span>
                  <span
                    className={`num text-data-xs font-semibold ${
                      volDeltaPct >= 0 ? "text-success" : "text-danger"
                    }`}
                  >
                    {volDeltaPct >= 0 ? "+" : ""}
                    {volDeltaPct.toFixed(0)}%
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
