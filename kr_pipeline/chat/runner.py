"""(#281) 분석 전문가 채팅용 실시간 출력 `claude -p` 실행기 (stream-json).

ai-library 의 librarian/chatrunner.py 를 옮긴 것. 다른 점: 허용 도구가 DB 조회 MCP 도구 2개뿐이고
(파일·셸 도구 없음), 실행 파일이 없으면 야간 체인의 대기 게이트 없이 바로 not_found 를 낸다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from kr_pipeline.chat import dbtool
from kr_pipeline.chat.mcp_server import SERVER_NAME, TOOL_NAMES
from kr_pipeline.llm_runner.llm.claude_cli import resolve_claude_bin

log = logging.getLogger(__name__)

MAX_LINE_CHARS = 4_000_000  # stdout 한 줄 상한(넘으면 그 줄을 버린다)
EXIT_WAIT = 5.0  # stdout EOF 뒤 리더 종료를 기다리는 시간(초)

DEFAULT_MODEL = "sonnet"  # 채팅 전용 핀. 운영 분류의 KR_CLAUDE_MODEL 과 분리한다(KR_CHAT_MODEL).
REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_TOOLS = tuple(f"mcp__{SERVER_NAME}__{t}" for t in TOOL_NAMES)

ChatKind = Literal["not_found", "timeout", "exit", "is_error", "rate_limit", "auth", "aborted"]

_RATE_RE = re.compile(r"usage limit|rate limit|limit reached|hit your limit", re.IGNORECASE)
_AUTH_RE = re.compile(r"/login|not logged in|authentication|invalid api key", re.IGNORECASE)


def chat_model() -> str:
    return os.environ.get("KR_CHAT_MODEL") or DEFAULT_MODEL


def classify_is_error(data: dict) -> tuple[Literal["rate_limit", "auth", "is_error"], str]:
    """claude `result` 객체(is_error=true)를 종류로 나눈다."""
    result = str(data.get("result") or "")
    detail = result[:500]
    status = data.get("api_error_status")
    if status == 429:
        return "rate_limit", detail
    if status in (401, 403):
        return "auth", detail
    if _RATE_RE.search(result):
        return "rate_limit", detail
    if _AUTH_RE.search(result):
        return "auth", detail
    return "is_error", detail


@dataclass
class Delta:
    text: str


@dataclass
class ToolUse:
    tool: str
    path: str | None  # query 의 sql 또는 describe 의 table(없으면 None)


@dataclass
class Done:
    text: str
    denied_paths: list[str]


ChatEvent = Delta | ToolUse | Done


class ChatRunError(Exception):
    # str(e) is only the kind; detail may contain output text and must never be logged at INFO.
    def __init__(self, kind: ChatKind, detail: str = ""):
        super().__init__(kind)
        self.kind: ChatKind = kind
        self.detail = detail


class ChatRunner(Protocol):
    def stream(self, prompt: str, *, timeout: int = 300) -> Iterator[ChatEvent]: ...
    # 이터레이터를 중간에 닫으면(close/GeneratorExit) 프로세스를 끝낸다.

    def abort(self) -> None: ...
    # 다른 스레드에서 호출 가능. stream() 호출 뒤(첫 next() 전 포함)에 오면 그 스트림이 시작하지
    # 않고 ChatRunError("aborted")를 내고, 실행 중이면 프로세스를 끝낸다. 스트림이 없으면 무시한다.


def _tool_path(inp: object) -> str | None:
    if not isinstance(inp, dict):
        return None
    for key in ("sql", "table"):
        v = inp.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def _denied_paths(data: dict) -> list[str]:
    out: list[str] = []
    for d in data.get("permission_denials") or []:
        if isinstance(d, dict):
            p = _tool_path(d.get("tool_input"))
            if p:
                out.append(p)
    return out


def _kill_group(pid: int) -> None:
    """SIGKILL the child's whole process group (it runs in its own session).

    Never uses Popen.poll()/kill(): those reap the leader, after which a background child that
    still holds stdout would be missed. The pgid stays valid while any group member exists.
    """
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass  # group already gone


class _Run:
    """Kill bookkeeping for one stream() call, shared with the watchdog and abort().

    The slot exists before the process does, so an abort() that lands before Popen is kept.
    Rule: every group kill happens before the leader is reaped (finish() first, then wait()),
    so a reused pid is never signalled.
    """

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.finished = False  # set once the group was killed for cleanup; no signals after
        self.timed_out = False
        self.aborted = False

    def attach(self, proc: subprocess.Popen) -> bool:
        """Record the started process. False (and the group is killed) if abort came first."""
        with self.lock:
            self.proc = proc
            if self.aborted:
                _kill_group(proc.pid)
                return False
            return True

    def kill(self, reason: Literal["timeout", "abort"]) -> None:
        with self.lock:
            if self.finished:
                return
            if reason == "timeout":
                self.timed_out = True
            else:
                self.aborted = True
            if self.proc is not None:
                _kill_group(self.proc.pid)

    def finish(self) -> None:
        with self.lock:
            if not self.finished:
                if self.proc is not None:
                    # also catches background children of an exited leader
                    _kill_group(self.proc.pid)
                self.finished = True


def _write_stdin(f, prompt: str) -> None:
    # 별도 스레드에서 쓴다: 자식이 stdin을 읽기 전에 stdout을 가득 채워도 교착되지 않게.
    try:
        f.write(prompt)
    except (OSError, ValueError):
        pass  # child died early (or was killed); reported by the reader
    try:
        f.close()
    except (OSError, ValueError):
        pass


def _read_lines(f, on_overlong) -> Iterator[str]:
    """Lines of at most MAX_LINE_CHARS; a longer line is consumed to its newline and dropped."""
    while True:
        cap = MAX_LINE_CHARS + 1  # 상한은 줄바꿈을 뺀 글자 수: 정확히 상한인 줄 + "\n"은 통과
        chunk = f.readline(cap)
        if not chunk:
            return
        if chunk.endswith("\n") or len(chunk) < cap:
            yield chunk
            continue
        on_overlong()
        while True:
            rest = f.readline(cap)
            if not rest or rest.endswith("\n"):
                break


def _settle(run: _Run) -> int:
    """Wait (bounded) for the leader to exit without reaping it, kill the group, then reap."""
    proc = run.proc
    assert proc is not None
    deadline = time.monotonic() + EXIT_WAIT
    while True:
        try:
            # WNOWAIT: 좀비로 남겨 둔다. 그동안 pgid가 예약돼 group kill이 남의 프로세스에 닿지 않는다.
            info = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except ChildProcessError:
            break
        if info is not None or time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    run.finish()
    return proc.wait()


class ClaudeChatRunner:
    def __init__(self, model: str | None = None, *, database_url: str | None = None) -> None:
        self.model = model
        self.database_url = database_url
        self._lock = threading.Lock()
        self._active: _Run | None = None  # single-flight: the run abort() targets

    def mcp_config(self) -> dict:
        """DB 조회 MCP 서버 1개만 담은 설정. 이 venv 의 파이썬으로 띄운다."""
        return {
            "mcpServers": {
                SERVER_NAME: {
                    "command": sys.executable,
                    "args": ["-m", "kr_pipeline.chat.mcp_server"],
                    "env": {
                        "CHAT_DATABASE_URL": self.database_url or dbtool.chat_database_url(),
                        "PYTHONPATH": str(REPO_ROOT),
                    },
                }
            }
        }

    def command(self, binary: str, mcp_config_path: str) -> list[str]:
        return [
            binary,
            "--model", self.model or chat_model(),
            "-p",
            "--tools", "",  # 내장 도구(파일·셸 등) 전부 끔
            "--mcp-config", mcp_config_path,
            "--strict-mcp-config",  # 사용자·프로젝트의 다른 MCP 설정 무시
            "--allowedTools", *ALLOWED_TOOLS,
            "--setting-sources", "",
            "--no-session-persistence",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
        ]

    @staticmethod
    def child_env() -> dict[str, str]:
        env = dict(os.environ)
        env["DISABLE_AUTOUPDATER"] = "1"  # (#269) 실행 도중 claude 바이너리 교체 방지
        return env

    def abort(self) -> None:
        """Thread-safe: abort the latest stream() call, even if its process hasn't started yet."""
        with self._lock:
            run = self._active
        if run is not None:
            run.kill("abort")

    def stream(self, prompt: str, *, timeout: int = 300) -> Iterator[ChatEvent]:
        # 생성기가 아니다: 호출 즉시 실행 자리를 등록해, 첫 next() 전에 온 abort도 잃지 않는다.
        # 새 호출이 자리를 바꾸므로 지난 abort가 다음 실행을 끊지 않는다.
        run = _Run()
        with self._lock:
            self._active = run
        return self._stream(run, prompt, timeout)

    def _stream(self, run: _Run, prompt: str, timeout: int) -> Iterator[ChatEvent]:
        try:
            if run.aborted:
                raise ChatRunError("aborted", "aborted by caller")
            yield from self._spawn(run, prompt, timeout)
        finally:
            with self._lock:
                if self._active is run:
                    self._active = None

    def _spawn(self, run: _Run, prompt: str, timeout: int) -> Iterator[ChatEvent]:
        # 야간 체인의 _resolve_or_wait(최대 510s 대기)를 쓰지 않는다: 없으면 바로 알린다.
        binary = resolve_claude_bin()
        if binary is None or not os.path.isfile(binary):
            raise ChatRunError("not_found", "claude CLI not found")
        log.debug("claude chat: prompt_len=%d", len(prompt))
        # R17: 매번 빈 임시 디렉터리에서 실행
        with tempfile.TemporaryDirectory(prefix="kr-chat-claude-") as cwd, \
                tempfile.TemporaryFile() as errf:
            cfg_path = os.path.join(cwd, "mcp.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(self.mcp_config(), f)
            cmd = self.command(binary, cfg_path)
            try:
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errf,
                    cwd=cwd, text=True, encoding="utf-8", errors="replace",
                    start_new_session=True, env=self.child_env(),
                )
            except FileNotFoundError as e:
                raise ChatRunError("not_found", str(e)) from e
            except OSError as e:
                raise ChatRunError("exit", f"OS error: {e}") from e

            timer = threading.Timer(timeout, run.kill, args=("timeout",))
            timer.daemon = True
            writer = threading.Thread(target=_write_stdin, args=(proc.stdin, prompt), daemon=True)
            try:
                if not run.attach(proc):
                    raise ChatRunError("aborted", "aborted by caller")
                writer.start()
                timer.start()
                yield from self._pump(run, errf, timeout)
            finally:
                timer.cancel()
                if timer.is_alive():
                    timer.join()
                run.finish()  # before any reap
                if writer.ident is not None:
                    writer.join(5)  # the group kill breaks a blocked write (EPIPE)
                else:
                    _write_stdin(proc.stdin, "")  # never started: just close
                try:
                    if proc.stdout:
                        proc.stdout.close()
                except OSError:
                    pass
                proc.wait()

    @staticmethod
    def _pump(run: _Run, errf, timeout: int) -> Iterator[ChatEvent]:
        proc = run.proc
        assert proc is not None and proc.stdout is not None
        done: Done | None = None
        warned = False

        def overlong() -> None:
            nonlocal warned
            if not warned:
                warned = True
                log.warning("claude chat: skipped output line over %d chars", MAX_LINE_CHARS)

        # EOF comes when every holder of stdout is gone: normal exit, or a group kill
        # by the watchdog / abort() (which also reaches background children).
        for raw in _read_lines(proc.stdout, overlong):
            line = raw.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            typ = data.get("type")
            if typ == "stream_event":
                ev = data.get("event") or {}
                if isinstance(ev, dict) and ev.get("type") == "content_block_delta":
                    delta = ev.get("delta") or {}
                    if isinstance(delta, dict) and delta.get("type") == "text_delta":
                        text = delta.get("text")
                        if isinstance(text, str) and text:
                            yield Delta(text)
            elif typ == "assistant":
                content = (data.get("message") or {}).get("content") or []
                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "tool_use":
                            yield ToolUse(str(item.get("name") or ""), _tool_path(item.get("input")))
            elif typ == "result":
                if data.get("is_error"):
                    kind, detail = classify_is_error(data)
                    raise ChatRunError(kind, detail)
                done = Done(str(data.get("result") or ""), _denied_paths(data))
        if done is not None:
            rc = _settle(run)
            if rc != 0 and not (run.aborted or run.timed_out):
                # 답은 유효하다. 종료 코드만 남긴다(본문은 남기지 않는다).
                log.warning("claude chat exited rc=%d after result", rc)
            log.debug("claude chat done: has_result=True")
            yield done
            return
        if run.aborted:
            raise ChatRunError("aborted", "aborted by caller")
        if run.timed_out:
            raise ChatRunError("timeout", f"timed out after {timeout}s")
        rc = _settle(run)
        if run.aborted:  # abort() raced with a natural exit
            raise ChatRunError("aborted", "aborted by caller")
        if run.timed_out:  # the watchdog fired while waiting for exit
            raise ChatRunError("timeout", f"timed out after {timeout}s")
        log.debug("claude chat done: rc=%d has_result=False", rc)
        errf.seek(0)
        stderr = errf.read(300).decode("utf-8", "replace").strip()
        raise ChatRunError("exit", f"exit {rc}: no result. {stderr}"[:500])


class FakeChatRunner:
    def __init__(self, scripts: list[list[ChatEvent | ChatRunError]]) -> None:
        self._scripts = [list(s) for s in scripts]
        self.prompts: list[str] = []
        self.closed = 0
        self.aborted = 0
        self._abort_flag = threading.Event()
        self._active = False  # like the real runner: abort only affects a stream mid-flight

    def abort(self) -> None:
        self.aborted += 1
        if self._active:
            self._abort_flag.set()

    def stream(self, prompt: str, *, timeout: int = 300) -> Iterator[ChatEvent]:
        self.prompts.append(prompt)
        if not self._scripts:
            raise AssertionError("FakeChatRunner: no scripts left")
        self._abort_flag.clear()
        self._active = True  # slot registered by stream(), like the real runner
        return self._run(self._scripts.pop(0))

    def _run(self, script: list[ChatEvent | ChatRunError]) -> Iterator[ChatEvent]:
        try:
            for item in script:
                if self._abort_flag.is_set():
                    self._abort_flag.clear()
                    raise ChatRunError("aborted", "aborted by caller")
                if isinstance(item, ChatRunError):
                    raise item
                yield item
        except GeneratorExit:
            self.closed += 1
            raise
        finally:
            self._active = False
            self._abort_flag.clear()
