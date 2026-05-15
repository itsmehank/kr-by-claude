from datetime import date
import pandas as pd
from pykrx import stock
# NOTE: StockTicker is an internal pykrx API (not re-exported by public modules).
# We use it because pykrx.stock.get_market_ticker_list(date, market) returns
# HTTP 400 from data.krx.co.kr in this environment. May break on pykrx upgrades.
from pykrx.website.krx.market.ticker import StockTicker

from kr_pipeline.common.retry import with_retry

# KRX market code → canonical market name
_MARKET_CODE_MAP = {"STK": "KOSPI", "KSQ": "KOSDAQ"}


@with_retry(attempts=3)
def fetch_name(ticker: str) -> str:
    return stock.get_market_ticker_name(ticker)


def fetch_universe(on_date: date) -> pd.DataFrame:
    """모든 KOSPI/KOSDAQ ticker + 이름 + 시장.

    pykrx의 날짜 기반 ticker list API(get_market_ticker_list)는 KRX 서버
    접근 제한으로 응답이 비어 있을 수 있다. 대신 StockTicker 싱글턴을
    사용해 전체 상장 종목을 한 번에 가져온다. StockTicker 는 날짜 파라미터
    없이 현재 상장 종목을 반환하므로 on_date 인자는 future 확장용으로만
    서명에 유지한다.
    """
    st = StockTicker()
    df = st.listed.reset_index()
    # 컬럼: 티커, 종목, ISIN, 시장
    df = df.rename(columns={"티커": "ticker", "종목": "name", "시장": "market_code"})
    df["market"] = df["market_code"].map(_MARKET_CODE_MAP)
    # KOSPI/KOSDAQ 만 남기고 KONEX 등 제외
    df = df[df["market"].notna()][["ticker", "name", "market"]].reset_index(drop=True)
    return df


@with_retry(attempts=3)
def fetch_sectors(on_date: date, market: str) -> pd.DataFrame:
    """ticker → sector 매핑. 컬럼: ticker, sector."""
    df = stock.get_market_sector_classifications(on_date.strftime("%Y%m%d"), market=market)
    # pykrx 반환 포맷에 따라 컬럼 정규화
    df = df.reset_index().rename(columns={"티커": "ticker", "업종명": "sector"})
    return df[["ticker", "sector"]]
