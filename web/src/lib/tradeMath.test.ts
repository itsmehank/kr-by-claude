import { describe, expect, it } from "vitest";
import { estimateAmount } from "./tradeMath";

describe("estimateAmount", () => {
  it("limit = price × qty as integer string", () => {
    expect(estimateAmount("LIMIT", "70000", "10", "91000")).toEqual({ amount: "700000", basis: "limit" });
  });
  it("market uses upper limit", () => {
    expect(estimateAmount("MARKET", null, "10", "91000")).toEqual({ amount: "910000", basis: "upper_limit" });
  });
  it("returns null when inputs incomplete", () => {
    expect(estimateAmount("LIMIT", "", "10", "91000")).toBeNull();
    expect(estimateAmount("MARKET", null, "10", null)).toBeNull();
    expect(estimateAmount("LIMIT", "70000", "0", "91000")).toBeNull();
  });
  it("handles large values without float rounding", () => {
    expect(estimateAmount("LIMIT", "1234567", "98765", null)!.amount).toBe("121932009755");   // 1234567×98765 (python 실측)
  });
});
