"""(#281) AI 분석 전문가 채팅 API: POST /api/chat(SSE), GET /api/chats, GET /api/chats/{id}, GET /api/chat/status.

ai-library api_chat.py 를 옮긴 것. 질문은 한 번에 1개(겹치면 409), 연결이 끊기거나 중단하면 claude 프로세스를 끝내고
그 턴을 aborted 로 저장한다.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import asdict
from pathlib import Path

import anyio
import anyio.to_thread
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg import Connection
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from api.deps import get_conn
from kr_pipeline.chat.prompt import TickerContext, build_ticker_context
from kr_pipeline.chat.runner import REPO_ROOT, ClaudeChatRunner
from kr_pipeline.chat.service import BUSY_TEXT, ChatBusy, ChatService, ConversationNotFound
from kr_pipeline.chat.store import ChatStore

log = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

QUESTION_MAX = 2000
DISCONNECT_POLL = 0.5
CHAIN_STALE_HOURS = 12  # 이보다 오래된 running 행은 죽은 실행의 잔재로 본다
NOT_FOUND_TEXT = "대화를 찾을 수 없어요"
INTERNAL_TEXT = "전문가에게 질문하지 못했어요."
SSE_HEADERS = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
_END = object()

_service: ChatService | None = None
_service_lock = threading.Lock()


def chats_dir() -> Path:
    return Path(os.environ.get("KR_CHAT_DIR") or REPO_ROOT / "data" / "chats")


def get_service() -> ChatService:
    """프로세스에 하나. 테스트는 이 모듈의 _service 를 바꿔 끼운다."""
    global _service
    with _service_lock:
        if _service is None:
            _service = ChatService(ChatStore(chats_dir()), ClaudeChatRunner())
        return _service


def _bad_request(message: str) -> JSONResponse:
    return JSONResponse({"error": "invalid_request", "message": message}, status_code=400)


def _conv_not_found() -> JSONResponse:
    return JSONResponse({"error": "not_found", "message": NOT_FOUND_TEXT}, status_code=404)


def _internal_error() -> JSONResponse:
    return JSONResponse({"error": "internal", "message": INTERNAL_TEXT}, status_code=500)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


class _ChatStream:
    """동기 ask 제너레이터를 스레드에서 한 칸씩 당기고, 끝날 때 한 번만 정리한다."""

    def __init__(self, service: ChatService, gen: Iterator[dict]) -> None:
        self.service = service
        self.gen = gen
        self.request_id: str | None = None
        self._pulling = threading.Lock()  # next()와 close()가 겹치지 않게
        self._finished = False

    def _next(self) -> object:
        with self._pulling:
            return next(self.gen, _END)

    async def pull(self) -> object:
        # 취소되면 기다리지 않고 돌아온다. 남은 next()는 finish()가 cancel로 풀고 끝나길 기다린다.
        return await anyio.to_thread.run_sync(self._next, abandon_on_cancel=True)

    def _close(self) -> None:
        if self.request_id is not None:
            self.service.cancel(self.request_id)  # claude 를 기다리며 멈춘 next()를 푼다
        with self._pulling:
            try:
                self.gen.close()  # 끝나지 않았으면 서비스의 중단 처리(aborted 저장·잠금 해제)
            except Exception as e:  # noqa: BLE001
                log.warning("closing chat generator failed: %s", type(e).__name__)

    async def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(self._close)


class _ChatResponse(StreamingResponse):
    """응답이 어떻게 끝나든(정상·끊김·취소·본문 미시작) 제너레이터를 정리한다."""

    def __init__(self, stream: _ChatStream, content: AsyncIterator[str]) -> None:
        super().__init__(content, media_type="text/event-stream", headers=SSE_HEADERS)
        self._chat_stream = stream

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        except ClientDisconnect:
            log.info("chat client disconnected")
        except OSError as e:
            log.warning("chat response failed: %s", type(e).__name__)
        finally:
            aclose = getattr(self.body_iterator, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception), anyio.CancelScope(shield=True):
                    await aclose()
            await self._chat_stream.finish()


def _ticker_context(conn_provider: Callable[[], Iterator[Connection]], ticker: str) -> TickerContext | None:
    # 종목 요약을 읽는 동안만 연결을 쓴다. 답이 도는 수 분 동안 풀 연결을 붙잡지 않는다.
    with contextlib.contextmanager(conn_provider)() as conn:
        return build_ticker_context(conn, ticker)


@router.post("/api/chat")
async def chat(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _bad_request("JSON 본문이 필요해요.")
    if not isinstance(body, dict):
        return _bad_request("JSON 객체가 필요해요.")
    question = body.get("question")
    if not isinstance(question, str):
        return _bad_request("질문을 입력해 주세요.")
    question = question.strip()
    if not 1 <= len(question) <= QUESTION_MAX:
        return _bad_request(f"질문은 1~{QUESTION_MAX}자로 써 주세요.")
    conv_id = body.get("conversation_id")
    ticker = body.get("ticker")
    if conv_id is not None and not isinstance(conv_id, str):
        return _bad_request("conversation_id 형식이 틀렸어요.")
    if ticker is not None and not isinstance(ticker, str):
        return _bad_request("ticker 형식이 틀렸어요.")

    service = get_service()
    context = None
    if ticker:
        # Depends 로 받지 않는다(받으면 스트림이 끝날 때까지 연결을 쥔다). 테스트의 get_conn 바꿔 끼우기는 그대로 따른다.
        provider = request.app.dependency_overrides.get(get_conn, get_conn)
        try:
            # 없는 종목·읽기 실패는 조용히 맥락 없이 답한다.
            context = await run_in_threadpool(_ticker_context, provider, ticker)
        except Exception as e:  # noqa: BLE001
            log.warning("chat context failed: %s", type(e).__name__)
    stream = _ChatStream(service, service.ask(question, conversation_id=conv_id, context=context))
    # 409·404는 스트림을 열기 전에 판정한다: 첫 이벤트(start)를 미리 꺼낸다.
    try:
        first = await stream.pull()
    except ChatBusy:
        return JSONResponse({"error": "busy", "message": BUSY_TEXT}, status_code=409)
    except ConversationNotFound:
        return _conv_not_found()
    except Exception as e:  # noqa: BLE001  예상 못 한 오류도 JSON으로 답한다
        log.warning("chat start failed: %s", type(e).__name__)
        await stream.finish()
        return _internal_error()
    except BaseException:
        await stream.finish()
        raise
    if first is _END or not isinstance(first, dict):  # 일어나지 않아야 한다
        await stream.finish()
        return _internal_error()
    stream.request_id = first.get("request_id")

    async def watch_disconnect() -> None:
        # claude 가 아무것도 내지 않는 동안에도 끊김을 알아채 중단한다.
        while not await request.is_disconnected():
            await asyncio.sleep(DISCONNECT_POLL)
        log.info("chat client disconnected: conv=%s", first.get("conversation_id"))
        await run_in_threadpool(service.cancel, stream.request_id)

    async def events() -> AsyncIterator[str]:
        watcher = asyncio.create_task(watch_disconnect())
        try:
            yield _sse(first)
            while True:
                ev = await stream.pull()
                if ev is _END:
                    break
                yield _sse(ev)  # type: ignore[arg-type]
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                with anyio.CancelScope(shield=True):
                    await watcher
            await stream.finish()

    return _ChatResponse(stream, events())


@router.get("/api/chats")
def list_chats():
    chats = get_service().chats
    try:
        chats.purge()
    except Exception as e:  # noqa: BLE001  삭제 실패가 목록을 막지 않게
        log.warning("chat purge failed: %s", type(e).__name__)
    return {"items": [c.summary() for c in chats.list()]}


@router.get("/api/chats/{conv_id}")
def get_chat(conv_id: str):
    try:
        conv = get_service().chats.get(conv_id)
    except KeyError:
        return _conv_not_found()
    return asdict(conv)


@router.get("/api/chat/status")
def chat_status(conn: Connection = Depends(get_conn)):
    """위젯의 경고용: LLM 체인(야간·주말·백필)이 실행 중인가. 채팅은 같은 claude 사용량 한도를 나눠 쓴다."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT pipeline FROM pipeline_runs "
            "WHERE status = 'running' AND pipeline LIKE 'llm\\_%%' "
            "AND started_at > now() - make_interval(hours => %s) ORDER BY 1",
            (CHAIN_STALE_HOURS,),
        )
        running = [r[0] for r in cur.fetchall()]
    return {"chain_running": bool(running), "pipelines": running}
