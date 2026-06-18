import { describe, it, expect } from "vitest";
import { summarizeWeekendRun } from "./runDetails";

const NOW = Date.parse("2026-06-18T12:00:00Z");

describe("summarizeWeekendRun", () => {
  it("step-shape(chain) details 는 null 반환 — 기존 step 렌더 사용", () => {
    const chain = { drift: { detected: 2 }, ohlcv: { rows: 100 } };
    expect(summarizeWeekendRun(chain, "succeeded", NOW)).toBeNull();
  });

  it("null details → null", () => {
    expect(summarizeWeekendRun(null, "succeeded", NOW)).toBeNull();
  });

  it("entry_params 형태({processed,failures}, failed_tickers 없음)는 null — weekend 오인 방지", () => {
    expect(summarizeWeekendRun({ processed: 5, failures: 0 }, "succeeded", NOW)).toBeNull();
  });

  it("완료된 weekend: 요약 + 실패종목 리스트, progress 없음", () => {
    const done = {
      processed: 100,
      candidates: 120,
      failures: 2,
      skipped_existing: 18,
      failed_tickers: [
        { symbol: "005930", error: "timeout", attempts: 3 },
        { symbol: "000660", error: "cli error", attempts: 2 },
      ],
      integrity_skipped: [{ symbol: "X" }],
    };
    const v = summarizeWeekendRun(done, "succeeded", NOW);
    expect(v).not.toBeNull();
    expect(v!.failedTickers).toHaveLength(2);
    expect(v!.failedTickers[0]).toEqual({ symbol: "005930", error: "timeout", attempts: 3 });
    expect(v!.progress).toBeNull();
    expect(v!.stale).toBe(false);
    const sumText = v!.summary.map((s) => `${s.label}:${s.value}`).join(",");
    expect(sumText).toContain("100"); // 처리
    expect(sumText).toContain("2"); // 실패
  });

  it("실행중 weekend: 진행(done/total/inFlight/failed) 반환, heartbeat 신선하면 stale=false", () => {
    const running = {
      weekend_progress: { done: 30, total: 120, in_flight: 4, failed: 1 },
      heartbeat_at: "2026-06-18T11:59:40Z", // 20초 전
    };
    const v = summarizeWeekendRun(running, "running", NOW);
    expect(v).not.toBeNull();
    expect(v!.progress).toEqual({ done: 30, total: 120, inFlight: 4, failed: 1 });
    expect(v!.stale).toBe(false);
  });

  it("실행중인데 heartbeat 오래됨(>2분) → stale=true", () => {
    const stuck = {
      weekend_progress: { done: 30, total: 120, in_flight: 4, failed: 1 },
      heartbeat_at: "2026-06-18T11:55:00Z", // 5분 전
    };
    const v = summarizeWeekendRun(stuck, "running", NOW);
    expect(v!.stale).toBe(true);
  });

  it("완료/성공 상태는 heartbeat 없어도 stale 아님", () => {
    const done = { processed: 5, candidates: 5, failures: 0, failed_tickers: [] };
    expect(summarizeWeekendRun(done, "succeeded", NOW)!.stale).toBe(false);
  });
});
