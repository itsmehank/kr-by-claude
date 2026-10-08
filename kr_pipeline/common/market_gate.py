"""시장 국면 게이트 — 분류층 §3.5 force_watch 와 트리거층 entry 경로 당일 차단(#109)이 공유하는 순수 판정.

근거: HMMS Ch.9 "FTD 없이 새 상승장 없음" — downtrend/correction 무조건, rally_attempt 는 최근 FTD 부재 시 매수 금지.
분배일은 경고(분류층 confidence 페널티)일 뿐 이 게이트의 입력이 아니다(#109 회신 Q-L ①). 신규 숫자 0 — '최근 FTD' 창은
STATUS_FTD_RECENT_DAYS(status.py·분류층과 동일).

entry_market_gate(#109, 회신 2026-10-08 Q-J B·Q-K A·A): 트리거 평가 전단의 결정론 사전 차단. production 하드 ON(설정 없음).
순수 함수 — DB·시각 접근 없음(입력 = current_status, days_since_ftd, as_of_date, trigger_date).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from kr_pipeline.common.thresholds import STATUS_FTD_RECENT_DAYS

KNOWN_MARKET_STATUSES = frozenset({"confirmed_uptrend", "rally_attempt", "downtrend", "correction"})

REASON_MARKET_GATE = "market_gate"              # 국면 규칙으로 차단
REASON_MARKET_GATE_NULL = "market_gate_null"    # 시장 행 부재·상태 결측·미지 상태(governance 4-2 null=보수)
REASON_MARKET_GATE_STALE = "market_gate_stale"  # 당일 행 없이 직전일로 대체됨(as_of_date < 판정일) — 당일 전환 미반영


def force_watch(status: str | None, days_since_ftd: int | None, *, has_last_ftd: bool = True) -> bool | None:
    """§3.5 하드룰: downtrend/correction 또는 (rally_attempt ∧ 최근 FTD 부재). 미지·결측 상태 → None(통과로 단정하지 않음).
    '최근' = 경과일 ≤ STATUS_FTD_RECENT_DAYS. 경과일 미산출·FTD 기록 없음은 최근 확인 불가 = 보수(차단)."""
    if status is None or status not in KNOWN_MARKET_STATUSES:
        return None
    ftd_recent = has_last_ftd and days_since_ftd is not None and days_since_ftd <= STATUS_FTD_RECENT_DAYS
    return status in ("downtrend", "correction") or (status == "rally_attempt" and not ftd_recent)


@dataclass(frozen=True)
class EntryMarketGate:
    blocked: bool
    reason: str | None


def entry_market_gate(*, current_status: str | None, days_since_ftd: int | None,
                      as_of_date: date | None, trigger_date: date, has_last_ftd: bool = True) -> EntryMarketGate:
    """entry 경로 트리거(go_now 가능) 당일 시장 차단. 우선순위: null(행 부재·상태 결측/미지) → stale(직전일 대체) → 국면 규칙."""
    if as_of_date is None or current_status is None or current_status not in KNOWN_MARKET_STATUSES:
        return EntryMarketGate(True, REASON_MARKET_GATE_NULL)
    if as_of_date < trigger_date:
        return EntryMarketGate(True, REASON_MARKET_GATE_STALE)
    if force_watch(current_status, days_since_ftd, has_last_ftd=has_last_ftd):
        return EntryMarketGate(True, REASON_MARKET_GATE)
    return EntryMarketGate(False, None)
