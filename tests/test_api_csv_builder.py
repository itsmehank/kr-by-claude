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


# --- (#99) daily.csv 17지표 일원화 + weekly_ohlcv.csv 전환 ---

def test_daily_indicator_columns_include_rs_line_flags():
    """(#99) payload.indicators_recent_60d 제거 후 daily.csv 가 지표 시계열의 유일
    표현 — JSON 에만 있던 rs_line 3열이 헤더에 있어야 무손실."""
    from api.services.csv_builder import DAILY_INDICATOR_COLUMNS
    assert DAILY_INDICATOR_COLUMNS[-3:] == [
        "rs_line_at_52w_high", "rs_line_uptrend_6w", "rs_line_uptrend_13w",
    ]
    assert len(DAILY_INDICATOR_COLUMNS) == 17


def test_daily_csv_parity_with_fetch_indicators_recent(db):
    """(#99) 일원화 무손실 근거: daily.csv 17개 지표열 == _fetch_indicators_recent.

    비교 정규화(LOOP_SPEC DC-2): ""<->None, "TRUE"/"FALSE"<->bool, 그 외 float()
    (rs_rating 은 int). 컬럼 매핑 avg_volume_50d<->volume_ma_50,
    volume_ratio_50d<->volume_ratio. volume 열은 의도적 제외 — daily.csv 는
    daily_prices 의 COALESCE(adj,raw), 구 JSON 은 daily_indicators.volume(halt 시
    null)로 소스·결측 규약이 원래 다르다(스펙 §11 수용).
    """
    import csv as _csv
    import io as _io
    from datetime import date, timedelta
    from api.services.csv_builder import build_daily_csv, DAILY_INDICATOR_COLUMNS
    from api.services.payload_builder import _fetch_indicators_recent

    t = "PARITY1"
    on_date = date(2026, 5, 20)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'P','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
        for i in range(5):
            d = on_date - timedelta(days=4 - i)
            close = 100.0 + i
            cur.execute(
                """INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,1000,100000)""",
                (t, d, close, close, close, close, close),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                     (ticker,date,adj_close,volume,sma_10,sma_21,sma_50,sma_150,sma_200,
                      w52_high,w52_low,rs_line,rs_rating,minervini_pass,
                      avg_volume_50d,volume_ratio_50d,pocket_pivot_flag,distribution_day_flag,
                      rs_line_at_52w_high,rs_line_uptrend_6w,rs_line_uptrend_13w)
                   VALUES (%s,%s,%s,1000,%s,%s,%s,%s,%s,110,90,1.5,%s,TRUE,
                           1234.5,0.8,FALSE,%s,TRUE,%s,FALSE)""",
                (t, d, close, close, close, close, close,
                 None if i == 2 else close,      # sma_200 결측 케이스
                 90 + i,
                 None if i == 0 else True,        # distribution_day_flag 결측 케이스
                 None if i == 4 else False),      # rs_line_uptrend_6w 결측 케이스
            )
    db.commit()
    csv_to_json_key = {"avg_volume_50d": "volume_ma_50", "volume_ratio_50d": "volume_ratio"}
    int_cols = {"rs_rating"}
    try:
        text = build_daily_csv(db, t, days=60, on_date=on_date).decode("utf-8")
        rows = list(_csv.DictReader(_io.StringIO(text)))
        expected = _fetch_indicators_recent(db, t, on_date, days=60)
        assert len(rows) == len(expected) == 5
        for csv_row, exp in zip(rows, expected):
            assert csv_row["date"] == exp["date"]  # 행 순서·날짜 동일
            for col in DAILY_INDICATOR_COLUMNS:
                raw = csv_row[col]
                if raw == "":
                    norm = None
                elif raw in ("TRUE", "FALSE"):
                    norm = raw == "TRUE"
                elif col in int_cols:
                    norm = int(raw)
                else:
                    norm = float(raw)
                assert norm == exp[csv_to_json_key.get(col, col)], f"{csv_row['date']} {col}"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
        db.commit()


def test_build_weekly_ohlcv_csv_matches_fetch_weekly_ohlcv(db):
    """(#99) weekly_ohlcv.csv == payload 구 weekly_ohlcv_recent_104w(JSON) —
    얇은 포매터라 구조적으로 동일해야 하고, 여기서 값 동일성을 회귀 고정."""
    import csv as _csv
    import io as _io
    from datetime import date
    from api.services.csv_builder import build_weekly_ohlcv_csv, WEEKLY_OHLCV_COLUMNS
    from api.services.payload_builder import _fetch_weekly_ohlcv

    t = "WOHLCV1"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'W','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
        # adj 있는 주 + adj 없는(raw 폴백) 주 (volume 은 스키마 NOT NULL — NULL 케이스 없음)
        cur.execute(
            """INSERT INTO weekly_prices
                 (ticker,week_end_date,open,high,low,close,adj_close,adj_open,adj_high,adj_low,adj_volume,volume,value,trading_days)
               VALUES (%s,'2026-01-02',10000,10500,9800,10000,2000,2000,2100,1960,500.0,1000,10000000,5),
                      (%s,'2026-01-09',10100,10600,9900,10200,10200,NULL,NULL,NULL,NULL,1100,11000000,5)""",
            (t, t),
        )
    db.commit()
    try:
        text = build_weekly_ohlcv_csv(db, t, weeks=104, on_date=date(2026, 1, 31)).decode("utf-8")
        rows = list(_csv.DictReader(_io.StringIO(text)))
        expected = _fetch_weekly_ohlcv(db, t, date(2026, 1, 31), weeks=104)
        assert list(rows[0].keys()) == WEEKLY_OHLCV_COLUMNS
        assert len(rows) == len(expected) == 2
        for csv_row, exp in zip(rows, expected):
            for col in WEEKLY_OHLCV_COLUMNS:
                raw = csv_row[col]
                if col in ("week_start", "week_end"):
                    norm = raw
                elif raw == "":
                    norm = None
                elif col == "volume":
                    norm = int(raw)
                else:
                    norm = float(raw)
                assert norm == exp[col], f"{csv_row['week_end']} {col}"
        # adj 우선/raw 폴백 스팟 값 + week_start=week_end-4d
        assert rows[0]["open"] == "2000.0" and rows[0]["volume"] == "500"
        assert rows[1]["open"] == "10100.0" and rows[1]["volume"] == "1100"
        assert rows[0]["week_start"] == "2025-12-29" and rows[0]["week_end"] == "2026-01-02"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
        db.commit()
