import { useRef, useState } from "react";
import type { ReactNode } from "react";
import { GLOSSARY_MAP } from "../../data/llm-pipeline/glossary";

interface Props {
  term: string;       // GLOSSARY_MAP lookup 키
  children?: ReactNode; // 표시할 텍스트 — 생략 시 term 그대로
}

/**
 * 인라인 용어 — hover 시 GLOSSARY 정의 popover 표시.
 * GLOSSARY_MAP 에 정의 없으면 plain text 처럼 렌더 (fallback).
 */
export function TermTooltip({ term, children }: Props) {
  const ref = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  const meaning = GLOSSARY_MAP[term];
  const display = children ?? term;

  // GLOSSARY 미정의 시 plain span (호버 효과 없음)
  if (!meaning) {
    return <span className="num">{display}</span>;
  }

  function show() {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const width = 360;
    const margin = 8;
    const vw = window.innerWidth;
    let left = r.left;
    if (left + width + margin > vw) left = vw - width - margin;
    if (left < margin) left = margin;
    setPos({ top: r.bottom + 6, left });
    setOpen(true);
  }

  return (
    <>
      <span
        ref={ref}
        onMouseEnter={show}
        onMouseLeave={() => setOpen(false)}
        onFocus={show}
        onBlur={() => setOpen(false)}
        tabIndex={0}
        className="num underline decoration-dotted underline-offset-2 cursor-help text-accent hover:text-ink focus:outline-none"
      >
        {display}
      </span>
      {open && (
        <div
          role="tooltip"
          className="fixed z-50 bg-paper border border-hairline shadow-bento-hover rounded-xl px-4 py-3 text-data text-ink"
          style={{ top: pos.top, left: pos.left, width: 360 }}
        >
          <div className="text-data-xs caps text-faint mb-1">{term}</div>
          {meaning}
        </div>
      )}
    </>
  );
}
