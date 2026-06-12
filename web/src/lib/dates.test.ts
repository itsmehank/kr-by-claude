import { describe, it, expect } from "vitest";
import { kstDateISO, todayKstISO, nDaysAgoKstISO, thisWeekMondayKstISO } from "./dates";

// 핵심 버그 케이스: KST 자정~09시 = UTC 기준 "어제".
// new Date().toISOString().slice(0,10) 는 이 시간대에 하루 밀린 날짜를 준다.
const KST_3AM = new Date("2026-06-12T18:00:00Z"); // = KST 2026-06-13 03:00

describe("kstDateISO", () => {
  it("KST 자정~09시 구간에서 UTC 가 아니라 KST 날짜를 반환", () => {
    expect(KST_3AM.toISOString().slice(0, 10)).toBe("2026-06-12"); // UTC (버그 동작)
    expect(kstDateISO(KST_3AM)).toBe("2026-06-13"); // KST (올바름)
  });

  it("KST 낮 시간(UTC 와 같은 날짜)에는 동일", () => {
    const noon = new Date("2026-06-12T03:00:00Z"); // KST 12:00
    expect(kstDateISO(noon)).toBe("2026-06-12");
  });
});

describe("todayKstISO", () => {
  it("YYYY-MM-DD 형식", () => {
    expect(todayKstISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe("nDaysAgoKstISO", () => {
  it("KST 기준 n일 전 (자정 경계 포함)", () => {
    expect(nDaysAgoKstISO(1, KST_3AM)).toBe("2026-06-12"); // KST 6/13 의 1일 전
    expect(nDaysAgoKstISO(7, KST_3AM)).toBe("2026-06-06");
  });
});

describe("thisWeekMondayKstISO", () => {
  it("KST 토요일 새벽(UTC 금요일 저녁)에 이번 주 월요일 반환", () => {
    const satDawn = new Date("2026-06-12T18:00:00Z"); // KST 토 6/13 03:00
    expect(thisWeekMondayKstISO(satDawn)).toBe("2026-06-08"); // 6/8 월
  });

  it("KST 월요일 오전 9시 전에도 그 월요일 자신을 반환 (기존 혼용 버그: 일요일로 계산)", () => {
    const monDawn = new Date("2026-06-07T18:00:00Z"); // KST 월 6/8 03:00
    expect(thisWeekMondayKstISO(monDawn)).toBe("2026-06-08");
  });

  it("KST 일요일은 6일 전 월요일", () => {
    const sunNoon = new Date("2026-06-14T03:00:00Z"); // KST 일 6/14 12:00
    expect(thisWeekMondayKstISO(sunNoon)).toBe("2026-06-08");
  });
});
