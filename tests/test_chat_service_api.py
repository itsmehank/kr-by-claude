"""(#281) 채팅 서비스·API — 가짜 실행기로 이벤트 순서, 동시 질문 409, 중단 시 aborted 저장을 본다."""
import json
import threading
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.deps import get_conn
from api.main import app
from api.routers import chat as chat_router
from kr_pipeline.chat.runner import ChatRunError, Delta, Done, ToolUse
from kr_pipeline.chat.service import BUSY_TEXT, ChatBusy, ChatService, ConversationNotFound, status_text
from kr_pipeline.chat.store import ChatStore

BLOCK = object()  # 이 자리에서 release 또는 abort를 기다린다
Q = ToolUse("mcp__krdb__query", "SELECT decision FROM trigger_evaluation_log t JOIN stocks s ON s.ticker = t.symbol")


class ScriptChatRunner:
    """stream()마다 스크립트 하나를 쓴다. BLOCK에서는 release/abort를 기다린다."""

    def __init__(self, scripts: list[list]) -> None:
        self.scripts = [list(s) for s in scripts]
        self.prompts: list[str] = []
        self.blocked = threading.Event()
        self.release = threading.Event()
        self._abort = threading.Event()
        self.aborts = 0

    def abort(self) -> None:
        self.aborts += 1
        self._abort.set()

    def stream(self, prompt: str, *, timeout: int = 300) -> Iterator:
        self.prompts.append(prompt)
        return self._run(self.scripts.pop(0))

    def _run(self, script: list) -> Iterator:
        self._abort.clear()
        for item in script:
            if item is BLOCK:
                self.blocked.set()
                deadline = time.monotonic() + 5
                while not self.release.is_set():
                    if self._abort.wait(0.01):
                        raise ChatRunError("aborted", "aborted by caller")
                    if time.monotonic() > deadline:
                        raise AssertionError("BLOCK was never released")
                continue
            if isinstance(item, Exception):
                raise item
            yield item


@pytest.fixture
def make(tmp_path):
    def _make(scripts):
        runner = ScriptChatRunner(scripts)
        store = ChatStore(tmp_path / "chats")
        return ChatService(store, runner), runner, store
    return _make


# ---- 서비스 ---------------------------------------------------------------------------------

def test_service_event_order_and_saved_turns(make):
    svc, runner, store = make([[Q, Delta("시장 "), Delta("게이트"), Done("시장 게이트 미충족", [])]])
    events = list(svc.ask("왜 wait?", conversation_id=None, context=None))
    assert [e["type"] for e in events] == ["start", "status", "delta", "delta", "done"]
    assert events[1]["text"] == "DB 조회 중: trigger_evaluation_log, stocks"
    turn = events[-1]["turn"]
    assert turn["text"] == "시장 게이트 미충족" and turn["status"] == "done" and turn["queries"] == [Q.path]
    conv = store.get(events[0]["conversation_id"])
    assert [(t.role, t.status) for t in conv.turns] == [("user", "done"), ("assistant", "done")]
    assert runner.prompts[0].endswith("사용자 질문:\n왜 wait?")


def test_service_separates_text_before_and_after_tool_call(make):
    svc, _, store = make([[Delta("확인해 볼게요."), Q, Q, Delta("결론은 "), Delta("wait 입니다."),
                           ChatRunError("timeout", "d")]])
    events = list(svc.ask("q", conversation_id=None, context=None))
    deltas = [e["text"] for e in events if e["type"] == "delta"]
    assert deltas == ["확인해 볼게요.", "\n\n결론은 ", "wait 입니다."]
    # 저장되는 부분 글도 화면에 나간 글과 같다
    assert store.get(events[0]["conversation_id"]).turns[-1].text == "확인해 볼게요.\n\n결론은 wait 입니다."


def test_service_no_separator_when_tool_call_comes_first(make):
    svc, _, _ = make([[Q, Delta("\n답"), Q, Delta("\n\n둘째"), Done("최종", [])]])
    events = list(svc.ask("q", conversation_id=None, context=None))
    assert [e["text"] for e in events if e["type"] == "delta"] == ["\n답", "\n\n둘째"]
    assert events[-1]["turn"]["text"] == "최종"  # 저장되는 답은 claude 의 최종 결과


def test_status_text_variants():
    assert status_text(ToolUse("mcp__krdb__describe", "stocks")) == "테이블 구조 확인 중: stocks"
    assert status_text(ToolUse("mcp__krdb__describe", None)) == "DB 확인 중"
    assert status_text(ToolUse("mcp__krdb__query", "select 1")) == "DB 확인 중"


def test_service_followup_includes_history_and_keeps_conversation(make):
    svc, runner, store = make([[Done("첫 답", [])], [Done("둘째 답", [])]])
    first = list(svc.ask("첫 질문", conversation_id=None, context=None))
    conv_id = first[0]["conversation_id"]
    list(svc.ask("이어 질문", conversation_id=conv_id, context=None))
    assert "사용자: 첫 질문\n전문가: 첫 답" in runner.prompts[1]
    assert len(store.get(conv_id).turns) == 4


def test_service_unknown_conversation(make):
    svc, _, _ = make([])
    with pytest.raises(ConversationNotFound):
        next(svc.ask("q", conversation_id="caaaaaaaaaaa", context=None))
    # 실패 뒤 잠금이 풀려 다음 질문을 받는다
    with pytest.raises(ConversationNotFound):
        next(svc.ask("q", conversation_id="caaaaaaaaaaa", context=None))


def test_service_busy_while_answering(make):
    svc, runner, _ = make([[BLOCK, Done("답", [])]])
    gen = svc.ask("q1", conversation_id=None, context=None)
    assert next(gen)["type"] == "start"
    with pytest.raises(ChatBusy):
        next(svc.ask("q2", conversation_id=None, context=None))
    runner.release.set()
    assert [e["type"] for e in gen] == ["done"]


@pytest.mark.parametrize("kind,msg", [
    ("rate_limit", "claude 사용량 한도에 걸렸어요. 잠시 뒤 다시 물어 주세요."),
    ("not_found", "claude 프로그램을 찾지 못했어요"),
    ("auth", "claude 로그인이 필요해요"),
    ("timeout", "응답 시간이 초과됐어요"),
])
def test_service_error_event_and_error_turn(make, kind, msg):
    svc, _, store = make([[Delta("부분"), ChatRunError(kind, "detail")]])
    events = list(svc.ask("q", conversation_id=None, context=None))
    assert events[-1] == {"type": "error", "kind": kind, "message": msg}
    last = store.get(events[0]["conversation_id"]).turns[-1]
    assert (last.status, last.error, last.text) == ("error", kind, "부분")


def test_service_unexpected_exception_is_internal_error(make):
    svc, _, store = make([[RuntimeError("boom")]])
    events = list(svc.ask("q", conversation_id=None, context=None))
    assert events[-1]["kind"] == "internal"
    assert store.get(events[0]["conversation_id"]).turns[-1].status == "error"


def test_service_cancel_saves_partial_as_aborted_and_frees_lock(make):
    svc, runner, store = make([[Q, Delta("부분 답"), BLOCK, Done("끝", [])], [Done("다음", [])]])
    gen = svc.ask("q", conversation_id=None, context=None)
    start = next(gen)
    assert [next(gen)["type"], next(gen)["type"]] == ["status", "delta"]
    threading.Timer(0.05, svc.cancel, args=(start["request_id"],)).start()
    assert list(gen) == []  # 중단되면 done/error 없이 끝난다
    last = store.get(start["conversation_id"]).turns[-1]
    assert (last.status, last.text, last.queries) == ("aborted", "부분 답", [Q.path])
    assert runner.aborts >= 1
    assert list(svc.ask("다음", conversation_id=None, context=None))[-1]["type"] == "done"


def test_service_close_midstream_saves_aborted(make):
    svc, _, store = make([[Delta("부분"), BLOCK]])
    gen = svc.ask("q", conversation_id=None, context=None)
    conv_id = next(gen)["conversation_id"]
    next(gen)
    gen.close()  # 클라이언트 연결 끊김
    assert store.get(conv_id).turns[-1].status == "aborted"


def test_service_cancel_with_other_request_id_is_ignored(make):
    svc, runner, _ = make([[BLOCK, Done("답", [])]])
    gen = svc.ask("q", conversation_id=None, context=None)
    next(gen)
    svc.cancel("not-this-request")
    runner.release.set()
    assert list(gen)[-1]["type"] == "done" and runner.aborts == 0


# ---- API ------------------------------------------------------------------------------------

@pytest.fixture
def api(make, db, monkeypatch):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override

    def _api(scripts):
        svc, runner, store = make(scripts)
        monkeypatch.setattr(chat_router, "_service", svc)
        return TestClient(app), runner, store
    yield _api
    app.dependency_overrides.pop(get_conn, None)


def _events(resp):
    return [json.loads(b[len("data: "):]) for b in resp.text.split("\n\n") if b.startswith("data: ")]


def test_api_chat_streams_sse(api):
    client, _, store = api([[Q, Delta("답"), Done("답", [])]])
    resp = client.post("/api/chat", json={"question": "  왜 wait?  "})
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-store"
    ev = _events(resp)
    assert [e["type"] for e in ev] == ["start", "status", "delta", "done"]
    assert store.get(ev[0]["conversation_id"]).turns[0].text == "왜 wait?"


@pytest.mark.parametrize("body", [
    {}, {"question": ""}, {"question": "   "}, {"question": 3}, {"question": "가" * 2001},
    {"question": "q", "conversation_id": 5}, {"question": "q", "ticker": 93320}, ["q"],
])
def test_api_chat_bad_request(api, body):
    client, runner, _ = api([])
    resp = client.post("/api/chat", json=body)
    assert resp.status_code == 400 and resp.json()["error"] == "invalid_request"
    assert runner.prompts == []


def test_api_chat_not_json(api):
    client, _, _ = api([])
    assert client.post("/api/chat", content=b"not json").status_code == 400


def test_api_chat_unknown_conversation_404(api):
    client, _, _ = api([])
    resp = client.post("/api/chat", json={"question": "q", "conversation_id": "caaaaaaaaaaa"})
    assert resp.status_code == 404 and resp.json()["error"] == "not_found"


def test_api_chat_busy_409(api):
    client, runner, _ = api([[BLOCK, Done("답", [])]])
    results = {}

    def first():
        results["first"] = client.post("/api/chat", json={"question": "q1"})

    t = threading.Thread(target=first)
    t.start()
    assert runner.blocked.wait(5)
    resp = client.post("/api/chat", json={"question": "q2"})
    assert resp.status_code == 409 and resp.json() == {"error": "busy", "message": BUSY_TEXT}
    runner.release.set()
    t.join(5)
    assert _events(results["first"])[-1]["type"] == "done"


def test_api_chat_ticker_context_goes_into_prompt_and_conversation(api, db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market, sector, listed_at) "
                    "VALUES ('9CHT03', '맥락종목', 'KOSDAQ', '반도체', '2020-01-01')")
    client, runner, store = api([[Done("답", [])], [Done("답", [])]])
    ev = _events(client.post("/api/chat", json={"question": "q", "ticker": "9CHT03"}))
    assert "<context>\n종목: 9CHT03 맥락종목" in runner.prompts[0]
    assert store.get(ev[0]["conversation_id"]).context == {"ticker": "9CHT03", "title": "맥락종목"}
    # 없는 종목은 조용히 맥락 없이 답한다
    client.post("/api/chat", json={"question": "q", "ticker": "000000"})
    assert "<context>" not in runner.prompts[1]


def test_api_list_and_get_chats(api):
    client, _, _ = api([[Done("답1", [])], [Done("답2", [])]])
    a = _events(client.post("/api/chat", json={"question": "첫 대화"}))[0]["conversation_id"]
    b = _events(client.post("/api/chat", json={"question": "둘째 대화"}))[0]["conversation_id"]
    items = client.get("/api/chats").json()["items"]
    assert {i["id"] for i in items} == {a, b} and all(i["turn_count"] == 2 for i in items)
    got = client.get(f"/api/chats/{a}").json()
    assert [t["text"] for t in got["turns"]] == ["첫 대화", "답1"]
    assert client.get("/api/chats/caaaaaaaaaaa").status_code == 404
    assert client.get("/api/chats/..%2Fx").status_code == 404


def test_api_chat_status_reports_running_llm_chain(api, db):
    client, _, _ = api([])
    assert client.get("/api/chat/status").json() == {"chain_running": False, "pipelines": []}
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO pipeline_runs (pipeline, mode, started_at, status) VALUES
                 ('llm_weekend', 'weekend', NOW() - INTERVAL '10 minutes', 'running'),
                 ('llm_daily_delta', 'full-daily', NOW() - INTERVAL '2 days', 'running'),
                 ('llm_daily_delta', 'full-daily', NOW() - INTERVAL '1 hour', 'success'),
                 ('ohlcv', 'incremental', NOW() - INTERVAL '1 minute', 'running')""")
    # 12시간 넘은 running(죽은 실행의 잔재)과 LLM 이 아닌 파이프라인은 세지 않는다
    assert client.get("/api/chat/status").json() == {"chain_running": True, "pipelines": ["llm_weekend"]}


def test_api_default_service_uses_chat_dir_env(monkeypatch, tmp_path):
    monkeypatch.setattr(chat_router, "_service", None)
    monkeypatch.setenv("KR_CHAT_DIR", str(tmp_path / "c"))
    svc = chat_router.get_service()
    assert svc.chats.root == tmp_path / "c" and chat_router.get_service() is svc


def test_api_chat_does_not_hold_db_connection_while_answering(api, monkeypatch):
    """종목 요약을 읽을 때만 연결을 열고, 답이 도는 동안에는 이미 돌려준 상태다."""
    client, runner, _ = api([[BLOCK, Done("답", [])], [Done("답", [])]])
    state = {"opened": 0, "open_now": 0}

    def provider():
        state["opened"] += 1
        state["open_now"] += 1
        try:
            yield object()
        finally:
            state["open_now"] -= 1

    seen = []
    monkeypatch.setattr(chat_router, "build_ticker_context", lambda conn, ticker: seen.append(ticker))
    app.dependency_overrides[get_conn] = provider
    results = {}
    t = threading.Thread(
        target=lambda: results.update(r=client.post("/api/chat", json={"question": "q", "ticker": "093320"})))
    t.start()
    assert runner.blocked.wait(5)
    assert state == {"opened": 1, "open_now": 0} and seen == ["093320"]  # 답하는 중: 연결 없음
    runner.release.set()
    t.join(5)
    assert _events(results["r"])[-1]["type"] == "done"
    client.post("/api/chat", json={"question": "q"})  # 종목이 없으면 연결을 열지도 않는다
    assert state == {"opened": 1, "open_now": 0}


def test_api_chat_route_has_no_connection_dependency():
    route = next(r for r in app.routes if getattr(r, "path", None) == "/api/chat")
    assert [d.call for d in route.dependant.dependencies] == []


class _FakeRequest:
    """연결 끊김을 흉내 낸다(TestClient 는 중간에 끊을 수 없다)."""

    def __init__(self, body: dict) -> None:
        self.app = app
        self._body = body
        self.gone = False
        self.polls = 0

    async def json(self) -> dict:
        return self._body

    async def is_disconnected(self) -> bool:
        self.polls += 1
        return self.gone


def test_api_chat_disconnect_while_claude_is_silent_aborts(api, monkeypatch):
    """claude 가 아무것도 내지 않는 동안 연결이 끊기면, 감시가 알아채 중단하고 aborted 로 저장한다."""
    import asyncio

    _, runner, store = api([[Delta("부분"), BLOCK, Done("끝", [])], [Done("다음", [])]])
    monkeypatch.setattr(chat_router, "DISCONNECT_POLL", 0.01)
    req = _FakeRequest({"question": "q"})

    async def go():
        resp = await chat_router.chat(req)
        it = resp.body_iterator
        start = json.loads((await anext(it))[len("data: "):])
        assert json.loads((await anext(it))[len("data: "):]) == {"type": "delta", "text": "부분"}

        async def drain() -> list:
            return [chunk async for chunk in it]

        rest = asyncio.create_task(drain())  # 다음 이벤트를 기다리며 멈춘다(claude 가 조용한 구간)
        assert await asyncio.to_thread(runner.blocked.wait, 5)
        await asyncio.sleep(0.05)
        assert req.polls > 0 and runner.aborts == 0 and not rest.done()  # 연결이 살아 있으면 건드리지 않는다
        req.gone = True
        return start, await rest  # 스트림을 닫지 않았는데도 끝난다 = 감시가 중단시켰다

    start, rest = asyncio.run(asyncio.wait_for(go(), 10))
    assert rest == [] and runner.aborts >= 1
    last = store.get(start["conversation_id"]).turns[-1]
    assert (last.status, last.text) == ("aborted", "부분")
    # 잠금이 풀려 다음 질문을 받는다
    svc = chat_router.get_service()
    assert list(svc.ask("다음", conversation_id=None, context=None))[-1]["type"] == "done"


def test_api_chat_stream_closed_by_server_aborts_and_stops_watcher(api, monkeypatch):
    """응답이 중간에 닫히면(전송 실패 등) 감시를 멈추고 실행을 중단한다."""
    import asyncio

    _, runner, store = api([[Delta("부분"), BLOCK, Done("끝", [])]])
    monkeypatch.setattr(chat_router, "DISCONNECT_POLL", 0.01)
    req = _FakeRequest({"question": "q"})

    async def go():
        resp = await chat_router.chat(req)
        it = resp.body_iterator
        start = json.loads((await anext(it))[len("data: "):])
        await anext(it)
        await it.aclose()
        polls = req.polls
        await asyncio.sleep(0.1)
        assert req.polls == polls  # 감시 작업이 남아 돌지 않는다
        return start

    start = asyncio.run(asyncio.wait_for(go(), 10))
    assert store.get(start["conversation_id"]).turns[-1].status == "aborted" and runner.aborts >= 1
