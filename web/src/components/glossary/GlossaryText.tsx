import { useMemo } from "react";
import { matchGlossary } from "../../data/reasoningGlossary";
import { GlossaryTerm } from "./GlossaryTerm";

/** 일반 텍스트 reasoning — 사전 용어에 밑줄 + 마우스 오버 설명 */
export function GlossaryText({ text, inButton = false }: { text: string; inButton?: boolean }) {
  const segs = useMemo(() => matchGlossary(text), [text]);
  return (
    <>
      {segs.map((s, i) =>
        s.kind === "text" ? s.text : <GlossaryTerm key={i} id={s.id} text={s.text} inButton={inButton} />,
      )}
    </>
  );
}
