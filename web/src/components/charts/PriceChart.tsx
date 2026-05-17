import { useEffect, useRef } from "react";
import {
  createChart,
  createSeriesMarkers,
  LineSeries,
  ColorType,
} from "lightweight-charts";
import type { SeriesMarker, Time } from "lightweight-charts";
import type { DailyIndicator } from "../../lib/types";

export interface PriceChartProps {
  data: DailyIndicator[];
  showSMA50?: boolean;
  showSMA150?: boolean;
  showSMA200?: boolean;
  showSMA10?: boolean;
  show52wHigh?: boolean;
  show52wLow?: boolean;
  showVolume?: boolean;
  showRSLine?: boolean;
  showPocketPivot?: boolean;
  showDistributionDay?: boolean;
  height?: number;
}

export function PriceChart(props: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      height: props.height ?? 500,
      layout: {
        background: { type: ColorType.Solid, color: "white" },
        textColor: "#333",
      },
      grid: {
        vertLines: { color: "#eee" },
        horzLines: { color: "#eee" },
      },
      timeScale: { timeVisible: false, secondsVisible: false },
    });

    // Main price line (adj_close)
    const priceSeries = chart.addSeries(LineSeries, {
      color: "#000000",
      lineWidth: 2,
    });
    priceSeries.setData(
      props.data
        .filter((d) => d.adj_close != null)
        .map((d) => ({ time: d.date as Time, value: d.adj_close }))
    );

    // SMA overlays
    if (props.showSMA50) {
      const s = chart.addSeries(LineSeries, { color: "#ff9800", lineWidth: 1 });
      s.setData(
        props.data
          .filter((d) => d.sma_50 != null)
          .map((d) => ({ time: d.date as Time, value: d.sma_50! }))
      );
    }
    if (props.showSMA150) {
      const s = chart.addSeries(LineSeries, { color: "#2196f3", lineWidth: 1 });
      s.setData(
        props.data
          .filter((d) => d.sma_150 != null)
          .map((d) => ({ time: d.date as Time, value: d.sma_150! }))
      );
    }
    if (props.showSMA200) {
      const s = chart.addSeries(LineSeries, { color: "#f44336", lineWidth: 1 });
      s.setData(
        props.data
          .filter((d) => d.sma_200 != null)
          .map((d) => ({ time: d.date as Time, value: d.sma_200! }))
      );
    }
    if (props.showSMA10) {
      const s = chart.addSeries(LineSeries, { color: "#9c27b0", lineWidth: 1 });
      s.setData(
        props.data
          .filter((d) => d.sma_10 != null)
          .map((d) => ({ time: d.date as Time, value: d.sma_10! }))
      );
    }
    if (props.show52wHigh) {
      const s = chart.addSeries(LineSeries, { color: "#4caf50", lineWidth: 1, lineStyle: 2 });
      s.setData(
        props.data
          .filter((d) => d.w52_high != null)
          .map((d) => ({ time: d.date as Time, value: d.w52_high! }))
      );
    }
    if (props.show52wLow) {
      const s = chart.addSeries(LineSeries, { color: "#e91e63", lineWidth: 1, lineStyle: 2 });
      s.setData(
        props.data
          .filter((d) => d.w52_low != null)
          .map((d) => ({ time: d.date as Time, value: d.w52_low! }))
      );
    }

    // Markers for Pocket Pivot / Distribution Day via createSeriesMarkers
    if (props.showPocketPivot || props.showDistributionDay) {
      const markers: SeriesMarker<Time>[] = [];
      if (props.showPocketPivot) {
        props.data
          .filter((d) => d.pocket_pivot_flag)
          .forEach((d) =>
            markers.push({
              time: d.date as Time,
              position: "belowBar",
              color: "#4caf50",
              shape: "arrowUp",
              text: "PP",
            })
          );
      }
      if (props.showDistributionDay) {
        props.data
          .filter((d) => d.distribution_day_flag)
          .forEach((d) =>
            markers.push({
              time: d.date as Time,
              position: "aboveBar",
              color: "#f44336",
              shape: "arrowDown",
              text: "DD",
            })
          );
      }
      // Sort markers by time (required by lightweight-charts)
      markers.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
      createSeriesMarkers(priceSeries, markers);
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
    props.data,
    props.showSMA10,
    props.showSMA50,
    props.showSMA150,
    props.showSMA200,
    props.show52wHigh,
    props.show52wLow,
    props.showPocketPivot,
    props.showDistributionDay,
    props.height,
  ]);

  return <div ref={containerRef} style={{ width: "100%" }} />;
}
