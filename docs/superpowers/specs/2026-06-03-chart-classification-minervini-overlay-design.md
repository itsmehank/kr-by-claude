# 차트 분류/미너비니 오버레이 — 설계

날짜: 2026-06-03
대상: `web/src/components/charts/PriceChart.tsx`, 신규 `web/src/components/charts/ChartOverlayBands.tsx`, `web/src/pages/ChartPage.tsx`, 신규 API `api/routers/classifications.py`(history 엔드포인트) + 스키마, `web/src/lib/types.ts`

## 배경 / 문제

차트 페이지(/chart)는 가격·이평선·마커는 보여주지만, 그 종목이 **시간에 따라 어떤 분류(entry/watch/ignore)였는지**, **언제 minervini를 미통과(=탈락)했는지**를 한눈에 볼 수 없다. 백테스트(백필)로 쌓은 과거 분류를 시각적으로 검증("진입 시점이 좋았나")하기도 어렵다.

## 목표

차트 배경에 **분류 상태를 시간 구간 색 밴드**로 오버레이하고, **on/off 토글 1개**로 켜고 끈다. 기존 차트 동작(호버 OHLC 툴팁, 드래그 기간 변경, 줌)은 그대로 유지한다.

## 비목표 (Non-goals)

- 기존 `PriceChart`의 캔들/이평선/마커/볼륨 렌더 로직 변경.
- lightweight-charts 버전 업그레이드, 차트 라이브러리 교체.
- 분류를 새로 계산/판정하는 로직 (기존 저장 데이터만 읽어 표시).

## 핵심 결정 (브레인스토밍 합의)

1. **렌더링 = B안(배경 색 밴드), 오버레이 레이어 방식.** lightweight-charts v5 는 배경 밴드를 기본 제공하지 않으므로, 차트 위에 투명 HTML 레이어를 덧대 밴드를 그린다. 기존 차트 코드 무수정.
2. **인터랙션 보존**: 오버레이 div 에 `pointer-events: none` → 마우스 이벤트가 차트 캔버스로 통과. 호버 툴팁·드래그 패닝·줌 그대로.
3. **동적 동기화**: `chart.timeScale().subscribeVisibleTimeRangeChange()` + `ResizeObserver` 로 줌/드래그/리사이즈 시 밴드 재배치. 위치는 `timeScale().timeToCoordinate(날짜)`. 화면 밖 날짜는 차트 가장자리로 클램프.
4. **배타적 4상태 (한 날짜 = 한 색, 겹침 없음)**: `entry`(초록), `watch`(파랑), `ignore`(회색), `fail`(빨강 = "미통과/탈락"). `disqualified` 분류 + minervini 미통과를 **하나의 `fail`** 로 통합.
5. **상태 산정 규칙 (per-date)**: `minervini_pass===false` → `fail`(우선). 아니면 그날의 **이월(carry-forward) 분류**(가장 최근 분류 ≤ 그 날). 첫 분류 이전 & 통과 중 → 밴드 없음(`none`).
6. **데이터 = 라이브 + 백필**: 분류 시계열은 `weekly_classification` + `classification_backfill` 을 UNION. 같은 날짜 중복 시 라이브 우선.
7. **토글 1개** `분류 밴드` (기본 OFF) → 켜면 4색 전체 표시. 끄면 현재와 동일.

## 아키텍처

### 데이터 소스

- **분류 시계열 (신규 API)**: `GET /api/classifications/history/{ticker}?start=&end=`
  - `weekly_classification` (키: `COALESCE(analyzed_for_date, classified_at::date)`) `UNION ALL` `classification_backfill` (키: `analyzed_for_date`), 날짜 범위 필터.
  - 같은 `(ticker, date)` 중복 시 **라이브 우선** (예: `DISTINCT ON (date)` + `ORDER BY date, source_rank` where live<backfill, classified_at DESC).
  - 반환: `[{date, classification}]` (date 오름차순). classification ∈ entry/watch/ignore/disqualified.
  - 기존 `classifications.py` 라우터에 핸들러 추가. `get_conn` 의존성, 날짜 기본값(start=end-365d, end=today).
- **minervini_pass (기존 데이터 재사용)**: 차트가 이미 받는 `GET /api/indicators/daily|weekly/{ticker}` 응답에 `minervini_pass` 포함. 신규 API 불필요. `PriceChartBar` 에 `minervini_pass` 필드 추가(어댑터 2곳).

### 세그먼트 빌드 (순수 함수)

`web/src/components/charts/overlayBands.ts` 에 순수 함수 `buildBandSegments(bars, classificationPoints)`:
- 입력: `bars: {date, minervini_pass}[]` (차트 표시 날짜, 오름차순), `classificationPoints: {date, classification}[]` (오름차순).
- 각 bar.date 에 대해 state 산정:
  - `minervini_pass === false` → `"fail"`.
  - 아니면 carry-forward: 그 날짜 이하 가장 최근 classificationPoint 의 분류. 단 `disqualified` 는 색 분류로 보지 않음(= `none`; fail 은 minervini 규칙이 담당).
  - 분류 없음(첫 분류 전) → `none`.
- 연속 동일 state 를 묶어 `[{startDate, endDate, state}]` 반환 (`none` 구간 제외).
- 입출력이 명확한 순수 함수 → 로직 검증 용이.

### 렌더링 — ChartOverlayBands

신규 `web/src/components/charts/ChartOverlayBands.tsx`:
- props: `chart`(IChartApi ref), `segments: BandSegment[]`, `visible: boolean`.
- 차트 컨테이너와 같은 부모(`position:relative`) 안의 절대배치 `div`(`pointer-events:none`, `inset:0`).
- 각 segment: `left = timeToCoordinate(startDate)`, `right = timeToCoordinate(endDate)` (null 이면 가장자리 클램프), 색 = state→color, 반투명. 세로는 가격 pane 높이.
- `useEffect` 에서 `timeScale().subscribeVisibleTimeRangeChange(redraw)` 구독 + `ResizeObserver(container)` → 위치 재계산. 언마운트 시 해제.
- `visible=false` 면 아무것도 안 그림.

### PriceChart 변경 (최소)

- 차트 컨테이너 div 를 `position:relative` wrapper 로 감싸고, 그 안에 `<ChartOverlayBands>` 자식 추가.
- 새 props 통과: `showClassificationBands?: boolean`, `bandSegments?: BandSegment[]`.
- 기존 시리즈/마커/라인/볼륨 코드 무수정. chart 인스턴스 ref 를 오버레이에 전달.

### ChartPage 변경

- 신규 useQuery: `classification-history` → `/api/classifications/history/{ticker}?start=&end=`.
- `PriceChartBar` 어댑터(`dailyToBar`/`weeklyToBar`)에 `minervini_pass` 매핑 추가.
- `buildBandSegments(bars, history)` 로 세그먼트 계산(useMemo).
- 토글 state `showClassificationBands`(기본 false) + 기존 토글 줄에 Toggle 추가.
- `<PriceChart showClassificationBands={...} bandSegments={...} />`.

## 색 정의

| state | 의미 | 색(반투명) |
|---|---|---|
| entry | 진입 | 초록 #16a34a |
| watch | 관찰 | 파랑 #2563eb |
| ignore | 무시 | 회색 #9ca3af |
| fail | 미통과/탈락 (구 disqualified + minervini 미통과) | 빨강 #dc2626 |
| none | 분류 전/표시 안 함 | 밴드 없음 |

## 엣지 케이스

- 분류 이력 없음 → 세그먼트 0개 → 토글 켜도 밴드 없음(에러 아님).
- 첫 분류 이전, minervini 통과 → 밴드 없음. 첫 분류 이전, minervini 미통과 → 빨강.
- 화면 밖(줌) 날짜 → 가장자리 클램프.
- weekly timeframe: minervini_pass 가 weekly 지표에도 있으면 동일 적용. 없으면 분류 밴드만, fail 은 분류값(disqualified)→none 처리로 빨강 미표시(주봉에선 일봉 minervini 기준이 다를 수 있음 — 일단 daily 우선, weekly 는 분류 밴드만으로 시작).
- 분류값 `disqualified` 자체는 색 분류에서 제외(fail 은 minervini_pass 가 담당).

## 테스트

**백엔드 (pytest)**:
- 신규 history 엔드포인트: 라이브+백필 UNION 결과, 같은 날짜 라이브 우선, 날짜범위 필터, 빈 결과, ticker 없음.

**프론트 (web — 단위테스트 프레임워크 없음)**:
- `buildBandSegments` 순수 함수: 가능하면 경량 검증(프레임워크 없으므로 별도 도입 대신, 로직을 작은 순수 함수로 고립시켜 tsc 타입 안전 + 수동 시나리오 검증). 입력 시나리오: minervini fail 우선, carry-forward, none 구간 제외, 연속 병합.
- 검증 = `npx tsc -b` + `npm run lint` + 앱 수동:
  1. 토글 OFF → 현재와 동일.
  2. 토글 ON → entry/watch/ignore/fail 색 밴드, 한 날짜 한 색(겹침 없음).
  3. 호버 OHLC 툴팁 정상.
  4. 드래그 기간 변경 시 밴드가 캔들과 정렬 유지하며 함께 이동.
  5. 줌/리사이즈 시 밴드 재배치.
  6. 분류 이력 없는 종목 → 밴드 없음, 에러 없음.

## 파일 변경 예상

- 신규: `api/routers/classifications.py` 에 history 핸들러 (+ `api/schemas/classification.py` 응답 모델).
- 신규: `web/src/components/charts/overlayBands.ts` (순수 세그먼트 빌더 + 타입/색).
- 신규: `web/src/components/charts/ChartOverlayBands.tsx` (오버레이 렌더).
- 변경: `web/src/components/charts/PriceChart.tsx` (컨테이너 wrap + 오버레이 자식 + props).
- 변경: `web/src/pages/ChartPage.tsx` (history fetch, minervini_pass 매핑, 세그먼트 계산, 토글).
- 변경: `web/src/lib/types.ts` (PriceChartBar 에 minervini_pass, 필요한 응답 타입).
- 변경: `tests/` 백엔드 엔드포인트 테스트.
