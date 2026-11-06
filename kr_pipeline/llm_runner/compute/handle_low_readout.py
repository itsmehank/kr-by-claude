# kr_pipeline/llm_runner/compute/handle_low_readout.py
"""#175 저장본 재현 readout 의 순수 함수(SELECT 없음, 매매 경로 비소비).

- legacy_detect: 2026-11-06 교체 **전** 검출기 규칙의 독립 재구현(정의 원문 보존 — governance 1-2(i)):
  창 끝 = classified_at 의 UTC 날짜(미포함), 손잡이 시작 = 컵 바닥 이후 `high ≥ pivot`(1단), (B) 손잡이 평균 ÷ 컵 평균 > 0.80,
  (D) 분배일 ≥ 1. specs/2026-11-05-issue175-handle-detector-spec.md §2 S1~S8.
- compare_fired_rows / fired_transition: 구·신 결과 대조 라벨.
스크립트 = scripts/issue175_handle_low_readout.py.
"""
from __future__ import annotations

from datetime import date, datetime

from kr_pipeline.common import thresholds

LEGACY_VOLUME_NOT_CONTRACTING_RATIO = 0.80   # 삭제된 HANDLE_VOLUME_NOT_CONTRACTING_RATIO(heuristic) — 재현 전용 보존값


def _d(x):
    return x.date() if isinstance(x, datetime) else x


def legacy_detect(rows, cls: dict) -> tuple[dict | None, str | None]:
    """구 규칙. rows = [(date, high, low, close, volume, sma50, dist_flag, ...)] (창은 호출자가 UTC 날짜 미포함으로 끊음).
    반환 (dict | None, skip_reason)."""
    if cls.get("pattern") != "cup_with_handle":
        return None, "S1 pattern"
    if cls.get("pivot_basis") != "handle_high":
        return None, "S1 pivot_basis"
    if cls.get("base_start_date") is None:
        return None, "S1 base_start None"
    if cls.get("pivot_price") is None or cls.get("base_depth_pct") is None:
        return None, "S1 pivot/depth None"
    if float(cls["base_depth_pct"]) <= 0:
        return None, "S1 base_depth<=0"
    if len(rows) < thresholds.BASE_MIN_DAYS + thresholds.HANDLE_LEGIT_MIN_DAYS:
        return None, "S2 window<10"
    hh = float(cls["pivot_price"])
    lows = [float(r[2]) for r in rows]
    cup_bottom = lows.index(min(lows))
    rim = next((i for i in range(cup_bottom, len(rows)) if float(rows[i][1]) >= hh), None)
    if rim is None:
        return None, "S4 rim not recovered"
    base_rows, handle_rows = rows[:rim], rows[rim:]
    if len(handle_rows) < thresholds.HANDLE_LEGIT_MIN_DAYS:
        return None, "S5 handle<5"
    if len(base_rows) < thresholds.BASE_MIN_DAYS:
        return None, "S5 base<5"
    hl = min(float(r[2]) for r in handle_rows)
    avg_b = sum(float(r[4]) for r in base_rows) / len(base_rows)
    avg_h = sum(float(r[4]) for r in handle_rows) / len(handle_rows)
    ratio_b = avg_h / avg_b if avg_b else 0.0
    dist = sum(1 for r in handle_rows if r[6])
    return {
        "handle_start": _d(handle_rows[0][0]).isoformat(), "handle_end": _d(handle_rows[-1][0]).isoformat(),
        "handle_high": round(hh, 2), "handle_low": round(hl, 2), "handle_depth_pct": round((hh - hl) / hh * 100, 2),
        "ratio_b": round(ratio_b, 3), "distribution_days": dist, "handle_days": len(handle_rows),
        "fired": ratio_b > LEGACY_VOLUME_NOT_CONTRACTING_RATIO or dist >= 1,
    }, None


def compare_fired_rows(stored: dict, new: dict) -> dict:
    """저장 발화 행 metrics vs 신 검출기 metrics — 시작·고점 일치, 창 끝 변화."""
    return {
        "start_match": str(stored.get("handle_start")) == str(new.get("handle_start")),
        "high_match": _num_eq(stored.get("handle_high"), new.get("handle_high")),
        "end_changed": str(stored.get("handle_end")) != str(new.get("handle_end")),
    }


def _num_eq(a, b, eps: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is b
    return abs(float(a) - float(b)) < eps


def fired_transition(old_fired, new_fired) -> str:
    left = "legacy_none" if old_fired is None else ("fired" if old_fired else "not")
    right = "none" if new_fired is None else ("fired" if new_fired else "not")
    return f"{left}→{right}"


def quantiles(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    s = sorted(xs)
    q = lambda p: s[min(len(s) - 1, int(p * len(s)))]  # noqa: E731
    return {"n": len(s), "min": s[0], "q1": q(.25), "median": q(.5), "q3": q(.75), "p90": q(.9), "max": s[-1]}


def kst_fallback_as_of(classified_at: datetime) -> date:
    """analyzed_for_date 가 없는 과거 행의 as_of = classified_at 의 KST 날짜 − 1일(그날 봉까지 포함)."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    return classified_at.astimezone(ZoneInfo("Asia/Seoul")).date() - timedelta(days=1)
