# 차트 페이지 종목명 검색 — 설계

날짜: 2026-06-03
대상: `web/src/pages/ChartPage.tsx` (React)

## 배경 / 문제

차트 페이지(`/chart`)는 현재 **종목 코드**(예: `000660`)로만 조회 가능하다.
"SK하이닉스" 같은 **종목명으로는 검색이 안 된다.** 코드를 외우거나 따로 찾아야 하는
불편이 있다.

## 목표

차트 페이지 검색 입력을 **자동완성 콤보박스**로 바꿔, **코드 또는 종목명** 아무거나
입력하면 매칭 후보가 뜨고 선택하면 해당 차트로 이동하게 한다.

## 비목표 (Non-goals)

- 차트 라우트 구조 변경. URL은 계속 `/chart/{ticker}` (코드가 정식 키).
- PromptPage 등 다른 페이지의 기존 검색 UI 변경/공통화 (불필요한 리팩터 회피 — 추후 선택적 후속).
- 백엔드 변경. 기존 `/api/stocks` 를 그대로 사용.

## 핵심 결정 (브레인스토밍 합의)

1. **UX**: 자동완성 드롭다운. 입력 → 후보 목록(`코드 · 이름 · 시장`) → 클릭/Enter 로 이동.
2. **데이터 소스**: 전 종목을 한 번 받아 **클라이언트에서 필터**(코드 OR 이름, 대소문자 무시).
   PromptPage 가 이미 이 방식 — 일관성 + 백엔드 변경 0. 한국 종목 수(~수천)면 단일 페이로드로 충분.
3. **라우트 불변**: 이름 검색은 "이름 → 코드 해석" 보조일 뿐. 선택 결과는 `/chart/{ticker}` 로 navigate.
4. 기존 "미너비니 통과" 빠른선택 드롭다운은 그대로 유지.

## 영향 범위

- 변경: `web/src/pages/ChartPage.tsx` — 기존 "종목 코드" 입력 폼(텍스트 input + "이동" 버튼)을
  새 `StockSearch` 컴포넌트로 교체.
- 신규: `web/src/components/StockSearch.tsx` — 자동완성 입력 + 드롭다운, ChartPage 전용.
- 기존 백엔드/라우트/타입 변경 없음. `api<Stock[]>("/stocks")` (이미 존재, `StockOut` 반환) 재사용.

## 동작 흐름

```
ChartPage
  └─ <StockSearch onSelect={(ticker) => navigate(`/chart/${ticker}`)} />
        - useQuery(["stocks-all"], () => api<Stock[]>("/stocks?limit=10000"))  // 1회 fetch, 캐시
        - 입력 query 에 대해 client-side 필터:
            stocks.filter(s =>
              s.ticker.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)
            ).slice(0, 20)
        - 후보 드롭다운 렌더: "{ticker} · {name} · {market}"
        - 후보 클릭 → onSelect(ticker)
        - Enter (입력 비어있지 않을 때) → 첫 후보 선택 (있으면)
        - 빈 입력 → 드롭다운 닫힘 / 후보 없음 → "결과 없음" 표시
```

- 기존 ChartPage 의 `inputTicker` state + `handleTickerSubmit` 폼은 제거하고 `StockSearch` 로 대체.
- `StockSearch` 는 내부 state(query, 열림 여부)만 가지며, 선택 시 부모 콜백 호출 — 부모(ChartPage)가 navigate 책임.

## StockSearch 컴포넌트 인터페이스

```tsx
interface StockSearchProps {
  onSelect: (ticker: string) => void;
  placeholder?: string;  // 기본 "코드 또는 종목명 (예: 000660, 하이닉스)"
}
```

- 의존: `api`(기존 fetch 래퍼), `Stock` 타입(기존 `web/src/lib/types.ts`), `@tanstack/react-query` useQuery.
- 책임: 검색 입력 + 후보 필터/표시 + 선택 콜백. navigate/라우팅은 하지 않음(부모 책임).

## 엣지 케이스

- 종목 목록 로딩 중: 입력 가능하되 후보 비어있음(또는 로딩 표시). 로드되면 필터 동작.
- 매칭 0건: "결과 없음" 메시지.
- 대소문자/공백: query 는 `trim().toLowerCase()` 후 비교.
- 코드 직접 입력 + Enter: 첫 후보로 이동(정확 코드면 그 후보가 최상단).

## 테스트

- web/ 테스트 인프라 유무를 계획 단계에서 확인:
  - 있으면(vitest/jest 등): `StockSearch` 컴포넌트 테스트 — 입력 시 후보 필터, 클릭 시 onSelect(ticker) 호출, 빈 입력/0건 처리.
  - 없으면: 앱 실행(run/verify 스킬) 후 수동 검증 — "하이닉스" 입력 → 000660 후보 → 클릭 → 차트 이동.
- 백엔드 변경 없으므로 Python 테스트 영향 없음.

## 파일 변경 예상

- 신규: `web/src/components/StockSearch.tsx`
- 변경: `web/src/pages/ChartPage.tsx` (검색 폼 영역만 교체; 차트/토글/패널 로직 불변)
