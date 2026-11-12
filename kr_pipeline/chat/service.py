"""(#281) 채팅 질문 하나를 처리한다: 단일 실행 잠금, 실시간 이벤트, 턴 저장, 중단.

ai-library chat/service.py 를 옮긴 것(인용·못 찾은 질문 기록은 뺐다). 답을 만들며 실행한 조회문은
턴의 queries 에 남겨 화면에서 근거로 보여 줄 수 있게 한다.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import asdict
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .prompt import TickerContext, build_chat_prompt
from .runner import ChatRunError, ChatRunner, Delta, Done, ToolUse
from .store import ChatStore, Conversation, Turn, TurnStatus

log = logging.getLogger(__name__)

CHAT_TIMEOUT = 300
QUERIES_MAX = 20  # 턴에 남기는 조회문 수 상한
QUERY_CHARS = 2000
BUSY_TEXT = "전문가가 답하는 중이에요"
STATUS_GENERIC = "DB 확인 중"
STATUS_TABLES = "DB 조회 중: {tables}"
STATUS_DESCRIBE = "테이블 구조 확인 중: {table}"
KST = ZoneInfo("Asia/Seoul")

ERROR_TEXT: dict[str, str] = {
    "rate_limit": "claude 사용량 한도에 걸렸어요. 잠시 뒤 다시 물어 주세요.",
    "timeout": "응답 시간이 초과됐어요",
    "auth": "claude 로그인이 필요해요",
    "not_found": "claude 프로그램을 찾지 못했어요",
}

_TABLE_RE = re.compile(r"\b(?:from|join)\s+(?:public\.)?([a-z_][a-z0-9_]*)", re.IGNORECASE)


def error_text(kind: str) -> str:
    return ERROR_TEXT.get(kind, f"전문가가 답하지 못했어요({kind})")


def status_text(ev: ToolUse) -> str:
    """도구 호출 한 번을 화면 진행 문구로. 조회문에서 테이블 이름만 뽑는다(조회문 자체는 내지 않는다)."""
    if not ev.path:
        return STATUS_GENERIC
    if ev.tool.endswith("__describe"):
        return STATUS_DESCRIBE.format(table=ev.path[:63])
    tables: list[str] = []
    for t in _TABLE_RE.findall(ev.path):
        if t.lower() not in tables:
            tables.append(t.lower())
    return STATUS_TABLES.format(tables=", ".join(tables[:4])) if tables else STATUS_GENERIC


class ConversationNotFound(KeyError):
    """이어 물을 대화가 없거나 읽을 수 없다(API는 404로 바꾼다)."""


class ChatBusy(Exception):
    def __init__(self) -> None:
        super().__init__(BUSY_TEXT)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def _history(turns: list[Turn]) -> list[tuple[str, str]]:
    """(사용자, 전문가) 쌍 중 전문가 턴이 done인 것만."""
    out: list[tuple[str, str]] = []
    for prev, cur in zip(turns, turns[1:], strict=False):
        if prev.role == "user" and cur.role == "assistant" and cur.status == "done":
            out.append((prev.text, cur.text))
    return out


class ChatService:
    def __init__(
        self, chats: ChatStore, runner: ChatRunner, *, clock: Callable[[], float] = time.time
    ) -> None:
        self.chats = chats
        self.runner = runner
        self._clock = clock
        self._busy = threading.Lock()  # 동시 채팅 1개(비차단 획득)
        self._state = threading.Lock()  # 아래 필드들 보호
        self._in_flight = False
        self._conv_id: str | None = None
        self._request_id: str | None = None
        self._cancel = threading.Event()

    # ---- 공개 API -------------------------------------------------------------------------

    def ask(
        self, question: str, *, conversation_id: str | None, context: TickerContext | None
    ) -> Iterator[dict]:
        """SSE 이벤트 dict를 낸다. 첫 next()에서 ChatBusy 또는 ConversationNotFound가 날 수 있다."""
        return self._ask(question, conversation_id, context)

    def cancel(self, request_id: str | None = None) -> None:
        """다른 스레드에서 불러도 된다. 답하는 중인 질문을 중단한다(없으면 아무것도 안 함).

        request_id(start 이벤트의 값)를 주면 그 요청이 답하는 중일 때만 중단한다. 늦게 온
        중단 요청이 다음 질문을 끊지 않게 한다. None이면 지금 답하는 질문을 중단한다.
        """
        with self._state:
            if not self._in_flight:
                return
            if request_id is not None and request_id != self._request_id:
                return
            conv_id = self._conv_id
            self._cancel.set()
            # _state 안에서 부른다: 밖에서 부르면 이 요청이 끝나고 다음 질문이 실행기에
            # 등록된 뒤에 abort가 닿아 다음 질문을 끊을 수 있다.
            self.runner.abort()
        log.info("chat cancel requested: conv=%s", conv_id)

    # ---- 내부 -----------------------------------------------------------------------------

    def _ask(
        self, question: str, conversation_id: str | None, context: TickerContext | None
    ) -> Iterator[dict]:
        if not self._busy.acquire(blocking=False):
            raise ChatBusy()
        request_id = uuid.uuid4().hex
        released = False

        def release() -> None:
            # done 이벤트 직전에 한 번, 아니면 finally에서 한 번만 푼다(두 번 풀면 다음 질문의
            # 잠금을 풀게 된다).
            nonlocal released
            if released:
                return
            released = True
            with self._state:
                self._in_flight = False
                self._conv_id = None
                self._request_id = None
                self._cancel.clear()
            self._busy.release()

        try:
            with self._state:
                self._cancel.clear()
                self._conv_id = conversation_id
                self._request_id = request_id
                self._in_flight = True
            yield from self._run(question, conversation_id, context, request_id, release)
        finally:
            release()

    def _run(
        self,
        question: str,
        conversation_id: str | None,
        context: TickerContext | None,
        request_id: str,
        release: Callable[[], None],
    ) -> Iterator[dict]:
        try:
            self.chats.purge()
        except Exception as e:  # noqa: BLE001  오래된 대화 삭제 실패가 질문을 막지 않게
            log.warning("chat purge failed: %s", type(e).__name__)
        conv: Conversation
        if conversation_id is None:
            ctx = {"ticker": context.ticker, "title": context.title} if context is not None else None
            conv = self.chats.create(ctx)
        else:
            try:
                conv = self.chats.get(conversation_id)
            except KeyError:
                raise ConversationNotFound(conversation_id) from None  # → 404
        with self._state:
            self._conv_id = conv.id
        history = _history(conv.turns)
        now = self._clock()
        self.chats.append(conv.id, Turn("user", question, _iso(now), id=Turn.new_id()))
        today = datetime.fromtimestamp(now, KST).date().isoformat()
        prompt = build_chat_prompt(question, context=context, history=history, today=today)
        log.info("chat ask: conv=%s q_len=%d history=%d", conv.id, len(question), len(history))

        parts: list[str] = []
        queries: list[str] = []
        stream: Iterator | None = None
        try:
            # start도 try 안에서 낸다: 첫 이벤트 직후 연결이 끊겨도(GeneratorExit) aborted를 저장한다.
            yield {"type": "start", "conversation_id": conv.id, "request_id": request_id}
            if self._cancel.is_set():
                self._save(conv.id, "", "aborted")
                return
            stream = self.runner.stream(prompt, timeout=CHAT_TIMEOUT)
            if self._cancel.is_set():
                # cancel()의 abort가 슬롯 등록 전에 닿아 사라졌을 수 있다. 등록 뒤 다시 보낸다.
                self.runner.abort()
            done: Done | None = None
            for ev in stream:
                if self._cancel.is_set():
                    break
                if isinstance(ev, Delta):
                    parts.append(ev.text)
                    yield {"type": "delta", "text": ev.text}
                elif isinstance(ev, ToolUse):
                    if ev.path and ev.tool.endswith("__query") and len(queries) < QUERIES_MAX:
                        queries.append(ev.path[:QUERY_CHARS])
                    yield {"type": "status", "text": status_text(ev)}
                elif isinstance(ev, Done):
                    done = ev
                    break
            if self._cancel.is_set():
                self._abort_stream(stream)
                self._save(conv.id, "".join(parts), "aborted", queries=queries)
                return
            if done is None:
                raise ChatRunError("exit", "stream ended without result")
            text = done.text or "".join(parts)
            turn = Turn("assistant", text, _iso(self._clock()), "done", queries=queries,
                        id=Turn.new_id())  # fmt: skip
            self.chats.append(conv.id, turn)
        except ChatRunError as e:
            if e.kind == "aborted" or self._cancel.is_set():
                self._save(conv.id, "".join(parts), "aborted", queries=queries)
                if self._cancel.is_set():
                    return
            else:
                self._save(conv.id, "".join(parts), "error", error=e.kind, queries=queries)
            log.info("chat error: conv=%s kind=%s partial_len=%d", conv.id, e.kind,
                     sum(map(len, parts)))  # fmt: skip
            yield {"type": "error", "kind": e.kind, "message": error_text(e.kind)}
            return
        except GeneratorExit:
            self._abort_stream(stream)
            self._save(conv.id, "".join(parts), "aborted", queries=queries)
            raise
        except Exception as e:  # noqa: BLE001  예상 못 한 오류도 턴과 error 이벤트로 남긴다
            log.warning("chat internal error: conv=%s err=%s", conv.id, type(e).__name__)
            self._save(conv.id, "".join(parts), "error", error="internal", queries=queries)
            yield {"type": "error", "kind": "internal", "message": error_text("internal")}
            return
        finally:
            self._abort_stream(stream)

        log.info("chat done: conv=%s a_len=%d queries=%d", conv.id, len(text), len(queries))
        # done을 받은 클라이언트가 바로 다음 질문을 보내도 409가 나지 않게 먼저 푼다.
        release()
        yield {"type": "done", "turn": asdict(turn)}

    def _abort_stream(self, stream: Iterator | None) -> None:
        if stream is None:
            return
        try:
            stream.close()  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            log.warning("closing chat stream failed: %s", type(e).__name__)

    def _save(self, conv_id: str, text: str, status: TurnStatus, *, error: str | None = None,
              queries: list[str] | None = None) -> None:  # fmt: skip
        try:
            self.chats.append(
                conv_id,
                Turn("assistant", text, _iso(self._clock()), status, queries=list(queries or []),
                     error=error, id=Turn.new_id()),  # fmt: skip
            )
        except Exception as e:  # noqa: BLE001  중단·오류 경로에서 저장 실패가 원래 흐름을 가리지 않게
            log.warning("saving %s turn failed: conv=%s err=%s", status, conv_id, type(e).__name__)
            return
        log.info("chat %s: conv=%s partial_len=%d", status, conv_id, len(text))
