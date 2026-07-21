# tests/test_trade_positions.py
# (#47) 포지션 wiring — positions 테이블·수동 기록 store·일일 손절 평가 러너.
# 준거: docs/superpowers/specs/2026-07-13-manage-active-trade.md §3 불변 계약,
#       docs/superpowers/specs/2026-07-22-issue47-position-wiring.md (본 PR 사전등록)
from datetime import date

import pytest


@pytest.mark.parametrize("table,cols", [
    ("positions", {"symbol", "entry_date", "entry_price", "breakeven_armed",
                   "status", "source"}),
    ("position_stop_evaluations", {"position_id", "eval_date", "close",
                                   "effective_stop", "binding", "triggered"}),
])
def test_position_tables_exist(db, table, cols):
    with db.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=%s",
            (table,),
        )
        have = {r[0] for r in cur.fetchall()}
    missing = cols - have
    assert not missing, f"{table} 누락 컬럼: {missing} — schema.sql 미적용?"


def _cleanup(db, symbols):
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM position_stop_evaluations WHERE position_id IN "
            "(SELECT id FROM positions WHERE symbol = ANY(%s))", (symbols,))
        cur.execute("DELETE FROM positions WHERE symbol = ANY(%s)", (symbols,))
        cur.execute("DELETE FROM daily_prices WHERE ticker = ANY(%s)", (symbols,))
        cur.execute("DELETE FROM daily_indicators WHERE ticker = ANY(%s)", (symbols,))
        cur.execute("DELETE FROM corporate_actions WHERE ticker = ANY(%s)", (symbols,))
        cur.execute("DELETE FROM stocks WHERE ticker = ANY(%s)", (symbols,))
    db.commit()


def _seed(db, symbol, *, entry_price=10000.0, entry_date=date(2026, 7, 1)):
    from kr_pipeline.trade_management.store import open_position
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') "
            "ON CONFLICT DO NOTHING", (symbol, symbol))
    pid = open_position(db, symbol=symbol, entry_date=entry_date,
                        entry_price=entry_price, quantity=10, note="t")
    db.commit()
    return pid


def _bar(db, symbol, d, close, *, sma_50=None):
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close,
                                         volume, value)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 1000, 1000) ON CONFLICT DO NOTHING""",
            (symbol, d, close, close, close, close, close))
        if sma_50 is not None:
            cur.execute(
                """INSERT INTO daily_indicators (ticker, date, adj_close, sma_50)
                   VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                (symbol, d, close, sma_50))
    db.commit()


def test_open_close_list_position(db):
    """수동 기록 store: open → list(open) → close → list 에서 제외."""
    from kr_pipeline.trade_management.store import (
        open_position, close_position, get_open_positions,
    )
    _cleanup(db, ["POS1"])
    pid = _seed(db, "POS1")
    rows = get_open_positions(db)
    mine = [r for r in rows if r["symbol"] == "POS1"]
    assert len(mine) == 1 and mine[0]["id"] == pid
    assert mine[0]["entry_price"] == 10000.0
    assert mine[0]["breakeven_armed"] is False

    close_position(db, position_id=pid, reason="test exit")
    db.commit()
    assert not [r for r in get_open_positions(db) if r["symbol"] == "POS1"]
    _cleanup(db, ["POS1"])


def test_daily_eval_records_and_persists_latch(db, mocker):
    """+20% 도달일에 래치 장전·영속화, 이후 본전 하회 시 매도 신호(triggered).

    시나리오: entry 10,000 → 7/10 종가 12,000(장전, breakeven 바닥) →
    7/11 종가 9,900 < 10,000 → triggered (initial_stop 9,200 이 아니라 본전 바닥).
    """
    from kr_pipeline.trade_management import runner
    _cleanup(db, ["POS2"])
    pid = _seed(db, "POS2")
    notify = mocker.patch.object(runner, "notify_stop_triggered")

    _bar(db, "POS2", date(2026, 7, 10), 12000.0, sma_50=9000.0)
    r1 = runner.run_daily_eval(db, as_of=date(2026, 7, 10))
    db.commit()
    assert r1["evaluated"] == 1 and r1["triggered"] == 0
    with db.cursor() as cur:
        cur.execute("SELECT breakeven_armed FROM positions WHERE id=%s", (pid,))
        assert cur.fetchone()[0] is True, "래치 미영속화"
        cur.execute(
            "SELECT effective_stop, binding, triggered FROM position_stop_evaluations "
            "WHERE position_id=%s AND eval_date=%s", (pid, date(2026, 7, 10)))
        stop, binding, trig = cur.fetchone()
        assert float(stop) == 10000.0 and binding == "breakeven" and trig is False

    _bar(db, "POS2", date(2026, 7, 11), 9900.0, sma_50=9000.0)
    r2 = runner.run_daily_eval(db, as_of=date(2026, 7, 11))
    db.commit()
    assert r2["triggered"] == 1
    notify.assert_called_once()
    with db.cursor() as cur:
        cur.execute(
            "SELECT triggered FROM position_stop_evaluations "
            "WHERE position_id=%s AND eval_date=%s", (pid, date(2026, 7, 11)))
        assert cur.fetchone()[0] is True
    _cleanup(db, ["POS2"])


def test_daily_eval_skips_halt_and_missing_bar(db, mocker):
    """halt(close=0)·봉 부재는 평가 대상 아님 — 스펙 §4 (러너가 사전에 거름)."""
    from kr_pipeline.trade_management import runner
    _cleanup(db, ["POS3", "POS4"])
    _seed(db, "POS3")
    _seed(db, "POS4")
    mocker.patch.object(runner, "notify_stop_triggered")
    _bar(db, "POS3", date(2026, 7, 10), 0.0)  # halt 센티널
    # POS4 는 7/10 봉 자체가 없음
    r = runner.run_daily_eval(db, as_of=date(2026, 7, 10))
    db.commit()
    assert r["evaluated"] == 0
    assert sorted(s["symbol"] for s in r["skipped"]) == ["POS3", "POS4"]
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM position_stop_evaluations WHERE position_id IN "
                    "(SELECT id FROM positions WHERE symbol IN ('POS3','POS4'))")
        assert cur.fetchone()[0] == 0
    _cleanup(db, ["POS3", "POS4"])


def test_daily_eval_idempotent_no_duplicate_notify(db, mocker):
    """같은 날 재실행: 평가 행 1개 유지 + Slack 중복 발송 없음."""
    from kr_pipeline.trade_management import runner
    _cleanup(db, ["POS5"])
    _seed(db, "POS5")
    notify = mocker.patch.object(runner, "notify_stop_triggered")
    _bar(db, "POS5", date(2026, 7, 10), 9000.0, sma_50=8000.0)  # < initial 9200 → trig
    runner.run_daily_eval(db, as_of=date(2026, 7, 10))
    db.commit()
    runner.run_daily_eval(db, as_of=date(2026, 7, 10))
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM position_stop_evaluations WHERE position_id IN "
                    "(SELECT id FROM positions WHERE symbol='POS5')")
        assert cur.fetchone()[0] == 1
    assert notify.call_count == 1, "재실행이 중복 알림 발송"
    _cleanup(db, ["POS5"])


def test_daily_eval_warns_on_corp_action_after_entry(db, mocker):
    """보유 중 기업행위 발생 → entry_price 재확인 경고 (수동 기록 모델의 한계 보강)."""
    from kr_pipeline.trade_management import runner
    _cleanup(db, ["POS6"])
    pid = _seed(db, "POS6", entry_date=date(2026, 7, 1))
    mocker.patch.object(runner, "notify_stop_triggered")
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO corporate_actions (ticker, event_date, event_type)
               VALUES ('POS6', '2026-07-05', 'split')""")
    db.commit()
    _bar(db, "POS6", date(2026, 7, 10), 10500.0)
    runner.run_daily_eval(db, as_of=date(2026, 7, 10))
    db.commit()
    with db.cursor() as cur:
        cur.execute(
            "SELECT warnings FROM position_stop_evaluations WHERE position_id=%s", (pid,))
        w = cur.fetchone()[0]
    assert w and any("corp_action_after_entry" in x for x in w)
    _cleanup(db, ["POS6"])


def test_daily_eval_anchor_is_entry_price_not_classification(db, mocker):
    """스펙 §3: anchor = 매수 시점 entry_price 고정 — 분류 테이블의 base_low/pivot
    무유입. 분류 행(base_low 8,000)이 있어도 유효 손절선은 entry×0.92 = 9,200."""
    from datetime import datetime, timezone
    from kr_pipeline.trade_management import runner
    _cleanup(db, ["POS7"])
    pid = _seed(db, "POS7")
    mocker.patch.object(runner, "notify_stop_triggered")
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO weekly_classification
               (symbol, classified_at, market, classification, pivot_price, base_low, source)
               VALUES ('POS7', %s, 'KOSPI', 'entry', 11000, 8000, 'weekend')
               ON CONFLICT DO NOTHING""",
            (datetime(2026, 7, 5, 3, tzinfo=timezone.utc),))
    db.commit()
    _bar(db, "POS7", date(2026, 7, 10), 9500.0, sma_50=9000.0)
    runner.run_daily_eval(db, as_of=date(2026, 7, 10))
    db.commit()
    with db.cursor() as cur:
        cur.execute(
            "SELECT effective_stop, binding FROM position_stop_evaluations "
            "WHERE position_id=%s", (pid,))
        stop, binding = cur.fetchone()
    assert float(stop) == 9200.0 and binding == "initial_stop", \
        f"base_low(8000) 유입 의심: stop={stop} binding={binding}"
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='POS7'")
    db.commit()
    _cleanup(db, ["POS7"])


def test_daily_eval_default_as_of_is_latest_bar(db, mocker):
    """as_of 미지정 → daily_prices 최신 날짜 (cron 이 일봉 체인 뒤에 붙는 규약).

    전역 MAX(date) 의존이므로 봉을 2099 센티널로 심어 다른 테스트의 잔존 봉과
    무관하게 최댓값을 보장 (리뷰 — 전역 MAX 취약성, full suite 실측으로 확증됨).
    """
    from kr_pipeline.trade_management import runner
    _cleanup(db, ["POS8"])
    _seed(db, "POS8")
    mocker.patch.object(runner, "notify_stop_triggered")
    sentinel = date(2099, 7, 10)
    _bar(db, "POS8", sentinel, 10500.0)
    try:
        r = runner.run_daily_eval(db)  # as_of=None
        db.commit()
        assert r["as_of"] == sentinel and r["evaluated"] >= 1
    finally:
        _cleanup(db, ["POS8"])


def test_daily_eval_skips_backdated_as_of(db, mocker):
    """(2기 리뷰 F-1) 이미 더 나중 날짜가 평가된 포지션에 과거 as_of 재실행 →
    미평가 과거일이라도 skip — 현재 래치를 과거에 소급 적용하는 시대착오 차단."""
    from kr_pipeline.trade_management import runner
    _cleanup(db, ["POS9"])
    _seed(db, "POS9")
    mocker.patch.object(runner, "notify_stop_triggered")
    _bar(db, "POS9", date(2026, 7, 10), 12000.0)  # 장전
    _bar(db, "POS9", date(2026, 7, 8), 9000.0)    # 과거일 (트리거였을 값)
    runner.run_daily_eval(db, as_of=date(2026, 7, 10))
    db.commit()
    r = runner.run_daily_eval(db, as_of=date(2026, 7, 8))  # backdated
    db.commit()
    assert r["evaluated"] == 0
    assert r["skipped"] and r["skipped"][0]["reason"] == "backdated_as_of"
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM position_stop_evaluations WHERE position_id IN "
                    "(SELECT id FROM positions WHERE symbol='POS9')")
        assert cur.fetchone()[0] == 1, "과거일 평가 행이 생성됨 (시대착오)"
    _cleanup(db, ["POS9"])
