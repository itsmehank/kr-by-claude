# LLM 출력 store 검증 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM 분류/트리거 결과 저장 시 classification·decision 을 유효 enum 으로 검증(아니면 거부), risk_flags 를 14종 화이트리스트로 정제(밖이면 drop+경고).

**Architecture:** 14종 화이트리스트 상수(신규 `risk_flags.py`) + store.py 검증 헬퍼 3개(`_validate_classification`/`_validate_decision`/`_clean_risk_flags`)를 `insert_classification`·`insert_backfill_classification`·`insert_trigger_log` 에 적용. 검증은 gates 적용 전(맨 앞), risk_flags 정제는 INSERT 시점.

**Tech Stack:** Python, pytest (+pytest-mock).

---

## 배경 / 스펙 근거

스펙: `docs/superpowers/specs/2026-06-07-llm-output-store-validation-design.md`.

실측(store.py):
- `insert_classification(conn, *, symbol, classified_at, market, result, source, llm_meta, analyzed_for_date=None)`: 맨 앞 `_original = copy.deepcopy(result)` → `apply_phase1_gates(conn, symbol, classified_at, result)`(fail-soft try/except; gates 가 result 의 classification 강등·risk_flags 에 handle_quality 추가 가능) → INSERT 에 `result["classification"]`(하드), `json.dumps(result.get("risk_flags", []))`.
- `insert_backfill_classification(conn, *, symbol, classified_at, market, result, source, llm_meta)`: 동일 패턴(gates → INSERT `result["classification"]` 하드 + risk_flags). `classification_backfill` 테이블.
- `insert_trigger_log(conn, *, symbol, evaluated_at, trigger_type, close, volume, pivot_price, result, prior_classification_at, llm_meta)`: INSERT 에 `result["decision"]`(하드). gates 없음.
- store.py 상단: `import copy, logging, json`; `log = logging.getLogger(__name__)`; `from kr_pipeline.llm_runner.gates import apply_phase1_gates`.
- gates(`gates.py`)는 risk_flags 에 `handle_quality`(화이트리스트 내)만 추가 → INSERT 시 정제해도 안전.
- 유효값: classification ∈ {entry,watch,ignore}(프롬프트 §310; disqualified 는 `insert_disqualification` 별도 경로), decision ∈ {go_now,wait,abort}. risk_flags 14종(스펙).
- 호출부 try/except: daily_delta(:94)·weekend(:139)→insert_classification, backfill 배치루프(:75)→insert_backfill_classification, evaluate_pivot(:66)→insert_trigger_log. dry-run 은 insert skip.

**비목표:** 숫자 sanity, 프롬프트 변경, 자동 보정.

---

### Task 1: risk_flags 화이트리스트 + 검증 헬퍼 3개 (순수)

**Files:**
- Create: `kr_pipeline/llm_runner/risk_flags.py`
- Modify: `kr_pipeline/llm_runner/store.py` (헬퍼 3개 추가)
- Test: `tests/test_llm_runner_store.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_runner_store.py` 에 추가:

```python
def test_risk_flags_taxonomy_has_14():
    from kr_pipeline.llm_runner.risk_flags import RISK_FLAGS_TAXONOMY
    assert len(RISK_FLAGS_TAXONOMY) == 14
    assert "climax_run" in RISK_FLAGS_TAXONOMY and "handle_quality" in RISK_FLAGS_TAXONOMY


def test_validate_classification():
    from kr_pipeline.llm_runner.store import _validate_classification
    import pytest
    assert _validate_classification({"classification": "entry"}) == "entry"
    assert _validate_classification({"classification": "watch"}) == "watch"
    for bad in ({"classification": "buy"}, {}, {"classification": None}):
        with pytest.raises(ValueError, match="invalid classification"):
            _validate_classification(bad)


def test_validate_decision():
    from kr_pipeline.llm_runner.store import _validate_decision
    import pytest
    assert _validate_decision({"decision": "go_now"}) == "go_now"
    for bad in ({"decision": "maybe"}, {}, {"decision": None}):
        with pytest.raises(ValueError, match="invalid decision"):
            _validate_decision(bad)


def test_clean_risk_flags():
    from kr_pipeline.llm_runner.store import _clean_risk_flags
    assert _clean_risk_flags(["climax_run", "bogus", "narrow_base"]) == ["climax_run", "narrow_base"]
    assert _clean_risk_flags([]) == []
    assert _clean_risk_flags(None) == []
    assert _clean_risk_flags("climax_run") == []   # 비 list
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_llm_runner_store.py -k "taxonomy or validate_ or clean_risk" -v`
Expected: FAIL (no module risk_flags / no helpers).

- [ ] **Step 3: 구현**
- `kr_pipeline/llm_runner/risk_flags.py` (신규):
```python
"""LLM risk_flags 허용 taxonomy (검증 SSOT).

prompts/analyze_chart_v3.md §taxonomy 와 수동 동기화 — 추가/삭제 시 양쪽.
"""
RISK_FLAGS_TAXONOMY = frozenset({
    "climax_run", "late_stage_base", "extended_from_ma", "faulty_pivot",
    "low_volume_breakout", "narrow_base", "wide_and_loose", "thin_liquidity_us_only",
    "prior_uptrend_insufficient", "volume_contraction_on_advance",
    "reverse_split_distortion", "unfavorable_market_context",
    "etf_methodology_mismatch", "handle_quality",
})  # 14종
```
- `store.py`: 상단 import 에 `from kr_pipeline.llm_runner.risk_flags import RISK_FLAGS_TAXONOMY` 추가. 헬퍼 3개 추가(예: insert_classification 위):
```python
_VALID_CLASSIFICATIONS = frozenset({"entry", "watch", "ignore"})
_VALID_DECISIONS = frozenset({"go_now", "wait", "abort"})


def _validate_classification(result: dict) -> str:
    c = result.get("classification")
    if c not in _VALID_CLASSIFICATIONS:
        raise ValueError(f"invalid classification: {c!r} (expected entry/watch/ignore)")
    return c


def _validate_decision(result: dict) -> str:
    d = result.get("decision")
    if d not in _VALID_DECISIONS:
        raise ValueError(f"invalid decision: {d!r} (expected go_now/wait/abort)")
    return d


def _clean_risk_flags(flags) -> list[str]:
    """RISK_FLAGS_TAXONOMY 밖 값 drop + log.warning. None/비list → []."""
    if not isinstance(flags, list):
        return []
    cleaned, dropped = [], []
    for f in flags:
        (cleaned if f in RISK_FLAGS_TAXONOMY else dropped).append(f)
    if dropped:
        log.warning("dropped unknown risk_flags: %s", dropped)
    return cleaned
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_llm_runner_store.py -k "taxonomy or validate_ or clean_risk" -v` → 4 passed.

- [ ] **Step 5: 커밋**
```bash
git add kr_pipeline/llm_runner/risk_flags.py kr_pipeline/llm_runner/store.py tests/test_llm_runner_store.py
git commit -m "feat(llm): risk_flags 14종 화이트리스트 + classification/decision/risk_flags 검증 헬퍼"
```

---

### Task 2: 3개 insert 함수에 검증 적용 + 와이어링 테스트

**Files:**
- Modify: `kr_pipeline/llm_runner/store.py` (insert_classification, insert_backfill_classification, insert_trigger_log)
- Test: `tests/test_llm_runner_store.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_runner_store.py` 에 추가(mock conn — 검증이 gates/cursor 전에 일어나 DB 불필요):

```python
def test_insert_classification_rejects_invalid(mocker):
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_classification
    import pytest
    conn = mocker.MagicMock()
    with pytest.raises(ValueError, match="invalid classification"):
        insert_classification(
            conn, symbol="X", classified_at=datetime(2026,6,7,tzinfo=timezone.utc),
            market="KOSPI", result={"classification": "buy"},
            source="daily_delta", llm_meta={},
        )
    conn.cursor.assert_not_called()   # 검증이 gates/INSERT 전 → DB 미접근


def test_insert_backfill_classification_rejects_invalid(mocker):
    from datetime import datetime, timezone, date
    from kr_pipeline.llm_runner.store import insert_backfill_classification
    import pytest
    conn = mocker.MagicMock()
    now = datetime(2026,6,7,tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="invalid classification"):
        insert_backfill_classification(
            conn, symbol="X", classified_at=now, market="KOSPI",
            result={"classification": "buy"}, source="backfill", llm_meta={},
            analyzed_for_date=date(2026,6,7),
        )
    conn.cursor.assert_not_called()   # backfill 도 검증이 gates/INSERT 전 → 와이어링 보장


def test_insert_trigger_log_rejects_invalid_decision(mocker):
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_trigger_log
    import pytest
    conn = mocker.MagicMock()
    now = datetime(2026,6,7,tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="invalid decision"):
        insert_trigger_log(
            conn, symbol="X", evaluated_at=now, trigger_type="breakout",
            close=100.0, volume=1000, pivot_price=99.0,
            result={}, prior_classification_at=now, llm_meta={},
        )
    conn.cursor.assert_not_called()
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_llm_runner_store.py -k "rejects_invalid" -v`
Expected: 3개 FAIL — 현재는 검증 없이 진행 → ValueError 안 남(insert_classification/backfill 은 gates 가 mock conn.cursor 접근·fail-soft 후 INSERT 시도; insert_trigger_log 는 result["decision"] KeyError 로 match 불일치). (3개: classification·backfill·trigger_log 와이어링)

- [ ] **Step 3: 구현**
- `insert_classification`: 함수 **맨 앞**(`_original = copy.deepcopy(result)` 이전)에 `_validate_classification(result)` 추가. INSERT 의 `result["classification"]` 는 그대로 두되(post-gate, 유효 보장), risk_flags 저장을 `json.dumps(_clean_risk_flags(result.get("risk_flags", [])))` 로 교체.
- `insert_backfill_classification`: 동일 — 맨 앞 `_validate_classification(result)`, INSERT risk_flags 를 `json.dumps(_clean_risk_flags(result.get("risk_flags", [])))` 로.
- `insert_trigger_log`: 함수 맨 앞(cursor 전)에 `_validate_decision(result)`. INSERT 의 `result["decision"]` → 검증 반환값 사용(또는 그대로 — 이미 유효 보장). 권장: `decision = _validate_decision(result)` 후 INSERT 에서 `decision` 사용.

> 배치: classification 검증은 gates 전(garbage 를 게이트가 처리하기 전 거부; gates 강등은 valid→valid 라 post-gate 도 유효). risk_flags 정제는 INSERT 시점(gates 가 추가한 handle_quality 포함 정제 — 화이트리스트 내라 보존).

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_llm_runner_store.py -k "rejects_invalid or taxonomy or validate_ or clean_risk" -v` → PASS. 기존 store 테스트(`test_insert_classification*`, `test_insert_entry_params` 등)도 유효값 사용이라 통과 확인: `uv run pytest tests/test_llm_runner_store.py tests/test_llm_store_load.py -v`(사전 baseline 실패 제외 신규 0).

- [ ] **Step 5: 커밋**
```bash
git add kr_pipeline/llm_runner/store.py tests/test_llm_runner_store.py
git commit -m "feat(llm): insert_classification/backfill/trigger_log 검증 적용 (거부 + risk_flags 정제)"
```

---

### Task 3: 회귀

**Files:** 없음(검증)

- [ ] **Step 1: 변경영역 + 인접**
```bash
uv run pytest tests/test_llm_runner_store.py tests/test_llm_store_load.py tests/test_store_phase1_gate.py tests/test_llm_claude_cli.py -v
```
Expected: 신규 + 기존 PASS(사전 baseline 실패 — expires_at/UniqueViolation — 제외 신규 0).

- [ ] **Step 2: 전체 회귀 base 대비**
```bash
uv run pytest tests/ -q 2>&1 | grep "^FAILED" | sed 's/ -.*//' | sort > /tmp/v_head.txt
wc -l < /tmp/v_head.txt
```
Expected: base(`git merge-base HEAD main`)의 사전 실패 수와 동일 — 신규 회귀 0. 다르면 `comm -23` 로 식별 후 수정.

- [ ] **Step 3: 최종 커밋(없으면 skip)**

---

## Self-Review

**1. Spec coverage:**
- risk_flags 14종 상수(SSOT) + _clean_risk_flags: Task 1 ✓
- classification/decision 검증 헬퍼: Task 1 ✓
- insert_classification·insert_backfill_classification·insert_trigger_log 적용: Task 2 ✓
- 거부=ValueError(호출부 try/except 로그+rollback): Task 2 와이어링 테스트 3개(classification·backfill·trigger_log, mock conn, cursor 미접근) ✓ — backfill 테스트가 그 함수 와이어링 누락 방지
- risk_flags 정제(gates 후 INSERT 시점, handle_quality 보존): Task 2 ✓
- 회귀 0: Task 3 ✓

**2. Placeholder scan:** 모든 코드 스텝에 실제 코드/명령/기대. 와이어링 테스트는 mock conn 으로 DB/gates 없이 거부만 검증(gates+DB 무거운 픽스처 회피 — 헬퍼 순수 단위 + 거부 경로가 핵심). Task 3 `<base>` 는 `git merge-base HEAD main`.

**3. Type consistency:** `RISK_FLAGS_TAXONOMY`(risk_flags.py) ↔ store import ↔ _clean_risk_flags 일관. `_validate_classification/_validate_decision` 반환 str ↔ INSERT 사용 일관. 헬퍼는 Task 1 정의·Task 2 사용(같은 파일).

**알려진 한계(의도적):** 숫자 sanity 미포함(별도). classification 검증은 raw LLM 값 기준(gates 전); gates 강등은 valid 내라 post-gate 도 유효. dry-run 은 insert skip 이라 헬퍼는 단위테스트로 커버.
