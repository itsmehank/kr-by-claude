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
    monkeypatch.setattr(uf, "_MIN_LISTED_NAMES", 1)

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

    assert df[["ticker", "name", "market"]].to_dict("records") == [
        {"ticker": "095570", "name": "AJ네트웍스", "market": "KOSPI"},
        {"ticker": "060310", "name": "3S", "market": "KOSDAQ"},
        {"ticker": "054620", "name": "APS", "market": "KOSDAQ"},
    ]


def _delisted(rows):
    return pd.DataFrame(rows, columns=["short_code", "codeName"])


def test_fetch_universe_resolves_from_delisted_table_only_when_listed_misses(monkeypatch):
    """get_market_ticker_name(StockTicker.get) 은 상장종목검색에 없으면 상폐종목검색을 봤다 — 정리매매 창 종목 등. 같은 순서를 유지하되
    상폐 표는 미해결이 있을 때만 1회(리뷰 3차: 보완 경로 전부 제거는 기존 해결 범위 축소)."""
    monkeypatch.setattr(uf, "fetch_tickers", lambda market, on_date: {"KOSPI": ["095570", "0DEL00"], "KOSDAQ": []}[market])
    monkeypatch.setattr(uf, "fetch_names", lambda: {"095570": "AJ네트웍스"})
    calls = []
    monkeypatch.setattr(uf, "_delisted_frame", lambda: calls.append(1) or _delisted([("0DEL00", "정리매매종목")]))

    df = uf.fetch_universe(date(2026, 10, 1))

    assert dict(zip(df["ticker"], df["name"])) == {"095570": "AJ네트웍스", "0DEL00": "정리매매종목"}
    assert calls == [1]


def test_fetch_universe_skips_delisted_lookup_when_all_resolved(monkeypatch):
    monkeypatch.setattr(uf, "fetch_tickers", lambda market, on_date: {"KOSPI": ["095570"], "KOSDAQ": []}[market])
    monkeypatch.setattr(uf, "fetch_names", lambda: {"095570": "AJ네트웍스"})
    monkeypatch.setattr(uf, "_delisted_frame", lambda: (_ for _ in ()).throw(AssertionError("불필요한 KRX 요청")))

    assert uf.fetch_universe(date(2026, 10, 1))["name"].tolist() == ["AJ네트웍스"]


def test_fetch_universe_returns_none_name_when_unresolved_everywhere(monkeypatch):
    """미해결은 여기서 raise 하지 않는다 — 호출부가 응답을 파일로 먼저 보존한 뒤 fail-closed(운영 규칙 5, 리뷰 3차). 이전엔 빈 DataFrame 이
    name 에 들어가 upsert 에서 터졐다."""
    monkeypatch.setattr(uf, "fetch_tickers", lambda market, on_date: {"KOSPI": ["095570", "0NEW00"], "KOSDAQ": []}[market])
    monkeypatch.setattr(uf, "fetch_names", lambda: {"095570": "AJ네트웍스"})
    monkeypatch.setattr(uf, "_delisted_frame", lambda: _delisted([]))

    df = uf.fetch_universe(date(2026, 10, 1))

    assert df.loc[df["ticker"] == "0NEW00", "name"].item() is None


def test_fetch_names_small_table_raises_for_retry(monkeypatch):
    """[design judgment] 상장종목검색 행 수 하한 — 잘린(비어 있지 않은) 응답을 정상 처리하면 수백 종목이 미해결/상폐 표 보완으로 흘러간다."""
    monkeypatch.setattr(uf, "_listed_frame", lambda: pd.DataFrame({"short_code": ["095570"], "codeName": ["AJ네트웍스"]}))

    with pytest.raises(ValueError, match=r"suspiciously small.*1 <"):
        uf.fetch_names.retry_with(wait=wait_none())()


def test_delisted_names_pick_first_isin_for_reused_code(monkeypatch):
    """pykrx StockTicker.get 은 재사용 코드(030270 에스마크/가희 11R)를 ISIN 정렬 후 첫 행으로 골랐다 — 같은 선택(리뷰 4차)."""
    monkeypatch.setattr(uf, "_delisted_frame", lambda: pd.DataFrame(
        {"short_code": ["030270", "030270"], "codeName": ["에스마크", "가희 11R"], "full_code": ["KR7030270003", "KRA030270151"]}))   # dict 마지막 행 = 가희 → ISIN 첫 행 = 에스마크 여야 함

    assert uf._delisted_names() == {"030270": "에스마크"}


def test_fetch_universe_tolerates_transient_empty_delisted_table(monkeypatch):
    """상폐 표가 비어 오면(throttle) 재시도 후에도 비면 {} 로 진행 — 미해결은 호출부 판정으로(리뷰 4차)."""
    monkeypatch.setattr(uf, "fetch_tickers", lambda market, on_date: {"KOSPI": ["095570", "0DEL00"], "KOSDAQ": []}[market])
    monkeypatch.setattr(uf, "fetch_names", lambda: {"095570": "AJ네트웍스"})
    calls = []
    monkeypatch.setattr(uf, "_delisted_frame", lambda: calls.append(1) or pd.DataFrame())
    monkeypatch.setattr(uf, "_delisted_names", uf._delisted_names.retry_with(wait=wait_none()))

    df = uf.fetch_universe(date(2026, 10, 1))

    assert len(calls) == 3                                     # 빈 표는 재시도 대상
    assert df.loc[df["ticker"] == "0DEL00", "name"].item() is None


def test_fetch_universe_marks_name_source(monkeypatch):
    """어느 표에서 이름이 왔는지 행에 남긴다 — 상폐 표에서 온 이름(코드 재사용 가능)은 호출부가 경고·증거로 추적(리뷰 4차)."""
    monkeypatch.setattr(uf, "fetch_tickers", lambda market, on_date: {"KOSPI": ["095570", "0DEL00"], "KOSDAQ": []}[market])
    monkeypatch.setattr(uf, "fetch_names", lambda: {"095570": "AJ네트웍스"})
    monkeypatch.setattr(uf, "_delisted_frame", lambda: _delisted([("0DEL00", "정리매매종목")]))

    df = uf.fetch_universe(date(2026, 10, 1))

    assert dict(zip(df["ticker"], df["name_source"])) == {"095570": "listed", "0DEL00": "delisted"}


def test_fetch_universe_fetches_tickers_before_names(monkeypatch):
    """종목 목록 하한 가드가 fail-closed 하면 종목명 요청은 쓰지 않는다 — 접촉 최소화 순서(리뷰 4차)."""
    monkeypatch.setattr(uf, "fetch_tickers", lambda market, on_date: (_ for _ in ()).throw(ValueError("suspiciously small ticker list")))
    monkeypatch.setattr(uf, "fetch_names", lambda: (_ for _ in ()).throw(AssertionError("목록 실패 뒤 종목명 요청 금지")))

    with pytest.raises(ValueError, match="ticker list"):
        uf.fetch_universe(date(2026, 10, 1))


def test_fetch_sectors_wraps_swallowed_pykrx_error(mocker):
    """pykrx wrap 은 원응답 오류(throttle HTML·JSON)를 빈 표로 삼키고 stock_api 가 KeyError('종가') 를 낸다 — 경고 문구에 원인 힌트(리뷰 4차)."""
    stock_mock = mocker.patch.object(uf, "stock")
    stock_mock.get_market_sector_classifications.side_effect = KeyError("종가")
    mocker.patch.object(uf, "_fetch_sector_frame", uf._fetch_sector_frame.retry_with(wait=wait_none()))   # 재시도 대기 제거(테스트 속도)

    with pytest.raises(ValueError, match=r"KOSDAQ.*2026-10-30.*삼킨.*컬럼명 변경 아님"):
        uf.fetch_sectors(date(2026, 10, 30), "KOSDAQ")
    assert stock_mock.get_market_sector_classifications.call_count == 3   # 예외는 재시도 대상(빈 응답과 달리)


def test_fetch_sectors_unexpected_columns_raise_readable_error(mocker):
    """비어 있지 않은데 컬럼이 다르면(pykrx/KRX 변경) rename 이 무시돼 원래의 암호 같은 KeyError 가 재현된다 — 실제 컬럼을 보여 주는 ValueError(리뷰 5차)."""
    stock_mock = mocker.patch.object(uf, "stock")
    stock_mock.get_market_sector_classifications.return_value = pd.DataFrame(
        [("095570", "서비스업")], columns=["티커", "산업"]).set_index("티커")

    with pytest.raises(ValueError, match=r"KOSPI.*2026-10-30.*unexpected columns.*티커.*산업"):
        uf.fetch_sectors(date(2026, 10, 30), "KOSPI")
