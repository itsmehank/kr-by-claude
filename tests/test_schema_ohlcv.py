def test_daily_weekly_prices_have_adj_open_volume(db):
    with db.cursor() as cur:
        for tbl in ("daily_prices", "weekly_prices"):
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name=%s AND column_name = ANY(%s)",
                (tbl, ["adj_open", "adj_volume"]),
            )
            cols = {r[0] for r in cur.fetchall()}
            assert cols == {"adj_open", "adj_volume"}, f"{tbl} missing - {cols}"


def test_daily_prices_has_change_pct(db):
    """#207: KRX 등락률(기준가 대비) 저장 컬럼 — 기업행위 조정계수 자체 산출 입력."""
    with db.cursor() as cur:
        cur.execute("SELECT data_type FROM information_schema.columns WHERE table_name='daily_prices' AND column_name='change_pct'")
        row = cur.fetchone()
    assert row is not None and row[0] == "numeric"
