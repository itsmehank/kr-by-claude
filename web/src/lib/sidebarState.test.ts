import { describe, it, expect } from "vitest";
import { sidebarReducer, isCollapsed, initialSidebar, type SidebarState } from "./sidebarState";

const run = (s: SidebarState, ...actions: Parameters<typeof sidebarReducer>[1][]) =>
  actions.reduce(sidebarReducer, s);

describe("sidebarReducer", () => {
  it("펼침 저장 상태에서 자동 접기 → 접힘, 저장값은 그대로", () => {
    const s = run(initialSidebar(false), { type: "beginVisit" }, { type: "autoCollapse" });
    expect(isCollapsed(s)).toBe(true);
    expect(s.saved).toBe(false);
  });

  it("페이지 이탈 → 자동 접기 해제(원래 펼침으로)", () => {
    const s = run(initialSidebar(false), { type: "beginVisit" }, { type: "autoCollapse" }, { type: "endVisit" });
    expect(isCollapsed(s)).toBe(false);
  });

  it("자동 접힘 중 사용자가 펼치면 같은 방문 동안 다시 접지 않음", () => {
    const s = run(
      initialSidebar(false),
      { type: "beginVisit" },
      { type: "autoCollapse" },
      { type: "userToggle" },
      { type: "autoCollapse" },
    );
    expect(isCollapsed(s)).toBe(false);
    expect(s.saved).toBe(false);
  });

  it("다음 방문에서는 다시 자동 접기", () => {
    const s = run(
      initialSidebar(false),
      { type: "beginVisit" }, { type: "autoCollapse" }, { type: "userToggle" }, { type: "endVisit" },
      { type: "beginVisit" }, { type: "autoCollapse" },
    );
    expect(isCollapsed(s)).toBe(true);
  });

  it("사용자가 접어 둔 상태(저장 접힘)는 이탈 후에도 접힘 유지", () => {
    const s = run(initialSidebar(true), { type: "beginVisit" }, { type: "autoCollapse" }, { type: "endVisit" });
    expect(isCollapsed(s)).toBe(true);
    expect(s.saved).toBe(true);
  });

  it("사용자 토글은 저장값을 바꿈", () => {
    expect(run(initialSidebar(false), { type: "userToggle" }).saved).toBe(true);
    expect(run(initialSidebar(true), { type: "userToggle" }).saved).toBe(false);
  });

  it("방문 밖에서 autoCollapse 는 무시", () => {
    expect(isCollapsed(run(initialSidebar(false), { type: "autoCollapse" }))).toBe(false);
  });
});
