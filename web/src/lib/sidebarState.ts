// 왼쪽 내비 접힘 상태(#275). 사용자가 저장한 선호(saved)와 페이지가 잠시 접는 상태(auto)를 분리한다.
// - 화면 표시 = saved || auto
// - 저장(localStorage)은 사용자 토글로 saved 가 바뀔 때만 한다(자동 접기는 저장값을 바꾸지 않음)

export interface SidebarState {
  saved: boolean;
  auto: boolean;
  /** 자동 접기를 쓰는 페이지에 머무는 중 */
  inVisit: boolean;
  /** 이번 방문에서 사용자가 직접 펼침 → 다시 자동으로 접지 않음 */
  userOverrode: boolean;
}

export type SidebarAction =
  | { type: "userToggle" }
  | { type: "beginVisit" }
  | { type: "endVisit" }
  | { type: "autoCollapse" };

export function initialSidebar(saved: boolean): SidebarState {
  return { saved, auto: false, inVisit: false, userOverrode: false };
}

export function isCollapsed(s: SidebarState): boolean {
  return s.saved || s.auto;
}

export function sidebarReducer(s: SidebarState, a: SidebarAction): SidebarState {
  switch (a.type) {
    case "userToggle":
      if (isCollapsed(s)) return { ...s, saved: false, auto: false, userOverrode: s.inVisit };
      return { ...s, saved: true };
    case "beginVisit":
      return { ...s, inVisit: true, auto: false, userOverrode: false };
    case "endVisit":
      return { ...s, inVisit: false, auto: false, userOverrode: false };
    case "autoCollapse":
      if (!s.inVisit || s.userOverrode || isCollapsed(s)) return s;
      return { ...s, auto: true };
  }
}
