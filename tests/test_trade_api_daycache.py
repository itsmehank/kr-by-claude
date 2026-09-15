# tests/test_trade_api_daycache.py
"""DayCache — KST 일 단위 캐시(#187 리뷰 추가 정리). 키에 today() 를 자동 포함해 자정 롤오버 시
전날 항목이 자연히 미스되는지, reset() 이 전부 비우는지만 순수 단위로 검증(DB·토스 접촉 없음)."""
from datetime import date

from trade_api.daycache import DayCache


def test_get_returns_none_for_unknown_key():
    cache = DayCache(today=lambda: date(2026, 9, 15))
    assert cache.get("limits", "005930") is None


def test_put_then_get_same_day_hits():
    cache = DayCache(today=lambda: date(2026, 9, 15))
    cache.put("limits", "005930", value="cached-value")
    assert cache.get("limits", "005930") == "cached-value"


def test_day_rollover_misses_previous_day_entry():
    today = {"d": date(2026, 9, 15)}
    cache = DayCache(today=lambda: today["d"])
    cache.put("commissions", value="rate-d")
    assert cache.get("commissions") == "rate-d"
    today["d"] = date(2026, 9, 16)   # 자정 경과
    assert cache.get("commissions") is None


def test_reset_clears_all_entries():
    cache = DayCache(today=lambda: date(2026, 9, 15))
    cache.put("limits", "005930", value="v1")
    cache.put("commissions", value="v2")
    cache.reset()
    assert cache.get("limits", "005930") is None
    assert cache.get("commissions") is None


def test_day_rollover_prunes_old_day_entries_on_put():
    """E(#187 최종 수정웨이브): put() 이 오늘 날짜가 아닌 키를 정리 — 전날 항목이 메모리에 남지 않는다."""
    today = {"d": date(2026, 9, 15)}
    cache = DayCache(today=lambda: today["d"])
    cache.put("limits", "005930", value="v1")
    today["d"] = date(2026, 9, 16)   # 자정 경과
    cache.put("commissions", value="v2")
    assert len(cache._items) == 1
