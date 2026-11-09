import { describe, it, expect } from "vitest";
import { parsePageSize, PAGE_SIZES, DEFAULT_PAGE_SIZE } from "./pageSize";

describe("parsePageSize", () => {
  it("허용값만 통과", () => {
    for (const n of PAGE_SIZES) expect(parsePageSize(String(n))).toBe(n);
  });
  it("없음·이상값 → 기본 5", () => {
    expect(DEFAULT_PAGE_SIZE).toBe(5);
    for (const v of [null, "", "7", "abc", "0", "-5", "100"]) expect(parsePageSize(v)).toBe(5);
  });
});
