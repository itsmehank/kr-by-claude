from datetime import date, datetime
import pandas as pd
import pytest

import kr_pipeline.common.trading_calendar as tc


def _patch_fetch(monkeypatch, days, *, raises=False):
    def fake(index_code, start, end):
        if raises:
            raise RuntimeError("KRX timeout")
        return pd.DataFrame({"date": list(days), "close": [1] * len(days)})
    monkeypatch.setattr(tc, "fetch_index", fake)


def test_eltd_today_after_buffer(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 8), date(2026, 6, 9), date(2026, 6, 10)])
    assert tc.expected_latest_trading_day(datetime(2026, 6, 10, 18, 0)) == date(2026, 6, 10)


def test_eltd_today_before_buffer(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 8), date(2026, 6, 9), date(2026, 6, 10)])
    assert tc.expected_latest_trading_day(datetime(2026, 6, 10, 11, 0)) == date(2026, 6, 9)


def test_eltd_holiday(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 4), date(2026, 6, 5)])
    assert tc.expected_latest_trading_day(datetime(2026, 6, 6, 18, 0)) == date(2026, 6, 5)


def test_unavailable_on_empty(monkeypatch):
    monkeypatch.setattr(tc, "fetch_index", lambda *a, **k: pd.DataFrame())
    with pytest.raises(tc.TradingCalendarUnavailable):
        tc.expected_latest_trading_day(datetime(2026, 6, 10, 18, 0))


def test_unavailable_on_exception(monkeypatch):
    _patch_fetch(monkeypatch, [], raises=True)
    with pytest.raises(tc.TradingCalendarUnavailable):
        tc.expected_latest_trading_day(datetime(2026, 6, 10, 18, 0))


def test_assert_fresh_passes(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    tc.assert_data_fresh(date(2026, 6, 10), datetime(2026, 6, 10, 18, 0))


def test_assert_fresh_stale_raises(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    with pytest.raises(tc.StaleDataError):
        tc.assert_data_fresh(date(2026, 6, 9), datetime(2026, 6, 10, 18, 0))


def test_assert_fresh_calendar_unavailable_propagates(monkeypatch):
    _patch_fetch(monkeypatch, [], raises=True)
    with pytest.raises(tc.TradingCalendarUnavailable):
        tc.assert_data_fresh(date(2026, 6, 10), datetime(2026, 6, 10, 18, 0))
