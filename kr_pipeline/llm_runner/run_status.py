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


def _judge(result: dict, label: str) -> str | None:
    if not isinstance(result, dict) or "processed" not in result:
        return None
    failures = result.get("failures")
    if failures is None:
        failures = len(result.get("failed_tickers") or [])
    processed = result.get("processed") or 0
    if processed == 0 and failures and failures > 0:
        return f"{label}: 성공 행 0 — 실패 {failures}/{failures + processed} (전량 실패)"
    return None


def check_all_failed(result: dict, *, mode: str) -> None:
    """전량 실패면 AllAttemptsFailedError. 판정 대상 = processed 키가 있는 결과(또는 그 하위 단계 dict)."""
    if not isinstance(result, dict):
        return
    msgs = []
    top = _judge(result, mode)
    if top:
        msgs.append(top)
    else:
        for k, v in result.items():
            m = _judge(v, f"{mode}/{k}") if isinstance(v, dict) else None
            if m:
                msgs.append(m)
    if msgs:
        raise AllAttemptsFailedError("; ".join(msgs))
