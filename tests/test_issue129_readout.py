"""#129 판독 스크립트의 순수 계수 함수 — DB 없이 합성 행으로 검증(리뷰 R1 반영)."""
from datetime import datetime, timezone

import pytest

from kr_pipeline.llm_runner.compute.pivot_continuity_stats import (
    downward_chains, pattern_round_trips, parse_log_events,
)


def _row(sym, day, pattern, pivot, cont, prev_pivot, prev_pattern, prev_day=None):
    at = datetime(2026, 9, day, tzinfo=timezone.utc)
    chg = None if pivot is None or prev_pivot in (None, 0) else round((pivot - prev_pivot) / prev_pivot * 100, 4)
    return {
        "symbol": sym, "classified_at": at, "analyzed_for_date": at.date(), "pattern": pattern,
        "pivot_price": pivot, "classification": "watch",
        "pc": {"base_continuity": cont, "prev_pivot_price": prev_pivot, "pivot_change_pct": chg,
               "prev_pattern": prev_pattern,
               "prev_classified_at": datetime(2026, 9, prev_day, tzinfo=timezone.utc).isoformat() if prev_day else None},
    }


def test_downward_chain_follows_rows_that_keep_lowered_pivot():
    # 049430 형: 23650 → 22050(하향) → 22050(same, Δ0) → 22050(same, Δ0) → 23450(복귀)
    rows = [
        _row("A", 1, "cup", 22050.0, "same", 23650.0, "cup"),
        _row("A", 7, "cup", 22050.0, "same", 22050.0, "cup"),
        _row("A", 14, "cup", 22050.0, "same", 22050.0, "cup"),
        _row("A", 26, "cup", 23450.0, "same", 22050.0, "cup"),
    ]
    chains = downward_chains(rows)
    assert len(chains) == 1
    start, old_pivot, members = chains[0]
    assert start is rows[0] and old_pivot == 23650.0
    assert [m["classified_at"].day for m in members] == [1, 7, 14]   # 복귀 행(26일)은 제외


def test_downward_chain_stops_on_base_change_and_dedups_nested_starts():
    rows = [
        _row("B", 1, "cup", 100.0, "same", 110.0, "cup"),     # 하향 1(old 110)
        _row("B", 5, "cup", 95.0, "near", 100.0, "cup"),      # 하향 2(old 100) — 1의 체인에도 포함
        _row("B", 9, "flat", 95.0, "different", 95.0, "cup"), # 베이스 변경 → 중단
    ]
    chains = downward_chains(rows)
    assert [(c[1], [m["classified_at"].day for m in c[2]]) for c in chains] == [(110.0, [1, 5]), (100.0, [5])]
    keys = {(m["symbol"], m["classified_at"]) for c in chains for m in c[2]}
    assert len(keys) == 2  # 평가 조회는 행 단위로 1회


def test_pattern_round_trips_only_true_consecutive_and_no_none():
    rows = [
        _row("C", 1, "cup", 10.0, "same", 10.0, "flat"),                  # prev=flat(직전 행 없음)
        _row("C", 8, "flat", 10.0, "same", 10.0, "cup", prev_day=1),      # flat→cup→flat: 왕복 1
        _row("C", 15, "none", None, "unknown", 10.0, "flat", prev_day=8), # none 개재 → 비계수
        _row("C", 22, "flat", 10.0, "unknown", None, "none", prev_day=15),
        _row("D", 1, "cup", 5.0, "same", 5.0, "double_bottom"),
        _row("D", 9, "double_bottom", 5.0, "same", 5.0, "cup", prev_day=5),  # 직전이 5일 행(미관측) → 연속 아님
    ]
    assert pattern_round_trips(rows) == 1


def test_parse_log_events_matches_same_base_lines_only():
    lines = [
        b"{\"message\": '[pivot-continuity] same-base pivot reread 049430: 23650.1 -> 22050.1 (-6.77%)'}\n",
        b"{\"message\": '[pivot-continuity] failed for 000000: boom'}\n",
        b"other\n",
    ]
    assert parse_log_events(lines) == {("049430", -6.77): 1}
