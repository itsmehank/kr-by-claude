import { describe, it, expect } from "vitest";
import {
  hasIdentifiedPattern,
  matchesPresenceFilters,
} from "./classificationFilters";

describe("hasIdentifiedPattern", () => {
  it("null 과 'none' 은 패턴 없음", () => {
    expect(hasIdentifiedPattern(null)).toBe(false);
    expect(hasIdentifiedPattern("none")).toBe(false);
  });
  it("실제 패턴명은 있음", () => {
    expect(hasIdentifiedPattern("cup_with_handle")).toBe(true);
    expect(hasIdentifiedPattern("flat_base")).toBe(true);
  });
});

describe("matchesPresenceFilters", () => {
  const withBoth = { pattern: "flat_base", pivot_price: 1000 };
  const noPattern = { pattern: "none", pivot_price: 1000 };
  const noPivot = { pattern: "flat_base", pivot_price: null };
  const neither = { pattern: null, pivot_price: null };

  it("필터 꺼짐이면 전부 통과", () => {
    const off = { hasPattern: false, hasPivot: false };
    expect(matchesPresenceFilters(neither, off)).toBe(true);
  });

  it("hasPattern 만 켜짐: 패턴 있는 행만", () => {
    const f = { hasPattern: true, hasPivot: false };
    expect(matchesPresenceFilters(withBoth, f)).toBe(true);
    expect(matchesPresenceFilters(noPivot, f)).toBe(true);
    expect(matchesPresenceFilters(noPattern, f)).toBe(false);
  });

  it("hasPivot 만 켜짐: pivot 있는 행만", () => {
    const f = { hasPattern: false, hasPivot: true };
    expect(matchesPresenceFilters(withBoth, f)).toBe(true);
    expect(matchesPresenceFilters(noPattern, f)).toBe(true);
    expect(matchesPresenceFilters(noPivot, f)).toBe(false);
  });

  it("둘 다 켜짐: pattern AND pivot 모두 있어야", () => {
    const f = { hasPattern: true, hasPivot: true };
    expect(matchesPresenceFilters(withBoth, f)).toBe(true);
    expect(matchesPresenceFilters(noPattern, f)).toBe(false);
    expect(matchesPresenceFilters(noPivot, f)).toBe(false);
    expect(matchesPresenceFilters(neither, f)).toBe(false);
  });
});
