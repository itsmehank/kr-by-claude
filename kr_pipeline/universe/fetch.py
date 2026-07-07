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
