import pandas as pd
from kr_pipeline.universe.transform import filter_common_stocks


def _row(ticker, name, market="KOSPI"):
    return {"ticker": ticker, "name": name, "market": market}


def test_keeps_common_stocks():
    df = pd.DataFrame([
        _row("005930", "삼성전자"),
        _row("000660", "SK하이닉스"),
    ])
    result = filter_common_stocks(df)
    assert list(result["ticker"]) == ["005930", "000660"]


def test_excludes_preferred_shares():
    df = pd.DataFrame([
        _row("005930", "삼성전자"),
        _row("005935", "삼성전자우"),
        _row("051915", "LG화학우"),
    ])
    result = filter_common_stocks(df)
    assert "005935" not in set(result["ticker"])
    assert "051915" not in set(result["ticker"])
    assert "005930" in set(result["ticker"])


def test_excludes_etfs_by_name_prefix():
    df = pd.DataFrame([
        _row("069500", "KODEX 200"),
        _row("102110", "TIGER 200"),
        _row("114800", "KODEX 인버스"),
        _row("005930", "삼성전자"),
    ])
    result = filter_common_stocks(df)
    assert set(result["ticker"]) == {"005930"}


def test_excludes_reits():
    df = pd.DataFrame([
        _row("330590", "롯데리츠"),
        _row("088980", "맥쿼리인프라"),
        _row("005930", "삼성전자"),
    ])
    result = filter_common_stocks(df)
    assert "330590" not in set(result["ticker"])
    assert "005930" in set(result["ticker"])


def test_excludes_spac():
    df = pd.DataFrame([
        _row("123456", "케이비17호스팩"),
        _row("005930", "삼성전자"),
    ])
    result = filter_common_stocks(df)
    assert set(result["ticker"]) == {"005930"}
