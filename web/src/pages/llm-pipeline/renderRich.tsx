import type { ReactNode } from "react";
import { TermTooltip } from "./TermTooltip";

/**
 * 문자열에서 [[term]] 패턴을 TermTooltip 으로, \n\n 을 단락 break 로 변환.
 *
 * 예: "...AI 가 [[go_now]] 결정을 받으면..." → "...AI 가 <TermTooltip>go_now</TermTooltip> 결정을 받으면..."
 *
 * 단락 break 는 React Fragment 안 여러 <span> 으로 분리 — whitespace-pre-line 대신 명시적 단락.
 */
export function renderRich(text: string): ReactNode {
  // 단락 분리 (\n\n) → 각 단락을 별도 <span> + <br/><br/> 로
  const paragraphs = text.split(/\n\n+/);
  return (
    <>
      {paragraphs.map((para, pIdx) => (
        <span key={pIdx}>
          {pIdx > 0 && <><br /><br /></>}
          {renderParagraph(para)}
        </span>
      ))}
    </>
  );
}

function renderParagraph(text: string): ReactNode {
  // [[term]] 또는 [[display|term]] 패턴 파싱
  const parts: ReactNode[] = [];
  const regex = /\[\[([^\]]+)\]\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let idx = 0;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(<span key={`t-${idx++}`}>{text.slice(lastIndex, match.index)}</span>);
    }
    const inner = match[1];
    const [display, termOrUndef] = inner.includes("|") ? inner.split("|") : [inner, inner];
    const term = termOrUndef ?? inner;
    parts.push(<TermTooltip key={`tt-${idx++}`} term={term}>{display}</TermTooltip>);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(<span key={`t-${idx++}`}>{text.slice(lastIndex)}</span>);
  }
  return <>{parts}</>;
}
