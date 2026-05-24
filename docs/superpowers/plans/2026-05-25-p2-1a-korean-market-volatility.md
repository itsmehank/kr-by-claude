# P2-1a Korean Market Volatility Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spec `2026-05-25-p2-1a-korean-market-volatility-design.md` (commit `1990390`) 구현 — KOSPI/KOSDAQ 시장별 σ rolling 측정 → NASDAQ 기준 임계 변환 → `detect_last_ftd` / `count_distribution_days` 호출 시 보정 임계 전달. 책 원리 B (TLOND p.232-233 "한 나라 두 지수도 다른 임계") 위반 해소.

**Architecture:** 3 순수 함수 (`compute_korean_sigma_pct` / `derive_market_thresholds` / `book_default_thresholds`) 가 신규 `volatility.py` 에 위치. SSOT 7 상수 (`kr_pipeline/common/thresholds.py`) 가 base 값 + clamp 정책 + window 정책 보유. `follow_through.py` / `distribution_day.py` 의 함수 시그니처에 `pct_threshold` 인자 추가 (default = SSOT base — 책 호환). `modes.py` 의 `_process_one_date` 에 σ 측정 → 보정 임계 → 전달 단계 삽입.

**Tech Stack:** Python 3.12+, psycopg, pandas, pytest

**Spec:** `docs/superpowers/specs/2026-05-25-p2-1a-korean-market-volatility-design.md` (commit `1990390`)

---

## Implementation Order

6 task. 의존성:

```
Task 1 (SSOT 상수 + generated.ts)
  ↓ (volatility.py 가 SSOT import)
Task 2 (volatility.py + 단위 테스트)
  │
  ├→ Task 3 (follow_through.py pct_threshold 인자화)
  │     └→ default 값에 FTD_PCT_BASE 사용 → Task 1 필요
  │
  └→ Task 4 (distribution_day.py pct_threshold 인자화)
        └→ default 값에 DISTRIBUTION_PCT_BASE 사용 → Task 1 필요
  ↓ (모두 완료 후)
Task 5 (modes.py data flow — σ 측정 → 보정 → 전달)
  ↓
Task 6 (통합 테스트 — end-to-end + 회귀 + 경계)
```

---

## File Structure

### 신규

| Path | Responsibility |
|---|---|
| `kr_pipeline/market_context/compute/volatility.py` | 3 순수 함수 (σ 측정 / 임계 derive / fallback) |
| `tests/test_volatility.py` | 단위 테스트 (3 함수 + clamp + scheme) |

### 수정

| Path | What |
|---|---|
| `kr_pipeline/common/thresholds.py` | SSOT 7 상수 추가 + `FTD_PCT_THRESHOLD` dict 제거 + `MARKET_DISTRIBUTION_PCT_THRESHOLD` 호환 별칭 유지 (deprecated 주석) |
| `tests/test_common_thresholds.py` | 신규 상수 테스트 추가 + 제거 dict 테스트 제거 |
| `kr_pipeline/market_context/compute/follow_through.py` | `detect_last_ftd` 시그니처에 `pct_threshold` 인자. 호환 별칭 `FTD_PCT_THRESHOLD` 제거. 함수 본체 `FTD_PCT_THRESHOLD` 참조 → `pct_threshold` 로 |
| `kr_pipeline/market_context/compute/distribution_day.py` | `is_distribution_day` + `count_distribution_days` 시그니처에 `pct_threshold` 인자. 함수 본체 참조 갱신 |
| `kr_pipeline/market_context/modes.py` | `_process_one_date` 에 σ 측정 → 보정 임계 → 전달. `COMPUTATION_NOTES` 의 임계 값 동적 화 (선택) |
| `tests/test_market_context_status.py` | 통합 테스트 (회귀 + 경계) — 파일 없으면 신규 |
| `web/src/data/thresholds.generated.ts` | 자동 재생성 (Task 1 끝 + Task 6 끝) |

---

## Task 1: SSOT 7 상수 추가 + 기존 정리

**Files:**
- Modify: `kr_pipeline/common/thresholds.py`
- Modify: `tests/test_common_thresholds.py`
- Modify: `web/src/data/thresholds.generated.ts` (자동 재생성)

### Step 1: Add 7 new constants

Read `kr_pipeline/common/thresholds.py` 상단 import 와 기존 구조 확인 (대략 line 1-30).

기존 `FTD_PCT_THRESHOLD: dict = {"KOSPI": 1.4, "KOSDAQ": 1.4}` 와 `MARKET_DISTRIBUTION_PCT_THRESHOLD: float = -0.2` 가 있을 것.

Edit `kr_pipeline/common/thresholds.py`:

1. `FTD_PCT_THRESHOLD` dict 항목을 *제거* (다음 step 에서 호환 별칭 처리).

2. `MARKET_DISTRIBUTION_PCT_THRESHOLD` 정의 *직후* (또는 파일 끝부분) 에 다음 블록 추가:

```python
# ===== P2-1a: Market volatility correction (한국시장 보정) =====

NASDAQ_REFERENCE_SIGMA: Final[float] = 1.0
"""정상 시장 NASDAQ 일간 % σ (단순수익률 기준).
책 명시 없음 — TLOND p.232-233 의 FTD 1.0-1.5% 임계 밴드의 분모로 implied.
Regime shift 시 재도출. 단위 정합: 임계 비교 대상 (FTD 1.4% / distribution
-0.2%) 이 단순수익률이므로 σ 도 단순수익률 기준 (log 아님)."""

FTD_PCT_BASE: Final[float] = 1.4
"""NASDAQ 기준 FTD 임계 (% 일간 상승).
책: TLOND p.232-233 (2003 NASDAQ).
한국 임계 = FTD_PCT_BASE × ratio_applied."""

DISTRIBUTION_PCT_BASE: Final[float] = -0.2
"""NASDAQ 기준 시장 distribution day 임계 (% 일간 하락).
책: O'Neil HMMS Ch.9 + IBD/Dr.K 통용. TLOND p.231 -0.1% 선호 (해석본) —
원전 우선으로 -0.2% 채택. 거래량 조건 (전일 초과) 은 별도 인자 (보정 제외).
한국 임계 = DISTRIBUTION_PCT_BASE × ratio_applied."""

SIGMA_WINDOW_DAYS: Final[int] = 252
"""한국 σ rolling window (1년 거래일).
환경 변화 부분적 반영. EWMA 등 동적 가중은 미적용 (단순 우선)."""

SIGMA_MIN_DATA_RATIO: Final[float] = 200 / 252
"""σ 측정 최소 데이터 비율. window_days * min_data_ratio 미만이면 None 반환
→ book_default_thresholds 로 fallback. 약 0.79 (200/252 거래일)."""

KOREAN_SIGMA_RATIO_FLOOR: Final[float] = 1.0
"""ratio clamp 하한. 한국 임계 ≥ 책 임계 보장 — 책의 'explosive / institutional
selling' 강도 최소 강제."""

KOREAN_SIGMA_RATIO_CEILING: Final[float] = 2.5
"""ratio clamp 상한. TLOND FTD 임계 역사 1.0-1.7% 좁은 밴드 근거 — 패닉기
한국 σ 폭증 (예: 5-6%) 시 임계 7% 이상으로 폭주 → confirmed_uptrend 봉쇄
→ 패닉 직후 매수 구간 통째 누락 방지. 평시 한국 σ 2.3 < 2.5 → 평시 투명.
패닉기에만 안전장치."""
```

3. 기존 `MARKET_DISTRIBUTION_PCT_THRESHOLD` 위에 deprecated 주석 추가 + 호환 별칭 유지:

기존:
```python
MARKET_DISTRIBUTION_PCT_THRESHOLD: Final[float] = -0.2
"""..."""
```

변경 (DISTRIBUTION_PCT_BASE 블록 다음 또는 같은 위치):
```python
# Deprecated alias — DISTRIBUTION_PCT_BASE 로 이전 (P2-1a). 다음 사이클 cleanup.
MARKET_DISTRIBUTION_PCT_THRESHOLD: Final[float] = DISTRIBUTION_PCT_BASE
```

(기존 docstring 은 DISTRIBUTION_PCT_BASE 로 이전됨. 별칭만 한 줄.)

### Step 2: Update tests

Read `tests/test_common_thresholds.py` 의 기존 test 들.

Edit `tests/test_common_thresholds.py`:

1. 기존 `FTD_PCT_THRESHOLD` dict 테스트가 있으면 제거 (또는 `pytest.raises(AttributeError)` 로 *제거 확인* — overkill, 그냥 제거).

2. 신규 7 상수 테스트 추가 (예: 기존 test 함수들 다음):

```python
def test_p2_1a_constants():
    """P2-1a 한국시장 보정 SSOT 상수 7개."""
    from kr_pipeline.common import thresholds as t
    assert t.NASDAQ_REFERENCE_SIGMA == 1.0
    assert t.FTD_PCT_BASE == 1.4
    assert t.DISTRIBUTION_PCT_BASE == -0.2
    assert t.SIGMA_WINDOW_DAYS == 252
    assert abs(t.SIGMA_MIN_DATA_RATIO - 200 / 252) < 1e-9
    assert t.KOREAN_SIGMA_RATIO_FLOOR == 1.0
    assert t.KOREAN_SIGMA_RATIO_CEILING == 2.5


def test_market_distribution_pct_threshold_aliased():
    """호환 별칭이 DISTRIBUTION_PCT_BASE 와 동일 값."""
    from kr_pipeline.common import thresholds as t
    assert t.MARKET_DISTRIBUTION_PCT_THRESHOLD == t.DISTRIBUTION_PCT_BASE
```

### Step 3: Run SSOT tests

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_common_thresholds.py -v`
Expected: 모든 테스트 PASS (기존 + 새 2개).

### Step 4: Regenerate thresholds.generated.ts

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run python scripts/export_thresholds.py`
Expected: `Wrote .../thresholds.generated.ts (NN constants)` — NN 이 7 증가 (이전 + 7).

검증: `grep "NASDAQ_REFERENCE_SIGMA\|FTD_PCT_BASE\|DISTRIBUTION_PCT_BASE\|SIGMA_WINDOW_DAYS\|KOREAN_SIGMA_RATIO" web/src/data/thresholds.generated.ts` 7 줄 표시.

### Step 5: tsc clean

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`.

### Step 6: Commit

```bash
git add kr_pipeline/common/thresholds.py tests/test_common_thresholds.py web/src/data/thresholds.generated.ts
git commit -m "feat(p2-1a): SSOT 7 상수 추가 (한국시장 보정 base + window + clamp)

NASDAQ_REFERENCE_SIGMA / FTD_PCT_BASE / DISTRIBUTION_PCT_BASE /
SIGMA_WINDOW_DAYS / SIGMA_MIN_DATA_RATIO / KOREAN_SIGMA_RATIO_FLOOR /
KOREAN_SIGMA_RATIO_CEILING.

기존 정리: FTD_PCT_THRESHOLD dict 제거 (이제 동적 계산 — 시장별 보정 임계
가 status.py 호출 단에서 derive). MARKET_DISTRIBUTION_PCT_THRESHOLD 는
DISTRIBUTION_PCT_BASE 호환 별칭으로 유지 (다음 사이클 cleanup).

generated.ts 자동 재생성으로 UI 도 새 상수 자동 노출."
```

---

## Task 2: volatility.py 신규 + 단위 테스트

**Files:**
- Create: `kr_pipeline/market_context/compute/volatility.py`
- Create: `tests/test_volatility.py`

### Step 1: Write failing test

Create `tests/test_volatility.py`:

```python
"""kr_pipeline/market_context/compute/volatility.py 단위 테스트.

3 순수 함수: compute_korean_sigma_pct / derive_market_thresholds /
book_default_thresholds.
"""
import pandas as pd
import pytest

from kr_pipeline.market_context.compute.volatility import (
    compute_korean_sigma_pct,
    derive_market_thresholds,
    book_default_thresholds,
)


# ===== derive_market_thresholds =====

def test_derive_no_clamp():
    """raw_ratio 가 [floor, ceiling] 안이면 clamped=False, 그대로 사용."""
    result = derive_market_thresholds(
        sigma_pct=1.5,
        anchor_sigma=1.0,
        ftd_base=1.4,
        dist_base=-0.2,
        clamp_floor=1.0,
        clamp_ceiling=2.5,
    )
    assert result["raw_ratio"] == 1.5
    assert result["ratio_applied"] == 1.5
    assert result["clamped"] is False
    assert result["ftd_pct"] == pytest.approx(1.4 * 1.5)
    assert result["distribution_pct"] == pytest.approx(-0.2 * 1.5)
    assert result["source"] == "sigma_derived"


def test_derive_floor_clamp():
    """raw_ratio 가 floor 미만이면 floor 로 clamp."""
    result = derive_market_thresholds(
        sigma_pct=0.5,
        anchor_sigma=1.0,
        ftd_base=1.4, dist_base=-0.2,
        clamp_floor=1.0, clamp_ceiling=2.5,
    )
    assert result["raw_ratio"] == 0.5
    assert result["ratio_applied"] == 1.0
    assert result["clamped"] is True
    assert result["ftd_pct"] == pytest.approx(1.4)
    assert result["distribution_pct"] == pytest.approx(-0.2)


def test_derive_ceiling_clamp():
    """raw_ratio 가 ceiling 초과면 ceiling 으로 clamp."""
    result = derive_market_thresholds(
        sigma_pct=5.0,
        anchor_sigma=1.0,
        ftd_base=1.4, dist_base=-0.2,
        clamp_floor=1.0, clamp_ceiling=2.5,
    )
    assert result["raw_ratio"] == 5.0
    assert result["ratio_applied"] == 2.5
    assert result["clamped"] is True
    assert result["ftd_pct"] == pytest.approx(1.4 * 2.5)
    assert result["distribution_pct"] == pytest.approx(-0.2 * 2.5)


def test_derive_schema_keys():
    """반환 dict 가 정확히 6 키."""
    result = derive_market_thresholds(
        sigma_pct=2.0, anchor_sigma=1.0,
        ftd_base=1.4, dist_base=-0.2,
        clamp_floor=1.0, clamp_ceiling=2.5,
    )
    assert set(result.keys()) == {
        "ftd_pct", "distribution_pct", "raw_ratio",
        "ratio_applied", "clamped", "source",
    }


# ===== book_default_thresholds =====

def test_book_defaults_match_pre_p2_1a():
    """fallback 결과가 pre-P2-1a behavior 와 정확히 일치."""
    result = book_default_thresholds(ftd_base=1.4, dist_base=-0.2)
    assert result["ftd_pct"] == 1.4
    assert result["distribution_pct"] == -0.2
    assert result["raw_ratio"] is None
    assert result["ratio_applied"] == 1.0
    assert result["clamped"] is False
    assert result["source"] == "book_default"


def test_book_defaults_schema_matches_derive():
    """fallback 과 derive 의 dict 키가 동일 (호출단 분기 단순화)."""
    derived = derive_market_thresholds(
        sigma_pct=2.0, anchor_sigma=1.0,
        ftd_base=1.4, dist_base=-0.2,
        clamp_floor=1.0, clamp_ceiling=2.5,
    )
    book = book_default_thresholds(ftd_base=1.4, dist_base=-0.2)
    assert set(derived.keys()) == set(book.keys())


# ===== compute_korean_sigma_pct =====

class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
    def execute(self, *args, **kwargs):
        pass
    def fetchall(self):
        return self._rows
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
    def cursor(self):
        return _FakeCursor(self._rows)


def test_compute_sigma_normal():
    """252 row 정상 σ 측정."""
    from datetime import date
    # close: 100, 101, 100, 101, ... 의 단순수익률 σ
    closes = [(100.0,) if i % 2 == 0 else (101.0,) for i in range(252)]
    conn = _FakeConn(closes)
    sigma = compute_korean_sigma_pct(conn, "1001", as_of=date(2026, 5, 21))
    # 단순수익률 alternates +1%, -0.99% → σ ≈ 1.0%
    assert sigma is not None
    assert 0.9 < sigma < 1.1


def test_compute_sigma_insufficient_data():
    """rows < window * min_data_ratio (≈200) 이면 None."""
    from datetime import date
    closes = [(100.0,)] * 100  # 100 < 200
    conn = _FakeConn(closes)
    sigma = compute_korean_sigma_pct(conn, "1001", as_of=date(2026, 5, 21))
    assert sigma is None


def test_compute_sigma_exact_min_data():
    """rows == window * min_data_ratio 경계 — 측정 가능."""
    from datetime import date
    closes = [(100.0 + i * 0.1,) for i in range(200)]  # exact 200
    conn = _FakeConn(closes)
    sigma = compute_korean_sigma_pct(conn, "1001", as_of=date(2026, 5, 21))
    assert sigma is not None
```

### Step 2: Run test to verify failures

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_volatility.py -v 2>&1 | tail -20`
Expected: FAIL — `ImportError` (volatility 모듈 미존재) 또는 함수 미정의.

### Step 3: Create volatility.py

Create `kr_pipeline/market_context/compute/volatility.py`:

```python
# kr_pipeline/market_context/compute/volatility.py
"""한국시장 변동성 보정 — σ 측정 + 임계 derive.

3 순수 함수 (DB 캐시 안 함):
- compute_korean_sigma_pct: index_daily 의 1년 rolling 단순수익률 σ
- derive_market_thresholds: σ → ratio → clamp → 보정 임계
- book_default_thresholds: fallback (σ 측정 실패 시 책 기본값)

Spec: docs/superpowers/specs/2026-05-25-p2-1a-korean-market-volatility-design.md
"""
from datetime import date

import pandas as pd
from psycopg import Connection

from kr_pipeline.common.thresholds import (
    SIGMA_WINDOW_DAYS,
    SIGMA_MIN_DATA_RATIO,
)


def compute_korean_sigma_pct(
    conn: Connection,
    index_code: str,
    *,
    as_of: date,
    window_days: int = SIGMA_WINDOW_DAYS,
    min_data_ratio: float = SIGMA_MIN_DATA_RATIO,
) -> float | None:
    """한국 지수 일간 % 변화율 (단순수익률) 의 rolling 표준편차.

    단순수익률: pct_change = (close_t / close_{t-1}) - 1.
    log 수익률 (log(p_t / p_{t-1})) 아님 — 임계 비교 대상 (FTD 1.4% / dist
    -0.2%) 이 모두 단순수익률이라 단위 정합 위해.

    Look-ahead 방지: WHERE date <= as_of (당일 포함). as_of 이후 데이터는
    절대 안 봄. 백테스트 / 과거 status 재계산 안전.

    Args:
        conn: psycopg connection
        index_code: 지수 코드 (예: "1001" KOSPI, "2001" KOSDAQ)
        as_of: 측정 기준일 (당일 포함)
        window_days: 윈도우 거래일 수 (default SIGMA_WINDOW_DAYS=252)
        min_data_ratio: 최소 데이터 비율 (default SIGMA_MIN_DATA_RATIO≈0.79)

    Returns:
        float: rolling σ (% 단위, 예: 2.34 = 2.34%)
        None: 가용 row 수 < window_days * min_data_ratio → 호출단 fallback
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT close FROM index_daily
             WHERE index_code = %s AND date <= %s
             ORDER BY date DESC LIMIT %s
            """,
            (index_code, as_of, window_days),
        )
        rows = cur.fetchall()

    if len(rows) < window_days * min_data_ratio:
        return None

    # rows 는 최신 → 과거 순. pct_change 계산을 위해 reverse (오래된 → 최신).
    closes = pd.Series([float(r[0]) for r in reversed(rows)])
    returns_pct = closes.pct_change().dropna() * 100  # % 단위 단순수익률
    return float(returns_pct.std())


def derive_market_thresholds(
    sigma_pct: float,
    *,
    anchor_sigma: float,
    ftd_base: float,
    dist_base: float,
    clamp_floor: float,
    clamp_ceiling: float,
) -> dict:
    """σ → ratio → clamp → base × ratio.

    Clamp 적용 지점: ratio 에만. % 임계에 직접 clamp 금지 (SSOT 원칙 — floor/
    ceiling 값이 FTD·distribution 두 곳에 중복 정의 방지).

    절차:
        raw_ratio = sigma_pct / anchor_sigma
        ratio_applied = clamp(raw_ratio, floor=clamp_floor, ceiling=clamp_ceiling)
        ftd_pct = ftd_base * ratio_applied
        distribution_pct = dist_base * ratio_applied

    Returns:
        {
            "ftd_pct": float,             # ftd_base * ratio_applied
            "distribution_pct": float,    # dist_base * ratio_applied
            "raw_ratio": float,           # 측정값 그대로 (디버깅)
            "ratio_applied": float,       # clamp 적용 후
            "clamped": bool,              # raw_ratio != ratio_applied
            "source": "sigma_derived",
        }
    """
    raw_ratio = sigma_pct / anchor_sigma
    ratio_applied = max(clamp_floor, min(clamp_ceiling, raw_ratio))
    return {
        "ftd_pct": ftd_base * ratio_applied,
        "distribution_pct": dist_base * ratio_applied,
        "raw_ratio": raw_ratio,
        "ratio_applied": ratio_applied,
        "clamped": raw_ratio != ratio_applied,
        "source": "sigma_derived",
    }


def book_default_thresholds(*, ftd_base: float, dist_base: float) -> dict:
    """Fallback — σ 측정 실패 시 책 기본값. derive 와 동일 스키마.

    회귀 보장: 이 경로의 결과 == pre-P2-1a behavior (보정 비활성 시 결과).

    Returns:
        {
            "ftd_pct": ftd_base,          # = pre-P2-1a 값 (예: 1.4)
            "distribution_pct": dist_base, # = pre-P2-1a 값 (예: -0.2)
            "raw_ratio": None,
            "ratio_applied": 1.0,
            "clamped": False,
            "source": "book_default",
        }
    """
    return {
        "ftd_pct": ftd_base,
        "distribution_pct": dist_base,
        "raw_ratio": None,
        "ratio_applied": 1.0,
        "clamped": False,
        "source": "book_default",
    }
```

### Step 4: Run tests to verify PASS

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_volatility.py -v 2>&1 | tail -25`
Expected: 모든 테스트 PASS (8-10 case).

### Step 5: Commit

```bash
git add kr_pipeline/market_context/compute/volatility.py tests/test_volatility.py
git commit -m "feat(p2-1a): volatility.py 신규 — 3 순수 함수 (σ + derive + fallback)

compute_korean_sigma_pct: index_daily 1년 rolling 단순수익률 σ. look-ahead
방지 (WHERE date <= as_of), 데이터 부족 (rows < window×0.79) 시 None.

derive_market_thresholds: σ → ratio → clamp [floor, ceiling] → base × ratio.
반환 6 키 dict (ftd_pct, distribution_pct, raw_ratio, ratio_applied,
clamped, source).

book_default_thresholds: fallback. derive 와 동일 스키마. pre-P2-1a behavior
회귀 보장."
```

---

## Task 3: follow_through.py `pct_threshold` 인자화

**Files:**
- Modify: `kr_pipeline/market_context/compute/follow_through.py`

### Step 1: Verify no external import of FTD_PCT_THRESHOLD alias

Run: `grep -rn "FTD_PCT_THRESHOLD" --include="*.py" kr_pipeline/ tests/ api/ 2>/dev/null | grep -v "common/thresholds.py" | grep -v "follow_through.py"`
Expected: 출력 없음 (외부 import 없음 — 별칭 제거 안전).

만약 외부 import 있으면 그 위치 정리 후 진행.

### Step 2: Update follow_through.py — remove alias + add pct_threshold arg

Read `kr_pipeline/market_context/compute/follow_through.py` 전체 (대략 line 1-80).

Edit `kr_pipeline/market_context/compute/follow_through.py`:

1. 상단 import 부분 변경. 기존:

```python
from kr_pipeline.common.thresholds import (
    FTD_PCT_THRESHOLD as _SSOT_FTD_PCT_THRESHOLD,
    FTD_RALLY_WINDOW_MIN_DAYS,
    FTD_RALLY_WINDOW_MAX_DAYS,
    FTD_LOW_LOOKBACK_DAYS,
)

# 기존 module-level 상수는 SSOT (kr_pipeline/common/thresholds.py) 로 이전.
# 호환성을 위해 같은 이름 별칭 유지. 시장별 임계는 추후 (P2-1a) 별도 함수
# 인자로 받도록 변경 예정 — 현재는 양 시장 동일 1.4% 사용.
FTD_PCT_THRESHOLD = _SSOT_FTD_PCT_THRESHOLD["KOSPI"]  # = KOSDAQ 도 동일값
FTD_RALLY_WINDOW_MIN = FTD_RALLY_WINDOW_MIN_DAYS
FTD_RALLY_WINDOW_MAX = FTD_RALLY_WINDOW_MAX_DAYS
FTD_LOW_LOOKBACK = FTD_LOW_LOOKBACK_DAYS
```

변경:

```python
from kr_pipeline.common.thresholds import (
    FTD_PCT_BASE,
    FTD_RALLY_WINDOW_MIN_DAYS,
    FTD_RALLY_WINDOW_MAX_DAYS,
    FTD_LOW_LOOKBACK_DAYS,
)

# P2-1a: FTD_PCT_THRESHOLD 호환 별칭 제거. pct_threshold 가 detect_last_ftd
# 의 인자로 이전 — 시장별 보정 임계를 호출단 (modes.py) 이 주입.
# Window / lookback 별칭만 유지 (보정 제외 — 책 그대로).
FTD_RALLY_WINDOW_MIN = FTD_RALLY_WINDOW_MIN_DAYS
FTD_RALLY_WINDOW_MAX = FTD_RALLY_WINDOW_MAX_DAYS
FTD_LOW_LOOKBACK = FTD_LOW_LOOKBACK_DAYS
```

2. `detect_last_ftd` 시그니처 변경. 기존:

```python
def detect_last_ftd(
    index_df: pd.DataFrame,
    end_idx: int,
    lookback_days: int = 90,
) -> date | None:
```

변경:

```python
def detect_last_ftd(
    index_df: pd.DataFrame,
    end_idx: int,
    *,
    pct_threshold: float = FTD_PCT_BASE,
    lookback_days: int = 90,
) -> date | None:
```

(`pct_threshold` 가 keyword-only 인자. default = SSOT base — 책 호환. lookback_days 도 keyword-only 로 이전 — 호출단 명시성 향상.)

3. 함수 본체의 `FTD_PCT_THRESHOLD` 참조 → `pct_threshold` 로:

기존 (line 56 부근):
```python
        if pct < FTD_PCT_THRESHOLD:
```

변경:
```python
        if pct < pct_threshold:
```

### Step 3: Update existing callers (단일 호출만 — modes.py 의 호출은 Task 5 에서)

`modes.py` 의 호출 `detect_last_ftd(index_df, end_idx=end_idx, lookback_days=90)` — 현재 그대로 두면 default `pct_threshold=FTD_PCT_BASE` (1.4) 사용 → *기존과 동일 동작*. Task 5 에서 `pct_threshold=thresholds["ftd_pct"]` 명시 전달로 변경.

### Step 4: Run follow_through tests

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/ -v -k "follow_through or ftd" 2>&1 | tail -25`
Expected: 기존 테스트 PASS (default 값으로 동일 동작).

만약 어떤 테스트가 `from ... import FTD_PCT_THRESHOLD` 또는 `follow_through.FTD_PCT_THRESHOLD` 참조하면 에러 — 그 테스트를 갱신 (인자로 전달 또는 import 제거).

### Step 5: Commit

```bash
git add kr_pipeline/market_context/compute/follow_through.py
git commit -m "refactor(p2-1a): follow_through.detect_last_ftd 에 pct_threshold 인자화

호환 별칭 FTD_PCT_THRESHOLD 제거 (외부 import 없음 grep 확인).
함수 시그니처에 pct_threshold (keyword-only, default = FTD_PCT_BASE)
추가. modes.py 의 호출단 (Task 5) 이 시장별 보정 임계 주입 예정.

window/lookback 호환 별칭은 보정 제외 (책 그대로) 이라 유지."
```

---

## Task 4: distribution_day.py `pct_threshold` 인자화

**Files:**
- Modify: `kr_pipeline/market_context/compute/distribution_day.py`

### Step 1: Update distribution_day.py — add pct_threshold arg

Read `kr_pipeline/market_context/compute/distribution_day.py` 전체.

Edit:

1. 상단 import 변경. 기존:

```python
from kr_pipeline.common.thresholds import (
    MARKET_DISTRIBUTION_PCT_THRESHOLD,
    MARKET_DISTRIBUTION_LOOKBACK_DAYS,
)

# 기존 module-level 상수는 SSOT 로 이전. 호환성 별칭 유지.
DISTRIBUTION_DAY_PCT_THRESHOLD = MARKET_DISTRIBUTION_PCT_THRESHOLD
```

변경:

```python
from kr_pipeline.common.thresholds import (
    DISTRIBUTION_PCT_BASE,
    MARKET_DISTRIBUTION_LOOKBACK_DAYS,
)

# P2-1a: DISTRIBUTION_DAY_PCT_THRESHOLD 호환 별칭은 DISTRIBUTION_PCT_BASE 로
# 이전. 시장별 보정 임계는 pct_threshold 인자로 modes.py 가 주입.
DISTRIBUTION_DAY_PCT_THRESHOLD = DISTRIBUTION_PCT_BASE
```

2. `is_distribution_day` 시그니처 변경. 기존:

```python
def is_distribution_day(
    today_close: float,
    today_volume: float,
    yesterday_close: float,
    yesterday_volume: float,
) -> bool:
    """오늘이 분포일인지 판정."""
    if yesterday_close == 0:
        return False
    pct_change = (today_close - yesterday_close) / yesterday_close * 100
    return pct_change <= DISTRIBUTION_DAY_PCT_THRESHOLD and today_volume > yesterday_volume
```

변경:

```python
def is_distribution_day(
    today_close: float,
    today_volume: float,
    yesterday_close: float,
    yesterday_volume: float,
    *,
    pct_threshold: float = DISTRIBUTION_PCT_BASE,
) -> bool:
    """오늘이 분포일인지 판정."""
    if yesterday_close == 0:
        return False
    pct_change = (today_close - yesterday_close) / yesterday_close * 100
    return pct_change <= pct_threshold and today_volume > yesterday_volume
```

3. `count_distribution_days` 시그니처 변경. 기존:

```python
def count_distribution_days(
    index_df: pd.DataFrame,
    end_idx: int,
    lookback: int = MARKET_DISTRIBUTION_LOOKBACK_DAYS,
) -> int:
```

변경:

```python
def count_distribution_days(
    index_df: pd.DataFrame,
    end_idx: int,
    *,
    pct_threshold: float = DISTRIBUTION_PCT_BASE,
    lookback: int = MARKET_DISTRIBUTION_LOOKBACK_DAYS,
) -> int:
```

4. `count_distribution_days` 본체 안의 `is_distribution_day` 호출에 `pct_threshold` 전달:

기존:
```python
        if is_distribution_day(
            today_close=float(today["close"]),
            today_volume=float(today["volume"]),
            yesterday_close=float(yesterday["close"]),
            yesterday_volume=float(yesterday["volume"]),
        ):
            count += 1
```

변경:
```python
        if is_distribution_day(
            today_close=float(today["close"]),
            today_volume=float(today["volume"]),
            yesterday_close=float(yesterday["close"]),
            yesterday_volume=float(yesterday["volume"]),
            pct_threshold=pct_threshold,
        ):
            count += 1
```

### Step 2: Run distribution_day tests

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/ -v -k "distribution_day or market_distribution" 2>&1 | tail -20`
Expected: 기존 테스트 PASS (default 값으로 동일 동작).

만약 테스트가 `DISTRIBUTION_DAY_PCT_THRESHOLD` 호환 별칭 직접 참조하면 그대로 작동 (별칭 유지).

### Step 3: Commit

```bash
git add kr_pipeline/market_context/compute/distribution_day.py
git commit -m "refactor(p2-1a): distribution_day 함수에 pct_threshold 인자화

is_distribution_day + count_distribution_days 시그니처에 pct_threshold
(keyword-only, default = DISTRIBUTION_PCT_BASE) 추가. modes.py 의 호출단
(Task 5) 이 시장별 보정 임계 주입 예정.

DISTRIBUTION_DAY_PCT_THRESHOLD 호환 별칭은 DISTRIBUTION_PCT_BASE 로 이전
(값 동일). lookback (보정 제외) 은 그대로."
```

---

## Task 5: modes.py data flow — σ 측정 → 보정 임계 → 전달

**Files:**
- Modify: `kr_pipeline/market_context/modes.py` (`_process_one_date` 함수)

### Step 1: Add imports

Read `kr_pipeline/market_context/modes.py` 의 import 부분 (line 1-25).

Edit `kr_pipeline/market_context/modes.py`:

1. 기존 import 들 다음에 추가:

```python
from kr_pipeline.common.thresholds import (
    NASDAQ_REFERENCE_SIGMA,
    FTD_PCT_BASE,
    DISTRIBUTION_PCT_BASE,
    KOREAN_SIGMA_RATIO_FLOOR,
    KOREAN_SIGMA_RATIO_CEILING,
)
from kr_pipeline.market_context.compute.volatility import (
    compute_korean_sigma_pct,
    derive_market_thresholds,
    book_default_thresholds,
)
```

### Step 2: Modify _process_one_date — σ measurement + threshold derivation

Read `kr_pipeline/market_context/modes.py` 의 `_process_one_date` 함수 (대략 line 90-140).

`_process_one_date` 안의 `dist_count = count_distribution_days(...)` + `last_ftd_date = detect_last_ftd(...)` 호출 *직전* 에 σ 측정 + derive 블록 삽입:

기존 (해당 부분):
```python
    dist_count = count_distribution_days(index_df, end_idx=end_idx, lookback=25)
    last_ftd_date = detect_last_ftd(index_df, end_idx=end_idx, lookback_days=90)
```

변경:
```python
    # P2-1a: 시장별 σ 측정 → 보정 임계 derive (fallback 안전 후퇴 보장)
    sigma = compute_korean_sigma_pct(conn, index_code, as_of=target_date)
    if sigma is None:
        thresholds = book_default_thresholds(
            ftd_base=FTD_PCT_BASE,
            dist_base=DISTRIBUTION_PCT_BASE,
        )
        log.warning(
            "sigma fallback for %s @ %s — using book defaults (ftd=%.3f, dist=%.3f)",
            index_code, target_date,
            thresholds["ftd_pct"], thresholds["distribution_pct"],
        )
    else:
        thresholds = derive_market_thresholds(
            sigma,
            anchor_sigma=NASDAQ_REFERENCE_SIGMA,
            ftd_base=FTD_PCT_BASE,
            dist_base=DISTRIBUTION_PCT_BASE,
            clamp_floor=KOREAN_SIGMA_RATIO_FLOOR,
            clamp_ceiling=KOREAN_SIGMA_RATIO_CEILING,
        )
        log.info(
            "sigma derived for %s @ %s: sigma=%.3f raw_ratio=%.3f ratio_applied=%.3f clamped=%s ftd_pct=%.3f dist_pct=%.3f",
            index_code, target_date, sigma,
            thresholds["raw_ratio"], thresholds["ratio_applied"], thresholds["clamped"],
            thresholds["ftd_pct"], thresholds["distribution_pct"],
        )

    dist_count = count_distribution_days(
        index_df, end_idx=end_idx,
        pct_threshold=thresholds["distribution_pct"],
        lookback=25,
    )
    last_ftd_date = detect_last_ftd(
        index_df, end_idx=end_idx,
        pct_threshold=thresholds["ftd_pct"],
        lookback_days=90,
    )
```

### Step 3: Update COMPUTATION_NOTES to reflect dynamic thresholds (optional)

기존 (line ~30):
```python
COMPUTATION_NOTES = json.dumps({
    "distribution_day_pct_threshold": -0.2,
    "ftd_pct_threshold": 1.4,
    "ftd_rally_window_min": 3,
    "ftd_rally_window_max": 15,
    "ftd_lookback_days": 90,
    "correction_off_high_pct": -10,
    "downtrend_off_high_pct": -15,
    "dist_count_threshold_for_ftd_invalidation": 6,
}, ensure_ascii=False)
```

→ 정적 dict 라 보정 임계 *못 반영*. 두 옵션:
- A. *그대로* — `COMPUTATION_NOTES` 가 *원래 책 임계* 만 기록 (보정 임계는 log 에 기록). 단순.
- B. *동적* — `_process_one_date` 가 그 호출의 보정 임계도 `computation_notes` 컬럼에 INSERT 함.

**권고: A** (그대로) — `COMPUTATION_NOTES` 가 *시스템 default* 기록 목적. 시장별 보정 임계는 log + DB 의 라인 단위 컬럼 추가 (B 옵션 — 미래 확장).

기존 COMPUTATION_NOTES 의 `"distribution_day_pct_threshold": -0.2` 와 `"ftd_pct_threshold": 1.4` 는 *base* 의미로 명확화. 다음 1줄 추가:

```python
COMPUTATION_NOTES = json.dumps({
    "distribution_day_pct_base": -0.2,
    "ftd_pct_base": 1.4,
    "note": "P2-1a: market thresholds scaled per-index by Korean σ. See log for per-date applied values.",
    "ftd_rally_window_min": 3,
    "ftd_rally_window_max": 15,
    "ftd_lookback_days": 90,
    "correction_off_high_pct": -10,
    "downtrend_off_high_pct": -15,
    "dist_count_threshold_for_ftd_invalidation": 6,
}, ensure_ascii=False)
```

(필드명 `distribution_day_pct_threshold` → `distribution_day_pct_base`, `ftd_pct_threshold` → `ftd_pct_base`, 의미 명확화. `note` 한 줄 추가.)

### Step 4: Run market_context tests

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/ -v -k "market_context" 2>&1 | tail -25`
Expected: 기존 테스트 PASS. 만약 깨지면 fixture 가 `_process_one_date` 호출 시 conn 미공급 — fixture 갱신 필요 (compute_korean_sigma_pct 가 conn 필요).

기존 단위 테스트가 sigma 측정 mock 안 되어 있으면 `sigma is None` → `book_default_thresholds` (pre-P2-1a behavior) 자연 fallback → 결과 동일.

### Step 5: Commit

```bash
git add kr_pipeline/market_context/modes.py
git commit -m "feat(p2-1a): modes._process_one_date 에 σ 측정 + 보정 임계 data flow

시장별 (KOSPI 1001 / KOSDAQ 2001) σ 측정 → derive_market_thresholds 또는
book_default_thresholds 호출 → detect_last_ftd / count_distribution_days
에 pct_threshold 인자 주입. sigma 측정 결과·ratio·clamp 여부 모두 log INFO,
fallback 은 WARN.

COMPUTATION_NOTES 의 _threshold 키를 _base 로 변경 + P2-1a note 추가
(보정 임계는 호출별 log 에 기록)."
```

---

## Task 6: 통합 테스트 (회귀 + 경계)

**Files:**
- Create or Modify: `tests/test_market_context_status.py`

이 task 는 *end-to-end* 검증 — 시장별 보정 임계가 status.py / market_context 흐름에 올바로 적용되는지 + fallback 회귀 + P0-2 종목 distribution 과 경계.

### Step 1: Check existing test file

Run: `ls tests/test_market_context*.py 2>&1`

만약 `tests/test_market_context_status.py` 또는 `tests/test_market_context_modes.py` 가 있으면 그 파일 확장. 없으면 신규.

### Step 2: Add integration tests

만약 신규 파일이면 새로 만들고, 기존 파일이면 다음 테스트들 추가:

```python
"""market_context flow 통합 테스트 — σ 측정 → 보정 → status."""
from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest


def test_fallback_path_equals_pre_p2_1a_behavior():
    """fallback (σ=None) 경로 결과 == 보정 비활성 시 pre-P2-1a 동작.

    회귀 보장 — book_default_thresholds 의 ftd_pct=1.4, dist_pct=-0.2 가
    follow_through / distribution_day 의 default 와 일치 → 결과 같음.
    """
    from kr_pipeline.market_context.compute.volatility import book_default_thresholds
    from kr_pipeline.common.thresholds import FTD_PCT_BASE, DISTRIBUTION_PCT_BASE

    thresholds = book_default_thresholds(
        ftd_base=FTD_PCT_BASE, dist_base=DISTRIBUTION_PCT_BASE,
    )
    # ftd_pct/distribution_pct 가 follow_through/distribution_day 의 default 와 같음
    assert thresholds["ftd_pct"] == FTD_PCT_BASE  # = 1.4
    assert thresholds["distribution_pct"] == DISTRIBUTION_PCT_BASE  # = -0.2


def test_p2_1a_boundary_does_not_touch_stock_distribution():
    """P2-1a 시장 보정이 종목 레벨 distribution (P0-2 / volume.py) 에 안 닿음.

    경계 박스 (spec Section 9) — 종목 distribution 은 prompt §6 가 LLM 에
    직접 정의 안내. P2-1a 의 pct_threshold 변경은 volume.py 와 무관.
    """
    # volume.py 의 distribution_day default (STOCK_DISTRIBUTION_VOL_MULT) 가
    # 변경 안 됨을 확인 — P0-2 의 1.0 유지
    from kr_pipeline.common.thresholds import STOCK_DISTRIBUTION_VOL_MULT
    assert STOCK_DISTRIBUTION_VOL_MULT == 1.0  # P0-2 후 정정 값

    # 또한 volume.py 의 distribution_day 함수 시그니처가 P2-1a 변경에 영향
    # 안 받음을 import 가능성으로 sanity check
    from kr_pipeline.indicators.compute.volume import distribution_day
    assert callable(distribution_day)


def test_derive_thresholds_with_korean_kospi_sigma():
    """spec §1 의 관찰값 (KOSPI σ ≈ 2.34) 으로 derive 검증."""
    from kr_pipeline.market_context.compute.volatility import derive_market_thresholds
    from kr_pipeline.common.thresholds import (
        NASDAQ_REFERENCE_SIGMA, FTD_PCT_BASE, DISTRIBUTION_PCT_BASE,
        KOREAN_SIGMA_RATIO_FLOOR, KOREAN_SIGMA_RATIO_CEILING,
    )

    thresholds = derive_market_thresholds(
        sigma_pct=2.34,
        anchor_sigma=NASDAQ_REFERENCE_SIGMA,
        ftd_base=FTD_PCT_BASE,
        dist_base=DISTRIBUTION_PCT_BASE,
        clamp_floor=KOREAN_SIGMA_RATIO_FLOOR,
        clamp_ceiling=KOREAN_SIGMA_RATIO_CEILING,
    )
    # raw_ratio = 2.34, clamp [1.0, 2.5] → 2.34 (clamp 안 걸림)
    assert thresholds["raw_ratio"] == 2.34
    assert thresholds["ratio_applied"] == 2.34
    assert thresholds["clamped"] is False
    # FTD: 1.4 × 2.34 = 3.276
    assert thresholds["ftd_pct"] == pytest.approx(1.4 * 2.34)
    # distribution: -0.2 × 2.34 = -0.468
    assert thresholds["distribution_pct"] == pytest.approx(-0.2 * 2.34)


def test_panic_sigma_triggers_ceiling_clamp():
    """패닉기 σ 5-6% 시 ceiling 2.5 clamp 작동 — FTD 임계 폭주 차단."""
    from kr_pipeline.market_context.compute.volatility import derive_market_thresholds
    from kr_pipeline.common.thresholds import (
        NASDAQ_REFERENCE_SIGMA, FTD_PCT_BASE, DISTRIBUTION_PCT_BASE,
        KOREAN_SIGMA_RATIO_FLOOR, KOREAN_SIGMA_RATIO_CEILING,
    )

    thresholds = derive_market_thresholds(
        sigma_pct=5.5,
        anchor_sigma=NASDAQ_REFERENCE_SIGMA,
        ftd_base=FTD_PCT_BASE,
        dist_base=DISTRIBUTION_PCT_BASE,
        clamp_floor=KOREAN_SIGMA_RATIO_FLOOR,
        clamp_ceiling=KOREAN_SIGMA_RATIO_CEILING,
    )
    assert thresholds["raw_ratio"] == 5.5
    assert thresholds["ratio_applied"] == 2.5  # ceiling
    assert thresholds["clamped"] is True
    # FTD 임계가 1.4 × 2.5 = 3.5% 로 제한 (7.7% 가 아님)
    assert thresholds["ftd_pct"] == pytest.approx(3.5)
```

### Step 3: Run integration tests

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_market_context_status.py -v 2>&1 | tail -25`
Expected: 모든 새 테스트 PASS.

### Step 4: Full integration check

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/ 2>&1 | tail -5`
Expected: baseline (343 passed / 25 사전 isolation fail) + 새 테스트 PASS 카운트만큼 증가. 새로 깨진 테스트 0.

### Step 5: Regenerate thresholds.generated.ts (sanity — Task 1 후 다시)

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run python scripts/export_thresholds.py && cd web && npx tsc --noEmit && echo CLEAN`
Expected: 신규 7 상수 export 확인 + tsc CLEAN.

### Step 6: Commit

```bash
git add tests/test_market_context_status.py web/src/data/thresholds.generated.ts
git commit -m "test(p2-1a): 통합 테스트 — 회귀 + 경계 + spec §1 관찰값

회귀: book_default_thresholds 의 ftd/dist == pre-P2-1a 책 임계 일치.
경계: P0-2 종목 distribution (volume.py / STOCK_DISTRIBUTION_VOL_MULT=1.0)
이 P2-1a 변경에 안 닿음.
관찰값: spec §1 의 KOSPI σ=2.34 → derived ftd=3.276 / dist=-0.468 (clamp
미적용).
패닉기: σ=5.5 → ceiling clamp 2.5 → ftd=3.5 (7.7 봉쇄 방지).

generated.ts 재생성 + tsc CLEAN."
```

---

## Self-Review

**1. Spec coverage**: spec 의 모든 결정 항목 매핑.
- Section 3 SSOT 상수 7개 → Task 1 ✅
- Section 4 SSOT 정리 (FTD dict 제거, MARKET_DISTRIBUTION 별칭) → Task 1 ✅
- Section 5 순수 함수 3개 → Task 2 ✅
- Section 6 Data flow → Task 5 ✅
- Section 7 Fallback 계약 → Task 5 + Task 6 (회귀 테스트) ✅
- Section 8 σ 단순수익률 + look-ahead 방지 → Task 2 (docstring + SQL) ✅
- Section 9 경계 → Task 6 (테스트) ✅
- Section 10 Testing (단위 + 통합 + 회귀) → Task 2 + Task 6 ✅
- Section 11 변경 대상 파일 list → Task 1-6 모두 ✅
- Section 12 비범위 (B 옵션 길 안 막음) → 함수가 순수 함수라 자연 충족 ✅

**2. Placeholder scan**: 모든 step 에 정확 코드 + 명령. ✅

**3. Type consistency**:
- `pct_threshold` 인자명이 follow_through / distribution_day 모두 동일 ✅
- SSOT 상수명 (NASDAQ_REFERENCE_SIGMA / FTD_PCT_BASE 등) 이 Task 1 정의와 Task 2, 5 import 일치 ✅
- 반환 dict 키 (`ftd_pct, distribution_pct, raw_ratio, ratio_applied, clamped, source`) 가 Task 2 함수 정의와 Task 5 호출, Task 6 테스트 일치 ✅
- `derive` / `book_default` 동일 스키마 — Task 2 의 `test_book_defaults_schema_matches_derive` 가 명시 검증 ✅

**4. 제외 / 한계**:
- Cup depth 33% 보정 — 별도 spec
- P2-3 candidate VCP footprint — 별도 사이클
- DB 캐시 (B 옵션) — 순수 함수로 길 안 막음, 미래 확장

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-25-p2-1a-korean-market-volatility.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
