# entry_params 계약 버그 수정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (6) calculate_entry_params 가 실 LLM(§9) 출력으로 entry_params 에 정상 저장되게 한다(현재 0행). 정규화 계층으로 §9→저장 컬럼 매핑·파생, §9-only 5필드 컬럼 추가, mock 을 §9 로 정렬.

**Architecture:** store.py 에 §9→저장 dict 변환 순수 함수 `_normalize_entry_params` 추가(리네임·파생·검증). schema.sql 에 5컬럼(+idempotent ALTER). mock 을 §9 스키마로 교체하고 dry-run 분기에서 정규화 검증.

**Tech Stack:** Python (psycopg3), pytest auto-rollback `db` 픽스처. schema = `kr_pipeline/db/schema.sql` (conftest 가 kr_test 에 `psql -f` 적용).

---

## 배경 / 스펙 근거

스펙: `docs/superpowers/specs/2026-06-07-entry-params-contract-fix-design.md`.

실측:
- `store.insert_entry_params`(`store.py:239-300`)가 14개 키를 하드인덱싱. 6개가 §9 불일치(2 리네임 `stop_loss`↔`stop_loss_price`/`position_size_pct`↔`suggested_weight_pct`, 4 부재 `entry_price`/`stop_loss_basis`/`risk_reward_ratio`/`position_size_basis`). 실 LLM §9 응답 → `result["entry_price"]` KeyError → 종목별 try/except(`entry_params.py:75-78`)에 삼켜짐 → **0행**.
- dry-run 은 INSERT 자체 skip(`entry_params.py:95-97` "skipping DB insert" 후 return). mock(`claude_cli.py:86-110`)은 코드 키명 사용.
- `entry_params` 컬럼(schema.sql:340~): symbol/signal_at(PK), entry_mode, trigger_price, entry_price, stop_loss, stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, stop_loss_basis, expected_target_price, expected_target_pct, risk_reward_ratio**(NUMERIC(5,2))**, position_size_pct, position_size_basis, breakout_volume_requirement, observed_breakout_volume_ratio, known_warnings(JSONB), other_warnings, notes, trigger_evaluation_at, prior_classification_at, llm_*, created_at. **신규 5컬럼 없음. stocks FK 없음**(라운드트립 시드 단순).
- §9 출력(17필드, `calculate_entry_params_v2_0.md:396-419`): entry_mode, pivot_price, trigger_price, current_price, stop_loss_price, stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, suggested_weight_pct, expected_target_price, expected_target_pct, pattern_basis, entry_window_days, max_chase_pct_from_pivot, breakout_volume_requirement, observed_breakout_volume_ratio, notes, known_warnings, other_warnings.
- `store.py` 상단에 `import json` 있음. `insert_entry_params(conn, *, symbol, signal_at, result, trigger_evaluation_at, prior_classification_at, llm_meta)`.

**비목표:** 프롬프트 §9 변경, 기존행 마이그레이션, 5컬럼 signals.py/web 노출, 타 LLM 단계 허점.

---

### Task 1: `_normalize_entry_params` 순수 함수 (매핑·파생·검증)

**Files:**
- Modify: `kr_pipeline/llm_runner/store.py` (신규 함수, DB 불필요)
- Test: `tests/test_llm_runner_store.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_runner_store.py` 에 추가:

```python
def _s9_result(**over):
    r = {
        "entry_mode": "pivot_breakout", "pivot_price": 192.50, "trigger_price": 192.69,
        "current_price": 192.30, "stop_loss_price": 178.96,
        "stop_loss_pct_from_pivot": -7.0, "stop_loss_pct_from_current_price": -6.9,
        "suggested_weight_pct": 10.0, "expected_target_price": 231.00, "expected_target_pct": 20.0,
        "pattern_basis": "flat_base", "entry_window_days": 3, "max_chase_pct_from_pivot": 5.0,
        "breakout_volume_requirement": "ge_1.4x_50day_avg", "observed_breakout_volume_ratio": None,
        "known_warnings": [], "other_warnings": "", "notes": "n",
    }
    r.update(over)
    return r


def test_normalize_entry_params_maps_and_derives():
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    n = _normalize_entry_params(_s9_result())
    assert n["stop_loss"] == 178.96               # 리네임 stop_loss_price
    assert n["position_size_pct"] == 10.0         # 리네임 suggested_weight_pct
    assert n["entry_price"] == 192.69             # 파생 = trigger_price
    assert round(n["risk_reward_ratio"], 2) == round(20.0 / 6.9, 2)  # 계산
    assert n["stop_loss_basis"] is None and n["position_size_basis"] is None
    assert n["pivot_price"] == 192.50 and n["current_price"] == 192.30
    assert n["pattern_basis"] == "flat_base" and n["entry_window_days"] == 3
    assert n["max_chase_pct_from_pivot"] == 5.0
    assert n["observed_breakout_volume_ratio"] is None  # null 허용


def test_normalize_entry_params_missing_field_raises():
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    bad = _s9_result()
    del bad["stop_loss_price"]
    import pytest
    with pytest.raises(ValueError, match="schema drift"):
        _normalize_entry_params(bad)


def test_normalize_entry_params_rr_zero_and_overflow():
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    assert _normalize_entry_params(_s9_result(stop_loss_pct_from_current_price=0))["risk_reward_ratio"] is None
    # 비정상 손절 0.01% → 20/0.01=2000 > NUMERIC(5,2) 범위 → None
    assert _normalize_entry_params(_s9_result(stop_loss_pct_from_current_price=-0.01))["risk_reward_ratio"] is None
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_llm_runner_store.py -k normalize -v` → FAIL (no `_normalize_entry_params`).

- [ ] **Step 3: 구현** — `store.py` 에 추가(예: `insert_entry_params` 위):

```python
_ENTRY_PARAMS_REQUIRED = (
    "entry_mode", "pivot_price", "trigger_price", "current_price",
    "stop_loss_price", "stop_loss_pct_from_pivot", "stop_loss_pct_from_current_price",
    "suggested_weight_pct", "expected_target_price", "expected_target_pct",
    "pattern_basis", "entry_window_days", "max_chase_pct_from_pivot",
    "breakout_volume_requirement", "observed_breakout_volume_ratio",
)


def _normalize_entry_params(result: dict) -> dict:
    """§9 LLM 출력 → entry_params 저장용 dict.

    리네임(stop_loss_price→stop_loss, suggested_weight_pct→position_size_pct),
    파생(entry_price=trigger_price, risk_reward_ratio 계산), §9 부재 메타는 None.
    필수 §9 키 누락 시 ValueError(조용한 0행 방지).
    """
    for k in _ENTRY_PARAMS_REQUIRED:
        if k not in result:
            raise ValueError(f"entry_params schema drift: missing §9 field '{k}'")
    target_pct = result["expected_target_pct"]
    stop_pct = result["stop_loss_pct_from_current_price"]
    rr = None
    if target_pct is not None and stop_pct not in (None, 0):
        rr = target_pct / abs(stop_pct)
        if abs(rr) >= 1000:  # NUMERIC(5,2) 범위 밖 → 오버플로(=조용한 실패) 방지
            rr = None
    return {
        "entry_mode": result["entry_mode"],
        "pivot_price": result["pivot_price"],
        "trigger_price": result["trigger_price"],
        "current_price": result["current_price"],
        "entry_price": result["trigger_price"],            # 파생: §1.1 "보통 trigger_price"
        "stop_loss": result["stop_loss_price"],            # 리네임
        "stop_loss_pct_from_pivot": result["stop_loss_pct_from_pivot"],
        "stop_loss_pct_from_current_price": result["stop_loss_pct_from_current_price"],
        "stop_loss_basis": None,
        "expected_target_price": result["expected_target_price"],
        "expected_target_pct": result["expected_target_pct"],
        "risk_reward_ratio": rr,
        "position_size_pct": result["suggested_weight_pct"],  # 리네임
        "position_size_basis": None,
        "pattern_basis": result["pattern_basis"],
        "entry_window_days": result["entry_window_days"],
        "max_chase_pct_from_pivot": result["max_chase_pct_from_pivot"],
        "breakout_volume_requirement": result["breakout_volume_requirement"],
        "observed_breakout_volume_ratio": result["observed_breakout_volume_ratio"],
        "known_warnings": result.get("known_warnings", []),
        "other_warnings": result.get("other_warnings"),
        "notes": result.get("notes"),
    }
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_llm_runner_store.py -k normalize -v` → 3 passed.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/store.py tests/test_llm_runner_store.py
git commit -m "feat(llm): _normalize_entry_params — §9→저장 매핑·파생·검증"
```

---

### Task 2: schema.sql 5컬럼 추가 (CREATE + idempotent ALTER) + kr_test 적용

**Files:**
- Modify: `kr_pipeline/db/schema.sql`

- [ ] **Step 1: CREATE TABLE 정의에 5컬럼 추가** — `entry_params` CREATE 블록에서 `entry_price NUMERIC(12,4),` 다음 줄 부근에 추가:

```sql
  pivot_price                             NUMERIC(12, 4),
  current_price                           NUMERIC(12, 4),
```

그리고 `position_size_basis TEXT,` 다음(또는 논리적 위치)에:

```sql
  pattern_basis                           VARCHAR(30),
  entry_window_days                       SMALLINT,
  max_chase_pct_from_pivot                NUMERIC(6, 2),
```

- [ ] **Step 2: idempotent ALTER 추가** — schema.sql 의 기존 ALTER 마이그레이션 블록(예: `:300` weekly_classification ALTER 근처 또는 entry_params CREATE 바로 뒤)에 추가:

```sql
ALTER TABLE entry_params ADD COLUMN IF NOT EXISTS pivot_price NUMERIC(12,4);
ALTER TABLE entry_params ADD COLUMN IF NOT EXISTS current_price NUMERIC(12,4);
ALTER TABLE entry_params ADD COLUMN IF NOT EXISTS pattern_basis VARCHAR(30);
ALTER TABLE entry_params ADD COLUMN IF NOT EXISTS entry_window_days SMALLINT;
ALTER TABLE entry_params ADD COLUMN IF NOT EXISTS max_chase_pct_from_pivot NUMERIC(6,2);
```

- [ ] **Step 3: kr_test 에 적용 + 컬럼 존재 확인**

Run:
```bash
psql "$TEST_DATABASE_URL" -f kr_pipeline/db/schema.sql
psql "$TEST_DATABASE_URL" -c "SELECT column_name FROM information_schema.columns WHERE table_name='entry_params' AND column_name IN ('pivot_price','current_price','pattern_basis','entry_window_days','max_chase_pct_from_pivot') ORDER BY column_name"
```
Expected: 5개 컬럼 모두 출력. (TEST_DATABASE_URL 미설정 시 `.env` 로드 후 재시도; conftest 도 세션 시작 시 동일 적용.)

- [ ] **Step 4: 커밋**

```bash
git add kr_pipeline/db/schema.sql
git commit -m "feat(llm): entry_params 5컬럼 추가 (pivot/current/pattern_basis/entry_window/max_chase) + ALTER"
```

> 프로덕션(kr_pipeline)은 머지 후 `psql -f kr_pipeline/db/schema.sql` 수동 적용 필요(메모리: schema 양쪽 DB 수동).

---

### Task 3: `insert_entry_params` 정규화 사용 + 신규 5컬럼 INSERT + 라운드트립 + 기존 테스트 §9 전환

**Files:**
- Modify: `kr_pipeline/llm_runner/store.py` (`insert_entry_params`)
- Test: `tests/test_llm_runner_store.py`(신규 라운드트립), `tests/test_llm_store_load.py`(**기존 test_insert_entry_params 를 §9 로 전환 — 안 하면 정규화 도입 후 ValueError 로 깨짐**)

> Task 2 의 schema(kr_test 적용)가 선행돼야 INSERT 가 성공.
> **주의**: 기존 `tests/test_llm_store_load.py:151 test_insert_entry_params` 는 result 를 **옛 코드 키(entry_price/stop_loss/...)** 로 넘긴다. 정규화 도입 시 §9 키 누락 ValueError → Step 1b 에서 §9 로 전환 필수.

- [ ] **Step 1: 실패 테스트(라운드트립) 작성** — `tests/test_llm_runner_store.py` 에 추가:

```python
def test_insert_entry_params_roundtrip_s9(db):
    from datetime import datetime, timezone
    from kr_pipeline.llm_runner.store import insert_entry_params
    now = datetime(2026, 6, 7, 1, 0, tzinfo=timezone.utc)
    insert_entry_params(
        db, symbol="RTRIP", signal_at=now, result=_s9_result(),
        trigger_evaluation_at=now, prior_classification_at=now,
        llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None},
    )
    # db.commit() 불필요: 같은 커넥션 내 INSERT 는 후속 SELECT 에 보임.
    # commit 하면 auto-rollback 격리가 깨져 테스트 DB 오염 → 하지 않는다.
    with db.cursor() as cur:
        cur.execute("""SELECT entry_price, stop_loss, position_size_pct, risk_reward_ratio,
                              pivot_price, current_price, pattern_basis, entry_window_days, max_chase_pct_from_pivot
                         FROM entry_params WHERE symbol='RTRIP' AND signal_at=%s""", (now,))
        row = cur.fetchone()
    assert row is not None                          # 0행 탈출 — §9 출력으로 저장됨
    assert float(row[0]) == 192.69                  # entry_price = trigger_price
    assert float(row[1]) == 178.96                  # stop_loss = stop_loss_price
    assert float(row[2]) == 10.0                    # position_size_pct = suggested_weight_pct
    assert round(float(row[3]), 2) == round(20.0/6.9, 2)  # risk_reward 계산
    assert float(row[4]) == 192.50 and float(row[5]) == 192.30
    assert row[6] == "flat_base" and row[7] == 3 and float(row[8]) == 5.0
```

- [ ] **Step 1b: 기존 test_insert_entry_params 를 §9 로 전환** — `tests/test_llm_store_load.py:151` 의 `result={...}` 를 §9 키로 교체하고 entry_price 단언을 trigger_price 기준으로 수정(파생 규칙). 교체 내용:

```python
        result={
            "entry_mode": "pivot_breakout",
            "pivot_price": 80.0,
            "trigger_price": 80.08,
            "current_price": 79.9,
            "stop_loss_price": 75.0,
            "stop_loss_pct_from_pivot": -6.25,
            "stop_loss_pct_from_current_price": -6.83,
            "suggested_weight_pct": 5.0,
            "expected_target_price": 95.0,
            "expected_target_pct": 18.0,
            "pattern_basis": "flat_base",
            "entry_window_days": 3,
            "max_chase_pct_from_pivot": 5.0,
            "breakout_volume_requirement": "1.4x",
            "observed_breakout_volume_ratio": 1.55,
            "known_warnings": [],
            "other_warnings": "",
            "notes": "test",
        },
```
그리고 말미 단언을 교체(entry_price = trigger_price 파생):
```python
        cur.execute("SELECT entry_mode, entry_price FROM entry_params WHERE symbol='EP1'")
        row = cur.fetchone()
    assert row[0] == "pivot_breakout"
    assert float(row[1]) == 80.08   # entry_price = trigger_price (파생)
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_llm_runner_store.py::test_insert_entry_params_roundtrip_s9 -v` → FAIL (현재 INSERT 가 `result["entry_price"]` KeyError; 신규 컬럼 미INSERT).

- [ ] **Step 3: 구현** — `insert_entry_params` 본문을 정규화 사용 + 신규 5컬럼 포함으로 교체:

```python
def insert_entry_params(
    conn: Connection, *, symbol, signal_at, result, trigger_evaluation_at,
    prior_classification_at, llm_meta,
) -> None:
    """entry_params 에 (6) 결과 INSERT (§9 → 정규화 → 저장)."""
    n = _normalize_entry_params(result)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO entry_params
              (symbol, signal_at,
               entry_mode, pivot_price, trigger_price, current_price, entry_price,
               stop_loss, stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, stop_loss_basis,
               expected_target_price, expected_target_pct, risk_reward_ratio,
               position_size_pct, position_size_basis,
               pattern_basis, entry_window_days, max_chase_pct_from_pivot,
               breakout_volume_requirement, observed_breakout_volume_ratio,
               known_warnings, other_warnings, notes,
               trigger_evaluation_at, prior_classification_at,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens)
            VALUES (%s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s)
            ON CONFLICT (symbol, signal_at) DO NOTHING
            """,
            (
                symbol, signal_at,
                n["entry_mode"], n["pivot_price"], n["trigger_price"], n["current_price"], n["entry_price"],
                n["stop_loss"], n["stop_loss_pct_from_pivot"], n["stop_loss_pct_from_current_price"], n["stop_loss_basis"],
                n["expected_target_price"], n["expected_target_pct"], n["risk_reward_ratio"],
                n["position_size_pct"], n["position_size_basis"],
                n["pattern_basis"], n["entry_window_days"], n["max_chase_pct_from_pivot"],
                n["breakout_volume_requirement"], n["observed_breakout_volume_ratio"],
                json.dumps(n["known_warnings"]), n["other_warnings"], n["notes"],
                trigger_evaluation_at, prior_classification_at,
                llm_meta.get("duration_s"), llm_meta.get("input_tokens"), llm_meta.get("output_tokens"),
            ),
        )
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_llm_runner_store.py tests/test_llm_store_load.py::test_insert_entry_params -v` → 라운드트립 + normalize + **전환된 기존 테스트** 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/store.py tests/test_llm_runner_store.py tests/test_llm_store_load.py
git commit -m "feat(llm): insert_entry_params 정규화 사용 + 신규 5컬럼 저장 (0행 탈출)"
```

---

### Task 4: mock → §9 스키마 + dry-run 정규화 검증

**Files:**
- Modify: `kr_pipeline/llm_runner/llm/claude_cli.py` (`_mock_calculate_entry_params`)
- Modify: `kr_pipeline/llm_runner/entry_params.py` (dry-run 분기)
- Test: `tests/test_llm_runner_store.py`(신규), `tests/test_llm_claude_cli.py`(**기존 test_call_claude_dry_run_returns_mock_6 단언을 §9 키로 전환 — 안 하면 mock §9 교체 후 깨짐**)

- [ ] **Step 1: 실패 테스트 작성** — mock 이 §9 키를 내고 정규화를 통과하는지:

```python
def test_mock_calculate_entry_params_passes_normalize():
    from kr_pipeline.llm_runner.llm.claude_cli import _mock_calculate_entry_params
    from kr_pipeline.llm_runner.store import _normalize_entry_params
    m = _mock_calculate_entry_params()
    # §9 필수 키 보유 → 정규화 성공(예외 없음)
    n = _normalize_entry_params(m)
    assert n["entry_price"] == m["trigger_price"]
    assert n["stop_loss"] == m["stop_loss_price"]
    # 코드 전용 키는 더 이상 안 냄
    assert "stop_loss" not in m and "suggested_weight_pct" in m
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_llm_runner_store.py::test_mock_calculate_entry_params_passes_normalize -v` → FAIL (현재 mock 은 §9 키(`stop_loss_price`/`suggested_weight_pct`/`pivot_price` 등) 없음 → `_normalize_entry_params` 가 ValueError).

- [ ] **Step 3: mock 을 §9 스키마로 교체** — `claude_cli.py` `_mock_calculate_entry_params` 를 §9 키만 내도록 교체:

```python
def _mock_calculate_entry_params() -> dict:
    pivot = round(random.uniform(50000, 100000), 0)
    trigger = round(pivot * 1.001, 2)
    stop = round(pivot * random.uniform(0.93, 0.95), 2)
    return {
        "entry_mode": random.choice(["pivot_breakout", "pocket_pivot"]),
        "pivot_price": pivot,
        "trigger_price": trigger,
        "current_price": round(pivot * random.uniform(0.99, 1.005), 2),
        "stop_loss_price": stop,
        "stop_loss_pct_from_pivot": round((stop - pivot) / pivot * 100, 2),
        "stop_loss_pct_from_current_price": round((stop - trigger) / trigger * 100, 2),
        "suggested_weight_pct": round(random.uniform(2, 10), 1),
        "expected_target_price": round(trigger * 1.20, 2),
        "expected_target_pct": 20.0,
        "pattern_basis": random.choice(["flat_base", "cup_with_handle"]),
        "entry_window_days": random.choice([2, 3, 5]),
        "max_chase_pct_from_pivot": 5.0,
        "breakout_volume_requirement": "ge_1.4x_50day_avg",
        "observed_breakout_volume_ratio": None,
        "known_warnings": [],
        "other_warnings": "",
        "notes": "dry-run mock entry params (§9 schema)",
    }
```

- [ ] **Step 4: dry-run 정규화 검증 추가** — `entry_params.py` 의 dry-run 분기(`:95-97`)를 교체. 상단 import 에 `from kr_pipeline.llm_runner.store import insert_entry_params, _normalize_entry_params` (기존 import 에 `_normalize_entry_params` 추가):

```python
    if dry_run:
        _normalize_entry_params(result)  # §9 정합 검증(드리프트 시 ValueError) — insert 는 skip
        log.info("dry-run: validated entry plan for %s (skipping DB insert)", symbol)
        return
```

- [ ] **Step 4b: 기존 claude_cli mock_6 테스트 §9 전환** — `tests/test_llm_claude_cli.py::test_call_claude_dry_run_returns_mock_6` 의 단언을 §9 키로 교체(mock §9 교체 후 `entry_price`/`stop_loss` 는 더 이상 없음):

```python
    assert "entry_mode" in result
    assert "stop_loss_price" in result
    assert "suggested_weight_pct" in result
    assert "pivot_price" in result
```

- [ ] **Step 5: 통과 확인** — `uv run pytest tests/test_llm_runner_store.py -k "mock or normalize or entry_params" tests/test_llm_claude_cli.py -v` → PASS(신규 + 전환된 기존 mock_6 포함).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/llm_runner/llm/claude_cli.py kr_pipeline/llm_runner/entry_params.py tests/test_llm_runner_store.py tests/test_llm_claude_cli.py
git commit -m "feat(llm): mock §9 스키마 정렬 + dry-run 정규화 검증 (계약 드리프트 노출)"
```

---

### Task 5: 회귀 + 소비자 무영향 확인

**Files:** 없음(검증)

- [ ] **Step 1: 변경영역 + 소비자 테스트**

Run:
```bash
uv run pytest tests/test_llm_runner_store.py tests/test_llm_store_load.py tests/test_store_phase1_gate.py tests/test_llm_performance.py tests/test_api_signals_performance.py -v
```
Expected: 신규 + 기존 PASS(또는 사전 baseline 실패만). signals/performance 테스트 통과로 무영향 확인.

- [ ] **Step 2: 전체 회귀 base 대비**

Run:
```bash
uv run pytest tests/ -q 2>&1 | grep "^FAILED" | sed 's/ -.*//' | sort > /tmp/ep_head.txt
wc -l < /tmp/ep_head.txt
```
Expected: 현재 main 사전 실패 수와 동일 — 신규 회귀 0. 다르면 base 와 `comm -23` 로 신규 실패 식별 후 수정. (schema ALTER 가 kr_test 에 적용돼 INSERT 성공해야 함 — Task 2 Step 3 선행.)

- [ ] **Step 3: 소비자 무변경 grep 확인**

Run:
```bash
git diff --name-only <base>..HEAD | grep -E "signals.py|performance.py|slack.py|calculate_entry_params_v2_0.md" || echo "(소비자 무변경 확인)"
```
Expected: `(소비자 무변경 확인)` — signals/performance/slack/prompt 미변경.

- [ ] **Step 4: 최종 커밋(없으면 skip)**

---

## Self-Review

**1. Spec coverage:**
- 정규화 계층(리네임·파생·risk_reward 계산·basis None·검증·RR 오버플로 가드): Task 1 ✓
- schema 5컬럼 + ALTER + kr_test 적용: Task 2 ✓
- insert_entry_params 정규화 사용 + 5컬럼 INSERT: Task 3 ✓
- mock §9 정렬 + dry-run 검증: Task 4 ✓
- 0행 탈출 결정적 증명(라운드트립): Task 3 Step 1 ✓
- 소비자 무영향(signals/performance/slack/web/prompt): Task 5 ✓
- **기존 테스트 깨짐 방지**: `test_llm_store_load.py::test_insert_entry_params`(옛 키→§9, Task 3 Step 1b), `test_llm_claude_cli.py::test_call_claude_dry_run_returns_mock_6`(옛 키 단언→§9, Task 4 Step 4b) — 둘 다 전환해 정규화/mock 변경으로 인한 신규 회귀 차단 ✓
- 회귀 0: Task 5 ✓

**2. Placeholder scan:** 모든 코드 스텝에 실제 코드/명령/기대. `<base>` 는 Task 5 Step 3 에서 실제 base SHA(브랜치 분기점)로 치환 — 구현자가 `git merge-base HEAD main` 로 확인.

**3. Type consistency:** `_normalize_entry_params` 반환 키 ↔ INSERT 컬럼·VALUES 순서 정합(Task 1↔3). `_s9_result` 헬퍼는 Task 1 에서 정의, Task 3·4 테스트가 재사용(같은 파일). mock 키집합 ↔ `_ENTRY_PARAMS_REQUIRED` 정합(Task 4↔1). risk_reward 계산식 일관(목표/|손절|, 범위 가드).

**알려진 한계(의도적):** entry_price=trigger_price(intraday 보정 없음), stop_loss_basis/position_size_basis=None, 5컬럼 API/web 미노출 — 전부 비목표(후속).
