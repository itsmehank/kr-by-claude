import { createContext, useContext, useEffect } from "react";
import type { ChatState, ChatStock } from "../../lib/chatState";

/** 지난 대화 목록의 react-query 키(답이 끝나면 다시 받는다) */
export const CHATS_QUERY_KEY = ["chat-list"] as const;

export interface ChatBanner {
  kind: "error" | "notice";
  text: string;
}

export interface ChatContextValue {
  open: boolean;
  setOpen: (open: boolean) => void;
  state: ChatState;
  input: string;
  setInput: (v: string) => void;
  /** 입력창의 글을 질문으로 보낸다(답하는 중·불러오는 중이면 아무것도 하지 않는다) */
  send: () => void;
  /** 답하는 중인 질문을 중단한다 */
  stop: () => void;
  newChat: () => void;
  resume: (id: string) => void;
  /** 대화를 불러오는 중(새로고침 복원·지난 대화 열기) */
  loading: boolean;
  banner: ChatBanner | null;
  /** 지금 화면에서 보고 있는 종목(없으면 null) */
  stock: ChatStock | null;
  /** 이 종목을 맥락으로 보내지 않기로 했는가 */
  contextOff: boolean;
  setContextOff: (off: boolean) => void;
}

export const ChatContext = createContext<ChatContextValue | null>(null);

export function useChat(): ChatContextValue | null {
  return useContext(ChatContext);
}

/** 페이지가 "지금 보는 종목"을 알리는 통로. 대화 상태와 분리해, 답이 흘러나와도 페이지가 다시 그려지지 않게 한다. */
export const ChatStockSetterContext = createContext<((stock: ChatStock | null) => void) | null>(null);

/**
 * 종목 화면에서 호출한다 — 채팅 위젯이 "현재 맥락"으로 보이고 질문과 함께 보낸다.
 * 종목이 없으면(선택 전) null 을 주면 되고, 페이지를 떠나면 자동으로 지워진다.
 */
export function useChatStock(ticker: string | null | undefined, name?: string | null): void {
  const set = useContext(ChatStockSetterContext);
  useEffect(() => {
    if (!set) return;
    set(ticker ? { ticker, name: name ?? null } : null);
    return () => set(null);
  }, [set, ticker, name]);
}
