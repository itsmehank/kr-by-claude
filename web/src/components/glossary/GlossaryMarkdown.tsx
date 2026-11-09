import { useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { matchGlossary } from "../../data/reasoningGlossary";
import { rehypeGlossaryWith } from "../../lib/glossaryMatch";
import { GlossaryTerm } from "./GlossaryTerm";

const rehypeGlossary = rehypeGlossaryWith(matchGlossary);
const REHYPE_PLUGINS = [rehypeGlossary];

/** 마크다운 reasoning — ReactMarkdown 과 같은 사용법, 사전 용어에 밑줄 + 마우스 오버 설명 */
export function GlossaryMarkdown({ children, components }: { children: string; components?: Components }) {
  const merged = useMemo<Components>(
    () => ({
      ...components,
      // eslint-disable-next-line @typescript-eslint/no-unused-vars -- node(hast)는 DOM 으로 넘기지 않도록 분리만 한다
      span: ({ node: _node, ...props }) => {
        const id = (props as Record<string, unknown>)["data-glossary-id"];
        if (typeof id === "string") return <GlossaryTerm id={id} text={String(props.children ?? "")} />;
        // 호출자가 span 렌더러를 넘겼다면 사전 용어가 아닌 span 에는 그것을 쓴다
        const CallerSpan = components?.span;
        if (CallerSpan && typeof CallerSpan !== "string") return <CallerSpan {...props} />;
        return <span {...props} />;
      },
    }),
    [components],
  );
  return (
    <ReactMarkdown rehypePlugins={REHYPE_PLUGINS} components={merged}>
      {children}
    </ReactMarkdown>
  );
}
