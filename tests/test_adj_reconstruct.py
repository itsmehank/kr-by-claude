"""#114 §4.5 adj_reconstruct 단위 테스트 — 병합/무상증자 재구성 정합."""
from datetime import date, timedelta

import pytest

from kr_pipeline.ohlcv.adj_reconstruct import (
    db_factor_jumps, error_stats, factor_curve, match_events, reconstruct,
    share_events,
)


def _d(i):
    return date(2024, 1, 1) + timedelta(days=i)


def test_share_events_detects_merge_and_ignores_noise():
    dates = [_d(i) for i in range(4)]
    shares = {_d(0): 5_000_000, _d(1): 5_000_000, _d(2): 1_000_000,
              _d(3): 1_000_100}  # 5:1 병합 + 0.01% 미세 변동(무시)
    ev = share_events(dates, shares)
    assert len(ev) == 1
    assert ev[0][0] == _d(2)
    assert ev[0][1] == pytest.approx(5.0)


def test_reconstruct_merge_5to1():
    # 병합 전 raw 2,000원 → 병합 후 10,000원. 재구성 수정가 = 과거 ×5.
    closes = [(_d(0), 2000.0), (_d(1), 2000.0), (_d(2), 10000.0), (_d(3), 10100.0)]
    shares = {_d(0): 5_000_000, _d(1): 5_000_000, _d(2): 1_000_000,
              _d(3): 1_000_000}
    recon = reconstruct(closes, shares)
    assert recon[_d(0)] == pytest.approx(10000.0)
    assert recon[_d(1)] == pytest.approx(10000.0)
    assert recon[_d(2)] == pytest.approx(10000.0)
    assert recon[_d(3)] == pytest.approx(10100.0)


def test_error_stats_perfect_and_scaled():
    recon = {_d(0): 10000.0, _d(1): 10100.0}
    adj = {_d(0): 5000.0, _d(1): 5050.0}   # 앵커만 다르고 형태 동일 → 오차 0
    st = error_stats(recon, adj)
    assert st["n"] == 2
    assert st["max"] == pytest.approx(0.0, abs=1e-9)


def test_db_jumps_and_matching():
    closes = [(_d(0), 2000.0), (_d(1), 2000.0), (_d(2), 10000.0)]
    adj = {_d(0): 10000.0, _d(1): 10000.0, _d(2): 10000.0}
    jumps = db_factor_jumps(closes, adj)          # factor 5→5→1: 점프 1건
    assert len(jumps) == 1 and jumps[0][0] == _d(2)
    m = match_events(jumps, [(_d(2), 5.0)])
    assert m == {"db_jumps": 1, "matched": 1, "missed_big": 0, "missed_small": 0}
    m2 = match_events(jumps, [])
    assert m2["missed_big"] == 1


def test_v3_events_fric_and_3rd_party():
    from kr_pipeline.ohlcv.adj_reconstruct import v3_events
    # 무상증자 100%: 기준일 _d(3) → 권리락일 = 직전 거래일 _d(2), 배율 0.5
    closes = [(_d(0), 10000.0), (_d(1), 10000.0), (_d(2), 5000.0), (_d(3), 5000.0)]
    shares = {_d(0): 1_000_000, _d(1): 1_000_000, _d(2): 1_000_000,
              _d(3): 1_000_000}
    details = [
        {"endpoint": "fricDecsn", "record_date": _d(3), "ratio": 1.0, "method": None},
        {"endpoint": "piicDecsn", "record_date": _d(3), "ratio": 0.2,
         "method": "제3자배정증자"},           # 3자배정 → 제외돼야 함
    ]
    ev = v3_events(closes, shares, details)
    assert ev == [(_d(2), pytest.approx(0.5))]
