import { useEffect, useRef, useState } from "react";
import {
  createChart,
  LineSeries,
  ColorType,
  CrosshairMode,
} from "lightweight-charts";
import type { Time, IChartApi, ISeriesApi } from "lightweight-charts";
import type { SectorTimeseries } from "../../lib/types";

const PALETTE = [
  "#2563eb",
  "#dc2626",
  "#16a34a",
  "#ea580c",
  "#9333ea",
  "#0891b2",
  "#db2777",
  "#65a30d",
  "#ca8a04",
  "#7c3aed",
  "#0284c7",
  "#e11d48",
  "#059669",
  "#d97706",
  "#a855f7",
  "#1d4ed8",
  "#b91c1c",
  "#15803d",
  "#c2410c",
  "#7e22ce",
  "#1e3a8a",
  "#991b1b",
  "#166534",
  "#9a3412",
];

interface SectorTimeseriesChartProps {
  series: SectorTimeseries[];
  height?: number;
}

export function SectorTimeseriesChart({
  series,
  height = 400,
}: SectorTimeseriesChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRefs = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const [hidden, setHidden] = useState<Set<string>>(new Set());

  // ── create chart + series once per dataset ──
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#18181b",
        fontFamily:
          '"Pretendard Variable", Pretendard, system-ui, sans-serif',
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
    chartRef.current = chart;
    seriesRefs.current = new Map();

    series.forEach((s, i) => {
      const color = PALETTE[i % PALETTE.length];
      const lineSeries = chart.addSeries(LineSeries, {
        color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        title: s.sector,
      });
      lineSeries.setData(
        s.points.map((p) => ({ time: p.date as Time, value: p.value }))
      );
      seriesRefs.current.set(s.sector, lineSeries);
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
      chart.remove();
      chartRef.current = null;
      seriesRefs.current = new Map();
    };
  }, [series, height]);

  // ── toggle visibility per sector without recreating chart ──
  useEffect(() => {
    series.forEach((s) => {
      const ref = seriesRefs.current.get(s.sector);
      if (ref) {
        ref.applyOptions({ visible: !hidden.has(s.sector) });
      }
    });
  }, [hidden, series]);

  function toggleSector(sector: string) {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(sector)) next.delete(sector);
      else next.add(sector);
      return next;
    });
  }

  function showAll() {
    setHidden(new Set());
  }

  function hideAll() {
    setHidden(new Set(series.map((s) => s.sector)));
  }

  return (
    <div>
      <div ref={containerRef} style={{ width: "100%" }} />

      <div className="flex items-baseline justify-between mt-5 mb-3">
        <div className="caps">Legend · 클릭으로 토글</div>
        <div className="flex gap-3 text-data-xs">
          <button
            onClick={showAll}
            className="text-accent hover:underline font-medium"
          >
            전체 표시
          </button>
          <button
            onClick={hideAll}
            className="text-muted hover:text-ink hover:underline"
          >
            전체 숨김
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {series.map((s, i) => {
          const color = PALETTE[i % PALETTE.length];
          const isHidden = hidden.has(s.sector);
          const latest = s.points[s.points.length - 1]?.value ?? 0;
          const tone =
            latest > 0 ? "text-success" : latest < 0 ? "text-danger" : "text-muted";
          return (
            <button
              key={s.sector}
              onClick={() => toggleSector(s.sector)}
              className={`flex items-center gap-2 px-2.5 py-1 rounded-lg text-data-xs border transition-all ${
                isHidden
                  ? "opacity-40 border-hairline bg-cream"
                  : "border-hairline bg-paper hover:border-accent"
              }`}
            >
              <span
                className="h-2.5 w-2.5 rounded-full shrink-0"
                style={{ background: color }}
              />
              <span className="font-medium text-ink">{s.sector}</span>
              <span className={`num font-semibold ${tone}`}>
                {latest > 0 ? "+" : ""}
                {latest.toFixed(1)}%
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
