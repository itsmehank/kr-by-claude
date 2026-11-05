# #253 방향 한정 래칫 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 같은 베이스에서 pivot 이 낮게 재판독돼도 트리거가 쓰는 pivot(`effective_pivot`)이 내려가지 않게 한다.

**Architecture:** 저장 시 순수 함수 `ratchet_pivot` 이 직전 활성 행의 `COALESCE(effective_pivot, pivot_price)` 와 새 판독값을 비교해 `weekly_classification.effective_pivot` 에 기록한다. 소비처(활성 조회·payload 2곳·API)는 `COALESCE(effective_pivot, pivot_price)` 를 읽는다. LLM 입력·프롬프트·`pivot_price`·백테스트 경로는 불변.

**Tech Stack:** Python 3.14 / psycopg / pytest(kr_test) / FastAPI / React + vitest.

**Spec:** `docs/superpowers/specs/2026-11-05-issue253-pivot-ratchet-design.md`

## Global Constraints

- KRX 접촉 0: 테스트·스크립트 어디서도 pykrx 로그인 경로 없음(CLAUDE.md 운영 규칙 5).
- `git add` 는 명시 경로만, 브랜치 `issue253-pivot-ratchet`(worktree `.claude/worktrees/i253`), 커밋에 Co-Authored-By 금지.
- suite 판정 전 `pgrep -f pytest` 확인. 기대 0 failed · 1 skipped · 1 deselected.
- thresholds.py 상수 추가·변경 없음(스펙 §5 의존성 맵이 승인됨). 프롬프트(.md) 텍스트 변경 없음.
- 운영 DB 쓰기 없음(테스트는 kr_test 만, conftest 가 schema.sql 재적용). 운영 schema 적용은 배포 단계에서 사용자 승인.
- `pivot_price` 열과 `pivot_continuity` 기존 키는 어떤 경로에서도 바꾸지 않는다.

## Review Focus

1. 직전 행이 레거시(effective_pivot NULL) → 기준은 pivot_price 여야 하며 NULL 로 래칫이 무력화되면 안 된다. (Task 2 테스트)
2. 2주 연속 하향에서 두 번째 주도 첫 값을 유지해야 한다(저장 최신값이 아니라 직전 effective 비교). (Task 2 테스트)
3. `_pivot_continuity` 가 예외를 내면 effective = 새 값, INSERT 는 반드시 성공해야 한다(fail-soft). (Task 2 테스트)
4. payload `prior_analysis.pivot_price` 와 `get_active_monitoring.pivot_price` 가 서로 다른 값을 주면 게이트와 LLM 판정이 어긋난다 — 둘 다 effective. (Task 3 테스트)
5. API 응답에서 레거시 행은 `effective_pivot` null 이어야 하고 pivot_price 는 그대로여야 한다. (Task 5 테스트)

---

### Task 1: 순수 함수 `ratchet_pivot`

**Files:**
- Create: `kr_pipeline/llm_runner/compute/pivot_ratchet.py`
- Test: `tests/test_pivot_ratchet.py`

**Interfaces:**
- Produces: `ratchet_pivot(new_pivot: float | None, prev_effective: float | None, continuity: str | None, new_pattern: str | None) -> tuple[float | None, str]` — reason ∈ {`no_pivot`, `no_baseline`, `released`, `unknown`, `cheat_release`, `kept`, `accepted`}. 우선순위는 스펙 §3.1 표 순서. `continuity=None` = 직전 기준 없음.

- [ ] **Step 1: 실패 테스트 작성**

```python
import math, pytest
from kr_pipeline.llm_runner.compute.pivot_ratchet import ratchet_pivot

@pytest.mark.parametrize("new,prev,cont,pat,exp", [
    (None, 23650.0, "same", "cup_with_handle", (None, "no_pivot")),
    (float("nan"), 23650.0, "same", "cup_with_handle", (None, "no_pivot")),
    (22050.0, None, None, "cup_with_handle", (22050.0, "no_baseline")),
    (22050.0, None, "same", "cup_with_handle", (22050.0, "no_baseline")),
    (22050.0, 23650.0, "different", "cup_with_handle", (22050.0, "released")),
    (22050.0, 23650.0, "unknown", "cup_with_handle", (22050.0, "unknown")),
    (22050.0, 23650.0, "same", "3c_cheat", (22050.0, "cheat_release")),
    (22050.0, 23650.0, "same", "cup_with_handle", (23650.0, "kept")),
    (22050.0, 23650.0, "near", "cup_with_handle", (23650.0, "kept")),
    (23650.0, 23650.0, "same", "cup_with_handle", (23650.0, "accepted")),
    (23800.0, 23650.0, "same", "cup_with_handle", (23800.0, "accepted")),
])
def test_ratchet_pivot_table(new, prev, cont, pat, exp):
    assert ratchet_pivot(new, prev, cont, pat) == exp
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_pivot_ratchet.py -q` — Expected: ImportError (module missing).
- [ ] **Step 3: 구현** — `pivot_ratchet.py` 에 위 시그니처. 비유한값은 `math.isfinite` 로 걸러 `no_pivot`. docstring 에 스펙 §1 책 근거 태그(상향 수용 PRESERVES TTLC §7 / 하향 거부 [design-judgment] / cheat_release TLSMW pp.243–245) 1줄씩.
- [ ] **Step 4: 통과 확인** — Run: 같은 명령 — Expected: 11 passed.
- [ ] **Step 5: Commit** — `git add kr_pipeline/llm_runner/compute/pivot_ratchet.py tests/test_pivot_ratchet.py` → `feat(#253): ratchet_pivot 순수 함수 — same/near 하향 유지·상향 수용·different/unknown/cheat 해제`

---

### Task 2: 스키마 + 저장 경로 래칫

**Files:**
- Modify: `kr_pipeline/db/schema.sql` (weekly_classification ALTER 블록, `pivot_continuity` 추가 뒤)
- Modify: `kr_pipeline/llm_runner/store.py` — `_pivot_continuity`(SELECT 에 `COALESCE(effective_pivot, pivot_price)` 추가, 반환 dict 에 `prev_effective_pivot`), `insert_classification`(effective 산출·JSON 키 `ratchet`·INSERT 열·kept 경고)
- Test: `tests/test_llm_runner_store.py` (기존 `_insert_cls`·`_continuity_of`·`_clean_symbol`·`_gates_identity` 재사용, 새 섹션 `# ====== (#253) effective_pivot 래칫 ======`)

**Interfaces:**
- Consumes: Task 1 `ratchet_pivot`.
- Produces: `weekly_classification.effective_pivot NUMERIC(12,4)`; `pivot_continuity` JSON 추가 키 `prev_effective_pivot: float|None`, `ratchet: str`; `_pivot_continuity` 반환 dict 에 `prev_effective_pivot`.

- [ ] **Step 1: 실패 테스트 작성** (helper `_effective_of(db, symbol, at)` = `SELECT effective_pivot` 추가)

```python
def test_ratchet_keeps_prev_effective_across_two_lowered_weeks(db, mocker):
    """같은 베이스 23,650 → 22,050 → 22,050: 두 번째·세 번째 행 effective 모두 23,650 (체인 유지)."""
    _gates_identity(mocker); _clean_symbol(db, "RAT1")
    t = [datetime(2026, 8, d, 3, 0, tzinfo=timezone.utc) for d in (22, 29)] + [datetime(2026, 9, 5, 3, 0, tzinfo=timezone.utc)]
    _insert_cls(db, "RAT1", at=t[0], pivot=23650.1, base_start="2026-06-01", afd=date(2026, 8, 22))
    _insert_cls(db, "RAT1", at=t[1], pivot=22050.1, base_start="2026-06-01", afd=date(2026, 8, 29))
    _insert_cls(db, "RAT1", at=t[2], pivot=22050.1, base_start="2026-06-01", afd=date(2026, 9, 5))
    assert float(_effective_of(db, "RAT1", t[0])) == 23650.1
    assert float(_effective_of(db, "RAT1", t[1])) == 23650.1
    assert float(_effective_of(db, "RAT1", t[2])) == 23650.1
    c2 = _continuity_of(db, "RAT1", t[1])
    assert c2["ratchet"] == "kept" and c2["prev_effective_pivot"] == 23650.1
    assert c2["prev_pivot_price"] == 23650.1          # 기존 키 불변
    c3 = _continuity_of(db, "RAT1", t[2])
    assert c3["prev_pivot_price"] == 22050.1 and c3["prev_effective_pivot"] == 23650.1

def test_ratchet_accepts_higher_and_releases_on_different_base(db, mocker): ...
    # same 23,650 → 23,800 → effective 23,800 (accepted); 그 뒤 base_start 60일 뒤 22,000 → effective 22,000 (released)

def test_ratchet_unknown_uses_new_value(db, mocker): ...
    # 직전 base_start None(watch, pivot None) → 이번 22,050: effective 22,050, ratchet == "no_baseline" 또는 "unknown"(직전 pivot None 이면 no_baseline)

def test_ratchet_legacy_prev_row_uses_pivot_price(db, mocker): ...
    # 직전 행을 raw INSERT(effective_pivot NULL, pivot_price 23,650) 후 insert_classification 22,050 same → effective 23,650

def test_ratchet_prev_ignore_breaks_chain(db, mocker): ...
    # 23,650 → ignore(pivot None) → 22,050 same base: effective 22,050, ratchet "no_baseline"

def test_ratchet_fail_soft_when_continuity_raises(db, mocker): ...
    # 기존 test_continuity_fail_soft 패턴(_pivot_continuity poison) → 행 저장됨, effective == pivot_price, pivot_continuity NULL

def test_ratchet_kept_logs_warning(db, mocker, caplog): ...
    # caplog 에 "[pivot-ratchet] kept RATx" 1건
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_llm_runner_store.py -q -k ratchet` — Expected: FAIL `column "effective_pivot" does not exist`(conftest 가 현재 schema.sql 적용) 또는 KeyError `ratchet`.
- [ ] **Step 3: schema.sql** — 스펙 §4 블록 그대로 추가(`pivot_continuity` ALTER 바로 아래).
- [ ] **Step 4: store.py** — `_pivot_continuity` SELECT 에 `COALESCE(effective_pivot, pivot_price)` 6번째 컬럼, 반환 dict `prev_effective_pivot=_finite_or_none(...)`. `insert_classification` 에서 continuity 블록 뒤:
  ```python
  effective_pivot, ratchet = ratchet_pivot(
      _finite_or_none(result.get("pivot_price")),
      (continuity_info or {}).get("prev_effective_pivot"),
      (continuity_info or {}).get("base_continuity"),
      result.get("pattern"),
  )
  if continuity_info is not None:
      continuity_info["ratchet"] = ratchet
      pivot_continuity = json.dumps(continuity_info, allow_nan=False)
  ```
  INSERT 열·VALUES 에 `effective_pivot` 추가. `cur.rowcount == 1 and ratchet == "kept"` 면 `log.warning("[pivot-ratchet] kept %s: llm %s < effective %s (base=%s)", ...)`. 기존 same-base 경고는 그대로.
- [ ] **Step 5: 통과 확인** — Run: `uv run pytest tests/test_llm_runner_store.py -q` — Expected: 전부 passed(기존 continuity 테스트 포함).
- [ ] **Step 6: Commit** — `git add kr_pipeline/db/schema.sql kr_pipeline/llm_runner/store.py tests/test_llm_runner_store.py` → `feat(#253): weekly_classification.effective_pivot 열 + 저장 시 래칫(직전 COALESCE(effective, pivot_price) 비교, pivot_continuity.ratchet 기록, kept 경고)`

---

### Task 3: 소비처 전환 (활성 조회·payload 2곳)

**Files:**
- Modify: `kr_pipeline/llm_runner/load.py::get_active_monitoring` (SELECT `pivot_price` → `COALESCE(effective_pivot, pivot_price) AS pivot_price`)
- Modify: `kr_pipeline/llm_runner/compute/payload_lite.py` 직전 분류 SELECT 2곳(5b·6) 동일 치환. `_PRIOR_KEYS`·`prior_row` 주입 경로 불변.
- Test: `tests/test_issue253_consumers.py`

**Interfaces:**
- Consumes: Task 2 열.
- Produces: 변경 없음(키 이름 동일, 값만 effective).

- [ ] **Step 1: 실패 테스트 작성**

```python
def _seed_effective(cur, symbol, *, pivot, effective, today):
    # tests/test_breakout_from_watch_integration._seed_watch 와 같은 꼴 + effective_pivot 열, daily_indicators today 행(close=pivot+1, 거래량 2×)

def test_get_active_with_current_returns_effective_pivot(db):
    # pivot_price 22050, effective_pivot 23650 → rows["RATC1"]["pivot_price"] == 23650.0

def test_get_active_with_current_legacy_null_falls_back(db):
    # effective NULL → pivot_price 22050.0

def test_payload_5b_prior_analysis_uses_effective(db):
    # build_for_5b(또는 현 함수명) → payload["prior_analysis"]["pivot_price"] == 23650.0

def test_payload_6_prior_analysis_uses_effective(db):
    # entry params payload 빌더 → prior_analysis.pivot_price == 23650.0
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_issue253_consumers.py -q` — Expected: 4 failed (22050 != 23650).
- [ ] **Step 3: 구현** — 3개 SELECT 치환만.
- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_issue253_consumers.py tests/test_llm_store_load.py tests/test_breakout_from_watch_integration.py tests/test_llm_evaluate_pivot.py -q` — Expected: passed.
- [ ] **Step 5: Commit** — `feat(#253): 활성 조회·5b/6 payload 의 pivot 을 COALESCE(effective_pivot, pivot_price) 로 전환`

---

### Task 4: 049430 재현 통합 테스트

**Files:**
- Test: `tests/test_issue253_ratchet_replay.py`

**Interfaces:**
- Consumes: Task 2·3. `insert_classification`, `get_active_with_current`, `compute.trigger_gate.evaluate`.

- [ ] **Step 1: 실패 테스트 작성** (Task 2·3 이전 커밋에서 돌리면 실패해야 하므로 Task 4 는 Task 3 머지 후 바로 작성하되, RED 확인은 `git stash` 없이 `ratchet_pivot` 을 `mocker.patch` 로 "항상 새 값" 반환하게 해서 수행)

```python
def test_049430_chain_no_breakout_after_lowered_reread(db, mocker):
    """08-22 23,650 → 08-29 22,050(same base). 09-04/09-09/09-15 종가 22,450/22,650/22,500, 거래량 2×:
    evaluate_gate 결과가 'breakout_from_watch'/'breakout' 이 아니어야 한다 (promotion 또는 None)."""
    # insert_classification 2회(watch, watch_reason valid_base_awaiting_breakout, base_start 2026-06-01)
    # daily_indicators: 전일 close 22,000(피벗 이하), 각 날짜 close, volume 2,000,000, avg 1,000,000, sma_50 21,000
    # for d in dates: rows = get_active_with_current(db, as_of=d); trig = evaluate_gate(**필드) ; assert trig not in ("breakout", "breakout_from_watch")
    # 대조: mocker.patch("kr_pipeline.llm_runner.store.ratchet_pivot", return_value=(22050.0, "accepted")) 로 재삽입하면 'breakout_from_watch' 가 나온다 (RED 증빙)
```

- [ ] **Step 2: RED 확인** — Run: `uv run pytest tests/test_issue253_ratchet_replay.py -q` (patch 한 대조 케이스가 breakout_from_watch 를 내는지 먼저 단독 assert) — Expected: 대조 케이스 통과 = 래칫 없으면 발화함을 증명.
- [ ] **Step 3: 본 케이스 통과 확인** — Expected: 3개 날짜 전부 breakout 계열 아님.
- [ ] **Step 4: Commit** — `test(#253): 049430 하향 재판독 체인 재현 — 래칫 후 돌파 발화 0`

---

### Task 5: API·웹 노출

**Files:**
- Modify: `api/schemas/classification.py` — `ClassificationRow`·`ClassificationHistoryRow` 에 `effective_pivot: float | None = None`
- Modify: `api/routers/classifications.py` — 두 SELECT 에 `effective_pivot` 추가·row 매핑
- Modify: `web/src/lib/types.ts` — `Classification`·`ClassificationHistoryRow` 에 `effective_pivot?: number | null`
- Create: `web/src/lib/effectivePivot.ts` — `effectivePivotNote(pivot: number|null, effective: number|null|undefined): string | null` (둘 다 있고 다를 때만 `"트리거 기준 N원 (래칫)"`, 아니면 null)
- Test: `web/src/lib/effectivePivot.test.ts`, `tests/test_api_classifications.py`
- Modify: `web/src/components/panels/ClassificationCard.tsx` — Pivot 줄 아래 note 가 있을 때만 `<div className="text-faint">` 1줄

- [ ] **Step 1: 실패 테스트(API)** — seed 에 `effective_pivot` 열 추가(CLSTEST01 = 1200.0, 나머지 NULL):
```python
def test_effective_pivot_exposed_and_legacy_null(client, seed_classifications):
    rows = {r["symbol"]: r for r in client.get("/api/classifications?lookback_days=30").json()}
    assert rows["CLSTEST01"]["effective_pivot"] == 1200.0 and rows["CLSTEST01"]["pivot_price"] == 1000.0
    assert rows["CLSTEST03"]["effective_pivot"] is None
def test_history_includes_effective_pivot(client, seed_classifications):
    r = client.get("/api/classifications/history/CLSTEST01"); assert any(x.get("effective_pivot") == 1200.0 for x in r.json())
```
- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_api_classifications.py -q` — Expected: KeyError/None 불일치.
- [ ] **Step 3: 실패 테스트(web)** — `effectivePivot.test.ts`: (22050, 23650) → "트리거 기준 23,650원 (래칫)", (23650, 23650) → null, (22050, null) → null, (null, 23650) → null.
- [ ] **Step 4: 실패 확인** — Run: `cd web && npx vitest run src/lib/effectivePivot.test.ts` — Expected: 모듈 없음 실패.
- [ ] **Step 5: 구현** — 스키마·라우터·types·helper·카드 1줄.
- [ ] **Step 6: 통과 확인** — Run: `uv run pytest tests/test_api_classifications.py -q` → passed; `cd web && npx vitest run && npx tsc --noEmit` → 0 errors.
- [ ] **Step 7: Commit** — `feat(#253): API 분류 응답·웹 카드에 effective_pivot(트리거 기준) 노출 — 판독값과 다를 때만 표시`

---

### Task 6: 문서·태그 정리

**Files:**
- Modify: `docs/GLOSSARY.md` §7 "방향 한정 래칫(권고안, 미구현)" → 구현 설명(effective_pivot·kept 로그·049430 예), 변경 이력 1줄
- Modify: `docs/pivot-reanalysis-tradeoff.md` 후속 절 — 래칫 도입(#253) 1줄, 허용폭 게이트는 비채택 사유(숫자 임계 책 근거 없음)
- Modify: `kr_pipeline/llm_runner/store.py` `_BASE_NEAR_DAYS` 주석에 `[design-judgment]`(전문가 Q-5) 1줄
- Modify: `README.md` 운영 절 — 기존 DB 업그레이드 시 schema.sql 재적용 한 줄이 없으면 추가(IF NOT EXISTS 라 안전)

- [ ] **Step 1: 편집** (테스트 없음 — 문서·주석)
- [ ] **Step 2: 용어집 규칙 점검** — 비유 없음, 실제 값, `출처:` 유지.
- [ ] **Step 3: Commit** — `docs(#253): 용어집 §7 래칫 구현 반영, 트레이드오프 후속, _BASE_NEAR_DAYS design-judgment 태그`

---

### 완료 게이트

- [ ] `pgrep -f pytest` 비어 있음 확인 후 `uv run pytest tests/ -q` → 0 failed · 1 skipped · 1 deselected (로그는 scratchpad 로 리다이렉트).
- [ ] `cd web && npx vitest run && npx tsc --noEmit` 통과.
- [ ] `grep -rn "pivot_price" kr_pipeline api --include=*.py` 로 소비처 재확인: 스펙 §3.3 표 밖 신규 읽기 경로 없음.
  (실행 결과: 최초 grep 은 `kr_pipeline`만 봐 `api/services/review_builder.py` 를 놓쳤고 독립 리뷰 R1 이 발견 → Task 7 로 수리.)

### Task 7: /review 페이지 pivot 계단을 effective 로 (리뷰 R1 Important 1)

- Modify: `api/services/review_builder.py` `MERGED_ROWS_CTES.live` — `COALESCE(effective_pivot, pivot_price) AS pivot_price`(bf 는 그대로)
- Test: `tests/test_api_review_builder.py` — effective ≠ pivot 인 라이브 행이 effective 값으로 나오고, 백필 행·레거시 행은 pivot_price 그대로.
- [ ] PR 생성(본문: 스펙·plan 링크, 배포 순서 §7, "Closes" 금지, 끝에 🤖 Generated with [Claude Code](https://claude.com/claude-code)) → 독립 리뷰 → 머지는 사용자 지시.
