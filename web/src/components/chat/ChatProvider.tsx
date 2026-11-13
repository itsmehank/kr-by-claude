import { useEffect, useReducer, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { awaitingAnswer, chatReducer, contextTicker, initialChat, validStock, type ChatStock } from "../../lib/chatState";
import { ChatHttpError, SEND_FALLBACK, getChat, httpStatus, streamChat, type ChatBody, type ChatConversation } from "../../lib/chatStream";
import { useGlossary } from "../glossary/glossaryContext";
import { CHATS_QUERY_KEY, ChatContext, ChatStockSetterContext, type ChatBanner, type ChatContextValue } from "./chatContext";

const OPEN_KEY = "kr.chat.open";
const CONV_KEY = "kr.chat.conversation";

const SETTLE_RETRIES = 3;
const SETTLE_WAIT_MS = 600;
// 중단을 눌렀는데 서버의 시작 신호(대화 번호)가 아직 안 왔으면 이만큼만 기다린다.
const STOP_WAIT_MS = 3000;

/**
 * 대화를 받는다. 마지막이 답 없는 질문이면(끊긴 답을 서버가 아직 "중단됨"으로 저장하기 전) 잠깐 뒤 다시 받는다.
 * 끝까지 답이 없으면 받은 그대로 돌려준다.
 */
async function getSettledChat(id: string, stale: () => boolean): Promise<ChatConversation> {
  for (let attempt = 0; ; attempt++) {
    const conversation = await getChat(id);
    if (!awaitingAnswer(conversation) || attempt >= SETTLE_RETRIES || stale()) return conversation;
    await new Promise((resolve) => setTimeout(resolve, SETTLE_WAIT_MS));
  }
}

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
  // 진행 중인 질문을 중단하는 함수(시작 신호 전이면 신호를 받을 때까지 미룬다)
  const stopRef = useRef<(() => void) | null>(null);
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
    getSettledChat(restoreId, () => mine !== gen.current)
      .then((conversation) => {
        if (mine === gen.current) dispatch({ type: "loaded", conversation });
      })
      .catch((err: unknown) => {
        if (mine !== gen.current) return;
        // 보관 기간(7일)이 지났으면 조용히 새 대화로 시작한다.
        if (httpStatus(err) === 404) writeSession(CONV_KEY, null);
        else setBanner({ kind: "error", text: "이전 대화를 불러오지 못했어요. 지난 대화에서 다시 열 수 있어요." });
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
    let ended = false; // done·error 를 받았다
    let convId = body.conversation_id ?? null;
    let stopWanted = false;
    let stopTimer: number | undefined;
    // 새 대화는 서버가 시작 신호로 대화 번호를 알려 준다. 그 전에 끊으면 서버에는 대화가 남는데 화면은 번호를 몰라
    // 다음 질문이 다른 대화로 갈라진다 — 번호를 받은 뒤에 끊는다(신호가 안 오면 STOP_WAIT_MS 뒤 그냥 끊는다).
    stopRef.current = () => {
      if (convId !== null || stopWanted) return ac.abort();
      stopWanted = true;
      stopTimer = window.setTimeout(() => ac.abort(), STOP_WAIT_MS);
    };
    // 중단·끊김·오류로 끝난 답은 서버에 저장된 것(근거 조회문 포함)으로 맞춘다 — 새로고침했을 때와 같은 모습.
    const syncFromServer = () => {
      if (convId === null) return;
      getSettledChat(convId, () => !current())
        .then((conversation) => {
          if (current() && !awaitingAnswer(conversation)) dispatch({ type: "loaded", conversation });
        })
        .catch(() => {
          /* 못 받으면 화면에 있는 그대로 둔다 */
        })
        .finally(refreshList);
    };
    streamChat(
      body,
      (event) => {
        if (!current()) return;
        gotEvent = true;
        dispatch({ type: "event", event });
        if (event.type === "start") {
          convId = event.conversation_id;
          if (stopWanted) ac.abort();
        } else if (event.type === "done") {
          ended = true;
          refreshList();
        } else if (event.type === "error") {
          ended = true;
          syncFromServer();
        }
      },
      ac.signal,
    )
      .then(() => {
        // 끝 표시(done·error) 없이 스트림이 닫혔다.
        if (!current() || ended) return;
        dispatch({ type: "aborted" });
        syncFromServer();
      })
      .catch((err: unknown) => {
        if (!current() || ended) return;
        if (ac.signal.aborted) {
          dispatch({ type: "aborted" });
          syncFromServer();
        } else if (!gotEvent) {
          // 시작 전에 거절됐다(다른 질문에 답하는 중 409 등): 질문을 입력창으로 돌려놓는다.
          const gone = err instanceof ChatHttpError && err.status === 404 && body.conversation_id !== undefined;
          dispatch({ type: "rejected", forgetConversation: gone });
          setInput((cur) => cur || question);
          if (gone) {
            writeSession(CONV_KEY, null);
            setBanner({ kind: "notice", text: "대화가 삭제됐어요. 보내면 새 대화로 시작해요." });
          } else {
            // 서버가 준 안내(409 등)만 그대로 보인다. 네트워크 오류의 브라우저 문구("Failed to fetch")는 보이지 않는다.
            setBanner({ kind: "error", text: err instanceof ChatHttpError && err.message ? err.message : SEND_FALLBACK });
          }
        } else {
          dispatch({ type: "disconnected" });
          syncFromServer();
        }
      })
      .finally(() => {
        window.clearTimeout(stopTimer);
        if (acRef.current === ac) {
          acRef.current = null;
          stopRef.current = null;
        }
      });
  };

  const stop = () => stopRef.current?.();

  /** 진행 중인 것을 모두 버리고 빈 대화로 만든다. */
  const clear = () => {
    gen.current++;
    acRef.current?.abort();
    acRef.current = null;
    stopRef.current = null;
    dispatch({ type: "reset" });
    setBanner(null);
    setLoading(false);
  };

  const newChat = () => {
    clear();
    writeSession(CONV_KEY, null);
  };

  // 받는 데 성공했을 때만 화면의 대화를 바꾼다. 실패하면 보던 대화가 그대로 남아, 저장된 대화 번호와 어긋나지 않는다.
  const resume = (id: string) => {
    if (state.live) return;
    const mine = ++gen.current;
    setBanner(null);
    setLoading(true);
    getSettledChat(id, () => mine !== gen.current)
      .then((conversation) => {
        if (mine === gen.current) dispatch({ type: "loaded", conversation });
      })
      .catch((err: unknown) => {
        if (mine !== gen.current) return;
        if (httpStatus(err) === 404) {
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

  // 종목 코드 형식이 아닌 값(주소에 잘못 들어온 값 등)은 맥락으로 보이지도, 보내지도 않는다.
  const shownStock = validStock(stock);
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
    stock: shownStock,
    contextOff: shownStock !== null && shownStock.ticker === offTicker,
    setContextOff: (off) => setOffTicker(off && shownStock ? shownStock.ticker : null),
  };

  return (
    <ChatStockSetterContext.Provider value={setStock}>
      <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
    </ChatStockSetterContext.Provider>
  );
}
