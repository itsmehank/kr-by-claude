import { describe, it, expect } from "vitest";
import { buildStockTimeline } from "./stockTimeline";
import type { ReviewRow, ReviewTrigger } from "./types";

function trigger(d: string, over: Partial<ReviewTrigger> = {}): ReviewTrigger {
  return {
    evaluated_at: `${d}T09:00:00+09:00`,
    d,
    trigger_type: "promotion",
    decision: "wait",
    close: 10000,
    pivot_price: 10500,
    reasoning: null,
    ...over,
  };
}

function row(key_date: string, over: Partial<ReviewRow> = {}): ReviewRow {
  return {
    symbol: "005930",
    name: "삼성전자",
    market: "KOSPI",
    source: "daily_delta",
    classified_at: `${key_date}T18:00:00+09:00`,
    analyzed_for_date: key_date,
    key_date,
    classification: "watch",
    pattern: "cup_with_handle",
    pivot_price: 10000,
    status: "미발동",
    first_breakout_at: null,
    first_breakout_type: null,
    first_breakout_decision: null,
    promotion_at: null,
    trigger_count: 0,
    t5_pct: null,
    t20_pct: null,
    max_reach_pct: null,
    corp_action_flag: false,
    spark: [],
    pivot_baseline: null,
    triggers: [],
    ...over,
  };
}

describe("buildStockTimeline — 분석·트리거 병합 (issue #127)", () => {
  it("빈 입력 → 빈 배열", () => {
    expect(buildStockTimeline([])).toEqual([]);
  });

  it("(a) 날짜 오름차순 정렬 — 분석만 있는 입력", () => {
    const events = buildStockTimeline([row("2026-08-14"), row("2026-07-27"), row("2026-08-05")]);
    expect(events.map((e) => e.date)).toEqual(["2026-07-27", "2026-08-05", "2026-08-14"]);
  });

  it("(b) 동일 날짜에 분석·트리거가 있으면 분석이 먼저 온다", () => {
    const events = buildStockTimeline([
      row("2026-08-20", { triggers: [trigger("2026-08-20")] }),
    ]);
    expect(events.map((e) => e.kind)).toEqual(["analysis", "trigger"]);
  });

  it("(c) 트리거만 있는 입력 — 분석 없이 트리거만 병합된다", () => {
    const events = buildStockTimeline([
      row("2026-08-01", { triggers: [trigger("2026-08-20")] }),
    ]);
    // 분석 이벤트(08-01) + 트리거 이벤트(08-20) 순서로 날짜 오름차순
    expect(events.map((e) => e.kind)).toEqual(["analysis", "trigger"]);
    expect(events.map((e) => e.date)).toEqual(["2026-08-01", "2026-08-20"]);
  });

  it("(c) 여러 종목의 분석·트리거가 섞여도 날짜 오름차순 단일 배열로 병합된다", () => {
    const events = buildStockTimeline([
      row("2026-08-05", { symbol: "AAA", triggers: [trigger("2026-08-10", { trigger_type: "invalidation" })] }),
      row("2026-08-07", { symbol: "BBB" }),
    ]);
    expect(events.map((e) => e.date)).toEqual(["2026-08-05", "2026-08-07", "2026-08-10"]);
  });

  it("직전 분석 대비 pivot_price 변경 없음 — pivotChanged=false, previousPivotPrice=직전 값", () => {
    const events = buildStockTimeline([
      row("2026-07-27", { pivot_price: 23600 }),
      row("2026-08-05", { pivot_price: 23600 }),
    ]);
    const second = events[1];
    if (second.kind !== "analysis") throw new Error("expected analysis event");
    expect(second.pivotChanged).toBe(false);
    expect(second.previousPivotPrice).toBe(23600);
  });

  it("직전 분석 대비 pivot_price 변경 있음 — pivotChanged=true", () => {
    const events = buildStockTimeline([
      row("2026-07-27", { pivot_price: 23600 }),
      row("2026-08-05", { pivot_price: 23900 }),
    ]);
    const second = events[1];
    if (second.kind !== "analysis") throw new Error("expected analysis event");
    expect(second.pivotChanged).toBe(true);
    expect(second.previousPivotPrice).toBe(23600);
  });

  it("첫 분석 이벤트는 직전이 없어 pivotChanged/classificationChanged=false, previousPivotPrice=null", () => {
    const events = buildStockTimeline([row("2026-07-27", { pivot_price: 23600, classification: "watch" })]);
    const first = events[0];
    if (first.kind !== "analysis") throw new Error("expected analysis event");
    expect(first.pivotChanged).toBe(false);
    expect(first.classificationChanged).toBe(false);
    expect(first.previousPivotPrice).toBeNull();
  });

  it("직전 분석 대비 classification 변경(watch→entry) — classificationChanged=true (DC-10)", () => {
    const events = buildStockTimeline([
      row("2026-08-14", { classification: "watch" }),
      row("2026-08-20", { classification: "entry" }),
    ]);
    const second = events[1];
    if (second.kind !== "analysis") throw new Error("expected analysis event");
    expect(second.classificationChanged).toBe(true);
  });

  it("동일 날짜·동일 종류 이벤트는 입력 순서를 유지한다(안정 정렬)", () => {
    const events = buildStockTimeline([
      row("2026-08-05", { symbol: "AAA" }),
      row("2026-08-05", { symbol: "BBB" }),
    ]);
    const symbols = events
      .filter((e): e is import("./stockTimeline").TimelineAnalysisEvent => e.kind === "analysis")
      .map((e) => e.row.symbol);
    expect(symbols).toEqual(["AAA", "BBB"]);
  });
});
