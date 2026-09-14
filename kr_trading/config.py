"""토스증권 매매 설정 — 기존 Config(DATABASE_URL 필수)와 분리.

DRY_RUN 은 fail-closed: 미설정·해석 불가 → True. 실주문은 명시적 "false" 만.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()

_FALSE = {"false", "0", "no", "off"}


def parse_bool_fail_closed(v: str | None) -> bool:
    if v is None:
        return True
    return v.strip().lower() not in _FALSE


@dataclass(frozen=True)
class TradeConfig:
    client_id: str
    client_secret: str
    account_seq: int | None
    base_url: str
    dry_run: bool
    max_order_krw: Decimal
    max_daily_krw: Decimal

    @classmethod
    def load(cls) -> "TradeConfig":
        seq = os.environ.get("TOSS_ACCOUNT_SEQ", "").strip()
        return cls(
            client_id=os.environ.get("TOSS_CLIENT_ID", ""),
            client_secret=os.environ.get("TOSS_CLIENT_SECRET", ""),
            account_seq=int(seq) if seq else None,
            base_url=os.environ.get("TOSS_BASE_URL", "https://openapi.tossinvest.com").rstrip("/"),
            dry_run=parse_bool_fail_closed(os.environ.get("TOSS_DRY_RUN")),
            max_order_krw=Decimal(os.environ.get("GUARD_MAX_ORDER_KRW", "5000000")),
            max_daily_krw=Decimal(os.environ.get("GUARD_MAX_DAILY_KRW", "10000000")),
        )
