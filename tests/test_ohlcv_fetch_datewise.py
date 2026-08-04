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


def test_snapshot_status_distinguishes_blocked_from_holiday(monkeypatch):
    """빈 스냅샷의 사유를 attrs 로 구분 — blocked(차단/빈 응답)만 결측 계정 대상,
    holiday(전량-0)는 정상 skip. 창 중간 하루 차단이 무신호로 소멸하는 것 방지."""
    monkeypatch.setattr(fetch_mod.stock, "get_market_ohlcv_by_ticker",
                        lambda ds, market: (_ for _ in ()).throw(KeyError("blocked")))
    blocked = fetch_mod.fetch_market_snapshot(date(2026, 8, 4))
    assert blocked.attrs["snapshot_status"] == "blocked"

    krx_holiday = _krx_frame({
        "티커": ["005930"], "시가": [0], "고가": [0], "저가": [0], "종가": [0],
        "거래량": [0], "거래대금": [0], "등락률": [0.0], "시가총액": [0],
    })
    monkeypatch.setattr(fetch_mod.stock, "get_market_ohlcv_by_ticker",
                        lambda ds, market: krx_holiday)
    holiday = fetch_mod.fetch_market_snapshot(date(2026, 8, 2))
    assert holiday.attrs["snapshot_status"] == "holiday"


def test_datewise_blocked_date_recorded_as_failure(monkeypatch):
    """차단으로 빈 스냅샷이 된 날짜는 failures 에 남아야 한다 — 다른 날짜가
    성공하면 어떤 종목도 raw.empty 가 아니어서 P1-5 계정이 못 잡기 때문."""
    def snap(d, market="ALL"):
        if d == date(2026, 8, 3):
            return fetch_mod._empty_snapshot("blocked")
        df = pd.DataFrame({
            "ticker": ["A"], "open": [3], "high": [3], "low": [3], "close": [3],
            "volume": [30], "value": [300],
        })
        df["date"] = d
        return df[fetch_mod.SNAPSHOT_COLUMNS]
    monkeypatch.setattr(fetch_mod, "fetch_market_snapshot", snap)
    monkeypatch.setattr(fetch_mod, "_fetch_one",
                        lambda t, s, e, adjusted: pd.DataFrame())
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)

    successes, failures = fetch_mod.fetch_many_datewise(
        ["A"], date(2026, 8, 3), date(2026, 8, 4), max_workers=1)

    assert dict(failures).get("snapshot:2026-08-03") == "blocked/empty response"
    assert successes["A"][0].shape[0] == 1  # 8/4 데이터는 정상 조립


def test_snapshot_blocked_keyerror_normalized_without_retry(monkeypatch):
    """차단/빈 응답의 실경로: pykrx wrap 층이 컬럼 없는 빈 DF 를 반환하고
    stock_api 휴일 판정이 KeyError 로 표면화(08-04 실측) — 빈 스냅샷으로
    정규화하고 with_retry 재시도 없이 1회 접촉으로 끝나야 한다."""
    calls = {"n": 0}

    def blocked(ds, market):
        calls["n"] += 1
        raise KeyError("None of [Index(['시가', ...])] are in the [columns]")
    monkeypatch.setattr(fetch_mod.stock, "get_market_ohlcv_by_ticker", blocked)
    out = fetch_mod.fetch_market_snapshot(date(2026, 8, 4))
    assert out.empty
    assert calls["n"] == 1


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


def test_datewise_skips_weekends_without_contact(monkeypatch):
    """주말은 KRX 접촉 없이 달력으로 확정 — 스냅샷 요청 자체를 보내지 않는다."""
    called: list[date] = []

    def snap(d, market="ALL"):
        called.append(d)
        return fetch_mod._empty_snapshot()
    monkeypatch.setattr(fetch_mod, "fetch_market_snapshot", snap)
    monkeypatch.setattr(fetch_mod, "_fetch_one",
                        lambda t, s, e, adjusted: pd.DataFrame())
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)

    # 2026-08-07(금) ~ 08-10(월): 토(8)·일(9) 은 요청 금지
    fetch_mod.fetch_many_datewise(["A"], date(2026, 8, 7), date(2026, 8, 10), max_workers=1)
    assert called == [date(2026, 8, 7), date(2026, 8, 10)]


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
