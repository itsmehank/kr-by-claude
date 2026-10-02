"""#207 회신 21 Q-5c 3 — 판정 행 표지 = 전용 컬럼 volume_regime_flag(문자열 표지 제거) + 트립와이어 (4)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from kr_pipeline.common.data_regimes import (
    ALLOW_EXCLUDED_REGIME_ENV, BACKTEST_EXCLUDED_FROM, FLAG_MIXED, VOLUME_REGIME_BOUNDARY, assert_backtest_range_allowed,
)
from tests.test_llm_runner_store import _cls_result, _s9_result

B = VOLUME_REGIME_BOUNDARY


def _seed_daily_window(db, ticker, *, straddle: bool):
    """straddle=True: 경계 전후 봉 → mixed. False: 경계 이후 봉 50개만 → new(NULL). 반환 = as_of(마지막 봉)."""
    start = (B - timedelta(days=30)) if straddle else B
    days, d = [], start
    while len(days) < 50:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT (ticker) DO NOTHING", (ticker, ticker))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (ticker,))
        cur.executemany("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) VALUES (%s,%s,1000,1000,1000,1000,1000,1,1)",   # close=pivot(1000) — store sanity(pivot_far_from_price) 중립
                        [(ticker, x) for x in days])
    return days[-1]


def _seed_weekly_range(db, ticker, week_ends):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT (ticker) DO NOTHING", (ticker, ticker))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (ticker,))
        cur.executemany("INSERT INTO weekly_prices (ticker, week_end_date, open, high, low, close, adj_close, volume, value, trading_days) "
                        "VALUES (%s,%s,1,1,1,1,1,1,1,5)", [(ticker, d) for d in week_ends])


CASES = [(True, FLAG_MIXED), (False, None)]      # (일간 50봉 창이 경계에 걸침?, 기대 flag)
_LLM_META = {"duration_s": 1.0, "input_tokens": None, "output_tokens": None}


def _one(db, sql, *args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()


def test_backtest_guard(monkeypatch):
    """회신 20 Q-4c: BACKTEST_EXCLUDED_FROM(09-28) 이후 봉은 백테스트 금지 — 명시 env 우회만 허용. (#220 리뷰: 삭제됐던 커버리지 복원)"""
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
    """세 진입점 중 두 곳(llm_runner.backfill·backtest.backfill)이 가드를 실제로 호출한다."""
    monkeypatch.delenv(ALLOW_EXCLUDED_REGIME_ENV, raising=False)
    from kr_pipeline.llm_runner import backfill as llm_backfill
    from kr_pipeline.backtest import backfill as bt_backfill
    with pytest.raises(ValueError):
        llm_backfill.run(db, start=BACKTEST_EXCLUDED_FROM, end=BACKTEST_EXCLUDED_FROM + timedelta(days=6))
    with pytest.raises(ValueError):
        bt_backfill.run_backtest_backfill(db, start=BACKTEST_EXCLUDED_FROM, end=BACKTEST_EXCLUDED_FROM + timedelta(days=6),
                                          tickers=["005930"])


def test_text_tag_helpers_are_gone():
    import kr_pipeline.common.data_regimes as m
    assert not hasattr(m, "with_volume_regime") and not hasattr(m, "VOLUME_REGIME_TAG")


@pytest.mark.parametrize("straddle,flag", CASES)
def test_classification_flag_column_and_clean_sanity(db, straddle, flag):
    as_of = _seed_daily_window(db, "VRF1", straddle=straddle)
    from kr_pipeline.llm_runner.store import insert_classification
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='VRF1'")
    insert_classification(db, symbol="VRF1", classified_at=datetime.now(timezone.utc), market="KOSPI",
                          result=_cls_result(), source="weekend", llm_meta=_LLM_META, analyzed_for_date=as_of)
    f, w = _one(db, "SELECT volume_regime_flag, sanity_warnings FROM weekly_classification WHERE symbol='VRF1'")
    assert f == flag and not (w or [])


@pytest.mark.parametrize("straddle,flag", CASES)
def test_backfill_classification_flag_column(db, straddle, flag):
    as_of = _seed_daily_window(db, "VRF5", straddle=straddle)
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    with db.cursor() as cur:
        cur.execute("DELETE FROM classification_backfill WHERE symbol='VRF5'")
    insert_backfill_classification(db, symbol="VRF5", classified_at=datetime.now(timezone.utc), market="KOSPI",
                                   result=_cls_result(), source="backfill", llm_meta=_LLM_META, analyzed_for_date=as_of)
    f = _one(db, "SELECT volume_regime_flag FROM classification_backfill WHERE symbol='VRF5'")[0]
    assert f == flag


@pytest.mark.parametrize("straddle,flag", CASES)
def test_trigger_log_flag_column(db, straddle, flag):
    as_of = _seed_daily_window(db, "VRF2", straddle=straddle)
    from kr_pipeline.llm_runner.store import insert_trigger_log
    now = datetime(B.year, B.month, B.day, 9, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol='VRF2'")
    insert_trigger_log(db, symbol="VRF2", evaluated_at=now, trigger_type="breakout", close=1010.0, volume=1, pivot_price=1000.0,
                       result={"decision": "wait", "confidence": 0.5, "reasoning": "t"}, prior_classification_at=now,
                       llm_meta=_LLM_META, analyzed_for_date=as_of)
    f, w = _one(db, "SELECT volume_regime_flag, sanity_warnings FROM trigger_evaluation_log WHERE symbol='VRF2'")
    assert f == flag and w is None


@pytest.mark.parametrize("straddle,flag", CASES)
def test_entry_params_flag_column_and_clean_known_warnings(db, straddle, flag):
    as_of = _seed_daily_window(db, "VRF3", straddle=straddle)
    from kr_pipeline.llm_runner.store import insert_entry_params
    now = datetime(B.year, B.month, B.day, 1, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute("DELETE FROM entry_params WHERE symbol='VRF3'")
    insert_entry_params(db, symbol="VRF3", signal_at=now, result=_s9_result(), trigger_evaluation_at=now,
                        prior_classification_at=now, llm_meta=_LLM_META, analyzed_for_date=as_of)
    f, kw = _one(db, "SELECT volume_regime_flag, known_warnings FROM entry_params WHERE symbol='VRF3' AND signal_at=%s", now)
    assert f == flag and "volume_regime_unverified_#207" not in (kw or [])


@pytest.mark.parametrize("anchor_offset_weeks,flag", [(-3, FLAG_MIXED), (0, None), (None, None)])
def test_position_evaluations_flag_from_anchor_window(db, anchor_offset_weeks, flag):
    """T2 창 = 앵커 주 ~ 평가 주(spec D7): 경계 전 앵커 → mixed, 경계 후 앵커 → NULL, 앵커 없음 → NULL. flag 는 run_daily_eval 이 1회
    계산해 climax 행에 넘기고, decline 행은 거래량 입력이 없어(T-A·TA-d = 가격 낙폭) 항상 NULL(리뷰 #222)."""
    from kr_pipeline.common.regime_windows import weekly_range_flag
    from kr_pipeline.trade_management.runner import _insert_climax_eval, _insert_decline_eval
    eval_week = B + timedelta(days=4)                                  # 10-02(금)
    fridays = [eval_week + timedelta(weeks=i) for i in range(-6, 1)]
    _seed_weekly_range(db, "VRF4", fridays)
    anchor = None if anchor_offset_weeks is None else (eval_week + timedelta(weeks=anchor_offset_weeks)).isoformat()
    with db.cursor() as cur:
        cur.execute("DELETE FROM positions WHERE symbol='VRF4'")
        cur.execute("INSERT INTO positions (symbol, entry_date, entry_price, quantity, status) VALUES ('VRF4', %s, 1000, 1, 'open') RETURNING id", (eval_week,))
        pid = cur.fetchone()[0]
    vr = weekly_range_flag(db, "VRF4", anchor, eval_week)
    assert vr == flag
    assert _insert_climax_eval(db, position_id=pid, as_of=eval_week, fired=False, suppressed=False, hold_days=1, triggers=[],
                               anchor_week=anchor, weeks_since=None, maturity_ok=None, p2_accel_ok=None, scope_active=None, mode="quality",
                               volume_regime_flag=vr)
    assert _insert_decline_eval(db, position_id=pid, as_of=eval_week, fired=False, hold_days=1, signals=[], anchor_week=anchor,
                                weeks_since=None, maturity_ok=None, ta_max_decline_now=None, ta_d_daily_max_decline_now=None,
                                mode="quality", climax_also_fired=False)
    assert _one(db, "SELECT volume_regime_flag FROM position_climax_evaluations WHERE position_id=%s", pid)[0] == flag
    assert _one(db, "SELECT volume_regime_flag FROM position_decline_evaluations WHERE position_id=%s", pid)[0] is None


def test_classification_flag_null_after_window_expires(db):
    """경계 + 50봉 이후 판정은 창이 전부 extended → NULL(자연 만료, spec §5)."""
    from kr_pipeline.llm_runner.store import insert_classification
    as_of = _seed_daily_window(db, "VRF9", straddle=False)
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='VRF9'")
    insert_classification(db, symbol="VRF9", classified_at=datetime.now(timezone.utc), market="KOSPI",
                          result=_cls_result(), source="weekend", llm_meta=_LLM_META, analyzed_for_date=as_of)
    assert _one(db, "SELECT volume_regime_flag FROM weekly_classification WHERE symbol='VRF9'")[0] is None


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
