"""#204 — universe fetch: 업종 조회 빈 응답 가드 + 종목명 1회 조회(종목별 루프 제거). KRX 접촉 0(전부 mock).

배경: 월간 체인(매월 1일 06:30)이 '오늘' 날짜로 업종분류현황을 조회 → 장 전이라 종가 전부 0 → pykrx 가 빈 DataFrame 반환 →
reset_index/rename 후 ticker·sector 컬럼이 없어 KeyError("None of [Index(['ticker','sector'])] are in the [columns]").
06-28·07-17·09-01·10-01 전부 비거래 시점 실측. 종목명은 pykrx StockTicker(상장종목검색 1회) 캐시라 실제 요청은 이미 1회 —
(a) 같은 출처의 표를 한 번 받아 매핑(이름 값 100% 동일, 스팩 축 영향 0).
"""
from datetime import date

from tenacity import wait_none

import pandas as pd
import pytest
import kr_pipeline.universe.fetch as uf


def _sector_frame(rows):
    """pykrx get_market_sector_classifications 정상 응답 모양 — index 종목코드, 컬럼 종목명·업종명·종가…"""
    df = pd.DataFrame(rows, columns=["종목코드", "종목명", "업종명", "종가"]).set_index("종목코드")
    return df


# ---------- 업종 조회 ----------

def test_fetch_sectors_empty_response_raises_clear_error(mocker):
    """pykrx 는 종가 전부 0(비거래 시점)이면 빈 DataFrame 을 돌려준다 — 조용한 KeyError 대신 원인이 읽히는 ValueError."""
    stock_mock = mocker.patch.object(uf, "stock")
    stock_mock.get_market_sector_classifications.return_value = pd.DataFrame()

    with pytest.raises(ValueError, match=r"KOSPI.*2026-10-01.*비거래"):
        uf.fetch_sectors(date(2026, 10, 1), "KOSPI")
    # 빈 응답은 결정론적(초 단위로 바뀌지 않음) — 재시도로 KRX 요청을 3배 쓰지 않는다(리뷰 1차). 예외·일시 장애만 재시도.
    assert stock_mock.get_market_sector_classifications.call_count == 1


def test_fetch_sectors_maps_pykrx_columns(mocker):
    stock_mock = mocker.patch.object(uf, "stock")
    stock_mock.get_market_sector_classifications.return_value = _sector_frame(
        [("095570", "AJ네트웍스", "서비스업", 7280), ("005930", "삼성전자", "전기·전자", 70000)])

    out = uf.fetch_sectors(date(2026, 9, 30), "KOSPI")

    assert list(out.columns) == ["ticker", "sector"]
    assert dict(zip(out["ticker"], out["sector"])) == {"095570": "서비스업", "005930": "전기·전자"}
    stock_mock.get_market_sector_classifications.assert_called_once_with("20260930", market="KOSPI")


# ---------- 종목명 1회 조회 ----------

def test_fetch_names_reads_listing_search_once(monkeypatch):
    """ticker→종목명 사전 = pykrx 상장종목검색 원응답(short_code·codeName) 1회 — get_market_ticker_name 이 StockTicker.listed 로 쓰는
    것과 같은 화면·같은 컬럼(리뷰 2차: 싱글턴 내부 _instance 조작·상폐종목검색 불필요 요청 제거)."""
    calls = []

    def _listed():
        calls.append(1)
        return pd.DataFrame({"short_code": ["095570", "005930", "0NAN00"], "codeName": ["AJ네트웍스", "삼성전자", float("nan")],
                             "marketName": ["유가증권", "유가증권", "코스닥"]})

    monkeypatch.setattr(uf, "_listed_frame", _listed)

    assert uf.fetch_names() == {"095570": "AJ네트웍스", "005930": "삼성전자"}   # NaN 이름은 'nan' 문자열이 아니라 미해결로 남긴다
    assert calls == [1]


def test_fetch_names_empty_table_raises_clear_error(monkeypatch):
    """상장종목검색 실패(throttle·JSON 오류)가 빈 DataFrame 으로 삼켜져도 KeyError 대신 원인 문구 — with_retry 가 실제 재조회."""
    monkeypatch.setattr(uf, "_listed_frame", lambda: pd.DataFrame())

    with pytest.raises(ValueError, match=r"상장종목검색.*비어"):
        uf.fetch_names.retry_with(wait=wait_none())()


def test_fetch_universe_uses_name_map(monkeypatch):
    monkeypatch.setattr(uf, "fetch_tickers", lambda market, on_date: {"KOSPI": ["095570"], "KOSDAQ": ["060310", "054620"]}[market])
    monkeypatch.setattr(uf, "fetch_names", lambda: {"095570": "AJ네트웍스", "060310": "3S", "054620": "APS"})

    df = uf.fetch_universe(date(2026, 10, 1))

    assert df.to_dict("records") == [
        {"ticker": "095570", "name": "AJ네트웍스", "market": "KOSPI"},
        {"ticker": "060310", "name": "3S", "market": "KOSDAQ"},
        {"ticker": "054620", "name": "APS", "market": "KOSDAQ"},
    ]


def test_fetch_universe_fails_closed_when_name_unresolvable(monkeypatch):
    """전종목시세에는 있고 상장종목검색에는 없는 종목(피드 지연 등)은 종목별 보완이 불가능하다 — get_market_ticker_name 도 같은 표를
    읽고 모르는 종목엔 빈 DataFrame 을 돌려줘(dataframe_empty_handler) 이전엔 upsert 'cannot adapt type DataFrame' 로 터졌다(KRX 접촉을 다
    쓴 뒤). 쓰기 전에 종목을 지목해 fail-closed(리뷰 2차: 보완 경로는 죽은 코드라 제거)."""
    monkeypatch.setattr(uf, "fetch_tickers", lambda market, on_date: {"KOSPI": ["095570", "0NEW00"], "KOSDAQ": []}[market])
    monkeypatch.setattr(uf, "fetch_names", lambda: {"095570": "AJ네트웍스"})

    with pytest.raises(ValueError, match=r"종목명.*0NEW00"):
        uf.fetch_universe(date(2026, 10, 1))
