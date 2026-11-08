"""#269 — claude CLI 실행 파일 미발견([Errno 2] 'claude' / [Errno 8] Exec format error)을 일시 오류로 다룬다.

발단: 2026-11-07 06:34 weekend run 2380 — 37/37 즉시 실패(`[Errno 2] No such file or directory: 'claude'`, 바이너리 31시간 부재),
2026-10-24 4 성공 뒤 48 실패(실행 도중 소실), 2026-09-19 run 1979 `Exec format error`(#201). 자동 업데이트가 npm 전역 패키지를
교체하는 창으로 추정. 사양: (1) 시작 시 절대 경로 해석(KR_CLAUDE_BIN → which → 후보 폴더), (2) 파일 없음/실행 불가는 **프로세스
전역 게이트**로 BINARY_WAIT_DELAYS(30·60·120·300s) 만큼만 기다렸다 재시도 — 대기 단계는 **벽시계 라운드**(워커 4개가 같은 라운드에
합류)이지 발생 횟수가 아니다(리뷰 Critical 1), (3) 다 기다려도 없으면 ClaudeBinaryMissingError(UsageLimitError 하위 = 기존 배치
abort 채널)로 배치 전체 즉시 중단, 이후 호출은 기다리지 않고 즉시 실패(spawn 성공 시 래치 해제), (4) 전량 실패 메시지에 첫 오류
문자열을 실어 run.error 에서 원인이 바로 보이게."""
import errno
import json
import subprocess
import threading
import time

import pytest

from kr_pipeline.llm_runner.llm import claude_cli as cc
from kr_pipeline.llm_runner.run_status import AllAttemptsFailedError, check_all_failed


class FakeClock:
    """time.sleep 이 가짜 시계를 전진시킨다 — 라운드 게이트(wait_until)가 단일 스레드 테스트에서도 다음 단계로 넘어가게."""
    def __init__(self):
        self.t, self.sleeps = 1000.0, []

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


@pytest.fixture(autouse=True)
def _reset_gate(monkeypatch):
    cc._reset_binary_gate()
    monkeypatch.delenv("KR_CLAUDE_BIN", raising=False)
    yield
    cc._reset_binary_gate()


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(cc.time, "sleep", c.sleep)
    monkeypatch.setattr(cc.time, "monotonic", c.monotonic)
    return c


def _ok_envelope():
    body = json.dumps({"ok": True})
    env = {"type": "result", "result": body, "modelUsage": {"claude-sonnet-5-5": {"outputTokens": 1}}, "usage": {"output_tokens": 1}}
    return subprocess.CompletedProcess(args=["claude"], returncode=0, stdout=json.dumps(env), stderr="")


def test_resolve_prefers_env_then_which_then_candidates(monkeypatch, tmp_path, caplog):
    b = tmp_path / "claude"
    b.write_text("#!/bin/sh\n"); b.chmod(0o755)
    monkeypatch.setenv("KR_CLAUDE_BIN", str(b))
    assert cc.resolve_claude_bin() == str(b)
    monkeypatch.setenv("KR_CLAUDE_BIN", str(tmp_path / "typo"))               # 명시 경로가 없어도 그대로(업데이트 창엔 비기도 함) + 경고 1줄
    with caplog.at_level("WARNING", logger="kr_pipeline.llm_runner.claude_cli"):
        assert cc.resolve_claude_bin() == str(tmp_path / "typo")
    assert "KR_CLAUDE_BIN" in caplog.text
    monkeypatch.delenv("KR_CLAUDE_BIN")
    monkeypatch.setattr(cc.shutil, "which", lambda name: "/which/claude")
    assert cc.resolve_claude_bin() == "/which/claude"
    monkeypatch.setattr(cc.shutil, "which", lambda name: None)
    monkeypatch.setattr(cc, "_BIN_CANDIDATES", [str(tmp_path / "nope"), str(b)])
    assert cc.resolve_claude_bin() == str(b)                       # 후보 폴더 순서대로, 존재+실행 가능만
    monkeypatch.setattr(cc, "_BIN_CANDIDATES", [str(tmp_path / "nope")])
    assert cc.resolve_claude_bin() is None


def test_call_waits_for_missing_binary_then_succeeds(monkeypatch, clock):
    """실행 도중 사라진 경우(10-24 형): ENOENT 2회 → 30s·60s 대기 후 3번째 성공. RETRY_DELAYS(1·3·9) 와 별개."""
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", "claude")
        assert cmd[0] == "/opt/homebrew/bin/claude"                # 이름이 아니라 해석된 절대 경로로 호출
        return _ok_envelope()
    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    monkeypatch.setattr(cc, "resolve_claude_bin", lambda: "/opt/homebrew/bin/claude")
    assert cc.call_claude("analyze_chart_v3.md", payload_inline={"x": 1}) == {"ok": True}
    assert clock.sleeps == cc.BINARY_WAIT_DELAYS[:2] and calls["n"] == 3


def test_call_gives_up_after_schedule_and_fails_fast_afterwards(monkeypatch, clock):
    """장시간 부재(11-07 형): 처음부터 못 찾으면 30·60·120·300s 만 기다리고 ClaudeBinaryMissingError. 같은 프로세스의 다음
    호출(다른 종목)은 다시 기다리지 않는다 — 37종목 × 8.5분 낭비 방지. 예외는 UsageLimitError 하위라 parallel 워커가 abort."""
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        raise FileNotFoundError(errno.ENOENT, "No such file or directory", "claude")
    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    monkeypatch.setattr(cc, "resolve_claude_bin", lambda: None)
    with pytest.raises(cc.ClaudeBinaryMissingError) as ei:
        cc.call_claude("analyze_chart_v3.md", payload_inline={})
    assert clock.sleeps == cc.BINARY_WAIT_DELAYS and calls["n"] == 0 and "510" in str(ei.value)
    clock.sleeps.clear()
    with pytest.raises(cc.ClaudeBinaryMissingError):
        cc.call_claude("analyze_chart_v3.md", payload_inline={})
    assert clock.sleeps == [] and calls["n"] == 0
    assert issubclass(cc.ClaudeBinaryMissingError, cc.UsageLimitError)


def test_exec_format_error_is_treated_as_missing_binary(monkeypatch, clock):
    """교체 중인 바이너리(#201 run 1979 `Exec format error`, errno 8)도 같은 게이트."""
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(errno.ENOEXEC, "Exec format error", "claude")
        return _ok_envelope()
    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    monkeypatch.setattr(cc, "resolve_claude_bin", lambda: "/opt/homebrew/bin/claude")
    assert cc.call_claude("analyze_chart_v3.md", payload_inline={}) == {"ok": True}
    assert clock.sleeps == [cc.BINARY_WAIT_DELAYS[0]]


def test_other_oserror_propagates_unchanged(monkeypatch, clock):
    def fake_run(cmd, **kw):
        raise PermissionError(errno.EACCES, "Permission denied", "claude")
    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    monkeypatch.setattr(cc, "resolve_claude_bin", lambda: "/x/claude")
    with pytest.raises(PermissionError):
        cc.call_claude("analyze_chart_v3.md", payload_inline={})
    assert clock.sleeps == []


def test_success_resets_cursor_and_gave_up(monkeypatch, clock):
    """spawn 성공 = 바이너리 복귀 증거 → 커서 0·포기 래치 해제. 장수 프로세스(uvicorn issue_brief)에서 두 번째 사고도 다시 기다린다(리뷰 Minor 5)."""
    seq = iter([FileNotFoundError(errno.ENOENT, "x", "claude"), _ok_envelope(),
                FileNotFoundError(errno.ENOENT, "x", "claude"), _ok_envelope()])

    def fake_run(cmd, **kw):
        v = next(seq)
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(cc.subprocess, "run", fake_run)
    monkeypatch.setattr(cc, "resolve_claude_bin", lambda: "/x/claude")
    cc.call_claude("analyze_chart_v3.md", payload_inline={})
    cc.call_claude("analyze_chart_v3.md", payload_inline={})
    assert clock.sleeps == [cc.BINARY_WAIT_DELAYS[0], cc.BINARY_WAIT_DELAYS[0]]
    # 포기 래치 뒤 바이너리 복귀 → 성공 spawn 이 래치를 푼다
    monkeypatch.setattr(cc, "resolve_claude_bin", lambda: None)
    with pytest.raises(cc.ClaudeBinaryMissingError):
        cc.call_claude("analyze_chart_v3.md", payload_inline={})
    assert cc._bin_gate["gave_up"] is True
    monkeypatch.setattr(cc, "resolve_claude_bin", lambda: "/x/claude")
    monkeypatch.setattr(cc.subprocess, "run", lambda cmd, **kw: _ok_envelope())
    cc.call_claude("analyze_chart_v3.md", payload_inline={})
    assert cc._bin_gate["gave_up"] is False and cc._bin_gate["cursor"] == 0


def test_gate_rounds_are_wall_clock_not_per_occurrence(monkeypatch):
    """리뷰 Critical 1: 워커 4개가 동시에 ENOENT 를 만나도 라운드(30·60·120·300)는 벽시계로 한 번씩만 — 발생 횟수로 커서가
    전진하면 4워커는 30초 만에 포기한다. 실시간 축소(÷100) 로 실측: 첫 포기 시각 ≥ sum(DELAYS), 커서 전진 == len(DELAYS)."""
    delays = [0.03, 0.06, 0.12, 0.30]
    monkeypatch.setattr(cc, "BINARY_WAIT_DELAYS", delays)
    t0 = time.monotonic()
    give_up_at: list[float] = []
    lock = threading.Lock()

    def worker():
        while True:
            try:
                cc._binary_backoff("sim")
            except cc.ClaudeBinaryMissingError:
                with lock:
                    give_up_at.append(time.monotonic() - t0)
                return
    ths = [threading.Thread(target=worker) for _ in range(4)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(timeout=5)
    assert len(give_up_at) == 4
    assert min(give_up_at) >= sum(delays) - 0.01, give_up_at
    assert cc._bin_gate["cursor"] == len(delays)


def test_all_failed_message_carries_first_error():
    """전량 실패 run.error 에 첫 오류 문자열 — 지금은 details JSON 안에만 있어 /runner·watch 에서 원인이 안 보였다."""
    r = {"processed": 0, "failures": 37,
         "failed_tickers": [{"symbol": "003490", "error": "[Errno 2] No such file or directory: 'claude'", "attempts": 1}] * 37}
    with pytest.raises(AllAttemptsFailedError, match=r"37/37.*No such file or directory: 'claude'"):
        check_all_failed(r, mode="weekend")
    r2 = {"processed": 0, "failures": 2, "failed_tickers": [{"symbol": "A"}, {"symbol": "B"}]}   # error 키 없음 → 메시지 불변
    with pytest.raises(AllAttemptsFailedError, match=r"2/2 \(전량 실패\)$"):
        check_all_failed(r2, mode="weekend")
