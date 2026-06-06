import socket
from datetime import date

import pandas as pd

import kr_pipeline.ohlcv.fetch as fetch_mod
from kr_pipeline.ohlcv.fetch import _fetch_one, FETCH_SOCKET_TIMEOUT_SECONDS


def test_socket_default_timeout_is_configured():
    """fetch 모듈 import 시 소켓 기본 타임아웃이 설정되어, KRX 무응답 읽기가
    영원히 hang 하지 않고 타임아웃 예외를 던지게 한다. (2026-06-07 hang 사고 대응)"""
    assert FETCH_SOCKET_TIMEOUT_SECONDS and FETCH_SOCKET_TIMEOUT_SECONDS > 0
    assert socket.getdefaulttimeout() == FETCH_SOCKET_TIMEOUT_SECONDS


def test_fetch_one_retries_and_recovers_on_timeout(monkeypatch):
    """타임아웃(=hang 이 전환된 예외)을 @with_retry 가 잡아 재시도하고 복구한다.
    타임아웃이 없으면 무한 hang 했지만, 이제는 예외 → 재시도 → 성공."""
    calls = {"n": 0}
    good = pd.DataFrame(
        {
            "시가": [100], "고가": [110], "저가": [95],
            "종가": [105], "거래량": [1000], "거래대금": [105000],
        },
        index=pd.DatetimeIndex([pd.Timestamp("2026-06-02")], name="날짜"),
    )

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("simulated KRX socket read timeout")
        return good

    monkeypatch.setattr(fetch_mod.stock, "get_market_ohlcv", flaky)
    df = _fetch_one("005930", date(2026, 6, 1), date(2026, 6, 5), adjusted=False)

    assert calls["n"] == 2  # 1차 타임아웃 → 재시도 → 2차 성공
    assert list(df["close"]) == [105]
    assert list(df["date"]) == [date(2026, 6, 2)]
