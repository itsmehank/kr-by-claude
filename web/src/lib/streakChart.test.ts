import { describe, expect, it } from "vitest";
import { buildChart, hitTest, mapClientToChart, triggerColor } from "./streakChart";

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
  it("steps·bands·dots 가 툴팁용 메타(날짜·값·사유)를 함께 반환한다", () => {
    const out = buildChart(base);
    expect(out.steps[0]).toMatchObject({
      from: "2026-06-02", to: "2026-06-04", pivot: 104 });
    expect(out.bands[0]).toMatchObject({
      start: "2026-06-02", end: "2026-06-04", closed_by: "ignore" });
    expect(out.dots[0]).toMatchObject({
      d: "2026-06-03", trigger_type: "promotion" });
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

describe("mapClientToChart", () => {
  const vb = { vbW: 940, vbH: 360, padX: 20, padY: 10 };

  it("종횡비 일치(letterbox 없음) — 단일 배율 역변환", () => {
    // rect 470x180 = viewBox 절반 → scale 0.5, 여백 0
    const rect = { left: 100, top: 50, width: 470, height: 180 };
    expect(mapClientToChart(vb, rect, 100 + (20 + 30) * 0.5, 50 + (10 + 40) * 0.5))
      .toEqual({ mx: 30, my: 40 });
  });
  it("세로가 눌린 rect(letterbox 좌우 여백)도 정확히 역변환한다", () => {
    // height 90 = vbH×0.25 < width 비율 → scale 0.25, 가로 여백 (470-235)/2
    const rect = { left: 0, top: 0, width: 470, height: 90 };
    const ox = (470 - 940 * 0.25) / 2;
    expect(mapClientToChart(vb, rect, ox + (20 + 30) * 0.25, (10 + 40) * 0.25))
      .toEqual({ mx: 30, my: 40 });
  });
});

describe("hitTest", () => {
  // width 100 · height 40 · min 100 · max 110(> pivot 104) → x(i)=25i, y(v)=40−4(v−100).
  // dot(06-03, close 101) = (50, 36) / step y = y(104) = 24, x 25~75 / bandY = 46.
  const input = { width: 100, height: 40, to: "2026-06-05", series,
    pivotSteps: [["2026-06-02", "2026-06-04", 104] as [string, string | null, number]],
    streaks: [{ start: "2026-06-02", end: "2026-06-04", closed_by: "ignore" as const,
                censored: false, backfilled: false, has_gap: false }],
    triggers: [{ d: "2026-06-03", trigger_type: "promotion", decision: "wait",
                 close: 101, pivot_price: 104 }] };

  it("트리거 점이 반경 8 안에서 메타(decision·close·pivot)와 함께 잡힌다", () => {
    expect(hitTest(input, 52, 33)).toMatchObject({
      kind: "dot", date: "2026-06-03", trigger_type: "promotion",
      decision: "wait", close: 101, pivot_price: 104,
    });
  });
  it("점·계단이 겹치면 점이 우선", () => {
    // (50,30): dot 거리 6 ≤ 8 AND step |30−24| = 6 ≤ 6 — 둘 다 매치 → dot
    expect(hitTest(input, 50, 30)).toMatchObject({ kind: "dot" });
  });
  it("계단 hit: x 구간 내·y 오차 ±6, from/to/pivot 반환", () => {
    expect(hitTest(input, 60, 26)).toMatchObject({
      kind: "step", from: "2026-06-02", to: "2026-06-04", pivot: 104,
    });
    // |31−24| = 7 > 6 → 계단 아님 → price 폴백
    expect(hitTest(input, 60, 31)).toMatchObject({ kind: "price" });
  });
  it("띠 hit: bandY ±8, 기간·닫힘 사유 반환", () => {
    expect(hitTest(input, 60, 46)).toMatchObject({
      kind: "band", start: "2026-06-02", end: "2026-06-04", closed_by: "ignore",
    });
  });
  it("닫힘 마커 글리프 영역(x2 우측 근접)도 band 로 잡힌다", () => {
    // band x2 = 75, ✕/○ 글리프는 x2 에서 우측으로 그려짐 → x2+10 까지 band 판정
    expect(hitTest(input, 82, 46)).toMatchObject({
      kind: "band", start: "2026-06-02", closed_by: "ignore" });
  });
  it("진행중(닫힘 마커 없음) band 는 끝 우측으로 확장되지 않는다", () => {
    const open = { ...input,
      streaks: [{ start: "2026-06-02", end: "2026-06-03", closed_by: null,
                  censored: false, backfilled: false, has_gap: false }] };
    // x2 = x(idx("2026-06-03")) = 50 — 마커가 없으니 58 은 band 아님 → price 폴백
    expect(hitTest(open, 58, 46)).toMatchObject({ kind: "price" });
  });
  it("빈 곳은 price 폴백 — 인덱스 역산으로 날짜·종가", () => {
    // i = round(88/100 × 4) = 4 → 06-05, 110
    expect(hitTest(input, 88, 5)).toMatchObject({
      kind: "price", date: "2026-06-05", close: 110,
    });
  });
  it("진행중 계단(to null)은 우측 끝까지 매치되고 to null 유지", () => {
    const open = { ...input,
      pivotSteps: [["2026-06-02", null, 104] as [string, string | null, number]] };
    expect(hitTest(open, 90, 24)).toMatchObject({ kind: "step", to: null });
  });
  it("n<2 이면 null", () => {
    expect(hitTest({ ...input, series: [["2026-06-01", 100]] as [string, number][] },
                   10, 10)).toBeNull();
  });
  it("차트 범위 밖이면 null (좌우·띠 아래)", () => {
    expect(hitTest(input, -5, 20)).toBeNull();
    expect(hitTest(input, 105, 20)).toBeNull();
    expect(hitTest(input, 50, 55)).toBeNull();   // bandY 46 + 8 초과
  });
});
