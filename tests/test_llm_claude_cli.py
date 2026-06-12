"""Claude CLI subprocess wrapper + dry-run."""
import subprocess
import pytest


def test_call_claude_dry_run_returns_mock_5():
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    result = call_claude(
        prompt_file="analyze_chart_v3.md",
        attachments=["/tmp/fake.zip"],
        dry_run=True,
    )
    assert "classification" in result
    assert result["classification"] in {"entry", "watch", "ignore"}
    assert "pattern" in result


def test_call_claude_dry_run_returns_mock_5b():
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    result = call_claude(
        prompt_file="evaluate_pivot_trigger_v1.md",
        attachments=[],
        payload_inline={"symbol": "TEST"},
        dry_run=True,
    )
    assert "decision" in result
    assert result["decision"] in {"go_now", "wait", "abort"}


def test_call_claude_dry_run_returns_mock_6():
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    result = call_claude(
        prompt_file="calculate_entry_params_v2_0.md",
        attachments=[],
        payload_inline={"symbol": "TEST"},
        dry_run=True,
    )
    assert "entry_mode" in result
    assert "stop_loss_price" in result
    assert "suggested_weight_pct" in result
    assert "pivot_price" in result


def test_call_claude_parses_json_output(mocker):
    """실제 호출 시 stdout JSON 파싱."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='{"classification": "entry", "pattern": "cup_with_handle"}',
        stderr="",
    )
    result = call_claude(
        prompt_file="analyze_chart_v3.md",
        attachments=["/tmp/fake.zip"],
    )
    assert result["classification"] == "entry"
    assert result["pattern"] == "cup_with_handle"


def test_call_claude_retries_on_failure(mocker):
    """일시적 실패 시 재시도 (1초 → 3초 → 9초)."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    # NOTE: "rate limit" 류 문구는 이제 UsageLimitError(즉시 중단) 경로 —
    # 일시 오류 재시도 검증에는 중립적인 에러 문구를 쓴다.
    mock_run.side_effect = [
        subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="connection reset"),
        subprocess.CompletedProcess(args=[], returncode=0, stdout='{"ok": true}', stderr=""),
    ]
    result = call_claude(
        prompt_file="analyze_chart_v3.md",
        attachments=["/tmp/fake.zip"],
    )
    assert mock_run.call_count == 2
    assert result == {"ok": True}


def test_call_claude_raises_after_3_retries(mocker):
    """3회 실패 후 예외."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude, ClaudeCLIError

    mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="error"
    )

    with pytest.raises(ClaudeCLIError):
        call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/fake.zip"])
    # 1차 시도 (즉시) + 3회 재시도 = 4 호출. plan loop: for attempt, delay in enumerate([0] + RETRY_DELAYS) → 4 iterations.
    assert mock_run.call_count == 4


def test_call_claude_uses_add_dir_not_attach(mocker, tmp_path):
    """attachments 가 있으면 --attach 대신 --add-dir + @path reference 를 사용해야 함."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    # 첨부 파일 준비
    att_file = tmp_path / "data.zip"
    att_file.write_bytes(b"PK\x03\x04test")

    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='{"classification": "watch", "pattern": "flat_base"}',
        stderr="",
    )

    call_claude(
        prompt_file="analyze_chart_v3.md",
        attachments=[str(att_file)],
        dry_run=False,
    )

    call_args = mock_run.call_args[0][0]

    # --attach 는 없어야 함
    assert "--attach" not in call_args

    # --add-dir 가 있어야 함
    assert "--add-dir" in call_args
    add_dir_idx = call_args.index("--add-dir")
    assert str(att_file.parent) == call_args[add_dir_idx + 1]

    # --permission-mode bypassPermissions 가 있어야 함
    assert "--permission-mode" in call_args
    perm_idx = call_args.index("--permission-mode")
    assert call_args[perm_idx + 1] == "bypassPermissions"

    # stdin 으로 전달된 prompt 에 @absolute_path 가 포함되어야 함
    input_text = mock_run.call_args[1]["input"]
    assert f"@{att_file}" in input_text


def test_call_claude_no_longer_uses_attach_in_source():
    """source code 에 --attach 가 더 이상 없어야 함 (regression guard)."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "kr_pipeline" / "llm_runner" / "llm" / "claude_cli.py"
    content = src.read_text()
    assert "--attach" not in content, "claude_cli.py 에서 --attach 옵션이 제거되어야 함"
    assert "--add-dir" in content, "claude_cli.py 가 --add-dir 를 사용해야 함"


def test_call_claude_usage_limit_no_retry(mocker):
    """사용량 제한(5시간)은 1~9초 재시도가 무의미 — 즉시 UsageLimitError, 재시도 0회."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError

    sleep = mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="Claude AI usage limit reached|1760000000", stderr=""
    )
    with pytest.raises(UsageLimitError):
        call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/fake.zip"])
    assert mock_run.call_count == 1
    sleep.assert_not_called()


def test_call_claude_usage_limit_rc0_text_output(mocker):
    """rc=0 인데 stdout 이 제한 안내 텍스트인 경우(JSON 없음)도 즉시 UsageLimitError."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError

    mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="5-hour limit reached ∙ resets 3am", stderr=""
    )
    with pytest.raises(UsageLimitError):
        call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/fake.zip"])
    assert mock_run.call_count == 1


def test_usage_limit_is_not_claude_cli_error():
    """UsageLimitError 는 ClaudeCLIError 의 하위가 아니어야 함 —
    weekend 워커의 transient 재시도(_TRANSIENT_EXC)에 걸리면 안 된다."""
    from kr_pipeline.llm_runner.llm.claude_cli import ClaudeCLIError, UsageLimitError
    assert not issubclass(UsageLimitError, ClaudeCLIError)
