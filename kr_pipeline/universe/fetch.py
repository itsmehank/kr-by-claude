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


def _listed_frame() -> pd.DataFrame:
    """pykrx 상장종목검색 원응답(short_code·codeName·marketName…) 1회 — 지연 import(테스트 monkeypatch 지점, #92 관례).

    get_market_ticker_name 이 종목마다 읽는 StockTicker.listed 가 **이 화면 그대로**(컬럼명만 바꿈)다. StockTicker 를 쓰지 않는 이유(리뷰 2차):
    @singleton 이 실패(throttle·JSON 오류)를 dataframe_empty_handler 의 빈 DataFrame 으로 삼켜 프로세스 수명 동안 봉인하고,
    생성마다 상폐종목검색까지 1회 더 부른다. 직접 호출이면 재시도 1회 = 요청 1회, pykrx 내부 _instance 조작 불필요."""
    from pykrx.website.krx.market.core import 상장종목검색
    return 상장종목검색().fetch("ALL")


@with_retry(attempts=3)
def fetch_names() -> dict[str, str]:
    """ticker → 종목명 전표. (#204, 사용자 결정 (a)) get_market_ticker_name 과 **같은 화면·같은 컬럼**(상장종목검색 codeName)을 한 번에
    받는다 — 이름 값 동일 → 스팩 축('스팩' 이름 키워드) 판정 영향 0. 종목별 루프만 제거.
    (b) 전종목시세 ISU_ABBRV 재사용(요청 −1)은 두 화면의 종목명 동일성이 미감사라 보류 — 감사 후 별건.
    빈 표(실패가 삼켜진 경우)는 명시 예외 → with_retry 재조회. 이름이 문자열이 아닌 행(NaN)은 사전에서 빼서 미해결로 남긴다
    (str() 강제 시 'nan' 이 이름으로 적재됨 — 리뷰 2차)."""
    df = _listed_frame()
    if df is None or df.empty or not {"short_code", "codeName"} <= set(df.columns):
        raise ValueError("종목명 표(pykrx 상장종목검색) 응답이 비어 있음 — KRX throttle/응답 오류 의심")
    return {str(t): n for t, n in zip(df["short_code"], df["codeName"]) if isinstance(n, str) and n}


def fetch_universe(on_date: date) -> pd.DataFrame:
    """모든 KOSPI/KOSDAQ ticker + 이름 + 시장. 종목명 미해결(전종목시세엔 있고 상장종목검색엔 없음·이름 NaN)이 하나라도 있으면
    어떤 쓰기보다 앞에서 fail-closed. 종목별 보완 경로는 두지 않는다 — get_market_ticker_name 도 같은 표를 읽어 해결 불가하고,
    모르는 종목엔 빈 DataFrame 을 돌려줘 이전엔 upsert 'cannot adapt type DataFrame' 로 터졌다(KRX 접촉을 다 쓴 뒤)."""
    names = fetch_names()
    rows, unresolved = [], []
    for market in ("KOSPI", "KOSDAQ"):
        for ticker in fetch_tickers(market, on_date):
            name = names.get(ticker)
            if not name:
                unresolved.append(ticker)
            rows.append({"ticker": ticker, "name": name, "market": market})
    if unresolved:
        raise ValueError(f"종목명 미해결 {len(unresolved)}종목(상장종목검색 응답에 없음·이름 결측): {unresolved[:20]}")
    return pd.DataFrame(rows)


@with_retry(attempts=3)
def _fetch_sector_frame(on_date: date, market: str) -> pd.DataFrame:
    """KRX 업종분류현황 원응답(재시도 대상 = 예외·일시 장애만)."""
    return stock.get_market_sector_classifications(on_date.strftime("%Y%m%d"), market=market)


def fetch_sectors(on_date: date, market: str) -> pd.DataFrame:
    """ticker → sector 매핑. 컬럼: ticker, sector.

    (#204) on_date 는 **종가가 있는 거래일**이어야 한다. pykrx 는 응답 종가가 전부 0(장 전·휴장일 조회)이면 빈 DataFrame 을
    돌려주고, 그대로 두면 컬럼 부재 KeyError 로만 보여 원인이 묻힌다(06-28·07-17·09-01·10-01 월간 체인 06:30 실측). 호출부는
    _sector_as_of(DB 최신 일봉 날짜)로 넘긴다. 빈 응답은 결정론적이라 **재시도 밖**에서 명시 예외(리뷰 1차: 시장당 3요청 낭비 방지).
    호출부 경고 처리(실패 시 기존 값 COALESCE 유지)는 불변.
    """
    df = _fetch_sector_frame(on_date, market)
    if df is None or df.empty:
        raise ValueError(
            f"empty sector response for {market} on {on_date.isoformat()} "
            f"(종가 전부 0 — 비거래 시점 조회 의심; 기준일은 종가가 있는 거래일이어야 함)"
        )
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
