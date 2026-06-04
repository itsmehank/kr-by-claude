"""tests/test_pipeline_drift.py — 드리프트 감지/재적재."""
from datetime import date


def test_is_drift_identical_returns_false():
    from kr_pipeline.pipeline.drift import is_drift
    db = {date(2024, 1, 2): 50000.0, date(2024, 1, 3): 50500.0}
    krx = {date(2024, 1, 2): 50000.0, date(2024, 1, 3): 50500.0}
    assert is_drift(db, krx, rel_tol=0.01) is False


def test_is_drift_split_ratio_returns_true():
    """분할 후 adj_close 가 배수로 바뀌면 겹치는 날에서 상대차 큼 → True."""
    from kr_pipeline.pipeline.drift import is_drift
    db = {date(2024, 1, 2): 50000.0, date(2024, 1, 3): 50500.0}
    krx = {date(2024, 1, 2): 10000.0, date(2024, 1, 3): 10100.0}
    assert is_drift(db, krx, rel_tol=0.01) is True


def test_is_drift_tiny_float_noise_returns_false():
    from kr_pipeline.pipeline.drift import is_drift
    db = {date(2024, 1, 2): 50000.0}
    krx = {date(2024, 1, 2): 50000.4}
    assert is_drift(db, krx, rel_tol=0.01) is False


def test_is_drift_no_overlap_returns_false():
    from kr_pipeline.pipeline.drift import is_drift
    db = {date(2024, 1, 2): 50000.0}
    krx = {date(2024, 2, 2): 50000.0}
    assert is_drift(db, krx, rel_tol=0.01) is False
