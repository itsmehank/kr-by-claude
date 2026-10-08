"""#109 entry 경로 트리거 당일 시장 게이트 — 순수 함수(회신 2026-10-08 Q-J B·Q-L·A 판정).

판정: downtrend/correction 무조건 차단, rally_attempt 는 최근 FTD(경과일 ≤ STATUS_FTD_RECENT_DAYS) 없으면 차단,
confirmed_uptrend 는 통과(분배일 무관 — Q-L ①). 시장 행 부재·미지 상태 → market_gate_null, 직전일 대체 → market_gate_stale(보수 차단).
"""
from datetime import date

import pytest

from kr_pipeline.common.market_gate import (
    REASON_MARKET_GATE, REASON_MARKET_GATE_NULL, REASON_MARKET_GATE_STALE, entry_market_gate, force_watch,
)
from kr_pipeline.common.thresholds import STATUS_FTD_RECENT_DAYS as R

D = date(2026, 10, 7)


@pytest.mark.parametrize("status,ftd,blocked,reason", [
    ("confirmed_uptrend", None, False, None),
    ("confirmed_uptrend", 5, False, None),
    ("confirmed_uptrend", R + 10, False, None),        # 분배일·FTD 경과와 무관하게 통과(Q-L ①)
    ("downtrend", 1, True, REASON_MARKET_GATE),          # FTD 가 최근이어도 무조건 차단
    ("downtrend", None, True, REASON_MARKET_GATE),
    ("correction", 3, True, REASON_MARKET_GATE),
    ("correction", None, True, REASON_MARKET_GATE),
    ("rally_attempt", 0, False, None),
    ("rally_attempt", R, False, None),                   # 경계 = 최근(≤)
    ("rally_attempt", R + 1, True, REASON_MARKET_GATE),  # 만료 FTD
    ("rally_attempt", None, True, REASON_MARKET_GATE),   # FTD 부재·경과일 미산출 = 보수
])
def test_status_by_ftd_matrix(status, ftd, blocked, reason):
    r = entry_market_gate(current_status=status, days_since_ftd=ftd, as_of_date=D, trigger_date=D)
    assert (r.blocked, r.reason) == (blocked, reason)


@pytest.mark.parametrize("status", ["confirmed_uptrend", "rally_attempt", "downtrend", "correction"])
def test_stale_market_row_is_blocked_regardless_of_status(status):
    """당일 행 없이 직전일로 대체(as_of_date < 판정일) → 상태와 무관하게 보수 차단(회신 A)."""
    r = entry_market_gate(current_status=status, days_since_ftd=1, as_of_date=date(2026, 10, 6), trigger_date=D)
    assert (r.blocked, r.reason) == (True, REASON_MARKET_GATE_STALE)


@pytest.mark.parametrize("status,as_of", [
    (None, None),                    # 시장 행 부재
    ("confirmed_uptrend", None),     # 날짜 미상 = 행 부재 취급
    (None, D),                       # 상태 결측
    ("bull_market", D),              # 미지 상태값 — 통과로 단정하지 않음
])
def test_missing_or_unknown_market_is_null_block(status, as_of):
    r = entry_market_gate(current_status=status, days_since_ftd=5, as_of_date=as_of, trigger_date=D)
    assert (r.blocked, r.reason) == (True, REASON_MARKET_GATE_NULL)


def test_null_takes_precedence_over_stale():
    r = entry_market_gate(current_status=None, days_since_ftd=None, as_of_date=date(2026, 10, 1), trigger_date=D)
    assert r.reason == REASON_MARKET_GATE_NULL


def test_force_watch_is_shared_with_classification_layer():
    """분류층 §3.5(payload_builder._market_direction_gate)와 같은 함수 — 규칙 사본 금지(회신: '분류층 force_watch 재사용')."""
    from api.services import payload_builder
    for status in ("confirmed_uptrend", "rally_attempt", "downtrend", "correction"):
        for ftd in (None, 0, R, R + 1):
            mc = {"current_status": status, "distribution_day_count_last_25_sessions": 2,
                  "last_follow_through_day": None if ftd is None else "2026-09-01", "days_since_follow_through": ftd}
            assert payload_builder._market_direction_gate(mc)["force_watch"] == force_watch(status, ftd, has_last_ftd=ftd is not None)
    assert force_watch(None, 5) is None and force_watch("bull_market", 5) is None


def test_pure_function_has_no_db_or_clock_access():
    import inspect
    import kr_pipeline.common.market_gate as m
    src = inspect.getsource(m)
    for forbidden in ("psycopg", "conn", "date.today", "datetime.now", "import os"):
        assert forbidden not in src, forbidden
