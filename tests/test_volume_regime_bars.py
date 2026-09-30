"""#207 회신 21 Q-5c 1 — 봉 단위 volume_regime + 판정 행 flag(PR-2 규칙)."""
from datetime import date, datetime, timedelta, timezone

from kr_pipeline.common.data_regimes import (
    FLAG_MIXED, REGIME_EXTENDED, REGIME_MIXED, REGIME_REGULAR, VOLUME_REGIME_BOUNDARY,
    VOLUME_REGIME_UNVERIFIED_FROM, regime_flag_for_as_of, regime_for_date,
)

B = VOLUME_REGIME_BOUNDARY


def test_constants_and_alias():
    assert VOLUME_REGIME_UNVERIFIED_FROM == B
    assert (REGIME_REGULAR, REGIME_EXTENDED, REGIME_MIXED, FLAG_MIXED) == ("regular", "extended", "mixed", "mixed")


def test_regime_for_date_boundary():
    assert regime_for_date(B - timedelta(days=1)) == "regular"
    assert regime_for_date(B) == "extended"


def test_regime_flag_for_as_of_pr2_rule():
    assert regime_flag_for_as_of(None) is None
    assert regime_flag_for_as_of(B - timedelta(days=1)) is None
    assert regime_flag_for_as_of(B) == "mixed"
    assert regime_flag_for_as_of(datetime(B.year, B.month, B.day, 9, tzinfo=timezone.utc)) == "mixed"
    assert regime_flag_for_as_of(B.isoformat()) == "mixed"


def test_schema_columns_exist(db):
    with db.cursor() as cur:
        for table in ("daily_prices", "index_daily", "weekly_prices"):
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s AND column_name='volume_regime'", (table,))
            assert cur.fetchone(), table
        for table in ("weekly_classification", "trigger_evaluation_log", "entry_params",
                      "position_climax_evaluations", "position_decline_evaluations"):
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s AND column_name='volume_regime_flag'", (table,))
            assert cur.fetchone(), table


# ── Task 2: 일봉·지수 저장 SQL 이 regime 기록 ──────────────────────────────
from kr_pipeline.ohlcv.store import upsert_daily_prices, upsert_index_daily


def _price_row(ticker, d):
    return (ticker, d, 100, 110, 90, 105, 105.0, 110.0, 90.0, 100.0, 1000.0, 1000, 105000, 1.5)


def test_upsert_daily_prices_writes_regime_by_date(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRB1','VRB1','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM daily_prices WHERE ticker='VRB1'")
    before, at = B - timedelta(days=1), B
    upsert_daily_prices(db, [_price_row("VRB1", before), _price_row("VRB1", at)])
    with db.cursor() as cur:
        cur.execute("SELECT date, volume_regime FROM daily_prices WHERE ticker='VRB1' ORDER BY date")
        assert cur.fetchall() == [(before, "regular"), (at, "extended")]
    upsert_daily_prices(db, [_price_row("VRB1", at)])          # 재적재도 동일(기본값 'regular' 로 덮지 않음)
    with db.cursor() as cur:
        cur.execute("SELECT volume_regime FROM daily_prices WHERE ticker='VRB1' AND date=%s", (at,))
        assert cur.fetchone()[0] == "extended"


def test_upsert_index_daily_writes_regime_by_date(db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM index_daily WHERE index_code='VRIDX'")
    upsert_index_daily(db, [("VRIDX", B - timedelta(days=1), 100.0, 101.0, 99.0, 100.5, 10, 20),
                            ("VRIDX", B, 100.0, 101.0, 99.0, 100.5, 10, 20)])
    with db.cursor() as cur:
        cur.execute("SELECT date, volume_regime FROM index_daily WHERE index_code='VRIDX' ORDER BY date")
        assert [r[1] for r in cur.fetchall()] == ["regular", "extended"]


# ── Task 3: 주봉 regime(regular/extended/mixed) ────────────────────────────
from kr_pipeline.weekly.store import upsert_weekly_prices


def _week_row(ticker, week_end):
    return (ticker, week_end, 100, 110, 90, 105, 105.0, 110.0, 90.0, 100.0, 5000.0, 5000, 525000, 5)


def test_upsert_weekly_prices_regime_regular_extended(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRW1','VRW1','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM weekly_prices WHERE ticker='VRW1'")
    upsert_weekly_prices(db, [_week_row("VRW1", date(2026, 9, 25)), _week_row("VRW1", date(2026, 10, 2))])
    with db.cursor() as cur:
        cur.execute("SELECT week_end_date, volume_regime FROM weekly_prices WHERE ticker='VRW1' ORDER BY 1")
        assert cur.fetchall() == [(date(2026, 9, 25), "regular"), (date(2026, 10, 2), "extended")]


def test_weekly_regime_mixed_when_week_straddles_boundary(db, monkeypatch):
    """경계를 수요일(가상)로 두면 그 주는 mixed — SQL 규칙(월요일 < 경계 ≤ week_end) 검증."""
    import kr_pipeline.weekly.store as ws
    monkeypatch.setattr(ws, "VOLUME_REGIME_BOUNDARY", date(2026, 9, 30))
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRW2','VRW2','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM weekly_prices WHERE ticker='VRW2'")
    upsert_weekly_prices(db, [_week_row("VRW2", date(2026, 10, 2))])
    with db.cursor() as cur:
        cur.execute("SELECT volume_regime FROM weekly_prices WHERE ticker='VRW2'")
        assert cur.fetchone()[0] == "mixed"
