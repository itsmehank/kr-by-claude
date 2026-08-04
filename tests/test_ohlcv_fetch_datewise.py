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


# ====== fetch_many_datewise ======

def _snap(d, rows):
    df = pd.DataFrame(rows)
    df["date"] = d
    return df[fetch_mod.SNAPSHOT_COLUMNS]


def _adj_frame(dates, closes):
    return pd.DataFrame({
        "date": dates, "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": [1] * len(dates), "value": [1] * len(dates),
    })


def test_datewise_assembles_raw_and_filters_universe(monkeypatch):
    """날짜 2일 스냅샷 → 종목별 raw 조립. universe 밖 티커(NEWIPO)는 제외."""
    snaps = {
        date(2026, 8, 3): _snap(date(2026, 8, 3), {
            "ticker": ["A", "B", "NEWIPO"], "open": [1, 2, 9], "high": [1, 2, 9],
            "low": [1, 2, 9], "close": [1, 2, 9], "volume": [10, 20, 90], "value": [100, 200, 900],
        }),
        date(2026, 8, 4): _snap(date(2026, 8, 4), {
            "ticker": ["A"], "open": [3], "high": [3], "low": [3], "close": [3],
            "volume": [30], "value": [300],
        }),
    }
    monkeypatch.setattr(fetch_mod, "fetch_market_snapshot",
                        lambda d, market="ALL": snaps.get(d, fetch_mod._empty_snapshot()))
    monkeypatch.setattr(fetch_mod, "_fetch_one",
                        lambda t, s, e, adjusted: _adj_frame([date(2026, 8, 3)], [1.0]))
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)

    successes, failures = fetch_mod.fetch_many_datewise(
        ["A", "B", "C"], date(2026, 8, 3), date(2026, 8, 4), max_workers=2)

    assert failures == []
    assert set(successes) == {"A", "B", "C"}          # NEWIPO 없음, 미출현 C 는 남음
    raw_a = successes["A"][0]
    assert list(raw_a["date"]) == [date(2026, 8, 3), date(2026, 8, 4)]  # 날짜 정렬
    assert successes["B"][0].shape[0] == 1
    assert successes["C"][0].empty                     # 활성인데 미출현 → empty 계정 대상


def test_datewise_snapshot_failure_recorded_others_continue(monkeypatch):
    """한 날짜의 스냅샷 예외는 failures 로 남고 다른 날짜는 계속 처리."""
    def snap(d, market="ALL"):
        if d == date(2026, 8, 3):
            raise RuntimeError("boom")
        return _snap(d, {"ticker": ["A"], "open": [3], "high": [3], "low": [3],
                         "close": [3], "volume": [30], "value": [300]})
    monkeypatch.setattr(fetch_mod, "fetch_market_snapshot", snap)
    monkeypatch.setattr(fetch_mod, "_fetch_one",
                        lambda t, s, e, adjusted: pd.DataFrame())
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)

    successes, failures = fetch_mod.fetch_many_datewise(
        ["A"], date(2026, 8, 3), date(2026, 8, 4), max_workers=1)

    assert "snapshot:2026-08-03" in dict(failures)
    assert successes["A"][0].shape[0] == 1


def test_datewise_adj_failure_retried_then_recorded(monkeypatch):
    """adj(Naver) 실패는 1회 재시도 후 실패 기록 — fetch_many 패턴 보존."""
    calls = {"n": 0}

    def adj_fail(t, s, e, adjusted):
        calls["n"] += 1
        raise RuntimeError("naver down")
    monkeypatch.setattr(fetch_mod, "fetch_market_snapshot",
                        lambda d, market="ALL": fetch_mod._empty_snapshot())
    monkeypatch.setattr(fetch_mod, "_fetch_one", adj_fail)
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)

    successes, failures = fetch_mod.fetch_many_datewise(
        ["A"], date(2026, 8, 4), date(2026, 8, 4), max_workers=1)

    assert calls["n"] == 2                 # 본 시도 + 재시도
    assert "A" in dict(failures)
    assert "A" not in successes
