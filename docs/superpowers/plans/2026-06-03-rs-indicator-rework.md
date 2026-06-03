# RS 지표 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** RS Rating을 IBD 가중 강도로 교체하고, RS Line 분모를 KOSPI 단일로 통일하며, O'Neil 7개월 하락 게이트(pure-declining)를 후보 하드 필터로 추가하고, Minervini 6주/13주 우상향 신호를 기울기 기반으로 재정의해 LLM에 전달한다.

**Architecture:** 기존 indicators 파이프라인(`kr_pipeline/indicators/`)의 compute 함수만 교체/추가하고 백분위·UPSERT 골격은 재사용한다. 7개월 게이트는 주봉에서 계산해 daily 행에 미러링하여 기존 `daily_indicators` 단일 테이블 후보 쿼리를 유지한다. RS 윈도우 상수를 `thresholds.py`(SSOT)로 추출하고, 정의 변경에 맞춰 전체 히스토리를 재계산한다.

**Tech Stack:** Python (pandas, numpy, psycopg), PostgreSQL, pytest, FastAPI(payload), TypeScript(생성물).

**설계 출처:** `docs/superpowers/specs/2026-06-03-rs-indicator-rework-design.md` (§ 참조는 그 문서 기준).

---

## 사전 결정 (설계 §9 확정값)

- 7개월 윈도우 = **30주** / 게이트 배선 = **daily 미러링** / `rs_line_in_decline_7m` → **`rs_line_not_declining_7m` 새 컬럼 교체(TRUE=건강)** / 히스토리 = **전체 재계산**.
- SF 수식 = 가격비율 합산형 / 데이터 갭 = NaN(보간 X) / weekly C8 `70` → `C8_RS_RATING_MIN` 통일.

## 파일 구조 (생성/수정)

| 파일 | 책임 | 변경 |
|---|---|---|
| `kr_pipeline/common/thresholds.py` | RS 윈도우 상수 SSOT | 추가 |
| `kr_pipeline/indicators/compute/rs_rating.py` | IBD SF 산출 | 추가 |
| `kr_pipeline/indicators/compute/rs_line.py` | 기울기 기반 우상향/비하락 | 추가 |
| `kr_pipeline/indicators/modes.py` | 호출부 교체(SF·분모·윈도우·미러) | 수정 |
| `kr_pipeline/indicators/store.py` | 컬럼 목록·미러 UPDATE·weekly 상수화 | 수정 |
| `kr_pipeline/llm_runner/load.py` | 후보 쿼리 게이트 AND | 수정 |
| `kr_pipeline/db/schema.sql` | 컬럼 교체 + 마이그레이션 | 수정 |
| `api/services/payload_builder.py` | RS boolean 페이로드 추가 | 수정 |
| `prompts/analyze_chart_v3.md` | §4.6 boolean 입력 명시 | 수정 |
| `scripts/export_thresholds.py` | (재실행만) | — |
| `docs/superpowers/threshold-change-checklist` 항목 | 의존성 맵 작성 | 신규 |
| `tests/test_indicators_rs_rating.py` | SF 테스트 | 신규 |
| `tests/test_indicators_rs_line.py` | 기울기 함수 테스트 | 수정 |

---

## Task 0: 베이스라인 + threshold-change-checklist

**Files:**
- Create: `docs/superpowers/specs/2026-06-03-rs-threshold-change-checklist.md`

- [ ] **Step 1: 베이스라인 테스트 기록**

Run: `uv run pytest tests/ -q 2>&1 | tail -15`
Expected: 사전 isolation fail ~25개(weekly/llm/ohlcv DB 격리). 이 수를 기준선으로 메모. 이후 작업이 이 수를 늘리면 회귀.

- [ ] **Step 2: threshold-change-checklist 의존성 맵 작성**

`docs/superpowers/threshold-change-checklist.md`(템플릿)를 읽고, 본 작업의 2축 의존성 맵을 새 문서로 작성한다. 최소 포함 항목:

```markdown
# RS 지표 개선 — threshold-change-checklist (2026-06-03)

## 변경 상수
- 신규: RS_LINE_UPTREND_SHORT_WEEKS=6, RS_LINE_UPTREND_LONG_WEEKS=13, RS_LINE_DECLINE_GATE_WEEKS=30
- 계산 로직 변경: rs_rating 입력(1년수익률 → IBD SF), rs_line 분모(시장별 → KOSPI 단일),
  uptrend 판정(MA위 → 기울기), 7개월 게이트(신고가없음 → pure-declining)

## 축 1 — 이 상수를 소비하는 고정 상수/룰
- C8_RS_RATING_MIN(=70): rs_rating 정의가 바뀌어도 70 임계값 자체는 불변. 단 ≥70 통과 분포가
  최근 모멘텀으로 이동 → 후보 수 재검증 필요(Task 7).
- minervini_pass: c8가 rs_rating 소비. 정의 불연속 → 과거 minervini_pass 재계산 필요(전체 재계산).
- 후보 쿼리(load.py): 신규 rs_line_not_declining_7m 게이트 AND 추가 → minervini_pass와 상호작용.

## 축 2 — prompt 임계 텍스트 정합
- analyze_chart_v3.md §4.6 RS Line: boolean 입력 추가(텍스트 동기화).
- §Inputs(line 46) indicator series 목록: RS boolean 추가.

## 충돌 점검 결과
- FTD/distribution 룰과 무관(rs는 종목 레벨, 시장 레벨 미접촉). 충돌 없음.
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-06-03-rs-threshold-change-checklist.md
git commit -m "docs(rs): threshold-change-checklist 의존성 맵"
```

---

## Task 1: RS 윈도우 상수 추출 (thresholds.py)

**Files:**
- Modify: `kr_pipeline/common/thresholds.py` (C8_RS_RATING_MIN 블록 뒤, line 51 이후)
- Test: `tests/test_common_thresholds.py`

- [ ] **Step 1: 상수 존재·값 테스트 작성**

`tests/test_common_thresholds.py` 에 추가:

```python
def test_rs_line_window_constants():
    from kr_pipeline.common import thresholds as t
    assert t.RS_LINE_UPTREND_SHORT_WEEKS == 6
    assert t.RS_LINE_UPTREND_LONG_WEEKS == 13
    assert t.RS_LINE_DECLINE_GATE_WEEKS == 30
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_common_thresholds.py::test_rs_line_window_constants -v`
Expected: FAIL (AttributeError: module has no attribute 'RS_LINE_UPTREND_SHORT_WEEKS')

- [ ] **Step 3: 상수 추가**

`thresholds.py` 의 `C8_RS_RATING_MIN` docstring 블록(line 51) 바로 다음에 삽입:

```python
# ===== RS Line 신호 윈도우 (kr_pipeline/indicators/compute/rs_line.py, modes.py) =====

RS_LINE_UPTREND_SHORT_WEEKS: Final[int] = 6
"""RS Line 단기 우상향 판정 윈도우 (주). Minervini TLSMW Ch.5 criterion 7 주석
'I like to see ... six weeks' — soft 선호 신호(게이트 아님). 일봉은 6주≈30영업일(×5)."""

RS_LINE_UPTREND_LONG_WEEKS: Final[int] = 13
"""RS Line 장기 우상향 판정 윈도우 (주). Minervini 선호 '13 weeks or more'. 일봉 13주≈65영업일(×5)."""

RS_LINE_DECLINE_GATE_WEEKS: Final[int] = 30
"""O'Neil 7개월 하락 게이트 윈도우 (주). HMMS 'L = Leader or Laggard' — RS line 7개월+ 하락 =
laggard. 7개월≈30주(설계 §9.1, 현행 28주에서 변경). 게이트는 주봉에서만 계산."""
```

- [ ] **Step 4: 통과 확인 + export 재생성**

Run: `uv run pytest tests/test_common_thresholds.py::test_rs_line_window_constants -v`
Expected: PASS

Run: `uv run python scripts/export_thresholds.py`
Expected: `Wrote .../thresholds.generated.ts (N constants)` — N이 3 증가. `git diff web/src/data/thresholds.generated.ts` 에 세 상수 추가 확인.

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/common/thresholds.py tests/test_common_thresholds.py web/src/data/thresholds.generated.ts
git commit -m "feat(rs): RS Line 윈도우 상수 SSOT 추출 (6/13/30주)"
```

---

## Task 2: IBD 가중 강도(SF) 계산 함수

**Files:**
- Modify: `kr_pipeline/indicators/compute/rs_rating.py`
- Test: `tests/test_indicators_rs_rating.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_indicators_rs_rating.py` 생성:

```python
import numpy as np
import pandas as pd
from kr_pipeline.indicators.compute.rs_rating import (
    compute_ibd_strength_factor, assign_rs_rating_percentiles,
)


def test_ibd_sf_weights_recent_quarter_double():
    # 가격이 일정하면 모든 비율=1 → SF = 2+1+1+1 = 5
    c = pd.Series([100.0] * 260)
    sf = compute_ibd_strength_factor(c, 63, 126, 189, 252)
    assert sf.iloc[-1] == 5.0


def test_ibd_sf_nan_before_longest_lookback():
    c = pd.Series([100.0] * 260)
    sf = compute_ibd_strength_factor(c, 63, 126, 189, 252)
    assert pd.isna(sf.iloc[251])   # 252 미만 → NaN
    assert not pd.isna(sf.iloc[252])


def test_ibd_sf_nan_when_intermediate_gap():
    # 중간 lookback(126) 지점이 NaN 이면 SF NaN (보간 안 함)
    c = pd.Series([100.0] * 260)
    c.iloc[260 - 1 - 126] = np.nan
    sf = compute_ibd_strength_factor(c, 63, 126, 189, 252)
    assert pd.isna(sf.iloc[-1])


def test_ibd_sf_higher_recent_growth_ranks_higher():
    # 최근 분기 급등 종목이 SF 더 큼 → 백분위 상위
    flat = pd.Series([100.0] * 260)
    recent_pop = flat.copy()
    recent_pop.iloc[-1] = 130.0      # 오늘만 +30%
    sf_flat = compute_ibd_strength_factor(flat, 63, 126, 189, 252).iloc[-1]
    sf_pop = compute_ibd_strength_factor(recent_pop, 63, 126, 189, 252).iloc[-1]
    assert sf_pop > sf_flat
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_indicators_rs_rating.py -v`
Expected: FAIL (ImportError: cannot import name 'compute_ibd_strength_factor')

- [ ] **Step 3: 함수 구현**

`kr_pipeline/indicators/compute/rs_rating.py` 의 `compute_1y_return` 다음에 추가(`compute_1y_return` 은 백테스트 호환 위해 보존):

```python
def compute_ibd_strength_factor(
    adj_close: pd.Series,
    q1: int = 63, q2: int = 126, q3: int = 189, q4: int = 252,
) -> pd.Series:
    """IBD 가중 강도(StrengthFactor) = 가격비율 합산형, 최근 분기 2배 가중.

    SF = 2·(C/C[-q1]) + (C/C[-q2]) + (C/C[-q3]) + (C/C[-q4])
    일봉: q=63/126/189/252, 주봉: q=13/26/39/52.
    네 시점 중 하나라도 결측이면 NaN (보간 안 함 — 설계 §9.2).
    """
    c = adj_close
    sf = (
        2 * (c / c.shift(q1))
        + (c / c.shift(q2))
        + (c / c.shift(q3))
        + (c / c.shift(q4))
    )
    return sf
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_indicators_rs_rating.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/indicators/compute/rs_rating.py tests/test_indicators_rs_rating.py
git commit -m "feat(rs): IBD 가중 강도(SF) 계산 함수"
```

---

## Task 3: RS Rating 입력을 SF로 교체 (modes.py)

**Files:**
- Modify: `kr_pipeline/indicators/modes.py:20` (import), `:189` (daily), `:508` (weekly)

- [ ] **Step 1: import 교체**

`modes.py:20` 을 다음으로 변경:

```python
from kr_pipeline.indicators.compute.rs_rating import compute_ibd_strength_factor, assign_rs_rating_percentiles
```

- [ ] **Step 2: daily 입력 교체 (modes.py:189)**

```python
    # SF (rs_rating 입력) — IBD 가중, 최근 분기 2배
    one_y_ret = compute_ibd_strength_factor(adj_close, 63, 126, 189, 252)
```

(주: 하위 변수명 `one_y_ret` / `one_y_returns_for_phase_b` 는 Phase B 입력일 뿐이라 그대로 두되, 의미가 SF로 바뀜. 혼동 방지 위해 같은 줄 주석만 갱신.)

- [ ] **Step 3: weekly 입력 교체 (modes.py:508)**

```python
    one_y_ret = compute_ibd_strength_factor(adj_close, 13, 26, 39, 52)
```

- [ ] **Step 4: import 정리 확인**

Run: `uv run python -c "import kr_pipeline.indicators.modes"`
Expected: 에러 없음 (`compute_1y_return` 미사용 import 가 modes.py 에 남지 않았는지 확인 — Step 1에서 제거됨).

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/indicators/modes.py
git commit -m "feat(rs): rs_rating 입력을 1년수익률→IBD SF로 교체 (일·주봉)"
```

---

## Task 4: RS Line 분모 KOSPI 단일화 (modes.py)

**Files:**
- Modify: `kr_pipeline/indicators/modes.py:107-113` (상수 추가), `:141-142`(daily), `:476-477`(weekly)

- [ ] **Step 1: KOSPI 단일 분모 상수 추가**

`modes.py` 의 `_market_to_index_code` 함수(line 107) 바로 위에 추가:

```python
KOSPI_INDEX_CODE = "1001"  # RS Line 광역 단일 분모 (설계 D2: 코스피·코스닥 전 종목 공통)
```

- [ ] **Step 2: daily 분모 교체 (modes.py:141-142)**

```python
    index_code = KOSPI_INDEX_CODE  # D2: 종목 시장 무관 KOSPI 단일 분모
    df_idx = load_index_daily(conn, index_code, load_start, load_end)
```

- [ ] **Step 3: weekly 분모 교체 (modes.py:476-477)**

```python
    index_code = KOSPI_INDEX_CODE  # D2: 종목 시장 무관 KOSPI 단일 분모
    df_idx = load_weekly_index(conn, index_code, load_start, load_end)
```

- [ ] **Step 4: import 확인**

Run: `uv run python -c "import kr_pipeline.indicators.modes; print('ok')"`
Expected: `ok` (`_market_to_index_code` 는 남겨두되 RS line 경로에서 미사용).

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/indicators/modes.py
git commit -m "feat(rs): RS Line 분모를 KOSPI 단일로 통일 (D2)"
```

---

## Task 5: 기울기 기반 우상향/비하락 compute 함수

**Files:**
- Modify: `kr_pipeline/indicators/compute/rs_line.py` (numpy import + 함수 추가)
- Test: `tests/test_indicators_rs_line.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_indicators_rs_line.py` 의 import 블록(line 6-12)에 두 함수 추가하고, 파일 끝에 테스트 추가:

```python
# import 블록에 추가:
#   compute_rs_line_uptrend_slope, compute_rs_line_not_declining

def test_uptrend_slope_true_when_rising():
    rs = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5])
    result = compute_rs_line_uptrend_slope(rs, window=3)
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[1])
    assert result.iloc[2] == True   # 0.1,0.2,0.3 기울기>0
    assert result.iloc[4] == True


def test_uptrend_slope_false_when_falling():
    rs = pd.Series([0.5, 0.4, 0.3, 0.2, 0.1])
    result = compute_rs_line_uptrend_slope(rs, window=3)
    assert result.iloc[2] == False


def test_uptrend_slope_false_when_flat():
    # 평평하면 기울기 0 → > 0 아님 → False (MA위 정의와 달라지는 핵심)
    rs = pd.Series([0.5, 0.5, 0.5, 0.5])
    result = compute_rs_line_uptrend_slope(rs, window=3)
    assert result.iloc[2] == False


def test_not_declining_true_for_sideways():
    # 횡보(평평): 하락 아님 → 건강(True). pure-declining 의 핵심.
    rs = pd.Series([0.5] * 6)
    result = compute_rs_line_not_declining(rs, window=4)
    assert result.iloc[5] == True


def test_not_declining_false_for_real_decline():
    # 기울기<0 AND 끝점<시작점 → declining → False
    rs = pd.Series([0.9, 0.8, 0.7, 0.6, 0.5, 0.4])
    result = compute_rs_line_not_declining(rs, window=4)
    assert result.iloc[5] == False


def test_not_declining_nan_before_window():
    rs = pd.Series([0.5, 0.6])
    result = compute_rs_line_not_declining(rs, window=4)
    assert pd.isna(result.iloc[1])
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_indicators_rs_line.py -k "slope or not_declining" -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: 함수 구현**

`kr_pipeline/indicators/compute/rs_line.py` line 4 의 `import pandas as pd` 다음에 `import numpy as np` 추가. 파일 끝에 추가:

```python
def _rolling_slope(rs_line: pd.Series, window: int) -> pd.Series:
    """각 window 구간 선형회귀 기울기. window 미만/결측 포함 시 NaN."""
    x = np.arange(window, dtype=float)

    def _slope(y):
        if np.isnan(y).any():
            return np.nan
        return np.polyfit(x, y, 1)[0]

    return rs_line.rolling(window=window, min_periods=window).apply(_slope, raw=True)


def compute_rs_line_uptrend_slope(rs_line: pd.Series, window: int) -> pd.Series:
    """최근 window 구간 회귀 기울기 > 0 → True (D7). window 미만 NaN.

    '이동평균 위' 정의를 대체 — 평평/스파이크에 False 가 되어 실제 상향만 잡음.
    """
    slope = _rolling_slope(rs_line, window)
    result = slope > 0
    return result.where(slope.notna())


def compute_rs_line_not_declining(rs_line: pd.Series, window: int) -> pd.Series:
    """NOT(기울기<0 AND 끝점<시작점) → True=건강 (D6, pure-declining). window 미만 NaN.

    횡보(기울기≈0)는 건강으로 보존, 실제 하락선만 False.
    끝점 비교는 같은 window 의 첫 점(rs_line.shift(window-1)) 기준.
    """
    slope = _rolling_slope(rs_line, window)
    endpoint_lower = rs_line < rs_line.shift(window - 1)
    declining = (slope < 0) & endpoint_lower
    result = ~declining
    return result.where(slope.notna())
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_indicators_rs_line.py -k "slope or not_declining" -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/indicators/compute/rs_line.py tests/test_indicators_rs_line.py
git commit -m "feat(rs): 기울기 기반 우상향/비하락(pure-declining) compute 함수"
```

---

## Task 6: 기존 우상향 테스트 정리 + 구식 함수 처리

**Files:**
- Modify: `tests/test_indicators_rs_line.py` (구 uptrend/decline 테스트)
- Modify: `kr_pipeline/indicators/compute/rs_line.py` (구 함수 deprecation 주석)

- [ ] **Step 1: 구 MA위 테스트 제거**

`tests/test_indicators_rs_line.py` 에서 `test_rs_line_uptrend_when_above_rolling_mean`, `test_rs_line_uptrend_false_when_below`, `test_rs_line_in_decline_7m_when_high_was_long_ago`, `test_rs_line_in_decline_handles_nan_high_date` 4개 삭제(정의가 교체됨). import 에서 `compute_rs_line_uptrend`, `compute_rs_line_in_decline_7m` 제거.

- [ ] **Step 2: 구 함수 deprecation 주석**

`rs_line.py` 의 `compute_rs_line_uptrend`(line 48) 와 `compute_rs_line_in_decline_7m`(line 60) docstring 첫 줄에 추가:
`"""[DEPRECATED 2026-06-03: 기울기/pure-declining 으로 교체. 미사용.] ..."""`

- [ ] **Step 3: 테스트 통과 확인**

Run: `uv run pytest tests/test_indicators_rs_line.py -v`
Expected: PASS (남은 테스트 전부; 삭제된 4개 없음)

- [ ] **Step 4: Commit**

```bash
git add tests/test_indicators_rs_line.py kr_pipeline/indicators/compute/rs_line.py
git commit -m "refactor(rs): 구 MA위/신고가없음 테스트 정리, 구 함수 deprecate"
```

---

## Task 7: 스키마 컬럼 교체 (rs_line_not_declining_7m)

**Files:**
- Modify: `kr_pipeline/db/schema.sql:113, 159`
- 적용: kr_pipeline, kr_test 양쪽 DB (메모리: schema 수동 적용 필수)

- [ ] **Step 1: schema.sql 컬럼 정의 교체**

`schema.sql:113`(daily)와 `:159`(weekly) 의
`rs_line_in_decline_7m BOOLEAN,` 를 각각
`rs_line_not_declining_7m BOOLEAN,   -- TRUE=건강(7개월 하락 아님). 주봉계산→일봉미러` 로 교체.

- [ ] **Step 2: 마이그레이션 SQL 작성·적용 (양쪽 DB)**

Run (kr_pipeline, kr_test 각각):

```bash
for DB in kr_pipeline kr_test; do
  psql "$DB" -c "ALTER TABLE daily_indicators  DROP COLUMN IF EXISTS rs_line_in_decline_7m;
                 ALTER TABLE daily_indicators  ADD  COLUMN IF NOT EXISTS rs_line_not_declining_7m BOOLEAN;
                 ALTER TABLE weekly_indicators DROP COLUMN IF EXISTS rs_line_in_decline_7m;
                 ALTER TABLE weekly_indicators ADD  COLUMN IF NOT EXISTS rs_line_not_declining_7m BOOLEAN;"
done
```

Expected: `ALTER TABLE` × 4 per DB, 에러 없음.

- [ ] **Step 3: 적용 확인**

Run: `psql kr_test -c "\d daily_indicators" | grep rs_line_not_declining`
Expected: `rs_line_not_declining_7m | boolean` 한 줄.

- [ ] **Step 4: Commit**

```bash
git add kr_pipeline/db/schema.sql
git commit -m "feat(rs): rs_line_in_decline_7m → rs_line_not_declining_7m 컬럼 교체 (양쪽 DB 적용)"
```

---

## Task 8: 7개월 게이트 계산 배선 (modes.py + store.py 컬럼 목록)

**Files:**
- Modify: `kr_pipeline/indicators/modes.py` (daily:186 제거, weekly:507 교체, row dict 키 교체)
- Modify: `kr_pipeline/indicators/store.py:9-26, 109-123` (PHASE_A_COLUMNS)

- [ ] **Step 1: weekly 게이트 계산 교체 (modes.py:507)**

`modes.py:507` 의
```python
    rs_decline = compute_rs_line_in_decline_7m(rs_line_high_date, current_dates, threshold_days=28*7)
```
를 다음으로 교체(import 에 `compute_rs_line_not_declining`, 상수 추가 필요):
```python
    rs_not_declining = compute_rs_line_not_declining(rs_line, window=RS_LINE_DECLINE_GATE_WEEKS)
```

`modes.py:15-19` import 에 `compute_rs_line_not_declining, compute_rs_line_uptrend_slope` 추가(구 `compute_rs_line_uptrend, compute_rs_line_in_decline_7m` 제거). 파일 상단 thresholds import 추가:
```python
from kr_pipeline.common.thresholds import (
    RS_LINE_UPTREND_SHORT_WEEKS, RS_LINE_UPTREND_LONG_WEEKS, RS_LINE_DECLINE_GATE_WEEKS,
)
```

- [ ] **Step 2: weekly uptrend 기울기 교체 (modes.py:504-505)**

```python
    rs_up_6w = compute_rs_line_uptrend_slope(rs_line, window=RS_LINE_UPTREND_SHORT_WEEKS)
    rs_up_13w = compute_rs_line_uptrend_slope(rs_line, window=RS_LINE_UPTREND_LONG_WEEKS)
```

- [ ] **Step 3: weekly row dict 키 교체 (modes.py:537)**

`"rs_line_in_decline_7m": _as_bool(rs_decline.loc[d]),` →
`"rs_line_not_declining_7m": _as_bool(rs_not_declining.loc[d]),`

- [ ] **Step 4: daily uptrend 기울기 교체 + decline 제거 (modes.py:183-186)**

```python
    rs_up_6w = compute_rs_line_uptrend_slope(rs_line, window=RS_LINE_UPTREND_SHORT_WEEKS * 5)   # 6주≈30영업일
    rs_up_13w = compute_rs_line_uptrend_slope(rs_line, window=RS_LINE_UPTREND_LONG_WEEKS * 5)   # 13주≈65영업일
```
`current_dates`/`rs_decline` 두 줄(185-186) 삭제(daily 게이트는 미러로 채움).

- [ ] **Step 5: daily row dict 키 교체 (modes.py:224)**

`"rs_line_in_decline_7m": _as_bool(rs_decline.loc[d]),` →
`"rs_line_not_declining_7m": None,  # Task 9 미러 단계에서 weekly 값으로 채움`

- [ ] **Step 6: store.py 컬럼 목록 교체**

`store.py:15` (`PHASE_A_COLUMNS_DAILY`) 와 `:115`(`PHASE_A_COLUMNS_WEEKLY`) 의
`"rs_line_in_decline_7m",` → `"rs_line_not_declining_7m",`

- [ ] **Step 7: import 무결성 확인**

Run: `uv run python -c "import kr_pipeline.indicators.modes; import kr_pipeline.indicators.store; print('ok')"`
Expected: `ok`

- [ ] **Step 8: Commit**

```bash
git add kr_pipeline/indicators/modes.py kr_pipeline/indicators/store.py
git commit -m "feat(rs): 7개월 게이트(weekly pure-declining)·uptrend 기울기 배선"
```

---

## Task 9: 주→일 미러 UPDATE (store.py + modes 오케스트레이션)

**Files:**
- Modify: `kr_pipeline/indicators/store.py` (미러 함수 추가)
- Modify: `kr_pipeline/indicators/modes.py:435` 근처 (run_daily 호출 추가, import 추가)
- Test: `tests/test_indicators_store.py` (DB 필요 — isolation 마킹 따름)

- [ ] **Step 1: 미러 함수 구현**

`store.py` 끝에 추가:

```python
def update_daily_rs_gate_from_weekly(
    conn: Connection, start_date: date, end_date: date
) -> int:
    """각 daily 행의 rs_line_not_declining_7m 을 최신 week_end_date ≤ date 의 weekly 값으로 미러.

    게이트는 주봉에서 계산(D3) → 후보 쿼리(daily 단일 테이블) 가 읽도록 daily 에 복사.
    weekly_indicators 가 먼저 적재돼 있어야 함.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE daily_indicators d
               SET rs_line_not_declining_7m = (
                     SELECT w.rs_line_not_declining_7m
                       FROM weekly_indicators w
                      WHERE w.ticker = d.ticker AND w.week_end_date <= d.date
                      ORDER BY w.week_end_date DESC
                      LIMIT 1
                   ),
                   updated_at = NOW()
             WHERE d.date BETWEEN %s AND %s
            """,
            (start_date, end_date),
        )
        return cur.rowcount
```

- [ ] **Step 2: run_daily 에 미러 단계 추가**

`modes.py:31-36` import 에 `update_daily_rs_gate_from_weekly` 추가. `modes.py:435`(`mn_affected = update_daily_indicators_minervini_pass(...)`) 다음 줄에 추가:

```python
        gate_affected = update_daily_rs_gate_from_weekly(conn, upsert_start, load_end)
        conn.commit()
        log.info("daily rs gate mirrored: %d rows", gate_affected)
```

- [ ] **Step 3: 미러 동작 테스트 (DB)**

`tests/test_indicators_store.py` 에 추가(파일 상단 `db` 픽스처 + `_seed_stock(db, ticker)` 헬퍼 재사용):

```python
def test_mirror_gate_picks_latest_week_le_date(db):
    from kr_pipeline.indicators.store import update_daily_rs_gate_from_weekly
    from datetime import date
    _seed_stock(db, "005930")
    with db.cursor() as cur:
        cur.execute("INSERT INTO weekly_indicators (ticker, week_end_date, adj_close, rs_line_not_declining_7m) "
                    "VALUES ('005930','2026-05-29',100,TRUE),('005930','2026-06-05',100,FALSE)")
        cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close) VALUES ('005930','2026-06-03',100)")
    update_daily_rs_gate_from_weekly(db, date(2026,6,1), date(2026,6,4))
    with db.cursor() as cur:
        cur.execute("SELECT rs_line_not_declining_7m FROM daily_indicators WHERE ticker='005930' AND date='2026-06-03'")
        # 2026-06-03 은 06-05 이전 → 최신 week_end ≤ date 는 05-29 → TRUE
        assert cur.fetchone()[0] is True
```

- [ ] **Step 4: 테스트 실행**

Run: `uv run pytest tests/test_indicators_store.py::test_mirror_gate_picks_latest_week_le_date -v`
Expected: PASS (kr_test DB 연결 가능 시). DB 미가용이면 isolation baseline 에 포함됨을 확인하고 다음 진행.

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/indicators/store.py kr_pipeline/indicators/modes.py tests/test_indicators_store.py
git commit -m "feat(rs): 7개월 게이트 주→일 미러 UPDATE + run_daily 배선"
```

---

## Task 10: 후보 쿼리 게이트 AND (load.py)

**Files:**
- Modify: `kr_pipeline/llm_runner/load.py:28-35`

- [ ] **Step 1: 후보 쿼리에 게이트 추가**

`load.py:28-35` 의 SQL 을 다음으로 교체:

```python
    sql = """
        SELECT i.ticker, s.market
          FROM daily_indicators i
          JOIN stocks s ON s.ticker = i.ticker
         WHERE i.date = %s
           AND i.minervini_pass = TRUE
           AND i.rs_line_not_declining_7m = TRUE
           AND s.delisted_at IS NULL
    """
```

(주: `= TRUE` 비교라 NaN/NULL 은 자동 제외 — 설계 §5.1.)

- [ ] **Step 2: disqualify 경로 영향 점검**

`load.py:81-102` `get_classified_losing_minervini` 는 강등(disqualify) 경로 — 게이트 추가하지 않는다(통과 기준만 강화, 강등은 minervini 기준 유지). 변경 없음 확인.

- [ ] **Step 3: import/구문 확인**

Run: `uv run python -c "import kr_pipeline.llm_runner.load; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add kr_pipeline/llm_runner/load.py
git commit -m "feat(rs): 후보 선정에 7개월 비하락 게이트 AND 추가"
```

---

## Task 11: weekly C8 하드코딩 → 상수화 (store.py)

**Files:**
- Modify: `kr_pipeline/indicators/store.py:179, 184`

- [ ] **Step 1: 하드코딩 70 교체**

`store.py:176-189` `update_weekly_indicators_minervini_pass` SQL 의 `rs_rating >= 70` 두 곳을 `rs_rating >= %s` 로 바꾸고 파라미터 전달:

```python
            UPDATE weekly_indicators
               SET minervini_c8 = (rs_rating >= %s),
                   minervini_pass = (
                       minervini_c1 IS TRUE AND minervini_c2 IS TRUE AND
                       minervini_c3 IS TRUE AND minervini_c4 IS TRUE AND
                       minervini_c5 IS TRUE AND minervini_c6 IS TRUE AND
                       minervini_c7 IS TRUE AND (rs_rating >= %s)
                   ),
                   updated_at = NOW()
             WHERE week_end_date BETWEEN %s AND %s
            """,
            (C8_RS_RATING_MIN, C8_RS_RATING_MIN, start_date, end_date),
```

(`C8_RS_RATING_MIN` 은 store.py:6 에서 이미 import 됨.)

- [ ] **Step 2: 구문 확인**

Run: `uv run python -c "import kr_pipeline.indicators.store; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add kr_pipeline/indicators/store.py
git commit -m "refactor(rs): weekly C8 하드코딩 70 → C8_RS_RATING_MIN 통일"
```

---

## Task 12: LLM 페이로드에 RS boolean 추가 (payload_builder.py)

**Files:**
- Modify: `api/services/payload_builder.py:142-172`

- [ ] **Step 1: SELECT 에 boolean 3종 추가**

`payload_builder.py:142-151` SELECT 의 마지막 컬럼(`i.distribution_day_flag`) 뒤에 추가:

```python
            SELECT p.date, p.adj_close, p.volume,
                   i.sma_10, i.sma_21, i.sma_50, i.sma_150, i.sma_200,
                   i.w52_high, i.w52_low, i.rs_line, i.rs_rating, i.minervini_pass,
                   i.avg_volume_50d, i.volume_ratio_50d, i.pocket_pivot_flag, i.distribution_day_flag,
                   i.rs_line_at_52w_high, i.rs_line_uptrend_6w, i.rs_line_uptrend_13w
```

- [ ] **Step 2: dict 에 boolean 3종 추가**

`payload_builder.py:171` `"distribution_day_flag": ...` 다음(닫는 `}` 직전)에 추가:

```python
            "rs_line_at_52w_high": bool(r[17]) if r[17] is not None else None,
            "rs_line_uptrend_6w": bool(r[18]) if r[18] is not None else None,
            "rs_line_uptrend_13w": bool(r[19]) if r[19] is not None else None,
```

- [ ] **Step 3: 구문 확인**

Run: `uv run python -c "import api.services.payload_builder; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add api/services/payload_builder.py
git commit -m "feat(rs): LLM 페이로드에 RS Line boolean 3종 추가"
```

---

## Task 13: 프롬프트 §4.6 / Inputs 동기화 (analyze_chart_v3.md)

**Files:**
- Modify: `prompts/analyze_chart_v3.md:46, 194-200`

- [ ] **Step 1: Inputs 목록에 boolean 추가 (line 46)**

`- **Recent indicator series**: ...` 끝에 추가:
`, rs_line_at_52w_high, rs_line_uptrend_6w (6주 회귀 기울기>0), rs_line_uptrend_13w (13주 기울기>0)`

- [ ] **Step 2: §4.6 boolean 사용 명시 (line 196 이후)**

`### 4.6. RS Line Leadership Check (O'Neil)` 의 `Examine the RS Line series ...` 다음에 한 줄 추가:

```markdown
Boolean signals (use as corroboration, not as filters): `rs_line_at_52w_high` (RS Line at 52-week high today), `rs_line_uptrend_6w` / `rs_line_uptrend_13w` (RS Line 6/13-week regression slope > 0). These are advisory inputs to the leadership judgment below, not pass/fail gates.
```

- [ ] **Step 3: Commit**

```bash
git add prompts/analyze_chart_v3.md
git commit -m "docs(rs): 프롬프트 §4.6/Inputs 에 RS boolean 입력 명시 (수동 동기화)"
```

---

## Task 14: 전체 히스토리 재계산 + 검증

**Files:** (실행 — 코드 변경 없음)

- [ ] **Step 1: 전체 테스트 그린 확인 (회귀 게이트)**

Run: `uv run pytest tests/ -q 2>&1 | tail -15`
Expected: Task 0 베이스라인 isolation fail 수와 동일(증가 없음). RS 관련 신규/수정 테스트 PASS.

- [ ] **Step 2: weekly 먼저, 그다음 daily 전체 재계산**

(미러는 weekly 가 최신이어야 정확 — weekly → daily 순서.)

Run:
```bash
uv run python -m kr_pipeline.indicators --target weekly --mode full-refresh
uv run python -m kr_pipeline.indicators --target daily  --mode full-refresh
```
Expected: 각 run 완료 로그, `daily rs gate mirrored: N rows` 출력. (실제 진입점 플래그는 `kr_pipeline/indicators/__main__.py` 확인 후 맞춤.)

- [ ] **Step 3: SF 전환 후 ≥70 후보 수·구성 재검증 (설계 §9.3)**

Run:
```bash
psql kr_pipeline -c "SELECT date, COUNT(*) FILTER (WHERE rs_rating>=70) AS ge70,
  COUNT(*) FILTER (WHERE minervini_pass) AS mn_pass,
  COUNT(*) FILTER (WHERE minervini_pass AND rs_line_not_declining_7m) AS final_cand
  FROM daily_indicators WHERE date=(SELECT MAX(date) FROM daily_indicators) GROUP BY date"
```
Expected: `final_cand` 가 합리적 범위(과거 minervini_pass 대비 게이트로 줄어든 수). 0 이거나 비정상 급감이면 게이트/미러 점검.

- [ ] **Step 4: 미러 커버리지 확인 (NULL 누수 점검)**

Run:
```bash
psql kr_pipeline -c "SELECT COUNT(*) FILTER (WHERE rs_line_not_declining_7m IS NULL) AS null_gate, COUNT(*) total
  FROM daily_indicators WHERE date=(SELECT MAX(date) FROM daily_indicators)"
```
Expected: 충분한 히스토리(≥52주) 종목은 NULL 아님. NULL 비율이 높으면 weekly 적재/미러 순서 점검.

- [ ] **Step 5: 검증 결과 기록 + Commit**

검증 수치를 설계 문서 §9.3 하단에 "재계산 검증(YYYY-MM-DD)" 으로 한 줄 기록.

```bash
git add docs/superpowers/specs/2026-06-03-rs-indicator-rework-design.md
git commit -m "chore(rs): 전체 재계산 검증 수치 기록"
```

---

## Self-Review 결과

- **Spec 커버리지**: 작업1(RS Rating SF)=Task2-3, 작업2(분모)=Task4, 작업3 7개월 게이트=Task5,7,8,9,10, 6주/13주 기울기=Task5,8, LLM 배선=Task12,13, 신고점(D8)=차트 기존 유지(지표화 없음, 별 task 불필요), 상수/SSOT=Task1, weekly C8 정리=Task11, 히스토리=Task14, 체크리스트=Task0. → 전 항목 매핑됨.
- **타입 일관성**: 신규 컬럼명 `rs_line_not_declining_7m`(TRUE=건강) 전 task 동일. 함수명 `compute_ibd_strength_factor`, `compute_rs_line_uptrend_slope`, `compute_rs_line_not_declining`, `update_daily_rs_gate_from_weekly` 일관.
- **확인 완료**: CLI 플래그 `--target {daily,weekly} --mode {backfill,incremental,full-refresh}`(modes.py:48-56), store 테스트 픽스처 `db` + `_seed_stock(db, ticker)`(test_indicators_store.py:11). Task 9·14 명령/테스트에 반영됨.
