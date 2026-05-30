# Phase 2 (i) prompt 안정화 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM 의 비결정적 cup-shape 라벨을 *측정값의 결정론 함수* 로 안정화하고, 후처리 gate 를 monotone-combine backstop 으로 강등해, 동일 입력 재현성(shape feature 9~10/10, verdict 재현, faulty→watch+handle_quality)을 확보한다.

**Architecture:** (1) 책 임계를 thresholds.py SSOT 로 이관(패턴×시장 표, book/heuristic 라벨) + 양방향 drift 테스트. (2) analyze prompt 에 measurement 정식 필드 + cup-scoped 결정 트리 Gate0~3 + 허용밴드 도입(주 메커니즘). (3) verify prompt 6차원(+layer-분리 guardrail). (4) gates.py 를 monotone-combine 으로 리팩토링(detector 제거, backstop 강등). (5) build-first 재측정 게이트(가지별 음성 패널 N=10).

**Tech Stack:** Python (psycopg, pytest, pytest-mock), PostgreSQL (idempotent schema.sql), Claude CLI subprocess, prompts/*.md, React SSOT export (TypeScript).

**Spec:** `docs/superpowers/specs/2026-05-31-phase2-i-prompt-stabilization-design.md`

**Pre-req:** 테스트는 `TEST_DATABASE_URL` 필요 (`uv run pytest tests/`). 사전 isolation fail ~25개는 baseline — 본 작업이 그 수를 늘리지 않는지 확인(CLAUDE.md).

---

## File Structure

| 파일 | 책임 | 작업 |
|---|---|---|
| `docs/superpowers/verification/2026-05-31-phase2-i-threshold-dependency-map.md` | CLAUDE.md 의무 2축 의존성 맵 | Create (Task 1) |
| `kr_pipeline/common/thresholds.py` | 책 임계 SSOT — cup depth/선행상승/핸들/failed_breakout/밴드 신규 | Modify (Task 2) |
| `kr_pipeline/llm_runner/compute/handle_quality.py` | 로컬 상수 → thresholds import (동작 0 변화, 장중 정의 주석) | Modify (Task 3) |
| `kr_pipeline/llm_runner/compute/failed_breakout.py` | 로컬 상수 → thresholds import | Modify (Task 3) |
| `tests/test_common_thresholds.py` | 신규 상수 sanity | Modify (Task 2) |
| `scripts/export_thresholds.py` | 중첩 dict 직렬화 검증 (이미 재귀 지원 — 테스트만) | (Task 4, 코드 무변경 가능) |
| `tests/test_prompt_threshold_drift.py` | 양방향 drift 테스트 (prompt↔SSOT + orphan) | Create (Task 5) |
| `kr_pipeline/db/schema.sql` | `weekly_classification.measurements JSONB` 추가 | Modify (Task 6) |
| `prompts/analyze_chart_v3.md` | 구조화 threshold 블록 + measurement 필드 + 트리 Gate0~3 + 밴드 + 14th flag | Modify (Task 7) |
| `kr_pipeline/llm_runner/store.py` | `measurements` 컬럼 저장 | Modify (Task 8) |
| `tests/test_llm_runner_store.py` | measurements 저장 검증 | Modify (Task 8) |
| `prompts/verify_analysis_v1.md` | 6차원 + layer-분리 + 14th flag | Modify (Task 9) |
| `kr_pipeline/llm_runner/gates.py` | monotone-combine 리팩토링 (detector 제거) | Modify (Task 10) |
| `tests/test_gates_phase1.py` | monotone 동작 (no-promotion, conf min) | Modify (Task 10) |
| `scripts/remeasure_phase2i.py` | build-first 재측정 하니스 (N회 동일입력, feature 분산/verdict 재현 진단) | Create (Task 11) |

---

## Phase A — SSOT 이관 (Task 1~5)

### Task 1: 2축 의존성 맵 작성 (CLAUDE.md 의무 — thresholds.py 변경 *선행*)

**Files:**
- Create: `docs/superpowers/verification/2026-05-31-phase2-i-threshold-dependency-map.md`

CLAUDE.md: thresholds.py 를 건드리므로 `threshold-change-checklist.md` 의 2축 맵이 코드 변경 *전* 필수. 이 Task 는 코드가 아니라 문서 — 통과 조건(checklist §c 5게이트)을 만족해야 다음 Task 진행.

- [ ] **Step 1: 의존성 맵 문서 작성**

다음 내용으로 파일 생성:

```markdown
# Phase 2 (i) Threshold 의존성 맵 (2축)

> CLAUDE.md 의무. 신규/이관 상수: CUP_DEPTH_MAX_NORMAL_PCT, CUP_DEPTH_MAX_BEAR_RECOVERY_PCT,
> CUP_PRIOR_UPTREND_MIN_PCT, MIN_BASE_WEEKS, HANDLE_LEGIT_MIN_DAYS, HANDLE_* , FAILED_BREAKOUT_* , MEASUREMENT_TOLERANCE_PCT.

## 의존성 (3 depth + boundary)

- **Depth1 파생신호**: cup depth 임계 → analyze 트리 Gate1 의 cup/none 분기. 선행상승 → Gate0.
- **Depth2 소비룰**: analyze_chart_v3.md §2 트리(Gate0~3) · handle_quality.py(HANDLE_*) · failed_breakout.py(FAILED_BREAKOUT_*) · gates.py(monotone-combine).
- **Depth3 고정상수**: handle_quality 내 ratio_a/ratio_b 비교, MIN_BASE_DAYS/MIN_HANDLE_DAYS.
- **Boundary(1줄)**: → analyze_chart_v3.md classification(entry/watch/ignore) → weekly_classification.

## 2축 판정표

| 상수 | 축1: 비율조정 가능? | 축2: 영향? | 책 정합 | Action → Follow-up |
|---|---|---|---|---|
| CUP_DEPTH_MAX_NORMAL_PCT 33% | 불가 (책 고정 앵커, O'Neil) | Present (cup/none 분기 직접) | PRESERVES | 변경 금지(book-anchor); 시장축과 동시 점검 |
| CUP_DEPTH_MAX_BEAR_RECOVERY_PCT 50% | 불가 (책 예외 앵커) | Present (F3 약세회복 분기) | PRESERVES | F3 트리거(market_context downtrend→uptrend 60세션) 동시 점검 — **핵심 셀** |
| CUP_PRIOR_UPTREND_MIN_PCT 30% | 불가 (책 앵커) | Present (Gate0 none 분기) | PRESERVES | cup-scoped — flat 20% 와 분리(다패턴 트리 미소비) |
| HANDLE_LEGIT_MIN_DAYS 5 | 불가 (책 ~1주 floor) | Present (Gate3 길이 → not_formed 분기) | PRESERVES | HANDLE_MIN_DAYS(3, heuristic 윈도우)와 분리 — 분류 게이트 |
| MEASUREMENT_TOLERANCE_PCT 5% | 가능 (heuristic) | Present (경계 straddle 흡수) | MethodDiff(시스템 정책) | calibration-target — 재측정(Task 11)이 보정 |
| HANDLE_DEEP_RATIO 0.33 | 가능 (heuristic) | Present (handle_quality 발화) | MethodDiff (책 8~12% 절대치와 reconcile 미완 — trace) | 변경 시 재측정 |
| HANDLE_VOLUME_NOT_CONTRACTING_RATIO 0.80 | 가능 | Present | MethodDiff | 변경 시 재측정 |
| FAILED_BREAKOUT_K_DAYS 5 / CONSECUTIVE_BELOW 2 | 가능 (시간상수 — 비율조정 부적절) | Present (2-F 기록) | MethodDiff | B-수치 (사례 누적 후 재조정) |

## 시장축 교차 점검 (depth × 시장 — 핵심)
- CUP_DEPTH 변경 시 (정상장 33 / 약세회복 50) 두 셀 + F3 market_context 전환 감지 로직 동시 점검.
- wide_and_loose(2-B) · status.py 와의 상호작용: (i) cup-scoped 라 직접 충돌 없음 — 2-B 진입 전 재확인.

## 통과 자기점검 (checklist §c)
- [x] 의존성 맵 존재 · [x] 모든 depth3 상수 행 · [x] 축1/축2 공란 없음 · [x] Present 행에 action 명시 · [x] boundary 1줄.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/verification/2026-05-31-phase2-i-threshold-dependency-map.md
git commit -m "docs(phase2-i): threshold 2축 의존성 맵 (CLAUDE.md 의무, thresholds.py 변경 선행)"
```

---

### Task 2: thresholds.py 신규 상수 + sanity 테스트

**Files:**
- Modify: `kr_pipeline/common/thresholds.py` (말미에 신규 섹션 추가)
- Test: `tests/test_common_thresholds.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_common_thresholds.py` 말미에 추가:

```python
def test_phase2i_cup_shape_constants():
    # book-anchor (변경 금지)
    assert thresholds.CUP_DEPTH_MAX_NORMAL_PCT == 33.0
    assert thresholds.CUP_DEPTH_MAX_BEAR_RECOVERY_PCT == 50.0
    assert thresholds.CUP_PRIOR_UPTREND_MIN_PCT == 30.0
    assert thresholds.HANDLE_DEPTH_BULL_MIN_PCT == 8.0
    assert thresholds.HANDLE_DEPTH_BULL_MAX_PCT == 12.0
    assert thresholds.HANDLE_LEGIT_MIN_DAYS == 5          # book-anchor 길이 게이트 (≠ HANDLE_MIN_DAYS heuristic)
    assert thresholds.MIN_BASE_WEEKS["cup_with_handle"] == 7


def test_phase2i_handle_heuristic_constants():
    # heuristic (튜닝 가능)
    assert thresholds.HANDLE_DEEP_RATIO == 0.33
    assert thresholds.HANDLE_VOLUME_NOT_CONTRACTING_RATIO == 0.80
    assert thresholds.HANDLE_MIN_DAYS == 3
    assert thresholds.BASE_MIN_DAYS == 5
    assert thresholds.HANDLE_POSITION_LOW_RATIO == 0.33


def test_phase2i_failed_breakout_and_band():
    assert thresholds.FAILED_BREAKOUT_K_DAYS == 5
    assert thresholds.FAILED_BREAKOUT_CONSECUTIVE_BELOW == 2
    assert thresholds.MEASUREMENT_TOLERANCE_PCT == 5.0
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_common_thresholds.py::test_phase2i_cup_shape_constants -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'CUP_DEPTH_MAX_NORMAL_PCT'`

- [ ] **Step 3: thresholds.py 에 신규 섹션 추가**

`kr_pipeline/common/thresholds.py` 말미(마지막 상수 뒤)에 추가:

```python
# ===== Phase 2 (i): cup-shape 결정론화 (analyze_chart_v3.md §2 트리 / handle_quality / failed_breakout) =====
# 분류: book-anchor = 책 고정 앵커(변경 금지) / heuristic = 튜닝 가능.
# 단일 스칼라 금지 — depth 는 패턴 × 시장 2축. (i) 트리는 cup 행만 소비, 나머지는 향후 다패턴 트리용.

CUP_DEPTH_MAX_NORMAL_PCT: Final[float] = 33.0
"""[book-anchor] cup 정상장 최대 depth %. O'Neil HMMS Ch.2."""

CUP_DEPTH_MAX_BEAR_RECOVERY_PCT: Final[float] = 50.0
"""[book-anchor] cup 약세장 회복(downtrend→uptrend 60세션 내) 최대 depth %.
O'Neil 예외. F3(cup depth 50% 예외 연속화)가 여기 묶임 — market_context 전환 트리거와 동시 점검."""

FLAT_BASE_DEPTH_MAX_PCT: Final[float] = 15.0
"""[book-anchor] flat base 최대 depth %. Minervini TLSMW Ch.10. (향후 다패턴 트리용 — (i) 미소비.)"""

CUP_PRIOR_UPTREND_MIN_PCT: Final[float] = 30.0
"""[book-anchor] cup 진입 전 최소 선행상승 %. O'Neil HMMS Ch.2 — 모든 cup 패턴 전제."""

FLAT_BASE_PRIOR_UPTREND_MIN_PCT: Final[float] = 20.0
"""[book-anchor] flat base 최소 선행상승 %. Minervini. (향후 다패턴 트리용 — (i) 미소비.)"""

MIN_BASE_WEEKS: Final[dict] = {
    "cup_with_handle": 7,
    "flat_base": 5,
    "double_bottom": 7,
    "vcp": 5,
}
"""[book-anchor] 패턴별 최소 base 주수 (narrow_base 미만 기준). 현 analyze_chart_v3.md §4 표와 동일."""

HANDLE_DEPTH_BULL_MIN_PCT: Final[float] = 8.0
HANDLE_DEPTH_BULL_MAX_PCT: Final[float] = 12.0
"""[book-anchor] 정상장 핸들 깊이 밴드(피크 대비 %). O'Neil HMMS Ch.2 p.116 '8% to 12%'."""

HANDLE_LEGIT_MIN_DAYS: Final[int] = 5
"""[book-anchor] 적법 핸들 최소 길이 (≈1주 = 5거래일). O'Neil HMMS Ch.2 ('one or two weeks'
floor) / Minervini (handle ≥1주, 현 analyze §4 표). **HANDLE_MIN_DAYS(=3, heuristic 계산
윈도우)와 다름** — 이건 분류 게이트(길이). 미달 → handle_status=not_formed(형성중, faulty 아님)."""

# --- handle_quality.py 이관 (heuristic) ---
HANDLE_DEEP_RATIO: Final[float] = 0.33
"""[heuristic] 컵깊이 대비 핸들깊이 비 발화 임계. **trace 필요**: 책의 8~12% 절대치
(HANDLE_DEPTH_BULL_*)와 reconcile 미완 — 현재는 휴리스틱."""

HANDLE_VOLUME_NOT_CONTRACTING_RATIO: Final[float] = 0.80
"""[heuristic] handle/base 평균거래량 비 발화 임계 (수축 안 됨)."""

HANDLE_MIN_DAYS: Final[int] = 3
BASE_MIN_DAYS: Final[int] = 5
"""[heuristic] handle_quality 계산 최소 윈도우."""

HANDLE_POSITION_LOW_RATIO: Final[float] = 0.33
"""[heuristic] 핸들 하단 위치 가중(단독 트리거 아님)."""

# --- failed_breakout.py 이관 (heuristic) ---
FAILED_BREAKOUT_K_DAYS: Final[int] = 5
FAILED_BREAKOUT_CONSECUTIVE_BELOW: Final[int] = 2
"""[heuristic] 2-F 돌파 실패 판정. 시간상수 — 비율조정 부적절, B-수치(사례 누적 후 재조정)."""

# --- 허용밴드 (heuristic · calibration-target) ---
MEASUREMENT_TOLERANCE_PCT: Final[float] = 5.0
"""[heuristic · calibration-target] LLM 측정값 경계 허용밴드 %. **고정상수 아님** —
shape 가 LLM 소유라 밴드폭이 안정성의 load-bearing 변수. 재측정(Task 11)의 'depth read
회차간 분산'으로 보정. 5% 는 잠정 시작값(사용자 ±5% 노이즈 정책)."""
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_common_thresholds.py -v`
Expected: PASS (신규 3개 + 기존 전부)

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/common/thresholds.py tests/test_common_thresholds.py
git commit -m "feat(phase2-i): cup-shape 임계 SSOT 이관 — 패턴×시장 depth/선행상승/핸들/밴드 (book/heuristic 라벨)"
```

---

### Task 3: 소비처를 thresholds import 로 전환 (동작 0 변화)

**Files:**
- Modify: `kr_pipeline/llm_runner/compute/handle_quality.py:17-22`
- Modify: `kr_pipeline/llm_runner/compute/failed_breakout.py:15-16`
- Test: `tests/test_gates_phase1.py` (기존 통과 유지로 회귀 검증)

- [ ] **Step 1: handle_quality.py 로컬 상수 → import**

`handle_quality.py` 의 로컬 상수 블록(line 17~22)을 삭제하고 import 로 대체. import 섹션에 추가:

```python
from kr_pipeline.common import thresholds
```

상수 사용처를 치환:
- `DEEP_HANDLE_RATIO` → `thresholds.HANDLE_DEEP_RATIO`
- `VOLUME_NOT_CONTRACTING_RATIO` → `thresholds.HANDLE_VOLUME_NOT_CONTRACTING_RATIO`
- `MIN_HANDLE_DAYS` → `thresholds.HANDLE_MIN_DAYS`
- `MIN_BASE_DAYS` → `thresholds.BASE_MIN_DAYS`
- `WEIGHT_POSITION_LOW_RATIO` → `thresholds.HANDLE_POSITION_LOW_RATIO`

그리고 line 100 `(A) deep handle` 주석 위에 장중 정의 lock 주석 추가:

```python
    # (A) deep handle — depth 는 장중 high/low 기준 (spec §4: O'Neil absolute peak→low, 종가 아님).
    #     rows[][1]=high, rows[][2]=low 사용 — 책-충실. 종가 전환 금지.
```

- [ ] **Step 2: failed_breakout.py 로컬 상수 → import**

`failed_breakout.py` line 15~16 (`K_DAYS = 5` / `CONSECUTIVE_BELOW = 2`) 삭제, import 추가:

```python
from kr_pipeline.common import thresholds
```

사용처(line 69, 85) 치환:
- `K_DAYS` → `thresholds.FAILED_BREAKOUT_K_DAYS`
- `CONSECUTIVE_BELOW` → `thresholds.FAILED_BREAKOUT_CONSECUTIVE_BELOW`

(반환 dict 의 `"K_days": K_DAYS` → `"K_days": thresholds.FAILED_BREAKOUT_K_DAYS`.)

- [ ] **Step 3: 회귀 확인 (동작 0 변화)**

Run: `uv run pytest tests/test_gates_phase1.py -v`
Expected: PASS — 기존 모든 테스트 통과 (값 동일이라 동작 불변).

- [ ] **Step 4: Commit**

```bash
git add kr_pipeline/llm_runner/compute/handle_quality.py kr_pipeline/llm_runner/compute/failed_breakout.py
git commit -m "refactor(phase2-i): handle_quality/failed_breakout 로컬 상수 → thresholds SSOT (동작 0 변화)"
```

---

### Task 4: SSOT export 재생성 + 중첩 dict 검증

**Files:**
- Modify: `web/src/data/thresholds.generated.ts` (생성 결과)
- Test: `tests/test_common_thresholds.py`

`export_thresholds.py` 의 `_to_ts_value`/`_ts_type` 는 이미 재귀 처리 → `MIN_BASE_WEEKS` 같은 균일 `{str: int}` dict 은 `Record<string, number>` 로 정상 생성됨. 코드 변경 불필요 — 재생성 + 검증만.

- [ ] **Step 1: export 실행**

Run: `uv run python scripts/export_thresholds.py`
Expected: `Wrote .../thresholds.generated.ts (N constants)` — N 이 신규 상수만큼 증가.

- [ ] **Step 2: 생성 결과에 신규 상수 포함 확인**

Run: `grep -E "CUP_DEPTH_MAX_NORMAL_PCT|MIN_BASE_WEEKS|MEASUREMENT_TOLERANCE_PCT" web/src/data/thresholds.generated.ts`
Expected: 3 줄 출력. `MIN_BASE_WEEKS` 는 `Record<string, number>` 타입에 `{ "cup_with_handle": 7, ... }` 값.

- [ ] **Step 3: 회귀 — export 가 깨지지 않는지 idempotent 확인**

Run: `uv run python scripts/export_thresholds.py && git diff --stat web/src/data/thresholds.generated.ts`
Expected: 두 번째 실행은 diff 없음 (idempotent).

- [ ] **Step 4: Commit**

```bash
git add web/src/data/thresholds.generated.ts
git commit -m "chore(phase2-i): SSOT export 재생성 — cup-shape 임계 반영"
```

---

### Task 5: 양방향 prompt drift 테스트

**Files:**
- Create: `tests/test_prompt_threshold_drift.py`

전제: analyze prompt 에 구조화 threshold 블록이 있어야 파싱 가능 (Task 7 에서 블록 삽입). 본 Task 는 테스트를 *먼저* 작성(실패) → Task 7 에서 블록을 넣어 통과시키는 TDD 순서. 테스트는 prompt 의 `<!-- SSOT-THRESHOLDS -->` ~ `<!-- /SSOT-THRESHOLDS -->` 마커 사이 `- NAME = VALUE` 줄을 파싱.

- [ ] **Step 1: drift 테스트 작성**

```python
# tests/test_prompt_threshold_drift.py
"""analyze_chart_v3.md 의 구조화 threshold 블록 ↔ thresholds.py SSOT 양방향 검증.
- 정합: prompt 의 모든 NAME=VALUE 가 thresholds.py 값과 일치.
- orphan: PROMPT_SYNCED 의 모든 상수가 prompt 블록에 실제 등장 (코드만 바뀌고 prompt 미반영 검출).
"""
from __future__ import annotations

import re
from pathlib import Path

from kr_pipeline.common import thresholds

PROMPT = Path(__file__).parent.parent / "prompts" / "analyze_chart_v3.md"

# prompt 에 반드시 동기화돼야 하는 SSOT 상수 (orphan 검출 기준).
PROMPT_SYNCED = [
    "CUP_DEPTH_MAX_NORMAL_PCT",
    "CUP_DEPTH_MAX_BEAR_RECOVERY_PCT",
    "CUP_PRIOR_UPTREND_MIN_PCT",
    "HANDLE_DEPTH_BULL_MIN_PCT",
    "HANDLE_DEPTH_BULL_MAX_PCT",
    "HANDLE_LEGIT_MIN_DAYS",
    "MEASUREMENT_TOLERANCE_PCT",
]

BLOCK_RE = re.compile(r"<!-- SSOT-THRESHOLDS -->(.*?)<!-- /SSOT-THRESHOLDS -->", re.S)
LINE_RE = re.compile(r"-\s*([A-Z_]+)\s*=\s*([0-9.]+)")


def _parse_block() -> dict[str, float]:
    text = PROMPT.read_text(encoding="utf-8")
    m = BLOCK_RE.search(text)
    assert m, "analyze_chart_v3.md 에 <!-- SSOT-THRESHOLDS --> 블록이 없음"
    return {name: float(val) for name, val in LINE_RE.findall(m.group(1))}


def test_prompt_values_match_ssot():
    parsed = _parse_block()
    for name, val in parsed.items():
        assert hasattr(thresholds, name), f"prompt 에 SSOT 미존재 상수: {name}"
        assert float(getattr(thresholds, name)) == val, (
            f"drift: prompt {name}={val} ≠ SSOT {getattr(thresholds, name)}"
        )


def test_no_orphan_synced_constants():
    parsed = _parse_block()
    for name in PROMPT_SYNCED:
        assert name in parsed, f"orphan: SSOT {name} 이 prompt 블록에 미반영"
```

- [ ] **Step 2: 실패 확인 (블록 미존재)**

Run: `uv run pytest tests/test_prompt_threshold_drift.py -v`
Expected: FAIL — `analyze_chart_v3.md 에 <!-- SSOT-THRESHOLDS --> 블록이 없음` (Task 7 에서 해소).

- [ ] **Step 3: Commit (실패 테스트 — Task 7 이 통과시킴)**

```bash
git add tests/test_prompt_threshold_drift.py
git commit -m "test(phase2-i): prompt↔SSOT 양방향 drift 테스트 (블록은 Task 7 에서 추가)"
```

---

## Phase B — DB (Task 6)

### Task 6: weekly_classification.measurements JSONB 컬럼

**Files:**
- Modify: `kr_pipeline/db/schema.sql` (weekly_classification ALTER 블록)
- Test: `tests/test_llm_runner_store.py`

근거: measurement 를 정식 필드로(spec §2.1) — 재측정이 "feature 가 회차 간 안정한가"를 기계 측정하려면 산문 아닌 구조화 저장. 다중 typed 컬럼 대신 단일 JSONB (triggered_rules/risk_flags 선례).

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_llm_runner_store.py` 말미에 추가:

```python
def test_measurements_column_exists_and_stores(db):
    """measurements JSONB 컬럼에 LLM 측정 블록 저장."""
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_classification

    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='MEAS'")
    insert_classification(
        db, symbol="MEAS", classified_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
        market="KOSPI",
        result={
            "classification": "watch", "pattern": "cup_with_handle", "confidence": 0.6,
            "reasoning": "x", "risk_flags": [], "pivot_price": None, "pivot_basis": None,
            "base_high": None, "base_low": None, "base_depth_pct": None, "base_start_date": None,
            "measurements": {"cup_depth_pct": 30.0, "prior_uptrend_pct": 40.0, "cup_shape": "U"},
        },
        source="weekend", llm_meta={},
    )
    with db.cursor() as cur:
        cur.execute("SELECT measurements FROM weekly_classification WHERE symbol='MEAS'")
        row = cur.fetchone()
    assert row[0]["cup_shape"] == "U"
    assert row[0]["cup_depth_pct"] == 30.0
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_llm_runner_store.py::test_measurements_column_exists_and_stores -v`
Expected: FAIL — `column "measurements" does not exist` (또는 store 가 미저장).

- [ ] **Step 3: schema.sql ALTER 추가**

`kr_pipeline/db/schema.sql` 의 `ALTER TABLE weekly_classification ADD COLUMN IF NOT EXISTS triggered_rules JSONB;` 바로 아래에 추가:

```sql
-- Phase 2 (i): LLM 측정-우선 scaffolding 의 measurement 블록 (shape feature 기계 집계용)
ALTER TABLE weekly_classification
  ADD COLUMN IF NOT EXISTS measurements JSONB;
```

테스트 DB 에 반영:

Run: `psql "$TEST_DATABASE_URL" -f kr_pipeline/db/schema.sql`
Expected: 에러 없음 (idempotent).

- [ ] **Step 4: store.py 에 measurements 저장 추가 (Task 8 과 분리 — 여기선 컬럼만)**

Task 8 에서 store INSERT 에 컬럼 추가. 본 Step 은 schema 만. 테스트는 Task 8 후 통과.

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/db/schema.sql
git commit -m "feat(phase2-i): weekly_classification.measurements JSONB 컬럼"
```

---

### Task 8: store.py measurements 저장

**Files:**
- Modify: `kr_pipeline/llm_runner/store.py:45-85`
- Test: `tests/test_llm_runner_store.py` (Task 6 테스트가 통과해야)

> (Task 7 prompt 보다 store 가 먼저 — 컬럼 채움. Task 번호는 의존 순서상 6→8→7 로 읽어도 무방.)

- [ ] **Step 1: INSERT 에 measurements 추가**

`store.py` 의 `insert_classification` INSERT 문 — 컬럼 리스트 `triggered_rules)` 를 `triggered_rules, measurements)` 로, VALUES 의 마지막 `%s)` 앞에 `%s` 하나 추가, 파라미터 튜플 끝(`json.dumps(triggered_rules) ...` 뒤)에 추가:

```python
                json.dumps(triggered_rules) if triggered_rules is not None else None,
                json.dumps(result.get("measurements")) if result.get("measurements") is not None else None,
```

컬럼/VALUES 정합(컬럼 21개 → 22개) 맞춰 편집.

- [ ] **Step 2: 통과 확인**

Run: `uv run pytest tests/test_llm_runner_store.py -v`
Expected: PASS (measurements 저장 + 기존 테스트).

- [ ] **Step 3: Commit**

```bash
git add kr_pipeline/llm_runner/store.py
git commit -m "feat(phase2-i): store insert_classification measurements 저장"
```

---

## Phase C — analyze prompt (Task 7)

### Task 7: analyze_chart_v3.md — 구조화 threshold 블록 + measurement 필드 + cup-scoped 트리 + 밴드 + 14th flag

**Files:**
- Modify: `prompts/analyze_chart_v3.md`
- Test: `tests/test_prompt_threshold_drift.py` (Task 5 — 통과로 전환)

prompt 는 .md 라 단위 TDD 불가 — drift 테스트(Task 5) 통과 + 수동 리뷰로 검증. 편집은 spec §1/§2/§7 에 충실.

- [ ] **Step 1: 구조화 threshold 블록 삽입 (drift 테스트 대상)**

`## Definitions` 바로 위(또는 `## Inputs` 앞)에 삽입:

```markdown
## Thresholds (SSOT-synced — DO NOT EDIT WITHOUT thresholds.py)

<!-- SSOT-THRESHOLDS -->
이 값들은 `kr_pipeline/common/thresholds.py` 와 동기화됨 (tests/test_prompt_threshold_drift.py 가 검증).
- CUP_DEPTH_MAX_NORMAL_PCT = 33.0
- CUP_DEPTH_MAX_BEAR_RECOVERY_PCT = 50.0
- CUP_PRIOR_UPTREND_MIN_PCT = 30.0
- HANDLE_DEPTH_BULL_MIN_PCT = 8.0
- HANDLE_DEPTH_BULL_MAX_PCT = 12.0
- HANDLE_LEGIT_MIN_DAYS = 5
- MEASUREMENT_TOLERANCE_PCT = 5.0
<!-- /SSOT-THRESHOLDS -->
```

- [ ] **Step 2: drift 테스트 통과 확인**

Run: `uv run pytest tests/test_prompt_threshold_drift.py -v`
Expected: PASS (블록 파싱 + 값 정합 + orphan 없음).

- [ ] **Step 3: measurement 정식 출력 필드 추가 (Output Schema)**

`## Output Schema` 의 JSON 에 `measurements` 객체 추가(cup 경로). 기존 필드 뒤:

```json
  "measurements": {
    "prior_uptrend_pct": 40.0,
    "cup_depth_pct": 30.0,
    "cup_shape": "U",
    "handle_status": "legitimate | faulty | not_formed",
    "handle_position": "upper_half | lower_half",
    "handle_vs_sma50": "above | below",
    "handle_drift": "down | flat | up",
    "handle_depth_pct": 9.0,
    "handle_volume_ratio": 0.7
  }
```

그리고 Constraints 에 1줄: "`measurements`: cup 계열일 때 위 필드 보고. 비-cup 패턴/none 이면 null 허용. 숫자는 차트/OHLCV 에서 측정해 보고 — *라벨을 먼저 정하지 말고 측정값을 먼저 보고*."

- [ ] **Step 4: cup-scoped 결정 트리 삽입 (§4 Base Pattern 의 cup_with_handle 블록 앞)**

`### 4. Base Pattern` 안, cup_with_handle 정의 직후에 추가:

```markdown
**Cup 식별 — 측정-우선 결정 트리 (cup 계열 기하에만 적용; 책 의존성 순서)**:

먼저 위 `measurements` 를 숫자/enum 으로 측정·보고한 뒤, 아래 트리를 *순서대로* 적용해
`pattern` 을 도출하라. "무슨 모양 같나" 게슈탈트로 라벨을 먼저 정하지 말 것.

- **Gate0**: `prior_uptrend_pct < CUP_PRIOR_UPTREND_MIN_PCT(30%)` → `none` (O'Neil: 모든 cup 전제).
- **Gate1**: `cup_depth_pct > 깊이상한` → `none`. 깊이상한 = 정상장 CUP_DEPTH_MAX_NORMAL_PCT(33%);
  단 `market_context` 가 downtrend→confirmed_uptrend 전환(최근 60세션)이면 CUP_DEPTH_MAX_BEAR_RECOVERY_PCT(50%).
- **Gate2**: `cup_shape == "V"` (둥근 U 아님) → `none`.
- **Gate3 (핸들 — 분기, shape ≠ quality 분리; 길이 먼저)**:
  - **핸들 길이 < HANDLE_LEGIT_MIN_DAYS(5거래일 ≈1주)** → `pattern=cup_with_handle`,
    `handle_status=not_formed`, **classification=watch**. (2~3일 조임 = shakeout 미완 = *형성중* 이지
    결함 아님 — faulty 로 보지 말 것. O'Neil ~1주 floor.)
  - 핸들 미형성(cup 구조 완성, 핸들 아직) → `handle_status=not_formed`, **watch** (none 아님 —
    '매수점 없음'은 verdict 판단이지 shape 판단 아님).
  - 적법 핸들(길이 ≥5일 ∧ 상단절반 ∧ 50일선 위 ∧ 하향/평탄 drift ∧ 깊이 ≤12%) →
    `handle_status=legitimate` (entry 후보).
  - faulty 핸들(깊이 > HANDLE_DEPTH_BULL_MAX_PCT(12%) / **하단절반(handle_position=lower_half, 50% 경계)** /
    50일선 아래 / 위로 wedging) → `handle_status=faulty`, `risk_flags 에 handle_quality`, **classification=watch**.
  - cup 구조 아님 → `none`.

  ⚠ **handle_position 경계 = 50%** (책 '상단 절반'). measurement 의 `handle_position` enum(upper_half/lower_half)
  은 컵 중앙(50%) 기준. (handle_quality.py 의 `HANDLE_POSITION_LOW_RATIO=0.33` 은 *별개 heuristic weight* 로
  분류 경계 아님 — 혼동 금지.)

**불가침**: "핸들 faulty → none" 및 "핸들 미형성 → none" 금지. faulty/미형성 핸들도 *모양은 cup* 이다
(O'Neil HMMS Ch.2: faulty handle 도 여전히 'cup-with-handle', 단 failure-prone). shape 는 구조 feature
로만 정한다 — 품질·매수가능성 이유로 shape 를 none 으로 강등하지 말 것.

**허용밴드 (경계 칼날 금지)**: depth/선행상승 이 임계 ± MEASUREMENT_TOLERANCE_PCT(5%) 경계면, 작은 측정
오차로 cup↔none 을 뒤집지 말고 *구조의 다른 단서* 로 판단. (이 값은 측정 노이즈 흡수용.)
```

- [ ] **Step 5: 14th risk_flag (handle_quality) 등록**

§5 Risk Flags 테이블에 행 추가:

```markdown
| `handle_quality` | cup_with_handle 의 핸들이 faulty (깊이 >12% / 컵깊이 대비 과대 / 하단절반 / 50일선 아래 / 위로 wedging / 핸들 구간 분배). **품질 층 flag — shape 를 none 으로 만들지 않는다**(Gate3 faulty 분기와 함께). |
```

그리고 `risk_flags` taxonomy "13 values" 표기를 **14** 로 갱신(§5 머리말 + Constraints + Forbidden 의 "13-value" → "14-value").

- [ ] **Step 6: verdict 입력에 돌파 거래량 확인 보존 (spec §1 — 분해 누락 금지)**

§8 Classification 의 entry 조건에 1줄 강조 추가:

```markdown
- **돌파 거래량 확인 (verdict 필수 입력 — 분해로 누락 금지)**: entry 는 돌파 거래량 ≥ 50일 평균 1.4~1.5×
  (O'Neil/Minervini). 미달 → `low_volume_breakout` → entry 아닌 watch. ⚠ `measurements.handle_volume_ratio`
  (핸들 dry-up = 품질)와 *별개* — 혼동 금지.
```

- [ ] **Step 7: 전체 prompt 일관성 수동 리뷰**

확인: (1) Discipline rule "when in doubt → none" 이 *shape* 가 아니라 *verdict* 맥락인지(§4 트리는 구조 실격만 none). (2) §4.7 pivot 표·§7 pivot 정의가 트리와 모순 없는지. (3) Output Schema 의 pattern 9-value 유지(cup_without_handle 미추가).

- [ ] **Step 8: Commit**

```bash
git add prompts/analyze_chart_v3.md
git commit -m "feat(phase2-i): analyze prompt 측정-우선 — SSOT 블록 + measurement 필드 + cup-scoped 트리 Gate0~3(4분기) + 밴드 + handle_quality 14th flag"
```

---

## Phase D — verify prompt (Task 9)

### Task 9: verify_analysis_v1.md — 6차원 + layer-분리 + 14th flag

**Files:**
- Modify: `prompts/verify_analysis_v1.md`

prompt 편집 — 수동 리뷰 검증. spec §6 충실. **stale verify = 위험**(신구조를 오판 disagree).

- [ ] **Step 1: 검증 차원 5 → 6 으로 재구성**

`## 검증 5 차원` → `## 검증 6 차원` 으로, 차원을 재측정 게이트 진단축과 같은 언어로:

```markdown
## 검증 6 차원 (분석가 출력의 3층 구조를 거울처럼)

### (a) 측정 정확성 (measurements)
- 보고된 measurements 숫자(cup_depth_pct·prior_uptrend_pct·handle_*)가 차트/OHLCV 와 일치?
- ⚠ 검증자도 LLM read 라 ± MEASUREMENT_TOLERANCE_PCT(5%) **허용밴드 상속**. 밴드 초과 또는
  *트리 결과를 바꾸는* 차이만 flag. 1~2% 차이로 disagree 금지(false precision).

### (b) shape (결정 트리 적용)
- measurements 에 Gate0~3 가 *순서대로* 올바로 적용됐나(thresholds.py 재계산).
- cup-scoped: 비-cup 패턴은 (i) 트리 밖 — 기존 §4 정의로 평가.

### (c) handle_quality
- handle_status(legitimate/faulty/not_formed) 와 handle_quality flag 발화가 핸들 measurement 와 정합?

### (d) verdict (monotone)
- classification 이 shape + handle_quality + 시장(M) + **돌파 거래량 확인**을 보수적으로 결합?
- handle_volume_ratio(핸들 dry-up=품질)를 돌파 거래량 확인과 혼동하지 않았나.

### (e) layer-분리 무결성 (핵심 guardrail — 체크 규칙)
- shape=none/강등의 *정당화* 를 감사:
  - 구조적 실격(컵없음/V자/depth>33%/선행상승<30%) → **정상**.
  - 품질·tradability 이유(핸들 나쁨/매수점 없음/위험해서) → **재융합 → disagree**.
- 역방향: shape=cup_with_handle 인데 정당화가 'tradability/매수매력' 이면 flag.
- 원칙: shape 주장은 오직 구조 feature 로만 정당화.

### (f) reasoning 논리 + 인용 정확성
- 5 섹션 논리 연결 + Minervini/O'Neil 인용 정확.
```

- [ ] **Step 2: 출력 스키마 6 정식 필드로 확장**

`## 출력 — JSON 한 객체` 의 `dimensions` 객체를 `measurement / shape / handle_quality / verdict / layer_separation / reasoning` 6 키로(각 `verdict`+`note`). 특히 `layer_separation` 은 discrete 신호:

```json
    "layer_separation": {
      "verdict": "agree | disagree",
      "refusion_detected": false,
      "note": "shape 정당화가 구조 feature 로만 됐는지 / 품질·verdict 누설 여부."
    }
```

(기존 classification/pattern/pivot/risk_flags/reasoning 키는 위 6 으로 흡수·확장 — pattern→shape, classification→verdict, risk_flags→handle_quality 특화 + 나머지 taxonomy 는 (d)/(f) 에서.)

- [ ] **Step 3: 14th flag + taxonomy 동기화**

§4 risk_flag 전수 점검 목록(line 42)에 `handle_quality` 추가, "13 taxonomy" 표기를 14 로. handle_quality 가 *품질 층* flag(shape disqualifier 아님)임을 명시.

- [ ] **Step 4: 역할 경계 1줄**

`## 검증 원칙` 에 추가: "verify 는 분석가 출력을 책+3층 규칙에 *대조* 하는 것이지 제2의 분석가가 되어 재도출하는 게 아님. 밴드 내 차이는 존중 — disagree 로 보이려 disagree 하지 말 것."

- [ ] **Step 5: Commit**

```bash
git add prompts/verify_analysis_v1.md
git commit -m "feat(phase2-i): verify prompt 6차원(+layer-분리 guardrail) + 측정 밴드 상속 + handle_quality 14th"
```

---

## Phase E — backstop monotone-combine (Task 10)

### Task 10: gates.py monotone-combine 리팩토링

**Files:**
- Modify: `kr_pipeline/llm_runner/gates.py`
- Test: `tests/test_gates_phase1.py`

spec §3.1: detector 없이 보수적 합치기. `if classification=='entry'` 특수분기 제거 — `most_conservative` 가 ignore/watch 를 자연 no-op 으로 만들고(v5 ignore→watch 승격 버그 구조적 차단), conf 는 `min`. **행동 변화**: handle_quality 발화 시 conf cap 이 entry 뿐 아니라 *현 verdict 무관* 적용(min). 기존 entry 테스트는 통과(아래 회귀).

- [ ] **Step 1: 신규 동작 실패 테스트 작성**

`tests/test_gates_phase1.py` 에 추가:

```python
def test_monotone_no_promotion_ignore_stays(monkeypatch, db):
    """ignore + handle_quality → ignore 유지 (most_conservative no-promotion)."""
    monkeypatch.setattr(gates, "compute_handle_quality",
                        lambda *a, **k: {"fired": True, "reasons": ["deep_handle"], "weights": [], "metrics": {}})
    monkeypatch.setattr(gates, "compute_failed_breakout", lambda *a, **k: None)
    result = _base_result(classification="ignore", confidence=0.90, risk_flags=[])
    out, tr = gates.apply_phase1_gates(db, "IG", datetime(2026, 1, 1, tzinfo=timezone.utc), result)
    assert out["classification"] == "ignore"          # 승격 금지
    assert out["confidence"] <= 0.60                    # conf cap 은 적용 (min)
    assert "handle_quality" in out["risk_flags"]


def test_monotone_watch_conf_capped_with_extended(monkeypatch, db):
    """LLM 이 이미 watch + handle_quality + extended → watch 유지 + conf ≤ 0.50."""
    monkeypatch.setattr(gates, "compute_handle_quality",
                        lambda *a, **k: {"fired": True, "reasons": ["deep_handle"], "weights": [], "metrics": {}})
    monkeypatch.setattr(gates, "compute_failed_breakout", lambda *a, **k: None)
    result = _base_result(classification="watch", confidence=0.80, risk_flags=["extended_from_ma"])
    out, tr = gates.apply_phase1_gates(db, "WX", datetime(2026, 1, 1, tzinfo=timezone.utc), result)
    assert out["classification"] == "watch"
    assert out["confidence"] <= 0.50
    assert "2E_tier2" in tr
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_gates_phase1.py::test_monotone_no_promotion_ignore_stays -v`
Expected: FAIL (현 코드는 entry 가 아니면 conf cap 미적용).

- [ ] **Step 3: gates.py monotone 리팩토링**

`apply_phase1_gates` 의 handle_quality 블록을 교체. 파일 상단 `TIER1_CONF_CAP`/`TIER2_CONF_CAP` 아래에 추가:

```python
VERDICT_ORDER = {"ignore": 0, "watch": 1, "entry": 2}  # 낮을수록 보수


def _most_conservative(a: str, b: str) -> str:
    return a if VERDICT_ORDER.get(a, 2) <= VERDICT_ORDER.get(b, 2) else b
```

handle_quality 블록(현 line 31~65)을 다음으로 교체:

```python
    # === handle_quality (관찰 flag 주입 — classification 무관) ===
    hq = compute_handle_quality(conn, symbol, classified_at, result)
    if hq and hq.get("fired"):
        if "handle_quality" not in risk_flags:
            risk_flags.append("handle_quality")

        # === backstop 강등 패키지 (monotone-combine, spec §3.1) ===
        # verdict floor = watch (승격 절대 안 함), conf cap = tier 별.
        extended = "extended_from_ma" in risk_flags
        backstop_cap = TIER2_CONF_CAP if extended else TIER1_CONF_CAP
        tier = "2E_tier2" if extended else "2E_tier1"
        inputs = ["handle_quality", "extended_from_ma"] if extended else ["handle_quality"]

        prev_verdict = result.get("classification")
        result["classification"] = _most_conservative(prev_verdict, "watch")  # ignore→ignore, watch→watch, entry→watch
        conf = result.get("confidence")
        result["confidence"] = backstop_cap if conf is None else min(conf, backstop_cap)

        triggered[tier] = {
            "fired": True,
            "inputs": inputs,
            "verdict_floor": "watch",
            "demoted": prev_verdict != result["classification"],
            "conf_cap": backstop_cap,
            "entry_params_block": extended,
            "handle_quality_metrics": hq.get("metrics"),
        }
```

(기존 `if result.get("classification") == "entry":` 분기 전체 제거 — monotone 이 흡수.)

- [ ] **Step 4: 신규 + 회귀 통과 확인**

Run: `uv run pytest tests/test_gates_phase1.py -v`
Expected: PASS — 신규 2개 + 기존 `test_tier1_soft_watch`/`test_tier2_hard_watch_with_extended` (entry 케이스라 동작 동일).

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/llm_runner/gates.py tests/test_gates_phase1.py
git commit -m "refactor(phase2-i): gates monotone-combine — detector 제거, most_conservative+min(conf), ignore 승격 구조적 차단"
```

---

## Phase F — 재측정 게이트 (Task 11, build-first)

### Task 11: build-first 재측정 하니스 + 가지별 음성 패널

**Files:**
- Create: `scripts/remeasure_phase2i.py`
- Create (실행 산출): `docs/superpowers/verification/2026-05-31-phase2-i-remeasure/FINDINGS.md`

spec §10. **build-first**: Task 1~10 적용된 prompt 로 N=10 동일입력 실행 → feature 재현성(9~10/10 band-containment) + verdict 재현 + faulty→handle_quality 인용을 *진단형* 으로 집계. 실제 LLM 호출 → 수동 실행. ±5% 밴드는 고정 시작값, straddle 발견 시 Task 2 밴드 수정 후 Task 7 재방문(1회 루프).

- [ ] **Step 1: 하니스 스크립트 작성**

`scripts/remeasure_phase2i.py` — 패널 티커 × N 회 `build_analysis_zip`(고정 on_date) → `call_claude("analyze_chart_v3.md", ...)` → measurements/pattern/classification/risk_flags 수집 → 회차간 분산·재현율 집계. (DB 미기록 — 진단 전용.) 패널 구조:

```python
# scripts/remeasure_phase2i.py
"""Phase 2 (i) build-first 재측정 하니스 (spec §10). DB 미기록 — 진단 전용.
실행: uv run python scripts/remeasure_phase2i.py --n 10
패널 티커는 실행 시점 데이터에서 선정(아래 PANEL 채우기). 가지별 음성 1 + faulty + 양성.

입력 고정: build_analysis_zip(conn, symbol) 는 DB 의 현재 데이터로 ZIP bytes 생성.
순수 경로 검증이려면 데이터 적재를 멈춘 채(또는 고정 거래일 DB) 실행 — 검증 시점 데이터 명시.
"""
from __future__ import annotations
import argparse, json, os, statistics, tempfile
from collections import Counter
from pathlib import Path

import psycopg

# 가지별 패널 — 실행 단계에서 실제 티커로 채움 (Step 2).
PANEL = {
    "gate0_neg": {"ticker": None, "expect_pattern": "none",            "note": "선행상승<30%"},
    "gate1_neg": {"ticker": None, "expect_pattern": "none",            "note": "depth>33% / wide-loose"},
    "gate2_neg": {"ticker": None, "expect_pattern": "none",            "note": "진짜 V자"},
    "gate3_neg": {"ticker": "005850", "expect_pattern": "cup_with_handle", "expect_cls": "watch", "expect_flag": "handle_quality", "note": "faulty handle"},
    "gate3_short": {"ticker": None, "expect_pattern": "cup_with_handle", "expect_cls": "watch", "note": "sub-1주 핸들 → handle_status=not_formed (형성중, faulty 아님)"},
    "positive":  {"ticker": None, "expect_cls": "entry|watch",         "note": "적법 핸들 cup"},
}

FEATURE_KEYS = ["prior_uptrend_pct", "cup_depth_pct", "handle_depth_pct", "handle_volume_ratio"]


def run_one(conn, ticker: str) -> dict:
    """고정 입력 1회 분석 — weekend._analyze_one 의 ZIP→temp→call_claude 패턴 그대로 (DB 미기록)."""
    from api.services.zip_builder import build_analysis_zip
    from kr_pipeline.llm_runner.llm.claude_cli import call_claude
    zip_bytes = build_analysis_zip(conn, ticker)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        f.write(zip_bytes)
        zip_path = f.name
    try:
        return call_claude(prompt_file="analyze_chart_v3.md", attachments=[zip_path], dry_run=False)
    finally:
        Path(zip_path).unlink(missing_ok=True)


def diagnose(runs: list[dict], expect: dict) -> dict:
    patterns = Counter(r.get("pattern") for r in runs)
    classes = Counter(r.get("classification") for r in runs)
    # feature 분산 (band-containment 판정용)
    feat_stats = {}
    for k in FEATURE_KEYS:
        vals = [r.get("measurements", {}).get(k) for r in runs if r.get("measurements")]
        vals = [v for v in vals if isinstance(v, (int, float))]
        if vals:
            feat_stats[k] = {"mean": round(statistics.mean(vals), 2),
                             "stdev": round(statistics.pstdev(vals), 3) if len(vals) > 1 else 0.0,
                             "min": min(vals), "max": max(vals)}
    # handle_quality 인용율
    hq = sum(1 for r in runs if "handle_quality" in (r.get("risk_flags") or []))
    return {"n": len(runs), "patterns": dict(patterns), "classes": dict(classes),
            "feature_stats": feat_stats, "handle_quality_cited": hq, "expect": expect}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    args = ap.parse_args()
    conn = psycopg.connect(os.environ["DATABASE_URL"])
    report = {}
    try:
        for key, cfg in PANEL.items():
            if not cfg.get("ticker"):
                print(f"[skip] {key}: 티커 미선정"); continue
            runs = [run_one(conn, cfg["ticker"]) for _ in range(args.n)]
            report[key] = diagnose(runs, cfg)
    finally:
        conn.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

(`build_analysis_zip` 은 `api/services/zip_builder.py` 의 `build_analysis_zip(conn, symbol) -> bytes`. `DATABASE_URL` 환경변수 사용 — 운영 DB 직접 읽으므로 검증 시점 데이터 고정 권장.)

- [ ] **Step 2: 패널 티커 선정 (데이터 실측)**

`PANEL` 의 `None` 티커를 실제 데이터에서 선정 — 정직한 음성이 되도록 SQL/차트로 확인:
- gate0_neg: 선행상승 <30% 인 cup-유사 종목
- gate1_neg: base depth >33% / wide-loose
- gate2_neg: V자 반등
- positive: 적법 핸들 cup (상단절반·50일선 위·하향 drift·거래량 dry-up)

확인 근거를 FINDINGS 에 기록.

- [ ] **Step 3: 재측정 실행 + 진단**

Run: `uv run python scripts/remeasure_phase2i.py --n 10`
판정(spec §10):
- **feature 안정(9~10/10 band-containment) + verdict 안정** → 청정 통과.
- feature 안정 + verdict 흔들 → 트리/precedence 구멍 → Task 7 트리 수정 후 재실행.
- feature 흔들(depth band straddle) → 측정 문제 → Task 2 밴드 폭 보정 후 Task 7 재방문(1회) 후 재실행. 졸업 후보면 FINDINGS 에 (ii) 신호로 기록.

합격 기준: 5종목 *전 가지* 가 기대대로 안정 + gate3_neg(005850) 가 cup_with_handle ≥9/10 + watch + handle_quality 인용 ≥9/10.

- [ ] **Step 4: FINDINGS 작성 + commit**

`docs/superpowers/verification/2026-05-31-phase2-i-remeasure/FINDINGS.md` 에 패널 선정 근거 + 진단 결과 + 판정(통과/루프) 기록.

```bash
git add scripts/remeasure_phase2i.py docs/superpowers/verification/2026-05-31-phase2-i-remeasure/
git commit -m "test(phase2-i): build-first 재측정 하니스 + 가지별 음성 패널 결과"
```

- [ ] **Step 5: 게이트 통과 시 ROADMAP 갱신**

합격하면 `docs/PROJECT_ROADMAP.md` §5 의 Phase 2 (i)/재측정 게이트 행을 종결 표시 + 2-B/C/D "재측정 합격선 통과 후" 차단 해제. memory `phase1_2a_state.md` 갱신.

```bash
git add docs/PROJECT_ROADMAP.md
git commit -m "docs(phase2-i): 재측정 게이트 통과 — 2-B/C/D 차단 해제"
```

---

## Self-Review (작성자 점검)

**Spec coverage:**
- §1 3층 분해 → Task 7(트리 4분기·불가침)·Task 9(layer-분리)·Task 10(monotone). ✓
- §2 측정-우선(정식 필드+트리+밴드) → Task 6(DB)·Task 7. ✓
- §3 backstop monotone(헌법) → Task 10. ✓
- §4 depth 장중정의/단일소스 연기 → Task 3(장중 lock 주석, 이미 intraday). ✓
- §5 SSOT(패턴×시장·book/heuristic·drift·10주선→50일선·의존성맵) → Task 1·2·3·4·5. ✓ (10주선→50일선은 §2 트리 Gate3 "50일선" 표기로 반영.)
- §6 verify 6차원 → Task 9. ✓
- §7 14th flag → Task 7 Step5·Task 9 Step3. ✓
- §8 비목표(다패턴/단일소스/auto-sync 연기) → Task 7 cup-scoped·Task 4 비수정. ✓
- §9 실행순서 build-first → Task 11. ✓
- §10 재측정 게이트(N=10 진단형·가지별 음성패널) → Task 11. ✓

**Placeholder scan:** `build_analysis_zip(conn, symbol)→bytes` (api/services/zip_builder.py) 확정 반영. PANEL 티커는 Step 2 가 실측 선정으로 채움(데이터 의존 — 정직한 음성이려면 사전 박제 불가, 선정 근거를 FINDINGS 에 기록). 그 외 코드 완성.

**Type consistency:** `most_conservative`/`VERDICT_ORDER`(Task 10), `measurements` 키(Task 6/7/8 동일 키), threshold 상수명(Task 2 정의 ↔ Task 3/5/7 참조) 일치 확인.

**주의 (실행자):**
- Task 10 은 행동 변화(conf cap 이 현 verdict 무관 적용) — 의도된 spec §3.1. **minor-2 확인**: ignore 의 낮춰진 confidence 가 다른 소비처에서 '품질 신호'로 오독되지 않는지 1회 확인 (`grep -rn "confidence" kr_pipeline/ api/ web/src` 로 ignore 분기 소비처 점검).
- Task 7 prompt 편집 후 dry-run mock(`_mock_analyze_chart_v3`)에 measurements 키 미포함 — dry-run 경로 쓰는 테스트가 있으면 mock 도 measurements 추가 검토.
- **핸들 길이 게이트**: Task 7 Gate3 의 길이 분기(< HANDLE_LEGIT_MIN_DAYS → not_formed)는 *형성중* (faulty 아님). HANDLE_MIN_DAYS(=3, heuristic 계산 윈도우)와 혼동 금지 — 분류 게이트는 HANDLE_LEGIT_MIN_DAYS(=5).
