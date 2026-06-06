"""Claude Code CLI subprocess wrapper + dry-run mock.

호출 모드:
  - 실제: claude CLI subprocess + JSON 파싱 + 3회 재시도 (1초/3초/9초 backoff)
  - dry-run: prompt_file 기반 mock JSON 반환 (LLM 호출 없음)
"""
from __future__ import annotations

import json
import logging
import os
import random
import subprocess
import time
from pathlib import Path


log = logging.getLogger("kr_pipeline.llm_runner.claude_cli")


class ClaudeCLIError(RuntimeError):
    """Claude CLI 호출 최종 실패 (3회 재시도 후)."""


# ── Mock generators for dry-run ─────────────────────────────────────────────

def _mock_analyze_chart_v3() -> dict:
    classification = random.choice(["entry", "watch", "ignore"])
    if classification == "ignore":
        return {
            "classification": "ignore",
            "pattern": "none",
            "confidence": round(random.uniform(0.6, 0.9), 2),
            "reasoning": "dry-run mock ignore",
            "risk_flags": [],
            "pivot_price": None,
            "pivot_basis": None,
            "base_high": None,
            "base_low": None,
            "base_depth_pct": None,
            "base_start_date": None,
        }
    pattern = random.choice(["flat_base", "cup_with_handle", "vcp", "double_bottom"])
    base_low = round(random.uniform(50, 80), 2)
    base_high = round(base_low * random.uniform(1.05, 1.15), 2)
    return {
        "classification": classification,
        "pattern": pattern,
        "confidence": round(random.uniform(0.6, 0.95), 2),
        "reasoning": "dry-run mock " + classification,
        "risk_flags": [],
        "pivot_price": round(base_high * 1.001, 2),
        "pivot_basis": {
            "flat_base": "range_high",
            "cup_with_handle": "handle_high",
            "vcp": "final_T_high",
            "double_bottom": "mid_W_peak",
        }[pattern],
        "base_high": base_high,
        "base_low": base_low,
        "base_depth_pct": round((base_high - base_low) / base_high * 100, 2),
        "base_start_date": "2026-03-01",
    }


def _mock_evaluate_pivot_trigger() -> dict:
    decision = random.choice(["go_now", "wait", "abort"])
    return {
        "decision": decision,
        "confidence": round(random.uniform(0.5, 0.9), 2),
        "reasoning": f"dry-run mock {decision}",
        "abort_reason": (
            random.choice(
                [
                    "sma50_breach_distribution_volume",
                    "volume_insufficient_intraday_weak",
                    "stop_loss_breach",
                ]
            )
            if decision == "abort"
            else None
        ),
    }


def _mock_calculate_entry_params() -> dict:
    pivot = round(random.uniform(50000, 100000), 0)
    trigger = round(pivot * 1.001, 2)
    stop = round(pivot * random.uniform(0.93, 0.95), 2)
    return {
        "entry_mode": random.choice(["pivot_breakout", "pocket_pivot"]),
        "pivot_price": pivot,
        "trigger_price": trigger,
        "current_price": round(pivot * random.uniform(0.99, 1.005), 2),
        "stop_loss_price": stop,
        "stop_loss_pct_from_pivot": round((stop - pivot) / pivot * 100, 2),
        "stop_loss_pct_from_current_price": round((stop - trigger) / trigger * 100, 2),
        "suggested_weight_pct": round(random.uniform(2, 10), 1),
        "expected_target_price": round(trigger * 1.20, 2),
        "expected_target_pct": 20.0,
        "pattern_basis": random.choice(["flat_base", "cup_with_handle"]),
        "entry_window_days": random.choice([2, 3, 5]),
        "max_chase_pct_from_pivot": 5.0,
        "breakout_volume_requirement": "ge_1.4x_50day_avg",
        "observed_breakout_volume_ratio": None,
        "known_warnings": [],
        "other_warnings": "",
        "notes": "dry-run mock entry params (§9 schema)",
    }


_MOCK_GENERATORS = {
    "analyze_chart_v3.md": _mock_analyze_chart_v3,
    "evaluate_pivot_trigger_v1.md": _mock_evaluate_pivot_trigger,
    "calculate_entry_params_v2_0.md": _mock_calculate_entry_params,
}


# ── Real subprocess call ────────────────────────────────────────────────────

PROMPTS_DIR = Path(__file__).parent.parent.parent.parent / "prompts"

RETRY_DELAYS = [1, 3, 9]


def call_claude(
    prompt_file: str,
    attachments: list[str] | None = None,
    payload_inline: dict | None = None,
    dry_run: bool = False,
    timeout_seconds: int = 600,
) -> dict:
    """Claude CLI 호출.

    Args:
        prompt_file: prompts/ 하위 파일명 (예: "analyze_chart_v3.md")
        attachments: 첨부 파일 절대경로 리스트 (ZIP, PNG 등)
        payload_inline: 텍스트로 직접 전달할 JSON (가벼운 payload 용)
        dry_run: True 면 LLM 호출 안 함, mock JSON 반환
        timeout_seconds: subprocess timeout

    Returns:
        parsed JSON dict

    Raises:
        ClaudeCLIError: 3회 재시도 후 실패 시
    """
    if dry_run:
        gen = _MOCK_GENERATORS.get(prompt_file)
        if gen is None:
            raise ValueError(f"No mock for prompt: {prompt_file}")
        return gen()

    prompt_path = PROMPTS_DIR / prompt_file
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")

    # Build prompt input
    prompt_text = prompt_path.read_text(encoding="utf-8")
    if payload_inline is not None:
        prompt_text += "\n\n## Input (JSON)\n\n```json\n"
        prompt_text += json.dumps(payload_inline, ensure_ascii=False, indent=2)
        prompt_text += "\n```\n"

    cmd = ["claude", "--print", "--permission-mode", "bypassPermissions"]

    # 첨부 파일들의 디렉토리를 --add-dir 로 등록 (claude CLI 최신 API)
    attach_dirs: set[str] = set()
    for att in attachments or []:
        attach_dirs.add(os.path.dirname(os.path.abspath(att)))
    for d in attach_dirs:
        cmd.extend(["--add-dir", d])

    # prompt 안에 파일 reference 를 @absolute_path 형식으로 추가
    if attachments:
        prompt_text += "\n\n## 첨부 파일\n\n다음 파일들을 참고하세요:\n"
        for att in attachments:
            prompt_text += f"- @{os.path.abspath(att)}\n"

    last_error = None
    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay > 0:
            log.warning("claude CLI retry attempt %d after %ds", attempt, delay)
            time.sleep(delay)

        result = subprocess.run(
            cmd,
            input=prompt_text,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                # Claude CLI 출력은 일반 텍스트 + JSON 블록. JSON 추출.
                stdout = result.stdout.strip()
                first_brace = stdout.find("{")
                last_brace = stdout.rfind("}")
                if first_brace == -1 or last_brace == -1:
                    raise ValueError("No JSON in output")
                json_str = stdout[first_brace : last_brace + 1]
                return json.loads(json_str)
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("JSON parse failed: %s. stdout=%r", e, result.stdout[:200])
                last_error = e
                continue
        else:
            log.warning(
                "claude CLI failed (rc=%d): %s",
                result.returncode,
                result.stderr[:200],
            )
            last_error = RuntimeError(f"rc={result.returncode}: {result.stderr}")

    raise ClaudeCLIError(
        f"claude CLI failed after {len(RETRY_DELAYS) + 1} attempts: {last_error}"
    )
