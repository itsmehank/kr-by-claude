from datetime import date, timedelta
from api.services.csv_builder import build_daily_csv, build_weekly_csv, build_index_csv


def _seed_daily(db, ticker="DAILY1", n=10):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s, 'D', 'KOSPI') ON CONFLICT DO NOTHING", (ticker,))
        for i in range(n):
            d = date(2026, 5, 1) + timedelta(days=i)
            # 가격·거래량 권위 소스 = daily_prices (Phase 0 Step 2 fix)
            cur.execute(
                """INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES (%s, %s, 100, 105, 95, 100, 100, 1000, 100000)
                   ON CONFLICT DO NOTHING""",
                (ticker, d),
            )
            cur.execute(
                """INSERT INTO daily_indicators (ticker, date, adj_close, volume, sma_50)
                   VALUES (%s, %s, 100, 1000, 95)
                   ON CONFLICT DO NOTHING""",
                (ticker, d),
            )
    db.commit()


def test_build_daily_csv_returns_bytes(db):
    _seed_daily(db, n=5)
    csv_bytes = build_daily_csv(db, "DAILY1", days=10)
    assert isinstance(csv_bytes, bytes)
    text = csv_bytes.decode("utf-8")
    assert "date" in text   # header
    assert "100" in text     # 값


def test_build_daily_csv_empty_ticker(db):
    """데이터 없는 종목 → header 만."""
    csv_bytes = build_daily_csv(db, "NOEXIST", days=10)
    text = csv_bytes.decode("utf-8")
    assert "date" in text
    # 한 줄 (header) 만
    assert len([l for l in text.strip().split("\n") if l]) == 1


def test_build_daily_csv_respects_on_date(db):
    from datetime import date, timedelta
    t = "ASOFD1"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'D','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        for i in range(20):
            d = date(2025, 6, 1) + timedelta(days=i)
            cur.execute(
                """INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value)
                   VALUES (%s,%s,100,105,95,100,%s,1000,100000) ON CONFLICT DO NOTHING""",
                (t, d, 100 + i),
            )
    db.commit()
    try:
        text = build_daily_csv(db, t, days=60, on_date=date(2025, 6, 10)).decode("utf-8")
        dates = [l.split(",")[0] for l in text.strip().split("\n")[1:]]
        assert "2025-06-10" in dates
        assert "2025-06-11" not in dates
        assert max(dates) == "2025-06-10"
        text2 = build_daily_csv(db, t, days=60).decode("utf-8")
        dates2 = [l.split(",")[0] for l in text2.strip().split("\n")[1:]]
        assert "2025-06-20" in dates2
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        db.commit()


def test_build_weekly_csv_respects_on_date(db):
    from datetime import date, timedelta
    t = "ASOFW1"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'W','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
        for i in range(10):
            wk = date(2025, 3, 7) + timedelta(weeks=i)
            cur.execute(
                """INSERT INTO weekly_indicators (ticker, week_end_date, adj_close, volume)
                   VALUES (%s,%s,%s,1000) ON CONFLICT DO NOTHING""",
                (t, wk, 100 + i),
            )
    db.commit()
    try:
        cutoff = date(2025, 3, 7) + timedelta(weeks=4)
        text = build_weekly_csv(db, t, weeks=104, on_date=cutoff).decode("utf-8")
        dates = [l.split(",")[0] for l in text.strip().split("\n")[1:]]
        later = (date(2025, 3, 7) + timedelta(weeks=5)).isoformat()
        assert cutoff.isoformat() in dates
        assert later not in dates
        assert max(dates) == cutoff.isoformat()
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
        db.commit()


def test_build_index_csv_respects_on_date(db):
    from datetime import date, timedelta
    code = "ASOFIDX"
    with db.cursor() as cur:
        cur.execute("DELETE FROM index_daily WHERE index_code=%s", (code,))
        for i in range(15):
            d = date(2025, 6, 1) + timedelta(days=i)
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value)
                   VALUES (%s,%s,10,11,9,10,1000,100000) ON CONFLICT DO NOTHING""",
                (code, d),
            )
    db.commit()
    try:
        text = build_index_csv(db, code, "daily", lookback=60, on_date=date(2025, 6, 8)).decode("utf-8")
        dates = [l.split(",")[0] for l in text.strip().split("\n")[1:]]
        assert "2025-06-08" in dates
        assert "2025-06-09" not in dates
        assert max(dates) == "2025-06-08"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM index_daily WHERE index_code=%s", (code,))
        db.commit()


def test_build_daily_csv_volume_is_adjusted(db):
    """기업행위 종목: daily.csv 의 volume 은 adj_volume(보정 거래량) 기준이어야 한다.

    payload(JSON)와 daily.csv 가 같은 LLM 입력에 들어가므로 도메인(raw/adj)이 갈리면
    같은 날 거래량이 두 숫자로 노출된다 — payload_builder(7850a0b)와 동일하게 adj 통일.
    adj_volume NULL(거래정지 등)이면 raw volume 폴백(payload_builder.py:102 와 동일 패턴).
    """
    t = "ADJVOL1"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'D','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        # 5:1 병합 가정 — raw 1000 → adj 200. adj_volume NULL 인 날 하나(폴백 확인).
        cur.execute(
            """INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,adj_volume,value)
               VALUES (%s,'2026-05-01',100,105,95,100,100,1000,200,100000)""", (t,))
        cur.execute(
            """INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,adj_volume,value)
               VALUES (%s,'2026-05-02',100,105,95,100,100,3000,NULL,100000)""", (t,))
    db.commit()
    try:
        text = build_daily_csv(db, t, days=10).decode("utf-8")
        lines = {l.split(",")[0]: l.split(",") for l in text.strip().split("\n")[1:]}
        vol_col = 2  # header: date, adj_close, volume, ...
        assert lines["2026-05-01"][vol_col] == "200", "adj_volume 이 있으면 보정값을 써야 함"
        assert lines["2026-05-02"][vol_col] == "3000", "adj_volume NULL 이면 raw 폴백"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        db.commit()
