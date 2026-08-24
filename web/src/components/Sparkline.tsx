export default function Sparkline({ values, baseline, width = 120, height = 28 }: {
  values: number[];
  baseline: number | null;
  width?: number;
  height?: number;
}) {
  if (values.length < 2) return <span className="text-faint">—</span>;
  const all = baseline != null ? [...values, baseline] : values;
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const x = (i: number) => (i / (values.length - 1)) * width;
  const y = (v: number) => height - ((v - min) / span) * height;
  const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} className="inline-block align-middle">
      {baseline != null && (
        <line x1={0} x2={width} y1={y(baseline)} y2={y(baseline)}
              stroke="#9ca3af" strokeDasharray="3 2" strokeWidth={1} />
      )}
      <polyline points={points} fill="none" stroke="#2563eb" strokeWidth={1.5} />
    </svg>
  );
}
