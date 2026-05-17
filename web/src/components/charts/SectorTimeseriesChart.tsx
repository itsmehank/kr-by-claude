import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  LineSeries,
  ColorType,
  CrosshairMode,
} from "lightweight-charts";
import type {
  Time,
  IChartApi,
  ISeriesApi,
  MouseEventParams,
} from "lightweight-charts";
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
  topN: number | "all";
  height?: number;
}

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  sector: string;
  date: string;
  value: number;
  color: string;
}

const HIDDEN_TOOLTIP: TooltipState = {
  visible: false,
  x: 0,
  y: 0,
  sector: "",
  date: "",
  value: 0,
  color: "",
};

export function SectorTimeseriesChart({
  series,
  topN,
  height = 400,
}: SectorTimeseriesChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRefs = useRef<Map<string, ISeriesApi<"Line">>>(new Map());

  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [tooltip, setTooltip] = useState<TooltipState>(HIDDEN_TOOLTIP);

  // ── sort by latest cumulative return desc, then slice top N ──
  const sortedSeries = useMemo(() => {
    const arr = series.slice().map((s) => {
      const latest = s.points[s.points.length - 1]?.value ?? 0;
      return { ...s, _latest: latest };
    });
    arr.sort((a, b) => b._latest - a._latest);
    const limited = topN === "all" ? arr : arr.slice(0, topN);
    return limited;
  }, [series, topN]);

  // ── create chart + series whenever sortedSeries or height changes ──
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
        // hide last value labels (each series adds one if lastValueVisible)
      },
      crosshair: {
        mode: CrosshairMode.Magnet,
        vertLine: { color: "#a1a1aa", style: 3, width: 1 },
        horzLine: { visible: false },
      },
    });
    chartRef.current = chart;
    seriesRefs.current = new Map();

    sortedSeries.forEach((s, i) => {
      const color = PALETTE[i % PALETTE.length];
      const lineSeries = chart.addSeries(LineSeries, {
        color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: true,
        crosshairMarkerRadius: 4,
        // store color on options for retrieval
        title: "",
      });
      lineSeries.setData(
        s.points.map((p) => ({ time: p.date as Time, value: p.value }))
      );
      seriesRefs.current.set(s.sector, lineSeries);
    });

    // Build sector→color map for tooltip
    const colorMap = new Map<string, string>();
    sortedSeries.forEach((s, i) => {
      colorMap.set(s.sector, PALETTE[i % PALETTE.length]);
    });

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

      // Find the closest series by Y distance
      let bestSector: string | null = null;
      let bestValue = 0;
      let bestDistance = Infinity;
      let bestColor = "";

      seriesRefs.current.forEach((s, sector) => {
        const data = param.seriesData.get(s) as
          | { value: number }
          | undefined;
        if (!data || data.value == null) return;
        const yPixel = s.priceToCoordinate(data.value);
        if (yPixel == null) return;
        const dist = Math.abs(yPixel - param.point!.y);
        if (dist < bestDistance) {
          bestDistance = dist;
          bestSector = sector;
          bestValue = data.value;
          bestColor = colorMap.get(sector) ?? "";
        }
      });

      // Only show tooltip if the closest line is within 20px of the cursor
      if (bestSector === null || bestDistance > 20) {
        setTooltip(HIDDEN_TOOLTIP);
        return;
      }

      const wrapper = wrapperRef.current;
      if (!wrapper) return;
      const rect = wrapper.getBoundingClientRect();
      const tooltipX = param.point.x;
      const tooltipY = param.point.y;

      setTooltip({
        visible: true,
        x: Math.min(tooltipX, rect.width - 200),
        y: Math.max(tooltipY - 60, 8),
        sector: bestSector,
        date: String(param.time),
        value: bestValue,
        color: bestColor,
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
      chart.remove();
      chartRef.current = null;
      seriesRefs.current = new Map();
    };
  }, [sortedSeries, height]);

  // ── toggle visibility per sector without recreating chart ──
  useEffect(() => {
    sortedSeries.forEach((s) => {
      const ref = seriesRefs.current.get(s.sector);
      if (ref) ref.applyOptions({ visible: !hidden.has(s.sector) });
    });
  }, [hidden, sortedSeries]);

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
    setHidden(new Set(sortedSeries.map((s) => s.sector)));
  }

  return (
    <div>
      <div ref={wrapperRef} className="relative">
        <div ref={containerRef} style={{ width: "100%" }} />

        {tooltip.visible && (
          <div
            className="absolute pointer-events-none bg-paper border border-hairline shadow-bento-hover rounded-xl px-3 py-2 z-10"
            style={{ left: tooltip.x + 12, top: tooltip.y }}
          >
            <div className="flex items-center gap-2 mb-1">
              <span
                className="h-2.5 w-2.5 rounded-full shrink-0"
                style={{ background: tooltip.color }}
              />
              <span className="text-data font-semibold text-ink">
                {tooltip.sector}
              </span>
            </div>
            <div className="num text-data-xs text-muted">{tooltip.date}</div>
            <div
              className={`num text-data-md font-bold mt-0.5 ${
                tooltip.value > 0
                  ? "text-success"
                  : tooltip.value < 0
                  ? "text-danger"
                  : "text-ink"
              }`}
            >
              {tooltip.value > 0 ? "+" : ""}
              {tooltip.value.toFixed(2)}%
            </div>
          </div>
        )}
      </div>

      <div className="flex items-baseline justify-between mt-5 mb-3">
        <div className="caps">Legend · 클릭으로 토글 · 수익률 내림차순</div>
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
        {sortedSeries.map((s, i) => {
          const color = PALETTE[i % PALETTE.length];
          const isHidden = hidden.has(s.sector);
          const latest = s.points[s.points.length - 1]?.value ?? 0;
          const tone =
            latest > 0
              ? "text-success"
              : latest < 0
              ? "text-danger"
              : "text-muted";
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
              <span className="num text-faint w-4 text-right">
                {i + 1}
              </span>
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
