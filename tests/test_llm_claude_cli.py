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
    assert "entry_price" in result
    assert "stop_loss" in result


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
    mock_run.side_effect = [
        subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="rate limit"),
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
