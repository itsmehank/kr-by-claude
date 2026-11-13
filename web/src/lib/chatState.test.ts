import { describe, it, expect } from "vitest";
import { chatReducer, contextTicker, initialChat, shortTime, DISCONNECTED_TEXT, type ChatAction, type ChatState } from "./chatState";
import type { ChatEvent, ChatTurn } from "./chatStream";

const run = (s: ChatState, ...actions: ChatAction[]) => actions.reduce(chatReducer, s);
const ev = (event: ChatEvent): ChatAction => ({ type: "event", event });
const turn = (over: Partial<ChatTurn>): ChatTurn => ({
  role: "assistant", text: "", created_at: "2026-11-13T00:00:00+00:00", status: "done", queries: [], error: null, id: null, ...over,
});
const START = ev({ type: "start", conversation_id: "caaaaaaaaaaa", request_id: "r1" });

describe("chatReducer — 질문 하나의 흐름", () => {
  it("보내기 → 시작 → 진행 문구 → 글 조각 → 완료", () => {
    let s = run(initialChat, { type: "send", question: "왜 wait?" }, START);
    expect(s.convId).toBe("caaaaaaaaaaa");
    expect(s.msgs.map((m) => [m.role, m.text])).toEqual([["user", "왜 wait?"]]);
    s = run(s, ev({ type: "status", text: "DB 조회 중: stocks" }));
    expect(s.live).toEqual({ text: "", status: "DB 조회 중: stocks" });
    s = run(s, ev({ type: "delta", text: "시장 " }), ev({ type: "delta", text: "게이트" }));
    expect(s.live).toEqual({ text: "시장 게이트", status: null }); // 글이 나오면 진행 문구는 지운다
    s = run(s, ev({ type: "done", turn: turn({ text: "시장 게이트", queries: ["select 1"] }) }));
    expect(s.live).toBeNull();
    expect(s.msgs[1]).toMatchObject({ role: "assistant", text: "시장 게이트", status: "done", queries: ["select 1"] });
    expect(new Set(s.msgs.map((m) => m.id)).size).toBe(2);
  });

  it("오류 이벤트: 그때까지 나온 글과 오류 문구를 남긴다", () => {
    const s = run(initialChat, { type: "send", question: "q" }, START, ev({ type: "delta", text: "부분" }),
      ev({ type: "error", kind: "rate_limit", message: "claude 사용량 한도에 걸렸어요. 잠시 뒤 다시 물어 주세요." }));
    expect(s.msgs[1]).toMatchObject({ text: "부분", status: "error", error: "claude 사용량 한도에 걸렸어요. 잠시 뒤 다시 물어 주세요." });
    expect(s.live).toBeNull();
  });

  it("중단: 나온 글까지 중단됨으로 남고, 그 뒤 늦게 온 이벤트는 무시한다", () => {
    let s = run(initialChat, { type: "send", question: "q" }, START, ev({ type: "delta", text: "부분" }), { type: "aborted" });
    expect(s.msgs[1]).toMatchObject({ text: "부분", status: "aborted", error: null });
    const before = s;
    s = run(s, ev({ type: "delta", text: "늦은 글" }), ev({ type: "done", turn: turn({ text: "늦은 답" }) }), { type: "aborted" });
    expect(s).toBe(before);
  });

  it("도중 연결 끊김은 오류로 남긴다", () => {
    const s = run(initialChat, { type: "send", question: "q" }, START, ev({ type: "delta", text: "부분" }), { type: "disconnected" });
    expect(s.msgs[1]).toMatchObject({ text: "부분", status: "error", error: DISCONNECTED_TEXT });
  });

  it("시작 전 거절(409): 방금 붙인 질문을 떼고 대화는 그대로", () => {
    const base = run(initialChat, { type: "loaded", conversation: {
      id: "cbbbbbbbbbbb", created_at: "", updated_at: "", context: null,
      turns: [turn({ role: "user", text: "앞 질문" }), turn({ text: "앞 답" })] } });
    const s = run(base, { type: "send", question: "새 질문" }, { type: "rejected" });
    expect(s.msgs.map((m) => m.text)).toEqual(["앞 질문", "앞 답"]);
    expect(s.live).toBeNull();
    expect(s.convId).toBe("cbbbbbbbbbbb");
  });

  it("대화가 서버에서 사라졌으면(404) 대화 ID 를 잊어 다음 질문이 새 대화로 간다", () => {
    const s = run({ ...initialChat, convId: "cbbbbbbbbbbb" }, { type: "send", question: "q" }, { type: "rejected", forgetConversation: true });
    expect(s.convId).toBeNull();
    expect(s.msgs).toEqual([]);
  });

  it("답하는 중에는 새 질문을 붙이지 않는다", () => {
    const s = run(initialChat, { type: "send", question: "q1" }, { type: "send", question: "q2" });
    expect(s.msgs.map((m) => m.text)).toEqual(["q1"]);
  });
});

describe("chatReducer — 대화 불러오기·새 대화", () => {
  it("저장된 턴을 그대로 옮기고, 저장된 오류 종류는 문구로 바꾼다", () => {
    const s = run(initialChat, { type: "loaded", conversation: {
      id: "cbbbbbbbbbbb", created_at: "", updated_at: "", context: { ticker: "093320", title: "케이아이엔엑스" },
      turns: [
        turn({ role: "user", text: "q1" }), turn({ text: "부분", status: "aborted", queries: ["select 1"] }),
        turn({ role: "user", text: "q2" }), turn({ text: "", status: "error", error: "timeout" }),
      ] } });
    expect(s.convId).toBe("cbbbbbbbbbbb");
    expect(s.msgs.map((m) => [m.role, m.status, m.error])).toEqual([
      ["user", "done", null], ["assistant", "aborted", null], ["user", "done", null], ["assistant", "error", "응답 시간이 초과됐어요"],
    ]);
    expect(s.msgs[1].queries).toEqual(["select 1"]);
    expect(new Set(s.msgs.map((m) => m.id)).size).toBe(4);
  });

  it("새 대화: 비우되 메시지 번호는 이어 간다(같은 번호가 다시 쓰이지 않게)", () => {
    const a = run(initialChat, { type: "send", question: "q" }, START, { type: "aborted" });
    const b = run(a, { type: "reset" });
    expect(b).toMatchObject({ convId: null, msgs: [], live: null });
    expect(b.nextId).toBe(a.nextId);
  });
});

describe("contextTicker", () => {
  it("종목이 있고 끄지 않았을 때만 보낸다", () => {
    const s = { ticker: "093320", name: "케이아이엔엑스" };
    expect(contextTicker(s, null)).toBe("093320");
    expect(contextTicker(s, "093320")).toBeUndefined();
    expect(contextTicker(s, "005930")).toBe("093320"); // 다른 종목에서 끈 것은 이 종목에 적용하지 않는다
    expect(contextTicker(null, null)).toBeUndefined();
    expect(contextTicker({ ticker: "abc", name: null }, null)).toBeUndefined();
    expect(contextTicker({ ticker: "0001A0", name: null }, null)).toBe("0001A0");
  });
});

describe("shortTime", () => {
  it("월/일 시:분, 읽을 수 없는 값은 빈 글", () => {
    const d = new Date(2026, 10, 13, 9, 5);
    expect(shortTime(d.toISOString())).toBe("11/13 09:05");
    expect(shortTime("이상한 값")).toBe("");
  });
});
