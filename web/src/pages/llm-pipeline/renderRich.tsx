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

/** [[term]] 또는 [[term|display]] 의 내부 토큰 파싱 — 키(term)가 먼저.
 *  과거 [display|term] 순서로 해석해, 화면에 raw 키가 노출되고 GLOSSARY 조회는
 *  표시 문구로 해서 툴팁이 안 뜨는 역전 버그가 있었다 (사용처·용어집 키 기준
 *  규약은 [[키|표시]] — 예: [[pocket_pivot|pocket pivot]]). */
export function parseRichToken(inner: string): { term: string; display: string } {
  const i = inner.indexOf("|");
  if (i === -1) return { term: inner, display: inner };
  return { term: inner.slice(0, i), display: inner.slice(i + 1) };
}

function renderParagraph(text: string): ReactNode {
  // [[term]] 또는 [[term|display]] 패턴 파싱
  const parts: ReactNode[] = [];
  const regex = /\[\[([^\]]+)\]\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let idx = 0;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(<span key={`t-${idx++}`}>{text.slice(lastIndex, match.index)}</span>);
    }
    const { term, display } = parseRichToken(match[1]);
    parts.push(<TermTooltip key={`tt-${idx++}`} term={term}>{display}</TermTooltip>);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(<span key={`t-${idx++}`}>{text.slice(lastIndex)}</span>);
  }
  return <>{parts}</>;
}
