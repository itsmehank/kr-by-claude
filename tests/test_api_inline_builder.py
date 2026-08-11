"""#99 — inline_builder 입력 축소(무손실) 검증.

A. dedup: minervini.json/corporate_actions.json 블록은 payload.conditions_detail/
   payload.price_data_notes 와 동일하므로 인라인하지 않는다.
B. 블록 구성: payload 사본 제거는 daily.csv/weekly_ohlcv.csv 로의 표현 이동이며,
   블록 집합은 정확히 고정한다(다른 블록의 우발 탈락 방지 — 이슈가 "제거 금지"로
   못박은 daily_ohlcv/weekly.csv/market_index_*.csv/PNG 2장 보존).
"""
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest


def _seed_stock(db, ticker):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market, sector) "
            "VALUES (%s, 'P', 'KOSPI', '전기·전자') ON CONFLICT DO NOTHING",
            (ticker,),
        )
    db.commit()


def _seed_weekly(db, ticker, n, start):
    with db.cursor() as cur:
        for i in range(n):
            p = 1000.0 - 0.5 * i
            d = start + timedelta(weeks=i)
            cur.execute(
                """INSERT INTO weekly_prices
                     (ticker, week_end_date, open, high, low, close, adj_close,
                      volume, value, trading_days)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,5)
                   ON CONFLICT DO NOTHING""",
                (ticker, d, p, p * 1.02, p * 0.98, p, p, 100_000, 100_000 * p),
            )
    db.commit()


def _seed_daily(db, ticker, on_date, n=25):
    """daily_prices+daily_indicators 동일 값 시드 (check_data_integrity 통과)."""
    with db.cursor() as cur:
        for i in range(n):
            d = on_date - timedelta(days=(n - 1 - i))
            close = 80000.0 + i * 10
            cur.execute(
                """INSERT INTO daily_prices
                     (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (ticker, d, close, close * 1.01, close * 0.99, close, close,
                 1_000_000, 1_000_000 * close),
            )
            cur.execute(
                """INSERT INTO daily_indicators
                     (ticker, date, adj_close, volume, sma_50, rs_line,
                      distribution_day_flag, pocket_pivot_flag,
                      rs_line_at_52w_high, rs_line_uptrend_6w, rs_line_uptrend_13w)
                   VALUES (%s,%s,%s,%s,%s,%s,FALSE,FALSE,TRUE,FALSE,%s)
                   ON CONFLICT DO NOTHING""",
                (ticker, d, close, 1_000_000, close * 0.95, 1.23,
                 None if i == 0 else True),  # None 직렬화(빈칸) 케이스 포함
            )
    db.commit()


@pytest.fixture
def inline_result(db, mocker):
    from api.services.inline_builder import build_analysis_inline

    ticker = "INL99A"
    _seed_stock(db, ticker)
    start = date(2018, 1, 5)
    _seed_weekly(db, ticker, 40, start)
    on_date = start + timedelta(weeks=39)
    _seed_daily(db, ticker, on_date, n=25)

    mocker.patch("api.services.inline_builder.render_daily_chart", return_value=b"DPNG")
    mocker.patch("api.services.inline_builder.render_weekly_chart", return_value=b"WPNG")

    inline_text, png_paths, freeze_bytes, gates = build_analysis_inline(db, ticker, on_date)
    yield inline_text, png_paths
    shutil.rmtree(str(Path(png_paths[0]).parent), ignore_errors=True)


def _block_headers(inline_text: str) -> list[str]:
    return re.findall(r"^### (.+)$", inline_text, flags=re.MULTILINE)


def test_inline_dedup_blocks_removed_but_payload_keys_present(inline_result):
    """A: minervini.json/corporate_actions.json 블록 부재 + 동일 정보가
    payload 블록(conditions_detail/price_data_notes)에 존재."""
    inline_text, _ = inline_result
    headers = _block_headers(inline_text)
    assert "minervini.json" not in headers
    assert "corporate_actions.json" not in headers
    assert '"conditions_detail"' in inline_text
    assert '"price_data_notes"' in inline_text


def test_inline_block_exact_set_and_two_pngs(inline_result):
    """블록 정확 집합 — 우발 탈락/추가 방지 (이슈 '제거 금지' 목록 보존)."""
    inline_text, png_paths = inline_result
    assert _block_headers(inline_text) == [
        "payload.json",
        "daily.csv",
        "weekly.csv",
        "weekly_ohlcv.csv",
        "market_index_daily.csv",
        "market_index_weekly.csv",
    ]
    assert len(png_paths) == 2


def test_inline_payload_block_drops_timeseries_copies(inline_result):
    """B: payload 블록에서 시계열 사본 키 제거, daily_ohlcv(고유 open/high/low)는 유지."""
    inline_text, _ = inline_result
    assert '"indicators_recent_60d"' not in inline_text
    assert '"weekly_ohlcv_recent_104w"' not in inline_text
    assert '"daily_ohlcv_recent_60d"' in inline_text
