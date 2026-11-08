"""(#184) volume_regime_flag_ver 이관 SQL — as_of ≥ 2026-09-28 의 NULL 행만 1(구 창), 멱등, system 행 제외, writer 의 2 는 불변."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SQL = Path(__file__).parent.parent / "scripts" / "sql" / "issue184_flag_ver_migrate.sql"
B = date(2026, 9, 28)


def test_migrate_sets_ver1_only_for_null_rows_on_or_after_boundary(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRV1','VRV1','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM weekly_classification WHERE symbol='VRV1'")
        rows = [(B - timedelta(days=3), None), (B, None), (B + timedelta(days=7), 2)]          # 전·후·이미 2
        for i, (d, ver) in enumerate(rows):
            cur.execute("INSERT INTO weekly_classification (symbol, classified_at, analyzed_for_date, market, classification, source, volume_regime_flag_ver) "
                        "VALUES ('VRV1', %s, %s, 'KOSPI', 'watch', 'llm', %s)", (datetime(2026, 9, 25 + i, tzinfo=timezone.utc), d, ver))
        cur.execute("INSERT INTO weekly_classification (symbol, classified_at, analyzed_for_date, market, classification, source) "
                    "VALUES ('VRV1', %s, %s, 'KOSPI', 'disqualified', 'system_disqualify')", (datetime(2026, 10, 9, tzinfo=timezone.utc), B + timedelta(days=10)))
        cur.execute(SQL.read_text()); cur.execute(SQL.read_text())                            # 2회 = 멱등
        cur.execute("SELECT analyzed_for_date, source, volume_regime_flag_ver FROM weekly_classification WHERE symbol='VRV1' ORDER BY classified_at")
        got = cur.fetchall()
    assert [r[2] for r in got] == [None, 1, 2, None]


def test_migrate_covers_position_evaluations_by_eval_date(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRV2','VRV2','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("DELETE FROM position_climax_evaluations WHERE position_id IN (SELECT id FROM positions WHERE symbol='VRV2')")
        cur.execute("DELETE FROM positions WHERE symbol='VRV2'")
        cur.execute("INSERT INTO positions (symbol, entry_date, entry_price, quantity, status) VALUES ('VRV2', %s, 1000, 1, 'open') RETURNING id", (B,))
        pid = cur.fetchone()[0]
        for d in (B - timedelta(days=1), B):
            cur.execute("INSERT INTO position_climax_evaluations (position_id, eval_date, fired, suppressed, hold_days, mode) VALUES (%s,%s,NULL,false,1,'quality')", (pid, d))
        cur.execute(SQL.read_text())
        cur.execute("SELECT eval_date, volume_regime_flag_ver FROM position_climax_evaluations WHERE position_id=%s ORDER BY eval_date", (pid,))
        got = cur.fetchall()
    assert [r[1] for r in got] == [None, 1]
