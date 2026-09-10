"""handle_quality 결정론 검출기 — (#177) 책 경계: 조건 A(깊이비) 부재 가드 · 핸들 < 5일 미평가 · 5일 경계 평가 ·
B(거래량비)·D(분배일) 발화 회귀 · Gate3(프롬프트) 무영향 · 결정론 재현 (합성 데이터)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from kr_pipeline.common import thresholds
from kr_pipeline.llm_runner.compute.handle_quality import compute_handle_quality


def _seed_ohlcv(db, ticker, start: date, bars: list[tuple]):
    """bars = [(high, low, close, volume, dist_flag), ...] 연속 거래일."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING",
            (ticker, ticker),
        )
        d = start
        for (high, low, close, vol, dist) in bars:
            cur.execute(
                """
                INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (ticker, d, close, high, low, close, close, vol, vol * close),
            )
            cur.execute(
                """
                INSERT INTO daily_indicators (ticker, date, adj_close, sma_50, distribution_day_flag)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (ticker, d, close, close * 0.95, dist),
            )
            d += timedelta(days=1)


def _cls(pattern="cup_with_handle", pivot=100.0, basis="handle_high",
         base_high=100.0, base_low=70.0, base_depth=30.0, base_start=None, classified_at=None):
    return {
        "classified_at": classified_at, "classification": "entry", "pattern": pattern,
        "pivot_price": pivot, "pivot_basis": basis, "base_high": base_high,
        "base_low": base_low, "base_depth_pct": base_depth, "base_start_date": base_start,
    }


# 검출 규칙(불변, #175 범위): cup_bottom(low 최소) → 이후 right_rim(high>=pivot) → 이후 handle.
# CUP(vol) = 컵 6봉: 좌측 림 → 바닥(low 78, idx3) → 우측 림(high 101>=100, idx5).
#   base_rows = rows[:5] (>= BASE_MIN_DAYS 5), handle_rows = rows[5:] (우측 림봉 포함).
def _cup(vol):
    return [
        (95, 90, 92, vol, False),   # idx0 좌측 림
        (93, 85, 87, vol, False),   # idx1
        (88, 80, 82, vol, False),   # idx2
        (85, 78, 80, vol, False),   # idx3 컵 바닥 (low 78)
        (94, 88, 92, vol, False),   # idx4 회복
        (101, 96, 99, vol, False),  # idx5 우측 림 (high 101 >= 100) — 핸들 1일차
    ]


def _handle(n_after_rim: int, low: float, vol: int, dist_idx: int | None = None):
    """우측 림 다음의 핸들 봉 n개 — 지정 low 로 한 번 내려갔다 회복. 핸들 길이 = n+1(림 봉 포함)."""
    bars = []
    for i in range(n_after_rim):
        lo = low if i == 1 else 98
        bars.append((99, lo, 98, vol, dist_idx is not None and i == dist_idx))
    return bars


def _run(db, ticker, bars, start, days_after):
    _seed_ohlcv(db, ticker, start, bars)
    cls = _cls(base_depth=30.0, base_start=start,
               classified_at=datetime.combine(start + timedelta(days=days_after), datetime.min.time(), tzinfo=timezone.utc))
    return compute_handle_quality(db, ticker, cls["classified_at"], cls)


# ---------- (#177 변경 1) 조건 A 부재 가드 ----------

def test_deep_handle_alone_does_not_fire(db):
    """깊은 핸들(depth 18% / base 30% = 구 ratio 0.6) + 거래량 마름 + 분배 없음 → 미발화(None).
    깊이 절대치는 프롬프트 §4 Gate3 담당 — 검출기는 A 조건이 없다."""
    start = date(2026, 1, 5)
    r = _run(db, "HQDEEP", _cup(1000) + _handle(5, low=82, vol=400), start, 20)
    assert r is None
    assert not hasattr(thresholds, "HANDLE_DEEP_RATIO") and not hasattr(thresholds, "HANDLE_MIN_DAYS")


def test_metrics_have_no_ratio_a_but_echo_depth(db):
    start = date(2026, 1, 19)
    r = _run(db, "HQECHO", _cup(1000) + _handle(5, low=82, vol=2000), start, 20)
    assert r is not None and r["reasons"] == ["volume_not_contracting"]
    assert "ratio_a" not in r["metrics"] and r["metrics"]["handle_depth_pct"] == 18.0
    assert r["metrics"]["handle_low"] == 82.0 and r["metrics"]["handle_high"] == 100.0


# ---------- (#177 변경 2) 책 최소 길이 ----------

def test_handle_shorter_than_5_days_not_evaluated(db):
    """핸들 4일(림 봉 + 3) — 거래량 폭증·분배일 있어도 미평가(None): 핸들 미형성은 결함이 아님."""
    start = date(2026, 2, 2)
    r = _run(db, "HQSHORT", _cup(1000) + _handle(3, low=90, vol=3000, dist_idx=1), start, 20)
    assert r is None


def test_handle_exactly_5_days_is_evaluated(db):
    """핸들 5일(림 봉 + 4) = HANDLE_LEGIT_MIN_DAYS 경계 → 평가됨(거래량비로 발화)."""
    start = date(2026, 2, 16)
    r = _run(db, "HQFIVE", _cup(1000) + _handle(4, low=90, vol=3000), start, 20)
    assert r is not None and r["fired"] and "volume_not_contracting" in r["reasons"]
    assert r["metrics"]["handle_start"] == (start + timedelta(days=5)).isoformat()
    assert thresholds.HANDLE_LEGIT_MIN_DAYS == 5


# ---------- B·D 발화 회귀 ----------

def test_shallow_handle_dry_volume_no_dist_not_fired(db):
    start = date(2026, 3, 2)
    r = _run(db, "HQSHAL", _cup(2000) + _handle(5, low=96, vol=400), start, 20)
    assert r is None


def test_volume_not_contracting_fires(db):
    start = date(2026, 3, 16)
    r = _run(db, "HQVOL", _cup(1000) + _handle(5, low=96, vol=2000), start, 20)
    assert r is not None and r["reasons"] == ["volume_not_contracting"]
    assert r["metrics"]["ratio_b"] > thresholds.HANDLE_VOLUME_NOT_CONTRACTING_RATIO


def test_distribution_in_handle_fires(db):
    start = date(2026, 4, 1)
    r = _run(db, "HQDIST", _cup(1000) + _handle(5, low=96, vol=400, dist_idx=2), start, 20)
    assert r is not None and r["reasons"] == ["distribution_in_handle"]
    assert r["metrics"]["distribution_days"] == 1


def test_not_cup_with_handle_skipped(db):
    cls = _cls(pattern="flat_base", base_start=date(2026, 5, 1),
               classified_at=datetime(2026, 5, 13, tzinfo=timezone.utc))
    assert compute_handle_quality(db, "NOPE", cls["classified_at"], cls) is None


def test_pivot_basis_not_handle_high_skipped(db):
    cls = _cls(basis="range_high", base_start=date(2026, 5, 1),
               classified_at=datetime(2026, 5, 13, tzinfo=timezone.utc))
    assert compute_handle_quality(db, "NOPE2", cls["classified_at"], cls) is None


def test_right_rim_never_recovered_skipped(db):
    start = date(2026, 6, 1)
    _seed_ohlcv(db, "HQNORIM", start, [(50, 40, 45, 1000, False)] * 12)
    cls = _cls(pivot=100.0, base_start=start, classified_at=datetime(2026, 6, 18, tzinfo=timezone.utc))
    assert compute_handle_quality(db, "HQNORIM", cls["classified_at"], cls) is None


# ---------- Gate3(LLM 프롬프트) 무영향 · 결정론 재현 ----------

def test_prompt_gate3_depth_rule_unchanged():
    """검출기 A 제거는 프롬프트 §4 Gate3 의 절대 깊이(12%) 판정을 건드리지 않는다."""
    text = (Path(__file__).resolve().parents[1] / "prompts" / "analyze_chart_v3.md").read_text(encoding="utf-8")
    assert "깊이 > HANDLE_DEPTH_BULL_MAX_PCT(12%)" in text and "handle_status=faulty" in text
    assert "Handle depth ≤ 8–12% from its own peak" in text


def test_detector_is_deterministic(db):
    start = date(2026, 7, 6)
    r1 = _run(db, "HQDET", _cup(1000) + _handle(5, low=90, vol=2000, dist_idx=3), start, 20)
    cls = _cls(base_depth=30.0, base_start=start, classified_at=r1 and datetime(2026, 7, 26, tzinfo=timezone.utc))
    r2 = compute_handle_quality(db, "HQDET", cls["classified_at"], cls)
    assert r1 == r2 and r1["reasons"] == ["volume_not_contracting", "distribution_in_handle"]


def _seed_ohlcv_adj(db, ticker, start: date, bars: list[tuple]):
    """raw = garbage(×7), adj_* = real."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING",
                    (ticker, ticker))
        d = start
        for (high, low, close, vol, dist) in bars:
            cur.execute(
                """INSERT INTO daily_prices
                    (ticker,date,open,high,low,close,adj_close,adj_open,adj_high,adj_low,adj_volume,volume,value)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (ticker, d, close * 7, high * 7, low * 7, close * 7, close, close, high, low, float(vol), vol * 7, vol * close * 7))
            cur.execute(
                "INSERT INTO daily_indicators (ticker,date,adj_close,sma_50,distribution_day_flag) VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING", (ticker, d, close, close * 0.95, dist))
            d += timedelta(days=1)


def test_handle_quality_uses_adjusted(db):
    start = date(2026, 5, 4)
    _seed_ohlcv_adj(db, "HQADJ", start, _cup(1000) + _handle(5, low=82, vol=2000))
    cls = _cls(base_depth=30.0, base_start=start, classified_at=datetime(2026, 5, 24, tzinfo=timezone.utc))
    r = compute_handle_quality(db, "HQADJ", cls["classified_at"], cls)
    assert r is not None and r["fired"] and r["metrics"]["handle_low"] == 82.0
