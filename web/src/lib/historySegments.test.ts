import { describe, it, expect } from "vitest";
import { groupHistorySegments } from "./historySegments";
import type { ClassificationHistoryRow } from "./types";

function row(date: string, classification: string, over: Partial<ClassificationHistoryRow> = {}): ClassificationHistoryRow {
  return {
    symbol: "T", date, classification, source: "backfill",
    pattern: "flat_base", confidence: 0.7, reasoning: `사유 ${date}`,
    ...over,
  };
}

describe("groupHistorySegments — 변화점 구간 그룹핑 (스펙 §4)", () => {
  it("빈 입력 → 빈 배열", () => {
    expect(groupHistorySegments([])).toEqual([]);
  });

  it("단일 구간: 연속 동일 분류는 한 구간, N주=행 수", () => {
    const segs = groupHistorySegments([row("2025-06-14", "watch"), row("2025-06-21", "watch")]);
    expect(segs).toHaveLength(1);
    expect(segs[0].classification).toBe("watch");
    expect(segs[0].startDate).toBe("2025-06-14");
    expect(segs[0].endDate).toBe("2025-06-21");
    expect(segs[0].weeks).toHaveLength(2);
  });

  it("분류 교차 시 분할 + 출력은 최신 구간 먼저", () => {
    const segs = groupHistorySegments([
      row("2025-06-14", "watch"), row("2025-06-21", "entry"), row("2025-06-28", "watch"),
    ]);
    expect(segs.map((s) => s.classification)).toEqual(["watch", "entry", "watch"]);
    expect(segs[0].startDate).toBe("2025-06-28"); // 최신 우선
  });

  it("미분석 갭은 구간을 끊지 않음 (스펙: 다른 분류가 끼어야 분할)", () => {
    const segs = groupHistorySegments([
      row("2025-06-14", "watch"), /* 3주 갭 */ row("2025-07-12", "watch"),
    ]);
    expect(segs).toHaveLength(1);
    expect(segs[0].weeks).toHaveLength(2); // 갭 주는 세지 않음
  });

  it("구간 대표값(pattern/confidence/reasoning)은 구간 첫 주 기준", () => {
    const segs = groupHistorySegments([
      row("2025-06-14", "watch", { pattern: "flat_base", reasoning: "전환 사유" }),
      row("2025-06-21", "watch", { pattern: "cup_with_handle", reasoning: "후속 사유" }),
    ]);
    expect(segs[0].pattern).toBe("flat_base");
    expect(segs[0].reasoning).toBe("전환 사유");
  });

  it("disqualified 도 하나의 구간 (NULL 필드 유지)", () => {
    const segs = groupHistorySegments([
      row("2025-06-14", "watch"),
      row("2025-06-21", "disqualified", { pattern: null, confidence: null, reasoning: null }),
    ]);
    expect(segs[0].classification).toBe("disqualified");
    expect(segs[0].pattern).toBeNull();
  });

  it("가장 오래된 구간에만 truncatedStart=true (창-잘림 보수 표기, 스펙 §4)", () => {
    const segs = groupHistorySegments([
      row("2025-06-14", "watch"), row("2025-06-21", "entry"),
    ]);
    const oldest = segs[segs.length - 1];
    expect(oldest.truncatedStart).toBe(true);
    expect(segs[0].truncatedStart).toBe(false);
  });

  it("입력이 정렬 안 돼 있어도 방어 정렬", () => {
    const segs = groupHistorySegments([row("2025-06-21", "watch"), row("2025-06-14", "watch")]);
    expect(segs[0].startDate).toBe("2025-06-14");
  });
});
