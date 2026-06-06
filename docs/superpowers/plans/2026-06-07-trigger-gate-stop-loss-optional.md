# 트리거 게이트 stop_loss 선택화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** base_low(stop_loss) 가 NULL 이어도 active 종목이 트리거 평가(breakout/promotion/sma_50 invalidation)에서 제외되지 않게 한다.

**Architecture:** trigger_gate.evaluate 의 stop_loss 를 `float | None` 으로 선택화(있을 때만 base_low invalidation), evaluate_pivot 입구 가드에서 stop_loss 필수 제거, load.py 의 오해 소지 기본값 정리.

**Tech Stack:** Python, pytest (+pytest-mock `mocker`).

---

## 배경 / 스펙 근거

스펙: `docs/superpowers/specs/2026-06-07-trigger-gate-stop-loss-optional-design.md`.

실측:
- `trigger_gate.py` `evaluate(*, close, pivot_price, volume, avg_volume_50d, stop_loss: float, sma_50, classification)` — invalidation: `if close < stop_loss: return "invalidation"`(첫째), `if close < sma_50: return "invalidation"`(둘째), 이후 breakout(entry: close>pivot+volume), promotion(watch).
- `evaluate_pivot.py run()` 입구 가드: `if not all(a.get(k) is not None for k in ("close","pivot_price","volume","avg_volume_50d","stop_loss","sma_50")): continue`. 통과 시 `evaluate_gate(close=a["close"], ..., stop_loss=a["stop_loss"], ...)`. trigger 후 `_process_one(conn, a, trig, ...)` → `build_for_5b(symbol)`(DB 에서 base_low 독립 조회; enriched stop_loss 안 씀). run 루프는 성공 시 `conn.commit()`.
- `load.py:139` `"stop_loss": a.get("base_low", 0)` — get_active_monitoring 이 base_low 키를 float/None 으로 항상 넣어 `, 0` 은 죽은 기본값.
- trigger_gate.evaluate 유일 호출자 = evaluate_pivot. 기존 `tests/test_llm_compute_trigger_gate.py`(7개)는 모두 stop_loss=양수 float.

**비목표:** breakout/promotion/sma_50 로직·base_low NOT NULL 강제·타 LLM 단계.

---

### Task 1: trigger_gate.evaluate — stop_loss 선택화

**Files:**
- Modify: `kr_pipeline/llm_runner/compute/trigger_gate.py`
- Test: `tests/test_llm_compute_trigger_gate.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_compute_trigger_gate.py` 에 추가:

```python
def test_stop_loss_none_skips_stop_invalidation_but_sma_still_fires():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    # stop_loss None: base_low invalidation 은 건너뛰되 close<sma_50 invalidation 은 발동
    assert evaluate(
        close=77000, pivot_price=80000, volume=900_000, avg_volume_50d=1_000_000,
        stop_loss=None, sma_50=78000, classification="entry",
    ) == "invalidation"   # close(77000) < sma_50(78000)


def test_stop_loss_none_allows_breakout():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    # stop_loss None 이어도 breakout(pivot 돌파+거래량) 정상 발동
    assert evaluate(
        close=82500, pivot_price=80000, volume=1_500_000, avg_volume_50d=1_000_000,
        stop_loss=None, sma_50=78000, classification="entry",
    ) == "breakout"


def test_stop_loss_none_no_false_invalidation():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    # stop_loss None + close 가 sma_50 위 + pivot 미돌파 → 트리거 없음(None). 옛 코드라면 close<None TypeError.
    assert evaluate(
        close=79000, pivot_price=80000, volume=900_000, avg_volume_50d=1_000_000,
        stop_loss=None, sma_50=78000, classification="entry",
    ) is None


def test_stop_loss_value_still_invalidates():
    """stop_loss 값 있으면 close<stop → invalidation (기존 동작 보존)."""
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    assert evaluate(
        close=75000, pivot_price=80000, volume=900_000, avg_volume_50d=1_000_000,
        stop_loss=76000, sma_50=70000, classification="entry",
    ) == "invalidation"
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_llm_compute_trigger_gate.py -k "stop_loss_none" -v`
Expected: FAIL — `TypeError: '<' not supported between instances of 'int' and 'NoneType'` (현재 `close < stop_loss` 가 None 비교).

- [ ] **Step 3: 구현** — `trigger_gate.py` `evaluate` 시그니처의 `stop_loss: float` → `stop_loss: float | None`, 첫 invalidation 조건 교체:

```python
    # 하향 트리거 우선 (베이스 깨짐이 더 critical)
    if stop_loss is not None and close < stop_loss:
        return "invalidation"
    if close < sma_50:
        return "invalidation"
```
(나머지 breakout/promotion 무변경.)

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_llm_compute_trigger_gate.py -v`
Expected: 신규 4 + 기존 7 = 11 PASS (기존은 stop_loss=양수라 불변).

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/compute/trigger_gate.py tests/test_llm_compute_trigger_gate.py
git commit -m "feat(llm): trigger_gate stop_loss 선택화 (base_low 없으면 그 invalidation만 skip)"
```

---

### Task 2: evaluate_pivot 가드에서 stop_loss 제거 + load.py 정리

**Files:**
- Modify: `kr_pipeline/llm_runner/evaluate_pivot.py` (입구 가드)
- Modify: `kr_pipeline/llm_runner/load.py:139`
- Test: `tests/test_llm_compute_trigger_gate.py`(또는 신규 `tests/test_evaluate_pivot_guard.py`)

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_evaluate_pivot_guard.py` (신규):

```python
"""evaluate_pivot 입구 가드 — base_low(stop_loss) NULL 종목이 제외되지 않음."""


def test_run_does_not_skip_null_stop_loss(mocker):
    import kr_pipeline.llm_runner.evaluate_pivot as ep
    # base_low NULL → stop_loss None, 그러나 pivot 등 존재 + breakout 조건
    active = [{
        "symbol": "X", "classification": "entry",
        "close": 82500, "pivot_price": 80000,
        "volume": 1_500_000, "avg_volume_50d": 1_000_000,
        "sma_50": 78000, "stop_loss": None,
    }]
    mocker.patch.object(ep, "get_active_with_current", return_value=active)
    proc = mocker.patch.object(ep, "_process_one")  # build_for_5b/LLM/DB 우회
    conn = mocker.MagicMock()  # conn.commit() no-op

    r = ep.run(conn=conn, dry_run=True)

    proc.assert_called_once()          # stop_loss None 이어도 skip 되지 않고 처리됨
    assert r["processed"] == 1
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_evaluate_pivot_guard.py -v`
Expected: FAIL — 현재 가드가 `stop_loss is not None` 요구 → ticker skip → `_process_one` 미호출(`proc.assert_called_once()` 실패, processed==0).

- [ ] **Step 3: 구현**
- `evaluate_pivot.py` 입구 가드의 필수 키 튜플에서 `"stop_loss"` 제거:
```python
        if not all(
            a.get(k) is not None
            for k in ("close", "pivot_price", "volume", "avg_volume_50d", "sma_50")
        ):
            continue
```
(이후 `evaluate_gate(..., stop_loss=a["stop_loss"], ...)` 호출은 그대로 — 키 항상 존재, None 가능, trigger_gate 가 None 처리.)
- `load.py:139` 의 `"stop_loss": a.get("base_low", 0)` → `"stop_loss": a.get("base_low")`.

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_evaluate_pivot_guard.py tests/test_llm_compute_trigger_gate.py -v`
Expected: 가드 테스트 + trigger_gate 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/evaluate_pivot.py kr_pipeline/llm_runner/load.py tests/test_evaluate_pivot_guard.py
git commit -m "feat(llm): evaluate_pivot 가드 stop_loss 제거 + load base_low 기본값 정리"
```

---

### Task 3: 회귀 확인

**Files:** 없음(검증)

- [ ] **Step 1: 변경영역 + 인접 테스트**

Run:
```bash
uv run pytest tests/test_llm_compute_trigger_gate.py tests/test_evaluate_pivot_guard.py tests/test_llm_store_load.py tests/test_api_triggers.py -v
```
Expected: 신규 + 기존 PASS(또는 사전 baseline 실패만 — test_llm_store_load 의 expires_at/UniqueViolation 류는 무관).

- [ ] **Step 2: 전체 회귀 base 대비**

Run:
```bash
uv run pytest tests/ -q 2>&1 | grep "^FAILED" | sed 's/ -.*//' | sort > /tmp/sl_head.txt
wc -l < /tmp/sl_head.txt
```
Expected: 현재 main 사전 실패 수와 동일 — 신규 회귀 0. 다르면 base(브랜치 분기점, `git merge-base HEAD main`)와 `comm -23` 로 신규 실패 식별 후 수정.

- [ ] **Step 3: 최종 커밋(없으면 skip)**

---

## Self-Review

**1. Spec coverage:**
- trigger_gate stop_loss 선택화(None 시 base_low invalidation skip, sma_50/breakout 유지): Task 1 ✓
- evaluate_pivot 가드 stop_loss 제거: Task 2 ✓
- load.py base_low 기본값 정리: Task 2 ✓
- 기존 동작 보존(stop_loss float→invalidation): Task 1 Step1 `test_stop_loss_value_still_invalidates` + 기존 7테스트 ✓
- base_low NULL+pivot 종목 미제외: Task 2 가드 테스트 ✓
- 회귀 0: Task 3 ✓

**2. Placeholder scan:** 모든 코드 스텝에 실제 코드/명령/기대. Task 2 테스트는 _process_one/get_active_with_current 를 mock 해 DB/LLM 없이 가드만 검증(heavy fixture 회피). Task 3 `<base>` 는 `git merge-base HEAD main` 으로 치환.

**3. Type consistency:** `stop_loss: float | None`(Task1) ↔ 가드/호출 `a["stop_loss"]`(None 가능, Task2) ↔ load `a.get("base_low")`(None 가능) 일관. evaluate 호출 키워드(close/pivot_price/volume/avg_volume_50d/stop_loss/sma_50/classification) 불변.

**알려진 한계(의도적):** 현재 라이브 영향 0(해당 종목 없음) — 예방적 수정. pivot_price NULL 종목은 종전대로 제외(올바름).
