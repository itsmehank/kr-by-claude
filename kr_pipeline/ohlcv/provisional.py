"""당일 스냅샷 잠정값 방어 — #207 회신 21 Q-5a ③ (시각 방어 ①②와 독립인 **값** 방어).

_run_upsert 의 ⓪ 단계: ① raw 커밋 **전에** 오늘 날짜 봉만 in-memory 로 비할트 low ≤ close ≤ high 를 검사한다.
위반 ≥1 → 잠정 스냅샷(애프터마켓 진행 중 20분 지연 현재값)으로 보고 PROVISIONAL_RETRY_WAIT_S 대기 후 오늘 스냅샷을
1회 재조회(KRX +1콜) → 여전히 위반이면 AdjustmentTripwireError(저장 0, run failed). 두 계수는 로그로 남겨 확정 시각
실측 자료가 된다(회신 21). 과거 날짜 봉은 회신 17 순서(① 커밋 → ② 검사) 그대로 — 잠정값일 수 없고, 잠정 스냅샷은
KRX 봉이 아니므로 fail-open 원칙과 충돌하지 않는다(회신 21).
"""
from __future__ import annotations

import logging
import time as _time
from datetime import date
from typing import Callable

import pandas as pd

from kr_pipeline.ohlcv.tripwires import AdjustmentTripwireError

log = logging.getLogger("kr_pipeline.ohlcv.provisional")

PROVISIONAL_RETRY_WAIT_S = 600   # 회신 21: 10분 대기 후 재조회 1회
_sleep: Callable[[float], None] = _time.sleep   # 테스트 주입점


def count_today_violations(frames: dict[str, pd.DataFrame], today: date) -> tuple[int, list[str]]:
    """오늘 날짜 행 중 비할트(high>0) 고저 위반 수와 종목 목록(정렬, 최대 10)."""
    bad: list[str] = []
    for ticker, df in frames.items():
        if df is None or df.empty or "date" not in df.columns:
            continue
        t = df[df["date"] == today]
        if t.empty:
            continue
        t = t[t["high"] > 0]
        if t.empty:
            continue
        viol = t[~((t["low"] <= t["close"]) & (t["close"] <= t["high"]))]
        if not viol.empty:
            bad.append(ticker)
    bad.sort()
    return len(bad), bad[:10]


def replace_today_rows(frames: dict[str, pd.DataFrame], snap: pd.DataFrame, today: date) -> dict[str, pd.DataFrame]:
    """재조회 스냅샷(ticker 컬럼 포함)으로 각 종목의 오늘 행을 교체. 스냅샷에 없는 종목의 오늘 행은 제거(미확정 취급)하되
    건수를 경고로 남긴다 — 무음 소멸 금지(#219 리뷰). 빈 스냅샷은 호출자(guard_today)가 예외로 막는다."""
    out: dict[str, pd.DataFrame] = {}
    by_ticker = {t: g.drop(columns=["ticker"]) for t, g in snap.groupby("ticker")} if not snap.empty else {}
    dropped: list[str] = []
    for ticker, df in frames.items():
        if df is None or df.empty or "date" not in df.columns:
            out[ticker] = df
            continue
        keep = df[df["date"] != today]
        new = by_ticker.get(ticker)
        if new is not None and not new.empty:
            keep = pd.concat([keep, new[keep.columns] if len(keep.columns) else new], ignore_index=True)
        elif len(keep) < len(df):
            dropped.append(ticker)
        out[ticker] = keep.sort_values("date").reset_index(drop=True)
    if dropped:
        log.warning("provisional_snapshot: 재조회 스냅샷에 없어 %s 오늘 행 제거 %d종목 %s", today, len(dropped), sorted(dropped)[:10])
    return out


def guard_today(
    frames: dict[str, pd.DataFrame], today: date, *, refetch: Callable[[date], pd.DataFrame],
    wait_s: float = PROVISIONAL_RETRY_WAIT_S,
) -> dict[str, pd.DataFrame]:
    """오늘 봉 잠정값 검사. 통과 → frames 그대로. 위반 → 대기·재조회 1회 → 통과면 교체된 frames, 아니면 예외(저장 0)."""
    n0, sample0 = count_today_violations(frames, today)
    if n0 == 0:
        return frames
    log.warning("provisional_snapshot: %s 비할트 고저 위반 %d행 %s — %ds 대기 후 재조회 1회", today, n0, sample0, wait_s)
    _sleep(wait_s)
    snap = refetch(today)
    if snap is None or snap.empty:
        # 차단/빈 응답(fetch_market_snapshot 은 예외 없이 빈 스냅샷 반환) — 오늘 행 전부 제거 후 '위반 0' 통과 금지(#219 리뷰)
        raise AdjustmentTripwireError(
            f"provisional_snapshot: 당일 {today} 비할트 고저 위반 {n0}행 → {wait_s:.0f}s 후 재조회 스냅샷 비어 있음"
            f"(status={getattr(snap, 'attrs', {}).get('snapshot_status', '?')}) — 저장 0(잠정값 여부 판정 불가)")
    frames2 = replace_today_rows(frames, snap, today)
    n1, sample1 = count_today_violations(frames2, today)
    log.warning("provisional_snapshot: 재조회 결과 %s 위반 %d행 %s (초회 %d) — 확정 시각 실측 자료", today, n1, sample1, n0)
    if n1 > 0:
        raise AdjustmentTripwireError(
            f"provisional_snapshot: 당일 {today} 비할트 고저 위반 {n0}행 → {wait_s:.0f}s 후 재조회 {n1}행 {sample1} — 저장 0(잠정 스냅샷)"
        )
    return frames2
