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


def test_v5_stkdp_event_at_pre_close_session():
    from kr_pipeline.ohlcv.adj_reconstruct import v3_events
    # 결산 주식배당: 기준일 12/31(비거래일) → 락일 = 폐장일 직전 거래일.
    # 배율 = 1/(1+배당총수/발행총수) [ratio 필드 = 배당총수/발행총수].
    dates = [date(2019, 12, 26), date(2019, 12, 27), date(2019, 12, 30),
             date(2020, 1, 2), date(2020, 1, 3)]
    closes = [(d, 1000.0) for d in dates]
    shares = {d: 1_000_000 for d in dates}
    details = [{"endpoint": "stkdpDecsn", "record_date": date(2019, 12, 31),
                "ratio": 0.0294, "method": "주식배당", "rcept_no": "20191220800361"},
               # 주총 후 기재정정(접수일 > 기준일) — KRX 는 원공시 비율로 이미
               # 락 조정 완료 → 이벤트에서 제외돼야 함
               {"endpoint": "stkdpDecsn", "record_date": date(2019, 12, 31),
                "ratio": 0.0400, "method": "주식배당", "rcept_no": "20200328800021"}]
    assert v3_events(closes, shares, details,
                     use_stkdp=False) == []                  # v4.1 재현 경로
    ev = v3_events(closes, shares, details)                  # 동결 v5: 기본 on
    assert len(ev) == 1
    assert ev[0][0] == date(2019, 12, 27)                    # 폐장일(12/30) 직전
    assert ev[0][1] == pytest.approx(1 / 1.0294)             # 원공시 비율 채택


def test_v5_stkdp_mid_year_record_uses_fric_rule():
    from kr_pipeline.ohlcv.adj_reconstruct import v3_events
    # 비연말 기준일(3월 결산 등) — 무상 동형: 락일 = 기준일 직전 거래일
    dates = [date(2025, 3, 11), date(2025, 3, 12), date(2025, 3, 13),
             date(2025, 3, 14), date(2025, 3, 17)]
    closes = [(d, 1000.0) for d in dates]
    shares = {d: 1_000_000 for d in dates}
    details = [{"endpoint": "stkdpDecsn", "record_date": date(2025, 3, 14),
                "ratio": 0.02, "method": "주식배당", "rcept_no": "20250219800800"}]
    ev = v3_events(closes, shares, details, use_stkdp=True)
    assert ev == [(date(2025, 3, 13), pytest.approx(1 / 1.02))]


def test_v5_stkdp_halt_and_overlap_skip():
    from kr_pipeline.ohlcv.adj_reconstruct import v3_events
    # 정지 스팬(기준일-직전거래일 >7일) → F2 동형: 조정은 재개일에 배치
    dates = [date(2019, 12, 1), date(2019, 12, 2), date(2020, 1, 20)]
    closes = [(d, 1000.0) for d in dates]
    shares = {d: 1_000_000 for d in dates}
    details = [{"endpoint": "stkdpDecsn", "record_date": date(2019, 12, 31),
                "ratio": 0.03, "method": "주식배당", "rcept_no": "20191220800001"}]
    ev = v3_events(closes, shares, details, use_stkdp=True)
    assert ev == [(date(2020, 1, 20), pytest.approx(1 / 1.03))]
    # 대형 갭 이벤트(±3일)와 겹치면 대형 경로 전담 — detail 스킵
    dates2 = [date(2019, 12, 26), date(2019, 12, 27), date(2019, 12, 30),
              date(2020, 1, 2)]
    closes2 = [(dates2[0], 10000.0), (dates2[1], 5000.0),
               (dates2[2], 5000.0), (dates2[3], 5000.0)]
    shares2 = {d: 1_000_000 for d in dates2}
    ev2 = v3_events(closes2, shares2, [
        {"endpoint": "stkdpDecsn", "record_date": date(2019, 12, 31),
         "ratio": 0.03, "method": "주식배당", "rcept_no": "20191220800002"}],
        use_stkdp=True)
    assert all(abs(r - 1 / 1.03) > 1e-9 for _, r in ev2)


def test_v3_correction_dedup_and_halt_span():
    from kr_pipeline.ohlcv.adj_reconstruct import v3_events
    from datetime import timedelta
    # 정정 공시: 기준일이 8일 이동한 무상증자 2건 — 최신 접수 1건만 적용돼야 함
    d0 = _d(0)
    dates = [d0 + timedelta(days=i) for i in range(0, 40, 2)]  # 격일 거래
    closes = [(d, 1000.0) for d in dates]
    shares = {d: 1_000_000 for d in dates}
    details = [
        {"endpoint": "fricDecsn", "record_date": d0 + timedelta(days=10),
         "ratio": 1.0, "method": None, "rcept_no": "20260101000001"},
        {"endpoint": "fricDecsn", "record_date": d0 + timedelta(days=18),
         "ratio": 0.5, "method": None, "rcept_no": "20260105000001"},  # 정정(최신)
    ]
    ev = v3_events(closes, shares, details)
    assert len(ev) == 1
    assert ev[0][1] == pytest.approx(1 / 1.5)   # 최신 공시(0.5 배정) 채택

    # 정지 스팬: 기준일 직전 거래일이 20일 전 — 이벤트는 재개일(기준일 이후 첫 거래일)로
    dates2 = [_d(0), _d(2), _d(30), _d(32)]
    closes2 = [(d, 1000.0) for d in dates2]
    shares2 = {d: 1_000_000 for d in dates2}
    details2 = [{"endpoint": "fricDecsn", "record_date": _d(20), "ratio": 1.0,
                 "method": None, "rcept_no": "20260101000002"}]
    ev2 = v3_events(closes2, shares2, details2)
    assert ev2 == [(_d(30), pytest.approx(0.5))]
