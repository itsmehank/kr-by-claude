export type BandState = "entry" | "watch" | "ignore" | "fail";

export interface BandSegment {
  startDate: string; // YYYY-MM-DD inclusive
  endDate: string;   // YYYY-MM-DD inclusive
  state: BandState;
}

export const BAND_COLORS: Record<BandState, string> = {
  entry: "rgba(22,163,74,0.18)",
  watch: "rgba(37,99,235,0.18)",
  ignore: "rgba(156,163,175,0.18)",
  fail: "rgba(220,38,38,0.18)",
};

export const BAND_LABELS: Record<BandState, string> = {
  entry: "entry",
  watch: "watch",
  ignore: "ignore",
  fail: "미통과/탈락",
};

export interface BandBar {
  date: string;
  minervini_pass: boolean | null;
}

export interface ClassificationPoint {
  date: string;
  classification: string;
}

const COLORED = new Set<string>(["entry", "watch", "ignore"]);

/**
 * 날짜별 배타 상태로 분류 밴드 세그먼트 생성.
 * minervini_pass === false → "fail"(우선). 아니면 그 날짜 이하 가장 최근 분류(entry/watch/ignore) 이월(carry-forward).
 * disqualified/분류없음 → 밴드 없음. 연속 동일 상태는 병합. bars/points 는 날짜 오름차순 가정(points 방어적 정렬).
 */
export function buildBandSegments(
  bars: BandBar[],
  points: ClassificationPoint[],
): BandSegment[] {
  const sorted = [...points].sort((a, b) => a.date.localeCompare(b.date));
  const segments: BandSegment[] = [];
  let pi = 0;
  let carried: BandState | null = null;
  let cur: BandSegment | null = null;

  for (const bar of bars) {
    while (pi < sorted.length && sorted[pi].date <= bar.date) {
      const c = sorted[pi].classification;
      carried = COLORED.has(c) ? (c as BandState) : null;
      pi++;
    }
    const state: BandState | null = bar.minervini_pass === false ? "fail" : carried;

    if (state === null) {
      if (cur) { segments.push(cur); cur = null; }
      continue;
    }
    if (cur && cur.state === state) {
      cur.endDate = bar.date;
    } else {
      if (cur) segments.push(cur);
      cur = { startDate: bar.date, endDate: bar.date, state };
    }
  }
  if (cur) segments.push(cur);
  return segments;
}
