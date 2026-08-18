"""#114 delisted_backfill 단위 테스트 — 설계 v2 §2·§3 검증."""
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from kr_pipeline.ohlcv.delisted_backfill import (
    add_calls, calls_today, in_window, insert_delisted_prices,
    insert_share_counts, load_checkpoint, price_rows, save_checkpoint,
    share_rows, upsert_delisted_stock,
)


def _ohlcv_df():
    idx = pd.to_datetime(["2018-01-02", "2018-01-03"])
    return pd.DataFrame(
        {"시가": [100, 102], "고가": [110, 103], "저가": [95, 99],
         "종가": [105, 100], "거래량": [1000, 2000],
         "거래대금": [105000, 200000], "등락률": [1.0, -4.8]}, index=idx)


def test_price_rows_transform():
    rows = price_rows("999990", _ohlcv_df())
    assert rows[0] == ("999990", date(2018, 1, 2), 100.0, 110.0, 95.0, 105.0,
                       1000, 105000)
    assert len(rows) == 2


def test_share_rows_transform():
    idx = pd.to_datetime(["2018-01-02"])
    df = pd.DataFrame({"시가총액": [1], "거래량": [1], "거래대금": [1],
                       "상장주식수": [676000000]}, index=idx)
    assert share_rows("999990", df) == [("999990", date(2018, 1, 2), 676000000)]


def test_checkpoint_roundtrip_and_budget(tmp_path: Path):
    p = tmp_path / "cp.json"
    cp = load_checkpoint(p)
    assert cp == {"done": [], "calls": {}}
    add_calls(cp, "2026-08-18", 3)
    cp["done"].append("999990")
    save_checkpoint(p, cp)
    cp2 = load_checkpoint(p)
    assert calls_today(cp2, "2026-08-18") == 3
    assert cp2["done"] == ["999990"]
    assert calls_today(cp2, "2026-08-19") == 0


def test_in_window():
    assert in_window(datetime(2026, 8, 18, 20, 30))      # 평일 야간
    assert in_window(datetime(2026, 8, 18, 23, 59))
    assert in_window(datetime(2026, 8, 19, 5, 59))        # 새벽 연속 실행
    assert not in_window(datetime(2026, 8, 18, 14, 0))    # 평일 주간
    assert not in_window(datetime(2026, 8, 18, 6, 1))     # 라이브 잡 시간대
    assert in_window(datetime(2026, 8, 22, 14, 0))        # 토요일 주간


def test_upsert_delisted_stock_never_touches_existing(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) "
                    "VALUES ('999990', '원래이름', 'KOSPI')")
    upsert_delisted_stock(db, "999990", "다른이름", "KOSDAQ",
                          date(2019, 1, 1), True)
    with db.cursor() as cur:
        cur.execute("SELECT name, market, delisted_at FROM stocks "
                    "WHERE ticker = '999990'")
        assert cur.fetchone() == ("원래이름", "KOSPI", None)  # 기존 행 무수정

    upsert_delisted_stock(db, "999980", "상폐사", "KOSDAQ", date(2019, 1, 1), True)
    with db.cursor() as cur:
        cur.execute("SELECT name, market, delisted_at, is_common FROM stocks "
                    "WHERE ticker = '999980'")
        assert cur.fetchone() == ("상폐사", "KOSDAQ", date(2019, 1, 1), True)


def test_insert_prices_and_shares_idempotent(db):
    upsert_delisted_stock(db, "999990", "상폐사", "KOSPI", date(2019, 1, 1), True)
    rows = price_rows("999990", _ohlcv_df())
    assert insert_delisted_prices(db, rows) == 2
    assert insert_delisted_prices(db, rows) == 0   # 재실행(이어받기) 시 중복 0
    assert insert_share_counts(db, [("999990", date(2018, 1, 2), 100)]) == 1
    assert insert_share_counts(db, [("999990", date(2018, 1, 2), 100)]) == 0
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM delisted_daily_prices")
        assert cur.fetchone()[0] == 2
