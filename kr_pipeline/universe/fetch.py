import time
from datetime import date

import pandas as pd
from pykrx import stock

from kr_pipeline.common.retry import with_retry


# [design judgment] 시장별 최소 종목 수 하한 — book 근거 아님. KRX throttling 이
# 예외가 아닌 '빈/부분 리스트' 로 나타나는 것(ohlcv 에서 기관찰)을 잡는 sanity.
# 실측 규모(KOSPI ~950 / KOSDAQ ~1,750) 대비 보수적 하한. 이 하한 미달 목록이
# mark_delisted 로 흘러가면 그 시장 전 종목이 일괄 오폐지된다.
_MIN_TICKERS_PER_MARKET = {"KOSPI": 700, "KOSDAQ": 1300}


@with_retry(attempts=3)
def fetch_tickers(market: str, on_date: date) -> list[str]:
    """market = 'KOSPI' | 'KOSDAQ'.

    가드가 함수 '내부' 인 이유: @with_retry 는 모든 예외를 백오프 재시도하므로,
    일시적 throttle 빈 응답은 자동 회복 기회를 얻고 지속 실패만 전파된다.
    """
    tickers = stock.get_market_ticker_list(on_date.strftime("%Y%m%d"), market=market)
    floor = _MIN_TICKERS_PER_MARKET.get(market)
    if floor is not None and len(tickers) < floor:
        raise ValueError(
            f"suspiciously small ticker list for {market}: {len(tickers)} < {floor} "
            f"(KRX throttling/빈 응답 의심 — 오폐지 방지 fail-closed)"
        )
    return tickers


@with_retry(attempts=3)
def fetch_name(ticker: str) -> str:
    return stock.get_market_ticker_name(ticker)


def fetch_universe(on_date: date) -> pd.DataFrame:
    """모든 KOSPI/KOSDAQ ticker + 이름 + 시장."""
    rows = []
    for market in ("KOSPI", "KOSDAQ"):
        for ticker in fetch_tickers(market, on_date):
            rows.append({
                "ticker": ticker,
                "name": fetch_name(ticker),
                "market": market,
            })
    return pd.DataFrame(rows)


@with_retry(attempts=3)
def fetch_sectors(on_date: date, market: str) -> pd.DataFrame:
    """ticker → sector 매핑. 컬럼: ticker, sector."""
    df = stock.get_market_sector_classifications(on_date.strftime("%Y%m%d"), market=market)
    df = df.reset_index().rename(columns={"종목코드": "ticker", "업종명": "sector"})
    return df[["ticker", "sector"]]


# [design judgment] 증권구분 응답 하한 — book 근거 아님. 실측 규모 2,765(STK 943 + KSQ 1,822, 2026-09-11)
# 대비 보수적 하한. 한 시장 누락(부분 응답)을 정상 처리하면 그 시장 전 종목이 UNRESOLVED → 자격 게이트
# fail-closed 로 유니버스가 조용히 축소된다. 하한 미달 = 예외(fail-closed).
_MIN_SECURITY_GROUP_ROWS = 2000
_SECUGRP_ALL = ["STMFRTSCIFDRFS"]  # ST 주권·MF 투자회사·RT 부동산투자회사·SC 선박투자회사·IF 인프라·DR 예탁증서·FS 외국주권


def _short_sale_all_stocks():
    """pykrx 공매도 전종목 스크레이퍼 — 지연 import(테스트 격리·KRX 접촉 0 규약 #92)."""
    from pykrx.website.krx.market.core import 개별종목_공매도_거래_전종목
    return 개별종목_공매도_거래_전종목()


@with_retry(attempts=3)
def fetch_security_groups(on_date: date) -> dict[str, str]:
    """ticker → SECUGRP_NM(증권구분). KRX 요청 2회(STK·KSQ), 2초 페이싱.

    증권구분은 영속 속성이므로 on_date 는 '최근 거래일' 이면 충분(거래정지·비거래일 종목은 응답에 없어
    UNRESOLVED 로 남고 다음 갱신에서 재시도 — 지속화 fail-open 은 store 가 담당).
    """
    scraper = _short_sale_all_stocks()
    out: dict[str, str] = {}
    for i, mkt in enumerate(("STK", "KSQ")):
        df = scraper.fetch(on_date.strftime("%Y%m%d"), mkt, _SECUGRP_ALL)
        for _, r in df.iterrows():
            out[str(r["ISU_CD"])] = str(r["SECUGRP_NM"])
        if i == 0:
            time.sleep(2)
    if len(out) < _MIN_SECURITY_GROUP_ROWS:
        raise ValueError(
            f"suspiciously small security_group response: {len(out)} < {_MIN_SECURITY_GROUP_ROWS} "
            f"(부분 응답 의심 — UNRESOLVED 대량 전환 방지 fail-closed)"
        )
    return out
