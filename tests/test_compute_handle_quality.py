"""handle_quality 휴리스틱 경계 + 트리거 단위 테스트 (합성 데이터)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

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


# 새 휴리스틱: cup_bottom (low 최소) → 그 이후 right_rim (high>=pivot) → 그 이후 handle.
# CUP(vol) = 컵 6봉: 좌측 림 → 바닥(low 78, idx3) → 우측 림(high 101>=100, idx5).
#   base_rows = rows[:5] (idx0~4, 5봉 >= MIN_BASE_DAYS).
#   handle_rows = rows[5:] (우측 림봉 idx5 + 핸들봉들, >= MIN_HANDLE_DAYS).
def _cup(vol):
    return [
        (95, 90, 92, vol, False),   # idx0 좌측 림
        (93, 85, 87, vol, False),   # idx1
        (88, 80, 82, vol, False),   # idx2
        (85, 78, 80, vol, False),   # idx3 컵 바닥 (low 78)
        (94, 88, 92, vol, False),   # idx4 회복
        (101, 96, 99, vol, False),  # idx5 우측 림 (high 101 >= 100)
    ]


def test_deep_handle_fires(db):
    """handle depth% / base depth% > 0.33 → deep_handle 발화."""
    start = date(2026, 1, 5)
    # 깊은 handle: 저점 82 → depth=(100-82)/100=18%, base 30% → ratio 0.6
    handle = [(99, 85, 86, 700, False), (97, 82, 84, 600, False), (98, 90, 96, 700, False)]
    _seed_ohlcv(db, "HQDEEP", start, _cup(1000) + handle)
    cls = _cls(base_depth=30.0, base_start=start, classified_at=datetime(2026, 1, 20, tzinfo=timezone.utc))
    r = compute_handle_quality(db, "HQDEEP", cls["classified_at"], cls)
    assert r is not None and r["fired"]
    assert "deep_handle" in r["reasons"]
    assert r["metrics"]["ratio_a"] > 0.33
    # 휴리스틱이 우측 림(idx5) 이후를 handle 로 잡았는지 — handle_low 82 (좌측 림 아님)
    assert r["metrics"]["handle_low"] == 82.0


def test_shallow_handle_no_volume_no_dist_not_fired(db):
    """얕은 handle + 거래량 마름 + 분배 없음 → 미발화 (None)."""
    start = date(2026, 2, 2)
    # 얕은 handle: 저점 ~96 (우측 림봉 low 96 포함) → depth 4%, base 30% → ratio 0.13
    handle = [(100, 98, 99, 400, False), (99, 97, 98, 380, False), (100, 98, 99, 360, False)]
    _seed_ohlcv(db, "HQSHAL", start, _cup(2000) + handle)
    cls = _cls(base_depth=30.0, base_start=start, classified_at=datetime(2026, 2, 16, tzinfo=timezone.utc))
    r = compute_handle_quality(db, "HQSHAL", cls["classified_at"], cls)
    assert r is None, "얕고 거래량 마른 handle 은 미발화"


def test_volume_not_contracting_fires(db):
    """handle 거래량이 base 대비 안 줄면 (ratio_b > 0.80) 발화."""
    start = date(2026, 3, 2)
    # 얕지만 (depth 4%, base 30 → ratio_a 0.13 미발화) 거래량 높음 → volume_not_contracting
    handle = [(100, 98, 99, 2000, False), (99, 97, 98, 2000, False), (100, 98, 99, 2000, False)]
    _seed_ohlcv(db, "HQVOL", start, _cup(1000) + handle)
    cls = _cls(base_depth=30.0, base_start=start, classified_at=datetime(2026, 3, 16, tzinfo=timezone.utc))
    r = compute_handle_quality(db, "HQVOL", cls["classified_at"], cls)
    assert r is not None and "volume_not_contracting" in r["reasons"]
    assert "deep_handle" not in r["reasons"]


def test_distribution_in_handle_fires(db):
    """handle 구간 분배일 1건 → 발화 (A/B 미발화 조건에서 dist 단독)."""
    start = date(2026, 4, 1)
    handle = [(100, 98, 99, 400, False), (99, 97, 98, 380, True),  # 분배일
              (100, 98, 99, 360, False)]
    _seed_ohlcv(db, "HQDIST", start, _cup(1000) + handle)
    cls = _cls(base_depth=30.0, base_start=start, classified_at=datetime(2026, 4, 15, tzinfo=timezone.utc))
    r = compute_handle_quality(db, "HQDIST", cls["classified_at"], cls)
    assert r is not None and "distribution_in_handle" in r["reasons"]
    assert "deep_handle" not in r["reasons"]
    assert "volume_not_contracting" not in r["reasons"]


def test_not_cup_with_handle_skipped(db):
    """pattern != cup_with_handle → None (적용 안 함)."""
    cls = _cls(pattern="flat_base", base_start=date(2026, 5, 1),
               classified_at=datetime(2026, 5, 13, tzinfo=timezone.utc))
    assert compute_handle_quality(db, "NOPE", cls["classified_at"], cls) is None


def test_pivot_basis_not_handle_high_skipped(db):
    """pivot_basis != handle_high → None."""
    cls = _cls(basis="range_high", base_start=date(2026, 5, 1),
               classified_at=datetime(2026, 5, 13, tzinfo=timezone.utc))
    assert compute_handle_quality(db, "NOPE2", cls["classified_at"], cls) is None


def test_right_rim_never_recovered_skipped(db):
    """컵 바닥 이후 high 가 pivot 회복 못 하면 None (우측 림 미형성)."""
    start = date(2026, 6, 1)
    bars = [(50, 40, 45, 1000, False)] * 12   # pivot 100 도달 안 함
    _seed_ohlcv(db, "HQNORIM", start, bars)
    cls = _cls(pivot=100.0, base_start=start,
               classified_at=datetime(2026, 6, 18, tzinfo=timezone.utc))
    assert compute_handle_quality(db, "HQNORIM", cls["classified_at"], cls) is None


def _seed_ohlcv_adj(db, ticker, start: date, bars: list[tuple]):
    """raw = garbage(×7), adj_* = real. adj-reading function should behave like _seed_ohlcv."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker,name,market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING",
            (ticker, ticker),
        )
        d = start
        for (high, low, close, vol, dist) in bars:
            cur.execute(
                """
                INSERT INTO daily_prices
                    (ticker,date,open,high,low,close,adj_close,adj_open,adj_high,adj_low,adj_volume,volume,value)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (ticker, d, close * 7, high * 7, low * 7, close * 7, close, close, high, low, float(vol), vol * 7, vol * close * 7),
            )
            cur.execute(
                """
                INSERT INTO daily_indicators (ticker,date,adj_close,sma_50,distribution_day_flag)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING
                """,
                (ticker, d, close, close * 0.95, dist),
            )
            d += timedelta(days=1)


def test_handle_quality_uses_adjusted(db):
    """adj_* 컬럼 우선 사용 검증 — raw 에 ×7 가비지, adj_* 에 실제 값."""
    start = date(2026, 5, 4)
    handle = [(99, 85, 86, 700, False), (97, 82, 84, 600, False), (98, 90, 96, 700, False)]
    _seed_ohlcv_adj(db, "HQADJ", start, _cup(1000) + handle)
    cls = _cls(base_depth=30.0, base_start=start, classified_at=datetime(2026, 5, 22, tzinfo=timezone.utc))
    r = compute_handle_quality(db, "HQADJ", cls["classified_at"], cls)
    assert r is not None and r["fired"]
    assert r["metrics"]["handle_low"] == 82.0
    assert "deep_handle" in r["reasons"]
