"""Claude CLI subprocess wrapper + dry-run."""
import json
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


@pytest.mark.parametrize("stdout", [
    "Claude AI usage limit reached|1760000000",
    "5-hour limit reached ∙ resets 3am",
    "Your rate limit has been exceeded",
    "The limit will reset at 9pm",
    # (#98) 2026-08-09 표본 C 백필에서 실제로 나온 문구 — 기존 패턴에 안 걸려
    # 셀당 4회 재시도로 약 1,175건의 0-토큰 헛호출이 발생했다.
    "You've hit your org's monthly spend limit · run /usage-credits to ask "
    "your admin for a higher limit",
])
def test_call_claude_usage_limit_no_retry(mocker, stdout):
    """사용량 제한은 1~9초 재시도가 무의미 — 즉시 UsageLimitError, 재시도 0회."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError

    sleep = mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout=stdout, stderr=""
    )
    with pytest.raises(UsageLimitError):
        call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/fake.zip"])
    assert mock_run.call_count == 1
    sleep.assert_not_called()


def test_call_claude_usage_limit_inside_error_envelope_no_retry(mocker):
    """(#98) 한도 문구가 --output-format json 봉투 안(rc≠0)에 실려도 재시도 0회.

    실제 실패 형태 — stderr 는 비고 stdout 에 is_error 봉투만 온다.
    """
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError

    envelope = json.dumps({
        "type": "result",
        "subtype": "error_during_execution",
        "is_error": True,
        "result": "You've hit your org's monthly spend limit · run /usage-credits "
                  "to ask your admin for a higher limit",
    })
    sleep = mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout=envelope, stderr=""
    )
    with pytest.raises(UsageLimitError):
        call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/fake.zip"])
    assert mock_run.call_count == 1
    sleep.assert_not_called()


def test_is_usage_limit_no_false_positive_on_classification():
    """(#98) 정상 분류 응답을 한도로 오인하면 12개 모듈의 배치가 통째로 중단된다.

    _is_usage_limit 는 봉투 result(모델 응답 본문)에도 적용되므로 오탐이 치명적이다.
    """
    from kr_pipeline.llm_runner.llm.claude_cli import _is_usage_limit

    result = json.dumps({
        "classification": "watch",
        "pattern": "cup_with_handle",
        "pivot_price": 51200.0,
        "confidence": 0.62,
        "reasoning": "52주 신고가 대비 -8% 구간에서 손잡이 형성 중. 거래량 감소를 "
                     "동반한 조정으로 베이스 품질은 양호하나, 시장 방향이 조정 "
                     "국면이라 신규 진입은 보류. 리스크 한도(risk limit) 내에서 "
                     "관찰 지속.",
    }, ensure_ascii=False)
    assert _is_usage_limit(result) is False


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


def test_call_claude_parses_json_among_prose_braces(mocker):
    """산문에 중괄호가 섞여도(예: 'config {x}' 후 JSON) 파싱 — 첫{~끝} 슬라이스는
    이런 출력에서 비-JSON 을 포함해 깨지고, 실패 시 전체 재호출(비용 증폭)된다."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout='분석 노트 {여기는 산문} 입니다.\n{"classification": "watch", "pattern": "vcp"}\n끝 {각주}',
        stderr="",
    )
    result = call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/f.zip"])
    assert result == {"classification": "watch", "pattern": "vcp"}
    assert mock_run.call_count == 1, "파싱 실패로 재호출되면 안 된다"


def test_call_claude_picks_last_json_object(mocker):
    """JSON 블록이 여럿이면 마지막(최종 답) 채택 — 모델이 중간 사고로 JSON 예시를
    먼저 출력하는 경우 대비."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout='{"draft": true}\n최종:\n{"classification": "entry"}',
        stderr="",
    )
    result = call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/f.zip"])
    assert result == {"classification": "entry"}


def test_call_claude_pins_model_from_env(mocker, monkeypatch):
    """KR_CLAUDE_MODEL 설정 시 --model 로 오버라이드, 미설정 시 기본 'sonnet' 핀 —
    사용자 /model·settings.json 변경에 production 분류 모델이 따라 흔들리지 않도록.
    'sonnet' 은 별칭이라 그 시점의 최신 Sonnet 으로 해석된다."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    monkeypatch.setenv("KR_CLAUDE_MODEL", "claude-opus-4-8")
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout='{"ok": true}', stderr="",
    )
    call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/f.zip"])
    cmd = mock_run.call_args[0][0]
    assert "--model" in cmd and "claude-opus-4-8" in cmd

    monkeypatch.delenv("KR_CLAUDE_MODEL")
    call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/f.zip"])
    cmd2 = mock_run.call_args[0][0]
    assert "--model" in cmd2, "미설정 시에도 프로젝트 기본 모델 핀"
    assert cmd2[cmd2.index("--model") + 1] == "sonnet", "기본 핀 = 최신 Sonnet 별칭"


def _envelope(result_text: str, model: str = "claude-sonnet-5",
              in_tok: int = 1247, out_tok: int = 67) -> str:
    """claude --print --output-format json 봉투 (실측 형태 축약)."""
    import json
    return json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "result": result_text,
        # 실측: input_tokens 는 비캐시 프리픽스만, 페이로드는 cache_* 에 잡힘.
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok,
                  "cache_creation_input_tokens": 9395,
                  "cache_read_input_tokens": 3219},
        "modelUsage": {model: {"inputTokens": in_tok, "outputTokens": out_tok}},
    })


def test_call_claude_parses_json_envelope_and_fills_meta_out(mocker):
    """--output-format json 봉투에서 답 JSON 추출 + meta_out 에 실모델·토큰 기록."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=_envelope('분석 결과:\n{"classification": "watch"}'),
        stderr="",
    )
    meta: dict = {}
    result = call_claude(prompt_file="analyze_chart_v3.md",
                         attachments=["/tmp/f.zip"], meta_out=meta)
    assert result == {"classification": "watch"}
    assert meta["model"] == "claude-sonnet-5"
    assert meta["input_tokens"] == 1247 + 9395 + 3219, "입력 = 비캐시 + 캐시생성 + 캐시읽기 합"
    assert meta["output_tokens"] == 67
    cmd = mock_run.call_args[0][0]
    assert "--output-format" in cmd and "json" in cmd


def test_call_claude_plain_stdout_fallback(mocker):
    """봉투가 아닌 플레인 JSON stdout (구버전/예외 경로) 도 기존대로 파싱."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout='{"classification": "watch"}', stderr="",
    )
    meta: dict = {}
    result = call_claude(prompt_file="analyze_chart_v3.md",
                         attachments=["/tmp/f.zip"], meta_out=meta)
    assert result == {"classification": "watch"}
    assert meta.get("model") is None, "봉투 없으면 모델 미상"


def test_call_claude_usage_limit_inside_envelope(mocker):
    """봉투 result 가 사용량 한도 안내 텍스트면 UsageLimitError (재시도 무의미)."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError

    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=_envelope("Claude AI usage limit reached|1760000000"),
        stderr="",
    )
    with pytest.raises(UsageLimitError):
        call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/f.zip"])


# --- (#99) 정적 프롬프트의 system prompt 승격 (캐시 프리픽스) ---

def _completed(stdout='{"ok": true}'):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def test_call_claude_promotes_static_prompt_to_system_prompt(mocker):
    """(#99) 정적 프롬프트 전문이 --append-system-prompt 인자로 승격되고,
    stdin(user 메시지)에는 포함되지 않는다 — 매 호출 동일한 프리픽스가
    프롬프트 캐시로 재사용되게 하는 구조."""
    from pathlib import Path
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude, PROMPTS_DIR

    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = _completed()
    call_claude(
        prompt_file="analyze_chart_v3.md",
        attachments=[],
        payload_inline="## 입력 데이터 (인라인)\n\nDATA",
    )
    cmd = mock_run.call_args[0][0]
    prompt_text = (Path(PROMPTS_DIR) / "analyze_chart_v3.md").read_text(encoding="utf-8")

    assert "--append-system-prompt" in cmd
    assert cmd[cmd.index("--append-system-prompt") + 1] == prompt_text
    # 동적 섹션(cwd/git status)이 system prompt 앞에서 프리픽스를 깨지 않게 하는 플래그
    assert "--exclude-dynamic-system-prompt-sections" in cmd

    stdin_text = mock_run.call_args[1]["input"]
    assert "## 입력 데이터 (인라인)" in stdin_text
    # 정적 프롬프트 본문은 stdin 에 없어야 함 (첫 줄로 대표 확인)
    first_prompt_line = prompt_text.splitlines()[0]
    assert first_prompt_line not in stdin_text


def test_call_claude_dict_payload_goes_to_stdin_as_json_block(mocker):
    """dict payload(evaluate_pivot 경로)는 기존과 동일하게 ```json 블록 — 위치만
    프롬프트 뒤 append 에서 user 메시지로 이동."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = _completed()
    call_claude(
        prompt_file="evaluate_pivot_trigger_v1.md",
        attachments=[],
        payload_inline={"symbol": "TEST"},
    )
    stdin_text = mock_run.call_args[1]["input"]
    assert "## Input (JSON)" in stdin_text
    assert '"symbol": "TEST"' in stdin_text


def test_call_claude_attachments_only_user_message(mocker, tmp_path):
    """payload_inline 없이 attachments 만 있는 상시 경로(scripts/remeasure_phase2i·
    replay_breakout_from_watch): user 메시지는 첨부 섹션만으로 구성된다."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    att = tmp_path / "data.zip"
    att.write_bytes(b"PK\x03\x04x")
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = _completed()
    call_claude(prompt_file="analyze_chart_v3.md", attachments=[str(att)])
    stdin_text = mock_run.call_args[1]["input"]
    assert f"@{att}" in stdin_text
    assert "## 첨부 파일" in stdin_text
    assert "Inputs" not in stdin_text  # 정적 프롬프트 미포함


def test_call_claude_empty_inputs_fallback_stdin(mocker):
    """payload 도 첨부도 없으면 고정 폴백 1줄 — 빈 stdin 방지(방어 경로)."""
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude

    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = _completed()
    call_claude(prompt_file="analyze_chart_v3.md", attachments=[])
    assert mock_run.call_args[1]["input"] == "시스템 프롬프트의 지침에 따라 진행하세요.\n"


# ── #100: rc≠0 실패 사유 합성 ────────────────────────────────────────────────


def test_call_claude_failure_reason_from_stdout_envelope(mocker):
    """rc=1 + 빈 stderr + stdout 에러 봉투 → 예외 메시지에 봉투 사유 포함 (#100)."""
    from kr_pipeline.llm_runner.llm.claude_cli import ClaudeCLIError, call_claude

    mocker.patch("time.sleep")
    envelope = json.dumps({
        "type": "result", "subtype": "error_during_execution", "is_error": True,
        "result": "API Error: 529 overloaded", "api_error_status": 529,
        "stop_reason": None,
    })
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout=envelope, stderr=""
    )

    with pytest.raises(ClaudeCLIError) as ei:
        call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/fake.zip"])
    msg = str(ei.value)
    assert "API Error: 529 overloaded" in msg
    assert "error_during_execution" in msg
    assert not msg.rstrip().endswith("rc=1:")


def test_call_claude_failure_reason_fallback_raw_stdout(mocker):
    """rc=1 + 빈 stderr + 비-JSON stdout → raw stdout 으로 폴백 (#100)."""
    from kr_pipeline.llm_runner.llm.claude_cli import ClaudeCLIError, call_claude

    mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="plain text CLI crash message", stderr=""
    )

    with pytest.raises(ClaudeCLIError) as ei:
        call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/fake.zip"])
    assert "plain text CLI crash message" in str(ei.value)


def test_call_claude_failure_diag_capped_500(mocker):
    """합성 진단 문자열은 500자 상한 — 백필 로그 무절단 append 폭주 방지 (#100)."""
    from kr_pipeline.llm_runner.llm.claude_cli import ClaudeCLIError, call_claude

    mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="x" * 5000
    )

    with pytest.raises(ClaudeCLIError) as ei:
        call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/fake.zip"])
    # 고정 접두("claude CLI failed after N attempts: rc=1: ") 여유 100자
    assert len(str(ei.value)) <= 600


def test_call_claude_non_quota_limit_no_false_alarm(mocker, caplog):
    """컨텍스트 초과류 'limit' 문구는 미분류 한도 경보를 울리지 않는다 (#100 함정 ③)."""
    import logging

    from kr_pipeline.llm_runner.llm.claude_cli import ClaudeCLIError, call_claude

    mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    non_quota = [
        "prompt is too long: 250000 tokens > 200000 maximum context limit",
        "max_tokens limit exceeded",  # 언더스코어 표기 (리뷰 관찰 반영)
    ]
    for stderr in non_quota:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=stderr,
        )
        with caplog.at_level(logging.ERROR):
            with pytest.raises(ClaudeCLIError):
                call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/fake.zip"])
    assert not any("미분류" in r.getMessage() for r in caplog.records)


def test_call_claude_unclassified_limit_phrase_alerts(mocker, caplog):
    """비-컨텍스트 'limit' 문구가 한도 패턴에 안 걸리면 조기경보를 남긴다 (#100)."""
    import logging

    from kr_pipeline.llm_runner.llm.claude_cli import ClaudeCLIError, call_claude

    mocker.patch("time.sleep")
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="weekly limit exceeded for your plan"
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ClaudeCLIError):
            call_claude(prompt_file="analyze_chart_v3.md", attachments=["/tmp/fake.zip"])
    assert any(
        "미분류" in r.getMessage() and "_USAGE_LIMIT_RE" in r.getMessage()
        for r in caplog.records
    )
