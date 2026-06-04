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
