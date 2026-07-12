# Issue #29 — 형제 분기 시장 재확인(방안 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** B §3.5의 형제 분기(marginal_tt·valid_base_awaiting_breakout)에 "prior risk_flags에 `unfavorable_market_context`가 있으면 unfavorable_market 게이트의 시장 재확인도 충족해야 go_now" 조건부 AND 게이트를 추가해, dist≥5 역류의 옆문(#29)을 닫는다.

**Architecture:** 프롬프트 텍스트 2개 bullet 보강(코드 무변경 — 5b payload에 `prior_analysis.risk_flags`·`market_context` 실존 확인 완료) + 가드 테스트 확장. 형제 bullet은 **임계 숫자를 재복제하지 않고** unfavorable_market 게이트를 참조(리터럴 사본 증가 방지 — PR #27 리뷰 5번 지적의 교훈). 동반 처리(같은 리뷰 답글 5번 권고): A측 임계 추출 정규식의 §3.5 스코핑 + unfavorable_market bullet 산문 리터럴 정리(3사본→1사본).

**Tech Stack:** markdown 프롬프트, pytest(텍스트 가드 — DB 불필요).

## Global Constraints

- `uv run pytest tests/` 기대 실패 **0**.
- **threshold-change-checklist 트리거 해당**(프롬프트 임계 텍스트 변경) → 아래 의존성 맵이 게이트. 신규 숫자 리터럴 추가 없음(게이트 참조 방식) — thresholds.py 무접촉.
- 동작 방향: **보수화만**(형제 분기에 AND 조건 추가 — go_now→wait 방향만 가능).
- 커밋 trailer 금지. C §7·백스톱(답글 6번)은 범위 외(후자는 PR 본문에 선택 항목으로 기록).

## 사전 확인된 사실 (main 55d4e71 — #29 브리핑에서 재검증 완료)

- B 형제 분기 `:136-137`(valid_base)·`:145-147`(marginal_tt)에 시장 재확인 없음.
- A §8.5 D4(:455-458): unfavorable_market vs marginal_tt 우선순위 무규정 → 동시 해당 시 사유가 marginal_tt로 기록 가능(+A §3.5 :102가 flag는 무관하게 강제 부여).
- 5b payload: `prior_analysis.risk_flags`(payload_lite.py:139)·`market_context`(:125) 실존 — 프롬프트만으로 수리 자립.
- C §7(:365-373) 면제의 근거 문장은 unfavorable_market 경로 전제 — 본 수리로 **전제가 전 경로에서 성립하게 됨**(C 무변경, 정합 복원).
- 기존 가드: `tests/test_prompt_trigger_gates.py` — `_b_unfavorable_block` 추출 정규식의 bullet 경계는 `\n- \`` 또는 `\n\n**공통**`; 형제 bullet 내부에 줄 추가해도 경계 불변(marginal_tt는 마지막 bullet → **공통** 경계, valid_base는 다음 bullet 경계).

## 임계 변경 의존성 맵 (checklist (b) 2축 판정)

**변경**: 형제 분기 2곳에 조건부 참조 게이트 추가("flag 존재 시 unfavorable_market 게이트와 동일한 시장 재확인 충족"). 숫자 리터럴 신설 없음.

**1단계 (파생 신호)**: `prior_analysis.risk_flags`의 `unfavorable_market_context`(분류 시점 기록, 변경 없음) + `market_context.current_status`/`distribution_day_count_last_25_sessions`(현재 값, 변경 없음) → 형제 분기 go_now 판정에 신규 참여.

**2단계 (소비 룰)**: ① B §3.5 형제 분기 2곳(신규 소비) ② unfavorable_market 게이트(기존 — 참조 대상) ③ C §7 면제(간접 — 전제 성립 복원, 무변경) ④ A §3.5 flag 부여 룰(생산자, 무변경).

**3단계 (룰 내부 고정 상수) — 2축 판정**:

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| 강등/회복 임계 5 (unfavorable_market 게이트 내 free text) | 부분 | **있음** — 형제 분기가 같은 게이트를 참조하므로 임계 변경 시 3경로 동시 반영(사본 미증가가 정확히 이 목적) | EXTENDS | 참조 방식 채택으로 사본 1개 유지 + 기존 A↔B 교차 가드가 계속 단일 지점을 강제 |
| A §3.5 flag 부여 조건(dist≥5 등) | 부분 | 미미 — flag 생산 룰 무변경, 소비만 추가. flag가 stale(분류 후 시장 회복)이어도 재확인 게이트가 dist<5면 통과시키므로 차단 아님(보수 방향 한정) | EXTENDS | 모니터링 (근거: AND 게이트는 현재 시장이 실제로 회복됐으면 투명) |
| D4 우선순위 공백 (A §8.5) | 불가 | 미미 — 본 수리로 **시장 재확인 축에서는** 사유 기록과 무관하게 결과 동일(공백 자체는 존치). ⚠ 거울 방향 잔존: marginal+시장불안 동시 해당 종목이 unfavorable_market 으로 기록되면 marginal_tt 의 clean-TT 재확인을 건너뜀 — marginal 흔적 flag 가 없어 flag 조건부 방식으론 폐쇄 불가(#22 재설계 검토 대상, PR #34 리뷰 발견) | EXTENDS | 존치 + #22 에 거울 갭 기록 |

**소비 경계 (1줄)**: `risk_flags(분류 시점) + market_context(현재) → build_for_5b payload → evaluate_pivot_trigger §3.5 go_now/wait → entry_params 직행 여부` (하류 단일 경로 — C §7 전제 정합 복원 포함).

**게이트 자가 점검**: 맵 ✓ / 3단계 3행 ✓ / 축1·축2 전 칸 ✓ / 축2 있음 행 후속=사본 미증가 설계+기존 가드 ✓ / 소비 경계 1줄 ✓.

---

### Task 1: 가드 테스트 확장 (RED)

**Files:** Modify: `tests/test_prompt_trigger_gates.py`

- [ ] **Step 1: 실패하는 테스트 추가**

```python
def _b_sibling_blocks() -> dict:
    """§3.5 형제 분기(valid_base·marginal_tt) bullet 추출."""
    text = B_PROMPT.read_text(encoding="utf-8")
    out = {}
    for name in ("valid_base_awaiting_breakout", "marginal_tt"):
        m = re.search(r"- `%s`:(.*?)(?=\n- `|\n\n\*\*공통\*\*)" % name, text, re.S)
        assert m, f"B §3.5 에 {name} 게이트 bullet 이 없음"
        out[name] = m.group(1)
    return out


def test_sibling_gates_recheck_market_when_flagged():
    """(#29) 형제 분기 — unfavorable_market_context flag 존재 시 시장 재확인 요구.

    사유(watch_reason)가 marginal_tt/valid_base 로 기록됐어도 flag 가 있으면
    unfavorable_market 게이트와 동일한 재확인을 거쳐야 역류 옆문이 닫힌다.
    """
    for name, block in _b_sibling_blocks().items():
        assert "unfavorable_market_context" in block, (
            f"{name} 분기가 flag 조건부 시장 재확인을 요구하지 않음 — #29 옆문 재개방"
        )


def test_sibling_gates_do_not_duplicate_threshold_literal():
    """(#29) 형제 분기는 임계 숫자를 재복제하지 않고 게이트를 참조해야 한다 —
    사본 증가 시 임계 변경이 한쪽만 반영되는 드리프트 통로가 생긴다."""
    for name, block in _b_sibling_blocks().items():
        assert not re.search(r"distribution_day_count_last_25_sessions`?\s*[<>=]+\s*\d", block), (
            f"{name} 분기에 임계 리터럴 사본 — unfavorable_market 게이트 참조로 대체할 것"
        )
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_prompt_trigger_gates.py -v`
Expected: test_sibling_gates_recheck_market_when_flagged FAIL 1건(형제 2분기 모두 flag 미언급), 사본 테스트는 PASS(현재 사본 없음 — 수리 후에도 PASS 유지가 목표)

- [ ] **Step 3 (동반 처리 — 답글 5번): A측 정규식 §3.5 스코핑**

`test_recovery_threshold_matches_demotion_threshold` 의 A측 추출을:
```python
    a_35 = re.search(r"### 3\.5\..*?(?=\n### )", a_text, re.S)
    assert a_35, "A 프롬프트에 §3.5 섹션이 없음"
    a_m = re.search(r"distribution_day_count_last_25_sessions`?\s*>=\s*(\d+)", a_35.group(0))
```

### Task 2: 프롬프트 수리 (GREEN)

**Files:** Modify: `prompts/evaluate_pivot_trigger_v1.md`

- [ ] **Step 1: 형제 bullet 2곳 보강** — 각 bullet 끝에 추가:

valid_base_awaiting_breakout:
```markdown
  **단, `prior_analysis.risk_flags` 에 `unfavorable_market_context` 가 있으면** 위 조건에 더해
  `unfavorable_market` 게이트와 동일한 시장 재확인(현재 `market_context` 로 회복+분배일 해소 판정)도
  충족해야 `go_now` — 사유로 기록되지 않았어도 flag 는 분류 시점 시장 불안의 기록이다.
```
marginal_tt 에도 동일 문구.

- [ ] **Step 2: 산문 리터럴 정리 (답글 5번)** — unfavorable_market bullet 의
"또는 분배일이 아직 5개 이상이면" → "또는 분배일이 아직 강등 임계(위 `< 5` 의 5) 미해소면",
"status 라벨은 분배일 5개와 공존 가능하므로" → "status 라벨은 강등 임계 수준의 분배일과 공존 가능하므로"
(operative `< 5` 리터럴은 1개 유지 — 교차 가드 무영향 확인).

- [ ] **Step 3: 통과 확인** — `uv run pytest tests/test_prompt_trigger_gates.py tests/test_prompt_threshold_drift.py -v` 전체 PASS

- [ ] **Step 4: 커밋**

### Task 3: checklist 이력 + 전체 회귀 + PR

- [ ] 적용 이력 append(시간순 말미) → `uv run pytest tests/ -q` 실패 0 → 커밋 → PR(Closes #29, C §7 전제 정합 복원·백스톱 선택 항목 명기)

## Self-Review 체크
1. 커버리지: 옆문 2곳 게이트 ✓ / 사본 미증가 강제 ✓ / A측 스코핑 ✓ / 산문 정리 ✓ / checklist 맵 ✓.
2. Placeholder 없음 ✓. 3. 명칭 일관(_b_sibling_blocks·flag·게이트명) ✓.
