# tests/test_no_handle_gates.py
# (#74) cup_without_handle 보수 장치 — strict 1.5× 인터셉트 + 보유 억제(dedupe).
# 준거: docs/superpowers/specs/2026-07-24-issue74-cup-without-handle.md §3·§5
# 체인 순서 = dedupe → extended(#45) → strict (F4 분모 오염 방지).
from datetime import date, datetime, timezone

import pytest


def _active_row(symbol, *, close, pivot=80.0, classification="entry",
                prev_close=79.0, watch_reason=None, pattern="cup_without_handle",
                volume=1_490_000, avg=1_000_000.0):
    return {
        "symbol": symbol, "close": close, "pivot_price": pivot,
        "volume": volume, "avg_volume_50d": avg,
        "stop_loss": 70.0, "sma_50": 78.0, "classification": classification,
        "prev_close": prev_close, "watch_reason": watch_reason,
        "pattern": pattern,
        "classified_at": datetime(2026, 7, 24, 3, tzinfo=timezone.utc),
    }


def _run_with(db, mocker, active, *, held=frozenset()):
    import kr_pipeline.llm_runner.evaluate_pivot as ev
    mocker.patch.object(ev, "get_active_with_current", return_value=active)
    mocker.patch.object(ev, "get_open_positions",
                        return_value=[{"symbol": s} for s in sorted(held)])
    llm_calls = []
    mocker.patch.object(
        ev, "_process_one",
        side_effect=lambda conn, a, trig, *, dry_run, as_of: llm_calls.append((a["symbol"], trig)),
    )
    result = ev.run(db, dry_run=False, as_of=date(2026, 7, 24))
    return result, llm_calls


def _cleanup(db, *symbols):
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol = ANY(%s)",
                    (list(symbols),))
    db.commit()


def _log_row(db, symbol):
    with db.cursor() as cur:
        cur.execute("SELECT decision, wait_reason, trigger_type, llm_model "
                    "FROM trigger_evaluation_log WHERE symbol=%s", (symbol,))
        return cur.fetchone()


# ---------- strict 1.5× ----------

def test_strict_blocks_no_handle_below_1_5x(db, mocker):
    """cup_without_handle + breakout + ratio 1.49 → LLM 미호출·결정론 wait."""
    _cleanup(db, "NH1")
    try:
        result, llm_calls = _run_with(db, mocker, [_active_row("NH1", close=83.0)])
        assert llm_calls == []
        assert result.get("strict_vol_blocked") == 1
        row = _log_row(db, "NH1")
        assert row is not None, "결정론 wait 행 미기록"
        assert row[0] == "wait" and row[1] == "volume_below_strict_no_handle"
        assert row[2] == "breakout" and row[3] is None
    finally:
        _cleanup(db, "NH1")


def test_strict_passes_at_exactly_1_5x(db, mocker):
    """ratio 1.5 정확히 = 통과(< 1.5 만 차단) → LLM 경로."""
    _cleanup(db, "NH2")
    result, llm_calls = _run_with(
        db, mocker, [_active_row("NH2", close=83.0, volume=1_500_000)])
    assert llm_calls == [("NH2", "breakout")]
    assert result.get("strict_vol_blocked", 0) == 0
    assert _log_row(db, "NH2") is None


def test_strict_not_applied_to_other_patterns(db, mocker):
    """cup_with_handle ratio 1.49 → 기존 경로(grace band 유지) — 비적용."""
    result, llm_calls = _run_with(
        db, mocker, [_active_row("NH3", close=83.0, pattern="cup_with_handle")])
    assert llm_calls == [("NH3", "breakout")]
    assert result.get("strict_vol_blocked", 0) == 0


def test_strict_unreachable_when_volume_data_missing(db, mocker):
    """avg_volume_50d 결측 → 발화 자체 없음(게이트가 volume≥avg 요구) —
    strict 인터셉트에 결측이 도달하는 경로가 없음을 고정(방어 분기는 belt).
    """
    result, llm_calls = _run_with(
        db, mocker, [_active_row("NH4", close=83.0, avg=None)])
    assert llm_calls == []
    assert result.get("strict_vol_blocked", 0) == 0
    assert _log_row(db, "NH4") is None


def test_extended_precedes_strict(db, mocker):
    """close 88(>1.05×80) + ratio 1.49 → extended 기록(strict 아님) — F4 오염 방지."""
    _cleanup(db, "NH5")
    try:
        result, llm_calls = _run_with(db, mocker, [_active_row("NH5", close=88.0)])
        assert llm_calls == []
        assert result.get("extended_blocked") == 1
        assert result.get("strict_vol_blocked", 0) == 0
        assert _log_row(db, "NH5")[1] == "extended_past_buy_range"
    finally:
        _cleanup(db, "NH5")


# ---------- dedupe (보유 억제) ----------

def test_held_symbol_upward_trigger_suppressed(db, mocker):
    """보유 티커의 breakout → 억제 행 기록 + LLM 미호출."""
    _cleanup(db, "NH6")
    try:
        result, llm_calls = _run_with(
            db, mocker, [_active_row("NH6", close=83.0, volume=2_000_000)],
            held={"NH6"})
        assert llm_calls == []
        assert result.get("position_suppressed") == 1
        row = _log_row(db, "NH6")
        assert row[0] == "wait" and row[1] == "suppressed_position_held"
    finally:
        _cleanup(db, "NH6")


def test_held_symbol_breakout_from_watch_and_promotion_suppressed(db, mocker):
    """상향 3종 전부 억제 — breakout_from_watch·promotion."""
    _cleanup(db, "NH7", "NH8")
    try:
        rows = [
            _active_row("NH7", close=83.0, classification="watch",
                        prev_close=79.0, watch_reason="valid_base_awaiting_breakout",
                        volume=2_000_000),
            _active_row("NH8", close=88.0, classification="watch",
                        prev_close=85.0, watch_reason="unfavorable_market",
                        pattern="flat_base", volume=2_000_000),
        ]
        result, llm_calls = _run_with(db, mocker, rows, held={"NH7", "NH8"})
        assert llm_calls == []
        assert result.get("position_suppressed") == 2
        # 발화 유형 고정 — NH7=breakout_from_watch(fresh cross), NH8=promotion
        # (회귀로 둘 다 bfw 로 변질되는 것 방지, 최종 리뷰 권고 5)
        assert _log_row(db, "NH7")[2] == "breakout_from_watch"
        assert _log_row(db, "NH8")[2] == "promotion"
    finally:
        _cleanup(db, "NH7", "NH8")


def test_held_symbol_invalidation_not_suppressed(db, mocker):
    """보유 티커의 invalidation(손절 신호)은 절대 억제 안 함 → LLM 경로."""
    row = _active_row("NH9", close=69.0, classification="entry",
                      prev_close=71.0, pattern="flat_base", volume=2_000_000)
    result, llm_calls = _run_with(db, mocker, [row], held={"NH9"})
    assert llm_calls == [("NH9", "invalidation")]
    assert result.get("position_suppressed", 0) == 0


def test_dedupe_precedes_extended(db, mocker):
    """보유 + close 88(extended 구간) → 억제 기록(extended 아님) — 체인 최선행."""
    _cleanup(db, "NHA")
    try:
        result, llm_calls = _run_with(
            db, mocker, [_active_row("NHA", close=88.0, volume=2_000_000)],
            held={"NHA"})
        assert llm_calls == []
        assert result.get("position_suppressed") == 1
        assert result.get("extended_blocked", 0) == 0
        assert _log_row(db, "NHA")[1] == "suppressed_position_held"
    finally:
        _cleanup(db, "NHA")
