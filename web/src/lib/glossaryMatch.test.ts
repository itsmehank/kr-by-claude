import { describe, it, expect } from "vitest";
import type { Root } from "hast";
import { buildMatcher, rehypeGlossaryWith } from "./glossaryMatch";
import type { GlossaryEntry, Segment } from "./glossaryTypes";

function entry(id: string, aliases: string[]): GlossaryEntry {
  return { id, title: id, aliases, category: "시장 상황", short: "설명" };
}

const match = buildMatcher([
  entry("confirmed_uptrend", ["confirmed_uptrend"]),
  entry("uptrend", ["uptrend"]),
  entry("flat_base", ["flat base"]),
  entry("follow_through_day", ["follow-through day", "FTD"]),
  entry("pattern_none", ["pattern=none"]),
  entry("sec_3_5", ["§3.5"]),
  entry("distribution_day", ["분배일"]),
  entry("gate0", ["Gate0", "G0"]),
]);

const terms = (segs: Segment[]) =>
  segs.filter((s) => s.kind === "term").map((s) => (s as { id: string }).id);
const joined = (segs: Segment[]) => segs.map((s) => s.text).join("");

describe("buildMatcher", () => {
  it("긴 alias 우선", () => {
    const s = match("confirmed_uptrend 전환");
    expect(s[0]).toEqual({ kind: "term", id: "confirmed_uptrend", text: "confirmed_uptrend" });
    expect(terms(s)).toEqual(["confirmed_uptrend"]);
  });

  it("단어 경계 — 다른 단어의 일부는 매칭하지 않음", () => {
    expect(terms(match("flat baseline 대비"))).toEqual([]);
    expect(terms(match("uptrending"))).toEqual([]);
    expect(terms(match("flat base 형성"))).toEqual(["flat_base"]);
    expect(terms(match("G0 미충족, G01"))).toEqual(["gate0"]);
  });

  it("대소문자 무시, 원문 유지", () => {
    const s = match("Follow-Through Day 이후");
    expect(s[0]).toEqual({ kind: "term", id: "follow_through_day", text: "Follow-Through Day" });
  });

  it("정규식 특수문자 alias", () => {
    expect(terms(match("(pattern=none, rejected_gate=gate1)"))).toEqual(["pattern_none"]);
    expect(terms(match("§3.5 하드룰"))).toEqual(["sec_3_5"]);
    expect(terms(match("§3.55"))).toEqual([]);
  });

  it("한국어 alias", () => {
    expect(terms(match("최근 25거래일 분배일 5회"))).toEqual(["distribution_day"]);
  });

  it("여러 용어, 이어 붙이면 원문", () => {
    const text = "FTD 이후 confirmed_uptrend, 분배일 2회 — pattern=none";
    const s = match(text);
    expect(terms(s)).toEqual(["follow_through_day", "confirmed_uptrend", "distribution_day", "pattern_none"]);
    expect(joined(s)).toBe(text);
  });

  it("매칭 없음 → 원문 한 덩어리", () => {
    expect(match("아무 용어도 없는 문장")).toEqual([{ kind: "text", text: "아무 용어도 없는 문장" }]);
    expect(match("")).toEqual([]);
  });
});

describe("rehypeGlossaryWith", () => {
  it("text 노드를 span[data-glossary-id] 로 쪼갬, a 하위는 건너뜀", () => {
    const tree: Root = {
      type: "root",
      children: [
        { type: "element", tagName: "p", properties: {}, children: [{ type: "text", value: "FTD 확인" }] },
        {
          type: "element",
          tagName: "a",
          properties: { href: "#" },
          children: [{ type: "text", value: "FTD" }],
        },
      ],
    };
    rehypeGlossaryWith(match)()(tree);
    const p = tree.children[0] as { children: { type: string; tagName?: string; properties?: Record<string, unknown> }[] };
    expect(p.children[0].type).toBe("element");
    expect(p.children[0].tagName).toBe("span");
    expect(p.children[0].properties?.dataGlossaryId).toBe("follow_through_day");
    expect(p.children[1]).toEqual({ type: "text", value: " 확인" });
    const a = tree.children[1] as { children: { type: string }[] };
    expect(a.children[0].type).toBe("text");
  });
});
