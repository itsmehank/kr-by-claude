"""TradeConfig — env 파싱, DRY_RUN fail-closed."""
from decimal import Decimal

import pytest
from dotenv import dotenv_values

from kr_trading.config import TradeConfig, parse_bool_fail_closed


@pytest.mark.parametrize("raw,expected", [
    ("false", False), ("0", False), ("no", False), ("FALSE", False),
    ("true", True), ("1", True), (None, True), ("", True), ("maybe", True),
])
def test_parse_bool_fail_closed(raw, expected):
    assert parse_bool_fail_closed(raw) is expected


def test_load_defaults(monkeypatch):
    monkeypatch.setenv("TOSS_CLIENT_ID", "cid")
    monkeypatch.setenv("TOSS_CLIENT_SECRET", "sec")
    monkeypatch.delenv("TOSS_ACCOUNT_SEQ", raising=False)
    monkeypatch.delenv("TOSS_DRY_RUN", raising=False)
    monkeypatch.delenv("GUARD_MAX_ORDER_KRW", raising=False)
    monkeypatch.delenv("GUARD_MAX_DAILY_KRW", raising=False)
    monkeypatch.delenv("TOSS_BASE_URL", raising=False)  # conftest 가 격리를 위해 강제 설정(#92 동형) — 기본값 테스트는 이를 해제
    cfg = TradeConfig.load()
    assert cfg.account_seq is None
    assert cfg.dry_run is True
    assert cfg.base_url == "https://openapi.tossinvest.com"
    assert cfg.max_order_krw == Decimal("5000000")
    assert cfg.max_daily_krw == Decimal("10000000")


def test_load_explicit(monkeypatch):
    monkeypatch.setenv("TOSS_CLIENT_ID", "cid")
    monkeypatch.setenv("TOSS_CLIENT_SECRET", "sec")
    monkeypatch.setenv("TOSS_ACCOUNT_SEQ", "3")
    monkeypatch.setenv("TOSS_DRY_RUN", "false")
    monkeypatch.setenv("GUARD_MAX_ORDER_KRW", "1000000")
    cfg = TradeConfig.load()
    assert cfg.account_seq == 3 and cfg.dry_run is False
    assert cfg.max_order_krw == Decimal("1000000")


def test_conftest_isolation_forces_dry_run_and_blank_credentials():
    """conftest 가 토스 자격증명을 비우고 DRY_RUN 을 강제해야 한다(#92 동형)."""
    import os
    assert os.environ.get("TOSS_CLIENT_ID") == ""
    assert os.environ.get("TOSS_CLIENT_SECRET") == ""
    assert os.environ.get("TOSS_DRY_RUN") == "true"
    assert os.environ.get("TOSS_BASE_URL") == "http://127.0.0.1:1"
    assert os.environ.get("TOSS_ACCOUNT_SEQ") == ""
    assert os.environ.get("GUARD_MAX_ORDER_KRW") == "5000000"
    assert os.environ.get("GUARD_MAX_DAILY_KRW") == "10000000"


def test_env_example_account_seq_is_blank():
    """.env.example 의 TOSS_ACCOUNT_SEQ 인라인 주석이 python-dotenv 파싱 시 값으로
    읽히면(빈 값 뒤 주석 → 실측 '# GET /trade-api/accounts …') TradeConfig.load() 가
    int(그 문자열) 로 죽는다. 설명은 윗줄 주석으로 옮기고 값은 진짜 빈 문자열이어야 한다.
    """
    values = dotenv_values(".env.example")
    assert values["TOSS_ACCOUNT_SEQ"] == ""
    assert values["GUARD_MAX_ORDER_KRW"] == "5000000"
    assert values["GUARD_MAX_DAILY_KRW"] == "10000000"
