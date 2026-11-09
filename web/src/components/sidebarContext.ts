import { createContext, useContext, useEffect } from "react";

export interface SidebarControl {
  beginVisit: () => void;
  endVisit: () => void;
  autoCollapse: () => void;
}

export const SidebarContext = createContext<SidebarControl | null>(null);

/** 자동 접기를 쓰는 페이지용(#275): 마운트 동안을 '방문'으로 등록하고, 접기 요청 함수를 돌려준다.
 *  페이지를 떠나면(언마운트) 자동으로 접었던 내비가 원래 상태로 돌아온다. */
export function useSidebarAutoCollapse(): () => void {
  const ctl = useContext(SidebarContext);
  useEffect(() => {
    if (!ctl) return;
    ctl.beginVisit();
    return () => ctl.endVisit();
  }, [ctl]);
  return ctl?.autoCollapse ?? noop;
}

function noop() {}
