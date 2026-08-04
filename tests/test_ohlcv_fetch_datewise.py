"""#94 — 날짜별 전종목 스냅샷 수집 테스트 (KRX 실 접촉 없음, 전부 monkeypatch)."""
from datetime import date

import pandas as pd

import kr_pipeline.ohlcv.fetch as fetch_mod


def _krx_frame(rows: dict) -> pd.DataFrame:
    """pykrx get_market_ohlcv_by_ticker 모양(티커 index, 한글 컬럼)의 프레임."""
    df = pd.DataFrame(rows)
    return df.set_index("티커")


def test_snapshot_maps_columns_and_stamps_date(monkeypatch):
    krx = _krx_frame({
        "티커": ["005930", "000660"],
        "시가": [70000, 120000], "고가": [71000, 122000],
        "저가": [69500, 119000], "종가": [70500, 121000],
        "거래량": [1000, 2000], "거래대금": [70_500_000, 242_000_000],
        "등락률": [0.5, -1.0], "시가총액": [1, 2],
    })
    monkeypatch.setattr(fetch_mod.stock, "get_market_ohlcv_by_ticker",
                        lambda ds, market: krx)
    out = fetch_mod.fetch_market_snapshot(date(2026, 8, 4))
    assert list(out.columns) == ["ticker", "open", "high", "low", "close", "volume", "value", "date"]
    assert out.loc[out["ticker"] == "005930", "value"].item() == 70_500_000
    assert (out["date"] == date(2026, 8, 4)).all()
    assert "등락률" not in out.columns


def test_snapshot_holiday_all_zero_returns_empty(monkeypatch):
    """휴일: KRX 가 전 종목 OHLC=0 행을 반환 — 적재 금지 계약이므로 빈 DF."""
    krx = _krx_frame({
        "티커": ["005930", "000660"],
        "시가": [0, 0], "고가": [0, 0], "저가": [0, 0], "종가": [0, 0],
        "거래량": [0, 0], "거래대금": [0, 0], "등락률": [0.0, 0.0], "시가총액": [0, 0],
    })
    monkeypatch.setattr(fetch_mod.stock, "get_market_ohlcv_by_ticker",
                        lambda ds, market: krx)
    out = fetch_mod.fetch_market_snapshot(date(2026, 8, 2))
    assert out.empty
    assert list(out.columns) == ["ticker", "open", "high", "low", "close", "volume", "value", "date"]


def test_snapshot_empty_response_returns_empty(monkeypatch):
    """차단/빈 응답: pykrx 빈 DF → 빈 스냅샷 (호출자가 empty 계정 — P1-5 보존)."""
    monkeypatch.setattr(fetch_mod.stock, "get_market_ohlcv_by_ticker",
                        lambda ds, market: pd.DataFrame())
    out = fetch_mod.fetch_market_snapshot(date(2026, 8, 4))
    assert out.empty


def test_snapshot_halt_row_passes_through(monkeypatch):
    """거래정지(OHLV=0, 종가만 존재) 행은 raw 계약 그대로 보존 — nullify 는 adj 층 몫."""
    krx = _krx_frame({
        "티커": ["005930", "HALTD"],
        "시가": [70000, 0], "고가": [71000, 0], "저가": [69500, 0], "종가": [70500, 5000],
        "거래량": [1000, 0], "거래대금": [70_500_000, 0],
        "등락률": [0.5, 0.0], "시가총액": [1, 0],
    })
    monkeypatch.setattr(fetch_mod.stock, "get_market_ohlcv_by_ticker",
                        lambda ds, market: krx)
    out = fetch_mod.fetch_market_snapshot(date(2026, 8, 4))
    halt = out[out["ticker"] == "HALTD"].iloc[0]
    assert halt["open"] == 0 and halt["close"] == 5000
