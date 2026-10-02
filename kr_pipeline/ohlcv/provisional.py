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


def replace_today_rows(frames: dict[str, pd.DataFrame], snap: pd.DataFrame, today: date,
                       dropped: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """재조회 스냅샷(ticker 컬럼 포함)으로 각 종목의 오늘 행을 교체. 스냅샷에 없는 종목의 오늘 행은 제거(미확정 취급)하되
    종목을 `dropped` 에 모아 호출자가 run warnings 로 승격한다 — 무음 소멸 금지(#219 리뷰). 초회에 없던 종목(빈 프레임)이
    재조회에 있으면 그 오늘 행을 받는다. 빈 스냅샷은 호출자(guard_today)가 예외로 막는다."""
    out: dict[str, pd.DataFrame] = {}
    by_ticker = {t: g.drop(columns=["ticker"]) for t, g in snap.groupby("ticker")} if not snap.empty else {}
    for ticker, df in frames.items():
        new = by_ticker.get(ticker)
        if df is None or df.empty or "date" not in df.columns:
            out[ticker] = new.reset_index(drop=True) if new is not None and not new.empty else df
            continue
        keep = df[df["date"] != today]
        if new is not None and not new.empty:
            keep = pd.concat([keep, new[keep.columns]], ignore_index=True)
        elif len(keep) < len(df) and dropped is not None:
            dropped.append(ticker)
        out[ticker] = keep.sort_values("date").reset_index(drop=True)
    return out


def _today_rows(frames: dict[str, pd.DataFrame], today: date) -> pd.DataFrame:
    """초회 스냅샷의 오늘 행(ticker 컬럼 복원) — 증거 보존용."""
    parts = []
    for ticker, df in frames.items():
        if df is None or df.empty or "date" not in df.columns:
            continue
        t = df[df["date"] == today]
        if not t.empty:
            parts.append(t.assign(ticker=ticker))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _persist_evidence(today: date, first_today: pd.DataFrame, snap: pd.DataFrame | None, reason: str) -> str:
    """운영 규칙 5(KRX 응답은 적재 성공과 무관하게 적재 전 파일 보존) — 저장 0 경로의 두 스냅샷(초회 오늘 행·재조회)을 JSON 으로.
    위치 = $KR_VERIFICATION_DIR(기본 data/verification). 실패해도 트립와이어를 가리지 않는다(경고 로그만)."""
    import json, os
    from datetime import datetime
    d = os.environ.get("KR_VERIFICATION_DIR") or "data/verification"
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"provisional_{today:%Y%m%d}_{datetime.now():%H%M%S}_{reason}.json")
    doc = {
        "target": today.isoformat(), "reason": reason, "saved_at": datetime.now().isoformat(timespec="seconds"),
        "first_today_rows": json.loads(first_today.to_json(orient="records", date_format="iso")) if not first_today.empty else [],
        "refetch_rows": json.loads(snap.to_json(orient="records", date_format="iso")) if snap is not None and not snap.empty else [],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return path


def _persist_safely(today: date, frames: dict[str, pd.DataFrame], snap: pd.DataFrame | None, reason: str) -> None:
    try:
        path = _persist_evidence(today, _today_rows(frames, today), snap, reason)
        if path:
            log.warning("provisional_snapshot: 증거 보존 %s", path)
    except Exception as e:  # noqa: BLE001 — 보존 실패가 저장 0 판정을 가리면 안 됨
        log.warning("provisional_snapshot: 증거 보존 실패(%s) — 판정은 그대로", e)


def guard_today(
    frames: dict[str, pd.DataFrame], today: date, *, refetch: Callable[[date], pd.DataFrame],
    wait_s: float = PROVISIONAL_RETRY_WAIT_S, warnings: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """오늘 봉 잠정값 검사. 통과 → frames 그대로. 위반 → 대기·재조회 1회 → 통과면 교체된 frames, 아니면 예외(저장 0).

    ⚠ 위반 0 ≠ 확정 증거(2차 리뷰): 09-29 17:20 잠정 스냅샷에서 고저 위반은 2,449 중 257 뿐이었고 나머지 2,001 행도 최종값과
    달랐다. 이 검사는 "시장 전체에 이상치 ≥1" 을 가정한 백스톱이며 1차 방어는 시각(CLOSE_BUFFER)이다. 최종성 확정은 재조회 대조.
    `warnings` 를 주면 스냅샷에 없어 오늘 행이 제거된 종목 수를 run warnings 로 승격한다(pipeline_runs 영속).
    """
    n0, sample0 = count_today_violations(frames, today)
    if n0 == 0:
        return frames
    log.warning("provisional_snapshot: %s 비할트 고저 위반 %d행 %s — %ds 대기 후 재조회 1회", today, n0, sample0, wait_s)
    _sleep(wait_s)
    try:
        snap = refetch(today)
    except Exception as e:  # noqa: BLE001 — 전송 예외(with_retry reraise)도 같은 접두어로 수렴(두 계수 기록)
        log.warning("provisional_snapshot: 재조회 실패 %s (초회 위반 %d) — %s", today, n0, e)
        _persist_safely(today, frames, None, "refetch_error")
        raise AdjustmentTripwireError(
            f"provisional_snapshot: 당일 {today} 비할트 고저 위반 {n0}행 → {wait_s:.0f}s 후 재조회 실패({e!r}) — 저장 0") from e
    if snap is None or snap.empty:
        # 차단/빈 응답(fetch_market_snapshot 은 KeyError·빈 DF 를 빈 스냅샷으로 정규화) — 오늘 행 전부 제거 후 '위반 0' 통과 금지(#219 리뷰)
        _persist_safely(today, frames, snap, "refetch_empty")
        raise AdjustmentTripwireError(
            f"provisional_snapshot: 당일 {today} 비할트 고저 위반 {n0}행 → {wait_s:.0f}s 후 재조회 스냅샷 비어 있음"
            f"(status={getattr(snap, 'attrs', {}).get('snapshot_status', '?')}) — 저장 0(잠정값 여부 판정 불가)")
    dropped: list[str] = []
    frames2 = replace_today_rows(frames, snap, today, dropped)
    if dropped:
        msg = f"provisional_dropped_today: {len(dropped)} 종목의 {today} 행이 재조회 스냅샷에 없어 제거됨 {sorted(dropped)[:10]}"
        log.warning("provisional_snapshot: %s", msg)
        if warnings is not None:
            warnings.append(msg)
    n1, sample1 = count_today_violations(frames2, today)
    log.warning("provisional_snapshot: 재조회 결과 %s 위반 %d행 %s (초회 %d) — 확정 시각 실측 자료", today, n1, sample1, n0)
    if n1 > 0:
        _persist_safely(today, frames, snap, "still_provisional")
        raise AdjustmentTripwireError(
            f"provisional_snapshot: 당일 {today} 비할트 고저 위반 {n0}행 → {wait_s:.0f}s 후 재조회 {n1}행 {sample1} — 저장 0(잠정 스냅샷)"
        )
    return frames2
