# Issue #19 — B 회복게이트 분배일 재확인 추가 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `evaluate_pivot_trigger_v1.md` §3.5의 `unfavorable_market` 회복 판정에 "분배일 수가 강등 임계(5) 미만으로 해소됐는가" 재확인을 추가해, A가 분배일 5개로 watch 강등한 종목이 분배일 5개 그대로인 날 go_now 통과하는 역류(03편 조건부모순 I)를 차단한다.

**Architecture:** 프롬프트 텍스트 1개 bullet 보강(payload에 `market_context.distribution_day_count_last_25_sessions`가 이미 존재하므로 코드 무변경) + A↔B 교차 임계 드리프트 가드 테스트 신설 + threshold-change-checklist 의존성 맵(아래 포함, 적용 이력 append).

**Tech Stack:** markdown 프롬프트, pytest(텍스트 가드 — DB 불필요).

## Global Constraints

- `uv run pytest tests/` 기대 실패 **0**.
- **threshold-change-checklist 트리거 해당** (프롬프트 임계 텍스트 변경) → 아래 의존성 맵이 spec 게이트. 단 "5"는 코드 비소비 프롬프트 전용값이므로 SSOT 비등재 원칙(적용 이력 2026-07-08) 유지 — thresholds.py 무변경.
- 커밋 메시지에 Claude co-author trailer 금지.
- 동작 방향: 보수화만(go_now → wait 가능성 추가, 그 역은 없음) — AND 결합 게이트.

## 사전 확인된 사실 (main 16c5bfd)

- B §3.5 unfavorable_market 회복 분기(`evaluate_pivot_trigger_v1.md:138-141`)는 `current_status == "confirmed_uptrend"`만 확인 — 분배일 수 재확인 없음.
- A 강등 룰(`analyze_chart_v3.md:101`): `distribution_day_count_last_25_sessions >= 5` → confidence −0.15 + prefer watch + `unfavorable_market_context`. "5"는 free text(SSOT 비등재).
- 상태 전환은 6개부터(`STATUS_DIST_COUNT_FOR_FTD_INVALIDATION = 6`, thresholds.py:192) → 분배일 5개는 confirmed_uptrend와 공존 가능 = 역류 통로.
- B 공통 게이트의 "최근 3일 distribution day 없음"(`:132`)은 **최근성** 차원 — 25세션 **누적** 카운트와 독립(3일 무분배 + 누적 5개 공존 가능).
- payload에 필드 실존: `build_for_5b` → `build_market_context` → `distribution_day_count_last_25_sessions`(`api/services/market_context_builder.py:53`) — 코드 변경 불필요.
- C §7 breakout_from_watch 예외(stale unfavorable_market_context 미적용, `calculate_entry_params_v2_0.md:376-382`)의 전제("B 통과 = 시장 회복 증거")가 본 수리로 실제 성립하게 됨 — C 무변경.

## 임계 변경 의존성 맵 (checklist (b) 2축 판정)

**변경**: B §3.5 unfavorable_market 회복 조건에 `distribution_day_count_last_25_sessions < 5` AND 게이트 추가 (신규 임계 텍스트 — A의 강등 임계 5와 co-anchored).

**1단계 (파생 신호)**: `distribution_day_count_last_25` (market_context_daily 적재값, 변경 없음) → payload `market_context.distribution_day_count_last_25_sessions` → B §3.5 신규 게이트 입력.

**2단계 (소비 룰)** — `grep -rn "distribution_day_count" prompts/ kr_pipeline/ api/`: ① A §3.5 강등(≥5, :101) ② B §3.5 회복 재확인(<5, 신규) ③ status.py 룰3 FTD 무효화(≥6) ④ C changelog 서술(≥5, 서술만) ⑤ market_context_builder(전달만).

**3단계 (룰 내부 고정 상수) — 2축 판정**:

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| A §3.5 강등 임계 5 (free text) | 부분 (dist_pct 보정이 카운트를 바꿔 연동) | **있음** — B 재확인 임계가 A 강등 임계와 동치여야 역류 차단이 정확 (5=5 co-anchored) | EXTENDS (책은 "5~6개 누적 시 위험" 통용, 구체 5는 시스템 채택) | **교차 가드 테스트로 동치 강제** (본 계획 Task 1 — A 변경 시 B 미동반 변경이면 테스트 red) |
| STATUS_DIST_COUNT_FOR_FTD_INVALIDATION = 6 | 부분 (동일 연동) | **미미** — dist≥6 이면 status 자체가 confirmed_uptrend 를 이탈해 회복 분기 진입 불가; 신규 게이트가 결정적인 구간은 dist=5 뿐 | EXTENDS | 모니터링 (근거: 신규 게이트와 룰3 은 서로 다른 status 구간에서 작동 — 겹침 없음) |
| B 공통 게이트 "최근 3일 dist 없음" (:132) | 불가 (시간) | **미미** — 최근성 vs 누적의 독립 차원, AND 결합이라 보수 방향으로만 상호작용 | EXTENDS | 모니터링 (근거: AND 게이트 추가는 기존 게이트의 동작을 바꾸지 않음) |

**소비 경계 (1줄)**: `distribution_day_count_last_25 → market_context_daily → build_for_5b payload → evaluate_pivot_trigger_v1.md §3.5 go_now/wait → entry_params 직행 여부` (하류 단일 경로).

**게이트 자가 점검**: 맵 존재 ✓ / 3단계 상수 행 3개 ✓ / 축1·축2 전 칸 기입 ✓ / 축2 있음 행의 후속 = 행동 예약(테스트) ✓ / 소비 경계 1줄 ✓.

---

### Task 1: A↔B 교차 임계 가드 테스트 (RED)

**Files:**
- Create: `tests/test_prompt_trigger_gates.py`

**Interfaces:**
- Produces: B §3.5 unfavorable_market bullet 이 분배일 재확인을 포함하고, 그 임계 숫자가 A §3.5 강등 임계와 동치임을 강제하는 가드.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""B §3.5 unfavorable_market 회복 게이트 — 분배일 재확인 가드 (#19).

역류(03편 조건부모순 I) 재발 방지: 회복 판정이 status 라벨만 보지 않고
강등 원인(분배일 누적)을 재확인하는지, 그 임계가 A 의 강등 임계와 동치인지 강제.
"""
import re
from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
B_PROMPT = PROMPTS / "evaluate_pivot_trigger_v1.md"
A_PROMPT = PROMPTS / "analyze_chart_v3.md"


def _b_unfavorable_block() -> str:
    """§3.5 watch_reason 게이트 목록에서 unfavorable_market bullet 만 추출."""
    text = B_PROMPT.read_text(encoding="utf-8")
    m = re.search(r"- `unfavorable_market`:(.*?)(?=\n- `|\n\n\*\*공통\*\*)", text, re.S)
    assert m, "B §3.5 에 unfavorable_market 게이트 bullet 이 없음"
    return m.group(1)


def test_unfavorable_market_recovery_rechecks_distribution_count():
    block = _b_unfavorable_block()
    assert "distribution_day_count_last_25_sessions" in block, (
        "unfavorable_market 회복 판정이 분배일 수를 재확인하지 않음 — "
        "status 라벨만으로 회복 판정 시 dist=5 역류(강등 사유 미해소 go_now) 재발"
    )


def test_recovery_threshold_matches_demotion_threshold():
    """B 회복 임계(< N)와 A 강등 임계(>= N)는 같은 N 이어야 역류가 정확히 닫힌다."""
    a_text = A_PROMPT.read_text(encoding="utf-8")
    a_m = re.search(r"distribution_day_count_last_25_sessions`?\s*>=\s*(\d+)", a_text)
    assert a_m, "A §3.5 강등 임계(>= N)를 찾지 못함"
    b_m = re.search(r"distribution_day_count_last_25_sessions`?\s*<\s*(\d+)", _b_unfavorable_block())
    assert b_m, "B 회복 임계(< N)를 찾지 못함"
    assert a_m.group(1) == b_m.group(1), (
        f"임계 드리프트: A 강등 >= {a_m.group(1)} vs B 회복 < {b_m.group(1)} — "
        "한쪽만 변경 시 역류 구간이 다시 열림"
    )
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_prompt_trigger_gates.py -v`
Expected: FAIL 2건 — block 에 분배일 재확인 없음

- [ ] **Step 3 (GREEN 은 Task 2)** — 이 Task 는 RED 확인까지. 커밋은 Task 2 와 함께(red 상태 커밋 금지).

---

### Task 2: B 프롬프트 §3.5 회복 게이트 보강 (GREEN)

**Files:**
- Modify: `prompts/evaluate_pivot_trigger_v1.md:138-141`

- [ ] **Step 1: bullet 교체** — 기존:

```markdown
- `unfavorable_market`: 강등 사유가 시장이었으므로 **`market_context.current_status ==
  "confirmed_uptrend"` (회복) 일 때만** `go_now`. 여전히 downtrend/correction/미확인
  rally_attempt 면 표준 검증을 충족해도 `wait` (시장이 아직 안 받쳐줌). ⚠ `watch_reason`
  값 자체를 회복 근거로 쓰지 말 것 — 반드시 입력 `market_context`(현재 값)로 판단.
```

교체:

```markdown
- `unfavorable_market`: 강등 사유가 시장이었으므로 **`market_context.current_status ==
  "confirmed_uptrend"` (회복) 이고 `market_context.distribution_day_count_last_25_sessions < 5`
  (강등 임계 미만으로 해소 — analyze_chart_v3 §3.5 의 ≥5 강등과 co-anchored) 일 때만** `go_now`.
  여전히 downtrend/correction/미확인 rally_attempt 면, 또는 분배일이 아직 5개 이상이면
  표준 검증을 충족해도 `wait` (강등 사유가 해소되지 않음 — status 라벨은 분배일 5개와
  공존 가능하므로 라벨만으로 회복 판정 금지). ⚠ `watch_reason` 값 자체를 회복 근거로
  쓰지 말 것 — 반드시 입력 `market_context`(현재 값)로 판단.
```

- [ ] **Step 2: 통과 확인**

Run: `uv run pytest tests/test_prompt_trigger_gates.py tests/test_prompt_threshold_drift.py -v`
Expected: 전체 PASS

- [ ] **Step 3: A 프롬프트에 co-anchor 상호주석** — `analyze_chart_v3.md:101` bullet 끝에 추가:

```markdown
(this 5 is co-anchored with evaluate_pivot_trigger_v1 §3.5 recovery gate `< 5` — change both together; guarded by tests/test_prompt_trigger_gates.py)
```

- [ ] **Step 4: 재확인**

Run: `uv run pytest tests/test_prompt_trigger_gates.py tests/test_prompt_threshold_drift.py -q`
Expected: PASS (A 주석 추가가 정규식 매칭을 깨지 않는지 확인)

- [ ] **Step 5: 커밋**

```bash
git add prompts/evaluate_pivot_trigger_v1.md prompts/analyze_chart_v3.md tests/test_prompt_trigger_gates.py
git commit -m "fix(prompt): B unfavorable_market 회복에 분배일 <5 재확인 추가 — dist5 역류 차단 (#19)"
```

---

### Task 3: checklist 적용 이력 + 전체 회귀

- [ ] **Step 1: 적용 이력 append** — `docs/superpowers/threshold-change-checklist.md` 적용 이력에:

```markdown
- 2026-07-10: #19 B §3.5 unfavorable_market 회복 게이트에 dist<5 재확인 추가 (03편 조건부모순 I 수리). 의존성 맵 = docs/superpowers/plans/2026-07-10-issue-19-dist5-recovery-recheck.md. "5"는 코드 비소비 프롬프트 전용값 — SSOT 비등재 원칙 유지, A↔B 동치는 tests/test_prompt_trigger_gates.py 가 강제. 동작 방향 = 보수화만(AND 게이트).
```

- [ ] **Step 2: 전체 테스트**

Run: `uv run pytest tests/ -q`
Expected: 실패 0

- [ ] **Step 3: 커밋**

```bash
git add docs/superpowers/threshold-change-checklist.md docs/superpowers/plans/2026-07-10-issue-19-dist5-recovery-recheck.md
git commit -m "docs(checklist): #19 의존성 맵·적용 이력 — dist5 회복 재확인 (#19)"
```

## Self-Review 체크

1. **Spec coverage**: 이슈의 수정 방향("회복 조건에 분배일 수 < 강등 임계(5) 재확인 한 줄 + checklist") — Task 2 + 의존성 맵 ✓. 재발 방지(교차 가드) ✓.
2. **Placeholder scan**: 전 스텝 실코드/실문구 포함 ✓.
3. **Type consistency**: 필드명 `distribution_day_count_last_25_sessions` 가 payload(:53)·A(:101)·B 신규 문구·테스트 정규식에서 동일 ✓.
