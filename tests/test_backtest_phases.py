from datetime import date


def test_phase_at_nearest_on_or_before():
    from kr_pipeline.backtest.phases import phase_at
    pm = [(date(2023, 1, 2), "downtrend"), (date(2023, 1, 5), "rally_attempt"),
          (date(2023, 1, 9), "confirmed_uptrend")]
    assert phase_at(pm, date(2023, 1, 1)) is None       # 이전 데이터 없음
    assert phase_at(pm, date(2023, 1, 2)) == "downtrend"
    assert phase_at(pm, date(2023, 1, 7)) == "rally_attempt"   # 1/5 의 값
    assert phase_at(pm, date(2023, 1, 30)) == "confirmed_uptrend"


def test_load_phase_map_orders_and_filters(db):
    from kr_pipeline.backtest.phases import load_phase_map
    with db.cursor() as cur:
        cur.execute("DELETE FROM market_context_daily WHERE index_code='9999'")
        cur.execute("INSERT INTO market_context_daily (date,index_code,current_status) "
                    "VALUES ('2023-02-01','9999','correction'),('2023-01-01','9999','downtrend')")
    db.commit()
    try:
        pm = load_phase_map(db, "9999")
        assert [d for d, _ in pm] == sorted(d for d, _ in pm)   # 오름차순
        assert pm[0][1] == "downtrend"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM market_context_daily WHERE index_code='9999'")
        db.commit()
