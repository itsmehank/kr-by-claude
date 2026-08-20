"""#114 P0 — 상폐 수정주가 생산: 격리 스키마 + 생산 모듈 단위 테스트."""
from datetime import date, timedelta

import pytest
from psycopg.types.json import Jsonb


def _d(i):
    return date(2024, 1, 1) + timedelta(days=i)


def test_delisted_adj_tables_roundtrip(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO delisted_adj_prices (ticker, date, adj_close) "
                    "VALUES ('999990', '2024-01-02', 1234.5)")
        cur.execute("INSERT INTO delisted_adj_quality "
                    "(ticker, chain_version, n_days, n_events, provenance, flags) "
                    "VALUES ('999990', 'v5', 1, 0, %s, %s)",
                    (Jsonb({"fric": 0}), Jsonb({"stkdp_unresolved": False})))
        cur.execute("SELECT adj_close::float FROM delisted_adj_prices "
                    "WHERE ticker='999990'")
        assert cur.fetchone() == (1234.5,)
        cur.execute("SELECT chain_version, flags->>'stkdp_unresolved' "
                    "FROM delisted_adj_quality WHERE ticker='999990'")
        assert cur.fetchone() == ("v5", "false")


def test_v3_events_prov_tags_and_wrapper_equivalence():
    from kr_pipeline.ohlcv.adj_reconstruct import v3_events, v3_events_prov
    # 대형 갭(주식수 정합) 1건 + 무상 detail 1건 + 유상 갭 detail 1건
    dates = [_d(i) for i in range(0, 20, 2)]
    closes = [(d, 10000.0) for d in dates[:3]] + [(d, 2000.0) for d in dates[3:]]
    shares = {d: (1_000_000 if d < dates[3] else 5_000_000) for d in dates}
    details = [
        {"endpoint": "fricDecsn", "record_date": dates[7], "ratio": 0.5,
         "method": None, "rcept_no": "20240101000001"},
    ]
    prov = v3_events_prov(closes, shares, details)
    assert [(d, r) for d, r, _ in prov] == v3_events(closes, shares, details)
    tags = {p for _, _, p in prov}
    assert "gap_share" in tags and "fric" in tags


def test_produce_delisted_adj_anchor_halt_and_flags():
    from kr_pipeline.ohlcv.delisted_adj import produce_delisted_adj
    # 5:1 병합 갭(주식수 정합 → 조정 유지) + 정지일(close=0) 1일
    dates = [_d(0), _d(1), _d(2), _d(3)]
    closes = [(_d(0), 2000.0), (_d(1), 0.0), (_d(2), 10000.0), (_d(3), 10100.0)]
    shares = {_d(0): 5_000_000, _d(1): 5_000_000, _d(2): 1_000_000,
              _d(3): 1_000_000}
    r = produce_delisted_adj(closes, shares, [], stkdp_unresolved=True)
    assert _d(1) not in r.adj                      # 정지일 미생산(nullify 관례)
    assert r.adj[_d(3)] == pytest.approx(10100.0)  # 최종일 앵커 = raw
    assert r.adj[_d(0)] == pytest.approx(10000.0)  # 과거 ×5 (gap_share 유지)
    assert r.provenance.get("gap_share", 0) == 1
    assert r.flags["stkdp_unresolved"] is True
    assert r.suppressed == []


def test_v5d_suppresses_fallback_gap_and_flags_liq_window():
    from kr_pipeline.ohlcv.adj_reconstruct import v3_events_prov
    from kr_pipeline.ohlcv.delisted_adj import produce_delisted_adj
    # 정리매매형 폭락(-50%, 주식수 비정합) — v5 는 fallback 이벤트, v5-d 는 보존
    closes = [(_d(0), 10000.0), (_d(1), 10000.0), (_d(2), 5000.0),
              (_d(3), 5000.0)]
    shares = {d: 1_000_000 for d, _ in closes}
    ev_v5 = v3_events_prov(closes, shares, [])
    assert [p for _, _, p in ev_v5] == ["gap_fallback"]
    assert v3_events_prov(closes, shares, [], use_gap_fallback=False) == []

    r = produce_delisted_adj(closes, shares, [])
    assert r.adj[_d(0)] == pytest.approx(10000.0)   # 폭락 보존(조정 미부여)
    assert r.adj[_d(2)] == pytest.approx(5000.0)
    assert r.suppressed == [(_d(2), pytest.approx(0.5), "gap_fallback")]
    assert r.flags["n_suppressed_gaps"] == 1
    assert r.flags["has_suppressed_upward_gap"] is False
    # 정리매매 창 = 마지막 관측일 전 14일(달력) — 여기선 전 구간이 창 안
    assert r.liq_window == {_d(0), _d(1), _d(2), _d(3)}
