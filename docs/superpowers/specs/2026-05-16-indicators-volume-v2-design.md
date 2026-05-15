# 지표 생성 V2: 거래량 지표 추가 설계

- **상태**: Design
- **작성일**: 2026-05-16
- **범위**: 서브프로젝트 #2 의 V2 확장 (거래량 지표 추가)
- **선행 의존**: #1 (일봉), #1.5 (주봉), #2 (지표 기본) — 모두 완료됨

## 1. 배경 및 목적

#2 의 최종 코드 리뷰에서 "거래량 지표는 미너비니/오닐 모두 강조하는 핵심 framework 인데 누락됨, V2 우선순위 ↑" 로 식별. 본 V2 는 거래량 기반 지표 6 종 (일봉) + 3 종 (주봉) 을 기존 `daily_indicators` / `weekly_indicators` 테이블에 컬럼 추가 형태로 확장.

새 테이블, 새 패키지, 새 모드 없음 — `compute/volume.py` 한 파일 추가 + 기존 `load.py`, `store.py`, `modes.py` 에 컬럼 통합.

후속 의존:
- #3 (UI) — 거래량 차트 오버레이, pocket pivot 종목 필터링
- #4 (Claude Code CLI 자동 분석) — breakout 거래량 컨텍스트, distribution day 누적 → 시장 추세 판정

## 2. 가격·거래량 컨벤션 (CRITICAL)

#2 의 가격 컨벤션 (모든 지표는 `adj_close` 사용) 에 **거래량 split-adjustment** 추가:

### 거래량 분할 보정

**거래량은 분할 영향을 받는다** (스펙 v1 초안의 "splits 영향 없음" 은 오류, 정정).

- 2:1 분할 → 발행 주식 수 2 배 → 분할 후 거래량도 자연히 더 큼
- 50일 평균이 분할 시점을 가로지르면 **불연속 발생** → pocket pivot, volume_ratio 가짜 신호

### 보정 공식

별도 데이터 소스 / split 이벤트 테이블 없이, 이미 있는 `close` 와 `adj_close` 의 비율로 derive:

```
split_factor = close / adj_close
adj_volume   = volume * split_factor
```

검증:
- 분할 전 어느 날: close=100, adj_close=50 → split_factor = 2.0 → adj_volume = volume × 2
- 분할 후 모든 날: close = adj_close → split_factor = 1.0 → adj_volume = volume

결과: 분할 시점 양쪽이 동일 스케일로 정규화됨.

### 컬럼 명명 컨벤션

`daily_indicators` / `weekly_indicators` 는 이미 "모든 값이 adjusted 기반" 인 분석 레이어 (adj_close, 모든 SMA, RS Line). 일관성 유지 위해 거래량 컬럼명도 `volume`, `avg_volume_50d` 등 **suffix 안 붙임**. split-adjusted 사용은 본 §2 에서 표명.

`daily_prices.volume` (raw) 은 본 V2 에서 직접 노출 안 함 — 분석 쿼리는 항상 `daily_indicators.volume` (adjusted) 사용.

### 알려진 한계

- **주봉 mid-week split**: 분할이 주중에 발생하면 `weekly_prices.volume` (raw daily 거래량의 주간 합) 에 부분 보정 오류 가능. 보정 공식 `weekly.volume * (close/adj_close)` 가 주중 분할 시점 데이터에 작은 오차 발생. 한국 시장 분할 빈도가 낮아 영향 미미 — 문서화 후 진행.
- 배당 변경은 거래량에 영향 없음 (가격에만). 즉 우리 보정은 "분할 보정만" 의미.

## 3. 결정 사항 요약

| 항목 | 결정 |
|---|---|
| 아키텍처 | #2 의 확장 — `kr_pipeline/indicators/compute/volume.py` 추가, 기존 modes/load/store 통합 |
| 입력 | `daily_prices.{close, adj_close, volume}` 또는 `weekly_prices.{...}` |
| 출력 | `daily_indicators` / `weekly_indicators` 에 컬럼 추가 |
| 보정 방식 | `adj_volume = volume * (close / adj_close)` |
| 컬럼명 | suffix 없음 (adjusted 사용 implicit, §2 명시) |
| 적재 모드 | #2 와 동일 — 별도 모드/진입점 없음 |

## 4. 추가 컬럼

### `daily_indicators` (+6 컬럼)

```sql
ALTER TABLE daily_indicators
    ADD COLUMN IF NOT EXISTS volume                    NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS avg_volume_50d            NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS volume_ratio_50d          NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS pocket_pivot_flag         BOOLEAN,
    ADD COLUMN IF NOT EXISTS volume_dry_up_flag        BOOLEAN,
    ADD COLUMN IF NOT EXISTS up_down_volume_ratio_50d  NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS distribution_day_flag     BOOLEAN;

-- pocket pivot 종목 빠른 조회용 파셔널 인덱스
CREATE INDEX IF NOT EXISTS idx_daily_indicators_pocket_pivot 
    ON daily_indicators(date) WHERE pocket_pivot_flag = TRUE;

-- 시장 distribution day 누적 집계용 (#4 의 시장 추세 판정 입력)
CREATE INDEX IF NOT EXISTS idx_daily_indicators_distribution 
    ON daily_indicators(date) WHERE distribution_day_flag = TRUE;
```

### `weekly_indicators` (+4 컬럼)

```sql
ALTER TABLE weekly_indicators
    ADD COLUMN IF NOT EXISTS volume                    NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS avg_volume_10w            NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS volume_ratio_10w          NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS up_down_volume_ratio_10w  NUMERIC(10,4);
```

주봉에는 pocket_pivot / volume_dry_up / distribution_day 제외 — 책의 "지난 10 일", "25 영업일 누적" 등이 일봉 전제. 주봉 VDU 는 별도 컬럼 없이 `volume_ratio_10w < 0.5` 쿼리로 도출 가능.

### 타입 결정 요지

- `NUMERIC(20,2)` for volume — split-adjusted 결과 소수 가능 (5:4 분할 = ×1.25)
- `NUMERIC(10,4)` for ratios — 음수 비율은 없지만 큰 값 (100+) 가능. 소수 4 자리로 정밀도 확보
- BOOLEAN for flags — 표준
- 모든 컬럼 NULLABLE — lookback 부족 시 NULL ("insufficient history")

### 의도적으로 안 함 (YAGNI)

- OBV, A/D Line, VWAP, climax volume, stalling day, churning — 책 외 지표 또는 다른 지표 + 가격 액션 조합으로 LLM 추론 가능
- 거래대금 (value) 기반 지표 — 거래량 framework 가 책 표준
- 주봉 pocket pivot / distribution day — 책 원의 일봉 전제

## 5. 계산식 (모든 지표는 adj_volume 기준)

```python
# 사전: split-adjusted volume
split_factor = close / adj_close
adj_volume = volume * split_factor

# 사전: up/down day 판정
is_up_day = adj_close > adj_close.shift(1)
is_down_day = adj_close < adj_close.shift(1)
```

### 1. `avg_volume_50d` — 50 영업일 평균 거래량

```python
avg_volume_50d = adj_volume.rolling(window=50, min_periods=50).mean()
```

### 2. `volume_ratio_50d` — 오늘 / 50일 평균

```python
volume_ratio_50d = adj_volume / avg_volume_50d
# 50일 평균 NaN 또는 0 → 결과 NaN/inf. inf 발생 시 → NaN 으로 마스킹 (실제로 평균이 0 인 케이스는 거의 없음)
```

### 3. `pocket_pivot_flag` — Morales & Kacher 정의

```python
# 지난 10일 중 하락일들의 adj_volume 최대값. shift(1) 로 어제까지의 lookback.
down_adj_vol_max_10 = adj_volume.where(is_down_day).rolling(window=10, min_periods=1).max().shift(1)

pocket_pivot_flag = (
    is_up_day                                       # (1) 상승일
    & (adj_volume >= down_adj_vol_max_10)           # (2) 거래량 ≥ 지난 10일 down 최대 (>= per 책 원문)
    & (adj_close > sma_50)                          # (3) 50일선 위 (책 필수 조건)
)
```

**Edge case**: 지난 10 일 중 하락일이 없으면 `down_adj_vol_max_10 = NaN` → `adj_volume >= NaN` = False → flag=False. 10 일 연속 무하락은 climax run 의심 영역이라 신호 안 잡혀도 무방 (실제로는 매우 강세 종목이긴 함).

### 4. `volume_dry_up_flag` — community standard 50% 임계

```python
volume_dry_up_flag = adj_volume < avg_volume_50d * 0.5
```

50% 는 책 명시 임계가 아닌 community standard. 향후 튜닝 여지 있음.

### 5. `up_down_volume_ratio_50d` — O'Neil A/D 의 simplification

```python
up_vol_50 = adj_volume.where(is_up_day, 0).rolling(window=50, min_periods=50).sum()
down_vol_50 = adj_volume.where(is_down_day, 0).rolling(window=50, min_periods=50).sum()
up_down_volume_ratio_50d = up_vol_50 / down_vol_50.where(down_vol_50 > 0)
# down_vol_50 = 0 (50일 무하락) → NaN → DB NULL
```

IBD proprietary 공식과는 다름 (단순 합 비율).

### 6. `distribution_day_flag` — O'Neil 정의

```python
distribution_day_flag = is_down_day & (adj_volume > avg_volume_50d * 1.25)
```

1.25x 임계는 책 명시 아닌 IBD/community 관행. 종목 레벨에서는 단순 `is_down_day` 사용 (시장 레벨에서는 -0.2% 임계 적용 — #4 에서 시장 지수 distribution day 집계 시 별도 처리).

### 주봉 버전 (3 지표)

같은 패턴으로 일봉 50 → 주봉 10 (= 50 영업일 등가):

```python
avg_volume_10w = weekly_adj_volume.rolling(window=10, min_periods=10).mean()
volume_ratio_10w = weekly_adj_volume / avg_volume_10w
up_vol_10w = weekly_adj_volume.where(is_up_week, 0).rolling(window=10, min_periods=10).sum()
down_vol_10w = weekly_adj_volume.where(is_down_week, 0).rolling(window=10, min_periods=10).sum()
up_down_volume_ratio_10w = up_vol_10w / down_vol_10w.where(down_vol_10w > 0)
```

## 6. 출처 정리 (spec 명시용)

| 지표 | 출처 |
|---|---|
| `avg_volume_50d`, `volume_ratio_50d` | O'Neil "How to Make Money in Stocks" — 50 영업일 평균을 institutional 활동 baseline 으로 사용 |
| `pocket_pivot_flag` | **Morales & Kacher "Trade Like an O'Neil Disciple"** (Minervini 아님). 책 원문: "up-volume equal to or greater than the largest down-volume day". `close > sma_50` 조건 책 명시 ("rare cases" 외 50일선 아래 PP 는 risky 라고 경고). 변동성 큰 종목은 lookback 11~15 일 권장 (본 V2 는 10 일로 시작, 향후 튜닝 가능) |
| `volume_dry_up_flag` | O'Neil HTMM 차트 라벨로 다수 등장 ("Volume dry-up on pullback", "Volume dry-up in handle" — Compaq/Macromedia/Amazon/Comverse). Minervini 책에서도 "below 50-day average... extremely low... dry up to a trickle" 언급. **임계 50% 는 책 명시 아닌 community standard** |
| `up_down_volume_ratio_50d` | O'Neil Accumulation/Distribution Rating 의 단순화. **IBD 의 proprietary 공식과는 다름** (책 원문: "highly accurate proprietary formula... not based on simple up/down volume calculations") |
| `distribution_day_flag` | O'Neil HTMM — 시장 추세 판정 (M of CAN SLIM) 의 핵심. 최근 25 영업일 누적 5~6 일 → 시장 약세 신호. **1.25x 임계는 책 명시 아닌 IBD/community 관행** |

## 7. 코드 구조 변경

### 새 파일

`kr_pipeline/indicators/compute/volume.py` — 거래량 지표 순수 함수

```python
"""거래량 지표 (split-adjusted) 순수 함수. 입력은 adj_close, close, raw volume, sma_50."""

def split_adjusted_volume(volume, close, adj_close) -> pd.Series: ...
def avg_volume(adj_volume, window) -> pd.Series: ...
def volume_ratio(adj_volume, avg_volume) -> pd.Series: ...
def pocket_pivot(is_up_day, adj_volume, sma_50, adj_close, lookback=10) -> pd.Series: ...
def volume_dry_up(adj_volume, avg_volume, threshold=0.5) -> pd.Series: ...
def up_down_volume_ratio(adj_volume, is_up_day, is_down_day, window) -> pd.Series: ...
def distribution_day(is_down_day, adj_volume, avg_volume, threshold=1.25) -> pd.Series: ...
```

### 수정되는 파일

- `kr_pipeline/db/schema.sql` — 끝에 ALTER TABLE / CREATE INDEX 추가
- `kr_pipeline/indicators/load.py` — `load_daily_prices` 가 `close, volume` 도 가져옴 (현재는 adj_close 만), 주봉도 동일
- `kr_pipeline/indicators/store.py` — `PHASE_A_COLUMNS_DAILY` / `PHASE_A_COLUMNS_WEEKLY` 에 컬럼 추가
- `kr_pipeline/indicators/modes.py` — `_process_ticker_daily` / `_process_ticker_weekly` 에 volume 계산 통합

### 변경 없음

- `__main__.py`, `Mode`, `Target`, `run_daily`, `run_weekly` 시그니처 — V2 추가가 기존 흐름에 투명하게 통합
- 다른 compute 모듈 (sma, high_low, rs_line, rs_rating, minervini)
- cron 스케줄 — 같은 명령으로 거래량 지표도 자동 채워짐

## 8. 데이터 흐름 (변경 사항)

### Phase A 종목별 처리 — 거래량 추가

기존:
1. SELECT daily_prices (date, adj_close)
2. SELECT index_daily (date, close)
3. compute SMA, 52w, RS Line, 1y return, minervini c1-c7
4. UPSERT Phase A columns

V2 추가:
1. SELECT daily_prices에 **`close, volume` 도 가져옴**
2. compute volume 지표 (split_adjusted_volume → 6 지표)
3. UPSERT 시 새 컬럼들 포함

Phase B (RS Rating) 와 Phase C (minervini c8 + pass) 는 변경 없음.

## 9. 에러 처리 / 멱등성 / Sanity

### 기존 패턴 그대로

- UPSERT 멱등성 — V2 컬럼들도 같은 ON CONFLICT 절에 포함
- 종목 단위 commit, 끝-of-run 1회 재시도
- NULL 전파 (lookback 부족 시)

### 새 sanity 체크 (선택)

`_run_sanity_checks_daily` 에 추가 가능:
- `avg_volume_50d IS NULL` 비율 (정상 5-10%, lookback 부족)
- pocket pivot 발생률 (정상 1-5% — 너무 0% 면 계산 버그 의심)
- distribution day 발생률 (정상 5-15%)

본 V2 spec 에서 권장 정도, 필수 아님. 첫 라이브 스모크 결과 보고 결정.

## 10. 테스팅 전략

### `tests/test_indicators_volume.py` 신규 — ~14 테스트

```python
# split-adjusted volume
def test_split_adjusted_volume_basic(): ...
def test_split_adjusted_volume_continuous_across_split(): ...

# avg_volume / volume_ratio
def test_avg_volume_basic(): ...
def test_avg_volume_insufficient_history_returns_nan(): ...
def test_volume_ratio_basic(): ...

# pocket pivot
def test_pocket_pivot_basic(): ...                          # up + vol >= max down + close > sma_50
def test_pocket_pivot_fails_below_sma_50(): ...
def test_pocket_pivot_uses_gte_not_gt(): ...                # >= not >, per book
def test_pocket_pivot_no_down_days_in_lookback(): ...       # NaN max → False (climax suspect)

# volume dry up
def test_volume_dry_up_threshold_50pct(): ...

# up/down volume ratio
def test_up_down_volume_ratio_basic(): ...
def test_up_down_volume_ratio_zero_division(): ...          # all-up 50 days → NULL

# distribution day
def test_distribution_day_basic(): ...
def test_distribution_day_threshold_1_25x(): ...
```

### 통합 테스트는 기존 `test_indicators_integration.py` 확장

- `test_daily_backfill_end_to_end` 에 volume 컬럼 검증 assertion 추가
- 거래량 지표만의 별도 통합 테스트는 불필요

### 단위 테스트만 약 14 추가, 통합 +0~2 새 → 총 +14~16 (#2 후 117 → ~131-133)

## 11. 범위 밖 (Out of Scope)

V2 에서 다루지 않음 (V3+ 가능성):
- 거래대금 (value) 기반 지표
- 시간대별 거래량 (분봉)
- 거래량 가중 가격 (VWAP, TWAP)
- OBV (On-Balance Volume), A/D Line, Money Flow
- Climax volume, stalling day, churning (다른 지표 + 가격 액션 조합으로 LLM 추론 가능)
- 주봉 pocket pivot / distribution day (책 외 해석)
- 시장 지수 레벨 distribution day 누적 (#4 의 별도 워크플로우)

## 12. 후속 작업

본 spec 승인 후:
1. `writing-plans` 스킬로 V2 구현 계획 (6 task) 작성
2. `subagent-driven-development` 으로 구현
3. 검증 후 #3 (UI) 또는 #4 (자동 분석) 진행
