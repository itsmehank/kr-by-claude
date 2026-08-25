import { describe, expect, it } from "vitest";
import { buildChart, triggerColor } from "./streakChart";

const series: [string, number][] = [
  ["2026-06-01", 100], ["2026-06-02", 102], ["2026-06-03", 101],
  ["2026-06-04", 105], ["2026-06-05", 110],
];

describe("triggerColor", () => {
  it("trigger_type 축 매핑 — decision 축 아님", () => {
    expect(triggerColor("breakout")).toBe("#16a34a");
    expect(triggerColor("breakout_from_watch")).toBe("#16a34a");
    expect(triggerColor("promotion")).toBe("#f59e0b");
    expect(triggerColor("invalidation")).toBe("#9ca3af");
  });
});

describe("buildChart", () => {
  const base = { width: 100, height: 40, to: "2026-06-05", series,
    pivotSteps: [["2026-06-02", "2026-06-04", 104] as [string, string | null, number]],
    streaks: [{ start: "2026-06-02", end: "2026-06-04", closed_by: "ignore" as const,
                censored: false, backfilled: false, has_gap: false }],
    triggers: [{ d: "2026-06-03", trigger_type: "promotion" }] };

  it("가격 폴리라인은 5점, x 는 인덱스 등간격", () => {
    const out = buildChart(base);
    expect(out.pricePoints.split(" ")).toHaveLength(5);
    expect(out.pricePoints.startsWith("0.0,")).toBe(true); // toFixed(1) → "0.0"
  });
  it("계단·띠·점의 x 범위가 날짜에 대응하고 닫힘 마커가 붙는다", () => {
    const out = buildChart(base);
    expect(out.steps).toHaveLength(1);
    expect(out.steps[0].x1).toBeLessThan(out.steps[0].x2);
    expect(out.bands[0].marker).toBe("o");        // ignore → ○
    expect(out.dots[0].color).toBe("#f59e0b");
  });
  it("진행중 streak 는 우측 끝까지, disqualify 는 x 마커", () => {
    const out = buildChart({ ...base,
      streaks: [{ start: "2026-06-02", end: null, closed_by: null,
                  censored: true, backfilled: false, has_gap: true }] });
    expect(out.bands[0].x2).toBe(100);
    expect(out.bands[0].marker).toBeNull();
    expect(out.bands[0].dashed).toBe(true);       // has_gap → 점선
    expect(out.bands[0].censored).toBe(true);
    const closed = buildChart({ ...base,
      streaks: [{ start: "2026-06-02", end: "2026-06-04",
                  closed_by: "disqualify" as const,
                  censored: false, backfilled: false, has_gap: false }] });
    expect(closed.bands[0].marker).toBe("x");     // 실격 → ✕ (스펙 §3 회귀 가드)
  });
});
