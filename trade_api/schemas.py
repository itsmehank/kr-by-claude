"""프론트용 응답 모델. 모든 라우트는 이 모듈(또는 kr_trading.toss.models)의 모델을 response_model 로 선언.
bare dict 반환 금지 — FastAPI 는 dict 의 Decimal 을 float 로 내보낸다(spec §5 실측)."""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from kr_trading.toss.models import Account

AccountOut = Account  # 재사용 — 브리프 인터페이스 계약(schemas.py 소비처용 별칭)


class HealthOut(BaseModel):
    dryRun: bool
    maxOrderKrw: Decimal
    maxDailyKrw: Decimal
    accountSeq: int | None


class ErrorDetail(BaseModel):
    code: str
    message: str
    data: dict | None = None
    requestId: str | None = None


class ErrorBody(BaseModel):
    error: ErrorDetail
