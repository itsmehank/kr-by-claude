from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import socket
import time

import pandas as pd
import requests
from pykrx import stock

from kr_pipeline.common.retry import with_retry


# ── KRX 페치 hang 방지 (2026-06-07 daily chain 무한 hang 사고) ────────────────
# pykrx 는 requests 기반인데 타임아웃을 걸지 않는다. KRX 가 부하/throttle 로 연결을
# 끊거나 응답을 안 주면 소켓 읽기에서 무한 대기 → @with_retry 도 예외가 안 나 발동
# 못 하고 파이프라인 전체가 hang 한다.
#
# (1) 소켓 기본 타임아웃 — raw 소켓용 floor. 단 requests/urllib3 는 timeout 미지정 시
#     소켓을 blocking(None) 으로 설정해 이 전역 기본값을 *무시* 하므로 이것만으론 부족.
FETCH_SOCKET_TIMEOUT_SECONDS = 30
socket.setdefaulttimeout(FETCH_SOCKET_TIMEOUT_SECONDS)

# (2) requests 어댑터에 기본 (connect, read) 타임아웃을 강제 주입 — pykrx 의 모든 HTTP
#     호출(로그인·OHLCV)에서 timeout 미지정이면 이 값이 적용되어 실제 소켓 읽기까지
#     타임아웃이 전달된다. 타임아웃 발생 → requests 예외 → @with_retry 가 잡아 재시도/복구.
FETCH_HTTP_CONNECT_TIMEOUT = 10
FETCH_HTTP_READ_TIMEOUT = 30
_orig_adapter_send = requests.adapters.HTTPAdapter.send


def _adapter_send_with_default_timeout(self, request, **kwargs):
    if kwargs.get("timeout") is None:
        kwargs["timeout"] = (FETCH_HTTP_CONNECT_TIMEOUT, FETCH_HTTP_READ_TIMEOUT)
    return _orig_adapter_send(self, request, **kwargs)


requests.adapters.HTTPAdapter.send = _adapter_send_with_default_timeout


# pykrx 의 IndexTicker.get_name 은 KRX 의 "코드 → 한국어 이름" 매핑 lookup 인데,
# KRX 응답 형식 변화로 빈 DataFrame 받아 KeyError 발생할 수 있음 (2026-05 관찰).
# 그 이름은 DataFrame.columns.name 메타데이터에만 쓰이고 우리 시스템은 안 사용.
# 실패 시 dummy 이름 반환해서 인덱스 OHLCV 자체는 정상 받도록 안전망.
try:
    from pykrx.website.krx.market.ticker import IndexTicker as _IndexTicker
    _orig_index_get_name = _IndexTicker.get_name

    def _safe_index_get_name(self, ticker):
        try:
            return _orig_index_get_name(self, ticker)
        except Exception:
            return f"INDEX_{ticker}"

    _IndexTicker.get_name = _safe_index_get_name
except ImportError:
    pass


log = logging.getLogger("kr_pipeline.ohlcv.fetch")


@with_retry(attempts=3, wait_seconds=1.0)
def _fetch_one(ticker: str, start: date, end: date, adjusted: bool) -> pd.DataFrame:
    df = stock.get_market_ohlcv(
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        ticker,
        adjusted=adjusted,
    )
    if df.empty:
        return df
    df = df.reset_index()
    df = df.rename(columns={
        "날짜": "date", "시가": "open", "고가": "high",
        "저가": "low", "종가": "close", "거래량": "volume", "거래대금": "value",
    })
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def fetch_ohlcv_pair(ticker: str, start: date, end: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """원가 + 수정종가 두 번 호출."""
    raw = _fetch_one(ticker, start, end, adjusted=False)
    time.sleep(0.15)
    adj = _fetch_one(ticker, start, end, adjusted=True)
    return raw, adj


@with_retry(attempts=3, wait_seconds=1.0)
def fetch_adj_only(ticker: str, start: date, end: date) -> pd.DataFrame:
    """수정종가만 가져옴 (full-refresh 전용).

    fetch_ohlcv_pair 와 달리 raw 호출 안 함. adjusted=True 만 한 번 호출.
    """
    return _fetch_one(ticker, start, end, adjusted=True)


@with_retry(attempts=3, wait_seconds=1.0)
def fetch_index(index_code: str, start: date, end: date) -> pd.DataFrame:
    df = stock.get_index_ohlcv(
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        index_code,
    )
    if df.empty:
        return df
    df = df.reset_index().rename(columns={
        "날짜": "date", "시가": "open", "고가": "high",
        "저가": "low", "종가": "close", "거래량": "volume", "거래대금": "value",
    })
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def fetch_many(
    tickers: list[str],
    start: date,
    end: date,
    *,
    max_workers: int = 3,
) -> tuple[dict[str, tuple[pd.DataFrame, pd.DataFrame]], list[tuple[str, str]]]:
    """병렬 fetch. (성공 dict, 실패 [(ticker, error)] ) 반환."""
    successes: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    failures: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_ohlcv_pair, t, start, end): t for t in tickers}
        for i, fut in enumerate(as_completed(futures), 1):
            ticker = futures[fut]
            try:
                successes[ticker] = fut.result()
            except Exception as e:
                failures.append((ticker, str(e)))
            if i % 100 == 0:
                log.info(f"Progress: {i}/{len(tickers)} (failures so far: {len(failures)})")

    # 1차 실패 재시도
    if failures:
        log.warning(f"Retrying {len(failures)} failed tickers")
        retry_failures = []
        for ticker, _ in failures:
            try:
                successes[ticker] = fetch_ohlcv_pair(ticker, start, end)
            except Exception as e:
                retry_failures.append((ticker, str(e)))
        failures = retry_failures

    return successes, failures
