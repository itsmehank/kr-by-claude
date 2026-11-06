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
