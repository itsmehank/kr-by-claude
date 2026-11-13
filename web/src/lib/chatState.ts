/** (#281) 채팅 화면 상태 — 질문 하나가 시작·진행·끝나는 과정을 순수 함수로 둔다(vitest 로 검증). */
import { errorText, type ChatConversation, type ChatEvent, type ChatTurn } from "./chatStream";

export interface ChatMsg {
  id: number;
  role: "user" | "assistant";
  text: string;
  status: "done" | "aborted" | "error";
  /** 오류일 때 화면에 보일 문구 */
  error: string | null;
  queries: string[];
}

/** 지금 흘러나오는 답 */
export interface ChatLive {
  text: string;
  /** "DB 조회 중: …" 같은 진행 문구(글이 다시 나오기 시작하면 지운다) */
  status: string | null;
}

export interface ChatState {
  convId: string | null;
  msgs: ChatMsg[];
  live: ChatLive | null;
  nextId: number;
}

export type ChatAction =
  | { type: "send"; question: string }
  | { type: "event"; event: ChatEvent }
  /** 사용자가 중단했거나, 끝 표시 없이 스트림이 닫혔다 */
  | { type: "aborted" }
  /** 답이 오는 도중 연결이 끊겼다 */
  | { type: "disconnected" }
  /** 시작 전에 거절됐다(409 등): 방금 붙인 질문을 뗀다. forgetConversation: 대화가 서버에서 사라졌다(404) */
  | { type: "rejected"; forgetConversation?: boolean }
  | { type: "loaded"; conversation: ChatConversation }
  | { type: "reset" };

export const DISCONNECTED_TEXT = "연결이 끊겼어요.";

export const initialChat: ChatState = { convId: null, msgs: [], live: null, nextId: 1 };

function fromTurn(t: ChatTurn, id: number): ChatMsg {
  const status = t.status === "aborted" || t.status === "error" ? t.status : "done";
  return {
    id,
    role: t.role,
    text: t.text,
    status,
    error: status === "error" ? errorText(t.error) : null,
    queries: Array.isArray(t.queries) ? t.queries : [],
  };
}

/** 흘러나오던 답을 메시지로 굳힌다. */
function settle(s: ChatState, m: Omit<ChatMsg, "id" | "role">): ChatState {
  if (!s.live) return s; // 이미 끝난 질문에 늦게 온 신호
  return { ...s, live: null, nextId: s.nextId + 1, msgs: [...s.msgs, { id: s.nextId, role: "assistant", ...m }] };
}

export function chatReducer(s: ChatState, a: ChatAction): ChatState {
  switch (a.type) {
    case "send":
      if (s.live) return s; // 답하는 중에는 새 질문을 받지 않는다
      return {
        ...s,
        nextId: s.nextId + 1,
        live: { text: "", status: null },
        msgs: [...s.msgs, { id: s.nextId, role: "user", text: a.question, status: "done", error: null, queries: [] }],
      };
    case "event": {
      const e = a.event;
      if (!s.live) return s;
      if (e.type === "start") return { ...s, convId: e.conversation_id };
      if (e.type === "delta") return { ...s, live: { text: s.live.text + e.text, status: null } };
      if (e.type === "status") return { ...s, live: { ...s.live, status: e.text } };
      if (e.type === "done") {
        const t = fromTurn(e.turn, 0);
        return settle(s, { text: t.text, status: t.status, error: t.error, queries: t.queries });
      }
      if (e.type === "error") {
        return settle(s, { text: s.live.text, status: "error", error: e.message || errorText(e.kind), queries: [] });
      }
      return s;
    }
    case "aborted":
      return settle(s, { text: s.live?.text ?? "", status: "aborted", error: null, queries: [] });
    case "disconnected":
      return settle(s, { text: s.live?.text ?? "", status: "error", error: DISCONNECTED_TEXT, queries: [] });
    case "rejected": {
      if (!s.live) return s;
      const last = s.msgs[s.msgs.length - 1];
      const msgs = last?.role === "user" ? s.msgs.slice(0, -1) : s.msgs;
      return { ...s, live: null, msgs, convId: a.forgetConversation ? null : s.convId };
    }
    case "loaded": {
      let id = s.nextId;
      const msgs = a.conversation.turns.map((t) => fromTurn(t, id++));
      return { convId: a.conversation.id, msgs, live: null, nextId: id };
    }
    case "reset":
      return { ...initialChat, nextId: s.nextId };
  }
}

/**
 * 마지막이 질문이고 답이 아직 저장되지 않았다. 답하던 중 끊긴 직후에 생긴다 —
 * 서버가 끊김을 알아채 그 턴을 "중단됨"으로 저장하기까지 잠깐(1초 안쪽) 걸린다.
 */
export function awaitingAnswer(c: ChatConversation): boolean {
  return c.turns.length > 0 && c.turns[c.turns.length - 1].role === "user";
}

/** 서버의 종목 코드 형식(prompt.py TICKER_RE)과 같다. 형식이 틀린 값은 맥락으로 보내지 않는다. */
export const TICKER_RE = /^[0-9A-Z]{6}$/;

export interface ChatStock {
  ticker: string;
  name: string | null;
}

/** 맥락으로 쓸 수 있는 종목만 남긴다. 화면의 "현재 맥락" 표시와 실제로 보내는 값이 같은 기준을 쓰게 한다. */
export function validStock(stock: ChatStock | null): ChatStock | null {
  return stock && TICKER_RE.test(stock.ticker) ? stock : null;
}

/** 질문과 함께 보낼 종목 코드. 맥락을 껐거나(그 종목에 한해) 형식이 틀리면 보내지 않는다. */
export function contextTicker(stock: ChatStock | null, offTicker: string | null): string | undefined {
  const valid = validStock(stock);
  if (!valid || valid.ticker === offTicker) return undefined;
  return valid.ticker;
}

/** 지난 대화 목록의 시각 표시: 11/13 09:05 */
export function shortTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const two = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${two(d.getHours())}:${two(d.getMinutes())}`;
}
