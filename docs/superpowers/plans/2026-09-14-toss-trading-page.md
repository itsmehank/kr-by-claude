# 토스증권 매매 페이지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 웹에 `/trading` 페이지 1개를 추가해 국내 주식을 지정가·시장가로 사고팔고(정정·취소 포함), 보유·주문 현황을 확인한다. 토스 호출은 별도 프로세스 `trade_api`(:8001)에서만.

**Architecture:** `kr_trading/`(도메인: 토스 클라이언트·가드·감사로그) + `trade_api/`(FastAPI, sync 라우트, pydantic 응답 모델 필수) + `web/src/pages/TradingPage.tsx`. 주문은 `preview → previewToken → 전송` 2단계, `TOSS_DRY_RUN=true` 기본, 감사로그는 전송 전 INSERT → 응답 후 UPDATE. 상태 갱신은 폴링.

**Tech Stack:** Python ≥3.11, FastAPI 0.136, pydantic 2.13, httpx 0.28 (`httpx.Client` + `MockTransport`), psycopg 3 sync, React + TanStack Query + vitest.

**Spec:** `docs/superpowers/specs/2026-09-14-toss-trading-page-design.md` — 실행자는 spec §5(가드 순서)·§6(API 계약)·§11(스펙 JSON 차이)을 같이 읽는다.

## Global Constraints

- 브랜치 `feature/toss-trading-page`에서 작업. 커밋 전 `git branch --show-current`로 main 아님 확인. `git add`는 **명시 경로만**(CLAUDE.md 운영규칙 1·2).
- **토스 실접촉 0** — 모든 테스트는 `httpx.MockTransport`. conftest가 `TOSS_CLIENT_ID/SECRET=""`, `TOSS_DRY_RUN=true` 강제(Task 1).
- 숫자는 `Decimal ↔ str`만. `float` 경유 금지. **모든 `trade_api` 라우트는 pydantic 응답 모델 필수, bare dict 반환 금지**(spec §5 실측: bare dict는 Decimal→float).
- enum 필드(`side·orderType·timeInForce·status·accountType·warningType·currency`)는 `str`로 받아 unknown 값을 허용.
- 에러 envelope(`code·message·data·requestId`)는 가공 없이 프론트까지 전달.
- `api/`·`kr_pipeline/`(schema.sql 제외)·`web/src/lib/api.ts` **변경 0줄**. `kr_pipeline/common/krx.py:krx_tick_size`는 import만.
- suite 판정 전 `pgrep -f pytest`(운영규칙 3). 기대: 기존 1458 passed 유지 + 신규 전부 pass, 1 skipped, 1 deselected.
- schema.sql 변경은 `kr_pipeline`·`kr_test` 양쪽 psql 수동 적용(운영규칙 4).
- 상한 기본값 `GUARD_MAX_ORDER_KRW=5000000`, `GUARD_MAX_DAILY_KRW=10000000`. `TOSS_DRY_RUN` 미설정·해석 불가 → **true**(fail-closed).
- 커밋 메시지는 한국어, `Co-Authored-By` 트레일러 금지(사용자 CLAUDE.md).

---

## File Structure

| 파일 | 책임 | Task |
|---|---|---|
| `kr_trading/__init__.py`, `kr_trading/toss/__init__.py` | 패키지 | 1 |
| `kr_trading/config.py` | `TradeConfig.load()` — env 파싱, fail-closed DRY_RUN | 1 |
| `tests/conftest.py` | 토스 env 격리 3줄 추가 | 1 |
| `pyproject.toml`, `.env.example` | httpx 런타임 승격, 신규 env 키 | 1 |
| `kr_trading/toss/errors.py` | `TossApiError`, `GuardError` | 2 |
| `kr_trading/toss/models.py` | 토스 요청·응답 pydantic 모델(Decimal) | 2 |
| `kr_trading/toss/token.py` | `TokenManager` | 3 |
| `kr_trading/toss/ratelimit.py` | `RateLimiter`(그룹별 토큰버킷) | 4 |
| `kr_trading/toss/client.py` | `TossClient` — 헤더·envelope·401 1회 재시도·429 | 5 |
| `kr_pipeline/db/schema.sql` | `toss_order_audit` 테이블 추가 | 6 |
| `kr_trading/audit.py` | `AuditLog.begin()/finish()`, `daily_buy_total_krw()` | 6 |
| `kr_trading/guard.py` | `check_order()` 순수 함수 + `order_amount_krw()` | 7 |
| `kr_trading/preview.py` | `PreviewStore` (해시·TTL·clientOrderId) | 8 |
| `trade_api/__init__.py`, `trade_api/main.py`, `trade_api/deps.py` | 앱·풀·싱글톤 DI | 9 |
| `trade_api/schemas.py` | 프론트용 응답 모델 | 9 |
| `trade_api/routers/health.py`, `accounts.py` | `/health`, `/accounts` | 9 |
| `trade_api/routers/holdings.py`, `market.py` | `/holdings`(+mismatch), `/search`, `/quote`, `/buying-power`, `/sellable` | 10 |
| `trade_api/routers/orders.py` | preview·create·cancel·modify·list·detail | 11 |
| `web/vite.config.ts` | `/trade-api` 프록시 | 12 |
| `web/src/lib/tradeApi.ts`, `tradeTypes.ts`, `tradeErrors.ts` | 클라이언트·타입·에러 문구 매핑 | 12 |
| `web/src/components/trading/*.tsx`, `web/src/pages/TradingPage.tsx`, `App.tsx` | 화면 3영역·라우트·NAV | 13 |
| `README.md`, `CLAUDE.md`, `docs/toss/live-verification-checklist.md` | 구동법·운영규칙 6·실물 검증 체크리스트 | 14 |

---

### Task 1: 설정·의존성·테스트 격리

**Files:**
- Create: `kr_trading/__init__.py`, `kr_trading/toss/__init__.py`, `kr_trading/config.py`
- Modify: `pyproject.toml`(httpx 승격), `.env.example`, `tests/conftest.py:24-26` 아래
- Test: `tests/test_trading_config.py`

**Interfaces:**
- Produces: `TradeConfig(client_id: str, client_secret: str, account_seq: int | None, base_url: str, dry_run: bool, max_order_krw: Decimal, max_daily_krw: Decimal)`, `TradeConfig.load() -> TradeConfig`, `parse_bool_fail_closed(v: str | None) -> bool`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_trading_config.py
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
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_trading_config.py -v` → `ModuleNotFoundError: kr_trading`

- [ ] **Step 3: 구현**

```python
# kr_trading/__init__.py  (빈 파일)
# kr_trading/toss/__init__.py  (빈 파일)
```

```python
# kr_trading/config.py
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
```

`tests/conftest.py` — 26행(`os.environ["KRX_PW"] = ""`) 블록 바로 아래에 추가:

```python
# ── 토스증권 자격증명 무력화 + DRY_RUN 강제 (spec 2026-09-14 §10, #92 동형) ────
# 키를 pop 하지 않고 값만 비운다 — kr_trading/config.py 의 load_dotenv() 가
# "키가 없을 때만" .env 값을 복원하기 때문.
os.environ["TOSS_CLIENT_ID"] = ""
os.environ["TOSS_CLIENT_SECRET"] = ""
os.environ["TOSS_DRY_RUN"] = "true"
```

`pyproject.toml` — `dependencies` 배열에 `"httpx>=0.28.1",` 추가(`psycopg-pool` 뒤), `dev` 그룹의 `"httpx>=0.28.1",` 줄 삭제. `uv lock` 실행.

`.env.example` 끝에 추가:

```
# 토스증권 Open API (spec docs/superpowers/specs/2026-09-14-toss-trading-page-design.md §9)
TOSS_CLIENT_ID=
TOSS_CLIENT_SECRET=
TOSS_ACCOUNT_SEQ=            # GET /trade-api/accounts 로 확인 후 고정 (accountType=BROKERAGE)
TOSS_DRY_RUN=true            # 기본 true. 실주문은 명시적으로 false
GUARD_MAX_ORDER_KRW=5000000
GUARD_MAX_DAILY_KRW=10000000
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_trading_config.py -v` → 12 passed

- [ ] **Step 5: 커밋**

```bash
git branch --show-current   # feature/toss-trading-page
git add kr_trading/__init__.py kr_trading/toss/__init__.py kr_trading/config.py tests/test_trading_config.py tests/conftest.py pyproject.toml uv.lock .env.example
git commit -m "kr_trading: TradeConfig(fail-closed DRY_RUN)·httpx 런타임 승격·conftest 토스 격리"
```

---

### Task 2: 에러 타입 · 토스 모델

**Files:**
- Create: `kr_trading/toss/errors.py`, `kr_trading/toss/models.py`
- Test: `tests/test_trading_models.py`

**Interfaces:**
- Produces:
  - `TossApiError(status: int, code: str, message: str, data: dict | None, request_id: str | None)` (Exception)
  - `GuardError(code: str, message: str, data: dict | None = None)` (Exception) — `code`는 `guard/…`
  - `OrderCreateRequest(symbol, side, orderType, quantity: Decimal, price: Decimal | None = None, timeInForce="DAY", clientOrderId: str | None = None, confirmHighValueOrder: bool = False)` + `.to_toss_json() -> dict` (Decimal→str, None 제외)
  - `OrderModifyRequest(orderType, quantity: Decimal | None, price: Decimal | None, confirmHighValueOrder=False)` + `.to_toss_json()`
  - 응답: `Account`, `PriceResponse`, `PriceLimitResponse`, `OrderbookEntry`, `OrderbookResponse`, `StockWarning`, `BuyingPowerResponse`, `SellableQuantityResponse`, `Commission`, `Money(krw: Decimal, usd: Decimal | None)`, `HoldingsItem`, `HoldingsOverview`, `OrderExecution`, `Order`, `PaginatedOrderResponse`, `OrderResponse(orderId, clientOrderId)`, `OrderOperationResponse(orderId)`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_trading_models.py
"""토스 모델 — Decimal 왕복(float 미개입), unknown enum 허용, None 제외 직렬화."""
from decimal import Decimal

from kr_trading.toss.errors import GuardError, TossApiError
from kr_trading.toss.models import (
    HoldingsOverview, Order, OrderCreateRequest, OrderModifyRequest,
)


def test_order_create_to_toss_json_uses_strings_and_drops_none():
    req = OrderCreateRequest(symbol="005930", side="BUY", orderType="LIMIT",
                             quantity=Decimal("10"), price=Decimal("70000"),
                             clientOrderId="20260914-abcd1234")
    j = req.to_toss_json()
    assert j == {"symbol": "005930", "side": "BUY", "orderType": "LIMIT",
                 "quantity": "10", "price": "70000", "timeInForce": "DAY",
                 "clientOrderId": "20260914-abcd1234", "confirmHighValueOrder": False}
    assert isinstance(j["price"], str)


def test_market_order_has_no_price_key():
    req = OrderCreateRequest(symbol="005930", side="BUY", orderType="MARKET", quantity=Decimal("3"))
    assert "price" not in req.to_toss_json()


def test_modify_to_toss_json():
    j = OrderModifyRequest(orderType="LIMIT", quantity=Decimal("15"), price=Decimal("71000")).to_toss_json()
    assert j == {"orderType": "LIMIT", "quantity": "15", "price": "71000", "confirmHighValueOrder": False}


def test_order_parses_string_decimals_and_unknown_enum():
    o = Order.model_validate({
        "orderId": "ord_1", "symbol": "005930", "side": "BUY", "orderType": "WEIRD_NEW_TYPE",
        "timeInForce": "DAY", "status": "PENDING", "price": "70000", "quantity": "10",
        "orderAmount": None, "currency": "KRW", "orderedAt": "2026-09-14T09:00:00+09:00",
        "canceledAt": None,
        "execution": {"filledQuantity": "0", "averageFilledPrice": None, "filledAmount": None,
                      "commission": None, "tax": None, "filledAt": None, "settlementDate": None},
    })
    assert o.price == Decimal("70000") and o.orderType == "WEIRD_NEW_TYPE"
    assert o.model_dump(mode="json")["price"] == "70000"


def test_holdings_overview_money():
    h = HoldingsOverview.model_validate({
        "totalPurchaseAmount": {"krw": "1000000", "usd": None},
        "marketValue": {"krw": "1100000", "usd": None},
        "profitLoss": {"krw": "100000", "usd": None},
        "dailyProfitLoss": {"krw": "-5000", "usd": None},
        "items": [{"symbol": "005930", "name": "삼성전자", "marketCountry": "KR", "currency": "KRW",
                   "quantity": "10", "lastPrice": "110000", "averagePurchasePrice": "100000",
                   "marketValue": {"krw": "1100000", "usd": None}, "profitLoss": {"krw": "100000", "usd": None},
                   "dailyProfitLoss": {"krw": "-5000", "usd": None}, "cost": {"krw": "1000000", "usd": None}}],
    })
    assert h.items[0].quantity == Decimal("10") and h.profitLoss.krw == Decimal("100000")


def test_error_types():
    e = TossApiError(status=422, code="insufficient-buying-power", message="", data={"x": 1}, request_id="r1")
    assert e.status == 422 and e.code == "insufficient-buying-power" and "insufficient" in str(e)
    g = GuardError("guard/tick-size", "호가 단위 불일치", {"tick": 100})
    assert g.code.startswith("guard/") and g.data == {"tick": 100}
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_trading_models.py -v` → ImportError

- [ ] **Step 3: 구현**

```python
# kr_trading/toss/errors.py
"""토스 API 에러 envelope → 예외. 가공 없이 code/message/data/requestId 보존."""
from __future__ import annotations


class TossApiError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 data: dict | None = None, request_id: str | None = None):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.data = data
        self.request_id = request_id


class GuardError(Exception):
    """자체 가드 거부. code 는 'guard/…'."""

    def __init__(self, code: str, message: str, data: dict | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.data = data
```

```python
# kr_trading/toss/models.py
"""토스 Open API 모델 (openapi.json v1.2.17 기준).

- 숫자 필드는 스펙상 `type: string, format: decimal` → 전부 Decimal. float 경유 금지.
- enum 필드는 str — 스펙이 "unknown code 허용" 을 요구.
- 요청 모델은 to_toss_json() 으로 Decimal→str, None 필드 제외.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ── 요청 ────────────────────────────────────────────────────────────
class OrderCreateRequest(_Base):
    symbol: str
    side: str            # BUY | SELL
    orderType: str       # LIMIT | MARKET
    quantity: Decimal
    price: Decimal | None = None
    timeInForce: str = "DAY"
    clientOrderId: str | None = None
    confirmHighValueOrder: bool = False

    def to_toss_json(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


class OrderModifyRequest(_Base):
    orderType: str
    quantity: Decimal | None = None
    price: Decimal | None = None
    confirmHighValueOrder: bool = False

    def to_toss_json(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


# ── 응답 ────────────────────────────────────────────────────────────
class Account(_Base):
    accountNo: str
    accountSeq: int
    accountType: str


class PriceResponse(_Base):
    symbol: str
    timestamp: str | None = None
    lastPrice: Decimal
    currency: str


class PriceLimitResponse(_Base):
    timestamp: str
    currency: str
    upperLimitPrice: Decimal | None = None
    lowerLimitPrice: Decimal | None = None


class OrderbookEntry(_Base):
    price: Decimal
    volume: Decimal


class OrderbookResponse(_Base):
    timestamp: str | None = None
    currency: str
    asks: list[OrderbookEntry]
    bids: list[OrderbookEntry]


class StockWarning(_Base):
    warningType: str
    exchange: str | None = None
    startDate: str | None = None
    endDate: str | None = None


class BuyingPowerResponse(_Base):
    currency: str
    cashBuyingPower: Decimal


class SellableQuantityResponse(_Base):
    sellableQuantity: Decimal


class Commission(_Base):
    marketCountry: str
    commissionRate: Decimal
    startDate: str | None = None
    endDate: str | None = None


class Money(_Base):
    krw: Decimal
    usd: Decimal | None = None


class HoldingsItem(_Base):
    symbol: str
    name: str
    marketCountry: str
    currency: str
    quantity: Decimal
    lastPrice: Decimal
    averagePurchasePrice: Decimal
    marketValue: Money
    profitLoss: Money
    dailyProfitLoss: Money
    cost: Money


class HoldingsOverview(_Base):
    totalPurchaseAmount: Money
    marketValue: Money
    profitLoss: Money
    dailyProfitLoss: Money
    items: list[HoldingsItem]


class OrderExecution(_Base):
    filledQuantity: Decimal
    averageFilledPrice: Decimal | None = None
    filledAmount: Decimal | None = None
    commission: Decimal | None = None
    tax: Decimal | None = None
    filledAt: str | None = None
    settlementDate: str | None = None


class Order(_Base):
    orderId: str
    symbol: str
    side: str
    orderType: str
    timeInForce: str
    status: str
    price: Decimal | None = None
    quantity: Decimal
    orderAmount: Decimal | None = None
    currency: str
    orderedAt: str
    canceledAt: str | None = None
    execution: OrderExecution


class PaginatedOrderResponse(_Base):
    orders: list[Order]
    nextCursor: str | None = None
    hasNext: bool = False


class OrderResponse(_Base):
    orderId: str
    clientOrderId: str | None = None


class OrderOperationResponse(_Base):
    orderId: str
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_trading_models.py -v` → 6 passed

- [ ] **Step 5: 커밋**

```bash
git add kr_trading/toss/errors.py kr_trading/toss/models.py tests/test_trading_models.py
git commit -m "kr_trading.toss: TossApiError/GuardError + Decimal 기반 요청·응답 모델(unknown enum 허용)"
```

---

### Task 3: TokenManager

**Files:**
- Create: `kr_trading/toss/token.py`
- Test: `tests/test_trading_token.py`

**Interfaces:**
- Consumes: `TradeConfig`(Task 1), `TossApiError`(Task 2)
- Produces: `TokenManager(http: httpx.Client, cfg: TradeConfig, clock: Callable[[], float] = time.monotonic)`, `.get() -> str`(유효 토큰, 만료 60초 전 선제 갱신), `.invalidate()`(다음 `get()`에서 강제 재발급), `.issue_count: int`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_trading_token.py
"""TokenManager — 선제 갱신·동시 발급 직렬화·invalidate. 토스 접촉 0 (MockTransport)."""
import threading
from decimal import Decimal

import httpx
import pytest

from kr_trading.config import TradeConfig
from kr_trading.toss.errors import TossApiError
from kr_trading.toss.token import TokenManager

CFG = TradeConfig(client_id="cid", client_secret="sec", account_seq=None,
                  base_url="https://toss.test", dry_run=True,
                  max_order_krw=Decimal("5000000"), max_daily_krw=Decimal("10000000"))


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=CFG.base_url)


def test_issues_once_and_caches():
    calls = []

    def handler(req: httpx.Request):
        calls.append(req)
        assert req.url.path == "/oauth2/token"
        assert req.headers["content-type"].startswith("application/x-www-form-urlencoded")
        body = req.content.decode()
        assert "grant_type=client_credentials" in body and "client_id=cid" in body
        return httpx.Response(200, json={"access_token": "tok1", "token_type": "Bearer", "expires_in": 3600})

    tm = TokenManager(_client(handler), CFG)
    assert tm.get() == "tok1" and tm.get() == "tok1"
    assert len(calls) == 1


def test_refreshes_60s_before_expiry():
    now = [1000.0]
    n = [0]

    def handler(req):
        n[0] += 1
        return httpx.Response(200, json={"access_token": f"tok{n[0]}", "token_type": "Bearer", "expires_in": 120})

    tm = TokenManager(_client(handler), CFG, clock=lambda: now[0])
    assert tm.get() == "tok1"
    now[0] = 1000.0 + 59        # 만료 61초 전 → 아직 유효
    assert tm.get() == "tok1"
    now[0] = 1000.0 + 61        # 만료 59초 전 → 선제 갱신
    assert tm.get() == "tok2"


def test_invalidate_forces_reissue():
    n = [0]

    def handler(req):
        n[0] += 1
        return httpx.Response(200, json={"access_token": f"tok{n[0]}", "token_type": "Bearer", "expires_in": 3600})

    tm = TokenManager(_client(handler), CFG)
    assert tm.get() == "tok1"
    tm.invalidate()
    assert tm.get() == "tok2"


def test_concurrent_get_issues_once():
    """토큰은 클라이언트당 1개 — 동시 발급은 서로를 무효화하므로 Lock 으로 직렬화."""
    n = [0]
    gate = threading.Event()

    def handler(req):
        gate.wait(1.0)
        n[0] += 1
        return httpx.Response(200, json={"access_token": f"tok{n[0]}", "token_type": "Bearer", "expires_in": 3600})

    tm = TokenManager(_client(handler), CFG)
    results = []
    threads = [threading.Thread(target=lambda: results.append(tm.get())) for _ in range(5)]
    for t in threads: t.start()
    gate.set()
    for t in threads: t.join()
    assert n[0] == 1 and set(results) == {"tok1"}


def test_auth_failure_raises_toss_api_error():
    def handler(req):
        return httpx.Response(401, json={"error": {"code": "invalid-client", "message": "bad", "requestId": "r1"}})

    tm = TokenManager(_client(handler), CFG)
    with pytest.raises(TossApiError) as ei:
        tm.get()
    assert ei.value.status == 401 and ei.value.code == "invalid-client" and ei.value.request_id == "r1"
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_trading_token.py -v` → ImportError

- [ ] **Step 3: 구현**

```python
# kr_trading/toss/token.py
"""OAuth2 client_credentials 토큰 매니저.

제약(요약 문서 §3): 클라이언트당 유효 토큰 1개 — 재발급 시 이전 토큰 즉시 무효.
→ 프로세스 내 싱글톤 + Lock 직렬화, 만료 60초 전 선제 갱신, 디스크 저장 금지.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

import httpx

from kr_trading.config import TradeConfig
from kr_trading.toss.errors import TossApiError

REFRESH_MARGIN_SEC = 60.0


def raise_for_envelope(resp: httpx.Response) -> None:
    """4xx/5xx 면 에러 envelope 을 TossApiError 로. 본문이 envelope 이 아니면 code='http-error'."""
    if resp.status_code < 400:
        return
    try:
        err = resp.json().get("error", {}) or {}
    except ValueError:
        err = {}
    raise TossApiError(
        status=resp.status_code,
        code=err.get("code") or "http-error",
        message=err.get("message") or "",
        data=err.get("data"),
        request_id=err.get("requestId") or resp.headers.get("X-Request-Id"),
    )


class TokenManager:
    def __init__(self, http: httpx.Client, cfg: TradeConfig,
                 clock: Callable[[], float] = time.monotonic):
        self._http = http
        self._cfg = cfg
        self._clock = clock
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0
        self.issue_count = 0

    def _valid(self) -> bool:
        return self._token is not None and self._clock() < self._expires_at - REFRESH_MARGIN_SEC

    def get(self) -> str:
        if self._valid():
            return self._token  # type: ignore[return-value]
        with self._lock:
            if self._valid():           # 다른 스레드가 방금 갱신
                return self._token  # type: ignore[return-value]
            resp = self._http.post(
                "/oauth2/token",
                data={"grant_type": "client_credentials",
                      "client_id": self._cfg.client_id,
                      "client_secret": self._cfg.client_secret},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            raise_for_envelope(resp)
            body = resp.json()
            self._token = body["access_token"]
            self._expires_at = self._clock() + float(body.get("expires_in", 0))
            self.issue_count += 1
            return self._token

    def invalidate(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_trading_token.py -v` → 5 passed

- [ ] **Step 5: 커밋**

```bash
git add kr_trading/toss/token.py tests/test_trading_token.py
git commit -m "kr_trading.toss: TokenManager — Lock 직렬화·만료 60초 전 선제 갱신·invalidate"
```

---

### Task 4: RateLimiter

**Files:**
- Create: `kr_trading/toss/ratelimit.py`
- Test: `tests/test_trading_ratelimit.py`

**Interfaces:**
- Produces: `RateLimiter(clock=time.monotonic, sleep=time.sleep)`, `.acquire(group: str) -> None`(버킷 토큰 없으면 sleep), `.update_from_headers(group: str, headers: Mapping[str, str]) -> None`(`X-RateLimit-Limit`로 용량 보정), `.retry_after_seconds(headers) -> float | None`, `GROUP_LIMITS: dict[str, int]`, `group_for_path(path: str) -> str`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_trading_ratelimit.py
"""그룹별 토큰버킷 — 초기 한도, 헤더 보정, 경로→그룹 매핑, Retry-After."""
from kr_trading.toss.ratelimit import GROUP_LIMITS, RateLimiter, group_for_path


def test_group_limits_seed():
    assert GROUP_LIMITS["ACCOUNT"] == 1 and GROUP_LIMITS["ORDER"] == 10 and GROUP_LIMITS["MARKET_DATA"] == 15


def test_group_for_path():
    assert group_for_path("/oauth2/token") == "AUTH"
    assert group_for_path("/api/v1/accounts") == "ACCOUNT"
    assert group_for_path("/api/v1/holdings") == "ASSET"
    assert group_for_path("/api/v1/prices") == "MARKET_DATA"
    assert group_for_path("/api/v1/orderbook") == "MARKET_DATA"
    assert group_for_path("/api/v1/price-limits") == "MARKET_DATA"
    assert group_for_path("/api/v1/stocks/005930/warnings") == "STOCK"
    assert group_for_path("/api/v1/orders") == "ORDER"
    assert group_for_path("/api/v1/orders/abc/cancel") == "ORDER"
    assert group_for_path("/api/v1/orders/abc") == "ORDER_HISTORY"
    assert group_for_path("/api/v1/buying-power") == "ORDER_INFO"
    assert group_for_path("/api/v1/sellable-quantity") == "ORDER_INFO"
    assert group_for_path("/api/v1/commissions") == "ORDER_INFO"


def test_acquire_sleeps_when_bucket_empty():
    now = [0.0]
    slept = []
    rl = RateLimiter(clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    rl.acquire("ACCOUNT")            # 용량 1 → 소진
    rl.acquire("ACCOUNT")            # 재충전 1초 필요
    assert len(slept) == 1 and 0.9 <= slept[0] <= 1.0


def test_update_from_headers_changes_capacity():
    # fake sleep 은 fake clock 을 반드시 전진시킨다 — 실제 time.sleep 이 time.monotonic 을
    # 전진시키는 것과 동형. 전진하지 않는 fake 는 acquire 의 재충전 루프를 영원히 굶긴다.
    now = [0.0]
    slept = []
    rl = RateLimiter(clock=lambda: now[0],
                     sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    rl.update_from_headers("ORDER", {"X-RateLimit-Limit": "2"})
    rl.acquire("ORDER"); rl.acquire("ORDER")
    assert slept == []
    rl.acquire("ORDER")
    # wait = (1 - 0) / capacity → 보정이 적용됐으면 0.5, 초기값 10 이면 0.1
    assert len(slept) == 1 and abs(slept[0] - 0.5) < 1e-9


def test_retry_after():
    rl = RateLimiter()
    assert rl.retry_after_seconds({"Retry-After": "3"}) == 3.0
    assert rl.retry_after_seconds({}) is None
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_trading_ratelimit.py -v` → ImportError

- [ ] **Step 3: 구현**

```python
# kr_trading/toss/ratelimit.py
"""API 그룹별 토큰버킷 (요약 문서 §8). 초기값은 문서 표, X-RateLimit-Limit 로 런타임 보정."""
from __future__ import annotations

import re
import threading
import time
from typing import Callable, Mapping

GROUP_LIMITS: dict[str, int] = {
    "AUTH": 5, "ACCOUNT": 1, "ASSET": 5, "STOCK": 5, "STOCK_ALL": 1,
    "MARKET_INFO": 3, "MARKET_DATA": 15, "MARKET_DATA_CHART": 20,
    "ORDER": 10, "ORDER_HISTORY": 5, "ORDER_INFO": 6,
}

_ORDER_ACTION = re.compile(r"^/api/v1/orders/[^/]+/(cancel|modify)$")
_ORDER_DETAIL = re.compile(r"^/api/v1/orders/[^/]+$")


def group_for_path(path: str) -> str:
    if path == "/oauth2/token":
        return "AUTH"
    if path == "/api/v1/accounts":
        return "ACCOUNT"
    if path == "/api/v1/holdings":
        return "ASSET"
    if path in ("/api/v1/prices", "/api/v1/orderbook", "/api/v1/trades", "/api/v1/price-limits"):
        return "MARKET_DATA"
    if path == "/api/v1/candles":
        return "MARKET_DATA_CHART"
    if path == "/api/v1/stocks/all":
        return "STOCK_ALL"
    if path.startswith("/api/v1/stocks"):
        return "STOCK"
    if path in ("/api/v1/buying-power", "/api/v1/sellable-quantity", "/api/v1/commissions"):
        return "ORDER_INFO"
    if path == "/api/v1/orders" or _ORDER_ACTION.match(path):
        return "ORDER"
    if _ORDER_DETAIL.match(path):
        return "ORDER_HISTORY"
    return "MARKET_INFO"


class _Bucket:
    def __init__(self, capacity: int, now: float):
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.updated = now


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}

    def _bucket(self, group: str) -> _Bucket:
        b = self._buckets.get(group)
        if b is None:
            b = self._buckets[group] = _Bucket(GROUP_LIMITS.get(group, 3), self._clock())
        return b

    def _refill(self, b: _Bucket) -> None:
        now = self._clock()
        b.tokens = min(b.capacity, b.tokens + (now - b.updated) * b.capacity)  # 초당 capacity 개 재충전
        b.updated = now

    def acquire(self, group: str) -> None:
        while True:
            with self._lock:
                b = self._bucket(group)
                self._refill(b)
                if b.tokens >= 1.0:
                    b.tokens -= 1.0
                    return
                wait = (1.0 - b.tokens) / b.capacity
            self._sleep(wait)

    def update_from_headers(self, group: str, headers: Mapping[str, str]) -> None:
        raw = headers.get("X-RateLimit-Limit") or headers.get("x-ratelimit-limit")
        if not raw:
            return
        try:
            cap = int(raw)
        except ValueError:
            return
        with self._lock:
            b = self._bucket(group)
            if cap > 0 and cap != int(b.capacity):
                b.capacity = float(cap)
                b.tokens = min(b.tokens, b.capacity)

    @staticmethod
    def retry_after_seconds(headers: Mapping[str, str]) -> float | None:
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_trading_ratelimit.py -v` → 5 passed

- [ ] **Step 5: 커밋**

```bash
git add kr_trading/toss/ratelimit.py tests/test_trading_ratelimit.py
git commit -m "kr_trading.toss: RateLimiter — 그룹별 토큰버킷·경로 매핑·헤더 보정·Retry-After"
```

---

### Task 5: TossClient

**Files:**
- Create: `kr_trading/toss/client.py`
- Test: `tests/test_trading_client.py`

**Interfaces:**
- Consumes: `TokenManager`(Task 3), `RateLimiter`(Task 4), `raise_for_envelope`(Task 3), 모델(Task 2)
- Produces: `TossClient(cfg: TradeConfig, http: httpx.Client | None = None, token: TokenManager | None = None, limiter: RateLimiter | None = None, sleep=time.sleep)`
  - 저수준: `.request(method, path, *, params=None, json=None, account: bool = False) -> dict | list`(envelope `result` 언랩)
  - 고수준: `.accounts() -> list[Account]`, `.holdings() -> HoldingsOverview`, `.prices(symbols: list[str]) -> list[PriceResponse]`, `.orderbook(symbol) -> OrderbookResponse`, `.price_limits(symbol) -> PriceLimitResponse`, `.warnings(symbol) -> list[StockWarning]`, `.buying_power() -> BuyingPowerResponse`, `.sellable_quantity(symbol) -> SellableQuantityResponse`, `.commissions() -> list[Commission]`, `.create_order(req: OrderCreateRequest) -> OrderResponse`, `.modify_order(order_id, req: OrderModifyRequest) -> OrderOperationResponse`, `.cancel_order(order_id) -> OrderOperationResponse`, `.list_orders(status: str, cursor: str | None = None, limit: int | None = None) -> PaginatedOrderResponse`, `.get_order(order_id) -> Order`
  - `account=True` 경로에 `TOSS_ACCOUNT_SEQ` 미설정이면 `GuardError("guard/account-seq-missing", …)`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_trading_client.py
"""TossClient — 헤더 자동 부착·envelope 언랩·401 1회 재시도·429 Retry-After·에러 무가공."""
from decimal import Decimal

import httpx
import pytest

from kr_trading.config import TradeConfig
from kr_trading.toss.client import TossClient
from kr_trading.toss.errors import GuardError, TossApiError
from kr_trading.toss.models import OrderCreateRequest

CFG = TradeConfig(client_id="cid", client_secret="sec", account_seq=7,
                  base_url="https://toss.test", dry_run=True,
                  max_order_krw=Decimal("5000000"), max_daily_krw=Decimal("10000000"))
TOKEN_OK = httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})


def make(handler, cfg=CFG, sleeps=None):
    def route(req: httpx.Request):
        if req.url.path == "/oauth2/token":
            return TOKEN_OK
        return handler(req)
    http = httpx.Client(transport=httpx.MockTransport(route), base_url=cfg.base_url)
    return TossClient(cfg, http=http, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def test_headers_and_unwrap():
    seen = {}

    def h(req):
        seen.update(req.headers)
        seen["path"] = req.url.path
        seen["q"] = str(req.url.query, "utf-8")
        return httpx.Response(200, json={"result": [{"symbol": "005930", "timestamp": None, "lastPrice": "70000", "currency": "KRW"}]})

    c = make(h)
    out = c.prices(["005930"])
    assert seen["authorization"] == "Bearer tok" and "x-tossinvest-account" not in seen
    assert seen["path"] == "/api/v1/prices" and seen["q"] == "symbols=005930"
    assert out[0].lastPrice == Decimal("70000")


def test_account_header_on_account_paths():
    seen = {}

    def h(req):
        seen.update(req.headers)
        return httpx.Response(200, json={"result": {"currency": "KRW", "cashBuyingPower": "1000000"}})

    assert make(h).buying_power().cashBuyingPower == Decimal("1000000")
    assert seen["x-tossinvest-account"] == "7"


def test_account_path_without_seq_is_guard_error():
    cfg = TradeConfig(**{**CFG.__dict__, "account_seq": None})
    with pytest.raises(GuardError) as ei:
        make(lambda r: httpx.Response(200, json={"result": {}}), cfg=cfg).buying_power()
    assert ei.value.code == "guard/account-seq-missing"


def test_401_expired_token_retries_once_then_raises():
    n = [0]

    def h(req):
        n[0] += 1
        return httpx.Response(401, json={"error": {"code": "expired-token", "message": "", "requestId": "r"}})

    with pytest.raises(TossApiError) as ei:
        make(h).holdings()
    assert n[0] == 2 and ei.value.code == "expired-token"   # 재발급 후 딱 1회 재시도


def test_401_then_success():
    n = [0]

    def h(req):
        n[0] += 1
        if n[0] == 1:
            return httpx.Response(401, json={"error": {"code": "token-revoked", "message": ""}})
        return httpx.Response(200, json={"result": [{"accountNo": "1", "accountSeq": 7, "accountType": "BROKERAGE"}]})

    assert make(h).accounts()[0].accountSeq == 7 and n[0] == 2


def test_429_waits_retry_after_then_retries():
    n = [0]; sleeps = []

    def h(req):
        n[0] += 1
        if n[0] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {"code": "rate-limit-exceeded", "message": ""}})
        return httpx.Response(200, json={"result": {"sellableQuantity": "5"}})

    assert make(h, sleeps=sleeps).sellable_quantity("005930").sellableQuantity == Decimal("5")
    assert sleeps == [2.0] and n[0] == 2


def test_429_then_401_reissues_and_retries():
    """Retry-After 대기 중 토큰이 무효화돼도 재발급 경로를 타야 한다(원인별 1회)."""
    seen = []; sleeps = []

    def h(req):
        seen.append(1)
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={"error": {"code": "rate-limit-exceeded", "message": ""}})
        if len(seen) == 2:
            return httpx.Response(401, json={"error": {"code": "token-revoked", "message": ""}})
        return httpx.Response(200, json={"result": {"currency": "KRW", "cashBuyingPower": "1"}})

    assert make(h, sleeps=sleeps).buying_power().cashBuyingPower == Decimal("1")
    assert len(seen) == 3 and sleeps == [1.0]   # 최초 + 레이트 재시도 + 인증 재시도 = 상한 3


def test_429_persisting_retries_once_then_raises():
    n = [0]; sleeps = []

    def h(req):
        n[0] += 1
        return httpx.Response(429, headers={"Retry-After": "1"}, json={"error": {"code": "rate-limit-exceeded", "message": ""}})

    with pytest.raises(TossApiError) as ei:
        make(h, sleeps=sleeps).holdings()
    assert n[0] == 2 and ei.value.code == "rate-limit-exceeded"   # 루프 금지


def test_error_envelope_passthrough():
    def h(req):
        return httpx.Response(400, headers={"X-Request-Id": "req-9"}, json={"error": {
            "requestId": "req-9", "code": "invalid-request", "message": "호가 단위",
            "data": {"field": "price", "tickSize": "100"}}})

    with pytest.raises(TossApiError) as ei:
        make(h).create_order(OrderCreateRequest(symbol="005930", side="BUY", orderType="LIMIT",
                                                quantity=Decimal("1"), price=Decimal("70050")))
    e = ei.value
    assert (e.status, e.code, e.message, e.data, e.request_id) == (400, "invalid-request", "호가 단위", {"field": "price", "tickSize": "100"}, "req-9")


def test_create_order_sends_string_decimals():
    seen = {}

    def h(req):
        import json
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"result": {"orderId": "ord_1", "clientOrderId": "c1"}})

    r = make(h).create_order(OrderCreateRequest(symbol="005930", side="BUY", orderType="LIMIT",
                                                quantity=Decimal("10"), price=Decimal("70000"), clientOrderId="c1"))
    assert r.orderId == "ord_1" and seen["price"] == "70000" and seen["quantity"] == "10"
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_trading_client.py -v` → ImportError

- [ ] **Step 3: 구현**

```python
# kr_trading/toss/client.py
"""토스 Open API 동기 클라이언트 (spec §5 TossClient).

- Authorization 자동, 계좌 필요 경로만 X-Tossinvest-Account.
- 성공 envelope {result: …} 언랩. 에러 envelope 은 TossApiError 로 무가공 전달.
- 401 expired-token/token-revoked/invalid-token → 재발급 후 1회만 재시도.
- 429 → Retry-After(없으면 1s) 대기 후 1회 재시도.
"""
from __future__ import annotations

import time
from typing import Any, Callable

import httpx

from kr_trading.config import TradeConfig
from kr_trading.toss.errors import GuardError, TossApiError
from kr_trading.toss.models import (
    Account, BuyingPowerResponse, Commission, HoldingsOverview, Order, OrderbookResponse,
    OrderCreateRequest, OrderModifyRequest, OrderOperationResponse, OrderResponse,
    PaginatedOrderResponse, PriceLimitResponse, PriceResponse, SellableQuantityResponse,
    StockWarning,
)
from kr_trading.toss.ratelimit import RateLimiter, group_for_path
from kr_trading.toss.token import TokenManager, raise_for_envelope

_REISSUE_CODES = {"expired-token", "token-revoked", "invalid-token"}


class TossClient:
    def __init__(self, cfg: TradeConfig, http: httpx.Client | None = None,
                 token: TokenManager | None = None, limiter: RateLimiter | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.cfg = cfg
        self._http = http or httpx.Client(base_url=cfg.base_url, timeout=httpx.Timeout(10.0, connect=5.0))
        self._token = token or TokenManager(self._http, cfg)
        self._limiter = limiter or RateLimiter()
        self._sleep = sleep

    # ── 저수준 ─────────────────────────────────────────────────────
    def request(self, method: str, path: str, *, params: dict | None = None,
                json: Any = None, account: bool = False) -> Any:
        headers = {"Accept": "application/json"}
        if account:
            if self.cfg.account_seq is None:
                raise GuardError("guard/account-seq-missing",
                                 "TOSS_ACCOUNT_SEQ 미설정 — GET /trade-api/accounts 로 확인 후 .env 에 고정")
            headers["X-Tossinvest-Account"] = str(self.cfg.account_seq)
        group = group_for_path(path)
        # 재시도는 원인별로 각 1회, 최대 3회 시도(최초 + 인증 1 + 레이트 1). 두 조건을
        # 순차 if 로 두면 "429 재시도 응답이 401 token-revoked" 인 경우가 재발급을 못 타므로
        # 원인별 플래그를 쓰는 유한 루프로 둔다 — Retry-After 대기 중 외부 재발급으로 토큰이
        # 무효화되는 것은 문서가 경고하는 실제 시나리오다.
        retried_auth = False
        retried_rate = False
        while True:
            resp = self._send(method, path, params, json, headers, group)
            if (resp.status_code == 401 and not retried_auth
                    and _error_code(resp) in _REISSUE_CODES):
                retried_auth = True
                self._token.invalidate()
                continue
            if resp.status_code == 429 and not retried_rate:
                retried_rate = True
                self._sleep(self._limiter.retry_after_seconds(resp.headers) or 1.0)
                continue
            break
        raise_for_envelope(resp)
        body = resp.json()
        return body.get("result") if isinstance(body, dict) else body

    def _send(self, method, path, params, json, headers, group) -> httpx.Response:
        self._limiter.acquire(group)
        h = dict(headers)
        h["Authorization"] = f"Bearer {self._token.get()}"
        resp = self._http.request(method, path, params=params, json=json, headers=h)
        self._limiter.update_from_headers(group, resp.headers)
        return resp

    # ── 고수준 ─────────────────────────────────────────────────────
    def accounts(self) -> list[Account]:
        return [Account.model_validate(a) for a in self.request("GET", "/api/v1/accounts")]

    def holdings(self) -> HoldingsOverview:
        return HoldingsOverview.model_validate(self.request("GET", "/api/v1/holdings", account=True))

    def prices(self, symbols: list[str]) -> list[PriceResponse]:
        r = self.request("GET", "/api/v1/prices", params={"symbols": ",".join(symbols)})
        return [PriceResponse.model_validate(p) for p in r]

    def orderbook(self, symbol: str) -> OrderbookResponse:
        return OrderbookResponse.model_validate(self.request("GET", "/api/v1/orderbook", params={"symbol": symbol}))

    def price_limits(self, symbol: str) -> PriceLimitResponse:
        return PriceLimitResponse.model_validate(self.request("GET", "/api/v1/price-limits", params={"symbol": symbol}))

    def warnings(self, symbol: str) -> list[StockWarning]:
        return [StockWarning.model_validate(w) for w in self.request("GET", f"/api/v1/stocks/{symbol}/warnings")]

    def buying_power(self) -> BuyingPowerResponse:
        return BuyingPowerResponse.model_validate(
            self.request("GET", "/api/v1/buying-power", params={"currency": "KRW"}, account=True))

    def sellable_quantity(self, symbol: str) -> SellableQuantityResponse:
        return SellableQuantityResponse.model_validate(
            self.request("GET", "/api/v1/sellable-quantity", params={"symbol": symbol}, account=True))

    def commissions(self) -> list[Commission]:
        return [Commission.model_validate(c) for c in self.request("GET", "/api/v1/commissions", account=True)]

    def create_order(self, req: OrderCreateRequest) -> OrderResponse:
        return OrderResponse.model_validate(self.request("POST", "/api/v1/orders", json=req.to_toss_json(), account=True))

    def modify_order(self, order_id: str, req: OrderModifyRequest) -> OrderOperationResponse:
        return OrderOperationResponse.model_validate(
            self.request("POST", f"/api/v1/orders/{order_id}/modify", json=req.to_toss_json(), account=True))

    def cancel_order(self, order_id: str) -> OrderOperationResponse:
        return OrderOperationResponse.model_validate(
            self.request("POST", f"/api/v1/orders/{order_id}/cancel", json={}, account=True))

    def list_orders(self, status: str, cursor: str | None = None, limit: int | None = None) -> PaginatedOrderResponse:
        params: dict[str, Any] = {"status": status}
        if cursor: params["cursor"] = cursor
        if limit: params["limit"] = limit
        return PaginatedOrderResponse.model_validate(self.request("GET", "/api/v1/orders", params=params, account=True))

    def get_order(self, order_id: str) -> Order:
        return Order.model_validate(self.request("GET", f"/api/v1/orders/{order_id}", account=True))


def _error_code(resp: httpx.Response) -> str:
    try:
        return (resp.json().get("error") or {}).get("code") or ""
    except ValueError:
        return ""
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_trading_client.py -v` → 10 passed

- [ ] **Step 5: 커밋**

```bash
git add kr_trading/toss/client.py tests/test_trading_client.py
git commit -m "kr_trading.toss: TossClient — 헤더 자동·envelope 언랩·401 1회 재시도·429 대기·에러 무가공"
```

---

### Task 6: 감사로그 테이블 · AuditLog

**Files:**
- Modify: `kr_pipeline/db/schema.sql`(파일 끝에 테이블 추가 — 기존 테이블 무변경)
- Create: `kr_trading/audit.py`
- Test: `tests/test_trading_audit.py`(kr_test DB 사용 — conftest가 schema.sql 적용)

**Interfaces:**
- Produces:
  - `AuditLog(conn: psycopg.Connection)`
  - `.begin(kind: str, symbol: str, side: str | None, client_order_id: str | None, order_amount_krw: Decimal | None, request_json: dict, dry_run: bool) -> int`(audit id; **전송 전 INSERT**, `http_status NULL`)
  - `.finish(audit_id: int, *, http_status: int, error_code: str | None = None, request_id: str | None = None, order_id: str | None = None, response_json: dict | None = None) -> None`
  - `.daily_buy_total_krw(today_kst: date) -> Decimal`(`kind='create' AND NOT dry_run AND side='BUY' AND http_status=200`, KST 자정 경계)
  - `kst_today() -> date`

- [ ] **Step 1: schema.sql 끝에 추가**

```sql
-- ── 토스증권 주문 감사로그 (spec 2026-09-14 §5 AuditLog) ────────────────────────
-- append-only. 전송 직전 INSERT(http_status NULL = pending) → 응답 후 UPDATE.
-- 1일 누적 상한 집계: kind='create' AND NOT dry_run AND side='BUY' AND http_status=200, KST 자정 경계.
CREATE TABLE IF NOT EXISTS toss_order_audit (
  id               BIGSERIAL PRIMARY KEY,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  kind             TEXT NOT NULL,               -- create | modify | cancel
  client_order_id  TEXT,
  symbol           TEXT NOT NULL,
  side             TEXT,                        -- BUY | SELL (cancel 은 NULL 가능)
  order_amount_krw NUMERIC(18, 2),              -- 가드 5 기준 금액 (MARKET 은 상한가×수량)
  request_json     JSONB NOT NULL,
  dry_run          BOOLEAN NOT NULL,
  http_status      INTEGER,                     -- NULL = pending(응답 미수신)
  error_code       TEXT,
  request_id       TEXT,                        -- 토스 X-Request-Id
  order_id         TEXT,
  response_json    JSONB,
  responded_at     TIMESTAMPTZ,
  CONSTRAINT toss_order_audit_kind_chk CHECK (kind IN ('create', 'modify', 'cancel'))
);
CREATE INDEX IF NOT EXISTS idx_toss_order_audit_day ON toss_order_audit (created_at, side, dry_run);
```

- [ ] **Step 2: 양쪽 DB 적용(운영규칙 4)**

```bash
export $(grep -E '^(DATABASE_URL|TEST_DATABASE_URL)=' .env | xargs)
psql "$DATABASE_URL" -f kr_pipeline/db/schema.sql
psql "$TEST_DATABASE_URL" -f kr_pipeline/db/schema.sql
psql "$DATABASE_URL" -c "\d toss_order_audit" | head -5
```

- [ ] **Step 3: 실패 테스트 작성**

```python
# tests/test_trading_audit.py
"""AuditLog — 전송 전 INSERT(pending) → finish UPDATE, 1일 BUY 누적(KST·dry_run·kind 필터)."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest

from kr_trading.audit import AuditLog, kst_today

KST = timezone(timedelta(hours=9))


@pytest.fixture
def conn(test_db_url):
    with psycopg.connect(test_db_url) as c:
        c.execute("DELETE FROM toss_order_audit")
        yield c
        c.rollback()


def test_begin_leaves_pending_row_even_if_send_never_finishes(conn):
    log = AuditLog(conn)
    aid = log.begin("create", "005930", "BUY", "c1", Decimal("700000"),
                    {"symbol": "005930", "price": "70000", "quantity": "10"}, dry_run=False)
    conn.commit()
    row = conn.execute("SELECT http_status, order_id, request_json->>'price' FROM toss_order_audit WHERE id=%s", (aid,)).fetchone()
    assert row == (None, None, "70000")   # pending 행 존재


def test_finish_updates_row(conn):
    log = AuditLog(conn)
    aid = log.begin("create", "005930", "BUY", "c1", Decimal("700000"), {"x": 1}, dry_run=False)
    log.finish(aid, http_status=200, request_id="req-1", order_id="ord_1", response_json={"orderId": "ord_1"})
    conn.commit()
    row = conn.execute("SELECT http_status, request_id, order_id, responded_at IS NOT NULL FROM toss_order_audit WHERE id=%s", (aid,)).fetchone()
    assert row == (200, "req-1", "ord_1", True)


def test_daily_buy_total_filters(conn):
    log = AuditLog(conn)
    today = kst_today()
    def add(kind, side, amt, dry, status, created=None):
        aid = log.begin(kind, "005930", side, None, Decimal(amt), {}, dry_run=dry)
        if status is not None:
            log.finish(aid, http_status=status)
        if created is not None:
            conn.execute("UPDATE toss_order_audit SET created_at=%s WHERE id=%s", (created, aid))
    add("create", "BUY", "1000000", False, 200)          # 포함
    add("create", "BUY", "2000000", False, 200)          # 포함
    add("create", "BUY", "5000000", True, 200)           # dry_run 제외
    add("create", "SELL", "5000000", False, 200)         # SELL 제외
    add("modify", "BUY", "5000000", False, 200)          # 정정 제외(이중 집계 방지)
    add("create", "BUY", "5000000", False, 422)          # 거부 제외
    add("create", "BUY", "5000000", False, None)         # pending 제외
    yesterday_2330 = datetime.combine(today - timedelta(days=1), datetime.min.time(), KST) + timedelta(hours=23, minutes=30)
    add("create", "BUY", "5000000", False, 200, created=yesterday_2330)   # 전날 23:30 KST 제외
    conn.commit()
    assert log.daily_buy_total_krw(today) == Decimal("3000000")


def test_kst_today_is_date():
    assert isinstance(kst_today(), date)
```

- [ ] **Step 4: 실패 확인** — `uv run pytest tests/test_trading_audit.py -v` → ImportError

- [ ] **Step 5: 구현**

```python
# kr_trading/audit.py
"""주문 감사로그 (spec §5). 전송 직전 begin() → 응답 후 finish(). 커밋은 호출자."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from psycopg import Connection
from psycopg.types.json import Jsonb

KST = timezone(timedelta(hours=9))


def kst_today() -> date:
    return datetime.now(KST).date()


class AuditLog:
    def __init__(self, conn: Connection):
        self._conn = conn

    def begin(self, kind: str, symbol: str, side: str | None, client_order_id: str | None,
              order_amount_krw: Decimal | None, request_json: dict, dry_run: bool) -> int:
        row = self._conn.execute(
            """
            INSERT INTO toss_order_audit
              (kind, symbol, side, client_order_id, order_amount_krw, request_json, dry_run)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (kind, symbol, side, client_order_id, order_amount_krw, Jsonb(request_json), dry_run),
        ).fetchone()
        return int(row[0])

    def finish(self, audit_id: int, *, http_status: int, error_code: str | None = None,
               request_id: str | None = None, order_id: str | None = None,
               response_json: dict | None = None) -> None:
        self._conn.execute(
            """
            UPDATE toss_order_audit
               SET http_status=%s, error_code=%s, request_id=%s, order_id=%s,
                   response_json=%s, responded_at=now()
             WHERE id=%s
            """,
            (http_status, error_code, request_id, order_id,
             Jsonb(response_json) if response_json is not None else None, audit_id),
        )

    def daily_buy_total_krw(self, today_kst: date) -> Decimal:
        row = self._conn.execute(
            """
            SELECT COALESCE(SUM(order_amount_krw), 0)
              FROM toss_order_audit
             WHERE kind = 'create' AND NOT dry_run AND side = 'BUY' AND http_status = 200
               AND (created_at AT TIME ZONE 'Asia/Seoul')::date = %s
            """,
            (today_kst,),
        ).fetchone()
        return Decimal(row[0])
```

- [ ] **Step 6: 통과 확인** — `uv run pytest tests/test_trading_audit.py -v` → 4 passed

- [ ] **Step 7: 커밋**

```bash
git add kr_pipeline/db/schema.sql kr_trading/audit.py tests/test_trading_audit.py
git commit -m "toss_order_audit 테이블 + AuditLog — 전송 전 INSERT·응답 후 UPDATE·KST 1일 BUY 누적(create·non-dry·200)"
```

---

### Task 7: OrderGuard (순수 함수)

**Files:**
- Create: `kr_trading/guard.py`
- Test: `tests/test_trading_guard.py`

**Interfaces:**
- Consumes: `krx_tick_size`(`kr_pipeline/common/krx.py`, import만), `GuardError`, `OrderCreateRequest`, `TradeConfig`
- Produces:
  - `order_amount_krw(req: OrderCreateRequest, upper_limit: Decimal | None) -> Decimal` — LIMIT `price×qty`, MARKET `upper×qty`(upper None이면 `GuardError("guard/price-limit-unavailable")`)
  - `check_order(req: OrderCreateRequest, *, cfg: TradeConfig, upper_limit: Decimal | None, lower_limit: Decimal | None, daily_buy_total: Decimal, sellable_qty: Decimal | None, count_toward_daily: bool = True) -> GuardResult`
  - `GuardResult(amount_krw: Decimal, amount_basis: str  # "limit"|"upper_limit", warnings: list[str])`
  - 순서·코드는 spec §5 1~8. `count_toward_daily=False`는 정정 재검용(1일 누적 생략)

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_trading_guard.py
"""OrderGuard — spec §5 1~8 규칙별 표 케이스. IO 없음."""
from decimal import Decimal

import pytest

from kr_trading.config import TradeConfig
from kr_trading.guard import check_order, order_amount_krw
from kr_trading.toss.errors import GuardError
from kr_trading.toss.models import OrderCreateRequest

CFG = TradeConfig(client_id="", client_secret="", account_seq=1, base_url="x", dry_run=True,
                  max_order_krw=Decimal("5000000"), max_daily_krw=Decimal("10000000"))
D = Decimal


def buy(qty="10", price="70000", order_type="LIMIT", side="BUY"):
    return OrderCreateRequest(symbol="005930", side=side, orderType=order_type,
                              quantity=D(qty), price=D(price) if price is not None else None)


def run(req, **kw):
    base = dict(cfg=CFG, upper_limit=D("91000"), lower_limit=D("49000"), daily_buy_total=D("0"), sellable_qty=None)
    base.update(kw)
    return check_order(req, **base)


def test_limit_ok():
    r = run(buy())
    assert r.amount_krw == D("700000") and r.amount_basis == "limit"


@pytest.mark.parametrize("req,code", [
    (buy(price=None), "guard/price-required"),
    (buy(order_type="MARKET", price="70000"), "guard/price-forbidden"),
    (buy(qty="0"), "guard/quantity-invalid"),
    (buy(qty="1.5"), "guard/quantity-invalid"),
    (buy(price="70000.5"), "guard/tick-size"),        # 비정수 가격 → krx_tick_size 도달 전 차단
    (buy(price="70050"), "guard/tick-size"),           # 5만~20만 구간 tick 100
    (buy(price="95000"), "guard/price-out-of-range"),  # 상한 91000 초과
    (buy(price="48000"), "guard/price-out-of-range"),  # 하한 49000 미달
    (buy(qty="100", price="70000"), "guard/max-order-amount"),   # 700만 > 500만
])
def test_rejections_in_order(req, code):
    with pytest.raises(GuardError) as ei:
        run(req)
    assert ei.value.code == code


def test_tick_size_error_carries_correct_tick():
    with pytest.raises(GuardError) as ei:
        run(buy(price="70050"))
    assert ei.value.data == {"tickSize": "100"}


def test_market_uses_upper_limit_basis():
    r = run(buy(order_type="MARKET", price=None, qty="10"))
    assert r.amount_krw == D("910000") and r.amount_basis == "upper_limit"


def test_limit_without_price_limits_is_blocked():
    """KR 종목은 상·하한가가 항상 있다 — None 이면 상류 이상, MARKET 과 동일하게 fail-closed."""
    with pytest.raises(GuardError) as ei:
        run(buy(), upper_limit=None)
    assert ei.value.code == "guard/price-limit-unavailable"
    with pytest.raises(GuardError) as ei:
        run(buy(), lower_limit=None)
    assert ei.value.code == "guard/price-limit-unavailable"


def test_order_amount_krw_limit_without_price_is_guard_error():
    """assert 가 아니라 GuardError — python -O 에서도 방어선 유지."""
    with pytest.raises(GuardError) as ei:
        order_amount_krw(buy(price=None), D("91000"))
    assert ei.value.code == "guard/price-required"


def test_market_without_upper_limit_is_blocked():
    with pytest.raises(GuardError) as ei:
        run(buy(order_type="MARKET", price=None), upper_limit=None)
    assert ei.value.code == "guard/price-limit-unavailable"


def test_daily_cap_counts_existing_total():
    with pytest.raises(GuardError) as ei:
        run(buy(qty="50", price="70000"), daily_buy_total=D("7000000"))   # 350만 + 700만 > 1000만
    assert ei.value.code == "guard/max-daily-amount"
    assert ei.value.data["dailyTotalKrw"] == "7000000"


def test_daily_cap_skipped_for_modify_recheck():
    r = run(buy(qty="50", price="70000"), daily_buy_total=D("7000000"), count_toward_daily=False)
    assert r.amount_krw == D("3500000")


def test_sell_is_exempt_from_daily_cap_but_checks_sellable():
    r = run(buy(side="SELL", qty="5"), daily_buy_total=D("99000000"), sellable_qty=D("5"))
    assert r.amount_krw == D("350000")
    with pytest.raises(GuardError) as ei:
        run(buy(side="SELL", qty="6"), sellable_qty=D("5"))
    assert ei.value.code == "guard/sellable-exceeded"


def test_high_value_flags():
    big = TradeConfig(**{**CFG.__dict__, "max_order_krw": D("99999999999"), "max_daily_krw": D("99999999999")})
    with pytest.raises(GuardError) as ei:
        run(buy(qty="2000", price="70000"), cfg=big)   # 1.4억, confirm 없음
    assert ei.value.code == "guard/confirm-high-value-required"
    ok = OrderCreateRequest(symbol="005930", side="BUY", orderType="LIMIT", quantity=D("2000"),
                            price=D("70000"), confirmHighValueOrder=True)
    assert "high_value" in run(ok, cfg=big).warnings
    with pytest.raises(GuardError) as ei:
        run(OrderCreateRequest(symbol="005930", side="BUY", orderType="LIMIT", quantity=D("50000"),
                               price=D("70000"), confirmHighValueOrder=True), cfg=big)   # 35억
    assert ei.value.code == "guard/max-order-amount-exceeded"


def test_order_amount_krw_direct():
    assert order_amount_krw(buy(), None) == D("700000")
    assert order_amount_krw(buy(order_type="MARKET", price=None), D("91000")) == D("910000")
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_trading_guard.py -v` → ImportError

- [ ] **Step 3: 구현**

```python
# kr_trading/guard.py
"""OrderGuard (spec §5 1~8) — 순수 함수. 하나라도 걸리면 GuardError, 토스 주문 API 미호출.

호가단위 판정은 kr_pipeline/common/krx.py:krx_tick_size 재사용(신설 금지). 로컬 검증은
API 왕복 전 편의이며 최종 판정권은 API(에러 data 에 올바른 단위가 옴).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from kr_pipeline.common.krx import krx_tick_size
from kr_trading.config import TradeConfig
from kr_trading.toss.errors import GuardError
from kr_trading.toss.models import OrderCreateRequest

HIGH_VALUE_KRW = Decimal("100000000")        # 1억 — confirmHighValueOrder 필수
MAX_ORDER_KRW_ABSOLUTE = Decimal("3000000000")  # 30억 — 스펙 422 max-order-amount-exceeded


@dataclass
class GuardResult:
    amount_krw: Decimal
    amount_basis: str            # "limit" | "upper_limit"
    warnings: list[str] = field(default_factory=list)


def order_amount_krw(req: OrderCreateRequest, upper_limit: Decimal | None) -> Decimal:
    if req.orderType == "MARKET":
        if upper_limit is None:
            raise GuardError("guard/price-limit-unavailable", "상한가 조회 불가 — 시장가 금액 산정 불가")
        return upper_limit * req.quantity
    if req.price is None:   # assert 금지 — python -O 에서도 방어선 유지
        raise GuardError("guard/price-required", "지정가 주문은 가격이 필요합니다")
    return req.price * req.quantity


def check_order(req: OrderCreateRequest, *, cfg: TradeConfig,
                upper_limit: Decimal | None, lower_limit: Decimal | None,
                daily_buy_total: Decimal, sellable_qty: Decimal | None,
                count_toward_daily: bool = True) -> GuardResult:
    # 1. LIMIT ↔ price 정합
    if req.orderType == "LIMIT" and req.price is None:
        raise GuardError("guard/price-required", "지정가 주문은 가격이 필요합니다")
    if req.orderType == "MARKET" and req.price is not None:
        raise GuardError("guard/price-forbidden", "시장가 주문에는 가격을 보내지 않습니다")
    # 2. 수량 양의 정수
    if req.quantity <= 0 or req.quantity != req.quantity.to_integral_value():
        raise GuardError("guard/quantity-invalid", "수량은 양의 정수", {"quantity": str(req.quantity)})
    # 3. 호가단위 / 4. 상하한
    if req.price is not None:
        if req.price != req.price.to_integral_value():
            raise GuardError("guard/tick-size", "KR 가격은 정수(원)", {"tickSize": "1"})
        tick = Decimal(krx_tick_size(float(req.price)))
        if req.price % tick != 0:
            raise GuardError("guard/tick-size", f"호가 단위 {tick}원 배수가 아닙니다", {"tickSize": str(tick)})
        # KR 종목은 상·하한가가 항상 있다 — None 은 상류 이상이므로 MARKET 과 동일하게 fail-closed
        if upper_limit is None or lower_limit is None:
            raise GuardError("guard/price-limit-unavailable", "상·하한가 조회 불가 — 가격 범위 검증 불가")
        if req.price > upper_limit or req.price < lower_limit:
            raise GuardError("guard/price-out-of-range", "상·하한가 범위 밖",
                             {"upperLimitPrice": str(upper_limit), "lowerLimitPrice": str(lower_limit)})
    # 5. 1건 상한
    amount = order_amount_krw(req, upper_limit)
    basis = "upper_limit" if req.orderType == "MARKET" else "limit"
    if amount > cfg.max_order_krw:
        raise GuardError("guard/max-order-amount", "1건 주문 금액 상한 초과",
                         {"amountKrw": str(amount), "maxOrderKrw": str(cfg.max_order_krw), "amountBasis": basis})
    # 6. 1일 누적 (BUY, create 만)
    if req.side == "BUY" and count_toward_daily and daily_buy_total + amount > cfg.max_daily_krw:
        raise GuardError("guard/max-daily-amount", "1일 매수 누적 상한 초과",
                         {"amountKrw": str(amount), "dailyTotalKrw": str(daily_buy_total), "maxDailyKrw": str(cfg.max_daily_krw)})
    # 7. 매도 가능 수량
    if req.side == "SELL" and sellable_qty is not None and req.quantity > sellable_qty:
        raise GuardError("guard/sellable-exceeded", "판매 가능 수량 초과",
                         {"sellableQuantity": str(sellable_qty), "quantity": str(req.quantity)})
    # 8. 고액
    warnings: list[str] = []
    if amount >= MAX_ORDER_KRW_ABSOLUTE:
        raise GuardError("guard/max-order-amount-exceeded", "30억 이상 주문은 접수 불가", {"amountKrw": str(amount)})
    if amount >= HIGH_VALUE_KRW:
        if not req.confirmHighValueOrder:
            raise GuardError("guard/confirm-high-value-required", "1억 이상 주문은 confirmHighValueOrder=true 필요",
                             {"amountKrw": str(amount)})
        warnings.append("high_value")
    return GuardResult(amount_krw=amount, amount_basis=basis, warnings=warnings)
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_trading_guard.py -v` → 20 passed

- [ ] **Step 5: 커밋**

```bash
git add kr_trading/guard.py tests/test_trading_guard.py
git commit -m "kr_trading.guard: check_order 순수 함수 — spec §5 1~8(krx_tick_size 재사용·시장가 상한가 기준·정정 누적 제외)"
```

---

### Task 8: PreviewStore

**Files:**
- Create: `kr_trading/preview.py`
- Test: `tests/test_trading_preview.py`

**Interfaces:**
- Produces:
  - `new_client_order_id(today: date | None = None) -> str` — `{yyyymmdd}-{uuid8}`, ≤36자, `[A-Za-z0-9_-]`
  - `canonical_hash(payload: dict) -> str` — `sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")))` hex
  - `PreviewStore(ttl_sec: float = 300, clock=time.monotonic)`, `.put(payload: dict, meta: dict) -> str`(token), `.get(token: str) -> tuple[dict, dict] | None`(만료·부재 None), `.verify(token: str, payload: dict) -> dict`(meta 반환; 부재 → `GuardError("guard/preview-required")`, 불일치 → `GuardError("guard/preview-mismatch")`)

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_trading_preview.py
from datetime import date
import re

import pytest

from kr_trading.preview import PreviewStore, canonical_hash, new_client_order_id
from kr_trading.toss.errors import GuardError


def test_client_order_id_format():
    cid = new_client_order_id(date(2026, 9, 14))
    assert re.fullmatch(r"20260914-[A-Za-z0-9]{8}", cid) and len(cid) <= 36
    assert new_client_order_id() != new_client_order_id()


def test_canonical_hash_is_order_independent():
    assert canonical_hash({"a": "1", "b": "2"}) == canonical_hash({"b": "2", "a": "1"})
    assert canonical_hash({"a": "1"}) != canonical_hash({"a": "2"})


def test_put_get_verify():
    now = [0.0]
    st = PreviewStore(ttl_sec=300, clock=lambda: now[0])
    payload = {"symbol": "005930", "price": "70000", "quantity": "10", "clientOrderId": "c1"}
    tok = st.put(payload, {"amount": "700000"})
    assert tok == canonical_hash(payload)
    assert st.verify(tok, payload) == {"amount": "700000"}
    with pytest.raises(GuardError) as ei:
        st.verify(tok, {**payload, "quantity": "100"})
    assert ei.value.code == "guard/preview-mismatch"
    now[0] = 301
    with pytest.raises(GuardError) as ei:
        st.verify(tok, payload)
    assert ei.value.code == "guard/preview-required"


def test_unknown_token_is_preview_required():
    with pytest.raises(GuardError) as ei:
        PreviewStore().verify("nope", {})
    assert ei.value.code == "guard/preview-required"
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_trading_preview.py -v` → ImportError

- [ ] **Step 3: 구현**

```python
# kr_trading/preview.py
"""미리보기 토큰 (spec §5 PreviewStore). 메모리·TTL 5분. clientOrderId 는 미리보기 시점에 생성.

서버 재시작 시 토큰 소멸 → 주문은 guard/preview-required 로 막힘(안전). 미리보기 재실행으로 복구.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import date
from typing import Callable

from kr_trading.audit import kst_today
from kr_trading.toss.errors import GuardError


def new_client_order_id(today: date | None = None) -> str:
    d = today or kst_today()
    return f"{d:%Y%m%d}-{uuid.uuid4().hex[:8]}"


def canonical_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PreviewStore:
    def __init__(self, ttl_sec: float = 300.0, clock: Callable[[], float] = time.monotonic):
        self._ttl = ttl_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._items: dict[str, tuple[float, dict, dict]] = {}   # token -> (expires_at, payload, meta)

    def put(self, payload: dict, meta: dict) -> str:
        tok = canonical_hash(payload)
        with self._lock:
            self._items[tok] = (self._clock() + self._ttl, payload, meta)
        return tok

    def get(self, token: str) -> tuple[dict, dict] | None:
        with self._lock:
            item = self._items.get(token)
            if item is None:
                return None
            exp, payload, meta = item
            if self._clock() > exp:
                del self._items[token]
                return None
            return payload, meta

    def verify(self, token: str, payload: dict) -> dict:
        item = self.get(token)
        if item is None:
            raise GuardError("guard/preview-required", "미리보기가 없거나 만료됨 — 미리보기를 다시 실행하세요")
        stored, meta = item
        if canonical_hash(payload) != token or stored != payload:
            raise GuardError("guard/preview-mismatch", "미리보기한 내용과 주문 내용이 다릅니다")
        return meta
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_trading_preview.py -v` → 4 passed

- [ ] **Step 5: 커밋**

```bash
git add kr_trading/preview.py tests/test_trading_preview.py
git commit -m "kr_trading.preview: PreviewStore — canonical 해시 토큰·TTL 5분·clientOrderId 생성"
```

---

### Task 9: trade_api 앱 골격 · `/health` · `/accounts` · 에러 핸들러

**Files:**
- Create: `trade_api/__init__.py`, `trade_api/main.py`, `trade_api/deps.py`, `trade_api/schemas.py`, `trade_api/routers/__init__.py`, `trade_api/routers/health.py`, `trade_api/routers/accounts.py`
- Test: `tests/test_trade_api_app.py`

**Interfaces:**
- Consumes: `TradeConfig`, `TossClient`, `PreviewStore`, `TossApiError`, `GuardError`
- Produces (DI, `trade_api/deps.py`):
  - `get_cfg() -> TradeConfig`, `get_toss() -> TossClient`, `get_preview() -> PreviewStore`, `get_conn() -> Generator[Connection]`(`api/deps.py` 동형)
  - `set_test_overrides(*, cfg=None, toss=None, preview=None)`·`reset_overrides()` — 테스트가 MockTransport 클라이언트를 주입
  - 예외 핸들러: `TossApiError` → 토스 상태코드 + `{"error": {"code","message","data","requestId"}}`; `GuardError` → 400 + `{"error": {"code","message","data","requestId": null}}`
- `trade_api/schemas.py`: `HealthOut(dryRun: bool, maxOrderKrw: Decimal, maxDailyKrw: Decimal, accountSeq: int | None)`, `AccountOut = Account`(재사용), `ErrorBody`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_trade_api_app.py
"""trade_api 골격 — health 응답 모델(Decimal→str), accounts(계좌 헤더 없이), 에러 핸들러 2종."""
from decimal import Decimal

import httpx
from fastapi.testclient import TestClient

from kr_trading.config import TradeConfig
from kr_trading.toss.client import TossClient
from trade_api import deps
from trade_api.main import app

CFG = TradeConfig(client_id="cid", client_secret="sec", account_seq=None, base_url="https://toss.test",
                  dry_run=True, max_order_krw=Decimal("5000000"), max_daily_krw=Decimal("10000000"))
TOKEN_OK = httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})


def toss_with(handler, cfg=CFG):
    def route(req):
        return TOKEN_OK if req.url.path == "/oauth2/token" else handler(req)
    return TossClient(cfg, http=httpx.Client(transport=httpx.MockTransport(route), base_url=cfg.base_url), sleep=lambda s: None)


def setup_function():
    deps.reset_overrides()


def test_health_uses_response_model_strings():
    deps.set_test_overrides(cfg=CFG, toss=toss_with(lambda r: httpx.Response(500)))
    r = TestClient(app).get("/trade-api/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"dryRun": True, "maxOrderKrw": "5000000", "maxDailyKrw": "10000000", "accountSeq": None}
    assert isinstance(body["maxOrderKrw"], str)     # bare dict 였다면 5000000(int/float)


def test_accounts_without_account_seq():
    seen = {}
    def h(req):
        seen.update(req.headers); seen["path"] = req.url.path
        return httpx.Response(200, json={"result": [{"accountNo": "123", "accountSeq": 7, "accountType": "BROKERAGE"}]})
    deps.set_test_overrides(cfg=CFG, toss=toss_with(h))
    r = TestClient(app).get("/trade-api/accounts")
    assert r.status_code == 200 and r.json() == [{"accountNo": "123", "accountSeq": 7, "accountType": "BROKERAGE"}]
    assert seen["path"] == "/api/v1/accounts" and "x-tossinvest-account" not in seen


def test_toss_error_passthrough_handler():
    def h(req):
        return httpx.Response(403, json={"error": {"code": "edge-blocked", "message": "ip", "requestId": "r1", "data": None}})
    deps.set_test_overrides(cfg=CFG, toss=toss_with(h))
    r = TestClient(app).get("/trade-api/accounts")
    assert r.status_code == 403
    assert r.json() == {"error": {"code": "edge-blocked", "message": "ip", "data": None, "requestId": "r1"}}


def test_guard_error_handler_400():
    deps.set_test_overrides(cfg=CFG, toss=toss_with(lambda r: httpx.Response(200, json={"result": {}})))
    r = TestClient(app).get("/trade-api/buying-power")   # account_seq None → guard/account-seq-missing
    assert r.status_code == 400 and r.json()["error"]["code"] == "guard/account-seq-missing"
```

> `/trade-api/buying-power`는 Task 10에서 생김 — 이 테스트 1건은 Task 10 완료 후 통과. Task 9 커밋 시점엔 `-k "not guard_error"`로 3건 통과 확인.

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_trade_api_app.py -v` → ImportError

- [ ] **Step 3: 구현**

```python
# trade_api/__init__.py  (빈 파일)
# trade_api/routers/__init__.py  (빈 파일)
```

```python
# trade_api/deps.py
"""trade_api 의존성 — TradeConfig·TossClient·PreviewStore 프로세스 싱글톤 + DB 풀(api/deps.py 동형).

토스 토큰은 클라이언트당 1개 → TossClient(=TokenManager) 는 이 프로세스에 정확히 1개.
테스트는 set_test_overrides 로 MockTransport 클라이언트를 주입(토스 접촉 0).
"""
from __future__ import annotations

from typing import Callable, Generator

from psycopg import Connection
from psycopg_pool import ConnectionPool

from kr_pipeline.common.config import Config
from kr_pipeline.db.connection import connect
from kr_trading.config import TradeConfig
from kr_trading.preview import PreviewStore
from kr_trading.toss.client import TossClient

_pool: ConnectionPool | None = None
_cfg: TradeConfig | None = None
_toss: TossClient | None = None
_preview: PreviewStore | None = None
_reset_hooks: list[Callable[[], None]] = []   # 상태를 가진 라우터가 등록 — deps 는 라우터를 import 하지 않는다(계층 방향 유지)


def register_reset_hook(fn: Callable[[], None]) -> None:
    _reset_hooks.append(fn)


def _run_reset_hooks() -> None:
    for fn in _reset_hooks:
        fn()


def init_singletons() -> None:
    global _pool, _cfg, _toss, _preview
    _cfg = _cfg or TradeConfig.load()
    _toss = _toss or TossClient(_cfg)
    _preview = _preview or PreviewStore()
    _pool = ConnectionPool(Config.load().database_url, min_size=1, max_size=5, open=True)


def close_singletons() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def set_test_overrides(*, cfg: TradeConfig | None = None, toss: TossClient | None = None,
                       preview: PreviewStore | None = None) -> None:
    global _cfg, _toss, _preview
    if cfg is not None: _cfg = cfg
    if toss is not None:
        _toss = toss
        _run_reset_hooks()          # 클라이언트 교체 시 라우터 캐시(예: accounts) 무효화 — 설계로 보장
    if preview is not None: _preview = preview


def reset_overrides() -> None:
    global _cfg, _toss, _preview
    _cfg = _toss = _preview = None
    _run_reset_hooks()


def get_cfg() -> TradeConfig:
    global _cfg
    if _cfg is None:
        _cfg = TradeConfig.load()
    return _cfg


def get_toss() -> TossClient:
    global _toss
    if _toss is None:
        _toss = TossClient(get_cfg())
    return _toss


def get_preview() -> PreviewStore:
    global _preview
    if _preview is None:
        _preview = PreviewStore()
    return _preview


def get_conn() -> Generator[Connection, None, None]:
    if _pool is not None:
        with _pool.connection() as conn:
            yield conn
        return
    with connect(Config.load().database_url) as conn:
        yield conn
```

```python
# trade_api/schemas.py
"""프론트용 응답 모델. 모든 라우트는 이 모듈(또는 kr_trading.toss.models)의 모델을 response_model 로 선언.
bare dict 반환 금지 — FastAPI 는 dict 의 Decimal 을 float 로 내보낸다(spec §5 실측)."""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


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
```

```python
# trade_api/routers/health.py
from fastapi import APIRouter, Depends

from kr_trading.config import TradeConfig
from trade_api.deps import get_cfg
from trade_api.schemas import HealthOut

router = APIRouter(prefix="/trade-api", tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(cfg: TradeConfig = Depends(get_cfg)) -> HealthOut:
    return HealthOut(dryRun=cfg.dry_run, maxOrderKrw=cfg.max_order_krw,
                     maxDailyKrw=cfg.max_daily_krw, accountSeq=cfg.account_seq)
```

```python
# trade_api/routers/accounts.py
"""GET /trade-api/accounts — 계좌 헤더 불필요. TOSS_ACCOUNT_SEQ 미설정 상태에서 accountSeq 확인용.
ACCOUNT 그룹 1/s → 5분 캐시."""
import time

from fastapi import APIRouter, Depends

from kr_trading.toss.client import TossClient
from kr_trading.toss.models import Account
from trade_api.deps import get_toss, register_reset_hook

router = APIRouter(prefix="/trade-api", tags=["accounts"])
_cache: tuple[float, list[Account]] | None = None
CACHE_TTL = 300.0


def reset_cache() -> None:
    global _cache
    _cache = None


register_reset_hook(reset_cache)   # deps 가 accounts 를 import 하는 대신 accounts 가 등록


@router.get("/accounts", response_model=list[Account])
def accounts(toss: TossClient = Depends(get_toss)) -> list[Account]:
    global _cache
    now = time.monotonic()
    if _cache and now - _cache[0] < CACHE_TTL:
        return _cache[1]
    out = toss.accounts()
    _cache = (now, out)
    return out
```

```python
# trade_api/main.py
"""토스증권 매매 API (:8001). 분석 API(api.main, :8000)와 별도 프로세스 — spec §4.

  uv run uvicorn trade_api.main:app --port 8001      # --workers 금지(토큰 1개), --reload 기본 미사용

토스 호출 코드는 이 프로세스에만 존재한다(CLAUDE.md 운영규칙 6).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from kr_trading.toss.errors import GuardError, TossApiError
from trade_api import deps
from trade_api.routers import accounts, health

log = logging.getLogger("trade_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    deps.init_singletons()
    cfg = deps.get_cfg()
    log.warning("trade_api 기동 — dry_run=%s max_order_krw=%s max_daily_krw=%s account_seq=%s",
                cfg.dry_run, cfg.max_order_krw, cfg.max_daily_krw, cfg.account_seq)
    try:
        yield
    finally:
        deps.close_singletons()


app = FastAPI(title="kr-by-claude trade API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_credentials=False,
                   allow_methods=["GET", "POST"], allow_headers=["*"])


@app.exception_handler(TossApiError)
async def _toss_error(_: Request, e: TossApiError) -> JSONResponse:
    return JSONResponse(status_code=e.status, content={"error": {
        "code": e.code, "message": e.message, "data": e.data, "requestId": e.request_id}})


@app.exception_handler(GuardError)
async def _guard_error(_: Request, e: GuardError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": {
        "code": e.code, "message": e.message, "data": e.data, "requestId": None}})


app.include_router(health.router)
app.include_router(accounts.router)
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_trade_api_app.py -v -k "not guard_error"` → 3 passed

- [ ] **Step 5: 커밋**

```bash
git add trade_api/__init__.py trade_api/main.py trade_api/deps.py trade_api/schemas.py trade_api/routers/__init__.py trade_api/routers/health.py trade_api/routers/accounts.py tests/test_trade_api_app.py
git commit -m "trade_api: 앱 골격(:8001) — 싱글톤 DI·health·accounts·TossApiError/GuardError 핸들러·기동 로그"
```

---

### Task 10: `/holdings`(+mismatch) · `/search` · `/quote` · `/buying-power` · `/sellable`

**Files:**
- Create: `trade_api/routers/holdings.py`, `trade_api/routers/market.py`
- Modify: `trade_api/schemas.py`(모델 추가), `trade_api/main.py`(라우터 등록)
- Test: `tests/test_trade_api_read.py`(kr_test DB — `positions`·`stocks` 픽스처 삽입)

**Interfaces:**
- Produces(schemas):
  - `MismatchOut(symbol: str, name: str, tossQty: Decimal, positionQty: Decimal | None, kind: str  # "missing"|"qty_diff")`
  - `HoldingsOut(overview: HoldingsOverview, mismatch: list[MismatchOut])`
  - `SearchHit(ticker: str, name: str, market: str)`
  - `QuoteOut(symbol: str, name: str | None, price: PriceResponse, orderbook: OrderbookResponse, limits: PriceLimitResponse, warnings: list[StockWarning])`
- 라우트: `GET /trade-api/holdings → HoldingsOut`, `GET /trade-api/search?q= → list[SearchHit]`, `GET /trade-api/quote/{symbol} → QuoteOut`, `GET /trade-api/buying-power → BuyingPowerResponse`, `GET /trade-api/sellable/{symbol} → SellableQuantityResponse`
- mismatch 규칙(spec §6): 토스 종목이 `positions(status='open')`에 없음 → `missing`; 있고 `quantity IS NOT NULL`이고 다름 → `qty_diff`; `quantity NULL` → 판정 생략

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_trade_api_read.py
"""읽기 라우트 — holdings mismatch 3규칙, search 상폐 필터, quote 묶음."""
from decimal import Decimal

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from kr_trading.config import TradeConfig
from kr_trading.toss.client import TossClient
from trade_api import deps
from trade_api.main import app

CFG = TradeConfig(client_id="c", client_secret="s", account_seq=7, base_url="https://toss.test",
                  dry_run=True, max_order_krw=Decimal("5000000"), max_daily_krw=Decimal("10000000"))
TOKEN_OK = httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
M = lambda krw: {"krw": krw, "usd": None}


def item(sym, name, qty):
    return {"symbol": sym, "name": name, "marketCountry": "KR", "currency": "KRW", "quantity": qty,
            "lastPrice": "1000", "averagePurchasePrice": "900", "marketValue": M("1"), "profitLoss": M("1"),
            "dailyProfitLoss": M("0"), "cost": M("1")}


def toss_with(routes: dict):
    def route(req):
        if req.url.path == "/oauth2/token": return TOKEN_OK
        fn = routes.get(req.url.path)
        return fn(req) if fn else httpx.Response(404, json={"error": {"code": "not-found", "message": ""}})
    return TossClient(CFG, http=httpx.Client(transport=httpx.MockTransport(route), base_url=CFG.base_url), sleep=lambda s: None)


@pytest.fixture
def db(test_db_url):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        c.execute("DELETE FROM positions")
        c.execute("INSERT INTO stocks (ticker, name, market) VALUES ('005930','삼성전자','KOSPI'),('000660','SK하이닉스','KOSPI'),('035420','NAVER','KOSPI') ON CONFLICT (ticker) DO UPDATE SET name=EXCLUDED.name, delisted_at=NULL, is_common=TRUE")
        # 검색 테스트 전용 시드 — 고유 마커(TRDT%). 다른 모듈이 '삼성전자' 이름으로 테스트 티커(RVSP·OLD·ADJ1…)를
        # 남기므로 실명(삼성/0059)으로 정확 일치 단언하면 전체 suite 에서 순서 의존 실패(리포 관례 TRGTEST%/EXCTEST%).
        c.execute("DELETE FROM stocks WHERE ticker LIKE 'TRDT%'")
        c.execute("INSERT INTO stocks (ticker, name, market) VALUES ('TRDT01','트레이드검색A','KOSPI'),('TRDT02','트레이드검색B상폐','KOSDAQ')")
        c.execute("UPDATE stocks SET delisted_at='2025-01-01' WHERE ticker='TRDT02'")
        c.execute("INSERT INTO positions (symbol, entry_date, entry_price, quantity) VALUES ('005930','2026-09-01',70000,10)")
        c.execute("INSERT INTO positions (symbol, entry_date, entry_price, quantity) VALUES ('000660','2026-09-01',200000,NULL)")
        # 앱의 get_conn 을 이 kr_test 연결로 — 미오버라이드 시 Config.load().database_url(운영) 로 감
        # (리포 관례 tests/test_api_triggers.py:17). autocommit 연결이라 라우터의 conn.commit() 은 no-op.
        def _override():
            yield c
        app.dependency_overrides[deps.get_conn] = _override
        yield c
        app.dependency_overrides.pop(deps.get_conn, None)
        c.execute("DELETE FROM positions WHERE symbol IN ('005930','000660')")
        c.execute("DELETE FROM stocks WHERE ticker LIKE 'TRDT%'")


def setup_function():
    deps.reset_overrides()


def test_holdings_mismatch_rules(db):
    holdings = {"totalPurchaseAmount": M("1"), "marketValue": M("1"), "profitLoss": M("0"), "dailyProfitLoss": M("0"),
                "items": [item("005930", "삼성전자", "12"),      # positions qty 10 → qty_diff
                          item("000660", "SK하이닉스", "3"),     # positions qty NULL → 판정 생략
                          item("035420", "NAVER", "1")]}       # positions 없음 → missing
    deps.set_test_overrides(cfg=CFG, toss=toss_with({"/api/v1/holdings": lambda r: httpx.Response(200, json={"result": holdings})}))
    r = TestClient(app).get("/trade-api/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body["overview"]["items"][0]["quantity"] == "12"
    assert sorted((m["symbol"], m["kind"]) for m in body["mismatch"]) == [("005930", "qty_diff"), ("035420", "missing")]
    assert next(m for m in body["mismatch"] if m["symbol"] == "005930")["positionQty"] == "10"


def test_search_excludes_delisted(db):
    deps.set_test_overrides(cfg=CFG, toss=toss_with({}))
    c = TestClient(app)
    assert [h["ticker"] for h in c.get("/trade-api/search?q=트레이드검색").json()] == ["TRDT01"]   # 상폐 TRDT02 제외
    assert c.get("/trade-api/search?q=B상폐").json() == []
    assert c.get("/trade-api/search?q=TRDT01").json()[0]["ticker"] == "TRDT01"                      # 정확 티커 우선
    assert c.get("/trade-api/search?q=TRDT0").json()[0]["name"] == "트레이드검색A"


def test_quote_bundle(db):
    routes = {
        "/api/v1/prices": lambda r: httpx.Response(200, json={"result": [{"symbol": "005930", "timestamp": None, "lastPrice": "70000", "currency": "KRW"}]}),
        "/api/v1/orderbook": lambda r: httpx.Response(200, json={"result": {"timestamp": None, "currency": "KRW", "asks": [{"price": "70100", "volume": "5"}], "bids": [{"price": "70000", "volume": "7"}]}}),
        "/api/v1/price-limits": lambda r: httpx.Response(200, json={"result": {"timestamp": "t", "currency": "KRW", "upperLimitPrice": "91000", "lowerLimitPrice": "49000"}}),
        "/api/v1/stocks/005930/warnings": lambda r: httpx.Response(200, json={"result": [{"warningType": "OVERHEATED", "exchange": "KRX", "startDate": None, "endDate": None}]}),
    }
    deps.set_test_overrides(cfg=CFG, toss=toss_with(routes))
    body = TestClient(app).get("/trade-api/quote/005930").json()
    assert body["name"] == "삼성전자" and body["price"]["lastPrice"] == "70000"
    assert body["limits"]["upperLimitPrice"] == "91000" and body["warnings"][0]["warningType"] == "OVERHEATED"
    assert body["orderbook"]["asks"][0]["price"] == "70100"


def test_buying_power_and_sellable():
    routes = {
        "/api/v1/buying-power": lambda r: httpx.Response(200, json={"result": {"currency": "KRW", "cashBuyingPower": "1234567"}}),
        "/api/v1/sellable-quantity": lambda r: httpx.Response(200, json={"result": {"sellableQuantity": "8"}}),
    }
    deps.set_test_overrides(cfg=CFG, toss=toss_with(routes))
    c = TestClient(app)
    assert c.get("/trade-api/buying-power").json() == {"currency": "KRW", "cashBuyingPower": "1234567"}
    assert c.get("/trade-api/sellable/005930").json() == {"sellableQuantity": "8"}
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_trade_api_read.py -v` → 404 실패

- [ ] **Step 3: 구현**

`trade_api/schemas.py`에 추가:

```python
from kr_trading.toss.models import (
    HoldingsOverview, OrderbookResponse, PriceLimitResponse, PriceResponse, StockWarning,
)


class MismatchOut(BaseModel):
    symbol: str
    name: str
    tossQty: Decimal
    positionQty: Decimal | None
    kind: str          # missing | qty_diff


class HoldingsOut(BaseModel):
    overview: HoldingsOverview
    mismatch: list[MismatchOut]


class SearchHit(BaseModel):
    ticker: str
    name: str
    market: str


class QuoteOut(BaseModel):
    symbol: str
    name: str | None
    price: PriceResponse
    orderbook: OrderbookResponse
    limits: PriceLimitResponse
    warnings: list[StockWarning]
```

```python
# trade_api/routers/holdings.py
"""GET /trade-api/holdings — 토스 잔고 + positions(open) 읽기전용 대조 (spec D2·§6).
positions 는 SELECT 만. quantity NULL(전량 모델)은 존재만 확인."""
from decimal import Decimal

from fastapi import APIRouter, Depends
from psycopg import Connection

from kr_trading.toss.client import TossClient
from trade_api.deps import get_conn, get_toss
from trade_api.schemas import HoldingsOut, MismatchOut

router = APIRouter(prefix="/trade-api", tags=["holdings"])


@router.get("/holdings", response_model=HoldingsOut)
def holdings(toss: TossClient = Depends(get_toss), conn: Connection = Depends(get_conn)) -> HoldingsOut:
    overview = toss.holdings()
    rows = conn.execute("SELECT symbol, quantity FROM positions WHERE status = 'open'").fetchall()
    pos: dict[str, Decimal | None] = {r[0]: (Decimal(r[1]) if r[1] is not None else None) for r in rows}
    mismatch: list[MismatchOut] = []
    for it in overview.items:
        if it.marketCountry != "KR":
            continue
        if it.symbol not in pos:
            mismatch.append(MismatchOut(symbol=it.symbol, name=it.name, tossQty=it.quantity, positionQty=None, kind="missing"))
        elif pos[it.symbol] is not None and pos[it.symbol] != it.quantity:
            mismatch.append(MismatchOut(symbol=it.symbol, name=it.name, tossQty=it.quantity, positionQty=pos[it.symbol], kind="qty_diff"))
    return HoldingsOut(overview=overview, mismatch=mismatch)
```

```python
# trade_api/routers/market.py
"""검색(로컬 stocks)·시세 묶음·매수가능금액·판매가능수량."""
from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from kr_trading.toss.client import TossClient
from kr_trading.toss.models import BuyingPowerResponse, SellableQuantityResponse
from trade_api.deps import get_conn, get_toss
from trade_api.schemas import QuoteOut, SearchHit

router = APIRouter(prefix="/trade-api", tags=["market"])


@router.get("/search", response_model=list[SearchHit])
def search(q: str = Query(..., min_length=1, max_length=30), conn: Connection = Depends(get_conn)) -> list[SearchHit]:
    like = f"%{q}%"
    rows = conn.execute(
        """
        SELECT ticker, name, market FROM stocks
         WHERE delisted_at IS NULL AND is_common
           AND (ticker ILIKE %s OR name ILIKE %s)
         ORDER BY (ticker = %s) DESC, (name ILIKE %s) DESC, name
         LIMIT 20
        """,
        (like, like, q, f"{q}%"),
    ).fetchall()
    return [SearchHit(ticker=r[0], name=r[1], market=r[2]) for r in rows]


@router.get("/quote/{symbol}", response_model=QuoteOut)
def quote(symbol: str, toss: TossClient = Depends(get_toss), conn: Connection = Depends(get_conn)) -> QuoteOut:
    row = conn.execute("SELECT name FROM stocks WHERE ticker = %s", (symbol,)).fetchone()
    prices = toss.prices([symbol])
    return QuoteOut(symbol=symbol, name=row[0] if row else None, price=prices[0],
                    orderbook=toss.orderbook(symbol), limits=toss.price_limits(symbol),
                    warnings=toss.warnings(symbol))


@router.get("/buying-power", response_model=BuyingPowerResponse)
def buying_power(toss: TossClient = Depends(get_toss)) -> BuyingPowerResponse:
    return toss.buying_power()


@router.get("/sellable/{symbol}", response_model=SellableQuantityResponse)
def sellable(symbol: str, toss: TossClient = Depends(get_toss)) -> SellableQuantityResponse:
    return toss.sellable_quantity(symbol)
```

`trade_api/main.py`: `from trade_api.routers import accounts, health, holdings, market` + `app.include_router(holdings.router)`, `app.include_router(market.router)`.

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_trade_api_read.py tests/test_trade_api_app.py -v` → 8 passed (Task 9의 guard_error 포함)

- [ ] **Step 5: 커밋**

```bash
git add trade_api/routers/holdings.py trade_api/routers/market.py trade_api/schemas.py trade_api/main.py tests/test_trade_api_read.py
git commit -m "trade_api: holdings(+positions 대조 3규칙)·search(상폐 제외)·quote 묶음·buying-power·sellable"
```

---

### Task 11: 주문 라우트 — preview · create(DRY_RUN/실주문) · cancel · modify · list · detail

**Files:**
- Create: `trade_api/routers/orders.py`
- Modify: `trade_api/schemas.py`(모델 추가), `trade_api/main.py`(라우터 등록)
- Test: `tests/test_trade_api_orders.py`(kr_test DB — 감사로그 검증)

**Interfaces:**
- Consumes: `check_order`, `GuardResult`(Task 7), `PreviewStore`·`new_client_order_id`(Task 8), `AuditLog`(Task 6), `TossClient`(Task 5)
- Produces(schemas):
  - `PreviewIn(symbol: str, side: str, orderType: str, quantity: Decimal, price: Decimal | None = None, confirmHighValueOrder: bool = False)`
  - `EstimateOut(amount: Decimal, amountBasis: str, commission: Decimal | None, total: Decimal)`
  - `PreviewOut(previewToken: str, clientOrderId: str | None, request: dict, estimate: EstimateOut, warnings: list[str], dryRun: bool, expiresInSec: int)`
  - `OrderSubmitIn(previewToken: str, request: OrderCreateRequest)`
  - `OrderSubmitOut(dryRun: bool, orderId: str | None, clientOrderId: str | None, auditId: int, request: dict)`
  - `ModifyPreviewIn(orderId: str, orderType: str, quantity: Decimal, price: Decimal | None = None, confirmHighValueOrder: bool = False)`
  - `ModifySubmitIn(previewToken: str, orderId: str, request: OrderModifyRequest)`
  - `OperationOut(dryRun: bool, orderId: str | None, auditId: int)`
- 라우트(전부 `response_model`):
  - `POST /trade-api/orders/preview → PreviewOut` — 가드 전부, `clientOrderId` 생성, 토스 주문 API 미호출
  - `POST /trade-api/orders → OrderSubmitOut` — `previewToken` 검증 → 감사 `begin` → (DRY_RUN이면 `finish(http_status=0)` 후 반환) → `toss.create_order` → `finish(200, order_id)`; `TossApiError`면 `finish(e.status, error_code, request_id)` 후 re-raise
  - `POST /trade-api/orders/modify/preview → PreviewOut`(원주문 조회 → 합성 요청으로 가드, `count_toward_daily=False`)
  - `POST /trade-api/orders/{order_id}/modify → OperationOut`, `POST /trade-api/orders/{order_id}/cancel → OperationOut`(둘 다 감사 기록, DRY_RUN 존중)
  - `GET /trade-api/orders?status=OPEN|CLOSED&cursor=&limit= → PaginatedOrderResponse`, `GET /trade-api/orders/{order_id} → Order`
- 감사 `http_status`: 토스 응답 상태 그대로; **DRY_RUN은 `0`**(전송 없음 표식). 1일 누적은 `http_status=200`만 집계하므로 영향 없음.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_trade_api_orders.py
"""주문 라우트 — 미리보기 토큰 강제, DRY_RUN 무전송, 실주문 감사 INSERT→UPDATE, 토스 에러 시 감사 기록, 정정·취소."""
import json
from decimal import Decimal

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from kr_trading.config import TradeConfig
from kr_trading.preview import PreviewStore
from kr_trading.toss.client import TossClient
from trade_api import deps
from trade_api.main import app

BASE = dict(client_id="c", client_secret="s", account_seq=7, base_url="https://toss.test",
            max_order_krw=Decimal("5000000"), max_daily_krw=Decimal("10000000"))
DRY = TradeConfig(dry_run=True, **BASE)
LIVE = TradeConfig(dry_run=False, **BASE)
TOKEN_OK = httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600})
LIMITS = lambda r: httpx.Response(200, json={"result": {"timestamp": "t", "currency": "KRW", "upperLimitPrice": "91000", "lowerLimitPrice": "49000"}})
COMM = lambda r: httpx.Response(200, json={"result": [{"marketCountry": "KR", "commissionRate": "0.00015", "startDate": None, "endDate": None}]})
SELLABLE = lambda r: httpx.Response(200, json={"result": {"sellableQuantity": "5"}})


def toss_with(routes: dict, cfg, calls: list | None = None):
    def route(req):
        if calls is not None: calls.append((req.method, req.url.path))
        if req.url.path == "/oauth2/token": return TOKEN_OK
        fn = routes.get((req.method, req.url.path))
        return fn(req) if fn else httpx.Response(404, json={"error": {"code": "not-found", "message": ""}})
    return TossClient(cfg, http=httpx.Client(transport=httpx.MockTransport(route), base_url=cfg.base_url), sleep=lambda s: None)


@pytest.fixture
def db(test_db_url):
    with psycopg.connect(test_db_url, autocommit=True) as c:
        c.execute("DELETE FROM toss_order_audit")
        # 앱의 get_conn 을 이 kr_test 연결로 — 미오버라이드 시 운영 DB 로 감(관례 tests/test_api_triggers.py:17).
        # autocommit 연결: 라우터의 conn.commit() 은 no-op, 모든 문장이 즉시 durable → pending 행 관측에 적합.
        def _override():
            yield c
        app.dependency_overrides[deps.get_conn] = _override
        yield c
        app.dependency_overrides.pop(deps.get_conn, None)


def setup_function():
    deps.reset_overrides()


READ_ROUTES = {("GET", "/api/v1/price-limits"): LIMITS, ("GET", "/api/v1/commissions"): COMM,
               ("GET", "/api/v1/sellable-quantity"): SELLABLE}
BUY = {"symbol": "005930", "side": "BUY", "orderType": "LIMIT", "quantity": "10", "price": "70000"}


def preview(client, body=BUY):
    r = client.post("/trade-api/orders/preview", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_preview_returns_token_and_client_order_id_without_calling_order_api(db):
    calls = []
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY, calls), preview=PreviewStore())
    p = preview(TestClient(app))
    assert p["clientOrderId"].startswith("2") and len(p["previewToken"]) == 64
    assert p["request"]["price"] == "70000" and p["request"]["clientOrderId"] == p["clientOrderId"]
    assert p["estimate"] == {"amount": "700000", "amountBasis": "limit", "commission": "105.00000", "total": "700105.00000"}
    assert p["dryRun"] is True
    assert ("POST", "/api/v1/orders") not in calls


def test_preview_guard_rejection_is_400_with_guard_code(db):
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY), preview=PreviewStore())
    r = TestClient(app).post("/trade-api/orders/preview", json={**BUY, "price": "70050"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "guard/tick-size"


def test_submit_without_preview_is_rejected(db):
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY), preview=PreviewStore())
    r = TestClient(app).post("/trade-api/orders", json={"previewToken": "x" * 64, "request": BUY})
    assert r.status_code == 400 and r.json()["error"]["code"] == "guard/preview-required"


def test_submit_mismatched_body_is_rejected(db):
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY), preview=PreviewStore())
    c = TestClient(app)
    p = preview(c)
    tampered = {**p["request"], "quantity": "100"}
    r = c.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": tampered})
    assert r.status_code == 400 and r.json()["error"]["code"] == "guard/preview-mismatch"


def test_dry_run_submit_records_audit_and_does_not_call_toss(db):
    calls = []
    deps.set_test_overrides(cfg=DRY, toss=toss_with(READ_ROUTES, DRY, calls), preview=PreviewStore())
    c = TestClient(app)
    p = preview(c)
    r = c.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": p["request"]})
    assert r.status_code == 200
    body = r.json()
    assert body["dryRun"] is True and body["orderId"] is None and body["clientOrderId"] == p["clientOrderId"]
    assert ("POST", "/api/v1/orders") not in calls
    row = db.execute("SELECT kind, dry_run, http_status, order_amount_krw, side FROM toss_order_audit WHERE id=%s", (body["auditId"],)).fetchone()
    assert row == ("create", True, 0, Decimal("700000.00"), "BUY")


def test_live_submit_audit_insert_then_update(db):
    seen = {}
    def create(req):
        seen["body"] = json.loads(req.content)
        pending = db.execute("SELECT http_status FROM toss_order_audit WHERE client_order_id=%s", (seen["body"]["clientOrderId"],)).fetchone()
        seen["pending_at_send"] = pending
        return httpx.Response(200, headers={"X-Request-Id": "req-7"}, json={"result": {"orderId": "ord_9", "clientOrderId": seen["body"]["clientOrderId"]}})
    deps.set_test_overrides(cfg=LIVE, toss=toss_with({**READ_ROUTES, ("POST", "/api/v1/orders"): create}, LIVE), preview=PreviewStore())
    c = TestClient(app)
    p = preview(c)
    r = c.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": p["request"]})
    assert r.status_code == 200 and r.json()["orderId"] == "ord_9" and r.json()["dryRun"] is False
    assert seen["pending_at_send"] == (None,)            # 전송 시점에 pending 행이 이미 존재
    assert seen["body"]["price"] == "70000" and seen["body"]["clientOrderId"] == p["clientOrderId"]
    row = db.execute("SELECT http_status, order_id, dry_run FROM toss_order_audit WHERE id=%s", (r.json()["auditId"],)).fetchone()
    assert row == (200, "ord_9", False)


def test_live_submit_toss_error_is_recorded_and_passed_through(db):
    def create(req):
        return httpx.Response(422, json={"error": {"code": "insufficient-buying-power", "message": "잔고", "requestId": "r-1", "data": {"needKrw": "1"}}})
    deps.set_test_overrides(cfg=LIVE, toss=toss_with({**READ_ROUTES, ("POST", "/api/v1/orders"): create}, LIVE), preview=PreviewStore())
    c = TestClient(app)
    p = preview(c)
    r = c.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": p["request"]})
    assert r.status_code == 422 and r.json()["error"] == {"code": "insufficient-buying-power", "message": "잔고", "data": {"needKrw": "1"}, "requestId": "r-1"}
    row = db.execute("SELECT http_status, error_code, request_id FROM toss_order_audit WHERE client_order_id=%s", (p["clientOrderId"],)).fetchone()
    assert row == (422, "insufficient-buying-power", "r-1")


def test_pending_row_is_durable_to_other_sessions_before_send(test_db_url):
    """commit-before-send 계약 pin — 비-autocommit 오버라이드(운영 풀 연결과 동형) + **제2 세션**에서
    전송 시점의 pending 행을 관측한다. 라우터의 begin 직후 conn.commit() 이 빠지면 제2 세션은 행을 못 본다.
    (기존 test_live_submit_* 는 autocommit 동일 연결이라 commit 유무를 구분하지 못함 — 리뷰 I-1)"""
    seen = {}
    c1 = psycopg.connect(test_db_url)                    # 비-autocommit
    c1.execute("DELETE FROM toss_order_audit"); c1.commit()

    def _override():
        yield c1
        c1.commit()                                      # 풀 컨텍스트의 정상 종료 commit 과 동형

    app.dependency_overrides[deps.get_conn] = _override
    try:
        def create(req):
            body = json.loads(req.content)
            with psycopg.connect(test_db_url, autocommit=True) as c2:   # 독립 세션
                seen["other_session"] = c2.execute(
                    "SELECT http_status FROM toss_order_audit WHERE client_order_id=%s",
                    (body["clientOrderId"],)).fetchone()
            return httpx.Response(200, json={"result": {"orderId": "ord_d", "clientOrderId": body["clientOrderId"]}})
        deps.set_test_overrides(cfg=LIVE, toss=toss_with({**READ_ROUTES, ("POST", "/api/v1/orders"): create}, LIVE), preview=PreviewStore())
        c = TestClient(app)
        p = preview(c)
        r = c.post("/trade-api/orders", json={"previewToken": p["previewToken"], "request": p["request"]})
        assert r.status_code == 200, r.text
        assert seen["other_session"] == (None,)          # 전송 시점에 타 세션이 pending 행을 봄 = commit 됨
        with psycopg.connect(test_db_url, autocommit=True) as c3:
            assert c3.execute("SELECT http_status, order_id FROM toss_order_audit WHERE id=%s",
                              (r.json()["auditId"],)).fetchone() == (200, "ord_d")
    finally:
        app.dependency_overrides.pop(deps.get_conn, None)
        c1.close()


def test_daily_cap_uses_audit(db):
    db.execute("INSERT INTO toss_order_audit (kind, symbol, side, order_amount_krw, request_json, dry_run, http_status) VALUES ('create','005930','BUY',9500000,'{}',false,200)")
    deps.set_test_overrides(cfg=LIVE, toss=toss_with(READ_ROUTES, LIVE), preview=PreviewStore())
    r = TestClient(app).post("/trade-api/orders/preview", json=BUY)     # 950만 + 70만 > 1000만
    assert r.status_code == 400 and r.json()["error"]["code"] == "guard/max-daily-amount"


def test_cancel_and_modify_with_audit(db):
    order = {"orderId": "ord_1", "symbol": "005930", "side": "BUY", "orderType": "LIMIT", "timeInForce": "DAY",
             "status": "PENDING", "price": "70000", "quantity": "10", "orderAmount": None, "currency": "KRW",
             "orderedAt": "2026-09-14T09:00:00+09:00", "canceledAt": None,
             "execution": {"filledQuantity": "0", "averageFilledPrice": None, "filledAmount": None, "commission": None, "tax": None, "filledAt": None, "settlementDate": None}}
    routes = {**READ_ROUTES,
              ("GET", "/api/v1/orders/ord_1"): lambda r: httpx.Response(200, json={"result": order}),
              ("POST", "/api/v1/orders/ord_1/cancel"): lambda r: httpx.Response(200, json={"result": {"orderId": "ord_2"}}),
              ("POST", "/api/v1/orders/ord_1/modify"): lambda r: httpx.Response(200, json={"result": {"orderId": "ord_3"}}),
              ("GET", "/api/v1/orders"): lambda r: httpx.Response(200, json={"result": {"orders": [order], "nextCursor": None, "hasNext": False}})}
    deps.set_test_overrides(cfg=LIVE, toss=toss_with(routes, LIVE), preview=PreviewStore())
    c = TestClient(app)
    # 취소
    r = c.post("/trade-api/orders/ord_1/cancel")
    assert r.status_code == 200 and r.json()["orderId"] == "ord_2"
    assert db.execute("SELECT kind, http_status, order_id FROM toss_order_audit WHERE id=%s", (r.json()["auditId"],)).fetchone() == ("cancel", 200, "ord_2")
    # 정정 미리보기 → 제출 (1일 누적은 재검 안 함)
    db.execute("INSERT INTO toss_order_audit (kind, symbol, side, order_amount_krw, request_json, dry_run, http_status) VALUES ('create','005930','BUY',9900000,'{}',false,200)")
    p = c.post("/trade-api/orders/modify/preview", json={"orderId": "ord_1", "orderType": "LIMIT", "quantity": "15", "price": "71000"})
    assert p.status_code == 200, p.text
    assert p.json()["estimate"]["amount"] == "1065000" and p.json()["clientOrderId"] is None
    r = c.post("/trade-api/orders/ord_1/modify", json={"previewToken": p.json()["previewToken"], "orderId": "ord_1", "request": {"orderType": "LIMIT", "quantity": "15", "price": "71000"}})
    assert r.status_code == 200 and r.json()["orderId"] == "ord_3"
    assert db.execute("SELECT kind, http_status FROM toss_order_audit WHERE id=%s", (r.json()["auditId"],)).fetchone() == ("modify", 200)
    # 목록·상세 그대로 전달
    assert c.get("/trade-api/orders?status=OPEN").json()["orders"][0]["price"] == "70000"
    assert c.get("/trade-api/orders/ord_1").json()["execution"]["filledQuantity"] == "0"
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_trade_api_orders.py -v` → 404 실패

- [ ] **Step 3: 구현**

`trade_api/schemas.py`에 추가:

```python
from kr_trading.toss.models import OrderCreateRequest, OrderModifyRequest


class PreviewIn(BaseModel):
    symbol: str
    side: str
    orderType: str
    quantity: Decimal
    price: Decimal | None = None
    confirmHighValueOrder: bool = False


class EstimateOut(BaseModel):
    amount: Decimal
    amountBasis: str
    commission: Decimal | None
    total: Decimal


class PreviewOut(BaseModel):
    previewToken: str
    clientOrderId: str | None
    request: dict
    estimate: EstimateOut
    warnings: list[str]
    dryRun: bool
    expiresInSec: int


class OrderSubmitIn(BaseModel):
    previewToken: str
    request: OrderCreateRequest


class OrderSubmitOut(BaseModel):
    dryRun: bool
    orderId: str | None
    clientOrderId: str | None
    auditId: int
    request: dict


class ModifyPreviewIn(BaseModel):
    orderId: str
    orderType: str
    quantity: Decimal
    price: Decimal | None = None
    confirmHighValueOrder: bool = False


class ModifySubmitIn(BaseModel):
    previewToken: str
    orderId: str
    request: OrderModifyRequest


class OperationOut(BaseModel):
    dryRun: bool
    orderId: str | None
    auditId: int
```

```python
# trade_api/routers/orders.py
"""주문 라우트 (spec §6). 실주문 코드는 _submit_live 안에만 있고 DRY_RUN 가드 뒤에 위치.

흐름: preview(가드 전부·clientOrderId 생성·토큰) → submit(토큰 검증 → 감사 begin → [DRY_RUN 종료]
→ 토스 호출 → 감사 finish). 토스 에러도 감사 finish 후 그대로 재던짐(핸들러가 envelope 전달).
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from kr_trading.audit import AuditLog, kst_today
from kr_trading.config import TradeConfig
from kr_trading.guard import GuardResult, check_order
from kr_trading.preview import PreviewStore, new_client_order_id
from kr_trading.toss.client import TossClient
from kr_trading.toss.errors import TossApiError
from kr_trading.toss.models import Order, OrderCreateRequest, PaginatedOrderResponse
from trade_api.deps import get_cfg, get_conn, get_preview, get_toss
from trade_api.schemas import (
    EstimateOut, ModifyPreviewIn, ModifySubmitIn, OperationOut, OrderSubmitIn, OrderSubmitOut,
    PreviewIn, PreviewOut,
)

router = APIRouter(prefix="/trade-api/orders", tags=["orders"])
DRY_RUN_STATUS = 0          # 감사 http_status: 전송 없음 표식(1일 누적은 200 만 집계)
PREVIEW_TTL_SEC = 300


def _kr_commission_rate(toss: TossClient) -> Decimal | None:
    try:
        for c in toss.commissions():
            if c.marketCountry == "KR":
                return c.commissionRate
    except TossApiError:
        return None
    return None


def _estimate(side: str, g: GuardResult, rate: Decimal | None) -> EstimateOut:
    commission = (g.amount_krw * rate) if rate is not None else None
    fee = commission or Decimal("0")
    total = g.amount_krw + fee if side == "BUY" else g.amount_krw - fee
    return EstimateOut(amount=g.amount_krw, amountBasis=g.amount_basis, commission=commission, total=total)


def _guard(req: OrderCreateRequest, *, cfg: TradeConfig, toss: TossClient, log: AuditLog,
           count_toward_daily: bool) -> GuardResult:
    limits = toss.price_limits(req.symbol)
    sellable = toss.sellable_quantity(req.symbol).sellableQuantity if req.side == "SELL" else None
    daily = log.daily_buy_total_krw(kst_today()) if (req.side == "BUY" and count_toward_daily) else Decimal("0")
    return check_order(req, cfg=cfg, upper_limit=limits.upperLimitPrice, lower_limit=limits.lowerLimitPrice,
                       daily_buy_total=daily, sellable_qty=sellable, count_toward_daily=count_toward_daily)


@router.post("/preview", response_model=PreviewOut)
def preview(body: PreviewIn, cfg: TradeConfig = Depends(get_cfg), toss: TossClient = Depends(get_toss),
            store: PreviewStore = Depends(get_preview), conn: Connection = Depends(get_conn)) -> PreviewOut:
    req = OrderCreateRequest(**body.model_dump(), clientOrderId=new_client_order_id())
    g = _guard(req, cfg=cfg, toss=toss, log=AuditLog(conn), count_toward_daily=True)
    est = _estimate(req.side, g, _kr_commission_rate(toss))
    payload = req.to_toss_json()
    token = store.put(payload, {"amount": str(g.amount_krw), "basis": g.amount_basis})
    return PreviewOut(previewToken=token, clientOrderId=req.clientOrderId, request=payload, estimate=est,
                      warnings=g.warnings, dryRun=cfg.dry_run, expiresInSec=PREVIEW_TTL_SEC)


@router.post("", response_model=OrderSubmitOut)
def submit(body: OrderSubmitIn, cfg: TradeConfig = Depends(get_cfg), toss: TossClient = Depends(get_toss),
           store: PreviewStore = Depends(get_preview), conn: Connection = Depends(get_conn)) -> OrderSubmitOut:
    payload = body.request.to_toss_json()
    meta = store.verify(body.previewToken, payload)
    log = AuditLog(conn)
    audit_id = log.begin("create", body.request.symbol, body.request.side, body.request.clientOrderId,
                         Decimal(meta["amount"]), payload, dry_run=cfg.dry_run)
    conn.commit()                                     # pending 행을 전송 전에 확정
    if cfg.dry_run:
        log.finish(audit_id, http_status=DRY_RUN_STATUS)
        return OrderSubmitOut(dryRun=True, orderId=None, clientOrderId=body.request.clientOrderId,
                              auditId=audit_id, request=payload)
    # ── 실주문 경로 (DRY_RUN 가드 뒤) ────────────────────────────────
    try:
        res = toss.create_order(body.request)
    except TossApiError as e:
        log.finish(audit_id, http_status=e.status, error_code=e.code, request_id=e.request_id)
        conn.commit()
        raise
    log.finish(audit_id, http_status=200, order_id=res.orderId, response_json=res.model_dump(mode="json"))
    return OrderSubmitOut(dryRun=False, orderId=res.orderId, clientOrderId=res.clientOrderId,
                          auditId=audit_id, request=payload)


@router.post("/modify/preview", response_model=PreviewOut)
def modify_preview(body: ModifyPreviewIn, cfg: TradeConfig = Depends(get_cfg), toss: TossClient = Depends(get_toss),
                   store: PreviewStore = Depends(get_preview), conn: Connection = Depends(get_conn)) -> PreviewOut:
    original = toss.get_order(body.orderId)
    synthetic = OrderCreateRequest(symbol=original.symbol, side=original.side, orderType=body.orderType,
                                   quantity=body.quantity, price=body.price,
                                   confirmHighValueOrder=body.confirmHighValueOrder)
    g = _guard(synthetic, cfg=cfg, toss=toss, log=AuditLog(conn), count_toward_daily=False)
    est = _estimate(original.side, g, _kr_commission_rate(toss))
    payload = {"orderId": body.orderId, **body.model_dump(mode="json", exclude={"orderId"}, exclude_none=True)}
    token = store.put(payload, {"amount": str(g.amount_krw), "basis": g.amount_basis,
                                "symbol": original.symbol, "side": original.side})
    return PreviewOut(previewToken=token, clientOrderId=None, request=payload, estimate=est,
                      warnings=g.warnings, dryRun=cfg.dry_run, expiresInSec=PREVIEW_TTL_SEC)


@router.post("/{order_id}/modify", response_model=OperationOut)
def modify(order_id: str, body: ModifySubmitIn, cfg: TradeConfig = Depends(get_cfg), toss: TossClient = Depends(get_toss),
           store: PreviewStore = Depends(get_preview), conn: Connection = Depends(get_conn)) -> OperationOut:
    payload = {"orderId": order_id, **body.request.model_dump(mode="json", exclude_none=True)}
    meta = store.verify(body.previewToken, payload)
    log = AuditLog(conn)
    audit_id = log.begin("modify", meta["symbol"], meta["side"], None, Decimal(meta["amount"]), payload, dry_run=cfg.dry_run)
    conn.commit()
    if cfg.dry_run:
        log.finish(audit_id, http_status=DRY_RUN_STATUS)
        return OperationOut(dryRun=True, orderId=None, auditId=audit_id)
    try:
        res = toss.modify_order(order_id, body.request)
    except TossApiError as e:
        log.finish(audit_id, http_status=e.status, error_code=e.code, request_id=e.request_id)
        conn.commit()
        raise
    log.finish(audit_id, http_status=200, order_id=res.orderId, response_json=res.model_dump(mode="json"))
    return OperationOut(dryRun=False, orderId=res.orderId, auditId=audit_id)


@router.post("/{order_id}/cancel", response_model=OperationOut)
def cancel(order_id: str, cfg: TradeConfig = Depends(get_cfg), toss: TossClient = Depends(get_toss),
           conn: Connection = Depends(get_conn)) -> OperationOut:
    original = toss.get_order(order_id)
    log = AuditLog(conn)
    audit_id = log.begin("cancel", original.symbol, original.side, None, None, {"orderId": order_id}, dry_run=cfg.dry_run)
    conn.commit()
    if cfg.dry_run:
        log.finish(audit_id, http_status=DRY_RUN_STATUS)
        return OperationOut(dryRun=True, orderId=None, auditId=audit_id)
    try:
        res = toss.cancel_order(order_id)
    except TossApiError as e:
        log.finish(audit_id, http_status=e.status, error_code=e.code, request_id=e.request_id)
        conn.commit()
        raise
    log.finish(audit_id, http_status=200, order_id=res.orderId, response_json=res.model_dump(mode="json"))
    return OperationOut(dryRun=False, orderId=res.orderId, auditId=audit_id)


@router.get("", response_model=PaginatedOrderResponse)
def list_orders(status: str = Query(..., pattern="^(OPEN|CLOSED)$"), cursor: str | None = None,
                limit: int | None = Query(None, ge=1, le=100), toss: TossClient = Depends(get_toss)) -> PaginatedOrderResponse:
    return toss.list_orders(status, cursor=cursor, limit=limit)


@router.get("/{order_id}", response_model=Order)
def detail(order_id: str, toss: TossClient = Depends(get_toss)) -> Order:
    return toss.get_order(order_id)
```

`trade_api/main.py`: `from trade_api.routers import accounts, health, holdings, market, orders` + `app.include_router(orders.router)`.

> 주의: `/modify/preview`는 `/{order_id}/modify`보다 **먼저** 등록돼야 한다(FastAPI는 선언 순서로 매칭). 위 파일 순서 그대로 둔다.

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_trade_api_orders.py -v` → 10 passed

- [ ] **Step 5: 커밋**

```bash
git add trade_api/routers/orders.py trade_api/schemas.py trade_api/main.py tests/test_trade_api_orders.py
git commit -m "trade_api: 주문 라우트 — preview 토큰 강제·DRY_RUN 무전송·감사 INSERT→UPDATE·정정(누적 재검 제외)·취소·목록·상세"
```

---

### Task 12: 프론트 기반 — vite 프록시 · `tradeApi.ts` · 타입 · 에러 문구 매핑

**Files:**
- Modify: `web/vite.config.ts`(proxy 1줄)
- Create: `web/src/lib/tradeTypes.ts`, `web/src/lib/tradeErrors.ts`, `web/src/lib/tradeApi.ts`, `web/src/lib/tradeMath.ts`
- Test: `web/src/lib/tradeErrors.test.ts`, `web/src/lib/tradeMath.test.ts`(vitest)

**Interfaces:**
- Produces:
  - `TradeApiError extends Error { status: number; code: string; message: string; data: unknown; requestId: string | null }`
  - `tradeApi<T>(path: string, init?: RequestInit): Promise<T>` — `/trade-api` base, 에러 envelope → `TradeApiError`
  - `errorMessage(code: string, fallback: string): string` — 한국어 매핑, unknown은 `${code} · ${fallback}`
  - `estimateAmount(orderType, price: string | null, qty: string, upperLimit: string | null): { amount: string; basis: "limit" | "upper_limit" } | null` — BigInt 기반 정수 곱(float 금지)
  - 타입: `Health, AccountOut, HoldingsOut, MismatchOut, SearchHit, QuoteOut, BuyingPower, Sellable, PreviewOut, OrderSubmitOut, OperationOut, Order, PaginatedOrders`(모든 금액 필드 `string`)

- [ ] **Step 1: 실패 테스트 작성**

```ts
// web/src/lib/tradeErrors.test.ts
import { describe, expect, it } from "vitest";
import { errorMessage } from "./tradeErrors";

describe("errorMessage", () => {
  it("maps known toss codes to Korean", () => {
    expect(errorMessage("insufficient-buying-power", "")).toContain("매수 가능 금액");
    expect(errorMessage("order-hours-closed", "")).toContain("주문 접수 불가 시간");
    expect(errorMessage("opposite-pending-order-exists", "")).toContain("반대 방향");
    expect(errorMessage("edge-blocked", "")).toContain("허용 IP");
  });
  it("maps guard codes", () => {
    expect(errorMessage("guard/tick-size", "")).toContain("호가 단위");
    expect(errorMessage("guard/preview-required", "")).toContain("미리보기");
    expect(errorMessage("guard/max-daily-amount", "")).toContain("1일");
  });
  it("falls back to code · message for unknown codes", () => {
    expect(errorMessage("brand-new-code", "서버 메시지")).toBe("brand-new-code · 서버 메시지");
    expect(errorMessage("brand-new-code", "")).toBe("brand-new-code");
  });
});
```

```ts
// web/src/lib/tradeMath.test.ts
import { describe, expect, it } from "vitest";
import { estimateAmount } from "./tradeMath";

describe("estimateAmount", () => {
  it("limit = price × qty as integer string", () => {
    expect(estimateAmount("LIMIT", "70000", "10", "91000")).toEqual({ amount: "700000", basis: "limit" });
  });
  it("market uses upper limit", () => {
    expect(estimateAmount("MARKET", null, "10", "91000")).toEqual({ amount: "910000", basis: "upper_limit" });
  });
  it("returns null when inputs incomplete", () => {
    expect(estimateAmount("LIMIT", "", "10", "91000")).toBeNull();
    expect(estimateAmount("MARKET", null, "10", null)).toBeNull();
    expect(estimateAmount("LIMIT", "70000", "0", "91000")).toBeNull();
  });
  it("handles large values without float rounding", () => {
    expect(estimateAmount("LIMIT", "1234567", "98765", null)!.amount).toBe("121932009755");   // 1234567×98765 (python 실측)
  });
});
```

- [ ] **Step 2: 실패 확인** — `cd web && npx vitest run src/lib/tradeErrors.test.ts src/lib/tradeMath.test.ts` → 모듈 없음

- [ ] **Step 3: 구현**

`web/vite.config.ts` — `server.proxy`에 추가:

```ts
      "/trade-api": process.env.VITE_TRADE_API_TARGET || "http://localhost:8001",
```

```ts
// web/src/lib/tradeTypes.ts
// trade_api(:8001) 응답 타입. 금액·수량은 전부 string(Decimal) — 절대 Number()로 계산하지 않는다.
export interface Health { dryRun: boolean; maxOrderKrw: string; maxDailyKrw: string; accountSeq: number | null }
export interface AccountOut { accountNo: string; accountSeq: number; accountType: string }
export interface Money { krw: string; usd: string | null }
export interface HoldingsItem {
  symbol: string; name: string; marketCountry: string; currency: string;
  quantity: string; lastPrice: string; averagePurchasePrice: string;
  marketValue: Money; profitLoss: Money; dailyProfitLoss: Money; cost: Money;
}
export interface HoldingsOverview {
  totalPurchaseAmount: Money; marketValue: Money; profitLoss: Money; dailyProfitLoss: Money; items: HoldingsItem[];
}
export interface MismatchOut { symbol: string; name: string; tossQty: string; positionQty: string | null; kind: "missing" | "qty_diff" | string }
export interface HoldingsOut { overview: HoldingsOverview; mismatch: MismatchOut[] }
export interface SearchHit { ticker: string; name: string; market: string }
export interface OrderbookEntry { price: string; volume: string }
export interface QuoteOut {
  symbol: string; name: string | null;
  price: { symbol: string; timestamp: string | null; lastPrice: string; currency: string };
  orderbook: { timestamp: string | null; currency: string; asks: OrderbookEntry[]; bids: OrderbookEntry[] };
  limits: { timestamp: string; currency: string; upperLimitPrice: string | null; lowerLimitPrice: string | null };
  warnings: { warningType: string; exchange: string | null; startDate: string | null; endDate: string | null }[];
}
export interface BuyingPower { currency: string; cashBuyingPower: string }
export interface Sellable { sellableQuantity: string }
export interface EstimateOut { amount: string; amountBasis: string; commission: string | null; total: string }
export interface PreviewOut {
  previewToken: string; clientOrderId: string | null; request: Record<string, unknown>;
  estimate: EstimateOut; warnings: string[]; dryRun: boolean; expiresInSec: number;
}
export interface OrderSubmitOut { dryRun: boolean; orderId: string | null; clientOrderId: string | null; auditId: number; request: Record<string, unknown> }
export interface OperationOut { dryRun: boolean; orderId: string | null; auditId: number }
export interface OrderExecution {
  filledQuantity: string; averageFilledPrice: string | null; filledAmount: string | null;
  commission: string | null; tax: string | null; filledAt: string | null; settlementDate: string | null;
}
export interface Order {
  orderId: string; symbol: string; side: string; orderType: string; timeInForce: string; status: string;
  price: string | null; quantity: string; orderAmount: string | null; currency: string;
  orderedAt: string; canceledAt: string | null; execution: OrderExecution;
}
export interface PaginatedOrders { orders: Order[]; nextCursor: string | null; hasNext: boolean }
```

```ts
// web/src/lib/tradeErrors.ts
// 토스 에러 코드(요약 문서 §7) + 자체 가드(guard/*) → 한국어. unknown 은 code 그대로(스펙 요구).
const MESSAGES: Record<string, string> = {
  // 인증·권한
  "invalid-token": "토큰이 유효하지 않습니다 (서버가 재발급합니다)",
  "expired-token": "토큰이 만료되었습니다 (서버가 재발급합니다)",
  "token-revoked": "다른 곳에서 토큰이 재발급되어 무효화됨 — 토스 호출 프로세스가 2개 이상인지 확인",
  "edge-blocked": "허용 IP 미등록 또는 인증 헤더 누락 — 토스 WTS 설정 > Open API > 허용 IP 확인",
  forbidden: "권한이 없습니다",
  // 요청 검증
  "invalid-request": "요청 값 오류 (호가 단위·수량·가격·필수값)",
  "confirm-high-value-required": "1억원 이상 주문은 고액 주문 확인이 필요합니다",
  "account-header-required": "계좌 정보가 누락되었습니다 (TOSS_ACCOUNT_SEQ)",
  "unsupported-content-type": "요청 형식 오류",
  // 상태 충돌
  "request-in-progress": "같은 주문이 처리 중입니다 — 잠시 후 상태를 확인하세요",
  "already-filled": "이미 체결된 주문입니다",
  "already-canceled": "이미 취소된 주문입니다",
  "already-modified": "이미 정정된 주문입니다",
  "already-rejected": "이미 거부된 주문입니다",
  "already-processing": "해당 주문에 정정/취소가 진행 중입니다",
  "opposite-pending-order-exists": "같은 종목에 반대 방향 대기 주문이 있습니다",
  // 주문 실행 불가
  "insufficient-buying-power": "매수 가능 금액이 부족합니다",
  "order-hours-closed": "현재는 주문 접수 불가 시간입니다",
  "stock-restricted": "거래가 제한된 종목입니다",
  "price-out-of-range": "상·하한가 범위를 벗어난 가격입니다",
  "order-type-not-allowed": "현재 사용할 수 없는 호가 유형입니다",
  "prerequisite-required": "약관 동의·교육 이수·위험 고지가 필요합니다 (토스 앱에서 진행)",
  "market-not-supported-for-stock": "해당 종목은 이 시장에서 거래할 수 없습니다",
  "investor-exchange-not-integrated": "투자자지시 거래소가 통합(SOR)이 아닙니다",
  "order-limit-exceeded": "주문 한도를 초과했습니다",
  "idempotency-key-conflict": "같은 주문 ID로 다른 내용이 요청되었습니다 — 미리보기를 다시 실행하세요",
  "account-restricted": "이 계좌 유형은 해당 주문을 할 수 없습니다",
  "max-order-amount-exceeded": "30억원 이상 주문은 접수할 수 없습니다",
  "stock-not-found": "종목을 찾을 수 없습니다",
  "account-not-found": "계좌를 찾을 수 없습니다",
  "order-not-found": "주문을 찾을 수 없습니다",
  "rate-limit-exceeded": "요청 한도 초과 — 잠시 후 다시 시도",
  "edge-rate-limit-exceeded": "요청 한도 초과 — 잠시 후 다시 시도",
  "internal-error": "토스 서버 오류",
  maintenance: "토스 서버 점검 중",
  // 자체 가드
  "guard/preview-required": "미리보기가 없거나 만료되었습니다 — 미리보기를 다시 실행하세요",
  "guard/preview-mismatch": "미리보기한 내용과 주문 내용이 다릅니다 — 미리보기를 다시 실행하세요",
  "guard/price-required": "지정가 주문은 가격이 필요합니다",
  "guard/price-forbidden": "시장가 주문에는 가격을 넣지 않습니다",
  "guard/quantity-invalid": "수량은 1 이상의 정수여야 합니다",
  "guard/tick-size": "호가 단위에 맞지 않는 가격입니다",
  "guard/price-out-of-range": "상·하한가 범위를 벗어난 가격입니다",
  "guard/price-limit-unavailable": "상한가를 조회할 수 없어 시장가 금액을 계산할 수 없습니다",
  "guard/max-order-amount": "1건 주문 금액 상한을 초과했습니다",
  "guard/max-daily-amount": "1일 매수 누적 상한을 초과했습니다",
  "guard/sellable-exceeded": "판매 가능 수량을 초과했습니다",
  "guard/confirm-high-value-required": "1억원 이상 주문은 고액 확인 체크가 필요합니다",
  "guard/max-order-amount-exceeded": "30억원 이상 주문은 접수할 수 없습니다",
  "guard/account-seq-missing": "TOSS_ACCOUNT_SEQ 가 설정되지 않았습니다 — 계좌 확인 후 .env 에 고정",
};

export function errorMessage(code: string, fallback: string): string {
  const known = MESSAGES[code];
  if (known) return known;
  return fallback ? `${code} · ${fallback}` : code;
}
```

```ts
// web/src/lib/tradeMath.ts
// 금액 계산은 BigInt 정수 곱만 — KR 가격·수량은 정수. float 금지(spec §5).
const INT = /^\d+$/;

export function estimateAmount(
  orderType: string, price: string | null, qty: string, upperLimit: string | null,
): { amount: string; basis: "limit" | "upper_limit" } | null {
  if (!INT.test(qty) || BigInt(qty) <= 0n) return null;
  if (orderType === "MARKET") {
    if (!upperLimit || !INT.test(upperLimit)) return null;
    return { amount: (BigInt(upperLimit) * BigInt(qty)).toString(), basis: "upper_limit" };
  }
  if (!price || !INT.test(price)) return null;
  return { amount: (BigInt(price) * BigInt(qty)).toString(), basis: "limit" };
}

export function fmtKrw(s: string | null | undefined): string {
  if (s == null || s === "") return "—";
  const [int, frac] = s.split(".");
  const neg = int.startsWith("-");
  const digits = neg ? int.slice(1) : int;
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${neg ? "-" : ""}${grouped}${frac ? "." + frac.replace(/0+$/, "").slice(0, 2) : ""}`.replace(/\.$/, "");
}
```

```ts
// web/src/lib/tradeApi.ts
// trade_api(:8001) 전용 클라이언트. 기존 lib/api.ts(:8000)와 분리. 에러 envelope 을 그대로 보존.
const BASE = "/trade-api";

export class TradeApiError extends Error {
  status: number; code: string; data: unknown; requestId: string | null;
  constructor(status: number, code: string, message: string, data: unknown, requestId: string | null) {
    super(message);
    this.status = status; this.code = code; this.data = data; this.requestId = requestId;
  }
}

export async function tradeApi<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let env: { error?: { code?: string; message?: string; data?: unknown; requestId?: string | null } } = {};
    try { env = await res.json(); } catch { /* 본문 없음 */ }
    const e = env.error ?? {};
    throw new TradeApiError(res.status, e.code ?? "http-error", e.message ?? "", e.data ?? null, e.requestId ?? null);
  }
  return res.json();
}

export const postJson = <T,>(path: string, body: unknown) =>
  tradeApi<T>(path, { method: "POST", body: JSON.stringify(body) });
```

- [ ] **Step 4: 통과 확인** — `cd web && npx vitest run src/lib/tradeErrors.test.ts src/lib/tradeMath.test.ts` → 7 passed; `npx tsc -b` 오류 0

- [ ] **Step 5: 커밋**

```bash
git add web/vite.config.ts web/src/lib/tradeTypes.ts web/src/lib/tradeErrors.ts web/src/lib/tradeMath.ts web/src/lib/tradeApi.ts web/src/lib/tradeErrors.test.ts web/src/lib/tradeMath.test.ts
git commit -m "web: /trade-api 프록시·tradeApi 클라이언트(에러 envelope 보존)·타입·에러 한국어 매핑·BigInt 금액 계산"
```

---

### Task 13: TradingPage — 주문 패널 · 주문 현황 · 보유 + 라우트·NAV

**Files:**
- Create: `web/src/components/trading/ModeBanner.tsx`, `SymbolSearch.tsx`, `OrderPanel.tsx`, `PreviewModal.tsx`, `OrdersTable.tsx`, `HoldingsTable.tsx`, `web/src/pages/TradingPage.tsx`
- Modify: `web/src/App.tsx`(import·NAV 항목·Route)

**Interfaces:**
- Consumes: Task 12 전부
- 동작 규약(spec §7): 상단 배너 `/health` 30초 폴링(노란 연습/빨간 실주문); 주문 현황 OPEN 탭은 **OPEN 주문이 있을 때만 2초 폴링**(`refetchInterval: (q) => (q.state.data?.orders.length ? 2000 : false)`); 주문·정정·취소 성공 시 `orders`·`holdings`·`buying-power` 쿼리 invalidate; 매도 시 sellable 초과면 버튼 비활성; 미리보기 모달에서만 `[주문 전송]` 노출.

- [ ] **Step 1: 컴포넌트 작성** (UI 컴포넌트는 vitest 대상 밖 — 검증은 Step 3 수동 + tsc/eslint)

```tsx
// web/src/components/trading/ModeBanner.tsx
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import { tradeApi } from "../../lib/tradeApi";
import type { Health } from "../../lib/tradeTypes";
import { fmtKrw } from "../../lib/tradeMath";

export function useHealth() {
  return useQuery<Health>({ queryKey: ["trade", "health"], queryFn: () => tradeApi<Health>("/health"), refetchInterval: 30_000 });
}

export default function ModeBanner() {
  const q = useHealth();
  if (q.isError) return <div className="rounded-md bg-slate-800 text-slate-100 px-3 py-2 text-sm">매매 서버(:8001)에 연결할 수 없습니다 — `uv run uvicorn trade_api.main:app --port 8001`</div>;
  if (!q.data) return null;
  const h = q.data;
  return h.dryRun ? (
    <div className="flex items-center gap-2 rounded-md bg-amber-100 text-amber-900 px-3 py-2 text-sm">
      <ShieldCheck size={16} /> <b>연습 모드 (DRY_RUN)</b> — 주문은 토스에 전송되지 않고 감사로그에만 기록됩니다. 상한 1건 {fmtKrw(h.maxOrderKrw)} / 1일 {fmtKrw(h.maxDailyKrw)}원
    </div>
  ) : (
    <div className="flex items-center gap-2 rounded-md bg-red-600 text-white px-3 py-2 text-sm">
      <AlertTriangle size={16} /> <b>실주문 모드</b> — 주문 전송 시 실제 계좌에 주문이 접수됩니다. 상한 1건 {fmtKrw(h.maxOrderKrw)} / 1일 {fmtKrw(h.maxDailyKrw)}원 · 계좌 #{h.accountSeq ?? "미설정"}
    </div>
  );
}
```

```tsx
// web/src/components/trading/SymbolSearch.tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { tradeApi } from "../../lib/tradeApi";
import type { SearchHit } from "../../lib/tradeTypes";

export default function SymbolSearch({ onSelect }: { onSelect: (hit: SearchHit) => void }) {
  const [q, setQ] = useState("");
  const hits = useQuery<SearchHit[]>({
    queryKey: ["trade", "search", q],
    queryFn: () => tradeApi<SearchHit[]>(`/search?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length >= 1,
    staleTime: 60_000,
  });
  return (
    <div className="relative">
      <input className="w-full rounded border px-2 py-1 text-sm" placeholder="종목명 또는 코드" value={q} onChange={(e) => setQ(e.target.value)} />
      {q && hits.data && hits.data.length > 0 && (
        <ul className="absolute z-10 mt-1 w-full max-h-60 overflow-auto rounded border bg-white shadow text-sm">
          {hits.data.map((h) => (
            <li key={h.ticker} className="cursor-pointer px-2 py-1 hover:bg-slate-100" onClick={() => { onSelect(h); setQ(""); }}>
              <span className="font-mono">{h.ticker}</span> {h.name} <span className="text-slate-400">{h.market}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

```tsx
// web/src/components/trading/PreviewModal.tsx
import { errorMessage } from "../../lib/tradeErrors";
import { fmtKrw } from "../../lib/tradeMath";
import type { PreviewOut } from "../../lib/tradeTypes";

interface Props {
  preview: PreviewOut; title: string; submitting: boolean; error: { code: string; message: string } | null;
  onConfirm: () => void; onClose: () => void;
}

export default function PreviewModal({ preview, title, submitting, error, onConfirm, onClose }: Props) {
  const e = preview.estimate;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-[520px] max-w-[95vw] rounded-lg bg-white p-4 shadow-xl" onClick={(ev) => ev.stopPropagation()}>
        <h3 className="mb-2 text-base font-semibold">{title} — 미리보기</h3>
        <div className={`mb-3 rounded px-2 py-1 text-xs ${preview.dryRun ? "bg-amber-100 text-amber-900" : "bg-red-600 text-white"}`}>
          {preview.dryRun ? "연습 모드: 전송되지 않습니다" : "실주문 모드: 전송하면 실제 주문이 접수됩니다"}
        </div>
        <dl className="grid grid-cols-2 gap-y-1 text-sm">
          <dt className="text-slate-500">예상 주문금액</dt><dd>{fmtKrw(e.amount)}원 {e.amountBasis === "upper_limit" && <span className="text-xs text-slate-500">(상한가 기준 최대)</span>}</dd>
          <dt className="text-slate-500">예상 수수료</dt><dd>{e.commission ? `${fmtKrw(e.commission)}원` : "—"}</dd>
          <dt className="text-slate-500">예상 총액</dt><dd className="font-semibold">{fmtKrw(e.total)}원</dd>
          {preview.clientOrderId && (<><dt className="text-slate-500">clientOrderId</dt><dd className="font-mono text-xs">{preview.clientOrderId}</dd></>)}
        </dl>
        {preview.warnings.length > 0 && <div className="mt-2 rounded bg-orange-100 px-2 py-1 text-xs text-orange-900">경고: {preview.warnings.join(", ")}</div>}
        <details className="mt-2 text-xs"><summary className="cursor-pointer text-slate-500">보낼 요청 본문</summary>
          <pre className="mt-1 overflow-auto rounded bg-slate-50 p-2">{JSON.stringify(preview.request, null, 2)}</pre></details>
        {error && <div className="mt-2 rounded bg-red-100 px-2 py-1 text-sm text-red-800">{errorMessage(error.code, error.message)}</div>}
        <div className="mt-4 flex justify-end gap-2">
          <button className="rounded border px-3 py-1 text-sm" onClick={onClose}>닫기</button>
          <button className={`rounded px-3 py-1 text-sm text-white ${preview.dryRun ? "bg-amber-600" : "bg-red-600"}`} disabled={submitting} onClick={onConfirm}>
            {submitting ? "전송 중…" : preview.dryRun ? "연습 전송" : "주문 전송"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

```tsx
// web/src/components/trading/OrderPanel.tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { postJson, tradeApi, TradeApiError } from "../../lib/tradeApi";
import { errorMessage } from "../../lib/tradeErrors";
import { estimateAmount, fmtKrw } from "../../lib/tradeMath";
import type { BuyingPower, OrderSubmitOut, PreviewOut, QuoteOut, SearchHit, Sellable } from "../../lib/tradeTypes";
import PreviewModal from "./PreviewModal";
import SymbolSearch from "./SymbolSearch";

type Side = "BUY" | "SELL"; type OrderType = "LIMIT" | "MARKET";

export default function OrderPanel() {
  const qc = useQueryClient();
  const [hit, setHit] = useState<SearchHit | null>(null);
  const [side, setSide] = useState<Side>("BUY");
  const [orderType, setOrderType] = useState<OrderType>("LIMIT");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  const [confirmHigh, setConfirmHigh] = useState(false);
  const [preview, setPreview] = useState<PreviewOut | null>(null);
  const [err, setErr] = useState<{ code: string; message: string } | null>(null);
  const [done, setDone] = useState<OrderSubmitOut | null>(null);
  const sym = hit?.ticker ?? null;

  const quote = useQuery<QuoteOut>({ queryKey: ["trade", "quote", sym], queryFn: () => tradeApi<QuoteOut>(`/quote/${sym}`), enabled: !!sym, refetchInterval: 5_000 });
  const bp = useQuery<BuyingPower>({ queryKey: ["trade", "buying-power"], queryFn: () => tradeApi<BuyingPower>("/buying-power"), refetchInterval: 15_000 });
  const sellable = useQuery<Sellable>({ queryKey: ["trade", "sellable", sym], queryFn: () => tradeApi<Sellable>(`/sellable/${sym}`), enabled: !!sym && side === "SELL" });

  const upper = quote.data?.limits.upperLimitPrice ?? null;
  const est = estimateAmount(orderType, orderType === "LIMIT" ? price : null, qty, upper);
  const sellOver = side === "SELL" && sellable.data && qty !== "" && /^\d+$/.test(qty) && BigInt(qty) > BigInt(sellable.data.sellableQuantity);
  const toErr = (e: unknown) => (e instanceof TradeApiError ? { code: e.code, message: e.message } : { code: "http-error", message: String(e) });

  const doPreview = useMutation({
    mutationFn: () => postJson<PreviewOut>("/orders/preview", { symbol: sym, side, orderType, quantity: qty, price: orderType === "LIMIT" ? price : null, confirmHighValueOrder: confirmHigh }),
    onSuccess: (p) => { setPreview(p); setErr(null); setDone(null); },
    onError: (e) => setErr(toErr(e)),
  });
  const doSubmit = useMutation({
    mutationFn: () => postJson<OrderSubmitOut>("/orders", { previewToken: preview!.previewToken, request: preview!.request }),
    onSuccess: (r) => { setDone(r); setPreview(null); setErr(null); qc.invalidateQueries({ queryKey: ["trade", "orders"] }); qc.invalidateQueries({ queryKey: ["trade", "holdings"] }); qc.invalidateQueries({ queryKey: ["trade", "buying-power"] }); },
    onError: (e) => setErr(toErr(e)),
  });

  const canPreview = !!sym && est !== null && !sellOver && !doPreview.isPending;
  return (
    <section className="rounded-lg border p-3">
      <h2 className="mb-2 font-semibold">주문</h2>
      <SymbolSearch onSelect={(h) => { setHit(h); setDone(null); setErr(null); }} />
      {hit && (
        <div className="mt-2 text-sm">
          <div className="font-medium"><span className="font-mono">{hit.ticker}</span> {hit.name}</div>
          {quote.data && (
            <div className="mt-1 grid grid-cols-3 gap-2 text-xs text-slate-600">
              <div>현재가 <b className="text-slate-900">{fmtKrw(quote.data.price.lastPrice)}</b></div>
              <div>상한 {fmtKrw(quote.data.limits.upperLimitPrice)}</div>
              <div>하한 {fmtKrw(quote.data.limits.lowerLimitPrice)}</div>
            </div>
          )}
          {quote.data && quote.data.warnings.length > 0 && (
            <div className="mt-1 rounded bg-red-100 px-2 py-1 text-xs text-red-800">유의사항: {quote.data.warnings.map((w) => w.warningType).join(", ")}</div>
          )}
          {quote.data && (
            <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
              <div><div className="text-slate-500">매도호가</div>{quote.data.orderbook.asks.slice(0, 5).reverse().map((a) => <div key={a.price} className="flex justify-between"><span className="text-blue-700">{fmtKrw(a.price)}</span><span>{fmtKrw(a.volume)}</span></div>)}</div>
              <div><div className="text-slate-500">매수호가</div>{quote.data.orderbook.bids.slice(0, 5).map((b) => <div key={b.price} className="flex justify-between"><span className="text-red-700">{fmtKrw(b.price)}</span><span>{fmtKrw(b.volume)}</span></div>)}</div>
            </div>
          )}
        </div>
      )}
      <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
        <div className="flex gap-1">{(["BUY", "SELL"] as Side[]).map((s) => <button key={s} className={`flex-1 rounded px-2 py-1 ${side === s ? (s === "BUY" ? "bg-red-600 text-white" : "bg-blue-600 text-white") : "border"}`} onClick={() => setSide(s)}>{s === "BUY" ? "매수" : "매도"}</button>)}</div>
        <div className="flex gap-1">{(["LIMIT", "MARKET"] as OrderType[]).map((t) => <button key={t} className={`flex-1 rounded px-2 py-1 ${orderType === t ? "bg-slate-800 text-white" : "border"}`} onClick={() => setOrderType(t)}>{t === "LIMIT" ? "지정가" : "시장가"}</button>)}</div>
        <label className="text-xs text-slate-600">수량<input className="mt-0.5 w-full rounded border px-2 py-1" inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))} /></label>
        <label className="text-xs text-slate-600">가격(원){orderType === "MARKET" && <span className="ml-1 text-slate-400">시장가 — 입력 안 함</span>}
          <input className="mt-0.5 w-full rounded border px-2 py-1" inputMode="numeric" disabled={orderType === "MARKET"} value={orderType === "MARKET" ? "" : price} onChange={(e) => setPrice(e.target.value.replace(/\D/g, ""))} /></label>
      </div>
      <div className="mt-2 text-sm">
        예상 주문금액 <b>{est ? `${fmtKrw(est.amount)}원` : "—"}</b>{est?.basis === "upper_limit" && <span className="ml-1 text-xs text-slate-500">(상한가 기준 최대)</span>}
        <span className="ml-3 text-xs text-slate-500">매수가능 {bp.data ? `${fmtKrw(bp.data.cashBuyingPower)}원` : "—"}</span>
        {side === "SELL" && <span className={`ml-3 text-xs ${sellOver ? "text-red-600" : "text-slate-500"}`}>판매가능 {sellable.data ? sellable.data.sellableQuantity : "—"}주{sellOver && " — 초과"}</span>}
      </div>
      {est && BigInt(est.amount) >= 100_000_000n && (
        <label className="mt-1 flex items-center gap-1 text-xs text-orange-800"><input type="checkbox" checked={confirmHigh} onChange={(e) => setConfirmHigh(e.target.checked)} /> 1억원 이상 고액 주문임을 확인합니다</label>
      )}
      {err && !preview && <div className="mt-2 rounded bg-red-100 px-2 py-1 text-sm text-red-800">{errorMessage(err.code, err.message)}</div>}
      {done && <div className="mt-2 rounded bg-emerald-100 px-2 py-1 text-sm text-emerald-900">{done.dryRun ? "연습 모드 — 감사로그 기록만" : `주문 접수 orderId ${done.orderId}`} (audit #{done.auditId})</div>}
      <button className="mt-3 w-full rounded bg-slate-900 px-3 py-2 text-sm text-white disabled:opacity-40" disabled={!canPreview} onClick={() => doPreview.mutate()}>{doPreview.isPending ? "검증 중…" : "미리보기"}</button>
      {preview && <PreviewModal preview={preview} title={`${hit?.name ?? sym} ${side === "BUY" ? "매수" : "매도"}`} submitting={doSubmit.isPending} error={err} onConfirm={() => doSubmit.mutate()} onClose={() => { setPreview(null); setErr(null); }} />}
    </section>
  );
}
```

```tsx
// web/src/components/trading/OrdersTable.tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { postJson, tradeApi, TradeApiError } from "../../lib/tradeApi";
import { errorMessage } from "../../lib/tradeErrors";
import { fmtKrw } from "../../lib/tradeMath";
import type { OperationOut, Order, PaginatedOrders, PreviewOut } from "../../lib/tradeTypes";
import PreviewModal from "./PreviewModal";

const STATUS_KR: Record<string, string> = {
  PENDING: "대기", PENDING_CANCEL: "취소 대기", PENDING_REPLACE: "정정 대기", PARTIAL_FILLED: "부분 체결",
  FILLED: "체결", CANCELED: "취소", REJECTED: "거부", REPLACED: "정정됨", CANCEL_REJECTED: "취소 거부", REPLACE_REJECTED: "정정 거부",
};

export default function OrdersTable() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"OPEN" | "CLOSED">("OPEN");
  const [cursor, setCursor] = useState<string | null>(null);
  const [modify, setModify] = useState<{ order: Order; qty: string; price: string } | null>(null);
  const [preview, setPreview] = useState<PreviewOut | null>(null);
  const [err, setErr] = useState<{ code: string; message: string } | null>(null);
  const toErr = (e: unknown) => (e instanceof TradeApiError ? { code: e.code, message: e.message } : { code: "http-error", message: String(e) });
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["trade", "orders"] }); qc.invalidateQueries({ queryKey: ["trade", "holdings"] }); qc.invalidateQueries({ queryKey: ["trade", "buying-power"] }); };

  const q = useQuery<PaginatedOrders>({
    queryKey: ["trade", "orders", tab, cursor],
    queryFn: () => tradeApi<PaginatedOrders>(`/orders?status=${tab}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}${tab === "CLOSED" ? "&limit=20" : ""}`),
    refetchInterval: (query) => (tab === "OPEN" && (query.state.data?.orders.length ?? 0) > 0 ? 2_000 : false),   // OPEN 주문 있을 때만 폴링
  });

  const cancel = useMutation({ mutationFn: (id: string) => postJson<OperationOut>(`/orders/${id}/cancel`, {}), onSuccess: () => { setErr(null); invalidate(); }, onError: (e) => setErr(toErr(e)) });
  const modPreview = useMutation({
    mutationFn: () => postJson<PreviewOut>("/orders/modify/preview", { orderId: modify!.order.orderId, orderType: "LIMIT", quantity: modify!.qty, price: modify!.price }),
    onSuccess: (p) => { setPreview(p); setErr(null); }, onError: (e) => setErr(toErr(e)),
  });
  const modSubmit = useMutation({
    mutationFn: () => postJson<OperationOut>(`/orders/${modify!.order.orderId}/modify`, { previewToken: preview!.previewToken, orderId: modify!.order.orderId, request: { orderType: "LIMIT", quantity: modify!.qty, price: modify!.price } }),
    onSuccess: () => { setPreview(null); setModify(null); setErr(null); invalidate(); }, onError: (e) => setErr(toErr(e)),
  });

  const rows = (q.data?.orders ?? []).filter((o) => tab === "OPEN" || o.status !== "PARTIAL_FILLED");   // PARTIAL_FILLED 는 OPEN 탭에만
  return (
    <section className="rounded-lg border p-3">
      <div className="mb-2 flex items-center gap-2">
        <h2 className="font-semibold">주문 현황</h2>
        {(["OPEN", "CLOSED"] as const).map((t) => <button key={t} className={`rounded px-2 py-0.5 text-xs ${tab === t ? "bg-slate-800 text-white" : "border"}`} onClick={() => { setTab(t); setCursor(null); }}>{t === "OPEN" ? "미체결" : "체결/종료"}</button>)}
        {tab === "OPEN" && rows.length > 0 && <span className="text-xs text-slate-400">2초 갱신</span>}
      </div>
      {err && <div className="mb-2 rounded bg-red-100 px-2 py-1 text-sm text-red-800">{errorMessage(err.code, err.message)}</div>}
      <table className="w-full text-xs">
        <thead className="text-slate-500"><tr><th className="text-left">시각</th><th className="text-left">종목</th><th>구분</th><th>상태</th><th className="text-right">가격</th><th className="text-right">수량</th><th className="text-right">체결</th><th></th></tr></thead>
        <tbody>
          {rows.map((o) => (
            <tr key={o.orderId} className="border-t">
              <td>{o.orderedAt.slice(11, 19)}</td>
              <td className="font-mono">{o.symbol}</td>
              <td className={`text-center ${o.side === "BUY" ? "text-red-700" : "text-blue-700"}`}>{o.side === "BUY" ? "매수" : "매도"} {o.orderType === "MARKET" ? "시장가" : "지정가"}</td>
              <td className="text-center">{STATUS_KR[o.status] ?? o.status}</td>
              <td className="text-right">{fmtKrw(o.price)}</td>
              <td className="text-right">{o.quantity}</td>
              <td className="text-right">{o.execution.filledQuantity}{o.execution.averageFilledPrice && ` @ ${fmtKrw(o.execution.averageFilledPrice)}`}</td>
              <td className="text-right whitespace-nowrap">
                {tab === "OPEN" && (<>
                  <button className="rounded border px-1" onClick={() => setModify({ order: o, qty: o.quantity, price: o.price ?? "" })}>정정</button>
                  <button className="ml-1 rounded border px-1 text-red-700" disabled={cancel.isPending} onClick={() => cancel.mutate(o.orderId)}>취소</button>
                </>)}
              </td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={8} className="py-3 text-center text-slate-400">{q.isLoading ? "불러오는 중…" : "주문 없음"}</td></tr>}
        </tbody>
      </table>
      {tab === "CLOSED" && q.data?.hasNext && <button className="mt-2 rounded border px-2 py-1 text-xs" onClick={() => setCursor(q.data!.nextCursor)}>다음 20건</button>}
      {modify && !preview && (
        <div className="mt-3 rounded border bg-slate-50 p-2 text-sm">
          정정 <span className="font-mono">{modify.order.symbol}</span>
          <input className="ml-2 w-20 rounded border px-1" value={modify.qty} onChange={(e) => setModify({ ...modify, qty: e.target.value.replace(/\D/g, "") })} /> 주
          <input className="ml-2 w-28 rounded border px-1" value={modify.price} onChange={(e) => setModify({ ...modify, price: e.target.value.replace(/\D/g, "") })} /> 원
          <button className="ml-2 rounded bg-slate-900 px-2 py-0.5 text-white" disabled={modPreview.isPending} onClick={() => modPreview.mutate()}>미리보기</button>
          <button className="ml-1 rounded border px-2 py-0.5" onClick={() => setModify(null)}>닫기</button>
        </div>
      )}
      {preview && modify && <PreviewModal preview={preview} title={`${modify.order.symbol} 정정`} submitting={modSubmit.isPending} error={err} onConfirm={() => modSubmit.mutate()} onClose={() => { setPreview(null); setErr(null); }} />}
    </section>
  );
}
```

```tsx
// web/src/components/trading/HoldingsTable.tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { tradeApi } from "../../lib/tradeApi";
import { fmtKrw } from "../../lib/tradeMath";
import type { HoldingsOut } from "../../lib/tradeTypes";

export default function HoldingsTable() {
  const q = useQuery<HoldingsOut>({ queryKey: ["trade", "holdings"], queryFn: () => tradeApi<HoldingsOut>("/holdings"), refetchInterval: 15_000 });
  if (!q.data) return <section className="rounded-lg border p-3"><h2 className="font-semibold">보유</h2><div className="text-sm text-slate-400">{q.isError ? "조회 실패" : "불러오는 중…"}</div></section>;
  const o = q.data.overview;
  const pl = (s: string) => <span className={s.startsWith("-") ? "text-blue-700" : "text-red-700"}>{fmtKrw(s)}</span>;
  return (
    <section className="rounded-lg border p-3">
      <h2 className="mb-2 font-semibold">보유</h2>
      {q.data.mismatch.length > 0 && (
        <div className="mb-2 flex items-start gap-2 rounded bg-orange-100 px-2 py-1 text-xs text-orange-900">
          <AlertTriangle size={14} className="mt-0.5" />
          <div>positions 미기입/불일치 {q.data.mismatch.length}종목 — {q.data.mismatch.map((m) => `${m.name}(${m.kind === "missing" ? "미기입" : `토스 ${m.tossQty} vs positions ${m.positionQty}`})`).join(", ")}.
            손절 러너는 <Link className="underline" to="/positions">positions</Link> 만 봅니다 (등록: <code>python -m kr_pipeline.trade_management --add</code>).</div>
        </div>
      )}
      <div className="mb-2 grid grid-cols-4 gap-2 text-xs">
        <div><div className="text-slate-500">투자원금</div>{fmtKrw(o.totalPurchaseAmount.krw)}</div>
        <div><div className="text-slate-500">평가금액</div>{fmtKrw(o.marketValue.krw)}</div>
        <div><div className="text-slate-500">손익</div>{pl(o.profitLoss.krw)}</div>
        <div><div className="text-slate-500">일간</div>{pl(o.dailyProfitLoss.krw)}</div>
      </div>
      <table className="w-full text-xs">
        <thead className="text-slate-500"><tr><th className="text-left">종목</th><th className="text-right">수량</th><th className="text-right">평단</th><th className="text-right">현재가</th><th className="text-right">평가</th><th className="text-right">손익</th></tr></thead>
        <tbody>
          {o.items.map((it) => (
            <tr key={it.symbol} className="border-t">
              <td><span className="font-mono">{it.symbol}</span> {it.name}</td>
              <td className="text-right">{it.quantity}</td><td className="text-right">{fmtKrw(it.averagePurchasePrice)}</td>
              <td className="text-right">{fmtKrw(it.lastPrice)}</td><td className="text-right">{fmtKrw(it.marketValue.krw)}</td>
              <td className="text-right">{pl(it.profitLoss.krw)}</td>
            </tr>
          ))}
          {o.items.length === 0 && <tr><td colSpan={6} className="py-3 text-center text-slate-400">보유 종목 없음</td></tr>}
        </tbody>
      </table>
    </section>
  );
}
```

```tsx
// web/src/pages/TradingPage.tsx
import ModeBanner from "../components/trading/ModeBanner";
import OrderPanel from "../components/trading/OrderPanel";
import OrdersTable from "../components/trading/OrdersTable";
import HoldingsTable from "../components/trading/HoldingsTable";

// 토스증권 Open API 매매 — 별도 프로세스 trade_api(:8001). spec docs/superpowers/specs/2026-09-14-toss-trading-page-design.md
export default function TradingPage() {
  return (
    <div className="space-y-3">
      <ModeBanner />
      <div className="grid gap-3 lg:grid-cols-[380px_1fr]">
        <OrderPanel />
        <div className="space-y-3"><OrdersTable /><HoldingsTable /></div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: `App.tsx` 연결**

```tsx
// import 추가
import TradingPage from "./pages/TradingPage";
import { Wallet } from "lucide-react";
// NAV_ITEMS — "메타 문서 / 운영" 그룹 앞에 새 그룹
  // ─── 실행 ─────────────────────────────────
  { to: "/trading", label: "Trading", kr: "매매", Icon: Wallet },
// Routes
          <Route path="/trading" element={<TradingPage />} />
```

- [ ] **Step 3: 검증** — `cd web && npx tsc -b && npx eslint src/components/trading src/pages/TradingPage.tsx src/lib/trade*.ts && npx vitest run` → 오류 0, 기존 69 + 7 = 76 passed. 수동: `trade_api` 미기동 상태로 `/trading` 열어 배너 "연결할 수 없습니다" 확인; 기동(DRY_RUN) 후 노란 배너 확인.

- [ ] **Step 4: 커밋**

```bash
git add web/src/components/trading web/src/pages/TradingPage.tsx web/src/App.tsx
git commit -m "web: /trading 페이지 — 모드 배너·주문 패널(미리보기 모달)·주문 현황(OPEN 조건부 폴링·정정/취소)·보유(positions 대조 경고)"
```

---

### Task 14: 문서·운영규칙·전체 검증·PR

**Files:**
- Modify: `README.md`(구동 절), `CLAUDE.md`(운영규칙 6)
- Create: `docs/toss/live-verification-checklist.md`

- [ ] **Step 1: README 「개발 API 서버」 절 아래에 추가**

```markdown
## 매매 API 서버 (토스증권 Open API, 별도 프로세스)

```
uv run uvicorn trade_api.main:app --port 8001
```

- 분석 API(:8000)와 **별도 프로세스**. `--workers` 금지(토스 토큰은 클라이언트당 1개), `--reload` 는 주문 중 재시작을 유발하므로 UI 개발 중에만 명시적으로.
- 기본 `TOSS_DRY_RUN=true`(연습 모드). 실주문은 `.env` 에서 명시적으로 `false` + 재기동. 화면 상단 배너로 현재 모드 확인.
- 설정 키·실물 검증 순서: `docs/toss/live-verification-checklist.md`, 설계: `docs/superpowers/specs/2026-09-14-toss-trading-page-design.md`.
```

- [ ] **Step 2: CLAUDE.md 「운영 규칙」에 6번 추가**

```markdown
6. **토스 API 호출은 `trade_api` 프로세스만** — `kr_pipeline`·CLI·테스트에서 토스 호출 금지(토큰 1개 제약, 위반 시 `401 token-revoked` 로 서로 무효화). `trade_api` 는 `--workers` 금지, `--reload` 기본 미사용. 테스트는 conftest 가 `TOSS_CLIENT_ID/SECRET` 를 비우고 `TOSS_DRY_RUN=true` 를 강제한다(#92 동형).
   발단: 2026-09-14 매매 페이지 설계(spec §4.3) — 문서상 제약을 사고 전에 규칙화.
```

- [ ] **Step 3: 실물 검증 체크리스트 작성**

```markdown
# 토스증권 매매 — 실물 검증 체크리스트 (spec §10, 안 1)

모든 단계는 사용자가 직접 수행·확인한다. 코드 변경 없음.

## 1. 허용 IP 등록 (사용자)
- [ ] 토스 WTS → 설정 > Open API > 허용 IP 관리 → 현재 공인 IP 등록 (`curl -s ifconfig.me`)
- [ ] ⚠️ 공인 IP 변경(재접속·다른 네트워크) 시 재등록. `403 edge-blocked` 가 뜨면 첫 확인 항목.

## 2. 읽기 연결 확인 (DRY_RUN=true)
- [ ] `.env` 에 `TOSS_CLIENT_ID/SECRET` 입력, `TOSS_ACCOUNT_SEQ` 는 비움
- [ ] `uv run uvicorn trade_api.main:app --port 8001` → 기동 로그에 `dry_run=True` 확인
- [ ] `curl -s localhost:8001/trade-api/accounts` → `accountType=BROKERAGE` 계좌의 `accountSeq` 확인 → `.env` `TOSS_ACCOUNT_SEQ` 에 고정 → 재기동
- [ ] `curl -s localhost:8001/trade-api/holdings`, `/trade-api/quote/005930`, `"/trade-api/orders?status=OPEN"` 응답 확인
- [ ] 웹 `/trading` — 노란 "연습 모드" 배너, 보유 표시

## 3. DRY_RUN 주문 경로
- [ ] 매수 미리보기 → 연습 전송 → 응답 `dryRun=true`, `psql "$DATABASE_URL" -c "SELECT kind, dry_run, http_status, client_order_id FROM toss_order_audit ORDER BY id DESC LIMIT 5"` 에 `dry_run=t, http_status=0` 행
- [ ] 고의 오류 확인: 가격 70,050원(호가단위 위반) → `guard/tick-size` 문구; 수량 1,000주 → `guard/max-order-amount`

## 4. 실주문 검증 (비가역 — 장중, 소액)
- [ ] `.env` `TOSS_DRY_RUN=false` → 재기동 → 빨간 "실주문 모드" 배너 확인
- [ ] 유동성 큰 종목 **1주**, 현재가 −3% 근처 **지정가 매수**(체결되지 않도록) → 미리보기 → 주문 전송 → orderId 수신
- [ ] 주문 현황 OPEN 탭에 표시(2초 갱신) → **즉시 취소** → CLOSED 탭 `취소` 확인
- [ ] 감사로그: `create(200, order_id)` 행 + `cancel(200)` 행 확인
- [ ] 위 왕복 통과 후에만: 1주 시장가(또는 현재가 지정가) 매수 → `FILLED` → 보유 표에 반영 → positions 미기입 경고 확인 → (원하면) 1주 매도로 정리
- [ ] 종료 후 `.env` `TOSS_DRY_RUN=true` 복귀 → 재기동 → 노란 배너

## 5. 사고 시
- 응답을 못 받은 주문: `toss_order_audit` 에 `http_status IS NULL` 행 → 토스 앱/`GET /trade-api/orders?status=OPEN` 으로 대조. `request_id` 로 CS 문의.
```

- [ ] **Step 4: 영향도 0 · 전체 suite 검증(Global Constraints)**

```bash
git diff --stat main -- api/ kr_pipeline/ web/src/lib/api.ts | tail -3      # kr_pipeline/db/schema.sql 만 나와야 함
pgrep -f pytest || echo "no other pytest"
uv run pytest tests/ 2>&1 | tail -3        # 기대: 기존 1458 + 신규(12+6+5+5+10+4+20+4+4+4+10=84) passed, 1 skipped, 1 deselected  (T5·T7 fix round 로 +5)
cd web && npx tsc -b && npx eslint . && npx vitest run 2>&1 | tail -3 && cd ..
```

- [ ] **Step 5: 커밋 · PR**

```bash
git add README.md CLAUDE.md docs/toss/live-verification-checklist.md
git commit -m "docs: trade_api 구동법·운영규칙 6(토스 호출 격리)·실물 검증 체크리스트"
git push -u origin feature/toss-trading-page
gh pr create --title "토스증권 매매 페이지 — trade_api(:8001) + /trading (DRY_RUN 기본)" --body-file <(cat <<'MD'
## 요약
spec `docs/superpowers/specs/2026-09-14-toss-trading-page-design.md` 구현. 국내 지정가·시장가 매수/매도·정정/취소·보유·주문현황. 별도 프로세스 `trade_api`(:8001), `TOSS_DRY_RUN=true` 기본, 미리보기 토큰 강제, 감사로그 전송 전 INSERT.

## 기존 영향
`api/`·`kr_pipeline/`(schema.sql 테이블 1개 추가 제외) 변경 0줄. `positions`·`stocks` SELECT 만. suite 결과 첨부.

## 검증
- `uv run pytest tests/` → N passed / 1 skipped / 1 deselected (토스 실접촉 0, MockTransport)
- `web`: tsc·eslint·vitest 76 passed
- 실물 검증은 머지 후 `docs/toss/live-verification-checklist.md` 순서로 사용자가 수행

## 운영
- schema.sql 양쪽 DB 적용 완료(운영규칙 4) / CLAUDE.md 운영규칙 6 추가
MD
)
```

---

## Self-Review

**Spec coverage** — §2 범위: 지정가·시장가(Task 7·11), 정정·취소(11), 조회(10·11), 폴링(13) ✅. §3 D1~D7 ✅(D7 sync: 전 라우트 `def`, `httpx.Client`, `threading.Lock`). §4.1 배치: `kr_trading/toss/*`(2~5), `guard/preview/audit`(6~8), `trade_api/*`(9~11), 프론트(12·13) ✅. §4.3 하드 룰 → Task 14 CLAUDE.md ✅. §5 TokenManager(3) · RateLimiter(4) · TossClient(5) · Decimal 응답 모델 규칙(9 테스트 `test_health_uses_response_model_strings`) · OrderGuard 1~9(7·11) · PreviewStore(8) · AuditLog+DDL(6) ✅. §6 12개 라우트: health·accounts(9), holdings·search·quote·buying-power·sellable(10), preview·orders·modify/preview·modify·cancel·list·detail(11) ✅ — spec 표엔 없던 `modify/preview`가 추가됨(정정도 "미리보기 동일 적용"이라는 spec 문장의 구현체; spec §6 표에 행 추가 필요 → 실행 시 spec 갱신 커밋에 포함). §7 배너·3영역·조건부 폴링·PARTIAL_FILLED 처리·mismatch 배너 ✅. §8 검증 규칙 ✅(`timeInForce` DAY 고정 — 프론트 미노출). §9 env·TradeConfig·httpx 승격(1) ✅. §10 격리(1)·단위/라우터 테스트(2~11)·영향도 0 확인·실물 순서(14) ✅. §12 운영규칙 6(14) ✅.

**Placeholder scan** — "TBD/TODO/적절히/similar to" 없음. 모든 코드 스텝에 실제 코드 있음.

**Type consistency** — `check_order(... count_toward_daily)` Task 7 정의 = Task 11 호출 ✅. `AuditLog.begin(kind, symbol, side, client_order_id, order_amount_krw, request_json, dry_run)` Task 6 = Task 11 호출 순서 ✅. `PreviewStore.put(payload, meta) -> token`, `.verify(token, payload) -> meta` Task 8 = Task 11 ✅. `TossClient.get_order/list_orders/cancel_order/modify_order/create_order` Task 5 = Task 11 ✅. 프론트 `PreviewOut.request`를 그대로 `OrderSubmitIn.request`로 되돌려 보냄 — 백엔드는 `OrderCreateRequest`로 재파싱 후 `to_toss_json()` → 동일 canonical 해시 ✅(`exclude_none` 양쪽 동일). 수정 반영 1건: Task 6 테스트 함수 `add()`가 `status=None`일 때 `finish` 미호출 → pending 행 유지 — 의도와 일치.

**남은 판단** — Task 13 UI 컴포넌트는 vitest 없이 tsc·eslint·수동 확인만. 로직은 Task 12(`tradeMath`·`tradeErrors`)로 빼서 테스트했고, 폴링 조건(`refetchInterval` 함수)은 수동 확인 항목.
