// Reasoning 텍스트에서 사전 용어를 찾아 세그먼트로 나누는 순수 함수.
// spec docs/superpowers/specs/2026-11-09-reasoning-glossary-design.md D3

import type { Element, ElementContent, Root, RootContent, Text } from "hast";
import type { GlossaryEntry, Segment } from "./glossaryTypes";

const WORD = /[A-Za-z0-9_]/;

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** alias 하나를 정규식 조각으로. 영문·숫자로 시작/끝나면 단어 경계를 붙인다.
 *  끝 경계는 '.숫자' 도 막아 '§3.5' 가 '§3.55' 에, 'c1' 이 'c1.5' 에 걸리지 않게 한다. */
function aliasPattern(alias: string): string {
  const head = WORD.test(alias[0]) ? "(?<![A-Za-z0-9_])" : "";
  const tail = WORD.test(alias[alias.length - 1]) ? "(?![A-Za-z0-9_]|\\.\\d)" : "";
  return head + escapeRegExp(alias) + tail;
}

export function buildMatcher(entries: GlossaryEntry[]): (text: string) => Segment[] {
  const idByAlias = new Map<string, string>();
  for (const e of entries) {
    for (const a of e.aliases) idByAlias.set(a.toLowerCase(), e.id);
  }
  const aliases = [...idByAlias.keys()].sort((a, b) => b.length - a.length);
  if (aliases.length === 0) return (text) => (text ? [{ kind: "text", text }] : []);
  const re = new RegExp(aliases.map(aliasPattern).join("|"), "gi");

  return (text: string): Segment[] => {
    const out: Segment[] = [];
    let last = 0;
    re.lastIndex = 0;
    for (let m = re.exec(text); m !== null; m = re.exec(text)) {
      const id = idByAlias.get(m[0].toLowerCase());
      if (!id) continue;
      if (m.index > last) out.push({ kind: "text", text: text.slice(last, m.index) });
      out.push({ kind: "term", text: m[0], id });
      last = m.index + m[0].length;
    }
    if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
    return out;
  };
}

/** react-markdown 용 rehype 플러그인. text 노드를 span[data-glossary-id] 로 쪼갠다(a 하위 제외). */
export function rehypeGlossaryWith(match: (text: string) => Segment[]) {
  const toNodes = (t: Text): ElementContent[] => {
    const segs = match(t.value);
    if (!segs.some((s) => s.kind === "term")) return [t];
    return segs.map((s): ElementContent =>
      s.kind === "text"
        ? { type: "text", value: s.text }
        : {
            type: "element",
            tagName: "span",
            properties: { dataGlossaryId: s.id },
            children: [{ type: "text", value: s.text }],
          },
    );
  };

  const walk = (node: Root | Element) => {
    if (node.type === "element" && node.tagName === "a") return;
    const next: (RootContent | ElementContent)[] = [];
    for (const child of node.children) {
      if (child.type === "text") next.push(...toNodes(child));
      else {
        if (child.type === "element") walk(child);
        next.push(child);
      }
    }
    node.children = next as typeof node.children;
  };

  return () => (tree: Root) => {
    walk(tree);
  };
}
