"""#122 — 확정 누락 이벤트의 참조 adj 소급 재적재(DART 배율 기반, 1회성). KRX·Naver·DART 접촉 0."""
from datetime import date

import pytest

from kr_pipeline.ohlcv import adj_reload_events as m


def _seed(db, ticker, rows, *, factor=1.0, halt_dates=()):
    """rows = [(date, close)] — adj = close × factor (기존 후행 이벤트 소급 상태 모사). halt_dates: adj OHLV NULL."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, 'A', 'KOSDAQ') ON CONFLICT DO NOTHING", (ticker,))
        for d, c in rows:
            a = c * factor
            halt = d in halt_dates
            cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, "
                        "adj_volume, volume, value, change_pct) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,NULL)",
                        (ticker, d, c, c, c, c, a, None if halt else a, None if halt else a, None if halt else a,
                         None if halt else 1000 / factor, 0 if halt else 1000))


AUDIT = {"rows": [
    {"ticker": "RL1", "kind": "cr", "status": "missing_confirmed", "ex_date": "2023-12-08", "gap_date": "2023-12-27",
     "expected_ratio": 20.0, "rcept_no": "r1"},
    {"ticker": "RL2", "kind": "fric", "status": "missing_confirmed", "ex_date": "2023-02-23", "gap_date": "2023-02-23",
     "expected_ratio": 0.25, "rcept_no": "r2"},
    {"ticker": "RL3", "kind": "cr", "status": "missing_unconfirmed", "ex_date": "2019-12-09", "gap_date": None,
     "expected_ratio": 5.0, "rcept_no": "r3"},
    {"ticker": "RL4", "kind": "cr", "status": "size_mismatch", "ex_date": "2021-04-15", "gap_date": "2021-04-15",
     "expected_ratio": 4.0, "rcept_no": "r4"},
]}


def test_load_targets_confirmed_only_with_gap_date_as_event_date():
    """대상 = missing_confirmed 만. 조정일 = gap_date(무상=권리락일, 병합=재개일), 계수 = expected_ratio."""
    ts = m.load_targets(AUDIT)
    assert [(t.ticker, t.date, t.coef, t.kind) for t in ts] == [
        ("RL1", date(2023, 12, 27), 20.0, "cr"), ("RL2", date(2023, 2, 23), 0.25, "fric")]


def test_plan_reports_rows_before_and_missing_state(db):
    """plan: 조정일 이전 행 수, 조정일 직전/당일 factor 비(≈1 = 아직 누락), 기록 여부. 읽기 전용."""
    _seed(db, "RL1", [(date(2023, 12, 5), 179), (date(2023, 12, 7), 197), (date(2023, 12, 8), 197),
                      (date(2023, 12, 27), 3840), (date(2023, 12, 28), 3685)], factor=2.2, halt_dates={date(2023, 12, 8)})
    t = m.Target("RL1", date(2023, 12, 27), 20.0, "cr", date(2023, 12, 8), "r1")
    p = m.plan_target(db, t)
    assert p["rows_before"] == 3 and p["recorded"] is False and p["state"] == "missing"
    assert abs(p["factor_ratio"] - 1.0) < 0.01          # 직전 행 factor / 당일 factor


def test_apply_multiplies_rows_before_event_only_and_records(db):
    """조정일 이전 행만 adj_* × coef, adj_volume ÷ coef; 할트 행의 NULL 은 NULL 유지; 당일·이후 불변; adj_factor_events 기록."""
    _seed(db, "RL1", [(date(2023, 12, 5), 179), (date(2023, 12, 7), 197), (date(2023, 12, 8), 197),
                      (date(2023, 12, 27), 3840), (date(2023, 12, 28), 3685)], factor=2.2, halt_dates={date(2023, 12, 8)})
    t = m.Target("RL1", date(2023, 12, 27), 20.0, "cr", date(2023, 12, 8), "r1")
    out = m.apply_target(db, t)
    assert out["applied_rows"] == 3 and out["recorded"] == 1 and out["skipped"] is None
    with db.cursor() as cur:
        cur.execute("SELECT date, adj_close, adj_high, adj_volume FROM daily_prices WHERE ticker='RL1' ORDER BY 1")
        rows = cur.fetchall()
    got = [(d, round(float(a), 1), None if h is None else round(float(h), 1), None if v is None else round(float(v), 2)) for d, a, h, v in rows]
    assert got == [
        (date(2023, 12, 5), 179 * 2.2 * 20, 179 * 2.2 * 20, round(1000 / 2.2 / 20, 2)),
        (date(2023, 12, 7), 197 * 2.2 * 20, 197 * 2.2 * 20, round(1000 / 2.2 / 20, 2)),
        (date(2023, 12, 8), 197 * 2.2 * 20, None, None),
        (date(2023, 12, 27), round(3840 * 2.2, 1), round(3840 * 2.2, 1), round(1000 / 2.2, 2)),
        (date(2023, 12, 28), round(3685 * 2.2, 1), round(3685 * 2.2, 1), round(1000 / 2.2, 2)),
    ]
    with db.cursor() as cur:
        cur.execute("SELECT date, coef::float FROM adj_factor_events WHERE ticker='RL1'")
        assert cur.fetchall() == [(date(2023, 12, 27), 20.0)]
    # 적용 후 factor 점프 = coef (검증 값)
    assert abs(out["factor_ratio_after"] / 20.0 - 1) < 0.01


def test_apply_is_idempotent_when_event_already_recorded(db):
    _seed(db, "RL2", [(date(2023, 2, 21), 25950), (date(2023, 2, 22), 26300), (date(2023, 2, 23), 7190)])
    t = m.Target("RL2", date(2023, 2, 23), 0.25, "fric", date(2023, 2, 23), "r2")
    assert m.apply_target(db, t)["applied_rows"] == 2
    out2 = m.apply_target(db, t)
    assert out2["applied_rows"] == 0 and out2["skipped"] == "recorded"


def test_apply_refuses_when_reference_already_adjusted(db):
    """사전 검사: 조정일 직전/당일 factor 비가 이미 coef 근방이면(그 사이 조정됨) 적용 거부 — 이중 소급 방지."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('RL5', 'A', 'KOSDAQ') ON CONFLICT DO NOTHING")
        for d, c, a in [(date(2023, 2, 22), 26300, 6575), (date(2023, 2, 23), 7190, 7190)]:   # 이미 ×0.25 소급됨
            cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, adj_high, adj_low, adj_open, "
                        "adj_volume, volume, value) VALUES ('RL5',%s,%s,%s,%s,%s,%s,%s,%s,%s,1,1000,1)", (d, c, c, c, c, a, a, a, a))
    t = m.Target("RL5", date(2023, 2, 23), 0.25, "fric", date(2023, 2, 23), "r5")
    out = m.apply_target(db, t)
    assert out["applied_rows"] == 0 and out["skipped"] == "already_adjusted"
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM adj_factor_events WHERE ticker='RL5'")
        assert cur.fetchone()[0] == 0


def test_backup_and_restore_round_trip(db):
    """backup = 조정일 이전 행의 adj 5열 스냅샷. restore = 그 값 복원 + 이벤트 기록 삭제."""
    _seed(db, "RL2", [(date(2023, 2, 21), 25950), (date(2023, 2, 22), 26300), (date(2023, 2, 23), 7190)])
    t = m.Target("RL2", date(2023, 2, 23), 0.25, "fric", date(2023, 2, 23), "r2")
    bk = m.backup_rows(db, t)
    assert [r["date"] for r in bk] == ["2023-02-21", "2023-02-22"] and bk[0]["adj_close"] == 25950.0
    m.apply_target(db, t)
    n = m.restore_rows(db, t, bk)
    assert n == 2
    with db.cursor() as cur:
        cur.execute("SELECT adj_close::float FROM daily_prices WHERE ticker='RL2' ORDER BY date")
        assert [r[0] for r in cur.fetchall()] == [25950.0, 26300.0, 7190.0]
        cur.execute("SELECT count(*) FROM adj_factor_events WHERE ticker='RL2'")
        assert cur.fetchone()[0] == 0


def test_recompute_ticker_calls_daily_weekly_weekly_indicators_in_order(db, mocker):
    """지표 재계산 = drift.reload_ticker 동형(일봉 Phase A → 주봉 재집계 → 주봉 Phase A), 그 종목만."""
    calls = []
    mocker.patch.object(m.indicators, "recompute_ticker_daily", side_effect=lambda conn, t: calls.append(("ind_daily", t)) or 5)

    class _S:
        rows_affected = 7
    mocker.patch.object(m.weekly, "run", side_effect=lambda *a, **k: calls.append(("weekly", k.get("only_tickers"))) or _S())
    mocker.patch.object(m.indicators, "recompute_ticker_weekly", side_effect=lambda conn, t: calls.append(("ind_weekly", t)) or 3)
    out = m.recompute_ticker(db, "RL1")
    assert [c[0] for c in calls] == ["ind_daily", "weekly", "ind_weekly"] and calls[1][1] == ["RL1"]
    assert out == {"indicators_daily": 5, "weekly": 7, "indicators_weekly": 3}


def test_reload_script_blanks_krx_credentials_before_pipeline_imports():
    """스크립트는 kr_pipeline import 전에 KRX_ID/KRX_PW 를 비운다 — pykrx 가 import 시점에 로그인하는 것을 막는다(접촉 0)."""
    src = open("scripts/issue122_adj_reload.py").read()
    blank = src.index('os.environ["KRX_ID"] = ""')
    assert blank < src.index("from kr_pipeline") and blank < src.index("import psycopg")
