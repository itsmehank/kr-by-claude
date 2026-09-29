"""#207 회신 20 (ii) — 09-28 이후 거래량 정의 미확정 표지 + 트립와이어 (4) 경고형 + 백테스트 금지 강제."""
from datetime import date, datetime, timedelta, timezone

import pytest

from kr_pipeline.common.data_regimes import (
    ALLOW_EXCLUDED_REGIME_ENV, BACKTEST_EXCLUDED_FROM, VOLUME_REGIME_TAG, VOLUME_REGIME_UNVERIFIED_FROM,
    assert_backtest_range_allowed, volume_regime_warnings, with_volume_regime,
)
from tests.test_llm_runner_store import _cls_result, _s9_result

BEFORE = VOLUME_REGIME_UNVERIFIED_FROM - timedelta(days=5)
AT = VOLUME_REGIME_UNVERIFIED_FROM
BOUNDARY_CASES = [(BEFORE, False), (AT, True)]
_LLM_META = {"duration_s": 1.0, "input_tokens": None, "output_tokens": None}


def test_helper_boundary_and_input_types():
    assert volume_regime_warnings(None) == []
    assert volume_regime_warnings(BEFORE) == []
    assert volume_regime_warnings(AT) == [VOLUME_REGIME_TAG]
    assert volume_regime_warnings(AT + timedelta(days=40)) == [VOLUME_REGIME_TAG]
    assert volume_regime_warnings(datetime(AT.year, AT.month, AT.day, 9, tzinfo=timezone.utc)) == [VOLUME_REGIME_TAG]
    assert volume_regime_warnings(AT.isoformat()) == [VOLUME_REGIME_TAG]


def test_with_volume_regime_appends_once():
    assert with_volume_regime(None, BEFORE) == []
    assert with_volume_regime(["a"], AT) == ["a", VOLUME_REGIME_TAG]
    assert with_volume_regime(["a", VOLUME_REGIME_TAG], AT) == ["a", VOLUME_REGIME_TAG]   # 중복 없음


def test_backtest_guard(monkeypatch):
    monkeypatch.delenv(ALLOW_EXCLUDED_REGIME_ENV, raising=False)
    assert_backtest_range_allowed(None)
    assert_backtest_range_allowed(BACKTEST_EXCLUDED_FROM - timedelta(days=1))
    with pytest.raises(ValueError, match="BACKTEST_EXCLUDED_FROM"):
        assert_backtest_range_allowed(BACKTEST_EXCLUDED_FROM)
    with pytest.raises(ValueError):
        assert_backtest_range_allowed(str(BACKTEST_EXCLUDED_FROM + timedelta(days=30)))
    monkeypatch.setenv(ALLOW_EXCLUDED_REGIME_ENV, "1")
    assert_backtest_range_allowed(BACKTEST_EXCLUDED_FROM)          # 명시 우회만 허용


def test_backfill_entrypoints_refuse_excluded_range(db, monkeypatch):
    monkeypatch.delenv(ALLOW_EXCLUDED_REGIME_ENV, raising=False)
    from kr_pipeline.llm_runner import backfill as llm_backfill
    from kr_pipeline.backtest import backfill as bt_backfill
    with pytest.raises(ValueError):
        llm_backfill.run(db, start=BACKTEST_EXCLUDED_FROM, end=BACKTEST_EXCLUDED_FROM + timedelta(days=6))
    with pytest.raises(ValueError):
        bt_backfill.run_backtest_backfill(db, start=BACKTEST_EXCLUDED_FROM, end=BACKTEST_EXCLUDED_FROM + timedelta(days=6),
                                          tickers=["005930"])


def _fetch_one(db, sql, *args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


@pytest.mark.parametrize("as_of,tagged", BOUNDARY_CASES)
def test_insert_classification_tags_rows_on_or_after_boundary(db, as_of, tagged):
    from kr_pipeline.llm_runner.store import insert_classification
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='VRTAG'")
    insert_classification(db, symbol="VRTAG", classified_at=datetime.now(timezone.utc), market="KOSPI",
                          result=_cls_result(), source="weekend", llm_meta=_LLM_META, analyzed_for_date=as_of)
    w = _fetch_one(db, "SELECT sanity_warnings FROM weekly_classification WHERE symbol='VRTAG'")
    assert (VOLUME_REGIME_TAG in (w or [])) is tagged


@pytest.mark.parametrize("as_of,tagged", BOUNDARY_CASES)
def test_insert_trigger_log_tags(db, as_of, tagged):
    from kr_pipeline.llm_runner.store import insert_trigger_log
    now = datetime(AT.year, AT.month, AT.day, 9, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='VRTRG'")
    insert_trigger_log(db, symbol="VRTRG", evaluated_at=now, trigger_type="breakout",
                       close=1010.0, volume=100000, pivot_price=1000.0,
                       result={"decision": "wait", "confidence": 0.5, "reasoning": "t"},
                       prior_classification_at=now, llm_meta=_LLM_META, analyzed_for_date=as_of)
    w = _fetch_one(db, "SELECT sanity_warnings FROM trigger_evaluation_log WHERE symbol='VRTRG'")
    assert (VOLUME_REGIME_TAG in (w or [])) is tagged


@pytest.mark.parametrize("as_of,tagged", BOUNDARY_CASES)
def test_insert_entry_params_tags_known_warnings(db, as_of, tagged):
    from kr_pipeline.llm_runner.store import insert_entry_params
    now = datetime(AT.year, AT.month, AT.day, 1, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("DELETE FROM entry_params WHERE symbol='VRENT'")
    insert_entry_params(db, symbol="VRENT", signal_at=now, result=_s9_result(observed_breakout_volume_ratio=1.8),
                        trigger_evaluation_at=now, prior_classification_at=now, llm_meta=_LLM_META, analyzed_for_date=as_of)
    w = _fetch_one(db, "SELECT known_warnings FROM entry_params WHERE symbol='VRENT' AND signal_at=%s", now)
    assert (VOLUME_REGIME_TAG in (w or [])) is tagged


def test_tripwire4_volume_breakout_count_warns_over_max(db):
    """임계 인자로 동작 검증(상수 리터럴 고정 없음 — 개정 절차가 테스트를 깨지 않게). 비할트(high>0)만 집계."""
    from kr_pipeline.ohlcv.tripwires import VOLUME_BREAKOUT_DAILY_MAX, check_volume_breakout_count
    d = date(2031, 1, 6)   # 다른 테스트와 겹치지 않는 미래 날짜
    with db.cursor() as cur:
        cur.execute("DELETE FROM daily_indicators WHERE date=%s", (d,))
        cur.execute("DELETE FROM daily_prices WHERE date=%s", (d,))
        for i, (ratio, high) in enumerate([(1.5, 100), (2.0, 100), (1.1, 100), (3.0, 0)]):  # 비할트 ≥1.4 = 2건
            t = f"VR{i:04d}"
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT (ticker) DO NOTHING", (t, t))
            cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) "
                        "VALUES (%s, %s, 90, %s, 80, 90, 90, 1000, 90000)", (t, d, high))
            cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close, volume_ratio_50d) VALUES (%s, %s, 90, %s)", (t, d, ratio))
    assert check_volume_breakout_count(db, start=d, end=d) == []                              # 2 ≤ 실측 최댓값
    assert VOLUME_BREAKOUT_DAILY_MAX > 2
    w = check_volume_breakout_count(db, start=d - timedelta(days=3), end=d, max_count=1)      # 창 안의 d 가 잡힘
    assert len(w) == 1 and w[0].startswith("volume_breakout_count") and str(d) in w[0]
    assert check_volume_breakout_count(db, start=d + timedelta(days=1), end=d + timedelta(days=1), max_count=1) == []
