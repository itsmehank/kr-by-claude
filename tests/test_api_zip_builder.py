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
