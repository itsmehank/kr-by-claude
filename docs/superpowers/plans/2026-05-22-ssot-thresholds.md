# SSOT Thresholds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모든 책-유래 임계를 단일 Python 모듈 (`kr_pipeline/common/thresholds.py`) 에 모으고, Python 코드는 import 로 참조, UI (TypeScript) 는 빌드 스크립트로 자동 생성된 `web/src/data/thresholds.generated.ts` 를 참조하도록 정합성 인프라 구축.

**Architecture:** SSOT (Single Source of Truth) 패턴. Python 단일 모듈이 모든 임계의 원천. 코드는 직접 import, UI 는 빌드 시 Python → JSON → TypeScript 변환으로 자동 동기화. Prompt (.md) 는 정적이라 수동 동기화 (별도 검증 스크립트 + P0 fix plan 에서 다룸). **동작 변화 0** — 모든 현재 값을 그대로 유지, 단지 정의 위치만 통합. 이후 P0/P1/P2 plan 에서 *값 1곳 수정* 만으로 전 표면에 전파.

**Tech Stack:** Python 3.12+, pytest, TypeScript, Vite

**Spec:** `docs/superpowers/specs/2026-05-22-book-audit-findings.md` SSOT-1 (commit c2591e3)

---

## File Structure

### 신규 (Created)

| Path | Responsibility |
|---|---|
| `kr_pipeline/common/thresholds.py` | 모든 책-유래 임계의 단일 정의. 카테고리별 상수 + 책 인용 docstring |
| `tests/test_common_thresholds.py` | SSOT 모듈 import smoke test + 값 sanity check |
| `scripts/export_thresholds.py` | `thresholds.py` → `thresholds.generated.ts` 변환 빌드 스크립트 |
| `web/src/data/thresholds.generated.ts` | 자동 생성된 TypeScript 상수 (git 에 commit, drift 추적용) |

### 수정 (Modified)

| Path | What |
|---|---|
| `kr_pipeline/llm_runner/compute/trigger_gate.py:22,27` | hardcoded → SSOT import |
| `kr_pipeline/indicators/compute/minervini.py:10,43,45` | hardcoded → SSOT (default arg + line 43/45 상수) |
| `kr_pipeline/indicators/compute/volume.py:36,66,95` | 3 함수의 default 인자 → SSOT |
| `kr_pipeline/market_context/compute/follow_through.py:13-16` | 4 module-level 상수 → SSOT |
| `kr_pipeline/market_context/compute/distribution_day.py:11,27` | 임계 + lookback default → SSOT |
| `kr_pipeline/market_context/compute/status.py:15-19` | 5 module-level 상수 → SSOT |
| `kr_pipeline/indicators/store.py:91,96` | SQL 안의 `>= 70` → f-string 으로 SSOT 참조 |
| `kr_pipeline/llm_runner/compute/delta.py:12` | RECENT_WINDOW_DAYS → SSOT |
| `.gitignore` | `web/src/data/thresholds.generated.ts` 는 *commit* (drift 추적용 — gitignore 안 함) |

---

## Task 1: SSOT 모듈 작성

**Files:**
- Create: `kr_pipeline/common/thresholds.py`
- Test: `tests/test_common_thresholds.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_common_thresholds.py`:

```python
"""SSOT thresholds 모듈의 import + 값 sanity test.

이 테스트는 SSOT 가 *현재 시스템 동작*과 일치하는 값을 가지는지 확인.
값 변경 (예: P0-2 의 1.25 → 1.0) 시 이 테스트를 함께 갱신해야 함.
"""
from kr_pipeline.common import thresholds


def test_gate_constants():
    assert thresholds.GATE_BREAKOUT_VOL_MULT == 1.0
    assert thresholds.GATE_PROMOTION_PRICE_RATIO == 0.95


def test_recent_window():
    assert thresholds.RECENT_CLASSIFICATION_WINDOW_DAYS == 7


def test_minervini_constants():
    assert thresholds.C3_SMA200_LOOKBACK_DAYS == 22
    assert thresholds.C6_W52LOW_MULT == 1.25
    assert thresholds.C7_W52HIGH_MULT == 0.75
    assert thresholds.C8_RS_RATING_MIN == 70


def test_pocket_pivot():
    assert thresholds.PP_DOWN_VOL_LOOKBACK_DAYS == 10


def test_volume_constants():
    assert thresholds.STOCK_DISTRIBUTION_VOL_MULT == 1.25
    assert thresholds.VOLUME_DRY_UP_MULT == 0.5


def test_market_distribution():
    assert thresholds.MARKET_DISTRIBUTION_PCT_THRESHOLD == -0.2
    assert thresholds.MARKET_DISTRIBUTION_LOOKBACK_DAYS == 25


def test_ftd_constants():
    assert thresholds.FTD_PCT_THRESHOLD == {"KOSPI": 1.4, "KOSDAQ": 1.4}
    assert thresholds.FTD_RALLY_WINDOW_MIN_DAYS == 3
    assert thresholds.FTD_RALLY_WINDOW_MAX_DAYS == 15
    assert thresholds.FTD_LOW_LOOKBACK_DAYS == 15


def test_status_constants():
    assert thresholds.STATUS_CORRECTION_OFF_HIGH_PCT == -10.0
    assert thresholds.STATUS_DOWNTREND_OFF_HIGH_PCT == -15.0
    assert thresholds.STATUS_DIST_COUNT_FOR_FTD_INVALIDATION == 6
    assert thresholds.STATUS_FTD_RECENT_DAYS == 90
    assert thresholds.STATUS_FTD_INVALIDATION_DAYS == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_common_thresholds.py -v`
Expected: FAIL with `ModuleNotFoundError` 또는 `AttributeError` (thresholds 모듈 / 상수 미존재)

- [ ] **Step 3: Create SSOT module**

Create `kr_pipeline/common/thresholds.py`:

```python
"""책 임계의 SSOT (Single Source of Truth).

모든 책-유래 임계의 단일 정의. 변경 시 영향:
- Python 코드: 자동 (이 모듈 import 참조)
- UI (TypeScript): 자동 (scripts/export_thresholds.py 가 web/src/data/thresholds.generated.ts 생성)
- Prompt (markdown): 수동 — prompts/*.md 의 텍스트 임계를 함께 갱신해야 함

본 모듈의 값은 *현재 시스템 동작* 과 일치한다 (동작 변화 0). 책 표준과
다를 수 있는 항목은 docstring 에 명시하고 별도 P0/P1 plan 에서 정합.
"""
from typing import Final

# ===== 결정론 게이트 (kr_pipeline/llm_runner/compute/trigger_gate.py) =====

GATE_BREAKOUT_VOL_MULT: Final[float] = 1.0
"""게이트의 breakout 거래량 통과 임계 (50일 평균 배수).
시스템 설계: 게이트는 '거래량 죽지 않은 정도' 만 확인, 정밀 임계 (책 표준
1.4-1.5×) 는 LLM 에 위임. TLOND p.133 BIDU 사례 (39% 거래량 돌파 = pocket
pivot) 같은 false negative 방지."""

GATE_PROMOTION_PRICE_RATIO: Final[float] = 0.95
"""watch → promotion staging 가격 임계 (pivot 비율).
시스템 자체 설계 — 책 근거 없음 (O'Neil 은 pivot 미만 매수 경고).
entry_params SQL 의 trigger_type='breakout' 필터로 매수 시그널 직행 차단."""

# ===== 신규 후보 윈도우 (kr_pipeline/llm_runner/compute/delta.py) =====

RECENT_CLASSIFICATION_WINDOW_DAYS: Final[int] = 7
"""daily_delta 의 '최근 N 일 미분류' 윈도우.
시스템 자체 설계 — 책 근거 없음."""

# ===== Minervini Trend Template (kr_pipeline/indicators/compute/minervini.py) =====

C3_SMA200_LOOKBACK_DAYS: Final[int] = 22
"""C3 의 sma_200 lookback (오늘 vs N 일 전 비교).
책: Minervini TLSMW Ch.5 / TTLC Ch.6 — '≥1 month' ≈ 22 거래일.
선호: '4-5 months minimum' — 상승 강도는 LLM 시각 판단에 위임."""

C6_W52LOW_MULT: Final[float] = 1.25
"""C6 의 52w 저점 대비 임계.
두 저작 충돌: TLSMW Ch.5 p.79 = 1.30 (30%), TTLC Ch.6 = 1.25 (25%).
최신작 (TTLC) 채택."""

C7_W52HIGH_MULT: Final[float] = 0.75
"""C7 의 52w 고점 대비 임계 (within 25% of 52w high).
책: Minervini TLSMW Ch.5 / TTLC Ch.6 공통."""

C8_RS_RATING_MIN: Final[int] = 70
"""C8 RS Rating 최소.
책: Minervini TLSMW Ch.5 'relative strength ranking ... is no less than 70'.
O'Neil HMMS 는 80+ 선호."""

# ===== Pocket Pivot (kr_pipeline/indicators/compute/volume.py) =====

PP_DOWN_VOL_LOOKBACK_DAYS: Final[int] = 10
"""Pocket pivot 의 직전 down-day 거래량 비교 lookback.
책: Morales & Kacher TLOND Ch.5 p.133 — 기본 10 일.
선호: 변동성 큰 종목은 11-15 일 (책 단서, 적응형 미구현)."""

# ===== Distribution Day - 종목 레벨 (kr_pipeline/indicators/compute/volume.py) =====

STOCK_DISTRIBUTION_VOL_MULT: Final[float] = 1.25
"""종목 레벨 distribution day 의 거래량 임계 (50일 평균 배수).
주의: 책 표준 / prompt §6 와 불일치 (P0-2 에서 1.0× 로 정렬 예정).
책 표준: O'Neil HMMS Ch.9 — 전일 거래량 초과 (avg 배수 아님)."""

# ===== Volume Dry-up (kr_pipeline/indicators/compute/volume.py) =====

VOLUME_DRY_UP_MULT: Final[float] = 0.5
"""volume_dry_up 의 거래량 임계 (50일 평균 배수).
책 명시 아님 — community standard."""

# ===== Distribution Day - 시장 레벨 (kr_pipeline/market_context/compute/distribution_day.py) =====

MARKET_DISTRIBUTION_PCT_THRESHOLD: Final[float] = -0.2
"""시장 지수 distribution day 의 일간 하락 임계 (%).
책: IBD/O'Neil 통용 -0.2%. TLOND p.231 는 -0.1% 선호 (해석본).
원전 우선 — -0.2% 유지."""

MARKET_DISTRIBUTION_LOOKBACK_DAYS: Final[int] = 25
"""시장 distribution day 카운트 lookback (세션 수).
책: O'Neil HMMS Ch.9 — 25 세션."""

# ===== Follow-Through Day (kr_pipeline/market_context/compute/follow_through.py) =====

FTD_PCT_THRESHOLD: Final[dict[str, float]] = {
    "KOSPI": 1.4,
    "KOSDAQ": 1.4,
}
"""FTD 일간 상승 임계 (%, 시장별).
책: TLOND p.232-233 — NASDAQ 1.4% (2003) / 1.5% (2010), S&P 1.1% (2004).
'한 나라 두 지수도 다른 임계' 권장. 현재 KOSPI/KOSDAQ 동일 — P2-1a 에서
한국 시장 변동성 측정 후 시장별 보정 예정."""

FTD_RALLY_WINDOW_MIN_DAYS: Final[int] = 3
"""FTD 발생 가능 윈도우 최소 (저점 후 일수).
책: O'Neil HMMS Ch.9 — 최소 3 일."""

FTD_RALLY_WINDOW_MAX_DAYS: Final[int] = 15
"""FTD 발생 가능 윈도우 최대.
책: O'Neil — 4-7 최적, 11 일까지 인정 (시스템은 15 일까지 허용)."""

FTD_LOW_LOOKBACK_DAYS: Final[int] = 15
"""FTD 의 rally 시작 후보 (저점) lookback.
시스템 자체 설계."""

# ===== Market Status (kr_pipeline/market_context/compute/status.py) =====

STATUS_CORRECTION_OFF_HIGH_PCT: Final[float] = -10.0
"""correction 판정의 52주 고점 대비 하락폭 임계."""

STATUS_DOWNTREND_OFF_HIGH_PCT: Final[float] = -15.0
"""downtrend 판정의 52주 고점 대비 하락폭 임계."""

STATUS_DIST_COUNT_FOR_FTD_INVALIDATION: Final[int] = 6
"""FTD 무효화 distribution 카운트 임계 (25 세션 내)."""

STATUS_FTD_RECENT_DAYS: Final[int] = 90
"""confirmed_uptrend 진입을 위해 FTD 가 유효한 최근 일수."""

STATUS_FTD_INVALIDATION_DAYS: Final[int] = 10
"""distribution 누적 후 FTD 무효화까지 일수."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_common_thresholds.py -v`
Expected: PASS — 9 tests

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/common/thresholds.py tests/test_common_thresholds.py
git commit -m "feat(ssot): kr_pipeline/common/thresholds.py 신규 — 책 임계 단일 정의

모든 책-유래 임계를 단일 모듈에 상수로 정의. 후속 task 에서 기존
Python 코드 / UI 가 이를 참조하도록 교체. 동작 변화 0."
```

---

## Task 2: trigger_gate.py — SSOT import

**Files:**
- Modify: `kr_pipeline/llm_runner/compute/trigger_gate.py`

- [ ] **Step 1: Replace module-level constants with SSOT import**

Read `kr_pipeline/llm_runner/compute/trigger_gate.py` first (특히 line 22, 27 주변 주석).

Edit `kr_pipeline/llm_runner/compute/trigger_gate.py` — line 22 의 `BREAKOUT_VOLUME_MULTIPLIER = 1.0` (주변 주석 포함) 과 line 27 의 `PROMOTION_THRESHOLD_RATIO = 0.95` (주변 주석 포함) 을 다음으로 교체:

```python
from kr_pipeline.common.thresholds import (
    GATE_BREAKOUT_VOL_MULT,
    GATE_PROMOTION_PRICE_RATIO,
)

# 기존 모듈-레벨 상수는 SSOT (kr_pipeline/common/thresholds.py) 로 이전됨.
# 호환성을 위해 같은 이름의 별칭만 유지 (외부 import 가 있을 수 있어).
BREAKOUT_VOLUME_MULTIPLIER = GATE_BREAKOUT_VOL_MULT
PROMOTION_THRESHOLD_RATIO = GATE_PROMOTION_PRICE_RATIO
```

기존 line 56, 61 의 `BREAKOUT_VOLUME_MULTIPLIER` / `PROMOTION_THRESHOLD_RATIO` 사용처는 *그대로* (별칭 유지로 호환).

- [ ] **Step 2: Run trigger_gate tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_trigger_gate.py -v 2>&1 | tail -20`
Expected: 모든 기존 테스트 PASS (값 동일하므로 동작 무변화)

테스트 파일 위치를 모르면: `find tests -name "*trigger_gate*"` 로 확인.

- [ ] **Step 3: Commit**

```bash
git add kr_pipeline/llm_runner/compute/trigger_gate.py
git commit -m "refactor(ssot): trigger_gate 가 SSOT thresholds 참조

BREAKOUT_VOLUME_MULTIPLIER, PROMOTION_THRESHOLD_RATIO 를 SSOT 에서 import.
호환성 별칭 유지. 동작 변화 0."
```

---

## Task 3: minervini.py — SSOT import

**Files:**
- Modify: `kr_pipeline/indicators/compute/minervini.py`

- [ ] **Step 1: Replace 3 thresholds**

Read `kr_pipeline/indicators/compute/minervini.py` first.

Edit `kr_pipeline/indicators/compute/minervini.py`:

1. 파일 상단 (docstring 다음) 에 SSOT import 추가:

```python
from kr_pipeline.common.thresholds import (
    C3_SMA200_LOOKBACK_DAYS,
    C6_W52LOW_MULT,
    C7_W52HIGH_MULT,
)
```

2. line 10 의 함수 시그니처 `def compute_minervini_c1_to_c7(df: pd.DataFrame, sma_200_lookback: int = 22) -> pd.DataFrame:` 를 다음으로 변경:

```python
def compute_minervini_c1_to_c7(
    df: pd.DataFrame,
    sma_200_lookback: int = C3_SMA200_LOOKBACK_DAYS,
) -> pd.DataFrame:
```

3. line 43 의 `out["minervini_c6"] = close >= w52l * 1.25` 를:

```python
    out["minervini_c6"] = close >= w52l * C6_W52LOW_MULT
```

4. line 45 의 `out["minervini_c7"] = close >= w52h * 0.75` 를:

```python
    out["minervini_c7"] = close >= w52h * C7_W52HIGH_MULT
```

기존 line 37-42 의 주석 (C6 의 1.25 vs 1.30 두 저작 차이) 은 SSOT 의 docstring 으로 이전됐으므로 *간소화* — line 37-42 주석을 다음 1줄로 교체:

```python
    # C6: close >= w52_low * C6_W52LOW_MULT (책 임계는 SSOT docstring 참조)
```

- [ ] **Step 2: Run minervini tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/ -v -k "minervini" 2>&1 | tail -20`
Expected: 모든 기존 minervini 테스트 PASS

- [ ] **Step 3: Commit**

```bash
git add kr_pipeline/indicators/compute/minervini.py
git commit -m "refactor(ssot): minervini 가 SSOT thresholds 참조

C3 lookback (22일), C6 1.25, C7 0.75 를 SSOT 에서 import.
인라인 주석 (두 저작 차이) 은 SSOT docstring 으로 이전. 동작 변화 0."
```

---

## Task 4: volume.py — 3 함수 default 인자

**Files:**
- Modify: `kr_pipeline/indicators/compute/volume.py`

- [ ] **Step 1: Replace 3 default arg values**

Read `kr_pipeline/indicators/compute/volume.py` first (line 31-105 부근).

Edit `kr_pipeline/indicators/compute/volume.py`:

1. 파일 상단에 SSOT import 추가:

```python
from kr_pipeline.common.thresholds import (
    PP_DOWN_VOL_LOOKBACK_DAYS,
    STOCK_DISTRIBUTION_VOL_MULT,
    VOLUME_DRY_UP_MULT,
)
```

2. line 36 의 `lookback: int = 10,` (pocket_pivot 함수 default) 를:

```python
    lookback: int = PP_DOWN_VOL_LOOKBACK_DAYS,
```

3. line 66 의 `threshold: float = 0.5,` (volume_dry_up 함수 default) 를:

```python
    threshold: float = VOLUME_DRY_UP_MULT,
```

4. line 95 의 `threshold: float = 1.25,` (distribution_day 함수 default) 를:

```python
    threshold: float = STOCK_DISTRIBUTION_VOL_MULT,
```

- [ ] **Step 2: Run volume tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/ -v -k "volume" 2>&1 | tail -20`
Expected: 기존 volume 테스트 PASS

- [ ] **Step 3: Commit**

```bash
git add kr_pipeline/indicators/compute/volume.py
git commit -m "refactor(ssot): volume.py 3 함수 default 가 SSOT 참조

pocket_pivot lookback (10), volume_dry_up threshold (0.5),
distribution_day threshold (1.25) 를 SSOT 에서 import. 동작 변화 0."
```

---

## Task 5: follow_through.py — 4 module-level 상수

**Files:**
- Modify: `kr_pipeline/market_context/compute/follow_through.py`

- [ ] **Step 1: Replace 4 module-level constants**

Read `kr_pipeline/market_context/compute/follow_through.py` first (line 13-16 + 함수 본체).

Edit `kr_pipeline/market_context/compute/follow_through.py`:

1. 파일 상단에 SSOT import 추가 (기존 import 들 다음):

```python
from kr_pipeline.common.thresholds import (
    FTD_PCT_THRESHOLD as _SSOT_FTD_PCT_THRESHOLD,
    FTD_RALLY_WINDOW_MIN_DAYS,
    FTD_RALLY_WINDOW_MAX_DAYS,
    FTD_LOW_LOOKBACK_DAYS,
)
```

(`FTD_PCT_THRESHOLD` 는 SSOT 에선 dict 이고 이 모듈에선 단일 float 로 쓰이므로 별칭 import.)

2. line 13-16 의 4 상수를 다음으로 교체:

```python
# 기존 module-level 상수는 SSOT (kr_pipeline/common/thresholds.py) 로 이전.
# 호환성을 위해 같은 이름 별칭 유지. 시장별 임계는 추후 (P2-1a) 별도 함수
# 인자로 받도록 변경 예정 — 현재는 양 시장 동일 1.4% 사용.
FTD_PCT_THRESHOLD = _SSOT_FTD_PCT_THRESHOLD["KOSPI"]  # = KOSDAQ 도 동일값
FTD_RALLY_WINDOW_MIN = FTD_RALLY_WINDOW_MIN_DAYS
FTD_RALLY_WINDOW_MAX = FTD_RALLY_WINDOW_MAX_DAYS
FTD_LOW_LOOKBACK = FTD_LOW_LOOKBACK_DAYS
```

line 29 이후 함수 본체의 사용처는 *그대로* (별칭 유지로 호환).

- [ ] **Step 2: Run follow_through tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/ -v -k "follow_through or ftd" 2>&1 | tail -20`
Expected: 기존 테스트 PASS

- [ ] **Step 3: Commit**

```bash
git add kr_pipeline/market_context/compute/follow_through.py
git commit -m "refactor(ssot): follow_through 가 SSOT thresholds 참조

FTD_PCT_THRESHOLD (KOSPI 값), WINDOW_MIN/MAX, LOW_LOOKBACK 을 SSOT 에서
import. 호환성 별칭 유지. 시장별 임계 분리 (P2-1a) 는 후속. 동작 변화 0."
```

---

## Task 6: distribution_day.py (market) — SSOT import

**Files:**
- Modify: `kr_pipeline/market_context/compute/distribution_day.py`

- [ ] **Step 1: Replace threshold + lookback default**

Read `kr_pipeline/market_context/compute/distribution_day.py` first.

Edit `kr_pipeline/market_context/compute/distribution_day.py`:

1. 파일 상단에 SSOT import 추가:

```python
from kr_pipeline.common.thresholds import (
    MARKET_DISTRIBUTION_PCT_THRESHOLD,
    MARKET_DISTRIBUTION_LOOKBACK_DAYS,
)
```

2. line 11 의 `DISTRIBUTION_DAY_PCT_THRESHOLD = -0.2   # community standard, IBD` 를:

```python
# 기존 module-level 상수는 SSOT 로 이전. 호환성 별칭 유지.
DISTRIBUTION_DAY_PCT_THRESHOLD = MARKET_DISTRIBUTION_PCT_THRESHOLD
```

3. line 27 의 `def count_distribution_days(index_df: pd.DataFrame, end_idx: int, lookback: int = 25) -> int:` 를:

```python
def count_distribution_days(
    index_df: pd.DataFrame,
    end_idx: int,
    lookback: int = MARKET_DISTRIBUTION_LOOKBACK_DAYS,
) -> int:
```

기존 함수 본체 (line 24 의 사용 등) 는 그대로.

- [ ] **Step 2: Run distribution_day tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/ -v -k "distribution" 2>&1 | tail -20`
Expected: 기존 테스트 PASS

- [ ] **Step 3: Commit**

```bash
git add kr_pipeline/market_context/compute/distribution_day.py
git commit -m "refactor(ssot): distribution_day (시장) 가 SSOT 참조

DISTRIBUTION_DAY_PCT_THRESHOLD (-0.2), lookback default (25) 를 SSOT 에서
import. 호환성 별칭 유지. 동작 변화 0."
```

---

## Task 7: status.py — 5 module-level 상수

**Files:**
- Modify: `kr_pipeline/market_context/compute/status.py`

- [ ] **Step 1: Replace 5 module-level constants**

Read `kr_pipeline/market_context/compute/status.py` first (line 15-19).

Edit `kr_pipeline/market_context/compute/status.py`:

1. 파일 상단에 SSOT import 추가:

```python
from kr_pipeline.common.thresholds import (
    STATUS_CORRECTION_OFF_HIGH_PCT,
    STATUS_DOWNTREND_OFF_HIGH_PCT,
    STATUS_DIST_COUNT_FOR_FTD_INVALIDATION,
    STATUS_FTD_RECENT_DAYS,
    STATUS_FTD_INVALIDATION_DAYS,
)
```

2. line 15-19 의 5 상수를 다음으로 교체 (이름 유지):

```python
# 기존 module-level 상수는 SSOT 로 이전. 호환성 별칭 유지.
CORRECTION_OFF_HIGH_PCT = STATUS_CORRECTION_OFF_HIGH_PCT
DOWNTREND_OFF_HIGH_PCT = STATUS_DOWNTREND_OFF_HIGH_PCT
DIST_COUNT_THRESHOLD_FOR_FTD_INVALIDATION = STATUS_DIST_COUNT_FOR_FTD_INVALIDATION
FTD_RECENT_DAYS = STATUS_FTD_RECENT_DAYS
FTD_INVALIDATION_DAYS = STATUS_FTD_INVALIDATION_DAYS
```

함수 본체 (line 37-59) 의 사용처는 그대로.

- [ ] **Step 2: Run status tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/ -v -k "status or market_context" 2>&1 | tail -20`
Expected: 기존 테스트 PASS

- [ ] **Step 3: Commit**

```bash
git add kr_pipeline/market_context/compute/status.py
git commit -m "refactor(ssot): status.py 5 상수가 SSOT 참조

CORRECTION/DOWNTREND off-high pct, DIST_COUNT FTD invalidation, FTD_RECENT_DAYS,
FTD_INVALIDATION_DAYS 를 SSOT 에서 import. 호환성 별칭 유지. 동작 변화 0."
```

---

## Task 8: store.py (RS_RATING SQL 안의 값)

**Files:**
- Modify: `kr_pipeline/indicators/store.py`

이 task 는 다른 task 와 다르다: hardcoded 값 `70` 이 SQL 문자열 안에 있어서 단순 import 로 안 됨. f-string 으로 SQL 을 빌드해서 SSOT 값을 주입한다.

- [ ] **Step 1: Read current SQL**

Read `kr_pipeline/indicators/store.py` line 80-100 부근.

- [ ] **Step 2: Replace SQL hardcoded 70 with f-string**

Edit `kr_pipeline/indicators/store.py`:

1. 파일 상단에 SSOT import 추가:

```python
from kr_pipeline.common.thresholds import C8_RS_RATING_MIN
```

2. `update_minervini_c8_and_pass` 함수 (line ~85-100) 의 SQL string 안 `rs_rating >= 70` 을 f-string + 파라미터로 변경.

기존 (예상):
```python
def update_minervini_c8_and_pass(conn: Connection) -> int:
    """단일 SQL UPDATE 로 c8 (rs_rating >= 70) 와 minervini_pass (c1..c8 ALL TRUE) 계산."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE daily_indicators
               SET minervini_c8 = (rs_rating >= 70),
                   minervini_pass = (
                       minervini_c1 IS TRUE AND ...
                       minervini_c7 IS TRUE AND (rs_rating >= 70)
                   ),
                   updated_at = NOW()
             WHERE ...
            """
        )
        return cur.rowcount
```

변경 후:
```python
def update_minervini_c8_and_pass(conn: Connection) -> int:
    """단일 SQL UPDATE 로 c8 (rs_rating >= C8_RS_RATING_MIN) 와 minervini_pass 계산."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE daily_indicators
               SET minervini_c8 = (rs_rating >= %s),
                   minervini_pass = (
                       minervini_c1 IS TRUE AND ...
                       minervini_c7 IS TRUE AND (rs_rating >= %s)
                   ),
                   updated_at = NOW()
             WHERE ...
            """,
            (C8_RS_RATING_MIN, C8_RS_RATING_MIN),
        )
        return cur.rowcount
```

**중요**: SQL injection 회피 — `%s` placeholder + psycopg parameter binding 사용 (f-string 으로 직접 값 삽입 금지). C8_RS_RATING_MIN 은 정수 상수라 직접 f-string 도 안전하지만, *원칙*상 parameter binding 이 안전.

기존 SQL 의 `WHERE` 조건 + 다른 부분은 그대로 유지. 단지 `rs_rating >= 70` 두 곳을 `rs_rating >= %s` 로 + params 추가.

실제 SQL 구조는 Read 로 확인 후 정확히 교체.

- [ ] **Step 3: Run store tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/ -v -k "store or minervini_pass" 2>&1 | tail -20`
Expected: 기존 테스트 PASS

- [ ] **Step 4: Commit**

```bash
git add kr_pipeline/indicators/store.py
git commit -m "refactor(ssot): store.update_minervini_c8_and_pass SQL 이 SSOT 참조

rs_rating >= 70 hardcoded → C8_RS_RATING_MIN 을 parameter binding 으로
주입. SQL injection 회피. 동작 변화 0."
```

---

## Task 9: delta.py — RECENT_WINDOW_DAYS

**Files:**
- Modify: `kr_pipeline/llm_runner/compute/delta.py`

- [ ] **Step 1: Replace RECENT_WINDOW_DAYS**

Read `kr_pipeline/llm_runner/compute/delta.py` first.

Edit `kr_pipeline/llm_runner/compute/delta.py`:

line 12 의 `RECENT_WINDOW_DAYS = 7` 을:

```python
from kr_pipeline.common.thresholds import RECENT_CLASSIFICATION_WINDOW_DAYS

# 기존 module-level 상수는 SSOT 로 이전. 호환성 별칭 유지.
RECENT_WINDOW_DAYS = RECENT_CLASSIFICATION_WINDOW_DAYS
```

line 19 의 사용처 (`cutoff = as_of - timedelta(days=RECENT_WINDOW_DAYS)`) 는 그대로.

- [ ] **Step 2: Run delta tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/ -v -k "delta or find_new" 2>&1 | tail -20`
Expected: 기존 테스트 PASS

- [ ] **Step 3: Full integration check — 모든 Python 코드 통합 검증**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/ 2>&1 | tail -30`
Expected: 사전 존재 isolation 이슈 외 모든 PASS (이전 audit 단계와 동일 baseline).

새로 깨진 테스트 있으면 그 파일을 검토해 import 누락 등 확인.

- [ ] **Step 4: Commit**

```bash
git add kr_pipeline/llm_runner/compute/delta.py
git commit -m "refactor(ssot): delta.py 의 RECENT_WINDOW_DAYS 가 SSOT 참조

호환성 별칭 유지. 동작 변화 0. Phase A (Python 코드 → SSOT 교체) 완료."
```

---

## Task 10: 빌드 스크립트 + generated.ts

**Files:**
- Create: `scripts/export_thresholds.py`
- Create: `web/src/data/thresholds.generated.ts`
- Modify: `package.json` (web/ 디렉터리) — optional `build:thresholds` 스크립트 추가

- [ ] **Step 1: Write the build script**

Create `scripts/export_thresholds.py`:

```python
"""SSOT thresholds.py → web/src/data/thresholds.generated.ts 자동 생성.

사용:
    uv run python scripts/export_thresholds.py

이 스크립트는 빌드 단계 또는 SSOT 변경 시 수동 실행. 결과 파일
(thresholds.generated.ts) 은 git 에 commit (drift 추적용).
"""
import inspect
import json
from pathlib import Path
from typing import Any

from kr_pipeline.common import thresholds as ssot

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "web" / "src" / "data" / "thresholds.generated.ts"

HEADER = """\
/* eslint-disable */
// AUTO-GENERATED — DO NOT EDIT BY HAND.
// Source: kr_pipeline/common/thresholds.py
// Regenerate: `uv run python scripts/export_thresholds.py`
"""


def _to_ts_value(v: Any) -> str:
    """Python 값을 TypeScript literal 로 직렬화."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, dict):
        items = ", ".join(f'"{k}": {_to_ts_value(val)}' for k, val in v.items())
        return "{ " + items + " }"
    if isinstance(v, (list, tuple)):
        items = ", ".join(_to_ts_value(x) for x in v)
        return "[" + items + "]"
    raise TypeError(f"Unsupported type for SSOT export: {type(v)}")


def _ts_type(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "number"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, dict):
        # 값 타입 균일 가정 (현 SSOT 의 dict 는 {market: float} 형태)
        if v:
            inner = _ts_type(next(iter(v.values())))
            return f"Record<string, {inner}>"
        return "Record<string, unknown>"
    if isinstance(v, list):
        if v:
            return f"{_ts_type(v[0])}[]"
        return "unknown[]"
    return "unknown"


def main() -> None:
    lines: list[str] = [HEADER]

    # ssot 모듈의 module-level 상수만 추출 (Final[...] 또는 평범한 대문자 변수)
    for name, value in vars(ssot).items():
        if name.startswith("_"):
            continue
        if inspect.ismodule(value) or inspect.isfunction(value) or inspect.isclass(value):
            continue
        # typing.Final 등 typing 이름은 skip
        if getattr(value, "__module__", None) == "typing":
            continue
        if not name.isupper() and not name[0].isupper():
            continue
        ts_type = _ts_type(value)
        ts_value = _to_ts_value(value)
        lines.append(f"export const {name}: {ts_type} = {ts_value};")

    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH} ({len(lines)-1} constants)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the build script**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run python scripts/export_thresholds.py`
Expected: `Wrote /Users/.../web/src/data/thresholds.generated.ts (XX constants)`

- [ ] **Step 3: Inspect the generated file**

Run: `head -40 web/src/data/thresholds.generated.ts`
Expected: 헤더 + `export const GATE_BREAKOUT_VOL_MULT: number = 1.0;` 등이 보임.

수동 확인: 모든 SSOT 상수가 export 됐는지 (약 21개 — typing.Final 제외).

- [ ] **Step 4: tsc clean check**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit`
Expected: CLEAN (generated.ts 가 tsc 통과)

- [ ] **Step 5: Commit**

```bash
git add scripts/export_thresholds.py web/src/data/thresholds.generated.ts
git commit -m "feat(ssot): scripts/export_thresholds.py + 자동 생성된 thresholds.generated.ts

Python SSOT (kr_pipeline/common/thresholds.py) → TypeScript 상수 모듈로
변환. UI 가 이 파일을 참조하면 SSOT 변경 시 자동 동기화 (수동 동기화는
별도 plan 에서 — UI hard-coded 값들을 generated.ts import 로 교체).

빌드: uv run python scripts/export_thresholds.py."
```

---

## Self-Review

**1. Spec coverage**: spec SSOT-1 행 (line 85) 의 요구 사항:
- ✅ 모든 책-유래 임계를 단일 모듈에 상수로 정의 → Task 1
- ✅ 코드는 import → Task 2-9
- ✅ UI 데이터는 모듈에서 생성 (빌드시 주입) → Task 10
- ⚠️ Prompt 빌드는 이 모듈에서 생성 → **이 plan 의 scope 외**. Prompt 는 정적 .md 유지, 별도 검증 스크립트 (후속 plan) 가 SSOT ↔ prompt 일치 점검.
- ⚠️ UI 의 hard-coded 값들을 generated.ts 참조로 *실제 교체* → **이 plan 의 scope 외**. 별도 plan (P1 단계) 에서 처리.

**Scope 명확화**: 이 plan 은 SSOT 인프라 구축 + Python 코드 동기화 + generated.ts 자동 생성까지. UI 교체와 Prompt 검증은 별도 plan.

**2. Placeholder scan**: 모든 step 에 코드 또는 명령. "TODO", "implement later" 없음. ✅

**3. Type consistency**: 
- SSOT 모듈의 상수명이 task 2-9 의 import 와 일치 ✅
- `FTD_PCT_THRESHOLD` 만 SSOT 에선 dict, follow_through.py 에선 float — Task 5 에서 별칭 import (`_SSOT_FTD_PCT_THRESHOLD`) + `[KOSPI]` 추출로 처리 ✅

**4. 한계 / 후속 plan**:
- P1 단계 plan: UI hard-coded 값들 (InfoTooltip / ClassificationsPage / HomePage / LlmPipelinePage / audit 데이터 / simulation) 을 `thresholds.generated` import 로 교체
- P3 단계 plan: SSOT ↔ prompt 일치 검증 스크립트 (`scripts/verify_prompts_match_ssot.py`)
- 이 plan 의 호환성 별칭 (예: `BREAKOUT_VOLUME_MULTIPLIER = GATE_BREAKOUT_VOL_MULT`) 은 추후 모든 외부 import 가 SSOT 로 마이그레이트되면 제거 가능 (장기 housekeeping)

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-22-ssot-thresholds.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
