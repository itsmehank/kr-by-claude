"""#201 — LLM 러너 run 상태 판정(2026-09-27 회신 17 Q-3 A, design-judgment).

발단: 2026-09-19 weekend run 1979 — 후보 61 전량 실패(`[Errno 8] Exec format error: 'claude'`, processed 0·failures 61)가
status=success 로 남아 그 주 분류 결손이 미탐지됐다(#203 조사에서 발견).
사양: **failed = 성공 행 0**(processed 0 이면서 실패 시도 ≥1). 부분 실패는 success 유지(부분 실패 임계 신설 금지 —
failed_tickers·warnings 집계로 관측). failed 시 예외 전파 → run_tracking 이 status=failed 기록(details 보존) →
CLI 비-0 종료 → 체인 스크립트가 후속 중단 → watch_pipelines 의 failed 감시가 알림.
full-daily 처럼 단계별 결과가 중첩된 dict 는 각 단계에 같은 규칙을 적용해 하나라도 전량 실패면 failed.
"""
from __future__ import annotations


class AllAttemptsFailedError(RuntimeError):
    """LLM 배치의 모든 시도가 실패(성공 행 0) — run failed 기록·체인 중단."""


def _judge(result: dict, label: str) -> tuple[str | None, str | None]:
    """(failed 메시지, warning) — failed = 시도 ≥1 ∧ 성공 0. 대상 0(시도 0·성공 0) = success + 'no_targets' 경고(회신 18)."""
    if not isinstance(result, dict) or "processed" not in result:
        return None, None
    failures = result.get("failures")
    if failures is None:
        failures = len(result.get("failed_tickers") or [])
    processed = result.get("processed") or 0
    if processed == 0 and failures and failures > 0:
        return f"{label}: 성공 행 0 — 실패 {failures}/{failures + processed} (전량 실패)", None
    if processed == 0 and not failures:
        return None, f"no_targets: {label}"
    return None, None


def check_all_failed(result: dict, *, mode: str) -> list[str]:
    """전량 실패면 AllAttemptsFailedError. 반환 = warnings(대상 0 단계 'no_targets: …'). 판정 대상 = processed 키가 있는
    결과(또는 그 하위 단계 dict)."""
    if not isinstance(result, dict):
        return []
    msgs: list[str] = []
    warns: list[str] = []
    top_fail, top_warn = _judge(result, mode)
    if top_fail or top_warn:
        if top_fail:
            msgs.append(top_fail)
        if top_warn:
            warns.append(top_warn)
    else:
        for k, v in result.items():
            if isinstance(v, dict):
                f, w = _judge(v, f"{mode}/{k}")
                if f:
                    msgs.append(f)
                if w:
                    warns.append(w)
    if msgs:
        raise AllAttemptsFailedError("; ".join(msgs))
    return warns


def collect_stage_warnings(result) -> list[str]:
    """(#109) 결과 dict(또는 한 단계 아래 하위 단계 dict)의 'warnings' 리스트를 모은다 — 단계가 직접 올린 경고(예: 시장 데이터 결측
    전건 차단)를 pipeline_runs warnings 로 승격. 중복 제거·순서 보존."""
    if not isinstance(result, dict):
        return []
    out: list[str] = []
    for d in [result, *[v for v in result.values() if isinstance(v, dict)]]:
        w = d.get("warnings")
        if isinstance(w, list):
            out.extend(str(x) for x in w if x)
    return list(dict.fromkeys(out))
