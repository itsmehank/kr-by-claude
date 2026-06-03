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

// 범례 스와치용 솔리드 색 (BAND_COLORS 의 불투명 원색 — 작은 스와치는 반투명이면 잘 안 보임).
export const BAND_SWATCH: Record<BandState, string> = {
  entry: "#16a34a",
  watch: "#2563eb",
  ignore: "#9ca3af",
  fail: "#dc2626",
};

// 범례/순회용 표시 순서.
export const BAND_ORDER: BandState[] = ["entry", "watch", "ignore", "fail"];

export interface BandBar {
  date: string;
}

export interface ClassificationPoint {
  date: string;
  classification: string;
}

const COLORED = new Set<string>(["entry", "watch", "ignore"]);

/**
 * 날짜별 분류 상태(sticky)로 밴드 세그먼트 생성.
 * 밴드는 "분류 시계열"만 본다(일별 minervini 지표는 보지 않음 — 그건 매일 출렁이므로).
 * 각 bar 날짜의 상태 = 그 날짜 이하 가장 최근 분류를 이월(carry-forward):
 *   entry/watch/ignore → 해당 색, disqualified → "fail"(빨강) 으로 다음 분류 전까지 유지.
 *   그 외 미지정 문자열은 carry 를 건드리지 않음(데이터 오염에 안전).
 * 첫 분류 이전(carry 없음) → 밴드 없음. 연속 동일 상태는 병합. bars/points 는 날짜 오름차순 가정(points 방어적 정렬).
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
      if (COLORED.has(c)) carried = c as BandState;
      else if (c === "disqualified") carried = "fail";
      pi++;
    }
    const state: BandState | null = carried;

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
