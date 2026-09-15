"""TradeConfig — env 파싱, DRY_RUN fail-closed."""
from decimal import Decimal

import pytest

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
