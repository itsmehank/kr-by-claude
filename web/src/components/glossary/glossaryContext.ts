import { createContext, useContext } from "react";

export interface GlossaryContextValue {
  open: boolean;
  setOpen: (open: boolean) => void;
  /** 검색 창에서 펼쳐 보여줄 항목. n 은 같은 id 를 다시 눌러도 스크롤되게 하는 카운터 */
  focus: { id: string; n: number } | null;
  openEntry: (id: string) => void;
}

export const GlossaryContext = createContext<GlossaryContextValue | null>(null);

/** Provider 밖이면 null — 용어 클릭은 툴팁만 동작하고 검색 창 연동은 생략된다. */
export function useGlossary(): GlossaryContextValue | null {
  return useContext(GlossaryContext);
}
