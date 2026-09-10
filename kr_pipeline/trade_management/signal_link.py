"""(#162 2026-09-09) 시그널(entry_params) → positions 연결 + 추격 매수 표시 — 배관 전용.

- 손절 판정은 **불변**: stop_stack 은 매입가 × (1 − 8%) 기준(book-mandated, HMMS 7~8%). 여기서
  저장하는 signal_stop_price(pivot × 0.92)·chase_pct 는 참고·표시용이며 어떤 판정에도 입력되지
  않는다(governance 4-3 상수 계약 / 4-6 매매 규칙 SSOT = trading-rules).
- 추격 여부는 기록·표시만 — 기록 거부 없음(수동 체결 모델). 신규 숫자 0: 5% 임계는 기존
  PIVOT_EXTENDED_BAND_MULT(1.05, A §8.5 extended 인터셉트) 재사용.
- 매칭: 해당 symbol 의 entry_params 중 signal_at(날짜) ≤ entry_date 인 가장 최근 행. 매칭 창(N일)은
  신설하지 않는다 — signal_gap_days 를 저장해 사람이 본다. --signal-at 로 명시 지정 가능.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from psycopg import Connection

from kr_pipeline.common.thresholds import PIVOT_EXTENDED_BAND_MULT

CHASE_LIMIT = round(PIVOT_EXTENDED_BAND_MULT - 1, 6)   # 0.05 — 재사용(값 신설 아님)
_ROUND = 6  # 분수 비교의 부동소수 잡음 제거(정확히 5% 는 미초과)

NO_SIGNAL_WARNING = "시그널 없는 매수 — 추격·손절 대조 불가"


def chase_warning(chase_pct: float) -> str:
    return (f"추격 매수 +{chase_pct * 100:.1f}% — 책 기준 {CHASE_LIMIT * 100:.0f}% 초과. "
            "매입가 기준 8% 손절은 정상 되돌림에 걸릴 수 있음(HMMS). 손절가는 그대로 매입가 × 0.92")


@dataclass(frozen=True)
class SignalLink:
    signal_at: datetime
    pivot_price: float | None
    signal_stop_price: float | None
    chase_pct: float | None          # entry_price / pivot_price − 1 (분수). pivot 없으면 None
    chase_over_limit: bool | None    # chase_pct > CHASE_LIMIT. chase 없으면 None
    signal_gap_days: int             # entry_date − signal_at(날짜). 표시용, 임계 없음


def chase_fields(entry_price: float, pivot_price: float | None) -> tuple[float | None, bool | None]:
    """chase_pct·chase_over_limit. pivot 부재/비양수 → (None, None). 경계: 정확히 5% 는 미초과."""
    if pivot_price is None or not pivot_price > 0:
        return None, None
    chase = round(entry_price / pivot_price - 1, _ROUND)
    return chase, chase > CHASE_LIMIT


def match_signal(conn: Connection, *, symbol: str, entry_date: date, entry_price: float,
                 signal_at: datetime | None = None) -> SignalLink | None:
    """symbol 의 entry_params 중 signal_at(날짜) ≤ entry_date 인 가장 최근 행. signal_at 명시 시 그
    행(존재해야 함 — 없으면 ValueError). 매칭 행 없으면 None."""
    with conn.cursor() as cur:
        if signal_at is not None:
            cur.execute(
                "SELECT signal_at, pivot_price, stop_loss FROM entry_params "
                "WHERE symbol = %s AND signal_at = %s",
                (symbol, signal_at))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"entry_params not found: {symbol} @ {signal_at.isoformat()}")
        else:
            cur.execute(
                "SELECT signal_at, pivot_price, stop_loss FROM entry_params "
                "WHERE symbol = %s AND signal_at::date <= %s "
                "ORDER BY signal_at DESC LIMIT 1",
                (symbol, entry_date))
            row = cur.fetchone()
    if row is None:
        return None
    sig_at, pivot, stop = row
    pivot_f = float(pivot) if pivot is not None else None
    chase, over = chase_fields(entry_price, pivot_f)
    return SignalLink(
        signal_at=sig_at, pivot_price=pivot_f,
        signal_stop_price=float(stop) if stop is not None else None,
        chase_pct=chase, chase_over_limit=over,
        signal_gap_days=(entry_date - sig_at.date()).days,
    )


def link_warnings(link: SignalLink | None) -> list[str]:
    """--add 출력·Slack 용 경고 문구(판정 무관)."""
    if link is None:
        return [NO_SIGNAL_WARNING]
    if link.chase_over_limit:
        return [chase_warning(link.chase_pct)]
    return []
