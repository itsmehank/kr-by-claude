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
  // 차트는 문자열(YYYY-MM-DD) time 모드 가정 — 날짜 문자열 비교로 클램프.
  const from = String(vr.from);
  const to = String(vr.to);
  // timeToCoordinate 는 캔들 '중심' x 를 준다. 세그먼트를 양 끝에서 반 칸(barSpacing/2)
  // 확장해야 캔들 전체 폭을 덮고, 인접 세그먼트(예: ignore→entry)가 틈 없이 맞닿는다.
  const half = (ts.options().barSpacing ?? 6) / 2;
  const out: Rect[] = [];
  for (const seg of segments) {
    if (seg.endDate < from || seg.startDate > to) continue; // 화면 밖
    const cs = seg.startDate < from ? from : seg.startDate;
    const ce = seg.endDate > to ? to : seg.endDate;
    const x1 = ts.timeToCoordinate(cs as Time);
    const x2 = ts.timeToCoordinate(ce as Time);
    if (x1 === null || x2 === null) continue;
    const left = Math.min(x1, x2) - half;
    const right = Math.max(x1, x2) + half;
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
