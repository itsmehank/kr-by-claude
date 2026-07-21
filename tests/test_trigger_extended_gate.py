# tests/test_trigger_extended_gate.py
# (#45) extended 상한 게이트 — 결정 3′: extended 일은 LLM 없이 결정론 wait 기록.
# 준거: docs/superpowers/plans/2026-07-21-issue45-extended-gate.md
from datetime import date, datetime, timezone

import pytest


def test_wait_reason_column_exists(db):
    """(#45) trigger_evaluation_log.wait_reason VARCHAR 컬럼 존재."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT data_type FROM information_schema.columns
             WHERE table_name = 'trigger_evaluation_log' AND column_name = 'wait_reason'
            """
        )
        row = cur.fetchone()
    assert row is not None, "wait_reason 컬럼 없음 — schema.sql ALTER 미적용"
    assert row[0] == "character varying"


def _insert_log(db, symbol, *, wait_reason=None, decision="wait",
                close=88.0, pivot=80.0,
                evaluated_at=None, prior_at=None, analyzed_for_date=None):
    from kr_pipeline.llm_runner.store import insert_trigger_log
    insert_trigger_log(
        db, symbol=symbol,
        evaluated_at=evaluated_at or datetime(2026, 7, 21, 7, tzinfo=timezone.utc),
        trigger_type="breakout", close=close, volume=2_000_000, pivot_price=pivot,
        result={"decision": decision, "confidence": None,
                "reasoning": "t", "abort_reason": None},
        prior_classification_at=prior_at or datetime(2026, 7, 19, 3, tzinfo=timezone.utc),
        llm_meta={}, analyzed_for_date=analyzed_for_date or date(2026, 7, 21),
        wait_reason=wait_reason,
    )


def test_insert_trigger_log_stores_wait_reason(db):
    """insert_trigger_log 의 wait_reason 파라미터가 컬럼으로 관통 저장 (기본 None)."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol IN ('WR1','WR2')")
    db.commit()
    _insert_log(db, "WR1", wait_reason="extended_past_buy_range")
    _insert_log(db, "WR2")
    db.commit()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT symbol, wait_reason FROM trigger_evaluation_log "
                "WHERE symbol IN ('WR1','WR2') ORDER BY symbol"
            )
            rows = dict(cur.fetchall())
        assert rows == {"WR1": "extended_past_buy_range", "WR2": None}
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol IN ('WR1','WR2')")
        db.commit()


# ====== T2: evaluate_pivot 결정론 인터셉트 ======

def _active_row(symbol, *, close, pivot=80.0, classification="entry",
                prev_close=79.0, watch_reason=None):
    return {
        "symbol": symbol, "close": close, "pivot_price": pivot,
        "volume": 2_000_000, "avg_volume_50d": 1_000_000.0,
        "stop_loss": 70.0, "sma_50": 78.0, "classification": classification,
        "prev_close": prev_close, "watch_reason": watch_reason,
        "classified_at": datetime(2026, 7, 19, 3, tzinfo=timezone.utc),
    }


def _run_with(db, mocker, active, *, dry_run=False):
    import kr_pipeline.llm_runner.evaluate_pivot as ev
    mocker.patch.object(ev, "get_active_with_current", return_value=active)
    llm_calls = []
    mocker.patch.object(
        ev, "_process_one",
        side_effect=lambda conn, a, trig, *, dry_run, as_of: llm_calls.append((a["symbol"], trig)),
    )
    result = ev.run(db, dry_run=dry_run, as_of=date(2026, 7, 21))
    return result, llm_calls


def test_extended_breakout_records_deterministic_wait(db, mocker):
    """breakout 인데 close > pivot×1.05 → LLM 미호출 + 결정론 wait 행 기록.

    close=88, pivot=80 (ratio 1.10). 기록 요건: decision='wait',
    wait_reason='extended_past_buy_range', llm_model NULL(LLM 비관여),
    close/pivot 보존(사후 pivot 재판독 감사용).
    """
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXT1'")
    db.commit()
    try:
        result, llm_calls = _run_with(db, mocker, [_active_row("EXT1", close=88.0)])
        assert llm_calls == [], f"extended 인데 LLM 경로 호출됨: {llm_calls}"
        assert result.get("extended_blocked") == 1
        with db.cursor() as cur:
            cur.execute(
                "SELECT decision, wait_reason, trigger_type, close, pivot_price, llm_model "
                "FROM trigger_evaluation_log WHERE symbol='EXT1'"
            )
            row = cur.fetchone()
        assert row is not None, "결정론 wait 행 미기록"
        decision, wait_reason, trig, close, pivot, llm_model = row
        assert decision == "wait"
        assert wait_reason == "extended_past_buy_range"
        assert trig == "breakout"
        assert float(close) == 88.0 and float(pivot) == 80.0
        assert llm_model is None
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXT1'")
        db.commit()


def test_non_extended_breakout_goes_to_llm(db, mocker):
    """close=83 (ratio 1.0375 ≤ 1.05) → 기존 LLM 경로 그대로, 결정론 행 없음."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXT2'")
    db.commit()
    result, llm_calls = _run_with(db, mocker, [_active_row("EXT2", close=83.0)])
    assert llm_calls == [("EXT2", "breakout")]
    assert result.get("extended_blocked", 0) == 0
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM trigger_evaluation_log WHERE symbol='EXT2'")
        assert cur.fetchone()[0] == 0


def test_extended_boundary_exact_multiple_not_blocked(db, mocker):
    """경계: close == pivot×1.05 정확히 → 차단 아님 (§8.5 와 동일한 초과 조건)."""
    result, llm_calls = _run_with(db, mocker, [_active_row("EXT3", close=84.0)])
    assert llm_calls == [("EXT3", "breakout")]
    assert result.get("extended_blocked", 0) == 0


def test_extended_promotion_not_intercepted(db, mocker):
    """promotion 은 인터셉트 비대상 (§3.3 이 go_now 전면 금지 — 매수 위험 0).

    watch + close=88 > pivot×1.05, prev_close=85 > pivot 라 fresh_cross 아님
    → 게이트는 promotion 반환 → LLM 경로 유지.
    """
    row = _active_row("EXT4", close=88.0, classification="watch",
                      prev_close=85.0, watch_reason="unfavorable_market")
    result, llm_calls = _run_with(db, mocker, [row])
    assert llm_calls == [("EXT4", "promotion")]
    assert result.get("extended_blocked", 0) == 0


def test_extended_breakout_from_watch_intercepted(db, mocker):
    """breakout_from_watch 갭업(prev 79→88, pivot 80)도 인터셉트 — 갭업 추격 차단."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXT5'")
    db.commit()
    try:
        row = _active_row("EXT5", close=88.0, classification="watch",
                          prev_close=79.0, watch_reason="valid_base_awaiting_breakout")
        result, llm_calls = _run_with(db, mocker, [row])
        assert llm_calls == []
        assert result.get("extended_blocked") == 1
        with db.cursor() as cur:
            cur.execute(
                "SELECT trigger_type, wait_reason FROM trigger_evaluation_log WHERE symbol='EXT5'"
            )
            assert cur.fetchone() == ("breakout_from_watch", "extended_past_buy_range")
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXT5'")
        db.commit()


def test_extended_dry_run_no_insert(db, mocker):
    """dry_run: 결정론 wait 도 기록하지 않음 (무부작용 미리보기 관례 보존)."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXT6'")
    db.commit()
    result, llm_calls = _run_with(db, mocker, [_active_row("EXT6", close=88.0)],
                                  dry_run=True)
    assert llm_calls == []
    assert result.get("extended_blocked") == 1
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM trigger_evaluation_log WHERE symbol='EXT6'")
        assert cur.fetchone()[0] == 0


# ====== T3: 복귀일 extension 이력 payload 주입 ======

def _run_real_process(db, mocker, active):
    """_process_one 실경로 — build_for_5b·call_claude 만 대체, payload 캡처."""
    import kr_pipeline.llm_runner.evaluate_pivot as ev
    mocker.patch.object(ev, "get_active_with_current", return_value=active)
    mocker.patch.object(ev, "build_for_5b",
                        side_effect=lambda conn, s, trigger_type, as_of: {"base": "x"})
    captured = {}
    def fake_call(prompt_file, attachments, payload_inline, dry_run, meta_out):
        captured.update(payload_inline)
        return {"decision": "wait", "confidence": 0.5,
                "reasoning": "t", "abort_reason": None}
    mocker.patch.object(ev, "call_claude", side_effect=fake_call)
    ev.run(db, dry_run=False, as_of=date(2026, 7, 21))
    return captured


def test_return_day_payload_includes_extension_history(db, mocker):
    """차단 이력 있는 종목의 복귀일 LLM 평가 payload 에 extension_history 3종 주입.

    이력: 07-19(88, +10%)·07-20(86, +7.5%) 차단 → 오늘 83(비-extended) 복귀.
    기대: max_extension_pct=10.0, days_extended=2,
    return_day_volume_ratio=2.0 (volume 2M / avg 1M).
    """
    from datetime import timedelta
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXH1'")
    db.commit()
    prior_at = datetime(2026, 7, 19, 3, tzinfo=timezone.utc)
    for i, close in enumerate((88.0, 86.0)):
        _insert_log(db, "EXH1", wait_reason="extended_past_buy_range", close=close,
                    evaluated_at=datetime(2026, 7, 19, 7, tzinfo=timezone.utc)
                    + timedelta(days=i),
                    prior_at=prior_at,
                    analyzed_for_date=date(2026, 7, 19) + timedelta(days=i))
    db.commit()
    try:
        payload = _run_real_process(db, mocker, [_active_row("EXH1", close=83.0)])
        assert "extension_history" in payload, f"이력 미주입: {payload}"
        h = payload["extension_history"]
        assert h["days_extended"] == 2
        assert h["max_extension_pct"] == 10.0
        assert h["return_day_volume_ratio"] == 2.0
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXH1'")
        db.commit()


def test_no_history_payload_unchanged(db, mocker):
    """차단 이력 없는 종목은 payload 무변경 (기존 경로 보존)."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXH2'")
    db.commit()
    try:
        payload = _run_real_process(db, mocker, [_active_row("EXH2", close=83.0)])
        assert "extension_history" not in payload
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXH2'")
        db.commit()


def test_extended_block_marks_done_for_same_day(db, mocker):
    """결정론 wait 행도 멱등 가드에 잡혀 같은 날 재실행 시 재기록·재평가 없음."""
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXT7'")
    db.commit()
    try:
        _run_with(db, mocker, [_active_row("EXT7", close=88.0)])
        result2, llm_calls2 = _run_with(db, mocker, [_active_row("EXT7", close=88.0)])
        assert llm_calls2 == []
        assert result2.get("extended_blocked") == 0, "같은 날 재실행이 중복 차단 기록"
        with db.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trigger_evaluation_log WHERE symbol='EXT7'")
            assert cur.fetchone()[0] == 1
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXT7'")
        db.commit()


def test_abort_skip_precedes_extended_gate(db, mocker):
    """현재 분류에 abort 가 있으면 extended 게이트 이전에 skip — wait 행 미기록."""
    from datetime import timedelta
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXT8'")
    db.commit()
    row = _active_row("EXT8", close=88.0)
    _insert_log(db, "EXT8", decision="abort",
                evaluated_at=datetime(2026, 7, 20, 7, tzinfo=timezone.utc),
                prior_at=row["classified_at"],
                analyzed_for_date=date(2026, 7, 20))
    db.commit()
    try:
        result, llm_calls = _run_with(db, mocker, [row])
        assert llm_calls == []
        assert result.get("extended_blocked") == 0
        assert result.get("abort_skipped") == 1
        with db.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM trigger_evaluation_log "
                "WHERE symbol='EXT8' AND wait_reason IS NOT NULL"
            )
            assert cur.fetchone()[0] == 0, "abort 된 분류에 wait 행이 기록됨"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXT8'")
        db.commit()


def test_extension_history_excludes_future_blocks_on_replay(db, mocker):
    """(F-1) force-replay 로 과거 as_of 를 재평가할 때 as_of 이후의 차단 행은
    이력에서 제외 — look-ahead 차단 (payload_lite 의 evaluated_at 상한과 동일 규율).

    이력: 07-19·07-20 차단 + 07-22(미래) 차단. as_of=07-21 재생 시
    days_extended=2 (07-22 행 미포함).
    """
    from datetime import timedelta
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXH3'")
    db.commit()
    prior_at = datetime(2026, 7, 19, 3, tzinfo=timezone.utc)
    for i, close in enumerate((88.0, 86.0)):
        _insert_log(db, "EXH3", wait_reason="extended_past_buy_range", close=close,
                    evaluated_at=datetime(2026, 7, 19, 7, tzinfo=timezone.utc)
                    + timedelta(days=i),
                    prior_at=prior_at,
                    analyzed_for_date=date(2026, 7, 19) + timedelta(days=i))
    # 미래(07-22) 차단 행 — 07-21 재생의 payload 에 새면 look-ahead
    _insert_log(db, "EXH3", wait_reason="extended_past_buy_range", close=90.0,
                evaluated_at=datetime(2026, 7, 22, 7, tzinfo=timezone.utc),
                prior_at=prior_at, analyzed_for_date=date(2026, 7, 22))
    db.commit()
    try:
        payload = _run_real_process(db, mocker, [_active_row("EXH3", close=83.0)])
        assert "extension_history" in payload
        h = payload["extension_history"]
        assert h["days_extended"] == 2, f"미래 차단 행이 이력에 새어듦: {h}"
        assert h["max_extension_pct"] == 10.0, f"미래 행(+12.5%)이 최대치 오염: {h}"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='EXH3'")
        db.commit()
