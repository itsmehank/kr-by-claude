"""#122 — 확정 누락 이벤트의 참조 adj 소급 재적재(DART 배율 기반, 1회성). KRX·Naver·DART 접촉 0."""
from datetime import date, datetime

import pytest

from kr_pipeline.ohlcv import adj_reload_events as m
from kr_pipeline.ohlcv import adjust


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


def _row(ticker, kind, status, ex, gap, ratio):
    return {"ticker": ticker, "kind": kind, "status": status, "ex_date": ex, "gap_date": gap,
            "expected_ratio": ratio, "rcept_no": "r"}


AUDIT = {"rows": [
    _row("RL1", "cr", "missing_confirmed", "2023-12-08", "2023-12-27", 20.0),
    _row("RL2", "fric", "missing_confirmed", "2023-02-23", "2023-02-23", 0.25),
    _row("RL3", "cr", "missing_unconfirmed", "2019-12-09", None, 5.0),
    _row("RL4", "cr", "size_mismatch", "2021-04-15", "2021-04-15", 4.0),
]}
T_RL1 = m.Target("RL1", date(2023, 12, 27), 20.0, "cr", date(2023, 12, 8), "r1")
T_RL2 = m.Target("RL2", date(2023, 2, 23), 0.25, "fric", date(2023, 2, 23), "r2")
RL1_ROWS = [(date(2023, 12, 5), 179), (date(2023, 12, 7), 197), (date(2023, 12, 8), 197),
            (date(2023, 12, 27), 3840), (date(2023, 12, 28), 3685)]
RL2_ROWS = [(date(2023, 2, 21), 25950), (date(2023, 2, 22), 26300), (date(2023, 2, 23), 7190)]


def test_load_targets_confirmed_only_with_gap_date_as_event_date():
    """대상 = missing_confirmed 만. 조정일 = gap_date(무상=권리락일, 병합=재개일), 계수 = expected_ratio."""
    ts = m.load_targets(AUDIT, frozen=None)
    assert [(t.ticker, t.date, t.coef, t.kind) for t in ts] == [
        ("RL1", date(2023, 12, 27), 20.0, "cr"), ("RL2", date(2023, 2, 23), 0.25, "fric")]


def test_load_targets_rejects_set_different_from_frozen():
    """동결본(18건)과 집합이 다르면 거부 — JSON 재생성으로 날짜가 바뀌어 같은 이벤트가 이중 적용되는 것을 막는다."""
    with pytest.raises(ValueError, match="동결본"):
        m.load_targets(AUDIT)
    frozen = frozenset({("RL1", "2023-12-27", 20.0), ("RL2", "2023-02-23", 0.25)})
    assert len(m.load_targets(AUDIT, frozen=frozen)) == 2
    assert len(m.FROZEN_TARGETS) == 18 and len({t for t, _, _ in m.FROZEN_TARGETS}) == 17


def test_plan_reports_rows_before_and_missing_state(db):
    """plan: 조정일 이전 행 수, 직전/당일 factor 비(≈1 = 아직 누락), raw 갭×coef(적용 후 연속성 예상), 기록 여부. 읽기 전용."""
    _seed(db, "RL1", RL1_ROWS, factor=2.2, halt_dates={date(2023, 12, 8)})
    p = m.plan_target(db, T_RL1)
    assert p["rows_before"] == 3 and p["recorded"] is False and p["state"] == "missing"
    assert abs(p["factor_ratio"] - 1.0) < 0.01 and abs(p["raw_gap_x_coef"] - 197 / 3840 * 20) < 1e-6


def test_apply_multiplies_rows_before_event_only_and_records(db):
    """조정일 이전 행만 adj_* × coef, adj_volume ÷ coef; 할트 행의 NULL 은 NULL 유지; 당일·이후 불변; adj_factor_events 기록;
    적용 후 adj_close 직전/당일 비가 ±30% 밴드 안(물리 불변식)."""
    _seed(db, "RL1", RL1_ROWS, factor=2.2, halt_dates={date(2023, 12, 8)})
    out = m.apply_target(db, T_RL1)
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
    assert abs(out["continuity_after"] - 197 * 20 / 3840) < 1e-6      # 1.026


def test_apply_raises_when_continuity_breaks(db):
    """계수가 raw 갭과 맞지 않으면(예: 20 대신 5) 적용 후 직전/당일 비가 밴드 밖 → 예외(호출부 rollback)."""
    _seed(db, "RL1", RL1_ROWS, halt_dates={date(2023, 12, 8)})
    bad = m.Target("RL1", date(2023, 12, 27), 5.0, "cr", date(2023, 12, 8), "r1")
    with pytest.raises(RuntimeError, match="연속성"):
        m.apply_target(db, bad)


def test_apply_is_idempotent_when_event_already_recorded(db):
    _seed(db, "RL2", RL2_ROWS)
    assert m.apply_target(db, T_RL2)["applied_rows"] == 2
    out2 = m.apply_target(db, T_RL2)
    assert out2["applied_rows"] == 0 and out2["skipped"] == "recorded"


def test_apply_refuses_when_reference_already_adjusted(db):
    """사전 검사: 직전/당일 factor 비가 이미 coef 근방이면(그 사이 조정됨) 거부 — 이중 소급 방지. 기록도 남기지 않는다."""
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


@pytest.mark.parametrize("ratio,coef,kind,expect", [
    (1.0, 0.6667, "fric", "missing"),            # 무상 1:0.5 — 무상 밴드 1.15 라 adjusted 밴드[0.58,0.77]와 안 겹침
    (1.3, 20.0, "cr", "ambiguous"),              # 어느 밴드에도 없음
    (0.9, 1.0, "fric", "ambiguous"),             # 두 밴드가 겹치는 구간
    (18.0, 20.0, "cr", "already_adjusted"),
    (None, 5.0, "cr", "no_rows"),
])
def test_state_bands(ratio, coef, kind, expect):
    assert m._state(ratio, coef, kind) == expect


def test_apply_skips_ambiguous_and_no_rows_without_recording(db):
    _seed(db, "RL6", [(date(2023, 2, 22), 26300), (date(2023, 2, 23), 7190)], factor=1.0)
    with db.cursor() as cur:   # 직전 행만 ×1.3 → 비 1.3 (어느 밴드에도 없음)
        cur.execute("UPDATE daily_prices SET adj_close = adj_close * 1.3 WHERE ticker='RL6' AND date='2023-02-22'")
    t6 = m.Target("RL6", date(2023, 2, 23), 0.25, "fric", date(2023, 2, 23), "r6")
    assert m.apply_target(db, t6)["skipped"] == "ambiguous"
    t7 = m.Target("RL6", date(2023, 3, 1), 0.25, "fric", date(2023, 3, 1), "r7")      # 조정일 행 없음
    assert m.apply_target(db, t7)["skipped"] == "no_rows"
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM adj_factor_events WHERE ticker='RL6'")
        assert cur.fetchone()[0] == 0


def test_apply_refuses_post_seam_event_and_nearby_recorded_event(db):
    """시임 이후 조정일은 ingest_events 몫(거부). 같은 종목 ±60일 안에 coef 근방 이벤트 기록이 있으면 ambiguous_nearby_event."""
    _seed(db, "RL8", [(date(2026, 10, 1), 1000), (date(2026, 10, 2), 4000)])
    post = m.Target("RL8", date(2026, 10, 2), 4.0, "cr", date(2026, 10, 2), "r8")
    assert m.apply_target(db, post)["skipped"] == "post_seam_use_ingest_events"
    _seed(db, "RL9", [(date(2023, 2, 21), 25950), (date(2023, 2, 22), 26300), (date(2023, 2, 23), 7190)])
    adjust.record_events(db, "RL9", [(date(2023, 2, 22), 0.25)])        # 하루 전 날짜로 이미 기록됨(JSON 재생성 시나리오)
    t9 = m.Target("RL9", date(2023, 2, 23), 0.25, "fric", date(2023, 2, 23), "r9")
    out = m.apply_target(db, t9)
    assert out["skipped"] == "ambiguous_nearby_event" and out["plan"]["nearby_events"] == [("2023-02-22", 0.25)]


def test_two_events_same_ticker_compose(db):
    """같은 종목 2건(2017 ×0.3333 → 2018 ×0.5) 순차 적용: 2017 이전 행 = ×(0.3333×0.5), 2017~2018 구간 = ×0.5, 2018 이후 불변."""
    _seed(db, "RLA", [(date(2017, 11, 8), 3000), (date(2017, 11, 9), 1000), (date(2018, 9, 13), 2000), (date(2018, 9, 14), 1000)])
    e1 = m.Target("RLA", date(2017, 11, 9), 0.3333, "fric", date(2017, 11, 9), "a")
    e2 = m.Target("RLA", date(2018, 9, 14), 0.5, "fric", date(2018, 9, 14), "b")
    assert m.apply_target(db, e1)["applied_rows"] == 1 and m.apply_target(db, e2)["applied_rows"] == 3
    with db.cursor() as cur:
        cur.execute("SELECT adj_close::float FROM daily_prices WHERE ticker='RLA' ORDER BY date")
        got = [round(x[0], 2) for x in cur.fetchall()]
    assert got == [round(3000 * 0.3333 * 0.5, 2), 500.0, 1000.0, 1000.0]
    assert adjust.load_events(db, "RLA") == [(date(2017, 11, 9), 0.3333), (date(2018, 9, 14), 0.5)]


def test_backup_and_restore_round_trip_all_columns(db):
    """backup = 조정일 이전 행의 adj 5열 스냅샷. restore = 5열 복원 + 이벤트 기록 삭제. 적용 안 된 건은 restore 가 건너뜀."""
    _seed(db, "RL2", RL2_ROWS, factor=2.0)
    before = m.backup_rows(db, T_RL2)
    assert [r["date"] for r in before] == ["2023-02-21", "2023-02-22"] and before[0]["adj_close"] == 51900.0
    assert m.restore_rows(db, T_RL2, before)["skipped"] == "not_applied"       # 적용 전 restore 는 무동작
    m.apply_target(db, T_RL2)
    r = m.restore_rows(db, T_RL2, before, backup_time=datetime(2000, 1, 1))
    assert r["restored_rows"] == 2 and r["warning"] is None
    assert m.backup_rows(db, T_RL2) == before
    with db.cursor() as cur:
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
    """스크립트는 kr_pipeline import 전에 KRX_ID/KRX_PW 를 비운다 — pykrx 가 import 시점에 로그인하는 것을 막는다(접촉 0).
    정적 검사(순서만 보증). 실제 미접촉은 conftest 동형 환경에서 실측(--plan 재실행 '환경 변수 미설정')."""
    src = open("scripts/issue122_adj_reload.py").read()
    blank = src.index('os.environ["KRX_ID"] = ""')
    assert blank < src.index("from kr_pipeline") and blank < src.index("import psycopg")
