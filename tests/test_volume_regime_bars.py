"""#207 회신 21 Q-5c 1 — 봉 단위 volume_regime + 판정 행 flag(PR-2 규칙)."""
from datetime import date, datetime, timedelta, timezone

from kr_pipeline.common.data_regimes import (
    FLAG_MIXED, REGIME_EXTENDED, REGIME_MIXED, REGIME_REGULAR, VOLUME_REGIME_BOUNDARY,
    VOLUME_REGIME_UNVERIFIED_FROM, regime_flag_for_as_of, regime_for_date, regime_for_week,
)

B = VOLUME_REGIME_BOUNDARY


def test_constants_and_alias():
    assert VOLUME_REGIME_UNVERIFIED_FROM == B
    assert (REGIME_REGULAR, REGIME_EXTENDED, REGIME_MIXED, FLAG_MIXED) == ("regular", "extended", "mixed", "mixed")


def test_regime_for_date_boundary():
    assert regime_for_date(B - timedelta(days=1)) == "regular"
    assert regime_for_date(B) == "extended"


def test_regime_for_week_rule(monkeypatch):
    """주봉: 주의 월요일(ISO)·금요일(week_end) 과 경계 — 둘 다 전 regular / 월요일 ≥ 경계 extended / 그 외 mixed.
    달력 월요일 기준(그 주 첫 거래일이 휴일이어도)은 보수적(mixed 쪽) 선택 — 2차 리뷰 기록."""
    assert regime_for_week(date(2026, 9, 25)) == "regular"
    assert regime_for_week(date(2026, 10, 2)) == "extended"
    import kr_pipeline.common.data_regimes as m
    monkeypatch.setattr(m, "VOLUME_REGIME_BOUNDARY", date(2026, 9, 30))      # 수요일 경계(가상)
    assert regime_for_week(date(2026, 10, 2)) == "mixed"
    assert regime_for_week(date(2026, 10, 9)) == "extended"


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
                      "position_climax_evaluations", "position_decline_evaluations",
                      "classification_backfill", "backtest_classification", "recall_audit_classification"):
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
    """경계를 수요일(가상)로 두면 그 주는 mixed — writer 가 Python regime_for_week 값을 저장(SQL CASE 아님)."""
    import kr_pipeline.common.data_regimes as m
    monkeypatch.setattr(m, "VOLUME_REGIME_BOUNDARY", date(2026, 9, 30))     # writer 는 regime_for_week(Python) 를 쓴다
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRW2','VRW2','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM weekly_prices WHERE ticker='VRW2'")
    upsert_weekly_prices(db, [_week_row("VRW2", date(2026, 10, 2))])
    with db.cursor() as cur:
        cur.execute("SELECT volume_regime FROM weekly_prices WHERE ticker='VRW2'")
        assert cur.fetchone()[0] == "mixed"


# ── Task 6: 이관 SQL 멱등 ──────────────────────────────────────────────────
from pathlib import Path


def test_migration_script_is_idempotent_and_moves_tags(db):
    sql = (Path(__file__).parent.parent / "scripts" / "sql" / "issue207_volume_regime_migrate.sql").read_text(encoding="utf-8")
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRM1','VRM1','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM daily_prices WHERE ticker='VRM1'"); cur.execute("DELETE FROM weekly_classification WHERE symbol='VRM1'")
        cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value, volume_regime) "
                    "VALUES ('VRM1', %s, 1,1,1,1,1,1,1,'regular')", (B,))
        cur.execute("INSERT INTO weekly_classification (symbol, classified_at, market, classification, pattern, source, analyzed_for_date, sanity_warnings) "
                    "VALUES ('VRM1', now(), 'KOSPI', 'watch', 'flat_base', 'weekend', %s, %s)", (B, '["x", "volume_regime_unverified_#207"]'))
    import psycopg, re
    code = re.sub(r"--[^\n]*", "", sql).upper()
    assert "BEGIN" not in code and "COMMIT" not in code, "스크립트는 트랜잭션 문을 갖지 않는다(psql -1 로 감쌈)"
    for _ in range(2):                       # 2회 실행 = 멱등
        with db.cursor() as cur:
            cur.execute(sql)
    # db 픽스처 격리 계약(conftest: 트랜잭션 → ROLLBACK). 스크립트 안의 COMMIT 은 이 트랜잭션을 실제 커밋해 시드 행을
    # kr_test 에 영구 남긴다(#220 리뷰 실측: VRM1 잔존) → 실행 뒤에도 트랜잭션이 열려 있어야 한다.
    assert db.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
    with db.cursor() as cur:
        cur.execute("SELECT volume_regime FROM daily_prices WHERE ticker='VRM1' AND date=%s", (B,)); assert cur.fetchone()[0] == "extended"
        cur.execute("SELECT volume_regime_flag, sanity_warnings FROM weekly_classification WHERE symbol='VRM1'")
        f, w = cur.fetchone(); assert f == "mixed" and w == ["x"]


def test_migration_sql_date_literals_equal_boundary_constant():
    """이관 SQL 의 날짜 리터럴은 전부 VOLUME_REGIME_BOUNDARY — 상수만 옮기고 SQL 을 안 고치면 재실행이 경계 사이 행을 되돌린다(2차 리뷰)."""
    import re
    sql = (Path(__file__).parent.parent / "scripts" / "sql" / "issue207_volume_regime_migrate.sql").read_text(encoding="utf-8")
    code = re.sub(r"--[^\n]*", "", sql)
    lits = set(re.findall(r"'(\d{4}-\d{2}-\d{2})'", code))
    assert lits == {B.isoformat()}, lits


def test_migration_does_not_flag_system_rows_and_unflags_them(db):
    """시스템 writer(system_disqualify·universe 배제)는 flag 를 쓰지 않는다 — 이관 SQL 이 그 행을 'mixed' 로 찍으면 안 되고,
    이미 찍힌 행(운영 8행 실측)은 NULL 로 되돌린다."""
    sql = (Path(__file__).parent.parent / "scripts" / "sql" / "issue207_volume_regime_migrate.sql").read_text(encoding="utf-8")
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRM2','VRM2','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM weekly_classification WHERE symbol='VRM2'")
        cur.execute("INSERT INTO weekly_classification (symbol, classified_at, market, classification, pattern, source, analyzed_for_date, volume_regime_flag) "
                    "VALUES ('VRM2', now(), 'KOSPI', 'disqualified', NULL, 'system_disqualify', %s, 'mixed')", (B,))
        cur.execute("INSERT INTO weekly_classification (symbol, classified_at, market, classification, pattern, source, analyzed_for_date, volume_regime_flag) "
                    "VALUES ('VRM2', now() - interval '1 day', 'KOSPI', 'watch', 'flat_base', 'daily_delta', %s, NULL)", (B,))
        cur.execute(sql)
        cur.execute("SELECT source, volume_regime_flag FROM weekly_classification WHERE symbol='VRM2' ORDER BY source")
        assert cur.fetchall() == [("daily_delta", "mixed"), ("system_disqualify", None)]


def test_ohlcv_sanity_warns_on_regime_column_mismatch(db):
    """저장된 volume_regime 이 날짜 규칙과 다르면 경고(운영 실측: 컬럼 선적용 + 구 writer → 09-30·10-01 'regular')."""
    from kr_pipeline.ohlcv import modes
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRS1','VRS1','KOSPI') ON CONFLICT (ticker) DO NOTHING")
        cur.execute("DELETE FROM daily_prices WHERE ticker='VRS1'")
        cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value, volume_regime) "
                    "VALUES ('VRS1', %s, 1,1,1,1,1,1,1,'regular')", (B,))
    warns = modes._run_sanity_checks(db, modes.Mode.INCREMENTAL)
    # 예시 종목 5개는 알파벳순이라 다른 테스트가 커밋한 기본값 행(예: PRV1)에 밀릴 수 있음 → 건수(≥1)만 단언
    hit = [w for w in warns if w.startswith("volume_regime_mismatch:")]
    assert hit and int(hit[0].split("daily_prices ")[1].split("행")[0]) >= 1, warns
