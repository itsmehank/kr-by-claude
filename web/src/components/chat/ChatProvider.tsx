import { useEffect, useReducer, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { chatReducer, contextTicker, initialChat, type ChatStock } from "../../lib/chatState";
import { ChatHttpError, SEND_FALLBACK, getChat, streamChat, type ChatBody } from "../../lib/chatStream";
import { useGlossary } from "../glossary/glossaryContext";
import { CHATS_QUERY_KEY, ChatContext, ChatStockSetterContext, type ChatBanner, type ChatContextValue } from "./chatContext";

const OPEN_KEY = "kr.chat.open";
const CONV_KEY = "kr.chat.conversation";

// sessionStorage 가 막힌 환경(사생활 보호 모드 등)에서도 위젯은 그대로 동작한다 — 기억만 못 한다.
function readSession(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeSession(key: string, value: string | null): void {
  try {
    if (value === null) window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, value);
  } catch {
    /* 저장 불가 환경 — 무시 */
  }
}

/**
 * 채팅의 대화·흘러나오는 답·입력 중인 글을 <Routes> 바깥에서 쥔다. 그래서 페이지를 옮기거나 패널을 닫아도 이어진다.
 * GlossaryProvider 안에 둔다(용어 사전과 번갈아 열기).
 */
export function ChatProvider({ children }: { children: ReactNode }) {
  const glossary = useGlossary();
  const glossaryOpen = glossary?.open ?? false;
  const setGlossaryOpen = glossary?.setOpen;
  const queryClient = useQueryClient();

  const [state, dispatch] = useReducer(chatReducer, initialChat);
  const [open, setOpenState] = useState<boolean>(() => readSession(OPEN_KEY) === "1");
  const [input, setInput] = useState("");
  const [banner, setBanner] = useState<ChatBanner | null>(null);
  // 새로고침 전에 열려 있던 대화. 처음 한 번만 읽는다(저장 값은 대화가 바뀔 때만 다시 쓴다).
  const [restoreId] = useState<string | null>(() => readSession(CONV_KEY));
  const [loading, setLoading] = useState<boolean>(restoreId !== null);
  const [stock, setStock] = useState<ChatStock | null>(null);
  const [offTicker, setOffTicker] = useState<string | null>(null);

  const acRef = useRef<AbortController | null>(null);
  // 새 대화·불러오기·보내기마다 올려, 이전 요청의 늦은 응답을 버린다.
  const gen = useRef(0);

  // 용어 사전이 열리면 채팅을 닫는다(오른쪽 아래 같은 자리를 쓴다).
  const [seenGlossaryOpen, setSeenGlossaryOpen] = useState(glossaryOpen);
  if (glossaryOpen !== seenGlossaryOpen) {
    setSeenGlossaryOpen(glossaryOpen);
    if (glossaryOpen && open) setOpenState(false);
  }
  // 새로고침 때 둘 다 "열림"으로 기억돼 있으면 채팅을 남긴다.
  useEffect(() => {
    if (readSession(OPEN_KEY) === "1") setGlossaryOpen?.(false);
  }, [setGlossaryOpen]);

  useEffect(() => writeSession(OPEN_KEY, open ? "1" : "0"), [open]);
  useEffect(() => {
    if (state.convId) writeSession(CONV_KEY, state.convId);
  }, [state.convId]);

  // 새로고침 뒤 복원: 서버에 저장된 대화를 다시 받는다(끊긴 답은 "중단됨"으로 저장돼 있다).
  useEffect(() => {
    if (!restoreId) return;
    const mine = ++gen.current;
    getChat(restoreId)
      .then((conversation) => {
        if (mine === gen.current) dispatch({ type: "loaded", conversation });
      })
      .catch((err: unknown) => {
        // 보관 기간(7일)이 지났으면 조용히 새 대화로 시작한다.
        if (mine === gen.current && err instanceof ChatHttpError && err.status === 404) writeSession(CONV_KEY, null);
      })
      .finally(() => {
        if (mine === gen.current) setLoading(false);
      });
  }, [restoreId]);

  // 앱이 내려가면 진행 중인 답을 끊는다(서버가 끊김을 알아채 그 턴을 중단됨으로 저장한다).
  useEffect(
    () => () => {
      acRef.current?.abort();
    },
    [],
  );

  const setOpen = (v: boolean) => {
    setOpenState(v);
    if (v) setGlossaryOpen?.(false);
  };

  const refreshList = () => void queryClient.invalidateQueries({ queryKey: CHATS_QUERY_KEY });

  const send = () => {
    const question = input.trim();
    if (!question || state.live || loading) return;
    const mine = ++gen.current;
    const current = () => mine === gen.current;
    const ac = new AbortController();
    acRef.current = ac;
    const body: ChatBody = { question };
    if (state.convId) body.conversation_id = state.convId;
    const ticker = contextTicker(stock, offTicker);
    if (ticker) body.ticker = ticker;

    dispatch({ type: "send", question });
    setInput("");
    setBanner(null);
    let gotEvent = false;
    streamChat(
      body,
      (event) => {
        if (!current()) return;
        gotEvent = true;
        dispatch({ type: "event", event });
        if (event.type === "done") refreshList();
      },
      ac.signal,
    )
      .then(() => {
        // 끝 표시(done·error) 없이 스트림이 닫혔다. 이미 끝난 질문이면 아무 일도 없다.
        if (current()) dispatch({ type: "aborted" });
      })
      .catch((err: unknown) => {
        if (!current()) return;
        if (ac.signal.aborted) {
          dispatch({ type: "aborted" });
          refreshList();
        } else if (!gotEvent) {
          // 시작 전에 거절됐다(다른 질문에 답하는 중 409 등): 질문을 입력창으로 돌려놓는다.
          const gone = err instanceof ChatHttpError && err.status === 404 && body.conversation_id !== undefined;
          dispatch({ type: "rejected", forgetConversation: gone });
          setInput((cur) => cur || question);
          if (gone) {
            writeSession(CONV_KEY, null);
            setBanner({ kind: "notice", text: "대화가 삭제됐어요. 보내면 새 대화로 시작해요." });
          } else {
            setBanner({ kind: "error", text: err instanceof Error && err.message ? err.message : SEND_FALLBACK });
          }
        } else {
          dispatch({ type: "disconnected" });
        }
      })
      .finally(() => {
        if (acRef.current === ac) acRef.current = null;
      });
  };

  const stop = () => acRef.current?.abort();

  /** 진행 중인 것을 모두 버리고 빈 대화로 만든다. */
  const clear = () => {
    gen.current++;
    acRef.current?.abort();
    acRef.current = null;
    dispatch({ type: "reset" });
    setBanner(null);
    setLoading(false);
  };

  const newChat = () => {
    clear();
    writeSession(CONV_KEY, null);
  };

  const resume = (id: string) => {
    clear();
    const mine = gen.current;
    setLoading(true);
    getChat(id)
      .then((conversation) => {
        if (mine === gen.current) dispatch({ type: "loaded", conversation });
      })
      .catch((err: unknown) => {
        if (mine !== gen.current) return;
        if (err instanceof ChatHttpError && err.status === 404) {
          setBanner({ kind: "notice", text: "대화가 삭제됐어요." });
          refreshList();
        } else {
          setBanner({ kind: "error", text: "대화를 불러오지 못했어요." });
        }
      })
      .finally(() => {
        if (mine === gen.current) setLoading(false);
      });
  };

  const value: ChatContextValue = {
    open,
    setOpen,
    state,
    input,
    setInput,
    send,
    stop,
    newChat,
    resume,
    loading,
    banner,
    stock,
    contextOff: stock !== null && stock.ticker === offTicker,
    setContextOff: (off) => setOffTicker(off && stock ? stock.ticker : null),
  };

  return (
    <ChatStockSetterContext.Provider value={setStock}>
      <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
    </ChatStockSetterContext.Provider>
  );
}
