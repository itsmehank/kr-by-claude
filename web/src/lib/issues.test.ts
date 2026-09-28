import { describe, it, expect } from "vitest";
import {
  dependencyState, effectiveStatus, groupItems, GROUP_ORDER, type IssueItem,
} from "./issues";

function item(n: number, over: Partial<IssueItem> = {}): IssueItem {
  return {
    number: n, title: `t${n}`, labels: [], state: "open", gh_updated_at: "2026-09-27T00:00:00Z",
    brief: { summary: "s", group: "ops", start_status: "ready", start_reason: "r", depends_on: [] },
    brief_at: "2026-09-27T00:00:00Z", brief_model: "m", brief_error: null,
    override_status: null, override_note: null, observed_at: "2026-09-27T00:00:00Z",
    ...over,
  };
}

describe("effectiveStatus", () => {
  it("override 가 AI 값보다 우선", () => {
    expect(effectiveStatus(item(1, { override_status: "blocked" }))).toBe("blocked");
    expect(effectiveStatus(item(1))).toBe("ready");
    expect(effectiveStatus(item(1, { brief: null }))).toBeNull();
  });
});

describe("groupItems", () => {
  it("그룹 순서 고정, 빈 그룹 생략, 요약 없는 항목은 unsummarized 로", () => {
    const items = [
      item(3, { brief: { summary: "s", group: "data", start_status: "ready", start_reason: "r", depends_on: [] } }),
      item(2, { brief: null }),
      item(1),
    ];
    const g = groupItems(items, "all");
    expect(g.map((x) => x.group)).toEqual(["data", "ops", "unsummarized"]);
    expect(GROUP_ORDER[0]).toBe("data");
  });
  it("상태 필터는 effectiveStatus 기준, 요약 없는 항목 제외", () => {
    const items = [item(1), item(2, { override_status: "blocked" }), item(3, { brief: null })];
    const g = groupItems(items, "blocked");
    expect(g.flatMap((x) => x.items.map((i) => i.number))).toEqual([2]);
  });
  it("그룹 안은 번호 내림차순", () => {
    const g = groupItems([item(1), item(5), item(3)], "all");
    expect(g[0].items.map((i) => i.number)).toEqual([5, 3, 1]);
  });
});

describe("dependencyState", () => {
  it("open 집합에 없으면 closed", () => {
    const open = new Set([10, 11]);
    expect(dependencyState(10, open)).toBe("open");
    expect(dependencyState(99, open)).toBe("closed");
  });
});
