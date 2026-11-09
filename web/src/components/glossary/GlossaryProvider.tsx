import { useCallback, useMemo, useState, type ReactNode } from "react";
import * as Tooltip from "@radix-ui/react-tooltip";
import { GlossaryContext, type GlossaryContextValue } from "./glossaryContext";

const OPEN_KEY = "kr.glossary.open";

function readOpen(): boolean {
  try {
    return window.localStorage.getItem(OPEN_KEY) === "1";
  } catch {
    return false;
  }
}

export function GlossaryProvider({ children }: { children: ReactNode }) {
  const [open, setOpenState] = useState<boolean>(readOpen);
  const [focus, setFocus] = useState<GlossaryContextValue["focus"]>(null);

  const setOpen = useCallback((v: boolean) => {
    setOpenState(v);
    try {
      window.localStorage.setItem(OPEN_KEY, v ? "1" : "0");
    } catch {
      /* 저장 불가 환경 — 무시 */
    }
  }, []);

  const openEntry = useCallback(
    (id: string) => {
      setOpen(true);
      setFocus((prev) => ({ id, n: (prev?.n ?? 0) + 1 }));
    },
    [setOpen],
  );

  const value = useMemo(() => ({ open, setOpen, focus, openEntry }), [open, setOpen, focus, openEntry]);

  return (
    <GlossaryContext.Provider value={value}>
      <Tooltip.Provider delayDuration={150} skipDelayDuration={300}>
        {children}
      </Tooltip.Provider>
    </GlossaryContext.Provider>
  );
}
