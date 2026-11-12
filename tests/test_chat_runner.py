"""(#281) 채팅 claude 실행기 — 허용 도구·모델·환경, 실행 파일 없음, stream-json 해석. 실제 claude 는 부르지 않는다."""
import json
import os
import stat
import sys
import time

import pytest

from kr_pipeline.chat import runner as chat_runner
from kr_pipeline.chat.runner import ChatRunError, ClaudeChatRunner, Delta, Done, ToolUse


def test_command_allows_only_the_two_db_tools(monkeypatch):
    monkeypatch.delenv("KR_CHAT_MODEL", raising=False)
    cmd = ClaudeChatRunner().command("/bin/claude", "/tmp/x/mcp.json")
    assert cmd[cmd.index("--tools") + 1] == ""  # 내장 도구(파일·셸) 없음
    i = cmd.index("--allowedTools")
    assert cmd[i + 1 : i + 3] == ["mcp__krdb__describe", "mcp__krdb__query"]
    assert cmd[i + 3].startswith("--")  # 허용 도구는 딱 2개
    assert "--strict-mcp-config" in cmd and cmd[cmd.index("--mcp-config") + 1] == "/tmp/x/mcp.json"
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert "--no-session-persistence" in cmd
    assert not any("bypassPermissions" in c or "dangerously" in c for c in cmd)
    for tool in ("Bash", "Read", "Write", "Edit", "Grep", "Glob", "WebFetch"):
        assert not any(tool in c for c in cmd[1:])


def test_model_is_chat_specific_not_classification_pin(monkeypatch):
    monkeypatch.setenv("KR_CLAUDE_MODEL", "opus")  # 운영 분류 핀 — 채팅에 영향 없어야 한다
    monkeypatch.delenv("KR_CHAT_MODEL", raising=False)
    cmd = ClaudeChatRunner().command("c", "m")
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    monkeypatch.setenv("KR_CHAT_MODEL", "haiku")
    cmd = ClaudeChatRunner().command("c", "m")
    assert cmd[cmd.index("--model") + 1] == "haiku"


def test_child_env_disables_autoupdater():
    assert ClaudeChatRunner.child_env()["DISABLE_AUTOUPDATER"] == "1"


def test_mcp_config_has_single_db_server_with_ro_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/kr_pipeline")
    monkeypatch.delenv("CHAT_DATABASE_URL", raising=False)
    cfg = ClaudeChatRunner().mcp_config()
    assert list(cfg["mcpServers"]) == ["krdb"]
    srv = cfg["mcpServers"]["krdb"]
    assert srv["command"] == sys.executable and srv["args"] == ["-m", "kr_pipeline.chat.mcp_server"]
    assert srv["env"]["CHAT_DATABASE_URL"] == "postgresql://kr_chat_ro@localhost/kr_pipeline"
    assert os.path.isdir(os.path.join(srv["env"]["PYTHONPATH"], "kr_pipeline"))


def test_missing_binary_fails_immediately(monkeypatch):
    monkeypatch.setenv("KR_CLAUDE_BIN", "/kr-test/no-such-claude")
    t0 = time.monotonic()
    with pytest.raises(ChatRunError) as e:
        list(ClaudeChatRunner(database_url="postgresql://x@h/d").stream("q"))
    assert e.value.kind == "not_found"
    assert time.monotonic() - t0 < 2  # 야간 체인의 510s 대기 게이트를 타지 않는다


def _fake_claude(tmp_path, lines, *, record=None, exit_code=0, sleep=0.0):
    """stream-json 줄을 내는 가짜 claude 실행 파일."""
    out = tmp_path / "out.jsonl"
    out.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    script = tmp_path / "claude"
    rec = f'printf "%s\\n" "$@" > "{record}"; env > "{record}.env"; cp "$(pwd)/mcp.json" "{record}.mcp"\n' if record else ""
    script.write_text(f'#!/bin/sh\n{rec}cat > /dev/null\nsleep {sleep}\ncat "{out}"\nexit {exit_code}\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def _delta(text):
    return {"type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}}}


def test_stream_parses_delta_tooluse_done_and_passes_env(tmp_path, monkeypatch):
    record = tmp_path / "argv"
    monkeypatch.setenv("KR_CLAUDE_BIN", _fake_claude(tmp_path, [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "mcp__krdb__query", "input": {"sql": "select 1 from stocks"}}]}},
        _delta("안녕"), _delta("하세요"),
        {"type": "result", "is_error": False, "result": "안녕하세요"},
    ], record=record))
    events = list(ClaudeChatRunner(database_url="postgresql://kr_chat_ro@h/d").stream("질문"))
    assert events == [ToolUse("mcp__krdb__query", "select 1 from stocks"), Delta("안녕"), Delta("하세요"),
                      Done("안녕하세요", [])]
    assert "DISABLE_AUTOUPDATER=1" in (tmp_path / "argv.env").read_text()
    mcp = json.loads((tmp_path / "argv.mcp").read_text())
    assert mcp["mcpServers"]["krdb"]["env"]["CHAT_DATABASE_URL"] == "postgresql://kr_chat_ro@h/d"
    assert "--strict-mcp-config" in record.read_text().splitlines()


@pytest.mark.parametrize("result,kind", [
    ({"result": "You've hit your limit", "api_error_status": None}, "rate_limit"),
    ({"result": "x", "api_error_status": 429}, "rate_limit"),
    ({"result": "Please run /login", "api_error_status": None}, "auth"),
    ({"result": "boom", "api_error_status": 500}, "is_error"),
])
def test_stream_classifies_error_results(tmp_path, monkeypatch, result, kind):
    monkeypatch.setenv("KR_CLAUDE_BIN", _fake_claude(tmp_path, [{"type": "result", "is_error": True, **result}]))
    with pytest.raises(ChatRunError) as e:
        list(ClaudeChatRunner(database_url="u").stream("q"))
    assert e.value.kind == kind


def test_stream_without_result_is_exit_error(tmp_path, monkeypatch):
    monkeypatch.setenv("KR_CLAUDE_BIN", _fake_claude(tmp_path, [_delta("부분")], exit_code=3))
    with pytest.raises(ChatRunError) as e:
        list(ClaudeChatRunner(database_url="u").stream("q"))
    assert e.value.kind == "exit"


def test_stream_timeout_kills_process(tmp_path, monkeypatch):
    monkeypatch.setenv("KR_CLAUDE_BIN", _fake_claude(tmp_path, [], sleep=30))
    t0 = time.monotonic()
    with pytest.raises(ChatRunError) as e:
        list(ClaudeChatRunner(database_url="u").stream("q", timeout=1))
    assert e.value.kind == "timeout" and time.monotonic() - t0 < 10


def test_abort_before_start_raises_aborted(tmp_path, monkeypatch):
    monkeypatch.setenv("KR_CLAUDE_BIN", _fake_claude(tmp_path, [], sleep=30))
    r = ClaudeChatRunner(database_url="u")
    stream = r.stream("q")
    r.abort()
    with pytest.raises(ChatRunError) as e:
        list(stream)
    assert e.value.kind == "aborted"


def test_classify_is_error_default():
    assert chat_runner.classify_is_error({"result": "weird"})[0] == "is_error"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _spawning_claude(tmp_path):
    """뒤에서 손자 프로세스를 띄우고, 글 한 조각을 낸 뒤 오래 멈춰 있는 가짜 claude."""
    pids = tmp_path / "pids"
    script = tmp_path / "claude"
    script.write_text(
        "#!/bin/sh\ncat > /dev/null\n"
        f'sleep 300 &\necho $! > "{pids}"\necho $$ >> "{pids}"\n'
        f"echo '{json.dumps(_delta('부분'))}'\n"
        "sleep 300\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script), pids


def _wait_gone(pids, seconds=5.0):
    deadline = time.monotonic() + seconds
    while any(_alive(p) for p in pids) and time.monotonic() < deadline:
        time.sleep(0.05)
    return [p for p in pids if _alive(p)]


def test_abort_midstream_kills_process_and_grandchild(tmp_path, monkeypatch):
    binary, pidfile = _spawning_claude(tmp_path)
    monkeypatch.setenv("KR_CLAUDE_BIN", binary)
    r = ClaudeChatRunner(database_url="u")
    stream = r.stream("q")
    assert next(stream) == Delta("부분")  # 프로세스가 떠서 글을 내는 중
    pids = [int(x) for x in pidfile.read_text().split()]
    assert len(pids) == 2 and all(_alive(p) for p in pids)
    t0 = time.monotonic()
    r.abort()  # 서비스의 cancel() 이 다른 스레드에서 부르는 것과 같다
    with pytest.raises(ChatRunError) as e:
        next(stream)
    assert e.value.kind == "aborted" and time.monotonic() - t0 < 5
    assert _wait_gone(pids) == []  # 뒤에서 띄운 손자까지 사라진다
    assert r._active is None


def test_close_midstream_kills_process_and_grandchild(tmp_path, monkeypatch):
    binary, pidfile = _spawning_claude(tmp_path)
    monkeypatch.setenv("KR_CLAUDE_BIN", binary)
    stream = ClaudeChatRunner(database_url="u").stream("q")
    assert next(stream) == Delta("부분")
    pids = [int(x) for x in pidfile.read_text().split()]
    stream.close()  # 이터레이터를 중간에 닫는 경로(연결 끊김)
    assert _wait_gone(pids) == []
