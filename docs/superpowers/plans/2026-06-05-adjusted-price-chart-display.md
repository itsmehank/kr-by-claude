# 웹 차트 수정주가(adjusted) 표시 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 웹 차트의 캔들·거래량을 raw 대신 저장된 adjusted 컬럼으로 표시해, 봉·이동평균선·52주선·RS선·헤더종가가 모두 단일(adjusted) 눈금에서 정합하게 한다.

**Architecture:** 표시 계층만 변경. (1) 차트 전용 API(`/api/indicators/daily|weekly`)가 `adj_open/adj_high/adj_low/adj_volume`를 추가로 내려주고(SELECT 끝에 append, COALESCE로 NULL 안전), (2) 프론트 어댑터(`dailyToBar`/`weeklyToBar`)가 캔들 바를 adj_*로 매핑한다. 렌더 코드·LLM 분석 체인은 무변경.

**Tech Stack:** FastAPI + psycopg3 (API), Pydantic (스키마), React + lightweight-charts + TypeScript (프론트), pytest (`db` 픽스처, auto-rollback).

---

## 배경 / 스펙 근거

스펙: `docs/superpowers/specs/2026-06-05-adjusted-price-chart-display-design.md`.

실측 확인 사실:
- `daily_prices`/`weekly_prices` 에 `adj_open/adj_high/adj_low/adj_close/adj_volume` 존재·100% 채워짐(daily 1,225,249행/weekly 262,501행, NULL 0). 컬럼은 nullable → COALESCE 방어.
- `api/routers/indicators.py` 의 daily(`get_daily`, :18-61)·weekly(`get_weekly`, :64-113) 엔드포인트는 응답을 **positional 튜플 인덱스**(`r[0]`…`r[20]` daily, `r[0]`…`r[15]` weekly)로 빌드한다. **신규 컬럼은 SELECT 맨 끝에 append** 하고 그 새 인덱스로 빌더에 추가해야 한다(중간 삽입 시 이후 필드가 밀려 조용히 손상).
- `daily_indicators.adj_close` 는 `daily_prices.adj_close` 에서 파생된 동일 adjusted 값(캔들 close 는 기존 `i.adj_close` 그대로 사용).
- 프론트: API row 타입 `DailyIndicator`(`web/src/lib/types.ts:9-31`)·`WeeklyIndicator`(:79-96), 어댑터 `dailyToBar`(`web/src/pages/ChartPage.tsx:89-109`)·`weeklyToBar`(:111-131), 캔들 타입 `PriceChartBar`(`web/src/components/charts/PriceChart.tsx:28-46`). `PriceChartBar` 는 **무변경**(바의 기존 open/high/low/close/volume 가 adj 값을 운반).
- `adj_volume` 은 `NUMERIC(20,2)` → 소수 가능, 스키마/빌더 모두 `float`.
- 프론트 테스트 러너 없음 → 타입체크(`npm run build` = `tsc -b && vite build`) + 수동 확인.
- API 테스트는 라우터 함수를 직접 호출(예: `get_daily(ticker, start, end, conn=db)`)해 반환 `list[DailyIndicatorOut]` 의 **모든 필드 매핑**을 검증(positional 밀림 탐지). `db` 픽스처는 `tests/conftest.py` 의 auto-rollback 연결.

## 파일 구조

- `api/schemas/indicator.py` — `DailyIndicatorOut`/`WeeklyIndicatorOut` 에 adj_* 필드(응답 계약).
- `api/routers/indicators.py` — daily/weekly SELECT append + 빌더 인덱스(데이터 공급).
- `web/src/lib/types.ts` — API row 타입에 adj_* 필드.
- `web/src/pages/ChartPage.tsx` — 어댑터가 캔들 바를 adj_* 로 매핑.
- `tests/test_api_indicators_series.py`(신규) — daily/weekly 응답 검증.

---

### Task 1: 스키마 + daily 엔드포인트 adj_* + 종합 테스트

**Files:**
- Modify: `api/schemas/indicator.py` (DailyIndicatorOut + WeeklyIndicatorOut)
- Modify: `api/routers/indicators.py:26-61` (daily SELECT + 빌더)
- Test: `tests/test_api_indicators_series.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_api_indicators_series.py` (신규):

```python
"""tests/test_api_indicators_series.py — 차트 시리즈 엔드포인트 adjusted 가격 검증.

라우터 함수를 직접 호출해 반환 모델의 모든 필드 매핑을 확인(positional 인덱스 밀림 탐지).
"""
from datetime import date


def _seed_daily(db, ticker="SPLIT"):
    """분할종목: raw ≠ adj 로 시드 + adj NULL 행(COALESCE fallback) 1건."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '분할', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )
        # 행1: adj 채워짐, raw ≠ adj, adj_volume 소수
        cur.execute(
            """INSERT INTO daily_prices
               (ticker, date, open, high, low, close, adj_close, adj_open, adj_high, adj_low, adj_volume, volume, value)
               VALUES (%s, %s, 10000, 10500, 9800, 10000, 2000, 2000, 2100, 1960, 5000.5, 1000, 10000000)
               ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 2)),
        )
        cur.execute(
            """INSERT INTO daily_indicators
               (ticker, date, adj_close, sma_50, volume_ratio_50d, distribution_day_flag)
               VALUES (%s, %s, 2000, 1950, 1.5, TRUE) ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 2)),
        )
        # 행2: adj_open/high/low/volume NULL → COALESCE 로 raw 대체되어야 함
        cur.execute(
            """INSERT INTO daily_prices
               (ticker, date, open, high, low, close, adj_close, volume, value)
               VALUES (%s, %s, 11000, 11200, 10800, 11000, 11000, 1500, 16500000)
               ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 5)),
        )
        cur.execute(
            """INSERT INTO daily_indicators (ticker, date, adj_close)
               VALUES (%s, %s, 11000) ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 5)),
        )
    db.commit()


def test_get_daily_returns_adjusted_ohlcv(db):
    from api.routers.indicators import get_daily
    _seed_daily(db)
    out = get_daily("SPLIT", start=date(2026, 1, 1), end=date(2026, 1, 31), conn=db)
    assert len(out) == 2
    r1 = out[0]  # 2026-01-02 (정렬 ORDER BY date)
    # adj_* 가 raw 가 아닌 저장된 adj 값으로 내려오는지
    assert r1.adj_open == 2000.0
    assert r1.adj_high == 2100.0
    assert r1.adj_low == 1960.0
    assert r1.adj_volume == 5000.5          # float(소수) 보존
    assert r1.adj_close == 2000.0
    # raw 필드는 그대로 유지(다른 소비자 안전)
    assert r1.open == 10000.0 and r1.close == 10000.0


def test_get_daily_positional_mapping_intact(db):
    """append 후에도 기존 필드가 올바른 위치에 매핑되는지(인덱스 밀림 회귀)."""
    from api.routers.indicators import get_daily
    _seed_daily(db)
    r1 = get_daily("SPLIT", start=date(2026, 1, 1), end=date(2026, 1, 31), conn=db)[0]
    assert r1.sma_50 == 1950.0
    assert r1.volume_ratio_50d == 1.5
    assert r1.distribution_day_flag is True


def test_get_daily_adj_null_falls_back_to_raw(db):
    """adj_open/high/low/volume NULL 행은 COALESCE 로 raw 대체."""
    from api.routers.indicators import get_daily
    _seed_daily(db)
    r2 = get_daily("SPLIT", start=date(2026, 1, 1), end=date(2026, 1, 31), conn=db)[1]  # 2026-01-05
    assert r2.adj_open == 11000.0   # raw open
    assert r2.adj_high == 11200.0   # raw high
    assert r2.adj_low == 10800.0    # raw low
    assert r2.adj_volume == 1500.0  # raw volume
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_indicators_series.py -v`
Expected: FAIL — `DailyIndicatorOut` 에 `adj_open` 등이 없어 `AttributeError`/Pydantic 에러, 또는 빌더가 해당 필드를 안 채워 `adj_open is None`.

- [ ] **Step 3: 스키마에 adj_* 필드 추가**

`api/schemas/indicator.py` — `DailyIndicatorOut` 과 `WeeklyIndicatorOut` 양쪽에 추가(weekly 는 Task 2 에서 쓰지만 한 번에 추가):

```python
    adj_open: float | None = None
    adj_high: float | None = None
    adj_low: float | None = None
    adj_volume: float | None = None
```

- [ ] **Step 4: daily SELECT 끝에 append + 빌더 인덱스 추가**

`api/routers/indicators.py` daily 쿼리(:26-38) — 기존 마지막 컬럼 `i.distribution_day_flag` 뒤에 콤마+4컬럼 append:

```sql
               i.volume_ratio_50d, i.pocket_pivot_flag, i.distribution_day_flag,
               COALESCE(p.adj_open,   p.open)   AS adj_open,
               COALESCE(p.adj_high,   p.high)   AS adj_high,
               COALESCE(p.adj_low,    p.low)    AS adj_low,
               COALESCE(p.adj_volume, p.volume) AS adj_volume
```

빌더(:40-61) `distribution_day_flag=r[20],` 다음에 추가:

```python
        adj_open=float(r[21]) if r[21] is not None else None,
        adj_high=float(r[22]) if r[22] is not None else None,
        adj_low=float(r[23]) if r[23] is not None else None,
        adj_volume=float(r[24]) if r[24] is not None else None,
```

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_api_indicators_series.py -k daily -v`
Expected: PASS (3 daily 테스트).

- [ ] **Step 6: 커밋**

```bash
git add api/schemas/indicator.py api/routers/indicators.py tests/test_api_indicators_series.py
git commit -m "feat(api): /indicators/daily 에 adj_open/high/low/volume 추가 (COALESCE, 차트 수정주가)"
```

---

### Task 2: weekly 엔드포인트 adj_* + 종합 테스트

**Files:**
- Modify: `api/routers/indicators.py:76-113` (weekly SELECT + 빌더)
- Test: `tests/test_api_indicators_series.py` (weekly 케이스 추가)

> 스키마(`WeeklyIndicatorOut`)는 Task 1 Step 3 에서 이미 adj_* 추가됨.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_api_indicators_series.py` 에 추가:

```python
def _seed_weekly(db, ticker="SPLITW"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, '분할주봉', 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker,),
        )
        # 행1: raw ≠ adj
        cur.execute(
            """INSERT INTO weekly_prices
               (ticker, week_end_date, open, high, low, close, adj_close, adj_open, adj_high, adj_low, adj_volume, volume, value, trading_days)
               VALUES (%s, %s, 10000, 10500, 9800, 10000, 2000, 2000, 2100, 1960, 5000.5, 1000, 10000000, 5)
               ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 2)),
        )
        cur.execute(
            """INSERT INTO weekly_indicators
               (ticker, week_end_date, adj_close, sma_10w, minervini_pass)
               VALUES (%s, %s, 2000, 1950, TRUE) ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 2)),
        )
        # 행2: adj NULL → COALESCE fallback
        cur.execute(
            """INSERT INTO weekly_prices
               (ticker, week_end_date, open, high, low, close, adj_close, volume, value, trading_days)
               VALUES (%s, %s, 11000, 11200, 10800, 11000, 11000, 1500, 16500000, 5)
               ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 9)),
        )
        cur.execute(
            """INSERT INTO weekly_indicators (ticker, week_end_date, adj_close)
               VALUES (%s, %s, 11000) ON CONFLICT DO NOTHING""",
            (ticker, date(2026, 1, 9)),
        )
    db.commit()


def test_get_weekly_returns_adjusted_ohlcv(db):
    from api.routers.indicators import get_weekly
    _seed_weekly(db)
    out = get_weekly("SPLITW", start=date(2026, 1, 1), end=date(2026, 1, 31), conn=db)
    assert len(out) == 2
    r1 = out[0]
    assert r1.adj_open == 2000.0
    assert r1.adj_high == 2100.0
    assert r1.adj_low == 1960.0
    assert r1.adj_volume == 5000.5
    assert r1.adj_close == 2000.0
    assert r1.open == 10000.0 and r1.close == 10000.0
    # positional 회귀: 기존 필드 정상
    assert r1.sma_10w == 1950.0
    assert r1.minervini_pass is True


def test_get_weekly_adj_null_falls_back_to_raw(db):
    from api.routers.indicators import get_weekly
    _seed_weekly(db)
    r2 = get_weekly("SPLITW", start=date(2026, 1, 1), end=date(2026, 1, 31), conn=db)[1]
    assert r2.adj_open == 11000.0
    assert r2.adj_high == 11200.0
    assert r2.adj_low == 10800.0
    assert r2.adj_volume == 1500.0
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_indicators_series.py -k weekly -v`
Expected: FAIL — weekly 빌더가 adj_* 를 안 채워 `adj_open is None` → assert 실패.

- [ ] **Step 3: weekly SELECT 끝에 append + 빌더 인덱스 추가**

`api/routers/indicators.py` weekly 쿼리(:78-89) — 기존 마지막 컬럼 `i.minervini_pass` 뒤에 콤마+4컬럼 append:

```sql
               i.rs_line, i.rs_rating, i.minervini_pass,
               COALESCE(p.adj_open,   p.open)   AS adj_open,
               COALESCE(p.adj_high,   p.high)   AS adj_high,
               COALESCE(p.adj_low,    p.low)    AS adj_low,
               COALESCE(p.adj_volume, p.volume) AS adj_volume
```

빌더(:93-113) `minervini_pass=r[15],` 다음에 추가:

```python
            adj_open=float(r[16]) if r[16] is not None else None,
            adj_high=float(r[17]) if r[17] is not None else None,
            adj_low=float(r[18]) if r[18] is not None else None,
            adj_volume=float(r[19]) if r[19] is not None else None,
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_api_indicators_series.py -v`
Expected: PASS (daily 3 + weekly 2 = 5).

- [ ] **Step 5: 커밋**

```bash
git add api/routers/indicators.py tests/test_api_indicators_series.py
git commit -m "feat(api): /indicators/weekly 에 adj_open/high/low/volume 추가 (COALESCE)"
```

---

### Task 3: 프론트 — API 타입 + 어댑터 adjusted 매핑

**Files:**
- Modify: `web/src/lib/types.ts` (`DailyIndicator`:9-31, `WeeklyIndicator`:79-96)
- Modify: `web/src/pages/ChartPage.tsx` (`dailyToBar`:89-109, `weeklyToBar`:111-131)

> `PriceChart.tsx` 는 **변경 없음**(렌더 코드·`PriceChartBar` 타입 그대로). 프론트 테스트 러너가 없어 타입체크(`npm run build`) + 수동 확인으로 검증한다.

- [ ] **Step 1: API row 타입에 adj_* 필드 추가**

`web/src/lib/types.ts` — `DailyIndicator` 인터페이스(:9-31)에 추가:

```ts
  adj_open: number | null;
  adj_high: number | null;
  adj_low: number | null;
  adj_volume: number | null;
```

`WeeklyIndicator` 인터페이스(:79-96)에도 동일 4줄 추가.

- [ ] **Step 2: 어댑터를 adjusted 매핑으로 교체**

`web/src/pages/ChartPage.tsx` — `dailyToBar`(:89-109) 의 캔들/거래량 매핑 5줄 교체:

```ts
function dailyToBar(d: DailyIndicator): PriceChartBar {
  return {
    date: d.date,
    open: d.adj_open,
    high: d.adj_high,
    low: d.adj_low,
    close: d.adj_close,
    adj_close: d.adj_close,
    volume: d.adj_volume,
    avg_volume_50d: d.avg_volume_50d,
    sma_short: d.sma_50,
    sma_mid: d.sma_150,
    sma_long: d.sma_200,
    sma_extra: d.sma_10,
    w52_high: d.w52_high,
    w52_low: d.w52_low,
    pocket_pivot_flag: d.pocket_pivot_flag,
    distribution_day_flag: d.distribution_day_flag,
    minervini_pass: d.minervini_pass,
  };
}
```

`weeklyToBar`(:111-131) 도 동일하게 `open: w.adj_open, high: w.adj_high, low: w.adj_low, close: w.adj_close, volume: w.adj_volume` 로 교체(나머지 줄 유지).

- [ ] **Step 3: 타입체크/빌드 통과 확인**

Run: `cd web && npm run build`
Expected: `tsc -b` 통과(타입 에러 없음) + vite build 성공. (어댑터가 `d.adj_*` 를 읽으므로 Step 1 의 타입 필드가 없으면 여기서 컴파일 에러로 잡힌다 — 이게 프론트의 "예상치 못한 에러" 안전망.)

- [ ] **Step 4: 수동 확인(분할종목 차트)**

웹 dev 서버에서 분할 이력 종목(예: 차트에서 raw≠adj 인 종목) 차트를 연다. 확인:
- 분할일에 캔들이 더 이상 급단차 없이 이동평균선과 같은 눈금에 정합
- 헤더 "종가"(이미 adj) 와 최신 캔들 종가 일치
- 호버 툴팁 OHLC·거래량이 수정주가 기준
- 배경 분류 밴드는 종전과 동일(날짜 기준)

(자동 테스트 러너 부재로 수동. 데이터/매핑 자체는 Task 1·2 의 API 테스트로 커버됨.)

- [ ] **Step 5: 커밋**

```bash
git add web/src/lib/types.ts web/src/pages/ChartPage.tsx
git commit -m "feat(web): 차트 캔들/거래량을 수정주가(adj_*)로 표시 (봉↔지표 눈금 정합)"
```

---

### Task 4: 회귀 + 범위 무영향 확인

**Files:** 없음(검증만)

- [ ] **Step 1: 변경영역 + 인접 테스트**

Run:
```bash
uv run pytest tests/test_api_indicators_series.py tests/test_api_chart_render.py tests/test_api_csv_builder.py tests/test_api_payload_builder.py -v
```
Expected: 신규 5 PASS. chart_render/csv/payload 테스트는 **무변경 통과**(이번 작업이 그 코드 경로를 안 건드림을 확인 — LLM 아티팩트 범위 밖).

- [ ] **Step 2: 전체 회귀 base 대비**

Run:
```bash
uv run pytest tests/ -q 2>&1 | grep "^FAILED" | sed 's/ -.*//' | sort > /tmp/p3_head.txt
wc -l < /tmp/p3_head.txt
```
Expected: 현재 main 사전 실패 수(~26)와 동일 — 신규 회귀 0. 다르면 base 와 `comm -23` 로 신규 실패 식별 후 수정.

- [ ] **Step 3: 프론트 빌드 최종 확인**

Run: `cd web && npm run build`
Expected: 성공(타입 에러 0).

- [ ] **Step 4: 최종 커밋(없으면 skip)**

검증만이므로 보통 커밋 없음. 수정 발생 시 해당 변경 커밋.

---

## Self-Review

**1. Spec coverage:**
- API daily/weekly 에 adj_* 추가(COALESCE, SELECT 끝 append, positional 인덱스): Task 1·2 ✓
- 스키마 adj_* (`float`): Task 1 Step 3 ✓
- 프론트 타입(`DailyIndicator`/`WeeklyIndicator`) + 어댑터(dailyToBar/weeklyToBar) adj 매핑, `PriceChartBar`/`PriceChart.tsx` 무변경: Task 3 ✓
- raw 필드 응답 유지: Task 1 SELECT(기존 컬럼 보존) ✓ + 테스트(`r1.open==10000`)로 검증
- NULL fallback(COALESCE): Task 1·2 의 `_adj_null_falls_back` 테스트 ✓
- adj_volume float 보존: `adj_volume == 5000.5` 테스트 ✓
- positional 밀림 회귀: `_positional_mapping_intact`/weekly sma·minervini 검증 ✓
- LLM 아티팩트/게이트 무변경: Task 4 Step 1 (chart_render/csv/payload 무변경 통과) ✓
- 회귀 0: Task 4 Step 2 ✓

**2. Placeholder scan:** 모든 코드 스텝에 실제 SQL/Python/TS/명령·기대출력. "적절히" 류 없음. ✓

**3. Type consistency:**
- 스키마 `adj_*: float | None`(Task1) ↔ 빌더 `float(r[..])`(Task1·2) ↔ 테스트 `== 2000.0/5000.5`(Task1·2) 일관.
- TS `adj_*: number | null`(Task3 types.ts) ↔ 어댑터 `d.adj_*`(Task3 ChartPage) ↔ `PriceChartBar.{open..}` 기존 `number | null`(무변경) 일관. `close: d.adj_close`(`number`) → `number | null` 할당 OK.
- 인덱스: daily append r[21~24], weekly r[16~19] — SELECT 컬럼 수(daily 기존 21개=r0~20, weekly 16개=r0~15)와 정합.

**알려진 범위 제한(의도적):** LLM 차트 PNG·payload·CSV·게이트·performance·프롬프트는 무변경(스펙 비목표). 그쪽 raw/adj 정합성은 별도 후속 프로젝트.
