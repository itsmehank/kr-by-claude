import { describe, it, expect } from "vitest";
import { parseRichToken } from "./renderRich";

describe("parseRichToken — [[term|display]] 규약 (키가 먼저)", () => {
  // 실사용처/용어집 실제 키 기준:
  //   [[pocket_pivot|pocket pivot]] — GLOSSARY 키는 "pocket_pivot"
  //   [[Slack digest|digest]]      — GLOSSARY 키는 "Slack digest"
  //   [[stop loss|손절선]]          — GLOSSARY 키는 "stop loss"
  it("파이프 있으면 앞 토큰=용어 키, 뒤 토큰=표시 문구", () => {
    expect(parseRichToken("pocket_pivot|pocket pivot")).toEqual({
      term: "pocket_pivot",
      display: "pocket pivot",
    });
    expect(parseRichToken("Slack digest|digest")).toEqual({
      term: "Slack digest",
      display: "digest",
    });
    expect(parseRichToken("stop loss|손절선")).toEqual({
      term: "stop loss",
      display: "손절선",
    });
  });

  it("파이프 없으면 둘 다 동일", () => {
    expect(parseRichToken("entry")).toEqual({ term: "entry", display: "entry" });
  });

  it("표시 문구에 파이프가 있어도 첫 파이프만 구분자", () => {
    expect(parseRichToken("k|a|b")).toEqual({ term: "k", display: "a|b" });
  });
});
