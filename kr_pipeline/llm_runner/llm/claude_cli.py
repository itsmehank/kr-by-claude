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
import re
import subprocess
import time
from pathlib import Path


log = logging.getLogger("kr_pipeline.llm_runner.claude_cli")


class ClaudeCLIError(RuntimeError):
    """Claude CLI 호출 최종 실패 (3회 재시도 후)."""


class UsageLimitError(RuntimeError):
    """Claude CLI 사용량 제한(5시간 윈도우) 감지 — 1~9초 재시도가 무의미.

    의도적으로 ClaudeCLIError 하위가 아님: weekend 워커의 transient 재시도
    (_TRANSIENT_EXC)에 걸리지 않고 배치 전체를 즉시 중단시켜야 한다.
    """


# CLI 가 제한 시 내는 메시지 패턴 (rc≠0 stderr 또는 rc=0 텍스트 stdout 양쪽).
# 예: "Claude AI usage limit reached|1760000000", "5-hour limit reached ∙ resets 3am"
_USAGE_LIMIT_RE = re.compile(
    r"usage limit reached|rate.?limit|5-hour limit|limit will reset",
    re.IGNORECASE,
)


def _is_usage_limit(text: str | None) -> bool:
    return bool(text and _USAGE_LIMIT_RE.search(text))


def _extract_json_objects(text: str) -> list[dict]:
    """텍스트에서 최상위 JSON object 들을 순서대로 추출.

    기존 '첫 { ~ 끝 }' 슬라이스는 산문 중괄호({각주} 등)나 복수 JSON 블록이
    섞이면 비-JSON 을 포함해 파싱이 깨지고, 실패가 전체 LLM 재호출(비용 증폭)
    로 이어졌다. raw_decode 스캔은 각 '{' 에서 유효한 JSON 만 골라낸다.
    소비자는 마지막 object(최종 답) 를 쓴다.
    """
    dec = json.JSONDecoder()
    out: list[dict] = []
    i = 0
    while True:
        j = text.find("{", i)
        if j == -1:
            break
        try:
            obj, end = dec.raw_decode(text, j)
        except json.JSONDecodeError:
            i = j + 1
            continue
        if isinstance(obj, dict):
            out.append(obj)
        i = end
    return out


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
    payload_inline: dict | str | None = None,
    dry_run: bool = False,
    timeout_seconds: int = 600,
) -> dict:
    """Claude CLI 호출.

    Args:
        prompt_file: prompts/ 하위 파일명 (예: "analyze_chart_v3.md")
        attachments: 첨부 파일 절대경로 리스트 (ZIP, PNG 등)
        payload_inline: 프롬프트 본문에 직접 붙일 입력.
            dict → ```json 블록으로 직렬화(가벼운 payload 용).
            str  → 원문 그대로 append(인라인 데이터 섹션 용; analyze_chart_v3 인라인 경로).
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
        if isinstance(payload_inline, str):
            prompt_text += "\n\n" + payload_inline + "\n"
        else:
            prompt_text += "\n\n## Input (JSON)\n\n```json\n"
            prompt_text += json.dumps(payload_inline, ensure_ascii=False, indent=2)
            prompt_text += "\n```\n"

    # --tools Read: default-deny tool surface. Classification reads only the
    # attached chart PNGs (@absolute_path → Read); web/news/external lookups must
    # NOT be reachable (point-in-time integrity + determinism). Web*/Bash/etc. are
    # not even exposed. bypassPermissions keeps the non-interactive --print flow
    # from prompting on the allowed Read.
    cmd = ["claude", "--print", "--permission-mode", "bypassPermissions", "--tools", "Read"]

    # 모델 핀: 기본 'sonnet'(별칭 — 그 시점의 최신 Sonnet). 사용자 /model·
    # settings.json 변경이 production 분류 모델을 조용히 바꾸지 않도록 항상 핀.
    # 예외적으로 다른 모델이 필요하면 KR_CLAUDE_MODEL 로 오버라이드.
    cmd.extend(["--model", os.environ.get("KR_CLAUDE_MODEL", "sonnet")])

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
                # Claude CLI 출력은 일반 텍스트 + JSON 블록 혼합 가능.
                # raw_decode 스캔으로 유효 JSON object 만 추출, 마지막(최종 답) 채택.
                objs = _extract_json_objects(result.stdout)
                if not objs:
                    raise ValueError("No JSON in output")
                return objs[-1]
            except (json.JSONDecodeError, ValueError) as e:
                # rc=0 이어도 stdout 이 사용량 제한 안내 텍스트일 수 있음 — 재시도 무의미.
                if _is_usage_limit(result.stdout):
                    raise UsageLimitError(f"usage limit: {result.stdout.strip()[:200]}") from e
                log.warning("JSON parse failed: %s. stdout=%r", e, result.stdout[:200])
                last_error = e
                continue
        else:
            # 사용량 제한(5시간)은 backoff 재시도가 무의미 — 즉시 전파해 배치 중단.
            if _is_usage_limit(result.stdout) or _is_usage_limit(result.stderr):
                raise UsageLimitError(
                    f"usage limit: rc={result.returncode} "
                    f"{(result.stdout or result.stderr).strip()[:200]}"
                )
            log.warning(
                "claude CLI failed (rc=%d): %s",
                result.returncode,
                result.stderr[:200],
            )
            last_error = RuntimeError(f"rc={result.returncode}: {result.stderr}")

    raise ClaudeCLIError(
        f"claude CLI failed after {len(RETRY_DELAYS) + 1} attempts: {last_error}"
    )
