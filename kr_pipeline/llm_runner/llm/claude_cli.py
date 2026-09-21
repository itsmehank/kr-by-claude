"""Claude Code CLI subprocess wrapper + dry-run mock.

호출 모드:
  - 실제: claude CLI subprocess + JSON 파싱 + 3회 재시도 (1초/3초/9초 backoff)
  - dry-run: prompt_file 기반 mock JSON 반환 (LLM 호출 없음)
"""
from __future__ import annotations

import hashlib
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
#     "You've hit your org's monthly spend limit · run /usage-credits to ..."  (#98)
#
# 패턴을 좁게 유지할 것 — _is_usage_limit() 는 아래 rc=0 경로에서 **모델 응답 본문**
# (envelope.result)에도 적용된다. 넓은 패턴(예: 단독 "spend limit")은 정상 분류
# 응답의 reasoning 을 한도로 오인해 UsageLimitError 를 던지고, 이를 처리하는 12개
# 모듈의 배치를 통째로 중단시킨다.
_USAGE_LIMIT_RE = re.compile(
    r"usage limit reached|rate.?limit|5-hour limit|limit will reset"
    r"|hit your .{0,40}?spend limit|/usage-credits",
    re.IGNORECASE,
)


def _is_usage_limit(text: str | None) -> bool:
    return bool(text and _USAGE_LIMIT_RE.search(text))


# (#100) 조기경보 제외용 — 쿼터와 무관한 'limit' 문구(컨텍스트 초과 등).
# 이 프로젝트는 호출당 ~125k 토큰을 보내므로 컨텍스트 초과가 실제로 난다.
# 이걸 한도 패턴(_USAGE_LIMIT_RE)에 넣으면 컨텍스트 초과 1건이 배치 전체를
# 중단시키므로, 경보에서 제외해 그 오판 유도를 차단한다.
_NON_QUOTA_LIMIT_RE = re.compile(r"context limit|too long|max(imum)?[ _]tokens", re.I)


def _failure_diagnostic(stdout: str, stderr: str) -> str:
    """rc≠0 실패의 진단 문자열 합성 (#100).

    --output-format json 에서 실패 사유는 stdout 봉투(result/api_error_status/
    subtype/stop_reason)에 실리고 stderr 는 비는 경우가 있다. 봉투가 파싱되면
    사유 필드만 추려 합성하고, 없으면 stderr → stdout 순으로 폴백한다.
    """
    for env in reversed(_extract_json_objects(stdout or "")):
        parts = []
        for key in ("result", "api_error_status", "subtype", "stop_reason"):
            v = env.get(key)
            if v in (None, "") or (key == "subtype" and v == "success"):
                continue
            parts.append(f"{key}={v}")
        if parts:
            return " ".join(parts)
    return (stderr or "").strip() or (stdout or "").strip()


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
    # #21 이후 production 은퇴 경로 — entry_params.py 가 call_claude 를 호출하지 않아
    # dry-run 에서 도달 불능. 레거시 테스트·parity 개조용으로만 잔존(§9 와 미묘하게
    # 다른 random mock 이므로 '구 LLM 출력'의 대역으로 쓰지 말 것).
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


def prompt_version_of(prompt_text: str) -> str:
    """프롬프트 버전 식별자 = 파일 전문 sha256 앞 12자 (SSOT — DB 컬럼·JSON 감사 산출물 공용, #181 B6·#198).

    동일성만 보장하고 순서는 없다(#197). 형식 변경 시 이 함수 하나만 바꾼다.
    """
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:12]


def call_claude(
    prompt_file: str,
    attachments: list[str] | None = None,
    payload_inline: dict | str | None = None,
    dry_run: bool = False,
    timeout_seconds: int = 600,
    meta_out: dict | None = None,
) -> dict:
    """Claude CLI 호출.

    Args:
        prompt_file: prompts/ 하위 파일명 (예: "analyze_chart_v3.md")
        attachments: 첨부 파일 절대경로 리스트 (ZIP, PNG 등)
        payload_inline: user 메시지(stdin)에 담을 호출별 입력. (#99) 정적
            프롬프트는 --append-system-prompt 로 분리되므로 user 메시지는 이것
            (+첨부 @참조)만으로 구성된다.
            dict → ```json 블록으로 직렬화(가벼운 payload 용).
            str  → 원문 그대로(인라인 데이터 섹션 용; analyze_chart_v3 인라인 경로).
        dry_run: True 면 LLM 호출 안 함, mock JSON 반환
        timeout_seconds: subprocess timeout
        meta_out: dict 를 주면 호출 메타를 채움 — model(별칭이 아닌 실제 해석된
            모델 ID, 예: claude-sonnet-5), input_tokens, output_tokens.
            봉투 파싱 실패(플레인 stdout 폴백) 시 미채움.

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

    # (#99) 정적 프롬프트(prompt_file 전문)는 user 메시지에 붙이지 않고
    # --append-system-prompt 로 승격 — 모든 호출에서 동일한 수십 KB 가 안정적인
    # 프롬프트 캐시 프리픽스가 된다. user 메시지(stdin)에는 호출별로 달라지는
    # 데이터(payload_inline·첨부 참조)만 남긴다.
    prompt_text = prompt_path.read_text(encoding="utf-8")
    if meta_out is not None:
        # (#181 B6) 프롬프트 버전 = 파일 전문 sha256 앞 12자 — 저장 행에 붙여 버전 혼재를 추적 가능하게.
        meta_out["prompt_version"] = prompt_version_of(prompt_text)
    user_parts: list[str] = []
    if payload_inline is not None:
        if isinstance(payload_inline, str):
            user_parts.append(payload_inline)
        else:
            user_parts.append(
                "## Input (JSON)\n\n```json\n"
                + json.dumps(payload_inline, ensure_ascii=False, indent=2)
                + "\n```"
            )

    # --tools Read: default-deny tool surface. Classification reads only the
    # attached chart PNGs (@absolute_path → Read); web/news/external lookups must
    # NOT be reachable (point-in-time integrity + determinism). Web*/Bash/etc. are
    # not even exposed. bypassPermissions keeps the non-interactive --print flow
    # from prompting on the allowed Read.
    # --output-format json: 봉투(modelUsage/usage)로 실제 사용 모델·토큰을 기록
    # 가능하게 한다 — 별칭 'sonnet' 핀이 어느 버전으로 해석됐는지 사후 추적용.
    # --exclude-dynamic-system-prompt-sections: cwd/git status 등 호출마다 변할 수
    # 있는 섹션을 system prompt 앞부분에서 첫 user 메시지로 밀어낸다 — 이게 없으면
    # append 한 정적 프롬프트 앞의 동적 텍스트가 캐시 프리픽스를 계속 깨뜨린다.
    cmd = ["claude", "--print", "--permission-mode", "bypassPermissions",
           "--tools", "Read", "--output-format", "json",
           "--append-system-prompt", prompt_text,
           "--exclude-dynamic-system-prompt-sections"]

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

    # user 메시지 안에 파일 reference 를 @absolute_path 형식으로 추가
    if attachments:
        att_lines = "\n".join(f"- @{os.path.abspath(att)}" for att in attachments)
        user_parts.append("## 첨부 파일\n\n다음 파일들을 참고하세요:\n" + att_lines)

    # payload 도 첨부도 없는 경우(현재 15개 호출처 중 해당 없음 — 방어) 빈 stdin 방지
    user_text = "\n\n".join(user_parts) + "\n" if user_parts else (
        "시스템 프롬프트의 지침에 따라 진행하세요.\n"
    )

    last_error = None
    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay > 0:
            log.warning("claude CLI retry attempt %d after %ds", attempt, delay)
            time.sleep(delay)

        result = subprocess.run(
            cmd,
            input=user_text,
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
                envelope = objs[-1]
                if envelope.get("type") == "result" and "result" in envelope:
                    # --output-format json 봉투: 답 텍스트는 result 필드에.
                    text = envelope.get("result") or ""
                    if _is_usage_limit(text):
                        raise UsageLimitError(f"usage limit: {text.strip()[:200]}")
                    if meta_out is not None:
                        mu = envelope.get("modelUsage") or {}
                        # 복수 모델(서브에이전트 등) 시 출력토큰 최대 = 본 호출 모델.
                        meta_out["model"] = max(
                            mu, key=lambda k: mu[k].get("outputTokens", 0),
                        ) if mu else None
                        usage = envelope.get("usage") or {}
                        # usage.input_tokens 는 비캐시 프리픽스만(실측 ~1.2k 고정) —
                        # 실제 입력은 cache_creation/read 에 잡히므로 합산해 기록.
                        in_parts = [usage.get("input_tokens"),
                                    usage.get("cache_creation_input_tokens"),
                                    usage.get("cache_read_input_tokens")]
                        meta_out["input_tokens"] = (
                            sum(p for p in in_parts if p is not None)
                            if any(p is not None for p in in_parts) else None
                        )
                        meta_out["output_tokens"] = usage.get("output_tokens")
                    inner = _extract_json_objects(text)
                    if not inner:
                        raise ValueError("No JSON in envelope result")
                    return inner[-1]
                # 봉투가 아니면(구버전/모킹) 기존 플레인 stdout 경로.
                return envelope
            except (json.JSONDecodeError, ValueError) as e:
                # rc=0 이어도 stdout 이 사용량 제한 안내 텍스트일 수 있음 — 재시도 무의미.
                if _is_usage_limit(result.stdout):
                    raise UsageLimitError(f"usage limit: {result.stdout.strip()[:200]}") from e
                log.warning("JSON parse failed: %s. stdout=%r", e, result.stdout[:200])
                last_error = e
                continue
        else:
            # 사용량 제한(5시간)은 backoff 재시도가 무의미 — 즉시 전파해 배치 중단.
            # (#100) 한도 판정은 raw stdout/stderr 검사를 유지 — 합성 diag 로
            # 대체하면 합성에 안 담긴 필드·봉투 밖 산문의 한도 문구를 놓친다.
            if _is_usage_limit(result.stdout) or _is_usage_limit(result.stderr):
                raise UsageLimitError(
                    f"usage limit: rc={result.returncode} "
                    f"{(result.stdout or result.stderr).strip()[:200]}"
                )
            # (#100) 진단은 stdout 봉투에서 합성 — stderr 만으로는 사유가 빈다.
            # 500자 상한: backfill.py agg["failed"] 가 무절단 append 하므로 원천 절단.
            diag = _failure_diagnostic(result.stdout, result.stderr)[:500]
            if "limit" in diag.lower() and not _NON_QUOTA_LIMIT_RE.search(diag):
                log.error(
                    "claude CLI rc=%d 실패에 미분류 'limit' 문구 — 쿼터 한도면 "
                    "_USAGE_LIMIT_RE 보강 검토: %r",
                    result.returncode, diag[:300],
                )
            log.warning(
                "claude CLI failed (rc=%d): %s",
                result.returncode,
                diag[:200],
            )
            last_error = RuntimeError(f"rc={result.returncode}: {diag}")

    raise ClaudeCLIError(
        f"claude CLI failed after {len(RETRY_DELAYS) + 1} attempts: {last_error}"
    )
