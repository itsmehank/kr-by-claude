# tests/test_store_phase1_gate.py
"""insert_classification 이 gate 적용 후 triggered_rules 까지 저장."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from kr_pipeline.llm_runner.store import insert_classification


def _seed_ohlcv_deep_handle(db, ticker):
    """deep handle 발화하는 OHLCV 시드.

    구조: cup(6봉) + deep_handle(3봉).
    컵: 좌측 림→바닥(low 78, idx3)→우측 림(high 101>=100, idx5).
    핸들: 깊은 하락(low 82) → depth=(100-82)/100=18%, base 30% → ratio 0.6 > 0.33.
    classified_at 을 2026-01-20 으로 하면 base_start=2026-01-05 이후 9봉 커버.

    [plan 원본 시드 교체 사유]
    plan 초안의 시드는 right_rim 봉(high >= pivot)이 없어 cup_with_handle 구조가
    성립하지 않았고, handle_quality 게이트가 발화되지 않았다. cup_bottom→right_rim
    →handle 순서가 갖춰지도록 현재 구조(idx5 right_rim high 101 >= pivot 100)로 교체.
    """
    # cup bars: (high, low, close, volume)
    cup = [
        (95, 90, 92, 1000),   # idx0 좌측 림
        (93, 85, 87, 1000),   # idx1
        (88, 80, 82, 1000),   # idx2
        (85, 78, 80, 1000),   # idx3 컵 바닥 (low 78)
        (94, 88, 92, 1000),   # idx4 회복
        (101, 96, 99, 1000),  # idx5 우측 림 (high 101 >= pivot 100)
    ]
    # handle bars (after right rim): deep handle, low 82 → ratio_a = 18/30 = 0.6 > 0.33
    handle = [
        (99, 85, 86, 700),
        (97, 82, 84, 600),
        (98, 90, 96, 700),
    ]
    start = date(2026, 1, 5)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker,name,market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING",
            (ticker, ticker),
        )
        d = start
        for (h, l, c, v) in cup + handle:
            cur.execute(
                "INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, d, c, h, l, c, c, v, v * c),
            )
            cur.execute(
                "INSERT INTO daily_indicators (ticker,date,adj_close,sma_50,distribution_day_flag) "
                "VALUES (%s,%s,%s,%s,FALSE) ON CONFLICT DO NOTHING",
                (ticker, d, c, c * 0.95),
            )
            d += timedelta(days=1)


def test_entry_demoted_to_watch_persisted(db):
    """entry + handle_quality + extended → DB 에 watch + 2E_tier2 저장."""
    _seed_ohlcv_deep_handle(db, "STG2E")
    classified_at = datetime(2026, 1, 20, tzinfo=timezone.utc)
    result = {
        "classification": "entry", "confidence": 0.80,
        "risk_flags": ["extended_from_ma"], "pattern": "cup_with_handle",
        "pivot_price": 100.0, "pivot_basis": "handle_high",
        "base_high": 101.0, "base_low": 78.0, "base_depth_pct": 30.0,
        "base_start_date": date(2026, 1, 5), "reasoning": "test",
    }
    insert_classification(
        db, symbol="STG2E", classified_at=classified_at, market="KOSPI",
        result=result, source="weekend", llm_meta={},
    )
    with db.cursor() as cur:
        cur.execute(
            "SELECT classification, confidence, risk_flags, triggered_rules "
            "FROM weekly_classification WHERE symbol='STG2E'"
        )
        cls, conf, flags, tr = cur.fetchone()
    assert cls == "watch"
    assert float(conf) <= 0.50
    assert "handle_quality" in flags
    assert tr is not None and "2E_tier2" in tr


def test_no_gate_fire_triggered_rules_null(db):
    """handle_quality 미발화 (flat_base) → triggered_rules NULL, classification 무변경."""
    classified_at = datetime(2026, 2, 10, tzinfo=timezone.utc)
    result = {
        "classification": "watch", "confidence": 0.70,
        "risk_flags": ["unfavorable_market_context"], "pattern": "flat_base",
        "pivot_price": None, "pivot_basis": None,
        "base_high": None, "base_low": None, "base_depth_pct": None,
        "base_start_date": None, "reasoning": "test",
    }
    # stocks 먼저 (FK)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker,name,market) VALUES ('STGNULL','STGNULL','KOSPI') ON CONFLICT DO NOTHING"
        )
    insert_classification(
        db, symbol="STGNULL", classified_at=classified_at, market="KOSPI",
        result=result, source="weekend", llm_meta={},
    )
    with db.cursor() as cur:
        cur.execute(
            "SELECT classification, confidence, triggered_rules "
            "FROM weekly_classification WHERE symbol='STGNULL'"
        )
        cls, conf, tr = cur.fetchone()
    assert cls == "watch"
    assert float(conf) == 0.70
    assert tr is None, "미발화 시 triggered_rules 는 NULL"


def test_gate_failure_stores_ungated_classification(db, monkeypatch):
    """gate 내부 예외 → fail-soft: 게이트 미적용 원본 분류 저장 + triggered_rules NULL."""
    from kr_pipeline.llm_runner import gates as gates_mod

    def boom(*a, **k):
        raise ValueError("simulated compute failure")

    monkeypatch.setattr(gates_mod, "compute_handle_quality", boom)

    classified_at = datetime(2026, 3, 10, tzinfo=timezone.utc)
    result = {
        "classification": "entry", "confidence": 0.80,
        "risk_flags": ["extended_from_ma"], "pattern": "cup_with_handle",
        "pivot_price": 100.0, "pivot_basis": "handle_high",
        "base_high": 100.0, "base_low": 70.0, "base_depth_pct": 30.0,
        "base_start_date": date(2026, 1, 5), "reasoning": "test",
    }
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker,name,market) VALUES ('GFAIL','GFAIL','KOSPI') ON CONFLICT DO NOTHING"
        )
    insert_classification(
        db, symbol="GFAIL", classified_at=classified_at, market="KOSPI",
        result=result, source="weekend", llm_meta={},
    )
    with db.cursor() as cur:
        cur.execute(
            "SELECT classification, confidence, triggered_rules "
            "FROM weekly_classification WHERE symbol='GFAIL'"
        )
        cls, conf, tr = cur.fetchone()
    assert cls == "entry", "fail-soft: 게이트 미적용 원본 classification 보존"
    assert float(conf) == 0.80, "원본 confidence 보존"
    assert tr is None, "gate 실패 시 triggered_rules NULL"
