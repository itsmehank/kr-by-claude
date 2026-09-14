# 토스증권 Open API 정리 및 매수 도구 구현 스펙

> 이 문서는 토스증권 Open API 공식 문서를 정리한 것이며, Claude Code CLI가 "원하는 매수를 수행하는 Web UI + 백엔드"를 구현할 때 참조하는 스펙 문서로 쓰입니다.
>
> 작성 기준일: 2026-09-14

---

## 0. 공식 문서 링크

| 종류 | URL | 비고 |
|---|---|---|
| 개발자센터 (사람용) | https://developers.tossinvest.com/docs | 브라우저 인터랙티브 레퍼런스 (JS 렌더링) |
| LLM/AI 에이전트 진입점 | https://developers.tossinvest.com/llms.txt | **Claude Code는 여기서 시작** |
| 개요 문서 (Markdown) | https://openapi.tossinvest.com/openapi-docs/overview.md | 퀵스타트·Rate Limit·에러 모델·웹소켓 가이드 |
| API 레퍼런스 (Markdown) | https://openapi.tossinvest.com/openapi-docs/latest/api-reference/README.md | 엔드포인트·모델 인덱스 |
| **OpenAPI 3.0 JSON (SoT)** | https://openapi.tossinvest.com/openapi-docs/latest/openapi.json | REST 스펙의 단일 진실 소스 |
| **AsyncAPI 3.0 JSON (SoT)** | https://openapi.tossinvest.com/openapi-docs/latest/asyncapi.json | 웹소켓 스펙의 단일 진실 소스 |

**서버 주소**

- REST: `https://openapi.tossinvest.com`
- WebSocket: `wss://openapi-ws.tossinvest.com/ws/v1`

> 구현 시작 전 Claude Code는 위 `openapi.json`을 반드시 직접 받아서 확인할 것. 이 문서는 요약이고, 스펙 변경 시 JSON이 우선입니다.

---

## 1. 30초 요약

- **REST + WebSocket** 두 가지로 제공.
- 인증은 **OAuth 2.0 Client Credentials Grant** 한 가지. refresh token 없음.
- 시세·종목 정보는 토큰만 있으면 호출 가능.
- **계좌 / 자산 / 주문 / 조건주문**은 토큰 + `X-Tossinvest-Account: {accountSeq}` 헤더 필요.
- 성공 응답은 전부 `{ "result": ... }` envelope. 에러는 `{ "error": { code, message, data, requestId } }`.
- 국내(KRX/NXT)와 미국 주식 모두 지원. 미국은 금액 기반 주문(`orderAmount`)·소수점 거래 지원.

### 카테고리

| 카테고리 | 내용 | 계좌 헤더 |
|---|---|---|
| Auth | OAuth2 토큰 발급 | 불필요 |
| Market Data | 현재가, 호가, 체결, 캔들, 상/하한가 | 불필요 |
| Stock Info | 종목 마스터, 매수 유의사항, 수급 동향 | 불필요 |
| Market Info | 환율, 장 운영 캘린더 | 불필요 |
| Ranking / Market Indicators | 랭킹, 지수·국채 | 불필요 |
| Account / Asset | 계좌 목록, 보유 주식 | **필요** |
| Order | 주문 생성·정정·취소, 조회, 매수가능금액 | **필요** |
| Conditional Order | 조건주문 (SINGLE / OCO / OTO) | **필요** |
| WebSocket | 실시간 체결·호가·본인 주문 이벤트 | 구독 선언 시 accountSeq |

---

## 2. 사전 준비 (사람이 직접 해야 하는 일)

1. **클라이언트 등록** — 토스증권 WTS 로그인 → `설정 > Open API` → `client_id`, `client_secret` 발급
2. **허용 IP 등록** — 같은 메뉴 하단 `허용 IP 관리`에서 호출할 IP를 등록. 등록되지 않은 IP는 **403으로 차단**됨 (REST·WebSocket 동일 적용)

> ⚠️ **이게 아키텍처를 결정합니다.**
> - 로컬 개발: 집/회사 공인 IP를 등록해야 함. IP가 바뀌면 다시 등록.
> - 클라우드 배포: **고정 공인 IP(NAT Gateway, Elastic IP 등)가 필수**. 서버리스/오토스케일 환경에서 IP가 유동적이면 사실상 못 씀.
> - 결론: 이 프로젝트는 **고정 IP를 가진 단일 서버(또는 로컬 PC)에서 돌리는 구조**가 가장 현실적입니다.

---

## 3. 인증 (Auth)

### `POST /oauth2/token`

- Content-Type: `application/x-www-form-urlencoded`
- 응답은 envelope 없이 **OAuth2 표준 형식**

**요청**

```bash
curl -s -X POST 'https://openapi.tossinvest.com/oauth2/token' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=client_credentials' \
  -d 'client_id=xxx' \
  -d 'client_secret=yyy'
```

| 파라미터 | 값 |
|---|---|
| `grant_type` | `client_credentials` (고정) |
| `client_id` | 발급받은 클라이언트 ID |
| `client_secret` | 발급받은 시크릿. **서버 측에서만 사용** |

**응답 (`OAuth2TokenResponse`)**

| 필드 | 타입 | 설명 |
|---|---|---|
| `access_token` | String | JWT. 모든 API의 `Authorization: Bearer`에 사용 |
| `token_type` | String | 항상 `Bearer` |
| `expires_in` | Long | 만료까지 남은 초 |

### 🔴 구현상 가장 중요한 제약

> **클라이언트당 유효한 access token은 1개입니다. 재발급하면 이전 토큰이 즉시 무효화됩니다.**

즉:

- 백엔드 인스턴스를 2개 띄우고 각자 토큰을 발급하면 **서로를 계속 로그아웃시킵니다.** (`401 token-revoked`)
- 로컬 CLI 테스트 중에 백엔드가 토큰을 재발급하면 CLI 쪽이 깨집니다.
- 따라서 **토큰 발급·캐시는 단일 지점(single token manager)** 으로 묶어야 합니다.
  - 권장: 백엔드 프로세스 1개 + 프로세스 내 싱글톤 캐시 + `asyncio.Lock`/`synchronized`
  - 다중 인스턴스가 필요하면 Redis에 토큰 저장 + 분산 락으로 재발급 직렬화
- `401 expired-token` / `401 token-revoked` 수신 시 **1회만** 재발급 후 재시도 (무한 루프 방지)
- Rate limit: `AUTH` 그룹 초당 5회

---

## 4. 공통 규격

### 요청 헤더

```
Authorization: Bearer {access_token}
X-Tossinvest-Account: {accountSeq}    # 계좌·자산·주문·조건주문 카테고리만
Content-Type: application/json        # POST 본문이 있을 때
```

### 성공 응답 envelope

```json
{ "result": { /* 엔드포인트별 payload */ } }
```

### 에러 응답 envelope

```json
{
  "error": {
    "requestId": "01HXYZABCDEFG123456789",
    "code": "invalid-request",
    "message": "주문 방향이 올바르지 않습니다.",
    "data": { "field": "side", "allowedValues": ["BUY", "SELL"] }
  }
}
```

- `requestId` = 응답 헤더 `X-Request-Id`. CS 문의 시 첨부 권장. 누락 시 `referenceId` 또는 `x-amz-cf-id` 사용.
- `data`는 에러 해결 힌트. 코드별로 키 구조가 다름 (예: 호가 단위 오류 시 올바른 단위가 들어옴) → **백엔드는 `data`를 그대로 프론트로 전달**해서 UI가 사용자에게 안내할 수 있게 할 것.

---

## 5. 엔드포인트 전체 목록

### 시세 (Market Data) — 토큰만 필요

| Method | Path | 설명 | Rate Limit Group |
|---|---|---|---|
| GET | `/api/v1/prices?symbols=` | 현재가 (콤마 구분 최대 200건) | `MARKET_DATA` (15/s) |
| GET | `/api/v1/orderbook?symbol=` | 호가 및 잔량 | `MARKET_DATA` |
| GET | `/api/v1/trades?symbol=&count=` | 당일 최근 체결 (최대 50) | `MARKET_DATA` |
| GET | `/api/v1/price-limits?symbol=` | 당일 상/하한가 | `MARKET_DATA` |
| GET | `/api/v1/candles?symbol=&interval=&count=&before=&adjusted=` | 캔들 OHLCV. `interval`=`1m`/`1d`, 최대 200봉, 최신순 정렬 | `MARKET_DATA_CHART` (20/s) |

### 종목 정보 (Stock Info)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/v1/stocks?symbols=` | 종목 기본 정보 (종목명, 시장, 통화, 상장 상태, 발행주식수) |
| GET | `/api/v1/stocks/all` | 마켓별 전체 종목 (`STOCK_ALL`, 1/s) |
| GET | `/api/v1/stocks/{symbol}/warnings` | **매수 유의사항** (정리매매, 단기과열, 투자경고/위험, VI 발동, 신주인수권) |
| GET | `/api/v1/stocks/{symbol}/investor-trading` | 투자자별 매매동향 (국내) |
| GET | `/api/v1/stocks/{symbol}/program-trades` | 프로그램매매 (국내) |
| GET | `/api/v1/stocks/{symbol}/short-selling` | 공매도 동향 (국내) |
| GET | `/api/v1/stocks/{symbol}/credit-trades` | 신용거래 동향 (국내) |
| GET | `/api/v1/stocks/{symbol}/securities-lending` | 대차거래 동향 (국내) |

### 시장 정보 / 랭킹 / 지표

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/v1/exchange-rate` | KRW↔USD 환율 |
| GET | `/api/v1/market-calendar/KR` | 국내 장 운영 (KRX·NXT 세션별) |
| GET | `/api/v1/market-calendar/US` | 미국 장 운영 (데이/프리/정규/애프터) |
| GET | `/api/v1/rankings` | 거래대금·거래량·등락률 랭킹 |
| GET | `/api/v1/market-indicators/prices` | 국내 지수·국채 현재가 |
| GET | `/api/v1/market-indicators/{symbol}/candles` | 지표 캔들 |
| GET | `/api/v1/market-indicators/{symbol}/investor-trading` | 투자자별 매매대금 (`KOSPI`·`KOSDAQ`만) |

### 계좌 · 자산 — 계좌 헤더 필요

| Method | Path | 설명 | Rate Limit |
|---|---|---|---|
| GET | `/api/v1/accounts` | 계좌 목록 | `ACCOUNT` (1/s) |
| GET | `/api/v1/holdings` | 보유 주식 (종목별 상세 + 평가금액·손익 합산) | `ASSET` (5/s) |

### 주문 — 계좌 헤더 필요

| Method | Path | 설명 | Rate Limit |
|---|---|---|---|
| POST | `/api/v1/orders` | **주문 생성** | `ORDER` (10/s) |
| POST | `/api/v1/orders/{orderId}/modify` | 주문 정정 | `ORDER` |
| POST | `/api/v1/orders/{orderId}/cancel` | 주문 취소 | `ORDER` |
| GET | `/api/v1/orders?status=OPEN\|CLOSED` | 주문 목록 | `ORDER_HISTORY` (5/s) |
| GET | `/api/v1/orders/{orderId}` | 주문 상세 (모든 상태) | `ORDER_HISTORY` |
| GET | `/api/v1/buying-power?currency=KRW\|USD` | 매수 가능 금액 | `ORDER_INFO` (6/s, 09:00~09:10은 3/s) |
| GET | `/api/v1/sellable-quantity?symbol=` | 판매 가능 수량 | `ORDER_INFO` |
| GET | `/api/v1/commissions` | 시장별 매매 수수료율 | `ORDER_INFO` |

### 조건주문 — 계좌 헤더 필요

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/v1/conditional-orders` | 조건주문 등록 (`SINGLE`·`OCO`·`OTO`) |
| POST | `/api/v1/conditional-orders/{id}/modify` | 수정 |
| DELETE | `/api/v1/conditional-orders/{id}` | 취소 |
| GET | `/api/v1/conditional-orders?status=OPEN\|CLOSED` | 목록 |
| GET | `/api/v1/conditional-orders/{id}` | 상세 |

> OCO·OTO는 **종목당 1개**만 등록 가능 (SINGLE은 제한 없음). 중복 시 `422 duplicate-conditional-order`.

---

## 6. 매수 핵심: `POST /api/v1/orders`

### 6.1 요청 스키마

`OrderCreateRequest`는 **수량 기반(`quantity`)** 과 **금액 기반(`orderAmount`)** 의 oneOf입니다. 둘 중 **정확히 하나만** 보내야 합니다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `symbol` | String | ✅ | KRX: 6자리 종목코드 (숫자 또는 영문+숫자, 예 `005930`, `0101N0`) / US: 티커 (`AAPL`). 허용 문자: 영문 대소문자, 숫자, `.`, `-` |
| `side` | String | ✅ | `BUY` \| `SELL` |
| `orderType` | String | ✅ | `LIMIT` (지정가) \| `MARKET` (시장가) |
| `quantity` | BigDecimal | 조건부 | 주문 수량(주). 기본 **양의 정수만**. 소수점은 US 시장가 매도만 허용 |
| `orderAmount` | BigDecimal | 조건부 | 주문 금액(USD). **US + `MARKET` 전용**. 수량이 시장가에 따라 결정됨 |
| `price` | BigDecimal | 조건부 | `LIMIT`일 때 **필수**, `MARKET`일 때 **전달 금지** |
| `timeInForce` | String | ❌ | 기본 `DAY`. `CLS`(장마감, US+LIMIT만), `OPG`(장개시 시가단일가, 국내 전용) |
| `clientOrderId` | String | ❌ | **멱등성 키**. 최대 36자, 영숫자 + `-`, `_`. 10분간 유효 |
| `confirmHighValueOrder` | Boolean | ❌ | 기본 `false`. **1억원 이상 주문 시 `true` 필수** |

### 6.2 `price` 규칙 (매수 시 가장 많이 터지는 부분)

- **KR**: 정수(원). 호가 단위에 맞아야 함. 예) 50,000~200,000원 구간은 100원 단위.
  - 안 맞으면 `400 invalid-request` + `data`에 올바른 호가 단위가 포함됨
- **US**: 소수점(달러)
  - $1 미만 → 소수점 4자리까지 (이하 절삭)
  - $1 이상 → 소수점 2자리까지 (이하 절삭)

### 6.3 소수점 / 금액 주문 시간 제약

- `orderAmount` 주문, 소수점 `quantity` 주문은 **정규장 시작 ~ 정규장 종료 1시간 전**까지만 접수
- 그 외 시간: `422 amount-order-outside-regular-hours` / `422 fractional-quantity-outside-regular-hours`
- 소수점 수량은 6자리까지. 초과 시 `400 invalid-request` (`fractional-quantity-scale-exceeded`)

### 6.4 응답

```json
{ "result": { "orderId": "ord_xxxxxxxxxxxx" } }
```

- `orderId`는 서버 발급 opaque token
- **정정/취소 시 새 `orderId`가 발급됩니다** (원주문 ID와 다름) → 프론트는 정정 후 ID를 갱신해야 함

### 6.5 요청 예시

**국내 지정가 매수 (삼성전자 10주 @ 70,000원)**

```bash
curl -s -X POST 'https://openapi.tossinvest.com/api/v1/orders' \
  -H 'Authorization: Bearer eyJhbGciOi...' \
  -H 'X-Tossinvest-Account: 1' \
  -H 'Content-Type: application/json' \
  -d '{
    "clientOrderId": "ui-20260914-001",
    "symbol": "005930",
    "side": "BUY",
    "orderType": "LIMIT",
    "quantity": 10,
    "price": 70000,
    "timeInForce": "DAY"
  }'
```

**국내 시장가 매수** — `price` 넣지 말 것

```json
{
  "clientOrderId": "ui-20260914-002",
  "symbol": "005930",
  "side": "BUY",
  "orderType": "MARKET",
  "quantity": 10
}
```

**미국 금액 기반 시장가 매수 ($500어치 AAPL)**

```json
{
  "clientOrderId": "ui-20260914-003",
  "symbol": "AAPL",
  "side": "BUY",
  "orderType": "MARKET",
  "orderAmount": 500
}
```

### 6.6 정정 · 취소

**정정** `POST /api/v1/orders/{orderId}/modify`

- **KR**: `quantity` 필수 (양의 정수)
- **US**: `quantity` 전달 불가. 가격만 변경. 전달 시 `400 us-modify-quantity-not-supported`

**취소** `POST /api/v1/orders/{orderId}/cancel` — 본문은 optional. 이미 체결된 주문은 취소 불가.

### 6.7 주문 조회

`GET /api/v1/orders?status=OPEN|CLOSED`

| 필터 값 | 포함되는 `orders[].status` |
|---|---|
| `OPEN` | `PENDING`, `PARTIAL_FILLED`, `PENDING_CANCEL`, `PENDING_REPLACE` |
| `CLOSED` | `FILLED`, `CANCELED`, `REJECTED`, `REPLACED`, `CANCEL_REJECTED`, `REPLACE_REJECTED`, `PARTIAL_FILLED` |

- `status`는 **그룹 라벨**이고 `orders[].status`는 세부 상태 — **값 체계가 다릅니다.**
- `PARTIAL_FILLED`는 양쪽에 모두 등장 → 프론트에서 중복 표시 주의
- 페이징: `OPEN`은 전량 반환 (`limit`/`cursor` 무시, `from`/`to`만 적용) / `CLOSED`는 `limit`(기본 20, 최대 100)·`cursor` 적용
- **Open API로 주문할 수 없는 호가 유형**(시간외단일가, 장후/장전 시간외 종가 등)의 주문은 조회 결과에 **나타나지 않습니다** → "토스 앱에서 낸 주문이 안 보인다"는 것은 버그가 아닐 수 있음

**`Order` 모델**

| 필드 | 설명 |
|---|---|
| `orderId` | 주문 식별자 |
| `symbol`, `side`, `orderType`, `timeInForce` | 주문 조건 (**unknown code 허용하도록 구현할 것**) |
| `status` | 세부 상태 |
| `price` | 주문 가격. `MARKET`이면 null |
| `quantity` | 주문 수량 |
| `orderAmount` | 금액 기반 US 시장가 매수만. 그 외 null |
| `currency` | `KRW` \| `USD` |
| `orderedAt` / `canceledAt` | ISO 8601, KST |
| `execution` | 체결 결과. 미체결이면 `filledQuantity=0` |

### 6.8 매수 전 확인용 API

| API | 응답 필드 |
|---|---|
| `GET /api/v1/buying-power?currency=KRW` | `currency`, `cashBuyingPower` (미수 미발생 기준 현금 매수가능금액) |
| `GET /api/v1/prices?symbols=005930` | `symbol`, `timestamp`, `lastPrice`, `currency` |
| `GET /api/v1/price-limits?symbol=005930` | 당일 상/하한가 |
| `GET /api/v1/stocks/{symbol}/warnings` | 정리매매·과열·투자경고·VI 등 |
| `GET /api/v1/accounts` | `accountNo`, `accountSeq`, `accountType` |

**`Account.accountType`** — 현재 주문 가능한 것은 `BROKERAGE`(종합매매)뿐. `OVERSEAS_DERIVATIVES`, `PENSION_SAVINGS`, `RESHORING_INVESTMENT`(RIA)는 `422 account-restricted`가 날 수 있음. unknown enum 허용 구현 필요.

---

## 7. 에러 코드 (매수 플로우 관련 발췌)

### 인증·권한

| HTTP | code | 의미 | 대응 |
|---|---|---|---|
| 401 | `invalid-token` | 토큰 무효/형식 오류 | 재발급 |
| 401 | `expired-token` | 만료 | 재발급 후 1회 재시도 |
| 401 | `token-revoked` | 다른 곳에서 재발급되어 무효화 | **토큰 매니저 단일화 확인** |
| 401 | `edge-blocked` | `Authorization` 헤더 누락 | 헤더 확인 |
| 403 | `edge-blocked` / `forbidden` | 허용 IP 미등록 / 권한 부족 | WTS에서 IP 등록 |

### 요청 검증

| HTTP | code | 의미 |
|---|---|---|
| 400 | `invalid-request` | 호가유형·방향·수량·가격·필수 파라미터 오류 (호가 단위 불일치 포함) |
| 400 | `confirm-high-value-required` | 1억원 이상인데 `confirmHighValueOrder != true` |
| 400 | `account-header-required` | `X-Tossinvest-Account` 누락 |
| 400 | `us-modify-quantity-not-supported` | US 주문 정정에 `quantity` 전달 |
| 415 | `unsupported-content-type` | 본문은 `application/json` 사용 |

### 상태 충돌

| HTTP | code | 의미 |
|---|---|---|
| 409 | `request-in-progress` | 동일 `clientOrderId` 주문 처리 중 |
| 409 | `already-filled` / `already-canceled` / `already-modified` / `already-rejected` | 정정·취소 대상이 이미 종료 |
| 409 | `already-processing` | 동일 주문에 정정/취소가 이미 진행 중 |
| 409 | `opposite-pending-order-exists` | **같은 종목에 반대 방향 대기 주문 존재** |

### 주문 실행 불가

| HTTP | code | 의미 |
|---|---|---|
| 422 | `insufficient-buying-power` | 매수 가능 금액 부족 |
| 422 | `order-hours-closed` | 현재 주문 접수 불가 시간 |
| 422 | `stock-restricted` | 종목 거래 제한 |
| 422 | `price-out-of-range` | 상/하한가 초과 |
| 422 | `order-type-not-allowed` | 현재 사용 불가한 호가 유형 |
| 422 | `prerequisite-required` | 약관 동의·교육 이수·위험 고지 미충족 |
| 422 | `market-not-supported-for-stock` | 해당 종목 거래 불가 시장 (KR) |
| 422 | `investor-exchange-not-integrated` | 투자자지시 거래소가 통합(SOR)이 아님 (KR) |
| 422 | `amount-order-outside-regular-hours` | 금액 주문은 정규장만 (US) |
| 422 | `order-limit-exceeded` | 주문 설정 한도 초과 |
| 422 | `idempotency-key-conflict` | 같은 `clientOrderId`로 **내용이 다른** 주문 재요청 |
| 422 | `account-restricted` | 계좌 유형이 해당 주문 불허 |
| 404 | `stock-not-found` / `account-not-found` / `order-not-found` | 대상 없음 |
| 429 | `rate-limit-exceeded` / `edge-rate-limit-exceeded` | TPS 초과 |
| 500 | `internal-error` / `maintenance` | 서버 장애 / 점검 |

---

## 8. Rate Limits

**클라이언트 × API 그룹** 단위로 초당 요청 수(TPS) 제한.

| Group | 한도 | 피크시간 |
|---|---|---|
| `AUTH` | 5/s | — |
| `ACCOUNT` | 1/s | — |
| `ASSET` | 5/s | — |
| `STOCK` | 5/s | — |
| `STOCK_ALL` | 1/s | — |
| `STOCK_TRADING_TREND` | 10/s | — |
| `MARKET_INFO` | 3/s | — |
| `MARKET_DATA` | 15/s | — |
| `MARKET_DATA_CHART` | 20/s | — |
| `RANKING` | 5/s | — |
| `MARKET_INDICATOR_PRICE` | 10/s | — |
| `MARKET_INDICATOR` | 10/s | — |
| `MARKET_INDICATOR_CHART` | 5/s | — |
| `ORDER` | 10/s | 09:00~09:10 KST: 10/s |
| `ORDER_HISTORY` | 5/s | — |
| `ORDER_INFO` | 6/s | 09:00~09:10 KST: **3/s** |
| `CONDITIONAL_ORDER` | 5/s | — |
| `CONDITIONAL_ORDER_HISTORY` | 10/s | — |

> 한도는 사전 공지 없이 조정될 수 있음. 실제 값은 응답 헤더로 확인.

**응답 헤더** (정상·429 모두 포함)

| 헤더 | 의미 |
|---|---|
| `X-RateLimit-Limit` | 현재 허용 초당 요청 수 (burst capacity) |
| `X-RateLimit-Remaining` | 남은 토큰 수 (429 시 0) |
| `X-RateLimit-Reset` | 토큰 1개 재충전까지 예상 초 |
| `Retry-After` | 재시도 권장 초 (429에만) |

**권장 대응**

- 429 → `Retry-After`만큼 대기 후 재시도
- 지수 백오프(1s → 2s → 4s) + jitter
- `X-RateLimit-Remaining`이 낮아지면 선제적으로 속도 완화
- `ACCOUNT`(1/s)와 `STOCK_ALL`(1/s)은 특히 낮음 → **계좌 목록과 전체 종목은 반드시 캐싱**

---

## 9. WebSocket (실시간)

엔드포인트는 `wss://openapi-ws.tossinvest.com/ws/v1` 하나. 핸드셰이크에 REST와 동일한 `Authorization: Bearer` 헤더. **TLS 필수.**

### 구독 채널

| 기능 | `type` | 설명 |
|---|---|---|
| 실시간 체결 | `trade:{market}` | 체결가·체결량 푸시 |
| 실시간 호가 | `orderbook:{market}` | 매도/매수 호가 푸시 |
| 실시간 주문 | `personal:order` | 본인 계좌 주문 이벤트 |

`{market}`: `kr`(국내, KRX+NXT 통합 시세만) / `us`(미국)

### 선언형(declarative) 구독 — full-replace

연결 후 **JSON 배열 1개**를 보냄. **이 배열이 현재 구독 전체**이며 새 배열이 기존 구독을 전부 대체합니다. 빠진 항목은 자동 해제, `[]`는 전체 해제.

```json
[
  {"id": "req-1"},
  {"type": "trade:us", "codes": ["AAPL"]},
  {"type": "orderbook:kr", "codes": ["005930"]},
  {"type": "personal:order", "codes": ["3"]}
]
```

수신 프레임의 `topic`은 `type` + `codes` 원소를 `:`로 이은 값 → `trade:us:AAPL`, `personal:order:3`

### 수신 프레임

| `type` | 형태 | 의미 |
|---|---|---|
| `subscriptions` | `{"type":"subscriptions","id":"req-1","subscribed":[...],"rejected":[...]}` | 선언 결과 ack |
| `message` | `{"type":"message","topic":"...","data":{...}}` | 실시간 데이터 |
| `error` | `{"type":"error","error":{"code":"...","message":"..."},"id":"req-1"}` | 선언 전체 실패 또는 `server-shutdown` |
| `pong` | `{"type":"pong"}` | keepalive 응답 |

### Keepalive

- **클라이언트로부터의 수신이 180초간 없으면 서버가 연결을 종료**
- **서버가 보내는 데이터는 이 타이머를 리셋하지 않음** → 데이터 받는 중에도 `PING` 필요
- **60초 간격 권장.** 웹소켓 표준 ping/pong 프레임도 지원

### 전달 보장

| 채널 | 보장 | 의미 |
|---|---|---|
| `trade`, `orderbook` | **LOSSY** | 수신이 밀리면 중간 프레임 유실 가능. sequence 미제공 |
| `personal:order` | **LOSSLESS** | backlog 유지. 단, 수신이 2초 이상 막히면 연결 종료 |

> LOSSLESS는 **연결 세션 내에서만** 보장. 끊긴 구간의 이벤트는 재전달되지 않으므로, **재연결 후 반드시 `GET /api/v1/orders`로 주문 상태를 재동기화**할 것.

### WebSocket 한도

| 항목 | 한도 | 초과 시 |
|---|---|---|
| 동시 연결 | **계정당 2개** | 새 연결 수락 + 가장 오래된 연결 종료 |
| 연결당 구독 수 | **100건** (`codes` 합산, accountSeq 포함) | `too-many-topics` |
| 선언 빈도 | **5회/초** | `rate-limit-exceeded` (약 1초 대기 후 재선언. `Retry-After` 없음) |

> 동시 연결 2개 제한 때문에, 백엔드가 WS를 쓰는 중에 로컬에서 테스트 스크립트를 2개 더 붙이면 **백엔드 연결이 끊깁니다.**

### 핸드셰이크 에러

| HTTP | 원인 | 대응 |
|---|---|---|
| 401 | 토큰 없음/무효/만료 | 재발급 후 재연결 |
| 403 | 허용 IP 미등록 | WTS에서 IP 등록 |
| 503 | 서버 내부 오류 | 백오프 후 재시도 |

### 구독 거부 코드

| 위치 | code | 의미 |
|---|---|---|
| `error.code` | `wrong-format` | JSON 파싱 실패 / 배열 아님 / 원소가 객체 아님 |
| `error.code` | `no-type`, `invalid-type`, `no-codes` | 필드 누락·미지원 |
| `error.code` | `too-many-topics`, `too-many` | 100건 초과 |
| `error.code` | `rate-limit-exceeded` | 선언 5회/초 초과 |
| `error.code` | `server-shutdown` | 서버 배포. 프레임 직후 연결 종료 → 재연결·재선언 |
| `rejected[].code` | `stock-not-found` | 종목 마스터에 없는 symbol (나머지는 정상 구독) |
| `rejected[].code` | `symbol-market-mismatch` | 선언 마켓과 종목 마켓 불일치 |
| `rejected[].code` | `account-not-found` | `personal:order`의 accountSeq가 본인 계좌 아님 |

> `rejected[]` 항목은 원인 수정 전까지 재선언마다 계속 거부됩니다. full-replace 특성상 재연결마다 반복되므로 **거부 항목은 선언 목록에서 제거**할 것.

---

## 10. 구현 스펙: 매수 Web UI + 백엔드

### 10.1 ⚠️ 이 프로젝트의 전제

> **토스증권 Open API에는 샌드박스/모의투자 환경이 문서에 명시되어 있지 않습니다.
> 즉, `POST /api/v1/orders`는 실제 계좌에 실제 주문을 냅니다.**

따라서 다음을 **기능 요구사항**으로 취급합니다.

1. **`DRY_RUN` 모드가 기본값.** 환경변수 `TOSS_DRY_RUN=true`일 때 주문 API는 호출하지 않고 "보낼 요청 본문"만 반환
2. **주문 전 2단계 확인.** UI에서 "미리보기 → 확인" 없이는 주문 전송 불가
3. **1일 주문 금액 상한 / 1건 최대 금액**을 서버 설정으로 강제 (API 한도와 별개로 자체 가드)
4. **모든 주문 요청·응답을 로컬 파일 또는 DB에 append-only 감사 로그로 기록** (요청 본문, `clientOrderId`, `requestId`, 응답 상태)
5. `client_secret`은 **절대 프론트로 내려가지 않음.** 프론트는 자체 백엔드만 호출

### 10.2 아키텍처

```
[React SPA]  ──(자체 인증)──>  [백엔드 (단일 인스턴스)]  ──(Bearer + Account 헤더)──>  [openapi.tossinvest.com]
                                        │
                                        ├─ TokenManager (싱글톤, 락, 만료 60s 전 갱신)
                                        ├─ RateLimiter (그룹별 토큰버킷)
                                        ├─ OrderGuard (금액 상한, DRY_RUN, 2단계 확인)
                                        ├─ AuditLog (append-only)
                                        └─ WS Relay (선택) ──> wss://openapi-ws.tossinvest.com
                                                  │
                                        [React] <─ SSE/WS ─┘
```

**스택 권장** (교체 가능)

- 백엔드: FastAPI + httpx (async) + SQLite(감사 로그) — 단일 프로세스로 토큰/WS 연결 제약을 자연스럽게 만족
- 프론트: React + Vite + TanStack Query
- 배포: 고정 공인 IP 서버 1대 또는 로컬 실행 (허용 IP 제약 때문)

### 10.3 백엔드 내부 컴포넌트

**TokenManager**
- `access_token`, `expires_at` 캐시
- 만료 **60초 전** 선제 갱신
- 발급은 `Lock`으로 직렬화 (동시 요청이 여러 번 발급하면 서로 무효화)
- 프로세스는 **1개만** 띄운다. 다중 인스턴스 필요 시 Redis + 분산 락

**RateLimiter**
- API 그룹별 토큰 버킷. 초기값은 §8 표 사용
- 응답 헤더 `X-RateLimit-Limit`을 읽어 **런타임에 버킷 용량 보정**
- 429 시 `Retry-After` 우선, 없으면 지수 백오프 + jitter

**TossClient**
- 모든 요청에 `Authorization` 자동 부착
- 계좌 필요 API는 `X-Tossinvest-Account` 자동 부착
- `401 expired-token`/`token-revoked` → 재발급 후 **1회만** 재시도
- 에러 응답의 `error.code` / `error.data` / `requestId`를 **가공하지 않고 그대로** 상위로 전달

**OrderGuard** (자체 안전장치)
- `DRY_RUN` 체크
- 1건 최대 금액 / 1일 누적 금액 상한
- `orderType=LIMIT`인데 `price` 없음, `MARKET`인데 `price` 있음 → 사전 차단
- KR 호가 단위 사전 검증 (실패 시 API에 안 보내고 UI에 안내)
- `price-limits` 대비 주문가 범위 검증
- `clientOrderId` 자동 생성 (예: `{yyyymmdd}-{uuid8}`, 36자 이내, 영숫자+`-_`만)

### 10.4 백엔드 API 설계 (프론트용)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/accounts` | 계좌 목록 (캐시, TTL 5분 — `ACCOUNT` 1/s 때문) |
| GET | `/api/search?q=` | 종목 검색 (`/stocks/all` 캐시 기반 로컬 검색) |
| GET | `/api/quote/{symbol}` | 현재가 + 호가 + 상/하한가 + 유의사항 묶음 |
| GET | `/api/buying-power?currency=` | 매수 가능 금액 |
| GET | `/api/holdings` | 보유 주식 |
| **POST** | **`/api/orders/preview`** | 주문 미리보기. 검증 + 예상 체결금액·수수료 계산. **API 호출 없음** |
| **POST** | **`/api/orders`** | 실제 주문. body에 `previewToken` 필수 (미리보기 없이 주문 불가) |
| POST | `/api/orders/{orderId}/cancel` | 취소 |
| POST | `/api/orders/{orderId}/modify` | 정정 |
| GET | `/api/orders?status=OPEN\|CLOSED` | 주문 목록 |
| GET | `/api/events` | SSE — 실시간 체결/주문 이벤트 릴레이 |

### 10.5 프론트 화면

**1) 매수 화면 (메인)**

- 종목 검색 → 선택
- 현재가 / 호가 10단 / 상·하한가 표시
- 매수 가능 금액 표시
- 입력: `orderType`(지정가·시장가), `quantity` 또는 `orderAmount`(US만), `price`(지정가만), `timeInForce`
- 실시간 계산: 예상 주문금액 = `price × quantity`, 수수료(`/commissions`), 총 필요 금액
- **유의사항 배너** — `/stocks/{symbol}/warnings`에 값이 있으면 빨간 배너로 강조
- 하단: `[미리보기]` → 모달에 요청 본문·예상 금액·경고 표시 → `[주문 전송]`
- `DRY_RUN`이면 화면 상단에 항상 노란 띠로 `모의 모드` 표시

**2) 주문 현황**

- `OPEN` 탭: 대기 주문 목록 + 정정/취소 버튼
- `CLOSED` 탭: 커서 페이징 (기본 20)
- `PARTIAL_FILLED`가 양쪽에 모두 나오므로 `OPEN` 탭에서만 진행 중으로 표시
- SSE로 `personal:order` 이벤트 수신 시 해당 행 갱신
- **재연결 시 `GET /api/orders?status=OPEN` 전량 재조회로 재동기화**

**3) 보유 자산**

- `/holdings` 기반 종목별 손익 + 합산 평가

### 10.6 검증 규칙 (프론트·백엔드 양쪽에 구현)

| 조건 | 규칙 |
|---|---|
| `quantity` vs `orderAmount` | 정확히 하나만 |
| `orderType=LIMIT` | `price` 필수 |
| `orderType=MARKET` | `price` 금지 |
| `orderAmount` | US + `MARKET` + `BUY`만 |
| 소수점 `quantity` | US + `MARKET` + `SELL`만, 6자리까지 |
| KR `price` | 정수, 호가 단위 배수 |
| US `price` | $1 미만 4자리 / $1 이상 2자리 (절삭) |
| 주문금액 ≥ 1억원 | `confirmHighValueOrder=true` 필수 + UI 추가 확인 |
| `timeInForce=CLS` | US + `LIMIT`만 |
| `timeInForce=OPG` | KR 전용 |
| `clientOrderId` | ≤36자, `[A-Za-z0-9_-]`만 |
| 같은 종목 반대방향 대기주문 | 사전 경고 (`opposite-pending-order-exists` 예방) |

### 10.7 환경변수

```env
TOSS_CLIENT_ID=
TOSS_CLIENT_SECRET=
TOSS_ACCOUNT_SEQ=            # /accounts 로 확인 후 고정
TOSS_BASE_URL=https://openapi.tossinvest.com
TOSS_WS_URL=wss://openapi-ws.tossinvest.com/ws/v1

TOSS_DRY_RUN=true            # 기본 true. 실주문은 명시적으로 false
GUARD_MAX_ORDER_KRW=1000000  # 1건 최대
GUARD_MAX_DAILY_KRW=5000000  # 1일 누적
AUDIT_LOG_PATH=./data/audit.log
```

`.env`는 `.gitignore`에 포함. 시크릿은 커밋 금지.

### 10.8 Claude Code에게 주는 지시사항

1. 작업 시작 전 `https://openapi.tossinvest.com/openapi-docs/latest/openapi.json`과 `asyncapi.json`을 받아서 `docs/` 에 저장하고, 이 문서와 **차이가 있으면 JSON을 따를 것**
2. 응답 모델은 OpenAPI JSON에서 생성하거나 직접 타이핑할 것. enum은 **unknown 값을 허용**하도록 (`orderType`, `timeInForce`, `accountType`, `status` 모두 문서에 명시된 요구사항)
3. `POST /api/v1/orders` 실호출 코드는 `DRY_RUN` 가드 안쪽에만 둘 것
4. 테스트는 시세·계좌·주문조회 등 **읽기 전용 API로만** 수행. 주문 생성 테스트는 mock으로
5. 백엔드 프로세스는 반드시 단일 인스턴스. 워커 여러 개(`uvicorn --workers 2` 등) 금지 — 토큰 1개 제약 위반
6. WebSocket 연결은 백엔드에서 **1개만** 유지 (계정당 2개 제한)
7. 모든 에러는 `error.code`를 그대로 프론트에 전달하고, UI는 §7 표를 매핑해 한국어 안내 문구를 보여줄 것

---

## 11. 구현 체크리스트

- [ ] WTS에서 `client_id`/`client_secret` 발급
- [ ] 허용 IP 등록 (배포 대상 서버 고정 IP 확인)
- [ ] `GET /api/v1/accounts`로 `accountSeq` 확인 → `.env`에 고정
- [ ] TokenManager 싱글톤 + 락 + 만료 60초 전 갱신
- [ ] 그룹별 RateLimiter + `X-RateLimit-Limit` 런타임 보정
- [ ] `401` 재발급 후 1회 재시도 로직
- [ ] `/stocks/all`, `/accounts` 캐싱 (1/s 그룹)
- [ ] OrderGuard: DRY_RUN, 금액 상한, 호가 단위·상하한가 사전 검증
- [ ] `clientOrderId` 자동 생성 + 멱등성 재시도 처리
- [ ] 감사 로그 append-only
- [ ] 주문 미리보기 → 확인 2단계 UI
- [ ] `OPEN`/`CLOSED` 주문 목록 + 커서 페이징
- [ ] WS 단일 연결 + 60초 PING + 재연결 후 주문 재동기화
- [ ] 에러 코드 → 한국어 안내 매핑 테이블
- [ ] `.env` gitignore 확인

---

## 12. 알아둘 점

- **모의투자 환경이 문서에 없습니다.** 실주문이 전제이므로 DRY_RUN 가드를 반드시 먼저 만들고 나서 주문 코드를 작성하세요.
- **허용 IP 제약**이 배포 방식을 사실상 결정합니다. 고정 IP가 없으면 이 서비스는 로컬 전용이 됩니다.
- **토큰 1개 / WS 연결 2개 제약**은 흔한 실수 지점입니다. 백엔드를 여러 워커로 띄우거나 테스트 스크립트를 동시에 돌리면 원인 찾기 어려운 401/연결 끊김이 발생합니다.
- 이 문서는 요약입니다. 필드 단위 정확성이 필요한 순간에는 항상 `openapi.json`을 확인하세요.
- 자동 매매 로직을 붙일 계획이라면, 조건주문 API(`/conditional-orders`)를 직접 쓰는 편이 폴링 기반 자체 로직보다 안전하고 Rate Limit에도 유리합니다.
