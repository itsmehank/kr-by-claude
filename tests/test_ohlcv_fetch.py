import socket
import threading
import time
from datetime import date

import pandas as pd
import pytest
import requests

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


def test_requests_default_timeout_injected(monkeypatch):
    """pykrx 가 쓰는 requests 호출에 timeout 미지정이면 기본 타임아웃을 주입하고,
    명시된 timeout 은 보존한다. (socket.setdefaulttimeout 은 requests 가 무시하므로
    이 어댑터 패치가 실제 효력을 가짐 — 2026-06-07 재hang 대응)"""
    captured = {}

    def fake_orig(self, request, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(fetch_mod, "_orig_adapter_send", fake_orig)
    adapter = requests.adapters.HTTPAdapter()

    requests.adapters.HTTPAdapter.send(adapter, "REQ", timeout=None)
    assert captured["timeout"] == (
        fetch_mod.FETCH_HTTP_CONNECT_TIMEOUT,
        fetch_mod.FETCH_HTTP_READ_TIMEOUT,
    )

    captured.clear()
    requests.adapters.HTTPAdapter.send(adapter, "REQ", timeout=5)
    assert captured["timeout"] == 5  # 명시값 보존


def test_real_hang_request_raises_within_timeout(monkeypatch):
    """실제 hang 검증: 응답 없는 서버에 timeout 미지정으로 요청해도, 어댑터 패치가
    주입한 read 타임아웃 때문에 무한 대기하지 않고 빠르게 예외를 던진다.
    (지난 socket.setdefaulttimeout 수정이 못 막았던 바로 그 상황을 재현)"""
    monkeypatch.setattr(fetch_mod, "FETCH_HTTP_CONNECT_TIMEOUT", 1)
    monkeypatch.setattr(fetch_mod, "FETCH_HTTP_READ_TIMEOUT", 1)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    host, port = srv.getsockname()

    def blackhole():
        try:
            conn, _ = srv.accept()
            time.sleep(5)  # 응답 안 함 — read 타임아웃(1s) 한참 초과
            conn.close()
        except OSError:
            pass

    th = threading.Thread(target=blackhole, daemon=True)
    th.start()

    start = time.time()
    with pytest.raises(requests.exceptions.RequestException):
        requests.get(f"http://{host}:{port}/")  # timeout 미지정 → 패치가 1s 주입
    elapsed = time.time() - start
    srv.close()

    assert elapsed < 4, f"타임아웃 미발동 — {elapsed:.1f}s 동안 대기(=hang)"
