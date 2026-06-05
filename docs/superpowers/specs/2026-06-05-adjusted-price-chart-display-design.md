# P3 — 웹 차트 수정주가(adjusted) 표시 설계

날짜: 2026-06-05
대상: `api/routers/indicators.py`, `api/schemas/indicator.py`, `web/src/pages/ChartPage.tsx`, `web/src/components/charts/PriceChart.tsx`
범위 밖(명시): `api/services/chart_render.py`(LLM PNG), `api/services/payload_builder.py`, `api/services/csv_builder.py`, `kr_pipeline/llm_runner/**`(게이트·저장값·performance), `prompts/**`.

## 배경 / 문제

웹 차트는 캔들(봉)을 **raw OHLC**(`daily_prices.open/high/low/close`)로 그리지만, 그 위에 겹치는 **이동평균선·52주 고저·RS선**은 **adjusted**(`adj_close` 등)로 계산된 값이다(`kr_pipeline/indicators/modes.py:148-176`). 평소엔 두 값이 같지만 **액면분할이 발생하면** raw 캔들은 분할일에 급변(예: 5만원→1만원)하는 반면 보정된 이동평균선은 매끄럽게 이어져, **봉과 보조선이 서로 다른 눈금 위에 놓이는** 시각적 불일치가 생긴다. 차트 헤더의 "종가"는 이미 `adj_close`(`web/src/pages/ChartPage.tsx:383`)라 캔들 종가와도 어긋난다.

P0에서 `daily_prices`/`weekly_prices` 에 `adj_open/adj_high/adj_low/adj_close/adj_volume` 가 1급 컬럼으로 추가·백필되어(실측: daily 1,225,249행·weekly 262,501행 모두 NULL 0), 새 계산 없이 **표시 계층에서 raw 대신 저장된 adj_* 컬럼을 읽기만** 하면 된다.

## 목표

웹 차트의 **캔들과 거래량을 adjusted 기준으로 교체**하여 봉·이동평균선·52주선·RS선·헤더 종가·거래량지표가 모두 **단일(adjusted) 눈금**에서 정합하도록 한다.

## 비목표 (Non-goals) — 의도적 범위 제한

- **LLM 분석 체인은 일절 건드리지 않는다**: LLM 차트 PNG(`chart_render.py`), payload(`payload_builder.py`), 분류/돌파/탈락 게이트, 저장 피벗·매수가, `performance.py`, 프롬프트. 이들 가격은 단순 표시가 아니라 LLM이 피벗/매수가/손절가를 산출→저장(`weekly_classification`, `entry_params`)→결정론 게이트·백테스트가 소비하므로, 눈금 변경은 트레이딩 로직 정합성 전반에 영향을 준다. 그 정합성은 **별도 후속 프로젝트**로 다룬다(감사에서 발견된 기존 raw/adj 혼용 버그 — 예: `performance.py:86` raw 매수가 vs adj 미래종가 — 포함).
- raw↔adj 토글 UI (사용자가 (가)교체를 선택, 토글 미채택).
- 지수(index) 캔들/CSV (index_daily 는 adjusted 컬럼 없음, 별도 영역).
- 실시간 보정 계산 (P0가 이미 저장 — 불필요).

## 아키텍처

웹 차트 한정 표시 계층 교체. 두 지점만 바꾼다: (1) 차트 전용 API가 adj_* 를 내려주도록 확장, (2) 프론트 어댑터가 캔들 바를 adj_* 로 매핑. 차트 렌더 코드 자체는 무변경(바의 OHLC 필드가 이제 adjusted 값을 운반).

### 1. API — `api/routers/indicators.py` + `api/schemas/indicator.py`

> **중대 구현 주의 — positional 인덱스**: 응답 빌더가 `DailyIndicatorOut(date=r[0], ..., distribution_day_flag=r[20])` 처럼 **튜플 위치 인덱스**(`r[0]`…`r[20]` daily, `r[0]`…`r[15]` weekly)로 매핑한다(`indicators.py:40-61`, `93-113`). 따라서 신규 컬럼은 **반드시 SELECT 의 맨 끝에 append** 하고 그 **새 인덱스**로 빌더에 추가한다. SELECT *중간* 에 끼우면 이후 모든 인덱스가 밀려 SMA·플래그 등이 엉뚱한 필드로 들어가 **조용히 손상**된다.

- **daily 엔드포인트**(`indicators.py:26-38` SELECT): 기존 마지막 컬럼 `i.distribution_day_flag`(=`r[20]`) **뒤에 append**:
  ```sql
                     i.volume_ratio_50d, i.pocket_pivot_flag, i.distribution_day_flag,
                     COALESCE(p.adj_open,   p.open)   AS adj_open,    -- r[21]
                     COALESCE(p.adj_high,   p.high)   AS adj_high,    -- r[22]
                     COALESCE(p.adj_low,    p.low)    AS adj_low,     -- r[23]
                     COALESCE(p.adj_volume, p.volume) AS adj_volume   -- r[24]
  ```
  빌더(`indicators.py:40-61`)에 추가:
  ```python
          adj_open=float(r[21]) if r[21] is not None else None,
          adj_high=float(r[22]) if r[22] is not None else None,
          adj_low=float(r[23]) if r[23] is not None else None,
          adj_volume=float(r[24]) if r[24] is not None else None,
  ```
  COALESCE 는 NULL 안전망(현재 데이터 100% 채워짐, 컬럼은 nullable 이라 방어). raw `open/high/low/close/volume` 는 응답에 **그대로 유지**(다른 소비자 안전; 캔들만 adj 사용). adj_close 는 이미 `i.adj_close`(=`r[1]`) 로 존재 — 캔들 종가는 이 값을 그대로 사용(`i.adj_close` 는 `p.adj_close` 에서 파생된 동일 adjusted 값이라 캔들 정합 유지).
- **weekly 엔드포인트**(`indicators.py:76-91` SELECT): 기존 마지막 컬럼 `i.minervini_pass`(=`r[15]`) 뒤에 동일 4컬럼 append → `r[16] adj_open, r[17] adj_high, r[18] adj_low, r[19] adj_volume`. 빌더(`indicators.py:93-113`)에 `adj_open=float(r[16])…, adj_volume=float(r[19])…` 추가(daily 와 동일 패턴, 인덱스만 16~19).
- **스키마**(`api/schemas/indicator.py`): `DailyIndicatorOut`(:5~) 및 `WeeklyIndicatorOut` 에 `adj_open: float | None = None`, `adj_high: float | None = None`, `adj_low: float | None = None`, `adj_volume: float | None = None` 추가. (adj_volume 은 `NUMERIC(20,2)` — 분할 보정 시 소수 가능 → `int` 아님, `float`.)

### 2. 프론트 — `web/src/lib/types.ts` + `web/src/pages/ChartPage.tsx`

- **API row 타입만 변경**(`web/src/lib/types.ts`): `DailyIndicator`(:9-31) 와 `WeeklyIndicator`(:79-96) 에 `adj_open: number | null`, `adj_high: number | null`, `adj_low: number | null`, `adj_volume: number | null` 추가. **`PriceChartBar`(`PriceChart.tsx:28-46`) 는 변경 없음** — 바의 기존 `open/high/low/close/volume` 필드가 어댑터를 통해 adjusted 값을 운반(새 필드 불필요).
- **어댑터만 변경**(`ChartPage.tsx:89-109` `dailyToBar`, `:111-131` `weeklyToBar`): 캔들 바 매핑을 raw→adj 로 교체(두 어댑터 동일 패턴).
  ```ts
  open:   d.adj_open,
  high:   d.adj_high,
  low:    d.adj_low,
  close:  d.adj_close,
  volume: d.adj_volume,
  adj_close: d.adj_close,   // 헤더/ChartMetaBar 용 유지(이제 캔들 close 와 동일 값)
  ```
- **`PriceChart.tsx` 렌더 코드 무변경**: 캔들 시리즈(`:176-188`)·거래량 시리즈(`:263-273`)·툴팁(`:360-491`)·등락%(`:434-436`)는 바의 `open/high/low/close/volume` 를 읽으므로 어댑터 매핑만으로 adjusted 로 전환된다.
- **"종가" 헤더**(`ChartPage.tsx:383` `latestBar.adj_close`)·`ChartMetaBar`(adj_close 기준)는 이미 adjusted → 이제 캔들 종가와 **일치**.
- **배경 밴드/범례**: `overlayBands`/`ChartOverlayBands` 는 날짜 기준(`ChartPage.tsx:240`)이라 무변경.

> 캔들 정합: `close` 는 `d.adj_close`(타입 `number`, non-null)라 항상 채워짐. `open/high/low/volume` 은 `d.adj_*`(`number | null`)이며 API COALESCE 로 non-null 보장 → 캔들 누락 없음.

## 데이터 흐름

`daily_prices.adj_*` → API(COALESCE 별칭) → 프론트 어댑터(`dailyToBar`) → `PriceChartBar.{open,high,low,close,volume}` → lightweight-charts 캔들/거래량. 이동평균·52주·RS·헤더종가는 이미 adjusted → 전 요소 단일 눈금 정합. (LLM PNG/payload 는 범위 밖이라 종전 raw 유지 — 의도적.)

## 에러 처리 / 엣지

- **NULL**: COALESCE(adj_x, raw_x)로 API 단에서 보장 → 어댑터/캔들 필터(`PriceChart.tsx:177-180`, null 바 제거)에서 캔들이 조용히 누락되는 일 방지.
- **캔들 내부 정합**(high≥close≥low): 캔들 OHLCV 를 모두 `daily_prices`(p)의 adj_* 에서 가져오고 close 는 `adj_close`(i.adj_close == p.adj_close, 동일 adjusted 데이터)라 정합 유지. 파이프라인 일시 불일치로 close>high 같은 경우라도 lightweight-charts 는 렌더 가능(허용).
- raw 필드 유지로 기존 API 소비자 무영향.

## 테스트

- **API**(신규 `tests/test_api_indicators_series.py` — daily/weekly 지표 시리즈 엔드포인트 전용 테스트가 없으므로 신규 생성): daily/weekly 응답에 `adj_open/adj_high/adj_low/adj_volume` 필드 존재. **분할종목 픽스처(raw≠adj, 예 close=10000/adj_close=2000)** 로 응답의 adj_* 가 raw 와 다르게(=저장된 adj 값으로) 내려오는지 값 검증. COALESCE: adj_* NULL 행에서 raw 로 대체되는지.
- **프론트**: `dailyToBar`/`weeklyToBar` 가 `adj_*` 를 캔들 바 `open/high/low/close/volume` 에 매핑하는지 단위 테스트(테스트 인프라 있으면) 또는 수동 확인(분할종목 차트에서 봉↔이동평균선 눈금 일치 육안 확인).
- **회귀**: base 대비 신규 실패 0. LLM 아티팩트/게이트/performance 테스트는 무변경(이번 범위가 그 코드 경로를 건드리지 않음을 확인).

## 파일 변경 예상

- 변경: `api/routers/indicators.py`(SELECT 끝에 append 2곳 + 빌더 인덱스 추가 2곳), `api/schemas/indicator.py`(adj_* 필드), `web/src/lib/types.ts`(`DailyIndicator`/`WeeklyIndicator` adj_* 필드), `web/src/pages/ChartPage.tsx`(어댑터 2곳).
- 무변경(확인용, UI): `web/src/components/charts/PriceChart.tsx`(렌더 코드·`PriceChartBar` 타입 그대로 — 바가 adjusted 값을 운반).
- 테스트: 신규 `tests/test_api_indicators_series.py` 에 adj_* 응답 검증.
- 무변경(확인용): `chart_render.py`, `payload_builder.py`, `csv_builder.py`, `kr_pipeline/llm_runner/**`, `prompts/**`.
