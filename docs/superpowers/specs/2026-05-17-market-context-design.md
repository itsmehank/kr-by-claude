# 시장 컨텍스트 + Breadth 인프라 설계 (#2.5)

- **상태**: Design
- **작성일**: 2026-05-17
- **범위**: 서브프로젝트 #2.5 — 시장 추세 판정 및 Breadth 계산 인프라
- **선행 의존**: #1 (일봉/지수), #1.5 (주봉), #2 (지표 기본 + V2 거래량) — 모두 완료됨
- **후속 의존자**: #2.6 (Corporate Actions), #3 (UI - payload.json), #4 (LLM 자동 분석)

## 1. 배경 및 목적

LLM 분석 프롬프트 `analyze_chart_v3.md` 의 §3.5 "Market Direction Confirmation" 이 요구하는 시장 상태 정보를 사전 계산해서 `market_context_daily` 테이블에 적재.

O'Neil 의 "M" (Market direction) 은 미너비니 트렌드 템플릿이 통과한 종목조차도 약세장에서는 entry → watch 로 강제 demotion 시키는 핵심 룰. 시장 상태가 잘못 판정되면 모든 후속 분석이 오염됨.

LLM 에게 직접 분포일/FTD 를 계산시키면 토큰 폭증 + 비결정성. 서버 단에서 사전 계산하는 게 옳음.

### 전체 시스템 분해 (재분해 후)

| # | 서브프로젝트 | 상태 |
|---|---|---|
| 1 | 일봉/지수 적재 | ✅ 완료 |
| 1.5 | 주봉 적재 | ✅ 완료 |
| 2 | 지표 생성 (기본 + V2 거래량) | ✅ 완료 |
| **2.5** | **시장 컨텍스트 + Breadth (본 문서)** | Design |
| 2.6 | Corporate Actions Fetcher (DART API) | 미시작 |
| 3 | 웹 UI + 새 ZIP 구조 | 미시작 |
| 4 | 2-step Claude Code CLI 자동 분석 | 미시작 |

## 2. 핵심 결정 사항

| 항목 | 결정 |
|---|---|
| 입력 | `index_daily` (KOSPI/KOSDAQ), `daily_indicators` (close, sma_200), `stocks` (market, delisted_at) |
| 출력 | `market_context_daily` 테이블 — 매일 KOSPI 1 행 + KOSDAQ 1 행 = 2 행 |
| 시장 단위 | KOSPI 와 KOSDAQ **각각 별도** — 책 원칙 ("거래하는 종목 유형을 대표하는 지수 추적") + 한국 시장의 명확한 분기점 |
| Breadth 단위 | **시장별** (KOSPI 행 = KOSPI 종목 breadth, KOSDAQ 행 = KOSDAQ 종목 breadth) |
| 아키텍처 | Python 파이프라인, #1/#1.5/#2 와 동일 패턴 (compute/load/store/modes) |
| 적재 모드 | 3 모드 — backfill / incremental / full-refresh |
| 외부 IO | 없음 (DB-to-DB) |
| 임계값 출처 | 책 + community standard 명시 (`computation_notes` 컬럼에 기록) |

## 3. 코드 구조

```
kr_pipeline/
├── market_context/                       # 신규
│   ├── __init__.py
│   ├── __main__.py                       # argparse 진입점
│   ├── modes.py                          # 3 모드 분기 + 오케스트레이션
│   ├── compute/                          # 순수 함수
│   │   ├── __init__.py
│   │   ├── distribution_day.py
│   │   ├── follow_through.py
│   │   ├── status.py
│   │   └── breadth.py
│   ├── load.py                           # index_daily, daily_indicators SELECT
│   └── store.py                          # market_context_daily UPSERT
└── (기존 모듈 변경 없음)

tests/
├── test_market_context_distribution_day.py    # ~5 tests
├── test_market_context_follow_through.py      # ~5 tests
├── test_market_context_status.py              # ~7 tests
├── test_market_context_breadth.py             # ~3 tests
├── test_market_context_modes.py               # ~3 tests
└── test_market_context_integration.py         # ~2 tests
```

총 ~25 신규 테스트.

### 진입점

```bash
# 1회성 백필
python -m kr_pipeline.market_context --mode=backfill

# 매일 증분
python -m kr_pipeline.market_context --mode=incremental --window-days=30

# 월 1회 재적재 (수정종가/지표 변경 흡수)
python -m kr_pipeline.market_context --mode=full-refresh
```

## 4. DB 스키마

```sql
CREATE TABLE IF NOT EXISTS market_context_daily (
    date                             DATE          NOT NULL,
    index_code                       VARCHAR(10)   NOT NULL,           -- '1001' (KOSPI) / '2001' (KOSDAQ)
    current_status                   VARCHAR(20)   NOT NULL,           -- 4 enum values
    distribution_day_count_last_25   SMALLINT,
    last_follow_through_day          DATE,                             -- nullable
    days_since_follow_through        SMALLINT,                         -- nullable
    pct_stocks_above_200d_ma         NUMERIC(5,2),                     -- 해당 index 시장의 활성 종목 중 비율
    computation_notes                TEXT,                             -- 사용된 임계값 JSON
    updated_at                       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (date, index_code)
);
CREATE INDEX IF NOT EXISTS idx_market_context_date ON market_context_daily(date);
```

### `current_status` enum 값

- `"confirmed_uptrend"` — 상승 추세 확정 (FTD 이후 정상)
- `"rally_attempt"` — 하락 후 반등 시도 중, FTD 미확정
- `"correction"` — 고점 대비 조정 중 (-5% ~ -15%)
- `"downtrend"` — 하락 추세 (-15% 이상 또는 SMA200 하회 + SMA50 < SMA200)

### `computation_notes` 형식

JSON 문자열로 사용된 임계값 기록 (향후 튜닝 추적):

```json
{
  "distribution_day_pct_threshold": -0.2,
  "ftd_pct_threshold": 1.4,
  "ftd_rally_window_min": 3,
  "ftd_rally_window_max": 15,
  "ftd_lookback_days": 90,
  "correction_off_high_pct": -10,
  "downtrend_off_high_pct": -15,
  "dist_count_threshold_for_ftd_invalidation": 6
}
```

## 5. 계산 로직

### 5.1 분포일 (Distribution Day)

**정의** (O'Neil/Kacher):
- 종가가 전일 대비 **−0.2% 이상 하락**
- 거래량이 전일보다 많음

```python
# compute/distribution_day.py
def is_distribution_day(today_close, today_volume, yesterday_close, yesterday_volume) -> bool:
    pct_change = (today_close - yesterday_close) / yesterday_close * 100
    return pct_change <= -0.2 and today_volume > yesterday_volume


def count_distribution_days(index_df: pd.DataFrame, end_idx: int, lookback: int = 25) -> int:
    """end_idx 기준 직전 lookback 세션 내 분포일 카운트.
    
    index_df 는 date 정렬된 (close, volume) 시계열.
    """
```

**임계값 출처**: −0.2% 는 IBD 표준 (Kacher 는 −0.1% 까지도 사용, 더 민감). community standard.

### 5.2 Follow-Through Day (FTD)

**정의** (Morales/Kacher 갱신):
- 지수 상승 **+1.4% 이상** (O'Neil 원래 1.0%, 변동성 증가로 상향)
- 거래량이 전일보다 많음
- 단순 반등 후 3-15 세션 사이 발생 (rally attempt 기간)

```python
# compute/follow_through.py
def detect_last_ftd(index_df: pd.DataFrame, end_idx: int, lookback_days: int = 90) -> date | None:
    """가장 최근 유효 FTD 날짜 반환. 없으면 None.
    
    조건:
    1. (today.close / yesterday.close - 1) >= 0.014
    2. today.volume > yesterday.volume
    3. 직전 15 세션 내 저점이 존재하고, 그 저점 이후 3-15 세션 안에 위치
    """
```

**임계값 출처**: 1.4% 는 Kacher 권장 (O'Neil 1.0% 너무 민감). 3-15 세션은 책 명시.

### 5.3 Current Status 결정 (우선순위 룰)

```python
# compute/status.py
def determine_status(
    close: float,
    sma_50: float | None,
    sma_200: float | None,
    pct_off_yearly_high: float,
    dist_count: int,
    last_ftd_date: date | None,
    today_date: date,
) -> str:
    """6 룰 우선순위 평가."""
    days_since_ftd = (today_date - last_ftd_date).days if last_ftd_date else None
    
    # 1. downtrend
    if (sma_200 is not None and sma_50 is not None 
        and close < sma_200 and sma_50 < sma_200 
        and pct_off_yearly_high < -15):
        return "downtrend"
    
    # 2. correction (가격 기준)
    if pct_off_yearly_high < -10 and sma_50 is not None and close < sma_50:
        return "correction"
    
    # 3. correction (FTD 무효화)
    if dist_count >= 6 and last_ftd_date and days_since_ftd > 10:
        return "correction"
    
    # 4. confirmed_uptrend
    if (last_ftd_date and days_since_ftd is not None and days_since_ftd <= 90
        and sma_50 is not None and close > sma_50 and dist_count < 6):
        return "confirmed_uptrend"
    
    # 5. rally_attempt (close > sma_50 인데 FTD 없거나 오래됨)
    if sma_50 is not None and close > sma_50 and (last_ftd_date is None or days_since_ftd > 90):
        return "rally_attempt"
    
    # 6. fallback
    if sma_50 is not None and close > sma_50:
        return "rally_attempt"
    return "correction"
```

### 5.4 Breadth (시장별)

**정의**: 해당 시장 (KOSPI 또는 KOSDAQ) 의 활성 (`delisted_at IS NULL`) 종목 중 `adj_close > sma_200` 비율.

```python
# compute/breadth.py
def compute_breadth(daily_indicators_rows: list[dict]) -> float | None:
    """입력: 특정 (시장, 날짜) 의 daily_indicators 행들 (adj_close, sma_200).
    
    sma_200 NULL 종목은 제외 (lookback 부족 — 상장 1년 미만).
    
    return: % (소수 1자리), 데이터 0 행이면 None.
    """
    valid = [r for r in daily_indicators_rows if r['sma_200'] is not None]
    if not valid:
        return None
    above = sum(1 for r in valid if r['adj_close'] > r['sma_200'])
    return round(above / len(valid) * 100, 1)
```

**SQL 로 구현 (성능)**:
```sql
SELECT 
    s.market,
    COUNT(*) FILTER (WHERE i.adj_close > i.sma_200) * 100.0 / NULLIF(COUNT(*), 0) AS breadth_pct
FROM daily_indicators i
JOIN stocks s ON s.ticker = i.ticker
WHERE i.date = $1
  AND i.sma_200 IS NOT NULL
  AND s.delisted_at IS NULL
GROUP BY s.market;
```

KOSPI 행에는 KOSPI 종목만, KOSDAQ 행에는 KOSDAQ 종목만 — payload_builder 가 종목의 시장에 매칭되는 row 만 조회해서 사용.

## 6. 데이터 흐름 (모드별)

### Phase 구조 (단일 phase)

#2 지표 와 달리 universe 단위 percentile 계산 없음. 날짜별로 독립 계산 가능.

```
각 (date, index_code) 에 대해:
  1. index_daily 시계열 로드 (FTD lookback 90일 + SMA200 lookback 252일 = ~342일 buffer)
  2. distribution_day 카운트 (최근 25 세션)
  3. FTD 감지 (최근 90 세션)
  4. current_status 결정 (close, sma_50, sma_200, off_high, dist, ftd 입력)
  5. breadth 계산 (해당 시장 daily_indicators 조회)
  6. UPSERT market_context_daily
```

### `--mode=backfill`

```
start = (SELECT MIN(date) FROM index_daily)
end = today - 1
for date in start..end:
    for index_code in ('1001', '2001'):
        compute and upsert
```

### `--mode=incremental --window-days=30`

```
load_start = today - 30 - LOOKBACK_DAYS   # LOOKBACK = max(252, 90) = 252
load_end = today
upsert_start = today - 30

# 282 일치 SELECT, 30 일치만 UPSERT
```

### `--mode=full-refresh`

```
backfill 과 동일 범위. 모든 (date, index_code) UPSERT.
```

### 의존 데이터

| 입력 | 출처 | 필요 컬럼 |
|---|---|---|
| index_daily | #1 | date, close, volume (index_code 별) |
| daily_indicators | #2 | date, ticker, adj_close, sma_200 (breadth 용) |
| stocks | #1 | ticker, market, delisted_at (활성 universe 필터) |

### 종목 단위 처리 vs 날짜 단위 처리

본 파이프라인은 **날짜 단위 처리** (#2 의 Phase B 와 비슷). 종목별 순차 처리 아님.

- 한 날짜에 KOSPI + KOSDAQ 2 행 생성
- 종목 universe 변경 (상장폐지 등) 은 자연스럽게 흡수 (매번 stocks JOIN)

### Cron 등록

```cron
TZ=Asia/Seoul

# 평일 19:30 — 일봉 지표 19:00 의 30 분 후
30 19 * * 1-5  cd $PROJECT_DIR && uv run python -m kr_pipeline.market_context --mode=incremental --window-days=30 >> $LOG_DIR/market_context.log 2>&1

# 매월 1일 03:30 — 일봉 지표 full-refresh 03:00 의 30 분 후
30  3 1 * *    cd $PROJECT_DIR && uv run python -m kr_pipeline.market_context --mode=full-refresh >> $LOG_DIR/market_context.log 2>&1
```

## 7. 에러 처리 / 멱등성 / Sanity

### 멱등성

- UPSERT: `ON CONFLICT (date, index_code) DO UPDATE SET ...`
- 같은 명령 두 번 = 같은 결과

### 트랜잭션 단위

- 날짜 단위 commit (한 날짜의 KOSPI + KOSDAQ 2 행 처리 후 commit)
- 한 날짜 실패해도 다른 날짜 보존

### 부분 실패 + 끝-of-run 재시도

#1, #1.5, #2 와 동일 패턴. Phase 가 단일이라 코드 간단.

### NULL 처리

- `last_follow_through_day = NULL` 인 경우 자연스러움 (FTD 없음)
- `days_since_follow_through = NULL` 일 때도 자연스러움
- `pct_stocks_above_200d_ma = NULL` 가능 — 해당 시장에 sma_200 계산된 종목 0 개일 때 (백필 초기)
- `sma_50` / `sma_200` NULL 입력 시 status 결정 룰이 분기 처리 (`if ... is not None`)

### Sanity 검증

`_run_sanity_checks` 에 추가:

| 검증 | 임계값 |
|---|---|
| 행 카운트 | `len = 2 × 처리_날짜수` 인지 (KOSPI + KOSDAQ 양쪽 다 만들어졌나) |
| status 분포 | 4 enum 외 값 없음 (코드 검증, 정상 작동 시 항상 만족) |
| breadth 범위 | 0 ≤ pct_stocks_above_200d_ma ≤ 100 |
| dist_count 범위 | 0 ≤ count ≤ 25 |
| status 일관성 | downtrend 인데 breadth > 80 같은 모순 발견 시 경고 (튜닝 단서) |

경고는 `pipeline_runs.error` 에 JSON 으로 기록.

## 8. 테스팅 전략

### 테스트 계층

| 파일 | 테스트 대상 | 개수 |
|---|---|---|
| `test_market_context_distribution_day.py` | is_distribution_day, count_distribution_days | ~5 |
| `test_market_context_follow_through.py` | detect_last_ftd | ~5 |
| `test_market_context_status.py` | determine_status (6 룰 + edge cases) | ~7 |
| `test_market_context_breadth.py` | compute_breadth | ~3 |
| `test_market_context_modes.py` | compute_date_range | ~3 |
| `test_market_context_integration.py` | end-to-end with DB | ~2 |

### 통합 테스트 (예시)

```python
def test_backfill_end_to_end(db):
    """index_daily + daily_indicators + stocks 시드 → backfill → market_context_daily 검증."""
    # 시드: 5 거래일 × 2 종목 × 2 시장
    # backfill 실행
    # 검증:
    #   - 5 일 × 2 index = 10 행 생성
    #   - current_status enum 값
    #   - breadth 0~100 범위
    #   - pipeline_runs success

def test_incremental_idempotent(db):
    """같은 incremental 두 번 → 결과 동일"""
```

### 단위 테스트 (status 결정 - 가장 두텁게)

```python
# 6 룰 각각 + boundary
test_status_downtrend_basic()
test_status_correction_off_high_basic()
test_status_correction_dist_invalidates_ftd()
test_status_confirmed_uptrend_basic()
test_status_rally_attempt_no_ftd()
test_status_rally_attempt_old_ftd()
test_status_fallback_below_sma50_returns_correction()
```

## 9. 사용자 spec 에서 채택 / 변경 / 제외한 항목

### 채택 (그대로)
- `current_status` 4 enum 값
- `distribution_day_count_last_25_sessions` 정의
- `last_follow_through_day` 정의
- `days_since_follow_through` 정의
- 임계값들 (-0.2%, 1.4%, -10%, -15%, 6, 25 세션, 90 일)
- `computation_notes` JSON 기록 패턴

### 변경
- `pct_stocks_above_200d_ma` 를 **시장별로 분리** (사용자 spec 은 글로벌 합산이었음 — 사용자 직접 변경 요청)
- `index_symbol` (string) → `index_code` (varchar(10), 우리 codebase 의 1001/2001 컨벤션)
- 모드 / cron 패턴 → 우리 #2 패턴 채택 (사용자 spec 은 단순 batch)

### 제외 (다른 subproject)
- "A 프로젝트" 언급 — 우리 codebase 와 무관
- DART API / corporate actions 코드 — `#2.6` 에서 처리
- Anthropic API / LLM 호출 — `#4` 에서 처리
- payload.json 통합 — `#3` 에서 처리

## 10. 범위 밖 (Out of Scope)

- 인덱스 자체의 지표 (`index_indicators` 같은 테이블 등) — 본 #2.5 는 시장 추세만
- 글로벌 합산 breadth (KOSPI + KOSDAQ 통합) — 시장별만
- 분봉/주봉 단위 시장 컨텍스트 — 일봉만
- ML 기반 status 분류 — 룰 기반만
- 사용자 설정 가능한 임계값 — 코드 상수
- 실시간 갱신 — 일봉 마감 후 배치만

## 11. 후속 작업

1. `writing-plans` 스킬로 구현 계획 (~7-8 task) 작성
2. `subagent-driven-development` 으로 자율 실행
3. 검증 후 `#2.6` (Corporate Actions Fetcher) 진행
