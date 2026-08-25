export type TriggerKind = "breakout" | "promotion" | "invalidation";

const GREEN = "#16a34a";
const AMBER = "#f59e0b";
const GRAY = "#9ca3af";

export function triggerColor(triggerType: string): string {
  if (triggerType === "breakout" || triggerType === "breakout_from_watch") return GREEN;
  if (triggerType === "promotion") return AMBER;
  return GRAY;
}

export interface StreakBandIn { start: string; end: string | null;
  closed_by: "ignore" | "disqualify" | null; censored: boolean;
  backfilled: boolean; has_gap: boolean; }
export interface ChartIn { width: number; height: number; to: string;
  series: [string, number][]; pivotSteps: [string, string | null, number][];
  streaks: StreakBandIn[]; triggers: { d: string; trigger_type: string }[]; }
export interface ChartOut {
  pricePoints: string;
  steps: { x1: number; x2: number; y: number }[];
  bands: { x1: number; x2: number; dashed: boolean;
           marker: "x" | "o" | null; censored: boolean }[];
  dots: { x: number; y: number; color: string }[]; }

export function buildChart(input: ChartIn): ChartOut {
  const { width, height, series } = input;
  const n = series.length;
  if (n < 2) return { pricePoints: "", steps: [], bands: [], dots: [] };
  const values = series.map(([, v]) => v);
  const pivots = input.pivotSteps.map(([, , p]) => p);
  const min = Math.min(...values, ...(pivots.length ? pivots : [Infinity]));
  const max = Math.max(...values, ...(pivots.length ? pivots : [-Infinity]));
  const span = max - min || 1;
  const x = (i: number) => (i / (n - 1)) * width;
  const y = (v: number) => height - ((v - min) / span) * height;
  // 날짜 → 가장 가까운(같거나 직전) 거래일 인덱스
  const idx = (d: string) => {
    let lo = 0, hi = n - 1, ans = 0;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (series[mid][0] <= d) { ans = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return ans;
  };
  const pricePoints = series
    .map(([, v], i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const steps = input.pivotSteps.map(([from, to, pivot]) => ({
    x1: x(idx(from)), x2: to == null ? width : x(idx(to)), y: y(pivot) }));
  const bands = input.streaks.map((s) => ({
    x1: x(idx(s.start)),
    x2: s.end == null ? width : x(idx(s.end)),
    dashed: s.has_gap || s.backfilled,
    marker: s.closed_by == null ? null : s.closed_by === "disqualify" ? "x" as const : "o" as const,
    censored: s.censored }));
  const dots = input.triggers.map((t) => ({
    x: x(idx(t.d)), y: y(series[idx(t.d)][1]), color: triggerColor(t.trigger_type) }));
  return { pricePoints, steps, bands, dots };
}
