# tests/test_market_context_breadth.py
import pytest

from kr_pipeline.market_context.compute.breadth import compute_breadth


def test_breadth_basic():
    """10 종목 중 6 개가 SMA200 위 → 60.0%."""
    rows = [
        {"adj_close": 100.0, "sma_200": 90.0},   # above
        {"adj_close": 100.0, "sma_200": 95.0},   # above
        {"adj_close": 100.0, "sma_200": 99.0},   # above
        {"adj_close": 100.0, "sma_200": 80.0},   # above
        {"adj_close": 100.0, "sma_200": 50.0},   # above
        {"adj_close": 100.0, "sma_200": 70.0},   # above
        {"adj_close": 100.0, "sma_200": 110.0},  # below
        {"adj_close": 100.0, "sma_200": 120.0},  # below
        {"adj_close": 100.0, "sma_200": 130.0},  # below
        {"adj_close": 100.0, "sma_200": 105.0},  # below
    ]
    result = compute_breadth(rows)
    assert result == 60.0


def test_breadth_excludes_null_sma200():
    """sma_200 NULL 종목은 제외."""
    rows = [
        {"adj_close": 100.0, "sma_200": 90.0},   # above
        {"adj_close": 100.0, "sma_200": None},   # 제외
        {"adj_close": 100.0, "sma_200": 110.0},  # below
        {"adj_close": 100.0, "sma_200": None},   # 제외
    ]
    result = compute_breadth(rows)
    # 유효 2: above 1, below 1 → 50.0
    assert result == 50.0


def test_breadth_empty_universe():
    """0 종목 → None."""
    assert compute_breadth([]) is None
    assert compute_breadth([{"adj_close": 100.0, "sma_200": None}]) is None
