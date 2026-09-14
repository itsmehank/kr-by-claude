"""유니버스 적재 전 배제 — 이름 3축(우선주·스팩·ETF) + SECUGRP 축(부동산투자회사).

plan: docs/superpowers/plans/2026-09-15-secugrp-universe-filter.md Task 2.
"""
import pandas as pd
import pytest

from kr_pipeline.universe.transform import (
    classify_exclusion_axis, filter_common_stocks, split_universe,
)


def _row(ticker, name, market="KOSPI", security_group="주권"):
    return {"ticker": ticker, "name": name, "market": market, "security_group": security_group}


def test_keeps_common_stocks():
    df = pd.DataFrame([_row("005930", "삼성전자"), _row("000660", "SK하이닉스")])
    assert list(filter_common_stocks(df)["ticker"]) == ["005930", "000660"]


def test_excludes_preferred_shares():
    df = pd.DataFrame([_row("005930", "삼성전자"), _row("005935", "삼성전자우"), _row("051915", "LG화학우")])
    kept = set(filter_common_stocks(df)["ticker"])
    assert kept == {"005930"}


def test_excludes_etfs_by_name_prefix():
    df = pd.DataFrame([_row("069500", "KODEX 200"), _row("102110", "TIGER 200"),
                       _row("114800", "KODEX 인버스"), _row("005930", "삼성전자")])
    assert set(filter_common_stocks(df)["ticker"]) == {"005930"}


def test_excludes_reits_by_security_group_not_name():
    """(Q-3 일원화) 리츠 배제는 SECUGRP '부동산투자회사' 경로. 이름에 '리츠' 유무는 무관."""
    df = pd.DataFrame([
        _row("330590", "롯데리츠", security_group="부동산투자회사"),
        _row("357250", "미래에셋맵스리츠", security_group="부동산투자회사"),
        _row("005930", "삼성전자"),
    ])
    kept, excluded = split_universe(df)
    assert set(kept["ticker"]) == {"005930"}
    assert set(excluded["ticker"]) == {"330590", "357250"}
    assert set(excluded["axis"]) == {"security_group"}


def test_reit_substring_false_positives_are_kept():
    """(오탐 회귀) '메리츠'·'블리츠' 는 리츠가 아니다 — 2026-09-15 발견, 138040·369370 부당 배제 사례."""
    df = pd.DataFrame([_row("138040", "메리츠금융지주"), _row("369370", "블리츠웨이엔터테인먼트")])
    assert set(filter_common_stocks(df)["ticker"]) == {"138040", "369370"}


def test_infra_and_investment_companies_are_row_kept():
    """(Q-4 수정) 사회간접자본투융자회사·투자회사는 적재 전 배제 아님 — 행 생성 후 자격 게이트가 담당.
    맥쿼리인프라 개별 하드코딩 제거: 088980 도 415640 과 같은 구분·같은 처리."""
    df = pd.DataFrame([
        _row("088980", "맥쿼리인프라", security_group="사회간접자본투융자회사"),
        _row("415640", "KB발해인프라", security_group="사회간접자본투융자회사"),
        _row("094800", "맵스리얼티", security_group="투자회사"),
    ])
    kept, excluded = split_universe(df)
    assert set(kept["ticker"]) == {"088980", "415640", "094800"}
    assert excluded.empty


def test_excludes_spac():
    df = pd.DataFrame([_row("123456", "케이비17호스팩"), _row("005930", "삼성전자")])
    assert set(filter_common_stocks(df)["ticker"]) == {"005930"}


def test_unresolved_security_group_is_kept_at_load():
    """지속화 fail-open: 증권구분 미해결(UNRESOLVED·컬럼 부재)은 적재 전 배제 사유가 아니다."""
    df_no_col = pd.DataFrame([{"ticker": "096610", "name": "알에프세미", "market": "KOSDAQ"}])
    kept, excluded = split_universe(df_no_col)
    assert list(kept["ticker"]) == ["096610"] and excluded.empty
    df_unres = pd.DataFrame([_row("096610", "알에프세미", "KOSDAQ", security_group="UNRESOLVED")])
    assert list(filter_common_stocks(df_unres)["ticker"]) == ["096610"]


@pytest.mark.parametrize("name,group,axis", [
    ("삼성전자우", "주권", "preferred"),
    ("CJ4우(전환)", "주권", "preferred"),
    ("KODEX 200", "UNRESOLVED", "etf"),
    ("메리츠제1호스팩", "주권", "spac"),
    ("롯데리츠", "부동산투자회사", "security_group"),
    ("메리츠금융지주", "주권", None),
    ("맵스리얼티", "투자회사", None),
])
def test_classify_exclusion_axis(name, group, axis):
    assert classify_exclusion_axis(name, group) == axis


def test_split_universe_preserves_columns_and_axis():
    df = pd.DataFrame([_row("005930", "삼성전자"), _row("005935", "삼성전자우")])
    kept, excluded = split_universe(df)
    assert list(kept.columns) == ["ticker", "name", "market", "security_group"]
    assert "axis" in excluded.columns and list(excluded["axis"]) == ["preferred"]
