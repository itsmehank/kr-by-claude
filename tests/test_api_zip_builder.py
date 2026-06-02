import io
import zipfile
from datetime import date

from api.services.zip_builder import build_analysis_zip


def _seed_minimal(db, ticker="ZIP1"):
    """ZIP 빌더 동작 위해 최소한 종목 + 지표 1행."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market, sector) VALUES (%s, 'Z', 'KOSPI', 'IT') ON CONFLICT DO NOTHING", (ticker,))
        cur.execute("""
            INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value)
            VALUES (%s, '2026-05-17', 100, 105, 95, 100, 100, 1000, 100000)
            ON CONFLICT DO NOTHING
        """, (ticker,))
        cur.execute("""
            INSERT INTO daily_indicators (ticker, date, adj_close, volume, sma_50, sma_150, sma_200, w52_high, w52_low, rs_rating, minervini_pass)
            VALUES (%s, '2026-05-17', 100, 1000, 90, 85, 80, 110, 70, 95, TRUE)
            ON CONFLICT DO NOTHING
        """, (ticker,))
    db.commit()


def test_build_analysis_zip_contains_13_files(db):
    """ZIP 에 13 파일 모두 있는지 확인."""
    _seed_minimal(db)
    zip_bytes = build_analysis_zip(db, "ZIP1", on_date=date(2026, 5, 17))

    assert isinstance(zip_bytes, bytes)
    assert len(zip_bytes) > 5000

    expected_files = {
        "README.md", "prompt_step1_analyze.md", "prompt_step2_entry_params.md",
        "payload.json", "market_context.json", "corporate_actions.json",
        "minervini.json", "daily.csv", "weekly.csv",
        "market_index_daily.csv", "market_index_weekly.csv",
        "daily_chart.png", "weekly_chart.png",
    }

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        actual_files = set(zf.namelist())

    assert expected_files == actual_files


def test_build_zip_payload_json_valid(db):
    """payload.json 이 valid JSON 인지."""
    import json
    _seed_minimal(db, "ZIP2")
    zip_bytes = build_analysis_zip(db, "ZIP2", on_date=date(2026, 5, 17))
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        payload_bytes = zf.read("payload.json")
    payload = json.loads(payload_bytes.decode("utf-8"))
    assert payload["symbol"] == "ZIP2"
    assert payload["market"] == "KOSPI"


def test_build_analysis_zip_excludes_data_after_on_date(db):
    from datetime import date, timedelta
    import io, zipfile, csv as _csv
    from api.services.zip_builder import build_analysis_zip
    from api.services.market_context_builder import INDEX_CODE_MAP
    t = "ASOFZIP1"
    on_date = date(2025, 6, 10)
    market = "KOSPI"
    idx = INDEX_CODE_MAP.get(market, "1001")
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'Z',%s) ON CONFLICT DO NOTHING", (t, market))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
        for i in range(20):
            d = date(2025, 6, 1) + timedelta(days=i)
            cur.execute(
                """INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value)
                   VALUES (%s,%s,100,105,95,100,%s,1000,100000) ON CONFLICT DO NOTHING""",
                (t, d, 100 + i),
            )
        for i in range(20):
            d = date(2025, 6, 1) + timedelta(days=i)
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value)
                   VALUES (%s,%s,10,11,9,10,1000,100000) ON CONFLICT DO NOTHING""",
                (idx, d),
            )
    db.commit()
    try:
        zip_bytes = build_analysis_zip(db, t, on_date=on_date)
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        for name in ("daily.csv", "market_index_daily.csv"):
            text = zf.read(name).decode("utf-8")
            rows = list(_csv.reader(io.StringIO(text)))
            dates = [r[0] for r in rows[1:] if r and r[0]]
            assert dates, f"{name}: 행이 있어야 함"
            assert max(dates) <= on_date.isoformat(), f"{name}: on_date 이후 데이터 누수 — max={max(dates)}"
            assert on_date.isoformat() in dates, f"{name}: on_date 당일 포함되어야"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM index_daily WHERE index_code=%s AND date >= '2025-06-01' AND date <= '2025-06-30'", (idx,))
        db.commit()


def test_fetch_latest_analysis_result_by_analyzed_for_date(db):
    from api.services.zip_builder import _fetch_latest_analysis_result
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='AXZIP1'")
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('AXZIP1','A','KOSPI') ON CONFLICT DO NOTHING")
        # 데이터 최신 = entry (어제), 실행 2일 전
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source, confidence)
               VALUES ('AXZIP1', NOW() - INTERVAL '2 day', CURRENT_DATE - 1, 'KOSPI', 'entry', 'weekend', 0.9)"""
        )
        # 백필성 ignore (30일전), 실행 방금
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source, confidence)
               VALUES ('AXZIP1', NOW(), CURRENT_DATE - 30, 'KOSPI', 'ignore', 'weekend', 0.3)"""
        )
    db.commit()
    try:
        result = _fetch_latest_analysis_result(db, "AXZIP1")
        assert result is not None
        assert result["classification"] == "entry"  # analyzed_for_date 최신
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='AXZIP1'")
        db.commit()
