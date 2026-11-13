/** (#281) AI 분석 전문가 채팅 — 서버(`/api/chat`, SSE)와 주고받는 부분. ai-library chat.ts 를 옮긴 것. */

export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
  created_at: string;
  status: "done" | "aborted" | "error";
  /** 이 답을 만들며 실행한 조회문(근거 표시용) */
  queries: string[];
  error: string | null;
  id: string | null;
}

export interface ChatConversation {
  id: string;
  created_at: string;
  updated_at: string;
  context: { ticker?: string; title?: string } | null;
  turns: ChatTurn[];
}

export interface ChatSummary {
  id: string;
  created_at: string;
  updated_at: string;
  first_question: string;
  context_title: string | null;
  turn_count: number;
}

export interface ChatStatus {
  chain_running: boolean;
  pipelines: string[];
}

export type ChatEvent =
  | { type: "start"; conversation_id: string; request_id: string }
  | { type: "delta"; text: string }
  | { type: "status"; text: string }
  | { type: "done"; turn: ChatTurn }
  | { type: "error"; kind: string; message: string };

export interface ChatBody {
  question: string;
  conversation_id?: string;
  ticker?: string;
}

export class ChatHttpError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export const SEND_FALLBACK = "전문가에게 질문하지 못했어요.";
const ERROR_FALLBACK = "답하는 중 문제가 생겼어요.";
const ERROR_COPY: Record<string, string> = {
  rate_limit: "claude 사용량 한도에 걸렸어요. 잠시 뒤 다시 물어 주세요.",
  timeout: "응답 시간이 초과됐어요",
  auth: "claude 로그인이 필요해요",
  not_found: "claude 프로그램을 찾지 못했어요",
};

/** 저장된 오류 종류를 서버가 스트림으로 보내는 문구(service.py error_text)와 같은 말로 바꾼다. */
export function errorText(kind: string | null | undefined): string {
  if (!kind) return ERROR_FALLBACK;
  return Object.hasOwn(ERROR_COPY, kind) ? ERROR_COPY[kind] : `전문가가 답하지 못했어요(${kind})`;
}

function parseEvent(block: string): ChatEvent | null {
  const data = block
    .split("\n")
    .filter((l) => l.startsWith("data:"))
    .map((l) => l.slice(5).replace(/^ /, ""))
    .join("\n");
  if (!data) return null;
  try {
    const v: unknown = JSON.parse(data);
    return v && typeof v === "object" && typeof (v as { type?: unknown }).type === "string" ? (v as ChatEvent) : null;
  } catch {
    return null;
  }
}

/** 네트워크가 아무 데서나 끊어 주는 글 조각을 받아, 완성된 이벤트만 돌려준다. */
export function createSseParser(): { push: (chunk: string) => ChatEvent[]; end: () => ChatEvent[] } {
  let buf = "";
  const drain = (final: boolean): ChatEvent[] => {
    const out: ChatEvent[] = [];
    buf = buf.replace(/\r\n/g, "\n");
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const ev = parseEvent(buf.slice(0, i));
      buf = buf.slice(i + 2);
      if (ev) out.push(ev);
    }
    if (final && buf.trim()) {
      const ev = parseEvent(buf);
      if (ev) out.push(ev);
    }
    if (final) buf = "";
    return out;
  };
  return {
    push: (chunk) => {
      buf += chunk;
      return drain(false);
    },
    end: () => drain(true),
  };
}

export async function streamChat(body: ChatBody, onEvent: (e: ChatEvent) => void, signal: AbortSignal): Promise<void> {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    let message = "";
    try {
      const j: unknown = JSON.parse(await res.text());
      if (j && typeof j === "object" && typeof (j as { message?: unknown }).message === "string") {
        message = (j as { message: string }).message;
      }
    } catch {
      /* JSON 이 아닌 응답 */
    }
    throw new ChatHttpError(res.status, message || SEND_FALLBACK);
  }
  if (!res.body) throw new Error(SEND_FALLBACK);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  const parser = createSseParser();
  let finished = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(dec.decode(value, { stream: true })).forEach(onEvent);
    }
    parser.push(dec.decode());
    parser.end().forEach(onEvent);
    finished = true;
  } finally {
    // 중단되거나 onEvent 가 던지면 연결을 놓아 서버가 끊김을 알게 한다.
    if (!finished) reader.cancel().catch(() => {});
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new ChatHttpError(res.status, `${path} ${res.status}`);
  return (await res.json()) as T;
}

export const getChats = () => getJson<{ items: ChatSummary[] }>("/api/chats").then((r) => r.items);
export const getChat = (id: string) => getJson<ChatConversation>(`/api/chats/${encodeURIComponent(id)}`);
export const getChatStatus = () => getJson<ChatStatus>("/api/chat/status");
