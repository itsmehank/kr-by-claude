"""(#162 2026-09-09) 시그널 → positions 연결 + 추격 표시 — 매칭·chase 계산·null 안전·손절 불변·알림 문구."""
from datetime import date, datetime, timedelta, timezone

import pytest

from kr_pipeline.common.thresholds import PIVOT_EXTENDED_BAND_MULT, TRADE_STOP_INITIAL_PCT
from kr_pipeline.trade_management.signal_link import (
    CHASE_LIMIT, NO_SIGNAL_WARNING, SignalLink, chase_fields, chase_warning, link_warnings, match_signal,
)
from kr_pipeline.trade_management.store import get_open_positions, open_position
from tests.test_trade_positions import _cleanup

KST = timezone(timedelta(hours=9))


def _seed_signals(db, symbol, rows):
    """rows: [(signal_at, pivot_price, stop_loss)]"""
    with db.cursor() as cur:
        cur.execute("DELETE FROM positions WHERE symbol=%s", (symbol,))
        cur.execute("DELETE FROM entry_params WHERE symbol=%s", (symbol,))
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING",
                    (symbol, symbol))
        for sig_at, pivot, stop in rows:
            cur.execute("""INSERT INTO entry_params (symbol, signal_at, pivot_price, stop_loss,
                                                     trigger_evaluation_at, prior_classification_at)
                           VALUES (%s,%s,%s,%s,%s,%s)""", (symbol, sig_at, pivot, stop, sig_at, sig_at))
    db.commit()


def _teardown(db, symbol):
    _cleanup(db, [symbol])
    with db.cursor() as cur:
        cur.execute("DELETE FROM entry_params WHERE symbol=%s", (symbol,))
    db.commit()


# ---------- chase 계산·경계 ----------

def test_chase_limit_reuses_extended_constant():
    assert CHASE_LIMIT == round(PIVOT_EXTENDED_BAND_MULT - 1, 6) == 0.05


@pytest.mark.parametrize("entry,pivot,expect_pct,expect_over", [
    (105.0, 100.0, 0.05, False),      # 정확히 5% = 미초과(strict >)
    (10500.0, 10000.0, 0.05, False),
    (105.01, 100.0, 0.0501, True),
    (104.0, 100.0, 0.04, False),
    (98.0, 100.0, -0.02, False),      # pivot 아래 매수(음수) — 초과 아님
])
def test_chase_fields_boundary(entry, pivot, expect_pct, expect_over):
    pct, over = chase_fields(entry, pivot)
    assert pct == pytest.approx(expect_pct, abs=1e-6) and over is expect_over


def test_chase_fields_null_safe():
    assert chase_fields(100.0, None) == (None, None)
    assert chase_fields(100.0, 0.0) == (None, None)


# ---------- 매칭 ----------

def test_match_most_recent_signal_on_or_before_entry(db):
    sym = "SIGL1"
    t = lambda d: datetime(2026, 7, d, 9, 0, tzinfo=KST)  # noqa: E731
    _seed_signals(db, sym, [(t(1), 100.0, 92.0), (t(10), 110.0, 101.2), (t(20), 120.0, 110.4)])
    link = match_signal(db, symbol=sym, entry_date=date(2026, 7, 15), entry_price=112.0)
    assert link.signal_at == t(10) and link.pivot_price == 110.0 and link.signal_stop_price == 101.2
    assert link.signal_gap_days == 5 and link.chase_over_limit is False
    assert link.chase_pct == pytest.approx(112.0 / 110.0 - 1, abs=1e-6)
    # 매수일 당일 시그널도 포함(signal_at 날짜 ≤ entry_date)
    same = match_signal(db, symbol=sym, entry_date=date(2026, 7, 20), entry_price=130.0)
    assert same.signal_at == t(20) and same.signal_gap_days == 0 and same.chase_over_limit is True
    _teardown(db, sym)


def test_match_explicit_signal_at_and_missing(db):
    sym = "SIGL2"
    t = lambda d: datetime(2026, 7, d, 9, 0, tzinfo=KST)  # noqa: E731
    _seed_signals(db, sym, [(t(1), 100.0, 92.0), (t(10), 110.0, 101.2)])
    link = match_signal(db, symbol=sym, entry_date=date(2026, 7, 15), entry_price=101.0, signal_at=t(1))
    assert link.signal_at == t(1) and link.pivot_price == 100.0 and link.signal_gap_days == 14
    with pytest.raises(ValueError):
        match_signal(db, symbol=sym, entry_date=date(2026, 7, 15), entry_price=101.0, signal_at=t(5))
    # 시그널 전무 / entry_date 이전 시그널 없음 → None + 경고 문구
    assert match_signal(db, symbol=sym, entry_date=date(2026, 6, 30), entry_price=101.0) is None
    assert link_warnings(None) == [NO_SIGNAL_WARNING]
    _teardown(db, sym)


def test_link_warnings_only_when_over_limit():
    ok = SignalLink(datetime(2026, 7, 1, tzinfo=KST), 100.0, 92.0, 0.05, False, 3)
    over = SignalLink(datetime(2026, 7, 1, tzinfo=KST), 100.0, 92.0, 0.083, True, 3)
    assert link_warnings(ok) == []
    assert link_warnings(over) == [chase_warning(0.083)]
    assert "+8.3%" in chase_warning(0.083) and "5% 초과" in chase_warning(0.083) and "매입가 × 0.92" in chase_warning(0.083)


# ---------- store: null 안전 · 참고 컬럼 영속 ----------

def test_open_position_persists_link_and_null_safe(db):
    sym = "SIGL3"
    t = datetime(2026, 7, 1, 9, 0, tzinfo=KST)
    _seed_signals(db, sym, [(t, 100.0, 92.0)])
    link = match_signal(db, symbol=sym, entry_date=date(2026, 7, 3), entry_price=108.0)
    pid = open_position(db, symbol=sym, entry_date=date(2026, 7, 3), entry_price=108.0, signal=link)
    db.commit()
    row = next(r for r in get_open_positions(db) if r["id"] == pid)
    assert row["signal_at"] == t and row["pivot_price"] == 100.0 and row["signal_stop_price"] == 92.0
    assert row["chase_pct"] == pytest.approx(0.08) and row["chase_over_limit"] is True and row["signal_gap_days"] == 2
    _teardown(db, sym)
    # 시그널 없이 개설 → 전부 None
    sym2 = "SIGL4"
    _cleanup(db, [sym2])
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING", (sym2, sym2))
    pid2 = open_position(db, symbol=sym2, entry_date=date(2026, 7, 3), entry_price=108.0)
    db.commit()
    row2 = next(r for r in get_open_positions(db) if r["id"] == pid2)
    assert all(row2[k] is None for k in ("signal_at", "pivot_price", "signal_stop_price", "chase_pct",
                                          "chase_over_limit", "signal_gap_days"))
    _teardown(db, sym2)


# ---------- 손절가 불변 회귀 + 알림 병기 ----------

def test_stop_unchanged_with_chase_and_notify_carries_signal_note(db, mocker):
    """추격 매수(+8%)여도 유효 손절 = 매입가 × 0.92(시그널 손절 92 아님). 알림엔 병기만."""
    from kr_pipeline.trade_management import runner
    from tests.test_trade_positions import _bar
    sym = "SIGL5"
    t = datetime(2026, 7, 1, 9, 0, tzinfo=KST)
    _seed_signals(db, sym, [(t, 100.0, 92.0)])
    link = match_signal(db, symbol=sym, entry_date=date(2026, 7, 3), entry_price=108.0)
    pid = open_position(db, symbol=sym, entry_date=date(2026, 7, 3), entry_price=108.0, signal=link)
    db.commit()
    notify = mocker.patch.object(runner, "notify_stop_triggered")
    mocker.patch.object(runner, "compute_held_gates", side_effect=RuntimeError("skip"))
    _bar(db, sym, date(2026, 7, 10), 99.0, sma_50=90.0)   # 99 < 108×0.92=99.36 → triggered (92 기준이면 미발동)
    r = runner.run_daily_eval(db, as_of=date(2026, 7, 10)); db.commit()
    assert r["triggered"] == 1
    with db.cursor() as cur:
        cur.execute("SELECT effective_stop, binding FROM position_stop_evaluations WHERE position_id=%s", (pid,))
        stop, binding = cur.fetchone()
    assert float(stop) == pytest.approx(108.0 * (1 - TRADE_STOP_INITIAL_PCT)) and binding == "initial_stop"
    kw = notify.call_args.kwargs
    assert kw["effective_stop"] == pytest.approx(99.36) and kw["signal_stop_price"] == 92.0
    assert kw["chase_pct"] == pytest.approx(0.08) and kw["chase_over_limit"] is True
    _teardown(db, sym)


def test_notify_stop_text_includes_signal_note(mocker):
    from kr_pipeline.llm_runner import slack
    post = mocker.patch.object(slack, "_post")
    slack.notify_stop_triggered(symbol="X", name="N", close=99.0, effective_stop=99.36, binding="initial_stop",
                                eval_date=date(2026, 7, 10), signal_stop_price=92.0, chase_pct=0.08,
                                chase_over_limit=True)
    text = post.call_args.args[0]["text"]
    assert "유효 손절선 ₩99" in text and "시그널 손절 ₩92" in text and "추격 +8.0%" in text and "5% 초과" in text
    post.reset_mock()
    slack.notify_stop_triggered(symbol="X", name="N", close=99.0, effective_stop=99.36, binding="initial_stop")
    assert "시그널" not in post.call_args.args[0]["text"]  # 시그널 없음 → 병기 없음(기존 문구 그대로)


def test_notify_chase_entry_text(mocker):
    from kr_pipeline.llm_runner import slack
    post = mocker.patch.object(slack, "_post")
    slack.notify_chase_entry(symbol="X", name="N", entry_price=108.0, pivot_price=100.0, chase_pct=0.08,
                             warning=chase_warning(0.08), entry_date=date(2026, 7, 3))
    text = post.call_args.args[0]["text"]
    assert "추격 매수 기록" in text and "+8.0%" in text and "매입가 × 0.92" in text
