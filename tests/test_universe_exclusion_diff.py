"""#221 — 배제 집합 변동의 3분류(상폐 자동 / 신규 상장 배제 자동 / 잔여)."""
import pandas as pd

from kr_pipeline.universe.exclusion_diff import AUTO_ACCEPT_AXES, classify_exclusion_diff


def _ex(*rows):
    return pd.DataFrame(list(rows), columns=["ticker", "name", "market", "security_group", "axis"])


def test_removed_absent_from_raw_is_delisted_auto():
    d = classify_exclusion_diff(prev_set={"465320", "P1"}, excluded=_ex(("P1", "가우", "KOSPI", "주권", "preferred")),
                                raw_tickers={"P1", "005930"}, ever_in_stocks=set())
    assert d.removed_delisted == ["465320"] and d.unexplained_removed == [] and not d.unexplained


def test_removed_still_in_raw_is_unexplained_axis_release():
    """원본에는 있는데 배제 집합에서만 빠짐 = 배제 축이 풀린 것(규칙 변경·분류 변경) → 사람 확인."""
    d = classify_exclusion_diff(prev_set={"R1"}, excluded=_ex(), raw_tickers={"R1"}, ever_in_stocks=set())
    assert d.removed_delisted == [] and [u["ticker"] for u in d.unexplained_removed] == ["R1"] and d.unexplained


def test_added_never_in_stocks_with_exclusion_axis_is_new_listing_auto():
    d = classify_exclusion_diff(prev_set=set(), excluded=_ex(("0200G0", "한국제17호스팩", "KOSDAQ", "주권", "spac"),
                                                             ("00088K", "한화3우B", "KOSPI", "주권", "preferred"),
                                                             ("0030R0", "대신밸류리츠", "KOSPI", "부동산투자회사", "security_group")),
                                raw_tickers={"0200G0", "00088K", "0030R0"}, ever_in_stocks=set())
    assert sorted(d.added_new_listing) == ["00088K", "0030R0", "0200G0"] and not d.unexplained
    assert AUTO_ACCEPT_AXES == frozenset({"spac", "preferred", "security_group"})


def test_added_that_was_ever_in_stocks_is_unexplained_199_type():
    """#199: 기존 포함 → 신규 배제 는 자동 수용 금지(상태 컬럼·의미 정정 동반 사안)."""
    d = classify_exclusion_diff(prev_set=set(), excluded=_ex(("088980", "맵스리얼티", "KOSPI", "투자회사", "security_group")),
                                raw_tickers={"088980"}, ever_in_stocks={"088980"})
    assert d.added_new_listing == [] and [u["ticker"] for u in d.unexplained_added] == ["088980"]
    assert d.unexplained_added[0]["reason"].startswith("기존 활성")


def test_added_with_unknown_axis_is_unexplained():
    d = classify_exclusion_diff(prev_set=set(), excluded=_ex(("X1", "뭔가", "KOSPI", "주권", "etf")), raw_tickers={"X1"}, ever_in_stocks=set())
    assert d.unexplained_added and d.unexplained_added[0]["axis"] == "etf"


def test_2026_10_01_real_diff_is_fully_auto_accepted():
    """10-01 실패 재현: +0200G0 +0209J0(신규 스팩) −465320(교보15호스팩 상폐) → 전부 자동."""
    prev = {"465320", "0004Y0", "00088K"}
    cur = _ex(("0004Y0", "디비금융제14호스팩", "KOSDAQ", "주권", "spac"), ("00088K", "한화3우B", "KOSPI", "주권", "preferred"),
              ("0200G0", "한국제17호스팩", "KOSDAQ", "주권", "spac"), ("0209J0", "KB제34호스팩", "KOSDAQ", "주권", "spac"))
    raw = set(cur["ticker"]) | {"005930"}
    d = classify_exclusion_diff(prev_set=prev, excluded=cur, raw_tickers=raw, ever_in_stocks={"005930"})
    assert d.removed_delisted == ["465320"] and sorted(d.added_new_listing) == ["0200G0", "0209J0"] and not d.unexplained
    s = d.summary()
    assert s["removed_delisted"] == ["465320"] and s["unexplained"] == []
