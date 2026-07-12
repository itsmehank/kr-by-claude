"""insert_classification — analyzed_for_date 인자 동작."""
from datetime import date, datetime, timezone


def test_insert_classification_with_analyzed_for_date(db):
    """analyzed_for_date 인자가 DB 컬럼에 저장됨."""
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='STRA'")
    db.commit()

    insert_classification(
        db,
        symbol="STRA",
        classified_at=datetime.now(timezone.utc),
        market="KOSPI",
        result={
            "classification": "watch",
            "pattern": "flat_base",
            "pivot_price": 1000.0,
            "pivot_basis": "high_of_base",
            "base_high": 1000.0,
            "base_low": 900.0,
            "base_depth_pct": 10.0,
            "base_start_date": "2026-03-01",
            "risk_flags": [],
            "confidence": 0.5,
            "reasoning": "test",
        },
        source="weekend",
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
        analyzed_for_date=date(2026, 5, 18),
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT analyzed_for_date FROM weekly_classification WHERE symbol='STRA'"
        )
        row = cur.fetchone()
    assert row[0] == date(2026, 5, 18)


def test_insert_classification_default_analyzed_for_date_is_null(db):
    """analyzed_for_date 인자 안 주면 컬럼 NULL."""
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='STRB'")
    db.commit()

    insert_classification(
        db,
        symbol="STRB",
        classified_at=datetime.now(timezone.utc),
        market="KOSDAQ",
        result={
            "classification": "ignore",
            "pattern": "none",
            "pivot_price": None,
            "pivot_basis": None,
            "base_high": None,
            "base_low": None,
            "base_depth_pct": None,
            "base_start_date": None,
            "risk_flags": [],
            "confidence": 0.8,
            "reasoning": "test",
        },
        source="daily_delta",
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute(
            "SELECT analyzed_for_date FROM weekly_classification WHERE symbol='STRB'"
        )
        row = cur.fetchone()
    assert row[0] is None


def test_measurements_column_exists_and_stores(db):
    """measurements JSONB 컬럼에 LLM 측정 블록 저장."""
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='MEAS'")
    db.commit()

    insert_classification(
        db, symbol="MEAS", classified_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
        market="KOSPI",
        result={
            "classification": "watch", "pattern": "cup_with_handle", "confidence": 0.6,
            "reasoning": "x", "risk_flags": [], "pivot_price": None, "pivot_basis": None,
            "base_high": None, "base_low": None, "base_depth_pct": None, "base_start_date": None,
            "measurements": {"cup_depth_pct": 30.0, "prior_uptrend_pct": 40.0, "cup_shape": "U"},
        },
        source="weekend", llm_meta={},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute("SELECT measurements FROM weekly_classification WHERE symbol='MEAS'")
        row = cur.fetchone()
    assert row[0]["cup_shape"] == "U"
    assert row[0]["cup_depth_pct"] == 30.0


def _s9_result(**over):
    r = {
        "entry_mode": "pivot_breakout", "pivot_price": 192.50, "trigger_price": 192.69,
        "current_price": 192.30, "stop_loss_price": 178.96,
        "stop_loss_pct_from_pivot": -7.0, "stop_loss_pct_from_current_price": -6.9,
        "suggested_weight_pct": 10.0, "expected_target_price": 231.00, "expected_target_pct": 20.0,
        "pattern_basis": "flat_base", "entry_window_days": 3, "max_chase_pct_from_pivot": 5.0,
        "breakout_volume_requirement": "ge_1.4x_50day_avg", "observed_breakout_volume_ratio": None,
        "known_warnings": [], "other_warnings": "", "notes": "n",
    }
    r.update(over)
    return r


def test_normalize_entry_params_maps_and_derives():
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    n = _normalize_entry_params(_s9_result())
    assert n["stop_loss"] == 178.96
    assert n["position_size_pct"] == 10.0
    assert n["entry_price"] == 192.69
    assert round(n["risk_reward_ratio"], 2) == round(20.0 / 6.9, 2)
    assert n["stop_loss_basis"] is None and n["position_size_basis"] is None
    assert n["pivot_price"] == 192.50 and n["current_price"] == 192.30
    assert n["pattern_basis"] == "flat_base" and n["entry_window_days"] == 3
    assert n["max_chase_pct_from_pivot"] == 5.0
    assert n["observed_breakout_volume_ratio"] is None


def test_normalize_entry_params_missing_field_raises():
    import pytest
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    bad = _s9_result()
    del bad["stop_loss_price"]
    with pytest.raises(ValueError, match="schema drift"):
        _normalize_entry_params(bad)


def test_normalize_entry_params_rr_zero_and_overflow():
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    assert _normalize_entry_params(_s9_result(stop_loss_pct_from_current_price=0))["risk_reward_ratio"] is None
    assert _normalize_entry_params(_s9_result(stop_loss_pct_from_current_price=-0.01))["risk_reward_ratio"] is None


# --- D-3: entry_params 가격/부호 sanity 검증 (HARD=거부, SOFT=경고) ---

def test_sanity_rejects_stop_at_or_above_entry():
    """손절가 ≥ 진입가(trigger) → 매수계획 깨짐 → ValueError(거부)."""
    import pytest
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    # entry_price = trigger_price = 192.69. stop 을 그 위로.
    with pytest.raises(ValueError, match="sanity"):
        _normalize_entry_params(_s9_result(stop_loss_price=200.0))
    with pytest.raises(ValueError, match="sanity"):
        _normalize_entry_params(_s9_result(stop_loss_price=192.69))  # ==entry → 즉시손절


def test_sanity_rejects_target_at_or_below_entry():
    """목표가 ≤ 진입가 → 이익 없음 → 거부."""
    import pytest
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    with pytest.raises(ValueError, match="sanity"):
        _normalize_entry_params(_s9_result(expected_target_price=150.0))
    with pytest.raises(ValueError, match="sanity"):
        _normalize_entry_params(_s9_result(expected_target_price=192.69))


def test_sanity_rejects_nonpositive_price():
    """가격 ≤ 0 → 거부."""
    import pytest
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    for over in (dict(pivot_price=0), dict(stop_loss_price=-1.0), dict(current_price=0.0),
                 dict(trigger_price=-5.0), dict(expected_target_price=0)):
        with pytest.raises(ValueError, match="sanity"):
            _normalize_entry_params(_s9_result(**over))


def test_sanity_rejects_wrong_sign_pct():
    """stop_pct 양수 / target_pct ≤ 0 → 부호 오류 → 거부(rr 도 보호)."""
    import pytest
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    with pytest.raises(ValueError, match="sanity"):
        _normalize_entry_params(_s9_result(stop_loss_pct_from_pivot=3.0))
    with pytest.raises(ValueError, match="sanity"):
        _normalize_entry_params(_s9_result(stop_loss_pct_from_current_price=2.0))
    with pytest.raises(ValueError, match="sanity"):
        _normalize_entry_params(_s9_result(expected_target_pct=-5.0))


def test_sanity_soft_range_warns_but_keeps():
    """책 범위 이탈(방향은 맞음) → 거부 아님, known_warnings 에 sanity_ 마커."""
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    n = _normalize_entry_params(_s9_result(suggested_weight_pct=30.0))  # [3,25] 초과
    assert any(w.startswith("sanity_") for w in n["known_warnings"])


def test_sanity_skips_none_values():
    """미제공(None)은 비교 불가 → 검사 skip(거부 안 함). scope=주어진 값의 정합성."""
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    n = _normalize_entry_params(_s9_result(expected_target_price=None, expected_target_pct=None))
    assert n["expected_target_price"] is None  # 통과(예외 없음)


def test_sanity_valid_params_pass_clean():
    """정상 계획은 거부도 경고도 없음."""
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    n = _normalize_entry_params(_s9_result())
    assert not any(w.startswith("sanity_") for w in n["known_warnings"])


def test_insert_entry_params_roundtrip_s9(db):
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_entry_params
    now = datetime(2026, 6, 7, 1, 0, tzinfo=timezone.utc)
    insert_entry_params(
        db, symbol="RTRIP", signal_at=now, result=_s9_result(),
        trigger_evaluation_at=now, prior_classification_at=now,
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
    )
    # No db.commit(): same-connection INSERT is visible to the SELECT below; committing would break auto-rollback isolation.
    with db.cursor() as cur:
        cur.execute("""SELECT entry_price, stop_loss, position_size_pct, risk_reward_ratio,
                              pivot_price, current_price, pattern_basis, entry_window_days, max_chase_pct_from_pivot
                         FROM entry_params WHERE symbol='RTRIP' AND signal_at=%s""", (now,))
        row = cur.fetchone()
    assert row is not None
    assert float(row[0]) == 192.69
    assert float(row[1]) == 178.96
    assert float(row[2]) == 10.0
    assert round(float(row[3]), 2) == round(20.0/6.9, 2)
    assert float(row[4]) == 192.50 and float(row[5]) == 192.30
    assert row[6] == "flat_base" and row[7] == 3 and float(row[8]) == 5.0


def test_mock_calculate_entry_params_passes_normalize():
    from kr_pipeline.llm_runner.llm.claude_cli import _mock_calculate_entry_params
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    m = _mock_calculate_entry_params()
    n = _normalize_entry_params(m)            # §9 keys present → no ValueError
    assert n["entry_price"] == m["trigger_price"]
    assert n["stop_loss"] == m["stop_loss_price"]
    assert "stop_loss" not in m and "suggested_weight_pct" in m  # §9 keys, not code keys


def test_insert_disqualification(db):
    """시스템 강등 행 — classification='disqualified', source='system_disqualify'."""
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_disqualification
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='DQ1'")
    insert_disqualification(db, symbol="DQ1", classified_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
                            market="KOSPI")
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT classification, source, reasoning FROM weekly_classification WHERE symbol='DQ1'")
        row = cur.fetchone()
    assert row[0] == "disqualified"
    assert row[1] == "system_disqualify"
    assert row[2] is not None


def test_normalize_entry_params_other_warnings_list_serialized():
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    n = _normalize_entry_params(_s9_result(other_warnings=["climax_run", "wide_spread"]))
    assert n["other_warnings"] == '["climax_run", "wide_spread"]'   # list → JSON 문자열(TEXT 컬럼)
    s = _normalize_entry_params(_s9_result(other_warnings="plain"))
    assert s["other_warnings"] == "plain"                            # 문자열은 그대로


def test_risk_flags_taxonomy_has_15():
    from kr_pipeline.llm_runner.risk_flags import RISK_FLAGS_TAXONOMY
    # 15종: 기존 14 + topping_distribution(§6.2 force-ignore, 2026-06-13)
    assert len(RISK_FLAGS_TAXONOMY) == 15
    assert "climax_run" in RISK_FLAGS_TAXONOMY and "handle_quality" in RISK_FLAGS_TAXONOMY
    assert "topping_distribution" in RISK_FLAGS_TAXONOMY


def test_validate_classification():
    from kr_pipeline.llm_runner.store import _validate_classification
    import pytest
    assert _validate_classification({"classification": "entry"}) == "entry"
    assert _validate_classification({"classification": "watch"}) == "watch"
    for bad in ({"classification": "buy"}, {}, {"classification": None}):
        with pytest.raises(ValueError, match="invalid classification"):
            _validate_classification(bad)


def test_validate_decision():
    from kr_pipeline.llm_runner.store import _validate_decision
    import pytest
    assert _validate_decision({"decision": "go_now"}) == "go_now"
    for bad in ({"decision": "maybe"}, {}, {"decision": None}):
        with pytest.raises(ValueError, match="invalid decision"):
            _validate_decision(bad)


def test_clean_risk_flags():
    from kr_pipeline.llm_runner.store import _clean_risk_flags
    assert _clean_risk_flags(["climax_run", "bogus", "narrow_base"]) == ["climax_run", "narrow_base"]
    assert _clean_risk_flags([]) == []
    assert _clean_risk_flags(None) == []
    assert _clean_risk_flags("climax_run") == []


def test_insert_classification_rejects_invalid(mocker):
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_classification
    import pytest
    conn = mocker.MagicMock()
    with pytest.raises(ValueError, match="invalid classification"):
        insert_classification(
            conn, symbol="X", classified_at=datetime(2026,6,7,tzinfo=timezone.utc),
            market="KOSPI", result={"classification": "buy"},
            source="daily_delta", llm_meta={},
        )
    conn.cursor.assert_not_called()


def test_insert_backfill_classification_rejects_invalid(mocker):
    from datetime import datetime, timezone, date
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    import pytest
    conn = mocker.MagicMock()
    now = datetime(2026,6,7,tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="invalid classification"):
        insert_backfill_classification(
            conn, symbol="X", classified_at=now, market="KOSPI",
            result={"classification": "buy"}, source="backfill", llm_meta={},
            analyzed_for_date=date(2026,6,7),
        )
    conn.cursor.assert_not_called()


def test_insert_trigger_log_rejects_invalid_decision(mocker):
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_trigger_log
    import pytest
    conn = mocker.MagicMock()
    now = datetime(2026,6,7,tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="invalid decision"):
        insert_trigger_log(
            conn, symbol="X", evaluated_at=now, trigger_type="breakout",
            close=100.0, volume=1000, pivot_price=99.0,
            result={}, prior_classification_at=now, llm_meta={},
        )
    conn.cursor.assert_not_called()


def test_measurements_json_merges_contraction():
    import json
    from kr_pipeline.llm_runner.store import _measurements_json
    out = json.loads(_measurements_json({
        "measurements": {"cup_depth_pct": 30.0},
        "contraction_count": 4,
        "contraction_depths_pct": [25.0, 14.0, 8.0, 4.0],
    }))
    assert out["cup_depth_pct"] == 30.0
    assert out["contraction_count"] == 4
    assert out["contraction_depths_pct"] == [25.0, 14.0, 8.0, 4.0]


def test_measurements_json_measurements_only_unchanged():
    import json
    from kr_pipeline.llm_runner.store import _measurements_json
    out = json.loads(_measurements_json({"measurements": {"cup_depth_pct": 30.0}}))
    assert out == {"cup_depth_pct": 30.0}


def test_measurements_json_none_when_empty():
    from kr_pipeline.llm_runner.store import _measurements_json
    assert _measurements_json({}) is None
    assert _measurements_json({"measurements": None}) is None


def test_measurements_json_contraction_only():
    import json
    from kr_pipeline.llm_runner.store import _measurements_json
    out = json.loads(_measurements_json({"contraction_count": 3, "contraction_depths_pct": [20.0, 10.0, 5.0]}))
    assert out == {"contraction_count": 3, "contraction_depths_pct": [20.0, 10.0, 5.0]}


def test_measurements_json_non_dict_measurements():
    import json
    from kr_pipeline.llm_runner.store import _measurements_json
    out = json.loads(_measurements_json({"measurements": "oops", "contraction_count": 2}))
    assert out == {"contraction_count": 2}


def test_insert_classification_stores_contraction_in_measurements(db):
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_classification
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='CONTRACT'")
    db.commit()
    insert_classification(
        db, symbol="CONTRACT", classified_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
        market="KOSPI",
        result={
            "classification": "watch", "pattern": "vcp", "confidence": 0.6,
            "reasoning": "x", "risk_flags": [],
            "pivot_price": None, "pivot_basis": None, "base_high": None,
            "base_low": None, "base_depth_pct": None, "base_start_date": None,
            "measurements": {"prior_uptrend_pct": 40.0},
            "contraction_count": 4,
            "contraction_depths_pct": [25.0, 14.0, 8.0, 4.0],
        },
        source="weekend", llm_meta={},
    )
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT measurements FROM weekly_classification WHERE symbol='CONTRACT'")
        m = cur.fetchone()[0]
    assert m["prior_uptrend_pct"] == 40.0
    assert m["contraction_count"] == 4
    assert m["contraction_depths_pct"] == [25.0, 14.0, 8.0, 4.0]


# ====== P1-2 Part A: 분류 가격 sanity 검증 ======

def _cls_result(**over):
    """유효한 분류 result 기본형 (HARD 통과값)."""
    r = {
        "classification": "watch", "pattern": "flat_base", "confidence": 0.6,
        "reasoning": "t", "risk_flags": [], "pivot_price": 1000.0,
        "pivot_basis": "high_of_base", "base_high": 1000.0, "base_low": 900.0,
        "base_depth_pct": 10.0, "base_start_date": None,
    }
    r.update(over)
    return r


def _gates_identity(mocker):
    """게이트를 identity 로 patch — 검증 로직만 단위 테스트."""
    mocker.patch(
        "kr_pipeline.llm_runner.store.apply_phase1_gates",
        side_effect=lambda conn, s, t, r: (r, None),
    )


def test_sanity_warnings_column_exists(db):
    """P1-2 Part A: weekly_classification.sanity_warnings JSONB 컬럼 존재."""
    with db.cursor() as cur:
        cur.execute("""
            SELECT data_type FROM information_schema.columns
             WHERE table_name = 'weekly_classification' AND column_name = 'sanity_warnings'
        """)
        row = cur.fetchone()
    assert row is not None, "sanity_warnings 컬럼 없음 — schema.sql ALTER 미적용"
    assert row[0] == "jsonb"


def test_classification_hard_rejects_impossible_prices(db, mocker):
    """HARD: 구조적으로 불가능한 가격은 ValueError + 행 미생성 (fail-closed).

    오염된 pivot 하나가 평일 트리거 게이트(close>pivot)를 매일 오발화시키므로
    저장 자체를 거부한다. 미저장 시 다음 사이클 재분류로 자연 복구.
    """
    import pytest
    from kr_pipeline.llm_runner.store import insert_classification

    _gates_identity(mocker)
    cases = [
        ({"pivot_price": -100.0}, "pivot_price"),
        ({"pivot_price": 0}, "pivot_price"),
        ({"base_high": -1.0}, "base_high"),
        ({"base_low": 1000.0, "base_high": 900.0}, "base_low"),      # low >= high
        ({"base_low": 950.0, "pivot_price": 900.0}, "base_low"),      # low > pivot
        ({"confidence": 1.5}, "confidence"),
        ({"confidence": -0.1}, "confidence"),
    ]
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='SANH'")
    db.commit()

    for over, needle in cases:
        with pytest.raises(ValueError, match=needle):
            insert_classification(
                db, symbol="SANH", classified_at=datetime.now(timezone.utc),
                market="KOSPI", result=_cls_result(**over),
                source="weekend", llm_meta={},
            )
        db.rollback()

    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM weekly_classification WHERE symbol='SANH'")
        assert cur.fetchone()[0] == 0, "HARD 위반 분류가 저장됨 (fail-closed 깨짐)"


def test_classification_valid_prices_saved_without_warnings(db, mocker):
    """정상값: 저장되고 sanity_warnings 는 NULL. NULL 가격(ignore)도 HARD 통과."""
    from kr_pipeline.llm_runner.store import insert_classification

    _gates_identity(mocker)
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol IN ('SANOK','SANNUL')")
    db.commit()

    insert_classification(
        db, symbol="SANOK", classified_at=datetime.now(timezone.utc),
        market="KOSPI", result=_cls_result(), source="weekend", llm_meta={},
    )
    insert_classification(
        db, symbol="SANNUL", classified_at=datetime.now(timezone.utc),
        market="KOSPI",
        result=_cls_result(classification="ignore", pivot_price=None, base_high=None,
                           base_low=None, confidence=None),
        source="weekend", llm_meta={},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute("SELECT sanity_warnings FROM weekly_classification WHERE symbol='SANOK'")
        assert cur.fetchone()[0] is None
        cur.execute("SELECT sanity_warnings FROM weekly_classification WHERE symbol='SANNUL'")
        assert cur.fetchone()[0] is None


def test_classification_soft_pivot_far_from_price(db, mocker):
    """SOFT: pivot 이 최근 종가의 밴드(0.3~3.0배) 밖 → 저장 + 경고 마커."""
    _gates_identity(mocker)
    as_of = date(2026, 6, 26)
    _seed_close(db, "SANFAR", 1000, as_of)
    # pivot 5000 = 종가의 5배 (밴드 상한 3.0 초과) — 자릿수 오류 의심
    w = _insert_and_get_warnings(
        db, "SANFAR",
        _cls_result(pivot_price=5000.0, base_high=5000.0, base_low=4500.0),
        as_of,
    )
    assert w is not None and "sanity_pivot_far_from_price" in w


def test_classification_soft_clean_pivot_no_warning(db, mocker):
    """SOFT: pivot 이 종가 근방(밴드 내) → 경고 없음(NULL)."""
    _gates_identity(mocker)
    as_of = date(2026, 6, 26)
    _seed_close(db, "SANNEAR", 1000, as_of)
    w = _insert_and_get_warnings(
        db, "SANNEAR",
        _cls_result(pivot_price=1010.0, base_high=1010.0),
        as_of,
    )
    assert w is None


def test_classification_soft_missing_pivot_for_entry(db, mocker):
    """SOFT: entry 인데 pivot 없음 → 저장 + 경고 (watch 는 pivot NULL 정상이라 비대상)."""
    from kr_pipeline.llm_runner.store import insert_classification

    _gates_identity(mocker)
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='SANNOPV'")
    db.commit()

    insert_classification(
        db, symbol="SANNOPV", classified_at=datetime.now(timezone.utc),
        market="KOSPI",
        result=_cls_result(classification="entry", pivot_price=None,
                           base_high=None, base_low=None),
        source="weekend", llm_meta={},
    )
    db.commit()

    with db.cursor() as cur:
        cur.execute("SELECT sanity_warnings FROM weekly_classification WHERE symbol='SANNOPV'")
        w = cur.fetchone()[0]
    assert w is not None and "sanity_missing_pivot_for_actionable" in w


# ====== (#23) §8.5 밴드 정합 · §4.7 pivot 산술 사후검증 (SOFT) ======

def _seed_close(db, symbol, close, as_of):
    """sanity 비교 종가 시드 — store 는 daily_prices(payload 와 동일 권위 소스)를 읽는다."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s,'S','KOSPI') ON CONFLICT DO NOTHING",
            (symbol,),
        )
        cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (symbol,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (symbol,))
        cur.execute(
            """INSERT INTO daily_prices
               (ticker, date, open, high, low, close, adj_close, volume, value)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 1000, 1000)""",
            (symbol, as_of, close, close, close, close, close),
        )
    db.commit()


def _insert_and_get_warnings(db, symbol, result, as_of):
    from kr_pipeline.llm_runner.store import insert_classification

    insert_classification(
        db, symbol=symbol, classified_at=datetime.now(timezone.utc),
        market="KOSPI", result=result, source="weekend", llm_meta={},
        analyzed_for_date=as_of,
    )
    db.commit()
    with db.cursor() as cur:
        cur.execute(
            "SELECT sanity_warnings FROM weekly_classification WHERE symbol=%s",
            (symbol,),
        )
        return cur.fetchone()[0]


def test_band_entry_above_band_warns(db, mocker):
    """§8.5: entry 인데 close > pivot×1.05 (추격 한계 초과 = extended 였어야) → 경고."""
    _gates_identity(mocker)
    as_of = date(2026, 6, 26)
    _seed_close(db, "SANB1", 1100, as_of)  # pos 1.1 > 1.05
    w = _insert_and_get_warnings(
        db, "SANB1",
        _cls_result(classification="entry", pivot_price=1000.1, base_high=1000.0),
        as_of,
    )
    assert w is not None and "sanity_band_mismatch_entry" in w


def test_band_entry_below_band_not_warned_pocket_pivot(db, mocker):
    """§8.5: entry 하단(pos<0.95)은 §4.5 pocket pivot(base 내부 진입)이 정당 —
    구분 불가라 미경고 (#38 리뷰: 상단 위반만 검사)."""
    _gates_identity(mocker)
    as_of = date(2026, 6, 26)
    _seed_close(db, "SANB6", 900, as_of)  # pos 0.9
    w = _insert_and_get_warnings(
        db, "SANB6",
        _cls_result(classification="entry", pivot_price=1000.1, base_high=1000.0),
        as_of,
    )
    assert w is None or not any("sanity_band" in x for x in w)


def test_band_ignores_stray_watch_reason_on_non_watch(db, mocker):
    """비-watch 의 잔류 watch_reason 은 저장 정규화(_watch_reason)처럼 무시 —
    오경고 금지 (#38 리뷰)."""
    _gates_identity(mocker)
    as_of = date(2026, 6, 26)
    _seed_close(db, "SANB7", 1000, as_of)  # pos ~1.0 (extended 라면 경고 위치)
    r = _cls_result(classification="ignore", pivot_price=1000.1, base_high=1000.0,
                    confidence=0.9)
    r["watch_reason"] = "extended"
    w = _insert_and_get_warnings(db, "SANB7", r, as_of)
    assert w is None or not any("sanity_band" in x for x in w)


def test_band_valid_base_requires_below_band(db, mocker):
    """§8.5: valid_base_awaiting_breakout 인데 close 가 pivot×0.95 이상 → 경고."""
    _gates_identity(mocker)
    as_of = date(2026, 6, 26)
    _seed_close(db, "SANB2", 1000, as_of)  # ratio ~1.0
    r = _cls_result(pivot_price=1000.1, base_high=1000.0)
    r["watch_reason"] = "valid_base_awaiting_breakout"
    w = _insert_and_get_warnings(db, "SANB2", r, as_of)
    assert w is not None and "sanity_band_mismatch_valid_base" in w


def test_band_extended_requires_above_band(db, mocker):
    """§8.5: extended 인데 close 가 pivot×1.05 이하 → 경고. 초과면 무경고."""
    _gates_identity(mocker)
    as_of = date(2026, 6, 26)
    _seed_close(db, "SANB3", 1000, as_of)
    r = _cls_result(pivot_price=1000.1, base_high=1000.0)
    r["watch_reason"] = "extended"
    w = _insert_and_get_warnings(db, "SANB3", r, as_of)
    assert w is not None and "sanity_band_mismatch_extended" in w

    _seed_close(db, "SANB4", 1100, as_of)  # ratio ~1.1 > 1.05 — 정합
    r2 = _cls_result(pivot_price=1000.1, base_high=1000.0)
    r2["watch_reason"] = "extended"
    w2 = _insert_and_get_warnings(db, "SANB4", r2, as_of)
    assert w2 is None or not any("sanity_band" in x for x in w2)


def test_band_entry_inside_no_warning(db, mocker):
    """§8.5: entry 이고 밴드 내(0.95~1.05) → 밴드 경고 없음."""
    _gates_identity(mocker)
    as_of = date(2026, 6, 26)
    _seed_close(db, "SANB5", 990, as_of)  # ratio ~0.99
    w = _insert_and_get_warnings(
        db, "SANB5",
        _cls_result(classification="entry", pivot_price=1000.1, base_high=1000.0),
        as_of,
    )
    assert w is None or not any("sanity_band" in x for x in w)


def test_pivot_above_base_high_warns_for_table_basis(db, mocker):
    """§4.7: 표 기반 basis(handle_high 등)는 anchor ≤ base_high — 초과 pivot 경고.
    (pocket pivot 예외는 basis 가 표 밖이라 비대상 — HARD 미검사 사유 보존)"""
    _gates_identity(mocker)
    as_of = date(2026, 6, 26)
    _seed_close(db, "SANP1", 1050, as_of)
    r = _cls_result(pivot_price=1100.1, base_high=1000.0, pivot_basis="handle_high")
    w = _insert_and_get_warnings(db, "SANP1", r, as_of)
    assert w is not None and "sanity_pivot_above_base_high" in w


def test_pivot_offset_rule_warns_on_wrong_fraction(db, mocker):
    """§4.7: +0.1 규칙 패턴에서 정수 앵커인데 pivot 소수부 ≠ 0.1 → 경고."""
    _gates_identity(mocker)
    as_of = date(2026, 6, 26)
    _seed_close(db, "SANP2", 990, as_of)
    r = _cls_result(pivot_price=1000.5, base_high=1000.0, pivot_basis="range_high")
    w = _insert_and_get_warnings(db, "SANP2", r, as_of)
    assert w is not None and "sanity_pivot_offset_rule" in w


def test_pivot_offset_rule_clean(db, mocker):
    """§4.7: pivot = 정수 앵커 + 0.1 → 경고 없음. 비-표 basis 도 비대상."""
    _gates_identity(mocker)
    as_of = date(2026, 6, 26)
    _seed_close(db, "SANP3", 990, as_of)
    r = _cls_result(pivot_price=1000.1, base_high=1000.0, pivot_basis="range_high")
    w = _insert_and_get_warnings(db, "SANP3", r, as_of)
    assert w is None or not any("sanity_pivot_" in x for x in w)


def test_pivot_offset_rule_skips_non_range_high_basis(db, mocker):
    """§4.7 오프셋 검사는 앵커 값을 아는 range_high(== base_high)만 — handle_high 등은
    앵커가 base_high 와 다른 가격이라 정수성 프록시가 성립 안 함 (#38 리뷰)."""
    _gates_identity(mocker)
    as_of = date(2026, 6, 26)
    _seed_close(db, "SANP4", 990, as_of)
    # 앵커(handle_high)=999.4 가 소수인 정당한 pivot 999.5 — base_high 는 정수 1000
    r = _cls_result(pivot_price=999.5, base_high=1000.0, pivot_basis="handle_high")
    w = _insert_and_get_warnings(db, "SANP4", r, as_of)
    assert w is None or "sanity_pivot_offset_rule" not in w
