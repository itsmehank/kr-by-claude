# ChartPage 메타바 + 요일 표시 — 설계

## 목적

ChartPage 의 차트 위에 종목 / 시장 비교 / 주간 거래량을 한 줄로 요약하는 메타바를 추가한다. 차트 hover tooltip 에 요일을 함께 표시한다.

세 정보 모두 매수 결정에 빠르게 참고되는 컨텍스트로, 카드 그리드까지 스크롤하지 않아도 차트 바로 위에서 확인할 수 있어야 한다.

## 비범위

- 사용자가 직접 비교 지수를 고르는 토글. `stocks.market` 기반 자동 매핑만.
- 1주/1달/3달 외 기간 (5년, YTD 등).
- 종목과 지수의 상관계수 / 베타 / α 차트화.
- 메타바의 시각 차트 (sparkline 등).

## 데이터 모델

기존 테이블만 사용. 신규 컬럼/테이블 없음.

- `index_daily` (kr_pipeline/db/schema.sql:28): `index_code`, `date`, `open`, `high`, `low`, `close`, `volume`
- `daily_indicators` (이미 사용): `ticker`, `date`, `adj_close`, `volume`, `avg_volume_50d`
- `stocks` (이미 사용): `ticker`, `name`, `market`, `sector`

## 시장 매핑

| `stocks.market` | `index_code` | 표시명 |
|---|---|---|
| `KOSPI`  | `1001` | KOSPI |
| `KOSDAQ` | `2001` | KOSDAQ |
| 기타     | —      | 비교 생략 |

## API

### `GET /api/index/daily/{index_code}`

**위치**: `api/routers/index.py` (신규)

**경로 파라미터**: `index_code` — `1001` 또는 `2001`.

**쿼리 파라미터**:

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `start` | YYYY-MM-DD | 365 일 전 | 기간 시작 (포함) |
| `end`   | YYYY-MM-DD | 오늘     | 기간 끝 (포함) |

**응답** (배열, date ASC):

```json
[
  { "date": "2026-02-20", "open": 2540.1, "high": 2562.0, "low": 2535.7, "close": 2558.3, "volume": 412345678 }
]
```

빈 결과는 `[]`. 알 수 없는 `index_code` 도 빈 배열로 응답 (404 안 함 — 클라이언트가 단순히 비교를 생략하도록).

### 기존 endpoint 재사용

- `GET /api/stocks/{ticker}` — `market`, `name`, `sector`
- `GET /api/indicators/daily/{ticker}?start=&end=` — 종목 OHLC + 거래량 + `avg_volume_50d`

## 컴포넌트

### `ChartMetaBar.tsx` (신규)

**파일**: `web/src/components/ChartMetaBar.tsx`

**Props**:

```ts
interface Props {
  ticker: string;
  stockName: string | null;
  market: string | null;   // "KOSPI" | "KOSDAQ" | 기타
  sector: string | null;
}
```

**자체 fetch (TanStack Query 2 개)**:

1. **종목**: `/api/indicators/daily/{ticker}?start={today-180d}&end={today}` — 180 달력일 ≈ 130 거래일 (3달 비교 안전 마진)
2. **지수**: `/api/index/daily/{indexCode}?start={today-180d}&end={today}` (market 매핑 시만)

**계산**:

- 종목 / 지수 수익률: 마지막 행 close 대비 N 거래일 전 close 의 % 변화
  - 1주 = `(close[-1] - close[-6]) / close[-6] × 100`  (5 거래일 전)
  - 1달 = N=23 (22 거래일 전)
  - 3달 = N=64 (63 거래일 전)
  - 데이터 부족 시 해당 기간만 `null` → UI 에서 `—` 표시
- 이번주 거래량 합:
  - KST 기준 오늘이 속한 주의 월요일 (`getDay()` 활용; 일요일이면 다음 주 월요일로 처리하지 말고 이전 월요일로)
  - 종목 daily 데이터에서 `date >= 그 주 월요일 AND date <= 마지막 행` 의 `volume` 합
  - 5 거래일 미만이어도 합 (월~목 진행 중일 수 있음)
- 평균 거래량 (SMA50V): 종목 daily 마지막 행의 `avg_volume_50d`
- 이번주 합 vs SMA50 비율: `((week_sum / 5거래일) / sma50v - 1) × 100` — "+27%" 같은 형태로 표시 (주간 일평균 대비 50일 평균)

> **주의**: 이번주가 5 거래일 미만 (수요일이면 3 거래일) 인 경우, "주간 합" 자체는 의미 있지만 SMA50 비교는 "주간 일평균" 으로 정규화해야 동일 척도로 비교 가능. 위 공식이 그것을 반영.

**표시 (한 줄로 압축, 두 행 텍스트)**:

```
{ticker} {stockName}  ·  {market} · {sector}
1주 ±X.X% (시장 ±Y.Y%)    1달 ±X.X% (±Y.Y%)    3달 ±X.X% (±Y.Y%)
이번주 거래량 {weekSumFormatted}  /  SMA50 {sma50Formatted}  ({±Z}%)
```

- 양수: 초록, 음수: 빨강, 0: 회색.
- 거래량 포맷: `1,234,567` 자릿수 (천 단위 컴마) — `toLocaleString()`.
- market 매핑 안 되는 종목: 시장 비교 컬럼 빈 칸 (`1주 ±X.X%` 만, 괄호 안 없음).

**상태**:

- 로딩: 회색 placeholder (`불러오는 중…`)
- 에러: 회색 한 줄 (`정보를 불러오지 못했습니다`) — 차트는 그대로 작동해야 하므로 절대 throw 하지 않음
- 빈 종목 (`!ticker`): 컴포넌트 자체를 렌더하지 않도록 ChartPage 에서 `{ticker && <ChartMetaBar … />}`

### ChartPage 수정

- 종목 선택 시 차트 카드 (line ~388 의 `<div className="bento p-2 mb-5 overflow-hidden">`) 바로 위에 메타바 삽입
- 메타바는 자체 카드 (`bento p-4 mb-3`) 로 감싸 다른 카드와 톤 일치
- 기존 useQuery (stockMeta) 데이터를 메타바에 prop 으로 넘김 (별도 호출 안 함)
- 기타 영역 (토글 / 카드 그리드 / 액션 버튼) 변경 없음

### PriceChart tooltip 의 요일

**파일**: `web/src/components/charts/PriceChart.tsx`

- tooltip 의 `{tooltip.date}` 표시 위치 (line 363 근방) 에서 한국어 요일을 함께 출력
- 변환 helper:

```ts
function withWeekday(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  const wd = ["일", "월", "화", "수", "목", "금", "토"][d.getDay()];
  return `${iso} (${wd})`;
}
```

- tooltip JSX 의 `{tooltip.date}` → `{withWeekday(tooltip.date)}`
- 다른 변경 없음 (스타일, OHLC, 거래량 영역 그대로)

## 컴포넌트 책임 경계

- **ChartMetaBar**: 종목 + 지수 데이터 자체 fetch, 수익률 / 주간 거래량 계산, 한 줄 요약 표시. ChartPage 와는 4 개의 prop 만 공유.
- **ChartPage**: 종목 선택 시 메타바 render — 데이터 흐름 추가 없음.
- **PriceChart**: tooltip 의 date 출력 형식만 변경 — 데이터 흐름 변경 없음.
- **새 index router**: `index_daily` 직접 조회, 필터는 `start/end` 만. 다른 라우터와 독립.

## 테스트

### API
`tests/test_api_index.py` (신규):
- 빈 결과 (`index_code='9999'`)
- 정상 결과 + 컬럼 채워짐
- start/end 필터 동작

### 프런트
- 기존 패턴 (vitest 또는 RTL 없으므로 tsc + 수동)
- 수동 검증: KOSPI / KOSDAQ 종목 각각 / market 이 매핑 안 되는 종목 / 데이터 부족 (신생 종목)

## 작업 분리 (plan task 후보)

1. `GET /api/index/daily/{index_code}` 라우터 + 스키마 + 테스트
2. `ChartMetaBar.tsx` 컴포넌트 (fetch + 계산 + 표시 + 빈 상태)
3. ChartPage 에 메타바 삽입 (1 줄 import + 1 줄 JSX)
4. PriceChart tooltip 요일 추가 (`withWeekday` helper + tooltip 한 줄 수정)

각 task 독립 commit 가능. 1 → 2 → 3 → 4 순서. (2 가 1 의 응답 형식 확정 후 가능; 3, 4 는 독립.)

## 성공 기준

- ChartPage 에서 KOSPI 종목 선택 시 메타바에 KOSPI 지수 대비 1주/1달/3달 % 가 표시된다.
- KOSDAQ 종목은 KOSDAQ 지수 대비 표시.
- 시장이 매핑 안 되는 종목은 시장 컬럼 없이 종목 수익률만 표시.
- 이번주 거래량 합과 SMA50 대비 % 가 표시된다.
- 데이터가 부족한 기간 (예: 신생 종목 3달 데이터 없음) 은 해당 기간만 "—" 로 표시되고 다른 정보는 정상 표시.
- 차트 hover tooltip 의 날짜 옆에 한국어 요일 (월/화/수/목/금/토/일) 이 표시된다.
- 데이터 fetch 실패 시 메타바는 한 줄 회색 메시지로 그레이스풀하게 fallback, 차트 자체는 계속 작동.
