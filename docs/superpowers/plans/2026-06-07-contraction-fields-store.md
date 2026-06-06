# contraction_* 출력 보존 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** analyze_chart_v3 의 VCP footprint 출력(contraction_count·contraction_depths_pct)을 measurements JSONB 보관 블록에 합쳐 저장(현재 버려짐).

**Architecture:** store.py 에 measurements + contraction_* 를 병합해 JSON 화하는 헬퍼 `_measurements_json` 추가, insert_classification·insert_backfill_classification 의 measurements 저장 라인을 그 헬퍼로 교체. 프롬프트·스키마 무변경.

**Tech Stack:** Python, pytest (auto-rollback `db` 픽스처).

---

## 배경 / 스펙 근거

스펙: `docs/superpowers/specs/2026-06-07-contraction-fields-store-design.md`.

실측:
- `contraction_count`(int)·`contraction_depths_pct`(% 배열)는 analyze_chart_v3 최상위 출력(프롬프트 §323-324). **코드에서 읽거나 저장 안 함**(전수 grep — web 문서 1곳 외 소비처 없음).
- `measurements`(nested object)는 `weekly_classification.measurements`/`classification_backfill.measurements` JSONB 에 저장(store.py:117·191): `json.dumps(result.get("measurements")) if result.get("measurements") is not None else None`.
- gates(`apply_phase1_gates`)는 저장 전 result 를 in-place 일부 키만 수정, measurements/contraction 미접근(확인) → contraction_* 보존.
- store.py 상단 `import json`. 기존 테스트 `test_measurements_column_exists_and_stores`(test_llm_runner_store.py:84): insert_classification 실 db 라운드트립, measurements 읽어 dict 단언(JSONB→dict).
- contraction_* 는 measurements 와 **별개 최상위 키** → 병합 시 충돌 없음.

**비목표:** 프롬프트/스키마 변경, measurements 소비자 추가, 별도 컬럼화.

---

### Task 1: `_measurements_json` 헬퍼 (병합·JSON화)

**Files:**
- Modify: `kr_pipeline/llm_runner/store.py` (헬퍼 추가)
- Test: `tests/test_llm_runner_store.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_runner_store.py` 에 추가:

```python
def test_measurements_json_merges_contraction():
    import json
    from kr_pipeline.llm_runner.store import _measurements_json
    # measurements + contraction 병합
    out = json.loads(_measurements_json({
        "measurements": {"cup_depth_pct": 30.0},
        "contraction_count": 4,
        "contraction_depths_pct": [25.0, 14.0, 8.0, 4.0],
    }))
    assert out["cup_depth_pct"] == 30.0
    assert out["contraction_count"] == 4
    assert out["contraction_depths_pct"] == [25.0, 14.0, 8.0, 4.0]


def test_measurements_json_measurements_only_unchanged():
    import json
    from kr_pipeline.llm_runner.store import _measurements_json
    out = json.loads(_measurements_json({"measurements": {"cup_depth_pct": 30.0}}))
    assert out == {"cup_depth_pct": 30.0}   # contraction 없으면 그대로


def test_measurements_json_none_when_empty():
    from kr_pipeline.llm_runner.store import _measurements_json
    assert _measurements_json({}) is None
    assert _measurements_json({"measurements": None}) is None


def test_measurements_json_contraction_only():
    import json
    from kr_pipeline.llm_runner.store import _measurements_json
    out = json.loads(_measurements_json({"contraction_count": 3, "contraction_depths_pct": [20.0, 10.0, 5.0]}))
    assert out == {"contraction_count": 3, "contraction_depths_pct": [20.0, 10.0, 5.0]}


def test_measurements_json_non_dict_measurements():
    import json
    from kr_pipeline.llm_runner.store import _measurements_json
    out = json.loads(_measurements_json({"measurements": "oops", "contraction_count": 2}))
    assert out == {"contraction_count": 2}   # 비-dict measurements 는 {} 기반
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_llm_runner_store.py -k measurements_json -v` → FAIL (no `_measurements_json`).

- [ ] **Step 3: 구현** — `store.py` 에 추가(예: insert_classification 위):

```python
def _measurements_json(result: dict) -> str | None:
    """measurements 블록에 최상위 contraction_count/contraction_depths_pct 를 병합해 JSON 문자열로.

    VCP footprint(최상위 출력)가 버려지지 않게 measurements 감사 블록에 합친다.
    measurements·contraction 둘 다 없으면 None(기존 None 동작 보존).
    """
    m = result.get("measurements")
    cc = result.get("contraction_count")
    cd = result.get("contraction_depths_pct")
    if m is None and cc is None and cd is None:
        return None
    blob = dict(m) if isinstance(m, dict) else {}
    if cc is not None:
        blob["contraction_count"] = cc
    if cd is not None:
        blob["contraction_depths_pct"] = cd
    return json.dumps(blob)
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_llm_runner_store.py -k measurements_json -v` → 5 passed.

- [ ] **Step 5: 커밋**
```bash
git add kr_pipeline/llm_runner/store.py tests/test_llm_runner_store.py
git commit -m "feat(llm): _measurements_json — measurements + contraction_* 병합"
```

---

### Task 2: 2개 insert 함수에 적용 + 라운드트립 테스트

**Files:**
- Modify: `kr_pipeline/llm_runner/store.py` (insert_classification:117, insert_backfill_classification:191)
- Test: `tests/test_llm_runner_store.py`

- [ ] **Step 1: 실패 테스트(라운드트립) 작성** — `tests/test_llm_runner_store.py` 에 추가(기존 `test_measurements_column_exists_and_stores` 패턴):

```python
def test_insert_classification_stores_contraction_in_measurements(db):
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_classification
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='CONTRACT'")
    db.commit()
    insert_classification(
        db, symbol="CONTRACT", classified_at=datetime(2026, 6, 7, tzinfo=timezone.utc),
        market="KOSPI",
        result={
            "classification": "watch", "pattern": "vcp", "confidence": 0.6,
            "reasoning": "x", "risk_flags": [],
            "pivot_price": None, "pivot_basis": None, "base_high": None,
            "base_low": None, "base_depth_pct": None, "base_start_date": None,
            "measurements": {"prior_uptrend_pct": 40.0},
            "contraction_count": 4,
            "contraction_depths_pct": [25.0, 14.0, 8.0, 4.0],
        },
        source="weekend", llm_meta={},
    )
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT measurements FROM weekly_classification WHERE symbol='CONTRACT'")
        m = cur.fetchone()[0]
    assert m["prior_uptrend_pct"] == 40.0
    assert m["contraction_count"] == 4
    assert m["contraction_depths_pct"] == [25.0, 14.0, 8.0, 4.0]
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_llm_runner_store.py::test_insert_classification_stores_contraction_in_measurements -v`
Expected: FAIL — 현재 measurements 만 저장(`json.dumps(result.get("measurements"))`) → 저장된 m 에 contraction_count 키 없음 → KeyError/assert 실패.

- [ ] **Step 3: 구현** — `store.py` 두 함수의 measurements 저장 값을 교체:
- `insert_classification`(:117): `json.dumps(result.get("measurements")) if result.get("measurements") is not None else None` → `_measurements_json(result)`.
- `insert_backfill_classification`(:191): 동일 교체.

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_llm_runner_store.py -k "contraction or measurements" -v`
Expected: 신규 라운드트립 + Task1 단위 + 기존 `test_measurements_column_exists_and_stores`(contraction 없음 → blob==measurements 동일) 모두 PASS.

- [ ] **Step 5: 커밋**
```bash
git add kr_pipeline/llm_runner/store.py tests/test_llm_runner_store.py
git commit -m "feat(llm): insert_classification/backfill measurements 에 contraction_* 합쳐 저장"
```

---

### Task 3: 회귀

**Files:** 없음(검증)

- [ ] **Step 1: 변경영역 + 인접**
```bash
uv run pytest tests/test_llm_runner_store.py tests/test_llm_store_load.py -v
```
Expected: 신규 + 기존 PASS(사전 baseline 실패 — expires_at/UniqueViolation — 제외 신규 0).

- [ ] **Step 2: 전체 회귀 base 대비**
```bash
uv run pytest tests/ -q 2>&1 | grep "^FAILED" | sed 's/ -.*//' | sort > /tmp/cf_head.txt
wc -l < /tmp/cf_head.txt
```
Expected: base(`git merge-base HEAD main`)의 사전 실패 수와 동일 — 신규 회귀 0.

- [ ] **Step 3: 최종 커밋(없으면 skip)**

---

## Self-Review

**1. Spec coverage:**
- `_measurements_json`(measurements + contraction 병합, 둘 다 없으면 None, 비-dict 처리): Task 1 ✓
- insert_classification·insert_backfill_classification 적용: Task 2 ✓
- contraction 저장 라운드트립: Task 2 ✓
- 기존 measurements 동작 보존(contraction 없음): Task 1 `measurements_only_unchanged` + Task 2 Step4 기존 테스트 ✓
- 회귀 0: Task 3 ✓

**2. Placeholder scan:** 모든 코드 스텝에 실제 코드/명령/기대. Task 3 `<base>` 는 `git merge-base HEAD main`.

**3. Type consistency:** `_measurements_json(result) -> str | None`(Task1) ↔ insert 적용(Task2) 일관. 반환 JSON 문자열 → INSERT 의 measurements(JSONB::text) 컬럼에 그대로(기존도 json.dumps 문자열 저장). 라운드트립은 JSONB→dict 로 읽어 단언.

**알려진 한계(의도적):** measurements 는 여전히 감사용(읽는 소비자 없음) — contraction 도 동일 위상으로 보존. 프롬프트/스키마 무변경.
