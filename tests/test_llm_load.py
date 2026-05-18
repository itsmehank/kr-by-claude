"""get_qualifying_tickers fallback 동작."""
from datetime import date, datetime, timezone


def test_get_qualifying_tickers_falls_back_to_most_recent(db):
    """as_of 에 daily_indicators 없으면 그 이전 가장 최근 날짜 사용."""
    from kr_pipeline.llm_runner.load import get_qualifying_tickers

    with db.cursor() as cur:
        # 격리 — 테스트 날짜 범위 정리
        cur.execute("DELETE FROM daily_indicators WHERE date BETWEEN '2026-05-14' AND '2026-05-18'")
        cur.execute("DELETE FROM stocks WHERE ticker IN ('TEST01','TEST02')")
        cur.execute(
            """INSERT INTO stocks (ticker, name, market, sector, listed_at)
               VALUES ('TEST01','Test1','KOSPI','금융','2020-01-01'),
                      ('TEST02','Test2','KOSPI','금융','2020-01-01')"""
        )
        # 금요일 5/15 의 daily_indicators 만 적재 (월 5/18 데이터 없음)
        cur.execute(
            """INSERT INTO daily_indicators (ticker, date, adj_close, minervini_pass, drawdown_filter_pass)
               VALUES ('TEST01','2026-05-15',1000.0, TRUE, TRUE),
                      ('TEST02','2026-05-15',2000.0, TRUE, TRUE)"""
        )
    db.commit()

    # 월요일 5/18 기준으로 호출 → 5/15 데이터 fallback
    result = get_qualifying_tickers(db, as_of=date(2026, 5, 18))
    tickers = {r["symbol"] for r in result}
    assert "TEST01" in tickers
    assert "TEST02" in tickers


def test_get_qualifying_tickers_exact_match(db):
    """as_of 에 daily_indicators 있으면 그 날짜 사용 (기존 동작)."""
    from kr_pipeline.llm_runner.load import get_qualifying_tickers

    with db.cursor() as cur:
        cur.execute("DELETE FROM daily_indicators WHERE date = '2026-05-16'")
        cur.execute("DELETE FROM stocks WHERE ticker = 'TEST03'")
        cur.execute(
            """INSERT INTO stocks (ticker, name, market, sector, listed_at)
               VALUES ('TEST03','Test3','KOSDAQ','반도체','2020-01-01')"""
        )
        cur.execute(
            """INSERT INTO daily_indicators (ticker, date, adj_close, minervini_pass, drawdown_filter_pass)
               VALUES ('TEST03','2026-05-16', 3000.0, TRUE, TRUE)"""
        )
    db.commit()

    result = get_qualifying_tickers(db, as_of=date(2026, 5, 16))
    assert any(r["symbol"] == "TEST03" for r in result)


def test_get_qualifying_tickers_default_uses_global_max(db):
    """as_of=None 이면 daily_indicators 의 전체 MAX(date) 사용 (기존 default)."""
    from kr_pipeline.llm_runner.load import get_qualifying_tickers
    # 그냥 호출 — 에러 없이 반환 (실제 데이터에 의존)
    result = get_qualifying_tickers(db, as_of=None)
    assert isinstance(result, list)
