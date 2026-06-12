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


def test_build_analysis_zip_contains_14_files(db):
    """원본 분석 ZIP = 14 파일 (분류 이력 없을 때 — prompt_verify.md 는 항상 포함).

    (stale 정정: prompt_verify.md 추가 후 13→14 가 됐는데 테스트가 미갱신돼
    baseline 상시 실패로 방치돼 있었다.)"""
    _seed_minimal(db)
    zip_bytes = build_analysis_zip(db, "ZIP1", on_date=date(2026, 5, 17))

    assert isinstance(zip_bytes, bytes)
    assert len(zip_bytes) > 5000

    expected_files = {
        "README.md", "prompt_step1_analyze.md", "prompt_step2_entry_params.md",
        "prompt_verify.md",
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

    # Weekly dates straddling on_date: 6 weeks before/at, 3 weeks after
    weekly_dates = [
        date(2025, 5, 2),
        date(2025, 5, 9),
        date(2025, 5, 16),
        date(2025, 5, 23),
        date(2025, 5, 30),
        date(2025, 6, 6),   # last week_end_date <= on_date(2025-06-10)
        date(2025, 6, 13),  # after on_date — must be excluded
        date(2025, 6, 20),
        date(2025, 6, 27),
    ]
    last_weekly_before_cutoff = "2025-06-06"

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'Z',%s) ON CONFLICT DO NOTHING", (t, market))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
        cur.execute(
            "DELETE FROM weekly_index WHERE index_code=%s AND week_end_date >= '2025-05-01' AND week_end_date <= '2025-06-30'",
            (idx,),
        )
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
        # Seed weekly_indicators straddling on_date
        for wd in weekly_dates:
            cur.execute(
                """INSERT INTO weekly_indicators (ticker, week_end_date, adj_close)
                   VALUES (%s, %s, 100) ON CONFLICT DO NOTHING""",
                (t, wd),
            )
        # Seed weekly_index straddling on_date
        for wd in weekly_dates:
            cur.execute(
                """INSERT INTO weekly_index (index_code, week_end_date, open, high, low, close, trading_days)
                   VALUES (%s, %s, 10, 11, 9, 10, 5) ON CONFLICT DO NOTHING""",
                (idx, wd),
            )
    db.commit()
    try:
        zip_bytes = build_analysis_zip(db, t, on_date=on_date)
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))

        # --- Daily CSV assertions (exact on_date match) ---
        for name in ("daily.csv", "market_index_daily.csv"):
            text = zf.read(name).decode("utf-8")
            rows = list(_csv.reader(io.StringIO(text)))
            dates = [r[0] for r in rows[1:] if r and r[0]]
            assert dates, f"{name}: 행이 있어야 함"
            assert max(dates) <= on_date.isoformat(), f"{name}: on_date 이후 데이터 누수 — max={max(dates)}"
            assert on_date.isoformat() in dates, f"{name}: on_date 당일 포함되어야"

        # --- Weekly CSV assertions (week_end_date won't equal on_date exactly) ---
        for name, date_col_idx in (("weekly.csv", 0), ("market_index_weekly.csv", 0)):
            text = zf.read(name).decode("utf-8")
            rows = list(_csv.reader(io.StringIO(text)))
            dates = [r[date_col_idx] for r in rows[1:] if r and r[date_col_idx]]
            assert dates, f"{name}: 주간 행이 있어야 함"
            assert max(dates) <= on_date.isoformat(), (
                f"{name}: on_date 이후 데이터 누수 — max={max(dates)}"
            )
            assert last_weekly_before_cutoff in dates, (
                f"{name}: 마지막 주(cutoff 직전 {last_weekly_before_cutoff}) 포함되어야 — dates={dates}"
            )
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
            cur.execute(
                "DELETE FROM index_daily WHERE index_code=%s AND date >= '2025-06-01' AND date <= '2025-06-30'",
                (idx,),
            )
            cur.execute(
                "DELETE FROM weekly_index WHERE index_code=%s AND week_end_date >= '2025-05-01' AND week_end_date <= '2025-06-30'",
                (idx,),
            )
        db.commit()


def test_build_analysis_zip_skips_prior_analysis_when_disabled(db):
    import io, zipfile
    from datetime import date, timedelta
    from api.services.zip_builder import build_analysis_zip
    t = "ZIPNOPRIOR"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'Z','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (t,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        # 라이브 분류 1건 (verify-mode 트리거가 됨).
        # NOTE: analysis_result 도 on_date 이하만 포함되므로 on_date(2025-06-10) 이전으로 시드.
        cur.execute(
            """INSERT INTO weekly_classification (symbol, classified_at, market, classification, source)
               VALUES (%s, '2025-06-09T12:00:00+00', 'KOSPI', 'watch', 'weekend')""", (t,))
        # 약간의 가격 데이터
        for i in range(10):
            d = date(2025, 6, 1) + timedelta(days=i)
            cur.execute("""INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value)
                           VALUES (%s,%s,100,105,95,100,100,1000,100000) ON CONFLICT DO NOTHING""", (t, d))
    db.commit()
    try:
        z_with = zipfile.ZipFile(io.BytesIO(build_analysis_zip(db, t, on_date=date(2025,6,10))))
        z_without = zipfile.ZipFile(io.BytesIO(build_analysis_zip(db, t, on_date=date(2025,6,10), include_prior_analysis=False)))
        assert "analysis_result.json" in z_with.namelist()        # 기본: verify-mode 포함
        assert "analysis_result.json" not in z_without.namelist()  # 백필: 미포함
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (t,))
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
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
        result = _fetch_latest_analysis_result(db, "AXZIP1", on_date=__import__("datetime").date.today())
        assert result is not None
        assert result["classification"] == "entry"  # analyzed_for_date 최신
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol='AXZIP1'")
        db.commit()


def test_fetch_latest_analysis_result_bounded_by_on_date(db):
    """검증 ZIP 의 analysis_result 도 on_date 이하 분류여야 한다 — 상한 없으면
    과거 시점 ZIP 에 그 이후 분류가 들어가 README 분석 기준일과 모순 (look-ahead,
    corporate_actions ce10e56 과 동일 클래스)."""
    from datetime import date, datetime
    from api.services.zip_builder import _fetch_latest_analysis_result

    t = "ZIPLA1"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (t,))
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, analyzed_for_date, market, classification, source)
               VALUES (%s, %s, %s, 'KOSPI', 'watch', 'weekend'),
                      (%s, %s, %s, 'KOSPI', 'entry', 'weekend')""",
            (t, datetime(2026, 3, 7, 4, 0), date(2026, 3, 6),
             t, datetime(2026, 4, 4, 4, 0), date(2026, 4, 3)),
        )
    db.commit()

    try:
        result = _fetch_latest_analysis_result(db, t, on_date=date(2026, 3, 20))
        assert result is not None
        assert result["classification"] == "watch", (
            f"on_date(3/20) 이후의 분류(4/3 {result['classification']})가 새어 들어옴"
        )
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_classification WHERE symbol=%s", (t,))
        db.commit()
