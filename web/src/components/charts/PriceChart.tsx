import { useEffect, useRef } from "react";
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  createSeriesMarkers,
  ColorType,
  CrosshairMode,
} from "lightweight-charts";
import type { Time, SeriesMarker } from "lightweight-charts";
import type { DailyIndicator } from "../../lib/types";

export interface PriceChartProps {
  data: DailyIndicator[];
  showSMA10?: boolean;
  showSMA50?: boolean;
  showSMA150?: boolean;
  showSMA200?: boolean;
  show52wHigh?: boolean;
  show52wLow?: boolean;
  showVolume?: boolean;
  showVolumeSMA?: boolean;
  showPocketPivot?: boolean;
  showDistributionDay?: boolean;
  height?: number;
}

export function PriceChart({
  data,
  showSMA10 = false,
  showSMA50 = true,
  showSMA150 = true,
  showSMA200 = true,
  show52wHigh = false,
  show52wLow = false,
  showVolume = true,
  showVolumeSMA = true,
  showPocketPivot = false,
  showDistributionDay = false,
  height = 600,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

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
      crosshair: { mode: CrosshairMode.Normal },
    });

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

    function addSMA(field: keyof DailyIndicator, color: string) {
      const series = chart.addSeries(LineSeries, {
        color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      series.setData(
        data
          .filter((d) => d[field] != null)
          .map((d) => ({ time: d.date as Time, value: d[field] as number }))
      );
    }

    if (showSMA10) addSMA("sma_10", "#9333ea");
    if (showSMA50) addSMA("sma_50", "#ea580c");
    if (showSMA150) addSMA("sma_150", "#2563eb");
    if (showSMA200) addSMA("sma_200", "#dc2626");

    if (show52wHigh) {
      const s = chart.addSeries(LineSeries, {
        color: "#15803d",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      s.setData(
        data
          .filter((d) => d.w52_high != null)
          .map((d) => ({ time: d.date as Time, value: d.w52_high! }))
      );
    }
    if (show52wLow) {
      const s = chart.addSeries(LineSeries, {
        color: "#db2777",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      s.setData(
        data
          .filter((d) => d.w52_low != null)
          .map((d) => ({ time: d.date as Time, value: d.w52_low! }))
      );
    }

    // ── Pane 1: Volume ──
    if (showVolume) {
      const volumeSeries = chart.addSeries(
        HistogramSeries,
        {
          priceFormat: { type: "volume" },
          priceScaleId: "",
          color: "#a1a1aa",
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
        const volSma = chart.addSeries(
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
        volSma.setData(
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
    if (markers.length > 0) {
      markers.sort((a, b) => String(a.time).localeCompare(String(b.time)));
      createSeriesMarkers(candleSeries, markers);
    }

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
      chart.remove();
    };
  }, [
    data,
    showSMA10,
    showSMA50,
    showSMA150,
    showSMA200,
    show52wHigh,
    show52wLow,
    showVolume,
    showVolumeSMA,
    showPocketPivot,
    showDistributionDay,
    height,
  ]);

  return <div ref={containerRef} style={{ width: "100%" }} />;
}
