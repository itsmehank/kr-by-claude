"""kr_pipeline/market_context/compute/volatility.py 단위 테스트.

3 순수 함수: compute_korean_sigma_pct / derive_market_thresholds /
book_default_thresholds.
"""
from datetime import date

import pytest


# ===== derive_market_thresholds =====

def test_derive_no_clamp():
    """raw_ratio 가 [floor, ceiling] 안이면 clamped=False, 그대로 사용."""
    from kr_pipeline.market_context.compute.volatility import derive_market_thresholds
    result = derive_market_thresholds(
        sigma_pct=1.5,
        anchor_sigma=1.0,
        ftd_base=1.4,
        dist_base=-0.2,
        clamp_floor=1.0,
        clamp_ceiling=2.5,
    )
    assert result["raw_ratio"] == 1.5
    assert result["ratio_applied"] == 1.5
    assert result["clamped"] is False
    assert result["ftd_pct"] == pytest.approx(1.4 * 1.5)
    assert result["distribution_pct"] == pytest.approx(-0.2 * 1.5)
    assert result["source"] == "sigma_derived"


def test_derive_floor_clamp():
    """raw_ratio 가 floor 미만이면 floor 로 clamp."""
    from kr_pipeline.market_context.compute.volatility import derive_market_thresholds
    result = derive_market_thresholds(
        sigma_pct=0.5,
        anchor_sigma=1.0,
        ftd_base=1.4, dist_base=-0.2,
        clamp_floor=1.0, clamp_ceiling=2.5,
    )
    assert result["raw_ratio"] == 0.5
    assert result["ratio_applied"] == 1.0
    assert result["clamped"] is True
    assert result["ftd_pct"] == pytest.approx(1.4)
    assert result["distribution_pct"] == pytest.approx(-0.2)


def test_derive_ceiling_clamp():
    """raw_ratio 가 ceiling 초과면 ceiling 으로 clamp."""
    from kr_pipeline.market_context.compute.volatility import derive_market_thresholds
    result = derive_market_thresholds(
        sigma_pct=5.0,
        anchor_sigma=1.0,
        ftd_base=1.4, dist_base=-0.2,
        clamp_floor=1.0, clamp_ceiling=2.5,
    )
    assert result["raw_ratio"] == 5.0
    assert result["ratio_applied"] == 2.5
    assert result["clamped"] is True
    assert result["ftd_pct"] == pytest.approx(1.4 * 2.5)
    assert result["distribution_pct"] == pytest.approx(-0.2 * 2.5)


def test_derive_schema_keys():
    """반환 dict 가 정확히 6 키."""
    from kr_pipeline.market_context.compute.volatility import derive_market_thresholds
    result = derive_market_thresholds(
        sigma_pct=2.0, anchor_sigma=1.0,
        ftd_base=1.4, dist_base=-0.2,
        clamp_floor=1.0, clamp_ceiling=2.5,
    )
    assert set(result.keys()) == {
        "ftd_pct", "distribution_pct", "raw_ratio",
        "ratio_applied", "clamped", "source",
    }


# ===== book_default_thresholds =====

def test_book_defaults_match_pre_p2_1a():
    """fallback 결과가 pre-P2-1a behavior 와 정확히 일치."""
    from kr_pipeline.market_context.compute.volatility import book_default_thresholds
    result = book_default_thresholds(ftd_base=1.4, dist_base=-0.2)
    assert result["ftd_pct"] == 1.4
    assert result["distribution_pct"] == -0.2
    assert result["raw_ratio"] is None
    assert result["ratio_applied"] == 1.0
    assert result["clamped"] is False
    assert result["source"] == "book_default"


def test_book_defaults_schema_matches_derive():
    """fallback 과 derive 의 dict 키가 동일 (호출단 분기 단순화)."""
    from kr_pipeline.market_context.compute.volatility import (
        derive_market_thresholds, book_default_thresholds,
    )
    derived = derive_market_thresholds(
        sigma_pct=2.0, anchor_sigma=1.0,
        ftd_base=1.4, dist_base=-0.2,
        clamp_floor=1.0, clamp_ceiling=2.5,
    )
    book = book_default_thresholds(ftd_base=1.4, dist_base=-0.2)
    assert set(derived.keys()) == set(book.keys())


# ===== compute_korean_sigma_pct =====

class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
    def execute(self, *args, **kwargs):
        pass
    def fetchall(self):
        return self._rows
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
    def cursor(self):
        return _FakeCursor(self._rows)


def test_compute_sigma_normal():
    """252 row 정상 σ 측정."""
    from kr_pipeline.market_context.compute.volatility import compute_korean_sigma_pct
    # close: 100, 101, 100, 101, ... 의 단순수익률 σ
    closes = [(100.0,) if i % 2 == 0 else (101.0,) for i in range(252)]
    conn = _FakeConn(closes)
    sigma = compute_korean_sigma_pct(conn, "1001", as_of=date(2026, 5, 21))
    # 단순수익률 alternates +1%, -0.99% → σ ≈ 1.0%
    assert sigma is not None
    assert 0.9 < sigma < 1.1


def test_compute_sigma_insufficient_data():
    """rows < window * min_data_ratio (≈200) 이면 None."""
    from kr_pipeline.market_context.compute.volatility import compute_korean_sigma_pct
    closes = [(100.0,)] * 100  # 100 < 200
    conn = _FakeConn(closes)
    sigma = compute_korean_sigma_pct(conn, "1001", as_of=date(2026, 5, 21))
    assert sigma is None


def test_compute_sigma_exact_min_data():
    """rows == window * min_data_ratio 경계 — 측정 가능."""
    from kr_pipeline.market_context.compute.volatility import compute_korean_sigma_pct
    closes = [(100.0 + i * 0.1,) for i in range(200)]  # exact 200
    conn = _FakeConn(closes)
    sigma = compute_korean_sigma_pct(conn, "1001", as_of=date(2026, 5, 21))
    assert sigma is not None
