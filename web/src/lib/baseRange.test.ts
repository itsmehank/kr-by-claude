import { describe, it, expect } from "vitest";
import { baseRangeDates } from "./baseRange";

const dates = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06"];

describe("baseRangeDates", () => {
  it("시작일부터 끝까지", () => {
    expect(baseRangeDates(dates, "2026-08-05")).toEqual(["2026-08-05", "2026-08-06"]);
  });
  it("시작일이 휴장일이면 그 다음 거래일부터", () => {
    expect(baseRangeDates(dates, "2026-08-04T00:00:00")).toEqual(["2026-08-04", "2026-08-05", "2026-08-06"]);
    expect(baseRangeDates(["2026-08-03", "2026-08-06"], "2026-08-04")).toEqual(["2026-08-06"]);
  });
  it("시작일이 창보다 앞이면 창 시작부터(전 구간)", () => {
    expect(baseRangeDates(dates, "2025-01-01")).toEqual(dates);
  });
  it("시작일 없음 → 전 구간, 데이터 없음 → 빈 배열", () => {
    expect(baseRangeDates(dates, null)).toEqual(dates);
    expect(baseRangeDates([], "2026-08-05")).toEqual([]);
  });
  it("시작일이 창보다 뒤면 빈 배열", () => {
    expect(baseRangeDates(dates, "2026-09-01")).toEqual([]);
  });
});
