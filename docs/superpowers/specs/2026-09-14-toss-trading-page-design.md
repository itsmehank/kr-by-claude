# 토스증권 Open API 매매 페이지 — 설계 spec

작성 2026-09-14. 상태: **사용자 검토 대기**.
참조: `docs/toss/toss-securities-open-api.md`(요약 문서), 스펙 정본
`https://openapi.tossinvest.com/openapi-docs/latest/openapi.json` (검토 시점 v1.2.17, 33 paths).
요약 문서와 JSON이 다르면 **JSON이 우선**(§11 대조 결과 참조).

## 1. 목표

기존 웹(`web/`)에 페이지 1개를 추가해 **내가 직접 가격을 넣어 국내 주식을 사고팔고,
잔고·보유·주문 현황을 확인**한다. 자동 매매·신호 연동은 범위 밖.

## 2. 범위

**포함** — KRX 종목 · 지정가(LIMIT)/시장가(MARKET) 매수·매도 · 주문 정정·취소 ·
미체결/체결 주문 조회 · 보유 종목·합산 손익 조회 · 매수가능금액·판매가능수량 조회.
상태 갱신은 **폴링**(OPEN 주문이 있을 때만 2초).

**제외** — 미국 주식(금액주문·소수점·환율·CLS), WebSocket 실시간, 조건주문(OCO/OTO),
`positions` 테이블 자동 기입, 자체 로그인/인증(로컬 단일 사용자 전제).

## 3. 결정 사항 (브레인스토밍 질의 기록)

| # | 질의 | 결정 | 근거 |
|---|---|---|---|
| D1 | 1차 범위 | B — 국내 지정가+시장가+정정/취소, 폴링 | 체결 확인은 `GET /orders/{id}` 폴링으로 1~2초 내 가능. WS는 폴링의 대체가 아니라 추가(재연결 시 REST 재동기화 필수)라 1차 제외 |
| D2 | `positions` 연동 | **분리 + 읽기전용 대조 경고** | `positions` 0행·`position_stop_evaluations` 0행. `trade_management/runner.py`가 "수동 기록 모델, entry_price=매수 시점 고정 anchor"를 명시. 토스 평균단가는 추가 매수 시 움직여 손절 anchor 의미와 충돌 → 자동 기입은 판정 규칙 변경이므로 별도 결정 |
| D3 | 사전 준비 상태 | client_id/secret 발급 완료, **허용 IP 미등록** | IP 등록이 실물 검증 1단계 |
| D4 | 자체 금액 상한 | **1건 500만원 / 1일 누적 1,000만원**, `.env` 조정 | 수량 오타 사고 방지. 토스 한도와 별개 |
| D5 | 백엔드 배치 | **별도 프로세스 `trade_api` (:8001)** | 분석 서버 `--reload`가 주문 서버를 재시작시키지 않음, 토큰 보유 프로세스 물리적 1개, 실주문 경로가 읽기전용 분석 서버와 분리 |
| D6 | 구현 전략 | **안 1 — 읽기 먼저 → DRY_RUN 주문 → 실주문 소액 검증** | 토큰·레이트리밋·에러 envelope 불확실성을 실주문 코드 없이 소거 |
| D7 | 동기/비동기 | **sync** (httpx.Client + threading.Lock + sync def) | 기존 `api/routers/*` async 라우트 0개·psycopg sync. 부하 1~2 req/s. async 라우트에서 sync DB 호출 시 이벤트루프 블로킹 함정 회피 |

## 4. 아키텍처

```
web/ (React SPA, :5173, vite dev)
 ├─ 기존 페이지 ── /api        ─proxy─> api.main   (:8000) 분석 API (읽기전용)
 └─ /trading    ── /trade-api  ─proxy─> trade_api  (:8001) ──> openapi.tossinvest.com
                                            │
                                            └──> Postgres (toss_order_audit 쓰기 / positions·stocks 읽기)
```

### 4.1 코드 배치 (기존 `api/`+`kr_pipeline/` 관례 준수)

| 경로 | 역할 |
|---|---|
| `kr_trading/config.py` | `TradeConfig` dataclass (§9) |
| `kr_trading/toss/token.py` | TokenManager |
| `kr_trading/toss/ratelimit.py` | 그룹별 토큰버킷 |
| `kr_trading/toss/client.py` | TossClient (httpx.Client) |
| `kr_trading/toss/errors.py` | `TossApiError(status, code, message, data, request_id)` |
| `kr_trading/toss/models.py` | pydantic 모델 — 숫자는 전부 `Decimal`, enum은 unknown 허용(`str`) |
| `kr_trading/guard.py` | OrderGuard |
| `kr_trading/preview.py` | PreviewStore |
| `kr_trading/audit.py` | AuditLog |
| `trade_api/main.py` | FastAPI 앱, lifespan에서 풀·TokenManager 초기화, 기동 로그 |
| `trade_api/deps.py` | DB 풀 (`api/deps.py` 동형, 별도 인스턴스) |
| `trade_api/routers/{health,accounts,holdings,market,orders}.py` | §6 |
| `web/src/pages/TradingPage.tsx` (+ `components/trading/*`) | §7 |
| `web/src/lib/tradeApi.ts` | `/trade-api` 클라이언트, 에러 envelope 파싱 |

호가단위는 **신설하지 않고** `kr_pipeline/common/krx.py:krx_tick_size` 를 import (2023-01-25 개편 반영,
KOSPI/KOSDAQ 공통). 시그니처 `float → int` 이므로 Decimal 경계에서 변환 1회. 해당 파일은 수정하지 않는다.

### 4.2 구동

```
uv run uvicorn api.main:app --reload --port 8000        # 기존
uv run uvicorn trade_api.main:app --port 8001           # 신규 — --workers 금지, --reload 기본 미사용
```

`--reload`는 주문 중 프로세스 재시작을 유발하므로 UI/개발 중에만 명시적으로 붙인다.

### 4.3 토큰 단일화 하드 룰

토스 API를 호출하는 코드는 `trade_api` 프로세스 안에만 존재한다. `kr_pipeline` 배치·CLI·테스트는
토스를 호출하지 않는다(호출 시 서로의 토큰을 무효화 — `401 token-revoked`). CLAUDE.md 운영규칙 6번으로
승격(§12).

## 5. 백엔드 컴포넌트

**TokenManager** — 프로세스 내 싱글톤, `threading.Lock`으로 발급 직렬화, `expires_at − 60s` 선제 갱신,
메모리만(디스크 저장 금지). `401 expired-token`/`token-revoked` → 재발급 후 **1회만** 재시도.

**RateLimiter** — 그룹별 토큰버킷. 초기값 요약 문서 §8 (`AUTH 5, ACCOUNT 1, ASSET 5, MARKET_DATA 15,
STOCK 5, ORDER 10, ORDER_HISTORY 5, ORDER_INFO 6`). 응답 헤더 `X-RateLimit-Limit`로 런타임 보정.
`429` → `Retry-After` 우선, 없으면 지수백오프(1→2→4s)+jitter.

**TossClient** — `Authorization` 자동, 계좌 필요 경로만 `X-Tossinvest-Account` 자동. 응답 헤더 `X-Request-Id` 를
호출자에게 노출(감사 성공 경로 기록용). 에러 envelope
(`code·message·data·requestId`)를 **가공 없이** `TossApiError`로 올린다. 숫자는 `Decimal ↔ str`만,
`float` 경유 금지.

**Decimal 직렬화 구현 규칙(실측 근거)** — FastAPI 0.136 은 라우트가 bare `dict` 를 반환하면 `Decimal("70000.10")`
을 `70000.1`(float) 로 내보내고, `response_model`(또는 pydantic 반환 타입 힌트)일 때만 `"70000.10"` 문자열로
내보낸다. 따라서 **`trade_api` 의 모든 라우트는 pydantic 응답 모델을 필수로 선언하고 bare `dict` 반환을 금지**
한다. 이를 라우터 테스트에서 검증한다(응답 JSON 의 금액 필드가 `str` 타입인지).

**OrderGuard** — 순서대로 검사, 하나라도 걸리면 토스 주문 API를 호출하지 않는다.

1. `LIMIT`인데 `price` 없음 → `guard/price-required` / `MARKET`인데 `price` 있음 → `guard/price-forbidden`
2. `quantity` 양의 정수 (KR)
3. KR 호가단위: `price % krx_tick_size(price) == 0` → 아니면 `guard/tick-size` (올바른 단위 동봉)
4. `GET /price-limits` 대비 `lowerLimitPrice ≤ price ≤ upperLimitPrice` → 아니면 `guard/price-out-of-range`
5. 주문금액 산정: `LIMIT` = `price × quantity`, **`MARKET` = `upperLimitPrice × quantity`**(시장가는 상한가까지
   체결 가능 — 보수적 기준). 1건 > `GUARD_MAX_ORDER_KRW` → `guard/max-order-amount`
6. 1일 누적(BUY만): `toss_order_audit` 에서 `kind='create' AND NOT dry_run AND side='BUY' AND http_status=200`
   행의 주문금액 합 + 이번 주문 > `GUARD_MAX_DAILY_KRW` → `guard/max-daily-amount`. 하루 경계 = **KST 자정**
   (`created_at AT TIME ZONE 'Asia/Seoul'`). 취소분은 차감하지 않음. **정정(`kind='modify'`)은 누적에 넣지
   않고 1건 상한(5번)만 재검**한다 — 원주문과 정정을 둘 다 합산하면 이중 집계로 과다 차단되기 때문.
   **이 규칙은 preview 뿐 아니라 `POST /orders`(submit) 에서도 재평가한다** — 미리보기 N개를 TTL 내 연속 제출하면
   preview 시점 합계가 stale 이라 상한을 넘을 수 있다(최종 리뷰 I-2). 결정은 행동 시점에.
7. 매도: `GET /sellable-quantity` 초과 → `guard/sellable-exceeded`
8. 주문금액 ≥ 1억 → `confirmHighValueOrder=true` 강제, ≥ 30억 → 차단(스펙 `422 max-order-amount-exceeded`)
9. `DRY_RUN`: 위 검사를 전부 통과한 뒤 토스 호출 대신 "보낼 본문"을 반환하고 감사로그에 `dry_run=true` 기록

로컬 호가단위 검증은 API 왕복 없이 먼저 걸러주는 편의이며 **최종 판정권은 API**(에러 `data`에 올바른 단위가 옴).

**PreviewStore** — 메모리, TTL 5분. `POST /orders/preview` 가 (a) 가드 전부 실행 (b) **`clientOrderId` 를
이 시점에 생성**(`{yyyymmdd}-{uuid8}`, ≤36자, `[A-Za-z0-9_-]`) 해 본문에 포함 (c) 본문 canonical JSON 의
SHA-256 을 `previewToken` 으로 발급. `POST /orders` 는 `previewToken` 필수 + 본문 해시 일치
(`guard/preview-required`, `guard/preview-mismatch`). 같은 미리보기 재전송 → 같은 `clientOrderId` →
토스 멱등성(10분)으로 중복 주문 차단. TTL 5분 < 멱등 10분. 메모리 저장이라 **서버 재시작 시 토큰이
소멸**한다 — 주문은 `guard/preview-required` 로 막히므로 안전하며, 사용자는 미리보기를 다시 실행하면 된다.

**AuditLog** — `toss_order_audit` append-only. **전송 직전 INSERT(`pending`) → 응답 후 UPDATE.** 타임아웃으로
응답을 못 받아도 "보냈다"는 행이 남는다. 정정·취소·DRY_RUN도 기록.

```sql
CREATE TABLE IF NOT EXISTS toss_order_audit (
  id               BIGSERIAL PRIMARY KEY,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  kind             TEXT NOT NULL,               -- create | modify | cancel
  client_order_id  TEXT,
  symbol           TEXT NOT NULL,
  side             TEXT,                        -- BUY | SELL (cancel 은 NULL 가능)
  order_amount_krw NUMERIC(18, 2),              -- 가드 5 기준 금액
  request_json     JSONB NOT NULL,
  dry_run          BOOLEAN NOT NULL,
  http_status      INTEGER,                     -- NULL = pending(응답 미수신)
  error_code       TEXT,
  request_id       TEXT,                        -- 토스 X-Request-Id
  order_id         TEXT,                        -- 발급/신규 orderId
  response_json    JSONB,
  responded_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_toss_order_audit_day ON toss_order_audit (created_at, side, dry_run);
```

스키마 변경 → 운영규칙 4 (kr_pipeline·kr_test 양쪽 psql 수동 적용).

## 6. 백엔드 API 계약 (`/trade-api`, sync 라우트)

| Method | Path | 토스 호출 | 비고 |
|---|---|---|---|
| GET | `/trade-api/health` | 없음 | `{dryRun, maxOrderKrw, maxDailyKrw, accountSeq|null}` — secret 미노출 |
| GET | `/trade-api/accounts` | `/accounts` | 계좌 헤더 불필요. **`TOSS_ACCOUNT_SEQ` 미설정 상태에서도 동작** — §10 2단계에서 `accountSeq`·`accountType` 확인용. TTL 5분 캐시(`ACCOUNT` 1/s) |
| GET | `/trade-api/holdings` | `/holdings` + `positions` SELECT | `HoldingsOverview` 그대로 + `mismatch[]`: `{symbol, name, tossQty, positionQty|null, kind: missing|qty_diff}`. `positions.quantity` 가 NULL(전량 모델)이면 존재만 확인하고 수량 비교는 생략(`qty_diff` 미판정) |
| GET | `/trade-api/search?q=` | 없음 | 로컬 `stocks` — `delisted_at IS NULL AND is_common` 필터, ticker·name prefix/부분 일치, 최대 20 |
| GET | `/trade-api/quote/{symbol}` | `/prices`, `/orderbook`, `/price-limits`, `/stocks/{symbol}/warnings` | 묶음. 종목명은 로컬 `stocks` |
| GET | `/trade-api/buying-power` | `/buying-power?currency=KRW` | |
| GET | `/trade-api/sellable/{symbol}` | `/sellable-quantity` | |
| POST | `/trade-api/orders/preview` | `/price-limits`, `/sellable-quantity`(SELL), `/commissions` | 가드 전부·`clientOrderId` 생성·`previewToken`. 주문 API 미호출 |
| POST | `/trade-api/orders` | `/orders` (DRY_RUN 시 미호출) | `previewToken` 필수 → **BUY 는 1일 누적 재검(§5 6번)** → 감사 INSERT→전송→UPDATE. 성공 시 `request_id`(X-Request-Id) 기록 |
| POST | `/trade-api/orders/{id}/cancel` | `/orders/{id}/cancel` | 감사 기록. 새 `orderId` 반환 |
| POST | `/trade-api/orders/modify/preview` | `/orders/{id}`(원주문 symbol·side), `/price-limits`, `/commissions` | 정정 미리보기 — 원주문과 합성한 요청으로 가드 실행(1일 누적 재검 제외), `previewToken` 발급. `clientOrderId` 없음 |
| POST | `/trade-api/orders/{id}/modify` | `/orders/{id}/modify` | 미리보기 동일 적용. 스펙상 `orderType` 필수, KR은 `quantity` 필수 |
| GET | `/trade-api/orders?status=OPEN\|CLOSED&cursor=&limit=` | `/orders` | 그대로 전달 |
| GET | `/trade-api/orders/{id}` | `/orders/{id}` | 폴링 대상 |

**미리보기 응답**
`{previewToken, clientOrderId, request, estimate:{amount, amountBasis: "limit"|"upper_limit", commission|null, total},
warnings[], dryRun, expiresAt}`.

**에러 규약** — 두 종류를 구분한다.
- 토스 에러: 토스의 HTTP 상태 그대로 + `{error:{code,message,data,requestId}}` 무가공.
- 자체 가드: `400 {error:{code:"guard/…", message, data}}`. 코드 목록 §5.
- 프론트는 `code` 기반으로 한국어 문구를 매핑(스펙: `message`는 빈 문자열일 수 있음). unknown code는
  `code · message` 그대로 표시.

CORS는 `localhost:5173` 허용(프록시 없이 직접 접근 대비). JSON 본문만 수용.

## 7. 프론트

- `web/vite.config.ts` proxy 에 `"/trade-api": "http://localhost:8001"` 추가. `lib/api.ts` 무변경.
- 라우트 `/trading`, NAV 신규 그룹 **"실행"** 에 "Trading / 매매".
- **상단 상시 배너**: `/health` 30초 폴링 → 노란 "연습 모드 (DRY_RUN)" / 빨간 "실주문 모드".

세 영역(한 페이지):

1. **주문 패널** — 종목 검색(로컬) → 선택 → 현재가·호가·상하한가, 유의사항 있으면 빨간 배너 → 매수/매도,
   지정가/시장가, 수량, 가격(지정가만) → 예상금액(시장가는 "상한가 기준 최대") → `[미리보기]` → 모달(보낼 본문·
   예상금액·경고·모드) → `[주문 전송]`. 매도 시 판매가능수량 표시·초과 시 비활성.
2. **주문 현황** — OPEN 탭(취소·정정, 정정은 같은 미리보기 모달) / CLOSED 탭(커서 페이징 20). OPEN 주문이
   있을 때만 `refetchInterval` 2초, 없으면 폴링 중단. `PARTIAL_FILLED`는 OPEN 탭에만. 정정·취소 후 새
   `orderId` 반영.
3. **보유** — 합산(투자원금·평가금액·손익·일간손익) + 종목표. `mismatch[]` 있으면 경고 배너 "positions 미기입
   N종목" + `/positions` 링크.

숫자는 프론트도 문자열로 송수신. 에러 코드 → 한국어 매핑 테이블(요약 문서 §7 전부 + `guard/*`).

## 8. 검증 규칙 (프론트·백엔드 양쪽)

| 조건 | 규칙 |
|---|---|
| `side`·`orderType`(inbound) | `Literal["BUY","SELL"]`·`Literal["LIMIT","MARKET"]` — unknown 허용은 **토스 응답** 에만, 인바운드 주문은 fail-closed(최종 리뷰 I-1) |
| `LIMIT` | `price` 필수, KR 정수, 호가단위 배수, 상·하한가 범위 |
| `MARKET` | `price` 금지 |
| `quantity` | 양의 정수 |
| `timeInForce` | `DAY` 고정(1차). `OPG`·`CLS` 미노출 |
| 금액 | 1건 ≤ `GUARD_MAX_ORDER_KRW`, 1일 BUY 누적 ≤ `GUARD_MAX_DAILY_KRW`, ≥1억 `confirmHighValueOrder`, ≥30억 차단 |
| 매도 | ≤ `sellableQuantity` |
| `clientOrderId` | ≤36자 `[A-Za-z0-9_-]`, 미리보기 시 생성 |
| 주문 전송 | `previewToken` 필수·본문 일치·TTL 내 |

## 9. 설정 (`.env`, gitignore 됨)

```
TOSS_CLIENT_ID=
TOSS_CLIENT_SECRET=
TOSS_ACCOUNT_SEQ=            # /accounts 로 확인 후 고정 (accountType=BROKERAGE)
TOSS_BASE_URL=https://openapi.tossinvest.com
TOSS_DRY_RUN=true            # 기본 true. 실주문은 명시적으로 false
GUARD_MAX_ORDER_KRW=5000000
GUARD_MAX_DAILY_KRW=10000000
```

`TradeConfig.load()`는 기존 `Config` 와 분리(기존 것은 `DATABASE_URL` 필수 구조). 기동 시 `dry_run`·상한 2개·
`account_seq` 를 로그 1회 출력. `pyproject.toml`: `httpx` 를 dev 그룹 → 런타임 `dependencies` 로 승격.

## 10. 테스트·검증

**격리(#92 동형)** — `tests/conftest.py` 에서 수집 전 `TOSS_CLIENT_ID=""`, `TOSS_CLIENT_SECRET=""`,
`TOSS_DRY_RUN="true"` 강제. 모든 토스 호출은 `httpx.MockTransport` 로 대체. 실제 토스 접촉 테스트는 만들지 않는다.

**단위** — TokenManager(선제 갱신·401 재시도 1회·동시 발급 직렬화) / RateLimiter(버킷·헤더 보정·429) /
OrderGuard(규칙별 표 케이스: price 정합, tick, 상하한, 1건·1일 상한 — MARKET 상한가 기준·dry_run 제외·KST 경계,
1억/30억, sellable) / PreviewStore(해시 일치·TTL·clientOrderId 포함) / AuditLog(전송 예외 시 pending 행 잔존) /
에러 envelope 무가공 통과 / Decimal↔str 왕복에 float 미개입 / **전 라우트 응답의 금액 필드가 JSON 문자열**
(bare dict 반환 회귀 방지).

**라우터** — FastAPI `TestClient` + MockTransport, DB는 kr_test(conftest가 schema.sql 적용).

**영향도 0 확인(머지 전)** — `git diff --stat main` 에서 `api/`·`kr_pipeline/`(schema.sql 제외)·`web/src/lib/api.ts`
변경 0줄, 기존 suite 1458 passed 유지. 하나라도 깨지면 "기존 영향 없음" 주장을 철회한다.

**실물 검증 순서(D6)**

1. 사용자: WTS `설정 > Open API > 허용 IP` 등록. 공인 IP 변경 시 재등록(403 `edge-blocked` 재발 시 첫 확인 항목)
2. 읽기 연결: `GET /trade-api/accounts` → `accountType=BROKERAGE` 계좌의 `accountSeq` 를 `.env` 에 고정 → 재기동 → `/holdings`·`/quote/005930`·`/orders?status=OPEN` 응답 확인
3. DRY_RUN=true 로 주문·정정·취소 전 경로 + UI 완성. 감사로그에 `dry_run=true` 행 확인
4. **실주문 검증(비가역)** — `TOSS_DRY_RUN=false`, 장중, 1주, 현재가 −3% 지정가 BUY → OPEN 확인 →
   **즉시 취소** → CLOSED `CANCELED` 확인 → 감사로그 create·cancel 행 확인. 이 왕복을 통과한 뒤에만 체결되는
   주문 1회 → `FILLED` · `/holdings` 반영 확인 → 종료 후 `TOSS_DRY_RUN=true` 복귀

## 11. 스펙 JSON 대조에서 발견한 요약 문서와의 차이

1. 숫자 필드(`quantity`·`price`·`orderAmount`·`lastPrice`·`averagePurchasePrice` 등)는 전부 `type: string,
   format: decimal`. → Decimal↔str 계약(§5).
2. `OrderModifyRequest.orderType` 이 required.
3. 30억 이상 주문은 `confirmHighValueOrder` 와 무관하게 `422 max-order-amount-exceeded`.
4. 보유 스키마 `HoldingsOverview{totalPurchaseAmount, marketValue, profitLoss, dailyProfitLoss, items[HoldingsItem]}` —
   손익이 계산돼 내려오므로 자체 계산 없음.
5. `ApiError.message` 는 빈 문자열일 수 있음 → `code` 기반 매핑 필수.

## 12. 운영 규칙 추가 (CLAUDE.md)

> 6. **토스 API 호출은 `trade_api` 프로세스만** — `kr_pipeline`·CLI·테스트에서 토스 호출 금지(토큰 1개 제약,
> 위반 시 `401 token-revoked` 로 서로 무효화). `trade_api` 는 `--workers` 금지, `--reload` 기본 미사용.
> 테스트는 conftest 가 `TOSS_CLIENT_ID/SECRET` 를 비우고 `TOSS_DRY_RUN=true` 를 강제한다(#92 동형).

## 13. 기존 시스템 영향

| 접점 | 내용 | 영향 |
|---|---|---|
| `kr_pipeline/db/schema.sql` | 테이블 1개 추가 | 기존 테이블 무변경. 양쪽 DB psql |
| `pyproject.toml` | httpx dev→런타임 | 설치 상태 동일 |
| `tests/conftest.py` | env 격리 3줄 | 기존 코드가 해당 변수 미사용 |
| `web/vite.config.ts`, `App.tsx` | 프록시 1줄, 라우트·NAV 1건 | 기존 라우트 무변경 |
| Postgres | `trade_api` 별도 연결 풀 | 연결 수 증가(기존 max 10 + 신규), 기본 한도 100 내 |
| `positions`·`stocks` | SELECT만 | 무변경 |

`api/`·`kr_pipeline/` 로직 변경 0. `krx_tick_size` 는 import 만.

## 14. 후속 후보 (이번 범위 밖, 이슈 미등록)

- `positions` 수동 기입 버튼(D2 의 다음 단계 — entry_price 규칙 확정 선행)
- WebSocket `personal:order` 릴레이(폴링 경로는 정본으로 유지)
- 조건주문(OCO/OTO) — 자동 매매 붙일 때 폴링 기반 자체 로직보다 우선 검토
- `--reload` 없는 개발 편의(별도 dev 스크립트)
