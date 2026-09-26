from datetime import date, timedelta
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
        "등락률": "change_pct",   # #207: KRX 기준가 대비 등락률 보존(adjusted=True 의 Naver 산출값은 merge 가 버림)
    })
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df




@with_retry(attempts=3, wait_seconds=1.0)
def fetch_index(index_code: str, start: date, end: date) -> pd.DataFrame:
    df = stock.get_index_ohlcv(
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        index_code,
        # #92: 기본값 True 면 get_index_ticker_name → IndexTicker() 가 시장 4종 마스터를
        # 추가로 fetch 해 ELTD 1회가 6요청이 된다(로그인 3 + OHLCV 1 + 마스터 4 중 일부).
        # 컬럼명 메타데이터는 소비하지 않는다(to_index_rows 는 date/OHLC/volume/value 만 읽음).
        name_display=False,
    )
    if df.empty:
        return df
    df = df.reset_index().rename(columns={
        "날짜": "date", "시가": "open", "고가": "high",
        "저가": "low", "종가": "close", "거래량": "volume", "거래대금": "value",
    })
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


SNAPSHOT_COLUMNS = ["ticker", "open", "high", "low", "close", "volume", "value", "date", "change_pct"]

_SNAPSHOT_RENAME = {
    "티커": "ticker", "시가": "open", "고가": "high",
    "저가": "low", "종가": "close", "거래량": "volume", "거래대금": "value",
    "등락률": "change_pct",   # #207
}


def _empty_snapshot(status: str = "empty") -> pd.DataFrame:
    """빈 스냅샷. status(attrs): holiday=정상 skip / blocked=결측 계정 대상."""
    df = pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    df.attrs["snapshot_status"] = status
    return df


@with_retry(attempts=3, wait_seconds=1.0)
def fetch_market_snapshot(d: date, market: str = "ALL") -> pd.DataFrame:
    """일자별 전종목 raw OHLCV — KRX 전종목시세(MDCSTAT01501) 단일 요청 (#94).

    종목별 스윕(2,549요청)이 차단 재트리거로 실측돼(run 1235, 86.2% 빈 응답)
    날짜별 1요청으로 대체. market="ALL" 이면 KOSPI+KOSDAQ+KONEX 가 한 번에 오고
    universe 교집합은 호출자(fetch_raw_datewise)가 거른다.

    - 휴일: KRX 가 전 종목 OHLC=0 행을 반환(빈 DF 아님) → 빈 스냅샷으로 정규화
      (적재 금지 — bad_prices sanity·halt 마커 규약·weekly 파생 오염 방지).
    - 차단/빈 응답: 빈 스냅샷(status="blocked") — 호출자(fetch_raw_datewise)가
      failures 로 계정하고 _run_upsert 가 snapshot_gap 경고로 승격한다. 창 중간
      하루만 차단이면 어떤 종목도 raw.empty 가 아니어서 P1-5 empty 계정이 못
      잡기 때문(전 기간 차단이면 empty 계정도 함께 발동). 실경로에선 pykrx
      wrap 층(@dataframe_empty_handler)이 컬럼 없는 빈 DF 를 반환하고 stock_api
      의 휴일 판정에서 KeyError 로 표면화된다(08-04 실측) → 여기서 잡아
      정규화하고 **재시도하지 않는다**(차단 중 접촉 증폭 방지 — with_retry 는
      transport 오류 전용으로 남긴다).
    - 거래정지 행(OHLV=0, close>0)은 그대로 통과 — raw 의 halt 마커 계약이며
      adj NULL 화는 merge_raw_and_adjusted → nullify_halt_adj 가 수행.
    """
    try:
        df = stock.get_market_ohlcv_by_ticker(d.strftime("%Y%m%d"), market=market)
    except KeyError:
        log.info(f"snapshot {d}: blocked/empty (pykrx KeyError)")
        return _empty_snapshot("blocked")
    if df.empty:
        log.info(f"snapshot {d}: empty response")
        return _empty_snapshot("blocked")
    if (df[["시가", "고가", "저가", "종가"]] == 0).all(axis=None):
        log.info(f"snapshot {d}: holiday (all-zero)")
        return _empty_snapshot("holiday")
    df = df.reset_index().rename(columns=_SNAPSHOT_RENAME)
    df["date"] = d
    return df[SNAPSHOT_COLUMNS]


def fetch_raw_datewise(
    tickers: list[str], start: date, end: date,
) -> tuple[dict[str, pd.DataFrame], list[tuple[str, str]]]:
    """#207 A안 라이브 경로: 날짜별 전종목 스냅샷으로 raw(OHLCV + change_pct)만 조립 — **Naver 접촉 0**.
    수정 OHLCV 는 호출자가 adjust.derive_adj(raw × F) 로 산출한다.
    반환 ({ticker: raw}, [(식별자, 오류)]); raw 미출현 종목도 빈 raw 로 남아 P1-5 empty 계정이 잡는다."""
    raw_by_ticker, failures = _assemble_raw_datewise(tickers, start, end)
    empty_cols = [c for c in SNAPSHOT_COLUMNS if c != "ticker"]
    return {t: raw_by_ticker.get(t, pd.DataFrame(columns=empty_cols)) for t in tickers}, failures


def _assemble_raw_datewise(
    tickers: list[str], start: date, end: date,
) -> tuple[dict[str, pd.DataFrame], list[tuple[str, str]]]:
    wanted = set(tickers)
    frames: list[pd.DataFrame] = []
    failures: list[tuple[str, str]] = []

    d = start
    while d <= end:
        if d.weekday() >= 5:  # 주말 — KRX 접촉 없이 달력으로 확정
            d += timedelta(days=1)
            continue
        try:
            snap = fetch_market_snapshot(d)
            if not snap.empty:
                frames.append(snap[snap["ticker"].isin(wanted)])
            elif snap.attrs.get("snapshot_status") == "blocked":
                # 휴일(전량-0)과 달리 차단/빈 응답은 결측 — 창 중간 하루면
                # P1-5 empty 계정이 못 잡으므로 여기서 failures 로 남긴다.
                failures.append((f"snapshot:{d.isoformat()}", "blocked/empty response"))
        except Exception as e:
            failures.append((f"snapshot:{d.isoformat()}", str(e)))
        time.sleep(0.2)  # 날짜 간 페이싱 — 재탐지 방지
        d += timedelta(days=1)

    raw_by_ticker: dict[str, pd.DataFrame] = {}
    if frames:
        raw_all = pd.concat(frames, ignore_index=True)
        raw_by_ticker = {
            t: g.drop(columns=["ticker"]).sort_values("date").reset_index(drop=True)
            for t, g in raw_all.groupby("ticker")
        }
    return raw_by_ticker, failures
