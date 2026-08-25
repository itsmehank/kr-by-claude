export type TriggerKind = "breakout" | "promotion" | "invalidation";

const GREEN = "#16a34a";
const AMBER = "#f59e0b";
const GRAY = "#9ca3af";

/** 묶음 띠의 y 오프셋(차트 높이 + 이 값) — 렌더와 hitTest 가 공유하는 단일 정의. */
export const BAND_OFFSET = 6;

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
  streaks: StreakBandIn[];
  triggers: { d: string; trigger_type: string; decision?: string | null;
              close?: number | null; pivot_price?: number | null }[]; }
export interface ChartOut {
  pricePoints: string;
  steps: { x1: number; x2: number; y: number }[];
  bands: { x1: number; x2: number; dashed: boolean;
           marker: "x" | "o" | null; censored: boolean }[];
  dots: { x: number; y: number; color: string }[]; }

export type ChartHit =
  | { kind: "dot"; date: string; trigger_type: string; decision: string | null;
      close: number | null; pivot_price: number | null; x: number; y: number }
  | { kind: "step"; from: string; to: string | null; pivot: number; y: number }
  | { kind: "band"; start: string; end: string | null;
      closed_by: "ignore" | "disqualify" | null; x1: number; x2: number }
  | { kind: "price"; date: string; close: number; x: number; y: number };

// buildChart 와 hitTest 가 좌표 공식을 공유한다 — 한쪽만 바뀌면 점 위치와
// 히트 영역이 어긋나므로 반드시 이 헬퍼를 통해서만 스케일을 계산할 것.
function computeScale(input: ChartIn) {
  const { width, height, series } = input;
  const n = series.length;
  if (n < 2) return null;
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
  return { n, min, max, x, y, idx };
}

export function buildChart(input: ChartIn): ChartOut {
  const scale = computeScale(input);
  if (!scale) return { pricePoints: "", steps: [], bands: [], dots: [] };
  const { width, series } = input;
  const { x, y, idx } = scale;
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

const DOT_RADIUS = 8;
const STEP_TOLERANCE = 6;
const BAND_TOLERANCE = 8;

/** viewBox 좌표 (mx, my) 에서 무엇 위에 있는지 판정 — 우선순위 dot > step > band > price.
 *  범위 밖·데이터 부족(n<2)은 null (툴팁·크로스헤어 숨김). */
export function hitTest(input: ChartIn, mx: number, my: number): ChartHit | null {
  const scale = computeScale(input);
  if (!scale) return null;
  const { width, height, series } = input;
  const { n, x, y, idx } = scale;
  const bandY = height + BAND_OFFSET;
  if (mx < 0 || mx > width || my < 0 || my > bandY + BAND_TOLERANCE) return null;

  for (const t of input.triggers) {
    const i = idx(t.d);
    const dx = mx - x(i), dy = my - y(series[i][1]);
    if (dx * dx + dy * dy <= DOT_RADIUS * DOT_RADIUS) {
      return { kind: "dot", date: t.d, trigger_type: t.trigger_type,
               decision: t.decision ?? null, close: t.close ?? null,
               pivot_price: t.pivot_price ?? null, x: x(i), y: y(series[i][1]) };
    }
  }
  for (const [from, to, pivot] of input.pivotSteps) {
    const x1 = x(idx(from)), x2 = to == null ? width : x(idx(to)), sy = y(pivot);
    if (mx >= x1 && mx <= x2 && Math.abs(my - sy) <= STEP_TOLERANCE) {
      return { kind: "step", from, to, pivot, y: sy };
    }
  }
  for (const s of input.streaks) {
    const x1 = x(idx(s.start)), x2 = s.end == null ? width : x(idx(s.end));
    if (mx >= x1 && mx <= x2 && Math.abs(my - bandY) <= BAND_TOLERANCE) {
      return { kind: "band", start: s.start, end: s.end, closed_by: s.closed_by, x1, x2 };
    }
  }
  const i = Math.min(n - 1, Math.max(0, Math.round((mx / width) * (n - 1))));
  return { kind: "price", date: series[i][0], close: series[i][1], x: x(i), y: y(series[i][1]) };
}
