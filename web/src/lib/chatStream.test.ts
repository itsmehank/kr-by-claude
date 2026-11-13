import { describe, it, expect } from "vitest";
import { createSseParser, errorText } from "./chatStream";

const sse = (o: unknown) => `data: ${JSON.stringify(o)}\n\n`;

describe("createSseParser", () => {
  it("한 덩어리에 여러 이벤트가 와도 순서대로 낸다", () => {
    const p = createSseParser();
    const out = p.push(sse({ type: "start", conversation_id: "c1", request_id: "r" }) + sse({ type: "delta", text: "가" }));
    expect(out.map((e) => e.type)).toEqual(["start", "delta"]);
  });

  it("이벤트가 아무 데서나 잘려 와도(한글 포함) 완성된 뒤에만 낸다", () => {
    const p = createSseParser();
    const whole = sse({ type: "delta", text: "분배일 9개\n\n결론" }) + sse({ type: "status", text: "DB 조회 중: stocks" });
    const out = [];
    for (const ch of whole) out.push(...p.push(ch));
    expect(out).toEqual([
      { type: "delta", text: "분배일 9개\n\n결론" },
      { type: "status", text: "DB 조회 중: stocks" },
    ]);
    expect(p.end()).toEqual([]);
  });

  it("CRLF 구분과 끝에 빈 줄 없이 닫힌 마지막 이벤트도 읽는다", () => {
    const p = createSseParser();
    expect(p.push('data: {"type":"delta","text":"a"}\r\n\r\n').length).toBe(1);
    expect(p.push('data: {"type":"delta","text":"b"}')).toEqual([]);
    expect(p.end()).toEqual([{ type: "delta", text: "b" }]);
    expect(p.end()).toEqual([]);
  });

  it("깨진 JSON·type 없는 값·주석 줄은 버린다", () => {
    const p = createSseParser();
    expect(p.push("data: {not json\n\n: keep-alive\n\ndata: [1]\n\ndata: {\"x\":1}\n\n")).toEqual([]);
  });
});

describe("errorText", () => {
  it("아는 종류는 서버와 같은 문구, 모르는 종류는 종류를 보인다", () => {
    expect(errorText("timeout")).toBe("응답 시간이 초과됐어요");
    expect(errorText("internal")).toBe("전문가가 답하지 못했어요(internal)");
    expect(errorText(null)).toBe("답하는 중 문제가 생겼어요.");
    expect(errorText("constructor")).toBe("전문가가 답하지 못했어요(constructor)");
  });
});
