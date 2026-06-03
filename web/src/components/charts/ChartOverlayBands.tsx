import { useEffect, useState, type RefObject } from "react";
import type { IChartApi, Time } from "lightweight-charts";
import type { BandSegment } from "./overlayBands";
import { BAND_COLORS } from "./overlayBands";

interface Rect {
  left: number;
  width: number;
  color: string;
}

interface ChartOverlayBandsProps {
  chart: IChartApi | null;
  containerRef: RefObject<HTMLDivElement | null>;
  segments: BandSegment[];
  visible: boolean;
}

function computeRects(chart: IChartApi, segments: BandSegment[]): Rect[] {
  const ts = chart.timeScale();
  const vr = ts.getVisibleRange();
  if (!vr) return [];
  const from = String(vr.from);
  const to = String(vr.to);
  const out: Rect[] = [];
  for (const seg of segments) {
    if (seg.endDate < from || seg.startDate > to) continue; // 화면 밖
    const cs = seg.startDate < from ? from : seg.startDate;
    const ce = seg.endDate > to ? to : seg.endDate;
    const x1 = ts.timeToCoordinate(cs as Time);
    const x2 = ts.timeToCoordinate(ce as Time);
    if (x1 === null || x2 === null) continue;
    const left = Math.min(x1, x2);
    const right = Math.max(x1, x2);
    out.push({ left, width: Math.max(1, right - left), color: BAND_COLORS[seg.state] });
  }
  return out;
}

export function ChartOverlayBands({ chart, containerRef, segments, visible }: ChartOverlayBandsProps) {
  const [rects, setRects] = useState<Rect[]>([]);

  useEffect(() => {
    const clear = () => setRects([]);
    if (!chart || !visible || segments.length === 0) {
      clear();
      return;
    }
    const ts = chart.timeScale();
    const recompute = () => setRects(computeRects(chart, segments));
    recompute();
    ts.subscribeVisibleTimeRangeChange(recompute);
    const container = containerRef.current;
    const ro = container ? new ResizeObserver(recompute) : null;
    if (ro && container) ro.observe(container);
    return () => {
      ts.unsubscribeVisibleTimeRangeChange(recompute);
      ro?.disconnect();
    };
  }, [chart, containerRef, segments, visible]);

  if (!visible) return null;
  return (
    <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 1 }}>
      {rects.map((r, i) => (
        <div
          key={i}
          style={{ position: "absolute", left: r.left, width: r.width, top: 0, bottom: 0, background: r.color }}
        />
      ))}
    </div>
  );
}
