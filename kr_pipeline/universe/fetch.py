from datetime import date

import pandas as pd
from pykrx import stock

from kr_pipeline.common.retry import with_retry


@with_retry(attempts=3)
def fetch_tickers(market: str, on_date: date) -> list[str]:
    """market = 'KOSPI' | 'KOSDAQ'."""
    return stock.get_market_ticker_list(on_date.strftime("%Y%m%d"), market=market)


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
    df = df.reset_index().rename(columns={"티커": "ticker", "업종명": "sector"})
    return df[["ticker", "sector"]]
