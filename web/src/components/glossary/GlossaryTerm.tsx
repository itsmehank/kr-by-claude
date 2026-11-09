import type { KeyboardEvent, MouseEvent } from "react";
import * as Tooltip from "@radix-ui/react-tooltip";
import { GLOSSARY_BY_ID } from "../../data/reasoningGlossary";
import { formatThreshold, type GlossaryEntry } from "../../lib/glossaryTypes";
import { useGlossary } from "./glossaryContext";

function TipBody({ entry }: { entry: GlossaryEntry }) {
  return (
    <div className="space-y-1.5">
      <div className="font-semibold">{entry.title}</div>
      <div className="leading-relaxed">{entry.short}</div>
      {entry.thresholds && entry.thresholds.length > 0 && (
        <div className="leading-relaxed">
          <div className="text-paper/60">현재 기준</div>
          <ul className="list-disc ml-4">
            {entry.thresholds.map((t) => (
              <li key={t.label}>{formatThreshold(t)}</li>
            ))}
          </ul>
        </div>
      )}
      {entry.meaning && <div className="leading-relaxed text-paper/85">→ {entry.meaning}</div>}
      <div className="text-paper/50 text-data-xs">클릭하면 용어 창에서 자세히 볼 수 있습니다</div>
    </div>
  );
}

interface GlossaryTermProps {
  id: string;
  text: string;
  /** 펼치기 버튼 안에 있을 때 — 포커스 요소를 만들지 않는다(버튼 안 포커스 요소는 잘못된 HTML) */
  inButton?: boolean;
}

export function GlossaryTerm({ id, text, inButton = false }: GlossaryTermProps) {
  const g = useGlossary();
  const entry = GLOSSARY_BY_ID[id];
  if (!entry) return <>{text}</>;

  const open = (e: MouseEvent | KeyboardEvent) => {
    // 버튼형 행에서 용어 클릭이 행 접기로 전파되지 않게
    e.stopPropagation();
    e.preventDefault();
    g?.openEntry(id);
  };

  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <span
          role={inButton ? undefined : "button"}
          tabIndex={inButton ? undefined : 0}
          onClick={open}
          onKeyDown={(e) => {
            if (!inButton && (e.key === "Enter" || e.key === " ")) open(e);
          }}
          className="underline decoration-dotted decoration-faint underline-offset-[3px] cursor-help hover:decoration-accent focus:outline-none focus-visible:decoration-accent"
        >
          {text}
        </span>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="top"
          sideOffset={6}
          collisionPadding={12}
          className="z-[60] max-w-sm rounded-xl bg-ink text-paper text-data-xs px-4 py-3 shadow-bento-hover whitespace-normal"
        >
          <TipBody entry={entry} />
          <Tooltip.Arrow className="fill-ink" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
