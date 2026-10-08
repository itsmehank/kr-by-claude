"""#109 entry 경로 시장 게이트 — evaluate_pivot 결정론 wait 체인 ④(① 보유 억제 → ② extended → ③ strict → ④ 시장 → LLM).
회신 2026-10-08 Q-J B·Q-M A: LLM 미호출 wait 행, wait_reason ∈ {market_gate, market_gate_null, market_gate_stale}."""
from datetime import date, datetime, timezone

import pytest

AS_OF = date(2026, 10, 7)


def _row(symbol, *, close=83.0, pivot=80.0, classification="entry", market="KOSPI", pattern=None,
         watch_reason=None, prev_close=79.0):
    return {"symbol": symbol, "close": close, "pivot_price": pivot, "volume": 2_000_000, "avg_volume_50d": 1_000_000.0,
            "stop_loss": 70.0, "sma_50": 78.0, "classification": classification, "prev_close": prev_close,
            "watch_reason": watch_reason, "market": market, "pattern": pattern,
            "classified_at": datetime(2026, 10, 3, 3, tzinfo=timezone.utc)}


def _mc(status, *, ftd=None, as_of=AS_OF):
    return {"as_of_date": as_of.isoformat() if as_of else None, "current_status": status,
            "distribution_day_count_last_25_sessions": 3, "last_follow_through_day": None if ftd is None else "2026-09-01",
            "days_since_follow_through": ftd, "pct_stocks_above_200d_ma": 40.0}


def _run(db, mocker, active, market_ctx):
    import kr_pipeline.llm_runner.evaluate_pivot as ev
    mocker.patch.object(ev, "get_active_with_current", return_value=active)
    mocker.patch.object(ev, "get_open_positions", return_value=[])
    calls = []
    mocker.patch.object(ev, "_process_one", side_effect=lambda conn, a, trig, *, dry_run, as_of: calls.append((a["symbol"], trig)))
    mctx = mocker.patch.object(ev, "build_market_context", side_effect=lambda conn, market, on_date: market_ctx[market])
    syms = [a["symbol"] for a in active]
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol = ANY(%s)", (syms,))
    result = ev.run(db, as_of=AS_OF)
    with db.cursor() as cur:
        cur.execute("SELECT symbol, decision, wait_reason, llm_call_duration_s, prompt_version FROM trigger_evaluation_log "
                    "WHERE symbol = ANY(%s) ORDER BY symbol", (syms,))
        rows = {r[0]: r[1:] for r in cur.fetchall()}
    return result, calls, rows, mctx


@pytest.mark.parametrize("status,ftd,reason", [
    ("downtrend", None, "market_gate"), ("correction", 3, "market_gate"), ("rally_attempt", None, "market_gate"),
])
def test_entry_breakout_blocked_by_market_without_llm(db, mocker, status, ftd, reason):
    result, calls, rows, _ = _run(db, mocker, [_row("MG1")], {"KOSPI": _mc(status, ftd=ftd)})
    assert calls == []
    assert rows["MG1"][:2] == ("wait", reason)
    assert result["market_gate_blocked"] == {"market_gate": 1, "market_gate_null": 0, "market_gate_stale": 0}


@pytest.mark.parametrize("status,ftd", [("confirmed_uptrend", None), ("rally_attempt", 10)])
def test_entry_breakout_passes_to_llm_when_market_ok(db, mocker, status, ftd):
    result, calls, rows, _ = _run(db, mocker, [_row("MG2")], {"KOSPI": _mc(status, ftd=ftd)})
    assert calls == [("MG2", "breakout")] and rows == {}
    assert sum(result["market_gate_blocked"].values()) == 0


def test_null_and_stale_reasons_and_rule7_equivalence(db, mocker):
    """행 부재 → market_gate_null, 직전일 대체 → market_gate_stale. 회신 7 동치: wait_reason IS NOT NULL ∧ llm_call_duration_s IS NULL."""
    market = {"KOSPI": _mc(None, as_of=None), "KOSDAQ": _mc("confirmed_uptrend", as_of=date(2026, 10, 6))}
    result, calls, rows, _ = _run(db, mocker, [_row("MG3", market="KOSPI"), _row("MG4", market="KOSDAQ")], market)
    assert calls == []
    assert rows["MG3"][1] == "market_gate_null" and rows["MG4"][1] == "market_gate_stale"
    for r in rows.values():
        assert r[1] is not None and r[2] is None and r[3] is None      # 결정론 wait 행 = LLM 미호출
    # 하루 전건이 null/stale 차단 → run warning(회신 Q-L ③·A)
    assert any(w.startswith("market_gate_data_missing_all") for w in result["warnings"]), result


def test_watch_breakout_and_downward_triggers_not_gated(db, mocker):
    """breakout_from_watch(watch §3.5 — 프롬프트 집행, #235)·invalidation·promotion 은 비대상."""
    active = [_row("MG5", classification="watch", watch_reason="unfavorable_market", prev_close=79.0),   # breakout_from_watch
              _row("MG6", close=69.0)]                                                                    # invalidation(close<stop)
    result, calls, rows, _ = _run(db, mocker, active, {"KOSPI": _mc("downtrend")})
    assert sorted(calls) == [("MG5", "breakout_from_watch"), ("MG6", "invalidation")]
    assert rows == {}


def test_chain_order_extended_and_strict_take_precedence(db, mocker):
    """④는 ②·③ 뒤 — 겹치면 앞 게이트 사유로 기록(#45·#74 사전등록 코호트 분모 불변, 과소 집계는 수용·명시)."""
    active = [_row("MG7", close=88.0),                                  # extended(88 > 80×1.05)
              _row("MG8", close=83.0, pattern="cup_without_handle")]    # strict 1.5× 미달(2.0? → 아래 volume 조정)
    active[1]["volume"] = 1_300_000                                     # 1.3× < 1.5×
    result, calls, rows, _ = _run(db, mocker, active, {"KOSPI": _mc("downtrend")})
    assert calls == []
    assert rows["MG7"][1] == "extended_past_buy_range" and rows["MG8"][1] == "volume_below_strict_no_handle"
    assert sum(result["market_gate_blocked"].values()) == 0


def test_market_context_fetched_once_per_market(db, mocker):
    result, calls, rows, mctx = _run(db, mocker, [_row("MG9"), _row("MGA"), _row("MGB", market="KOSDAQ")],
                                     {"KOSPI": _mc("downtrend"), "KOSDAQ": _mc("downtrend")})
    assert mctx.call_count == 2 and result["market_gate_blocked"]["market_gate"] == 3
    assert not any(w.startswith("market_gate_data_missing_all") for w in result.get("warnings", []))


def test_collect_stage_warnings_promotes_nested_lists():
    from kr_pipeline.llm_runner.run_status import collect_stage_warnings
    r = {"disqualify": {"processed": 1}, "evaluate": {"warnings": ["market_gate_data_missing_all: x"]}, "entry": {"warnings": []}}
    assert collect_stage_warnings(r) == ["market_gate_data_missing_all: x"]
    assert collect_stage_warnings({"warnings": ["a", "a"], "s": {"warnings": ["b"]}}) == ["a", "b"]
    assert collect_stage_warnings(None) == []
