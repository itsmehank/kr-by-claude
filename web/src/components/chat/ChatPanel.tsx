import { memo, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowUp, History, Loader2, MessageSquareText, Plus, Square, TriangleAlert, X } from "lucide-react";
import { shortTime, type ChatMsg } from "../../lib/chatState";
import { getChatStatus, getChats, type ChatStatus, type ChatSummary } from "../../lib/chatStream";
import { CHATS_QUERY_KEY, useChat } from "./chatContext";

const QUESTION_MAX = 2000; // 서버 상한(api/routers/chat.py QUESTION_MAX)과 같다
const REMARK_PLUGINS = [remarkGfm];
const EXAMPLES = ["지금 시장 상태 어때?", "이번 주 watch 중 pivot 에 가장 가까운 종목은?", "최근 entry 로 분류된 종목 알려줘"];

/* eslint-disable @typescript-eslint/no-unused-vars -- node(hast)는 DOM 으로 넘기지 않도록 분리만 한다 */
const ANSWER_MD: Components = {
  p: ({ node: _n, ...p }) => <p className="mb-2 last:mb-0" {...p} />,
  ul: ({ node: _n, ...p }) => <ul className="list-disc ml-5 mb-2 last:mb-0 space-y-0.5" {...p} />,
  ol: ({ node: _n, ...p }) => <ol className="list-decimal ml-5 mb-2 last:mb-0 space-y-0.5" {...p} />,
  h1: ({ node: _n, ...p }) => <p className="font-semibold mt-3 mb-1 first:mt-0" {...p} />,
  h2: ({ node: _n, ...p }) => <p className="font-semibold mt-3 mb-1 first:mt-0" {...p} />,
  h3: ({ node: _n, ...p }) => <p className="font-semibold mt-3 mb-1 first:mt-0" {...p} />,
  h4: ({ node: _n, ...p }) => <p className="font-semibold mt-2 mb-1 first:mt-0" {...p} />,
  strong: ({ node: _n, ...p }) => <strong className="font-semibold" {...p} />,
  a: ({ node: _n, ...p }) => <a className="text-accent underline" target="_blank" rel="noreferrer" {...p} />,
  hr: () => <hr className="my-3 border-hairline" />,
  code: ({ node: _n, ...p }) => <code className="font-mono text-[12px] bg-tint-stone rounded px-1 py-0.5 break-words" {...p} />,
  pre: ({ node: _n, ...p }) => (
    <pre className="mb-2 last:mb-0 p-2 rounded-lg bg-tint-stone overflow-x-auto text-[12px] [&_code]:bg-transparent [&_code]:p-0" {...p} />
  ),
  // 패널이 좁다: 넓은 표는 표 안에서만 가로로 민다
  table: ({ node: _n, ...p }) => (
    <div className="mb-2 last:mb-0 overflow-x-auto">
      <table className="text-data-xs border-collapse" {...p} />
    </div>
  ),
  th: ({ node: _n, ...p }) => <th className="border border-hairline bg-cream px-2 py-1 text-left font-semibold whitespace-nowrap" {...p} />,
  td: ({ node: _n, ...p }) => <td className="border border-hairline px-2 py-1 align-top" {...p} />,
};
/* eslint-enable @typescript-eslint/no-unused-vars */

function Answer({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={ANSWER_MD}>
      {text}
    </ReactMarkdown>
  );
}

function Queries({ queries }: { queries: string[] }) {
  if (queries.length === 0) return null;
  return (
    <details className="mt-2 text-data-xs text-muted">
      <summary className="cursor-pointer select-none hover:text-ink">근거 조회문 {queries.length}개</summary>
      <div className="mt-1 space-y-1">
        {queries.map((q, i) => (
          <pre key={i} className="p-2 rounded-lg bg-tint-stone font-mono text-[11px] whitespace-pre-wrap break-words">
            {q}
          </pre>
        ))}
      </div>
    </details>
  );
}

// 답이 한 조각 올 때마다 패널이 다시 그려진다. 끝난 메시지는 그대로이므로 마크다운을 다시 해석하지 않게 한다.
const Message = memo(function Message({ m }: { m: ChatMsg }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] px-3 py-2 rounded-2xl rounded-br-md bg-ink text-paper text-data whitespace-pre-wrap break-words">
          {m.text}
        </div>
      </div>
    );
  }
  return (
    <div className="text-data text-ink leading-relaxed break-words">
      {m.text && <Answer text={m.text} />}
      {m.status === "aborted" && <p className="mt-1 text-data-xs text-faint">중단됨</p>}
      {m.status === "error" && <p className="mt-1 text-data-xs text-danger">{m.error}</p>}
      <Queries queries={m.queries} />
    </div>
  );
});

function HistoryList({ onPick, disabled }: { onPick: (id: string) => void; disabled: boolean }) {
  const q = useQuery<ChatSummary[]>({ queryKey: CHATS_QUERY_KEY, queryFn: getChats, staleTime: 0 });
  if (q.isLoading) return <p className="px-4 py-4 text-data-xs text-faint">불러오는 중…</p>;
  if (q.isError) return <p className="px-4 py-4 text-data-xs text-danger">지난 대화를 불러오지 못했어요.</p>;
  const items = q.data ?? [];
  if (items.length === 0) return <p className="px-4 py-4 text-data-xs text-muted">지난 대화가 없어요. 대화는 7일 동안 보관돼요.</p>;
  return (
    <ul>
      {items.map((c) => (
        <li key={c.id} className="border-b border-hairline last:border-b-0">
          <button
            type="button"
            disabled={disabled}
            onClick={() => onPick(c.id)}
            className="w-full text-left px-4 py-2.5 hover:bg-cream disabled:opacity-50"
          >
            <div className="text-data text-ink truncate">{c.first_question || "(질문 없음)"}</div>
            <div className="mt-0.5 text-data-xs text-faint num">
              {shortTime(c.updated_at)} · {Math.ceil(c.turn_count / 2)}번 질문
              {c.context_title ? ` · ${c.context_title}` : ""}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** 모든 페이지 공통 — 화면 오른쪽 아래(용어 사전 버튼 왼쪽) 버튼 + 그 위로 열리는 채팅 창 */
export function ChatPanel() {
  const chat = useChat();
  const [view, setView] = useState<"chat" | "history">("chat");
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  // 사용자가 위로 올려 읽는 중이면 새 글이 와도 끌어내리지 않는다
  const stick = useRef(true);

  const open = chat?.open ?? false;
  const statusQ = useQuery<ChatStatus>({
    queryKey: ["chat-status"],
    queryFn: getChatStatus,
    enabled: open,
    staleTime: 30_000,
    refetchInterval: open ? 60_000 : false,
  });

  const msgCount = chat?.state.msgs.length ?? 0;
  const liveText = chat?.state.live?.text ?? null;
  const liveStatus = chat?.state.live?.status ?? null;
  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [msgCount, liveText, liveStatus, open, view]);

  // 창을 열거나 대화 화면으로 돌아올 때만 입력창에 커서를 둔다.
  // 새로고침으로 "열림"이 복원된 첫 화면에서는 페이지의 커서를 가져가지 않는다.
  const shown = useRef({ open, view });
  useEffect(() => {
    const changed = shown.current.open !== open || shown.current.view !== view;
    shown.current = { open, view };
    if (changed && open && view === "chat") inputRef.current?.focus();
  }, [open, view]);

  if (!chat) return null;
  const { state } = chat;
  const answering = state.live !== null;
  const busy = answering || chat.loading;
  const canSend = !busy && chat.input.trim().length > 0;

  const onPanelKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    // Esc: 지난 대화 목록 → 대화로, 대화 → 창 닫기(대화·흘러나오는 답은 유지). 한글 조합 중에는 무시한다.
    // 아래 모달(document 리스너)까지 전파되지 않게 막는다.
    if (e.key !== "Escape" || e.nativeEvent.isComposing) return;
    e.stopPropagation();
    if (view === "history") setView("chat");
    else chat.setOpen(false);
  };

  const onInputKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Safari 는 한글 조합을 끝내는 Enter 에 isComposing 대신 keyCode 229 를 준다.
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return;
    e.preventDefault();
    stick.current = true;
    chat.send();
  };

  const empty = state.msgs.length === 0 && !answering && !chat.loading;

  return (
    <>
      {chat.open && (
        <div
          role="dialog"
          aria-label="AI 분석 전문가 채팅"
          onKeyDown={onPanelKeyDown}
          className="chat-slide-up fixed right-4 bottom-16 z-[60] w-[440px] max-w-[calc(100vw-2rem)] h-[640px] max-h-[calc(100vh-6rem)] flex flex-col bg-paper border border-hairline rounded-xl shadow-bento-hover"
        >
          <div className="flex items-center gap-1.5 px-3 py-2 border-b border-hairline">
            <MessageSquareText size={14} className="text-faint" />
            <span className="text-data font-semibold text-ink flex-1">
              {view === "history" ? "지난 대화" : "AI 분석 전문가"}
            </span>
            <button
              type="button"
              aria-pressed={view === "history"}
              onClick={() => setView(view === "history" ? "chat" : "history")}
              className={`flex items-center gap-1 px-2 py-1 rounded-lg text-data-xs hover:bg-cream ${view === "history" ? "text-accent" : "text-muted"}`}
            >
              <History size={13} />
              지난 대화
            </button>
            <button
              type="button"
              disabled={answering}
              title={answering ? "답하는 중에는 새 대화를 시작할 수 없어요" : undefined}
              onClick={() => {
                chat.newChat();
                setView("chat");
              }}
              className="flex items-center gap-1 px-2 py-1 rounded-lg text-data-xs text-muted hover:bg-cream disabled:opacity-40"
            >
              <Plus size={13} />새 대화
            </button>
            <button type="button" aria-label="채팅 창 닫기" onClick={() => chat.setOpen(false)} className="p-1 text-faint hover:text-ink">
              <X size={14} />
            </button>
          </div>

          {view === "history" ? (
            <div className="flex-1 overflow-y-auto">
              {answering && <p className="px-4 pt-3 text-data-xs text-muted">답하는 중에는 다른 대화를 열 수 없어요.</p>}
              <HistoryList
                disabled={answering}
                onPick={(id) => {
                  stick.current = true;
                  chat.resume(id);
                  setView("chat");
                }}
              />
            </div>
          ) : (
            <>
              <div
                ref={bodyRef}
                onScroll={(e) => {
                  const el = e.currentTarget;
                  stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
                }}
                className="flex-1 overflow-y-auto px-4 py-3 space-y-4"
              >
                {chat.loading && <p className="text-data-xs text-faint">대화를 불러오는 중…</p>}
                {empty && (
                  <div className="text-data text-muted leading-relaxed">
                    <p>분류 결과·트리거 판정·지표를 DB 에서 직접 조회해 근거와 함께 답해요.</p>
                    <div className="mt-3 flex flex-col items-start gap-1.5">
                      {EXAMPLES.map((ex) => (
                        <button
                          key={ex}
                          type="button"
                          onClick={() => {
                            chat.setInput(ex);
                            inputRef.current?.focus();
                          }}
                          className="px-2.5 py-1.5 rounded-lg border border-hairline bg-cream text-data-xs text-ink hover:border-accent text-left"
                        >
                          {ex}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {state.msgs.map((m) => (
                  <Message key={m.id} m={m} />
                ))}
                {state.live && (
                  <div className="text-data text-ink leading-relaxed break-words" aria-live="off">
                    {state.live.text && <Answer text={state.live.text} />}
                    <p className="mt-1 flex items-center gap-1.5 text-data-xs text-muted">
                      <Loader2 size={12} className="animate-spin" />
                      {state.live.status ?? (state.live.text ? "답하는 중" : "생각하는 중")}
                    </p>
                  </div>
                )}
              </div>

              <div className="border-t border-hairline px-3 py-2 space-y-2">
                {statusQ.data?.chain_running && (
                  <p className="flex items-start gap-1.5 px-2 py-1.5 rounded-lg bg-amber-soft text-data-xs text-warning">
                    <TriangleAlert size={13} className="shrink-0 mt-px" />
                    <span>
                      LLM 분석({statusQ.data.pipelines.join(", ")})이 실행 중이에요. 같은 claude 사용량을 나눠 쓰니 꼭 필요한 질문만 해 주세요.
                    </span>
                  </p>
                )}
                {chat.banner && (
                  <p role="status" className={`px-2 py-1.5 rounded-lg text-data-xs ${chat.banner.kind === "error" ? "bg-danger-soft text-danger" : "bg-cream text-muted"}`}>
                    {chat.banner.text}
                  </p>
                )}
                {chat.stock && (
                  <div className="flex items-center gap-1.5 text-data-xs">
                    {chat.contextOff ? (
                      <>
                        <span className="text-faint truncate">맥락 꺼짐: {chat.stock.ticker}</span>
                        <button type="button" onClick={() => chat.setContextOff(false)} className="text-accent hover:underline shrink-0">
                          켜기
                        </button>
                      </>
                    ) : (
                      <>
                        <span className="text-muted truncate">
                          현재 맥락: <span className="text-ink num">{chat.stock.ticker}</span>
                          {chat.stock.name ? ` ${chat.stock.name}` : ""}
                        </span>
                        <button
                          type="button"
                          aria-label="현재 맥락 끄기"
                          title="이 종목을 질문에 붙이지 않기"
                          onClick={() => chat.setContextOff(true)}
                          className="text-faint hover:text-ink shrink-0"
                        >
                          <X size={12} />
                        </button>
                      </>
                    )}
                  </div>
                )}
                <div className="flex items-end gap-2 px-2 py-1.5 rounded-xl border border-hairline bg-cream focus-within:border-accent">
                  <textarea
                    ref={inputRef}
                    value={chat.input}
                    onChange={(e) => chat.setInput(e.target.value)}
                    onKeyDown={onInputKeyDown}
                    rows={2}
                    maxLength={QUESTION_MAX}
                    placeholder="질문을 입력하세요 (Enter 보내기 · Shift+Enter 줄바꿈)"
                    aria-label="질문"
                    className="flex-1 resize-none bg-transparent text-data outline-none placeholder:text-faint max-h-32"
                  />
                  {answering ? (
                    <button
                      type="button"
                      onClick={chat.stop}
                      aria-label="답변 중단"
                      title="중단"
                      className="shrink-0 p-1.5 rounded-lg bg-ink text-paper hover:bg-ink/90"
                    >
                      <Square size={13} fill="currentColor" />
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={!canSend}
                      onClick={() => {
                        stick.current = true;
                        chat.send();
                      }}
                      aria-label="질문 보내기"
                      className="shrink-0 p-1.5 rounded-lg bg-accent text-paper hover:bg-accent-light disabled:bg-hairline disabled:text-faint"
                    >
                      <ArrowUp size={13} />
                    </button>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      )}
      <button
        type="button"
        onClick={() => chat.setOpen(!chat.open)}
        aria-expanded={chat.open}
        className="fixed right-[5.75rem] bottom-4 z-[60] flex items-center gap-1.5 px-3 py-2 rounded-full bg-accent text-paper text-data-xs shadow-bento-hover hover:bg-accent-light"
      >
        {answering ? <Loader2 size={14} className="animate-spin" /> : <MessageSquareText size={14} />}
        전문가
      </button>
    </>
  );
}
