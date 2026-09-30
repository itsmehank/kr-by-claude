"""#207 회신 21 Q-5c 3 — 판정 행 표지 = 전용 컬럼 volume_regime_flag(문자열 표지 제거) + 트립와이어 (4)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from kr_pipeline.common.data_regimes import FLAG_MIXED, VOLUME_REGIME_BOUNDARY
from tests.test_llm_runner_store import _cls_result, _s9_result

B = VOLUME_REGIME_BOUNDARY
CASES = [(B - timedelta(days=5), None), (B, FLAG_MIXED)]
_LLM_META = {"duration_s": 1.0, "input_tokens": None, "output_tokens": None}


def _one(db, sql, *args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def test_text_tag_helpers_are_gone():
    import kr_pipeline.common.data_regimes as m
    assert not hasattr(m, "with_volume_regime") and not hasattr(m, "VOLUME_REGIME_TAG")


@pytest.mark.parametrize("as_of,flag", CASES)
def test_classification_flag_column_and_clean_sanity(db, as_of, flag):
    from kr_pipeline.llm_runner.store import insert_classification
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='VRF1'")
    insert_classification(db, symbol="VRF1", classified_at=datetime.now(timezone.utc), market="KOSPI",
                          result=_cls_result(), source="weekend", llm_meta=_LLM_META, analyzed_for_date=as_of)
    f, w = _one(db, "SELECT volume_regime_flag, sanity_warnings FROM weekly_classification WHERE symbol='VRF1'")
    assert f == flag and not (w or [])


@pytest.mark.parametrize("as_of,flag", CASES)
def test_backfill_classification_flag_column(db, as_of, flag):
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    with db.cursor() as cur:
        cur.execute("DELETE FROM classification_backfill WHERE symbol='VRF5'")
    insert_backfill_classification(db, symbol="VRF5", classified_at=datetime.now(timezone.utc), market="KOSPI",
                                   result=_cls_result(), source="backfill", llm_meta=_LLM_META, analyzed_for_date=as_of)
    f = _one(db, "SELECT volume_regime_flag FROM classification_backfill WHERE symbol='VRF5'")[0]
    assert f == flag


@pytest.mark.parametrize("as_of,flag", CASES)
def test_trigger_log_flag_column(db, as_of, flag):
    from kr_pipeline.llm_runner.store import insert_trigger_log
    now = datetime(B.year, B.month, B.day, 9, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='VRF2'")
    insert_trigger_log(db, symbol="VRF2", evaluated_at=now, trigger_type="breakout", close=1010.0, volume=1, pivot_price=1000.0,
                       result={"decision": "wait", "confidence": 0.5, "reasoning": "t"}, prior_classification_at=now,
                       llm_meta=_LLM_META, analyzed_for_date=as_of)
    f, w = _one(db, "SELECT volume_regime_flag, sanity_warnings FROM trigger_evaluation_log WHERE symbol='VRF2'")
    assert f == flag and w is None


@pytest.mark.parametrize("as_of,flag", CASES)
def test_entry_params_flag_column_and_clean_known_warnings(db, as_of, flag):
    from kr_pipeline.llm_runner.store import insert_entry_params
    now = datetime(B.year, B.month, B.day, 1, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("DELETE FROM entry_params WHERE symbol='VRF3'")
    insert_entry_params(db, symbol="VRF3", signal_at=now, result=_s9_result(), trigger_evaluation_at=now,
                        prior_classification_at=now, llm_meta=_LLM_META, analyzed_for_date=as_of)
    f, kw = _one(db, "SELECT volume_regime_flag, known_warnings FROM entry_params WHERE symbol='VRF3' AND signal_at=%s", now)
    assert f == flag and "volume_regime_unverified_#207" not in (kw or [])


@pytest.mark.parametrize("as_of,flag", CASES)
def test_position_evaluations_flag_column(db, as_of, flag):
    from kr_pipeline.trade_management.runner import _insert_climax_eval, _insert_decline_eval
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRF4','VRF4','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM positions WHERE symbol='VRF4'")
        cur.execute("INSERT INTO positions (symbol, entry_date, entry_price, quantity, status) VALUES ('VRF4', %s, 1000, 1, 'open') RETURNING id", (as_of,))
        pid = cur.fetchone()[0]
    assert _insert_climax_eval(db, position_id=pid, as_of=as_of, fired=False, suppressed=False, hold_days=1, triggers=[],
                               anchor_week=None, weeks_since=None, maturity_ok=None, p2_accel_ok=None, scope_active=None, mode="quality")
    assert _insert_decline_eval(db, position_id=pid, as_of=as_of, fired=False, hold_days=1, signals=[], anchor_week=None,
                                weeks_since=None, maturity_ok=None, ta_max_decline_now=None, ta_d_daily_max_decline_now=None,
                                mode="quality", climax_also_fired=False)
    assert _one(db, "SELECT volume_regime_flag FROM position_climax_evaluations WHERE position_id=%s", pid)[0] == flag
    assert _one(db, "SELECT volume_regime_flag FROM position_decline_evaluations WHERE position_id=%s", pid)[0] == flag


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
