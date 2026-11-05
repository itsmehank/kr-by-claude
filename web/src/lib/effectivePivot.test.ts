import { describe, expect, it } from "vitest";
import { effectivePivotNote } from "./effectivePivot";

describe("effectivePivotNote (#253)", () => {
  it("판독값과 트리거 기준이 다를 때만 안내 문구", () => {
    expect(effectivePivotNote(22050, 23650)).toBe("트리거 기준 23,650원 (래칫)");
  });
  it("같으면 null", () => {
    expect(effectivePivotNote(23650, 23650)).toBeNull();
  });
  it("트리거 기준이 없으면(레거시 행) null", () => {
    expect(effectivePivotNote(22050, null)).toBeNull();
    expect(effectivePivotNote(22050, undefined)).toBeNull();
  });
  it("판독값이 없으면 null", () => {
    expect(effectivePivotNote(null, 23650)).toBeNull();
  });
});
