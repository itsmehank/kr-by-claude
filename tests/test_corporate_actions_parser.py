# tests/test_corporate_actions_parser.py
import pytest

from kr_pipeline.corporate_actions.parser import parse_event_type, parse_ratio


def test_parse_액면분할():
    assert parse_event_type("주식분할결정") == "stock_split"


def test_parse_액면분할_keyword():
    assert parse_event_type("[기재정정]주식분할결정 ") == "stock_split"


def test_parse_액면병합():
    assert parse_event_type("주식병합결정") == "reverse_split"


def test_parse_회사분할():
    assert parse_event_type("회사분할결정") == "spinoff"


def test_parse_물적분할():
    assert parse_event_type("물적분할결정") == "spinoff"


def test_parse_회사합병():
    assert parse_event_type("회사합병결정") == "merger"


def test_parse_타법인합병():
    assert parse_event_type("타법인합병") == "merger"


def test_parse_자본감소():
    assert parse_event_type("자본감소결정") == "capital_reduction"


def test_parse_감자결정():
    assert parse_event_type("감자결정") == "capital_reduction"


def test_parse_unknown_returns_none():
    assert parse_event_type("정기주주총회 안내") is None


def test_parse_사업보고서_returns_none():
    """6 종 외 일반 공시는 None."""
    assert parse_event_type("사업보고서") is None


def test_parse_ratio_50_to_1():
    """제목에 50:1 패턴 → '50:1'"""
    assert parse_ratio("주식분할결정 50:1", "stock_split") == "50:1"


def test_parse_ratio_with_spaces():
    assert parse_ratio("주식병합결정 (1 : 10)", "reverse_split") == "1:10"


def test_parse_ratio_returns_none_no_pattern():
    assert parse_ratio("주식분할결정", "stock_split") is None
