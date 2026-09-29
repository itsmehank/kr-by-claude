"""#207 회신 20 (ii) — 09-28 이후 거래량 정의 미확정 표지 + 트립와이어 (4) 경고형."""
from datetime import date, datetime, timezone

import pytest

from kr_pipeline.common.data_regimes import (
    BACKTEST_EXCLUDED_FROM, VOLUME_REGIME_TAG, VOLUME_REGIME_UNVERIFIED_FROM, volume_regime_warnings,
)


def test_constants_and_helper():
    assert VOLUME_REGIME_UNVERIFIED_FROM == date(2026, 9, 28) == BACKTEST_EXCLUDED_FROM
    assert VOLUME_REGIME_TAG == "volume_regime_unverified_#207"
    assert volume_regime_warnings(None) == []
    assert volume_regime_warnings(date(2026, 9, 23)) == []
    assert volume_regime_warnings(date(2026, 9, 28)) == [VOLUME_REGIME_TAG]
    assert volume_regime_warnings(date(2026, 10, 1)) == [VOLUME_REGIME_TAG]


def _cls_result():
    return {"classification": "watch", "pattern": "flat_base", "pivot_price": 1000.0,
            "pivot_basis": "high_of_base", "base_high": 1000.0, "base_low": 900.0,
            "base_depth_pct": 10.0, "base_start_date": "2026-03-01", "risk_flags": [],
            "confidence": 0.5, "reasoning": "test"}


@pytest.mark.parametrize("as_of,tagged", [(date(2026, 9, 23), False), (date(2026, 9, 28), True)])
def test_insert_classification_tags_rows_on_or_after_boundary(db, as_of, tagged):
    from kr_pipeline.llm_runner.store import insert_classification
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='VRTAG'")
    insert_classification(db, symbol="VRTAG", classified_at=datetime.now(timezone.utc), market="KOSPI",
                          result=_cls_result(), source="weekend",
                          llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
                          analyzed_for_date=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT sanity_warnings FROM weekly_classification WHERE symbol='VRTAG'")
        w = cur.fetchone()[0]
    assert (VOLUME_REGIME_TAG in (w or [])) is tagged


@pytest.mark.parametrize("as_of,tagged", [(date(2026, 9, 23), False), (date(2026, 9, 28), True)])
def test_insert_trigger_log_tags(db, as_of, tagged):
    from kr_pipeline.llm_runner.store import insert_trigger_log
    now = datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='VRTRG'")
    insert_trigger_log(db, symbol="VRTRG", evaluated_at=now, trigger_type="breakout",
                              close=1010.0, volume=100000, pivot_price=1000.0,
                              result={"decision": "wait", "confidence": 0.5, "reasoning": "t"},
                              prior_classification_at=now,
                              llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
                              analyzed_for_date=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT sanity_warnings FROM trigger_evaluation_log WHERE symbol='VRTRG'")
        w = cur.fetchone()[0]
    assert (VOLUME_REGIME_TAG in (w or [])) is tagged


def _s9_result():
    return {
        "entry_mode": "breakout", "pivot_price": 192.50, "trigger_price": 192.69, "current_price": 192.30,
        "stop_loss_price": 178.96, "stop_loss_pct_from_pivot": -7.0, "stop_loss_pct_from_current_price": -6.9,
        "suggested_weight_pct": 10.0, "expected_target_price": 231.0, "expected_target_pct": 20.0,
        "pattern_basis": "flat_base", "entry_window_days": 3, "max_chase_pct_from_pivot": 5.0,
        "breakout_volume_requirement": "ge_1.5x_50day_avg", "observed_breakout_volume_ratio": 1.8,
        "known_warnings": [], "other_warnings": None, "notes": None,
    }


@pytest.mark.parametrize("as_of,tagged", [(date(2026, 9, 23), False), (date(2026, 9, 28), True)])
def test_insert_entry_params_tags_known_warnings(db, as_of, tagged):
    from kr_pipeline.llm_runner.store import insert_entry_params
    now = datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("DELETE FROM entry_params WHERE symbol='VRENT'")
    insert_entry_params(db, symbol="VRENT", signal_at=now, result=_s9_result(),
                        trigger_evaluation_at=now, prior_classification_at=now,
                        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
                        analyzed_for_date=as_of)
    with db.cursor() as cur:
        cur.execute("SELECT known_warnings FROM entry_params WHERE symbol='VRENT' AND signal_at=%s", (now,))
        w = cur.fetchone()[0]
    assert (VOLUME_REGIME_TAG in (w or [])) is tagged


def test_tripwire4_volume_breakout_count_warns_over_max(db):
    from kr_pipeline.ohlcv.tripwires import VOLUME_BREAKOUT_DAILY_MAX, check_volume_breakout_count
    assert VOLUME_BREAKOUT_DAILY_MAX == 1361
    d = date(2031, 1, 6)   # 다른 테스트와 겹치지 않는 미래 날짜
    with db.cursor() as cur:
        cur.execute("DELETE FROM daily_indicators WHERE date=%s", (d,))
        cur.execute("DELETE FROM daily_prices WHERE date=%s", (d,))
        for i, (ratio, high) in enumerate([(1.5, 100), (2.0, 100), (1.1, 100), (3.0, 0)]):  # 2건만 비할트 ≥1.4
            t = f"VR{i:04d}"
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT (ticker) DO NOTHING", (t, t))
            cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) VALUES (%s, %s, 90, %s, 80, 90, 90, 1000, 90000)",
                        (t, d, high))
            cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close, volume_ratio_50d) VALUES (%s, %s, 90, %s)", (t, d, ratio))
    assert check_volume_breakout_count(db, start=d, end=d) == []                         # 2 ≤ 1361
    w = check_volume_breakout_count(db, start=d, end=d, max_count=1)                    # 2 > 1
    assert len(w) == 1 and w[0].startswith("volume_breakout_count") and str(d) in w[0] and "2" in w[0]
