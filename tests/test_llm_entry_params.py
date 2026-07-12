"""entry_params 러너 — 결정론 함수 경로 (#21: call_claude → calculate_entry_params).

echo 검증·UsageLimitError 는 LLM 은퇴와 함께 소멸. 거부(EntryParamsRejected)는
종목 단위 격리(run 루프 except) 를 검증한다.
"""
from datetime import date, datetime, timezone

import kr_pipeline.llm_runner.entry_params as ep


def _valid_payload(symbol="EPX1", name="테스트"):
    return {
        "symbol": symbol,
        "name": name,
        "prior_analysis": {
            "classification": "entry", "pattern": "flat_base", "pivot_price": 10000.0,
            "pivot_basis": "range_high", "base_high": 10000.0, "base_low": 9300.0,
            "base_depth_pct": 9.0, "risk_flags": [], "confidence": 0.8,
            "reasoning": "clean base",
        },
        "trigger_evaluation": {"trigger_type": "breakout", "decision": "go_now"},
        "current_state": {"close": 10010.0, "volume": 1_600_000, "avg_volume_50d": 1_000_000},
        "recent_daily_indicators": [],
    }


def test_process_one_deterministic_insert_and_meta(db, mocker):
    """함수 경로: LLM 미호출, insert 에 결정론 meta(model 표기·토큰 None) 전달."""
    mocker.patch.object(ep, "build_for_6", return_value=_valid_payload())
    insert = mocker.patch.object(ep, "insert_entry_params")
    notify = mocker.patch.object(ep, "notify_signal")

    ep._process_one(db, "EPX1", datetime(2026, 5, 20, 16, 32), None,
                    dry_run=False, as_of=date(2026, 5, 20))

    assert insert.call_count == 1
    kw = insert.call_args.kwargs
    assert kw["result"]["entry_mode"] == "pivot_breakout"
    assert kw["result"]["trigger_price"] == round(10000.0 * 1.001, 2)
    assert kw["llm_meta"]["model"].startswith("deterministic:")
    assert kw["llm_meta"]["input_tokens"] is None
    assert notify.call_count == 1
    assert notify.call_args.kwargs["entry_price"] == kw["result"]["trigger_price"]


def test_process_one_dry_run_validates_without_insert(db, mocker):
    mocker.patch.object(ep, "build_for_6", return_value=_valid_payload())
    insert = mocker.patch.object(ep, "insert_entry_params")
    notify = mocker.patch.object(ep, "notify_signal")

    ep._process_one(db, "EPX1", datetime(2026, 5, 20, 16, 32), None,
                    dry_run=True, as_of=date(2026, 5, 20))

    insert.assert_not_called()
    notify.assert_not_called()


def test_run_isolates_rejected_symbol_and_continues(db, mocker):
    """D2(a) 거부(pattern=none)는 해당 종목만 failed — 배치는 계속."""
    bad = _valid_payload("BAD1")
    bad["prior_analysis"]["pattern"] = "none"
    bad["prior_analysis"]["pivot_price"] = None
    good = _valid_payload("GOOD1")

    mocker.patch.object(ep, "_fetch_go_now_candidates", return_value=[
        ("BAD1", datetime(2026, 5, 20, 16, 32, tzinfo=timezone.utc), None),
        ("GOOD1", datetime(2026, 5, 20, 16, 33, tzinfo=timezone.utc), None),
    ])
    mocker.patch.object(ep, "build_for_6",
                        side_effect=lambda conn, s, evaluation_at: bad if s == "BAD1" else good)
    insert = mocker.patch.object(ep, "insert_entry_params")
    mocker.patch.object(ep, "notify_signal")

    out = ep.run(db, dry_run=False, as_of=date(2026, 5, 20))

    assert out == {"processed": 1, "failures": 1}
    assert insert.call_count == 1
    assert insert.call_args.kwargs["symbol"] == "GOOD1"


def test_fetch_go_now_candidates_filters_decisions(db):
    """go_now + breakout 계열만 후보 — wait/promotion 제외 (SQL 경로)."""
    as_of = date(2026, 5, 20)
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol LIKE 'EPQ%'")
        rows = [
            ("EPQ1", "breakout", "go_now"),
            ("EPQ2", "breakout", "wait"),
            ("EPQ3", "promotion", "go_now"),   # promotion 은 제외
            ("EPQ4", "breakout_from_watch", "go_now"),
        ]
        for i, (sym, tt, dec) in enumerate(rows):
            cur.execute(
                """INSERT INTO trigger_evaluation_log
                   (symbol, evaluated_at, analyzed_for_date, trigger_type, close, volume,
                    pivot_price, decision, confidence, reasoning, prior_classification_at)
                   VALUES (%s, %s, %s, %s, 100, 1, 99, %s, 0.8, 'x', %s)""",
                (sym, datetime(2026, 5, 20, 16, 30 + i, tzinfo=timezone.utc), as_of, tt, dec,
                 datetime(2026, 5, 17, 3, 0, tzinfo=timezone.utc)),
            )
    db.commit()
    try:
        got = sorted(s for s, _, _ in ep._fetch_go_now_candidates(db, as_of))
        assert got == ["EPQ1", "EPQ4"]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol LIKE 'EPQ%'")
        db.commit()
