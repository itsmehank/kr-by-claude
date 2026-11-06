# tests/test_issue175_readout.py
"""#175 저장본 재현 readout 의 순수 비교 함수(SELECT 없음)."""
from kr_pipeline.llm_runner.compute.handle_low_readout import compare_fired_rows, fired_transition


def test_compare_fired_rows_flags_start_and_end_changes():
    stored = {"handle_start": "2026-07-21", "handle_high": 100.1, "handle_end": "2026-07-24"}
    new = {"handle_start": "2026-07-21", "handle_high": 100.1, "handle_end": "2026-07-25"}
    assert compare_fired_rows(stored, new) == {"start_match": True, "high_match": True, "end_changed": True}


def test_compare_fired_rows_detects_start_shift():
    stored = {"handle_start": "2026-07-21", "handle_high": 100.1, "handle_end": "2026-07-24"}
    new = {"handle_start": "2026-07-18", "handle_high": 100.0, "handle_end": "2026-07-24"}
    assert compare_fired_rows(stored, new) == {"start_match": False, "high_match": False, "end_changed": False}


def test_fired_transition_labels_2x2():
    assert fired_transition(True, True) == "fired→fired"
    assert fired_transition(True, False) == "fired→not"
    assert fired_transition(False, True) == "not→fired"
    assert fired_transition(None, False) == "legacy_none→not"


def test_legacy_window_end_uses_utc_date_for_live_rows():
    """리뷰 R1-2: 구 규칙 재현의 실전 행 창 끝은 classified_at 의 **UTC** 날짜(세션 tz 무관). 금 21:00 UTC = 토 06:00 KST → UTC 날짜 = 금."""
    from datetime import date, datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    from kr_pipeline.llm_runner.compute.handle_low_readout import legacy_window_end
    cat_kst = datetime(2026, 6, 13, 6, 0, tzinfo=ZoneInfo("Asia/Seoul"))        # psycopg 가 세션 tz 로 돌려준 꼴
    assert legacy_window_end(cat_kst, None, "weekly_classification") == date(2026, 6, 12)
    assert legacy_window_end(cat_kst, date(2026, 6, 12), "weekly_classification") == date(2026, 6, 12)
    assert legacy_window_end(datetime(2026, 8, 11, tzinfo=timezone.utc), date(2020, 8, 14), "backtest_classification") == date(2020, 8, 15)
