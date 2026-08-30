import { buildChart, type ChartIn } from "../lib/streakChart";
import { CLOSED_DESC, MARK_DESC, TRIGGER_DOT_DESC } from "./ChartLegend";

export default function StreakChart(props: Omit<ChartIn, "width" | "height">) {
  const width = 420, height = 64, bandY = height + 6;
  const out = buildChart({ ...props, width, height });
  if (!out.pricePoints) return <span className="text-faint">—</span>;
  return (
    <svg width={width} height={height + 14} className="block">
      {out.steps.map((s, i) => (
        <line key={`s${i}`} x1={s.x1} x2={s.x2} y1={s.y} y2={s.y}
              stroke="#9ca3af" strokeDasharray="4 3" strokeWidth={1.2}>
          <title>{`pivot(돌파 기준가) ${s.pivot.toLocaleString()} · ${s.from} ~ ${s.to ?? "진행중"}`}</title>
        </line>))}
      <polyline points={out.pricePoints} fill="none" stroke="#2563eb" strokeWidth={1.4} />
      {out.bands.map((b, i) => (
        <g key={`b${i}`}>
          <line x1={b.x1} x2={b.x2} y1={bandY} y2={bandY} stroke="#16a34a"
                strokeWidth={4} strokeDasharray={b.dashed ? "6 4" : undefined}>
            <title>{`watch 이상 구간 ${b.start} ~ ${b.end ?? "진행중"}${
              b.closed_by == null ? "" : `\n${CLOSED_DESC[b.closed_by]}`}`}</title>
          </line>
          {b.censored && (
            <text x={b.x1} y={bandY + 4} fontSize={9} fill="#b45309">
              <title>{MARK_DESC.censored}</title>⟵</text>)}
          {b.marker && (
            /* 구간 끝에서 닫히면 x2=width — svg 밖으로 잘리지 않게 클램프(큰 차트와 동일) */
            <text x={Math.min(b.x2, width - 10)} y={bandY + 4} fontSize={10}
                  fill={b.marker === "x" ? "#dc2626" : "#6b7280"}>
              <title>{b.marker === "x" ? MARK_DESC.closedX : MARK_DESC.closedO}</title>
              {b.marker === "x" ? "✕" : "○"}</text>)}
        </g>))}
      {out.dots.map((d, i) => (
        <circle key={`d${i}`} cx={d.x} cy={d.y} r={3} fill={d.color}>
          <title>{`${TRIGGER_DOT_DESC[d.trigger_type] ?? d.trigger_type} (${d.d})`}</title>
        </circle>))}
    </svg>
  );
}
