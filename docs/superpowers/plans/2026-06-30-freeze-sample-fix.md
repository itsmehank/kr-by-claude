# 표본 드리프트 수정 — 사전등록 100종목 고정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 백테스트가 매 실행 라이브로 재계산하던 표본(`_sample`)을, 사전등록 문서의 **고정 100종목**으로 핀(pin)해 §2 위반(움직이는 표본)을 복구한다.

**Architecture:** `profitability_cli._sample()` = `draw_sample(build_frame(live))` 가 지표 드리프트로 흔들려 표본 100이 바뀌었다(동결문서와 32개 차이, 적재 103종목 중 14가 동결 밖). 사전등록 문서 `docs/superpowers/backtest-profitability-sample.md` 의 **100종목이 권위**다. 그 100을 커밋된 데이터 모듈로 동결하고, `_sample()` 이 그것을 반환하게 한다. `build_frame`/`draw_sample` 는 보존(동결 생성·테스트용)하되 런타임 경로는 동결 목록만 본다. 이미 적재된 out-of-sample 14종목은 잉여(분석이 동결 100으로 필터하므로 자동 제외). **주(week) 단위 드리프트는 이 수정 범위 밖** — 완료 후 민감도분석으로 처리(기합의).

**Tech Stack:** Python, pytest.

## Global Constraints

- **수정 범위**: `kr_pipeline/backtest/` 한정(새 모듈 + CLI 1곳). 운영 코드·지표 파이프라인 불변.
- **권위 = 사전등록 문서의 100종목** (`docs/superpowers/backtest-profitability-sample.md`, seed 20260623, 2026-06-23 커밋). 재추첨 금지(또 드리프트함).
- **적재분 보존**: 기존 1,775/103 행 삭제 안 함. 분석은 동결 100으로 필터(out-of-sample 14는 무시).
- **멱등 유지**: 백필은 동결 100 기준으로 미적재분만 채움(기존 skip 로직 그대로).
- 커밋 메시지에 Co-Authored-By trailer 금지.
- 회귀 판정: base↔HEAD 실패 수 비교(baseline 24). 새 실패 0.

---

### Task 1: 동결 표본 모듈 생성 (사전등록 100 핀)

**Files:**
- Create: `kr_pipeline/backtest/frozen_sample.py`
- Test: `tests/test_backtest_frozen_sample.py`

**Interfaces:**
- Produces: `FROZEN_SAMPLE: list[str]` (정렬된 100종목, 사전등록 문서 유래), `FROZEN_SEED = 20260623`(출처 기록용 상수).

- [ ] **Step 1: 사전등록 문서에서 100종목 추출(생성 보조)**

Run:
```bash
grep -oE '\b[0-9]{6}\b' docs/superpowers/backtest-profitability-sample.md | sort -u | wc -l
grep -oE '\b[0-9]{6}\b' docs/superpowers/backtest-profitability-sample.md | sort -u | tr '\n' ' '
```
Expected: `100` 개. 이 목록이 `FROZEN_SAMPLE` 의 원천.
**검증**: 추출 100개가 문서의 "100종목" 섹션과 일치하는지 육안 확인(문서에 6자리 숫자가 종목 외 없는지 — frame_size 1851/seed 등은 4·8자리라 미포함).

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# tests/test_backtest_frozen_sample.py
import re


def test_frozen_sample_is_100_unique_sorted():
    from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
    assert len(FROZEN_SAMPLE) == 100
    assert len(set(FROZEN_SAMPLE)) == 100
    assert FROZEN_SAMPLE == sorted(FROZEN_SAMPLE)
    assert all(re.fullmatch(r"\d{6}", t) for t in FROZEN_SAMPLE)


def test_frozen_sample_matches_preregistration_doc():
    """동결 목록이 사전등록 문서의 100종목과 정확히 일치(권위 보존)."""
    from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
    txt = open("docs/superpowers/backtest-profitability-sample.md").read()
    doc = sorted(set(re.findall(r"\b\d{6}\b", txt)))
    assert set(FROZEN_SAMPLE) == set(doc)
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/test_backtest_frozen_sample.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: 구현 — Step 1 추출 결과를 모듈에 박음**

```python
# kr_pipeline/backtest/frozen_sample.py
"""사전등록 동결 표본 — 백테스트 권위 종목 100.

출처: docs/superpowers/backtest-profitability-sample.md (seed 20260623, 2026-06-23 커밋).
배경: CLI _sample() 이 라이브 build_frame 재계산이라 지표 드리프트로 표본이 흔들렸다.
이 모듈이 단일 권위 — 런타임은 이 목록만 본다(재추첨·라이브재계산 금지).
"""
from __future__ import annotations

FROZEN_SEED = 20260623

FROZEN_SAMPLE: list[str] = [
    # ← Step 1 에서 추출한 100종목을 정렬해 그대로 나열
]
```
(Step 1 의 `sort -u` 출력 100개를 따옴표 리스트로 붙여넣는다.)

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_backtest_frozen_sample.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/backtest/frozen_sample.py tests/test_backtest_frozen_sample.py
git commit -m "feat(backtest): 사전등록 동결 표본 100종목 모듈(표본 드리프트 차단)"
```

---

### Task 2: `_sample()` 을 동결 목록으로 핀

**Files:**
- Modify: `kr_pipeline/backtest/profitability_cli.py` (`_sample`)
- Test: `tests/test_backtest_sample_pinned.py`

**Interfaces:**
- Consumes: `kr_pipeline.backtest.frozen_sample.FROZEN_SAMPLE`
- Produces: `_sample(conn)` 이 DB 상태와 무관하게 `FROZEN_SAMPLE`(복사본)을 반환. `cmd_backfill`/`cmd_analyze` 는 이를 통해 동결 100만 대상.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_backtest_sample_pinned.py
def test_sample_returns_frozen_regardless_of_db(db):
    from kr_pipeline.backtest.profitability_cli import _sample
    from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
    got = _sample(db)
    assert sorted(got) == sorted(FROZEN_SAMPLE)
    assert len(got) == 100
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_backtest_sample_pinned.py -v`
Expected: FAIL — 현재 `_sample` 은 라이브 `draw_sample(build_frame(...))` 라 동결과 불일치(드리프트로 32개 차이).

- [ ] **Step 3: 구현**

`profitability_cli.py` 의 import 에 추가:
```python
from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
```

기존 `_sample` 교체:
```python
def _sample(conn) -> list[str]:
    # 사전등록 동결 100종목 고정(라이브 build_frame 재계산 금지 — 지표 드리프트로
    # 표본이 흔들렸던 §2 위반 복구). cf. frozen_sample.py
    return list(FROZEN_SAMPLE)
```
또한 `cmd_sample`(`cli sample` 표시 명령)이 라이브 추첨을 보여주면 실제 백필이 쓰는 동결 100과 **다른 목록을 출력**해 혼란을 준다. `cmd_sample` 의 표본 산출도 `_sample` 경유로 바꾼다:
```python
def cmd_sample(conn) -> int:
    sample = _sample(conn)                      # 동결 100
    comp = sample_composition(conn, sample)
    frame = build_frame(conn, START, END)       # 참고용 라이브 frame 크기만 표시
    print(json.dumps({"seed": DEFAULT_SEED, "frame_size_live": len(frame),
                      "frozen": True, "sample": sample, "composition": comp},
                     ensure_ascii=False, indent=2))
    return 0
```
(`build_frame`/`draw_sample`/`DEFAULT_SEED` import 는 `cmd_sample` 이 여전히 써서 유지 — 미사용 import 안 됨. `cmd_backfill`/`cmd_analyze` 는 `_sample` 경유라 자동 동결.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_backtest_sample_pinned.py -v`
Expected: PASS

- [ ] **Step 5: 백테스트 회귀 확인**

Run: `uv run pytest tests/ -k "backtest" -q`
Expected: 새 테스트 PASS, 기존 backtest 테스트 불변.

- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/backtest/profitability_cli.py tests/test_backtest_sample_pinned.py
git commit -m "fix(backtest): _sample 을 동결 100종목으로 핀(라이브 재계산 제거)"
```

---

### Task 3: 동결 100 기준 현황 점검 + 재개 (실행 단계)

**Files:** 없음(실행). gapcheck 스크립트 재사용(`/tmp/bt_gapcheck.py` — 이제 `_sample` 이 동결이라 자동으로 동결 100 기준).

- [ ] **Step 1: 동결 100 기준 누락 점검**

Run: `uv run python /tmp/bt_gapcheck.py 2>&1 | tail -8`
Expected: 이제 "현재 qualifying" 이 **동결 100 기준**으로 계산됨. 누락(C) 출력 — 동결 100 중 채울 분량 확인. (out-of-sample 14는 더 이상 대상 아님.)

- [ ] **Step 2: 드리프트 잔존(B) 재측정 — 동결 100 기준**

Run: `uv run python /tmp/bt_drift_measure.py 2>&1 | tail -8`
Expected: B(분석했지만 동결100×현재주 비대상)·C(미적재) 동결 기준 재출력. 결과 기록.

- [ ] **Step 3: 무인 워치독 재가동 (동결 100 대상)**

Run:
```bash
ps aux | grep -E "bt_loop.sh|profitability_cli backfill" | grep -v grep || echo "clean"
nohup bash /tmp/bt_loop.sh >/tmp/bt_loop.out 2>&1 </dev/null & disown
```
Expected: 유령 0 확인 후 기동. 이제 백필이 **동결 100** 의 qualifying 주만 채움(`_sample` 핀 적용).

- [ ] **Step 4: 진행 확인**

Run: `psql .../kr_pipeline -c "SELECT COUNT(*), COUNT(DISTINCT symbol) FROM backtest_classification WHERE source='backtest' AND symbol = ANY(ARRAY(SELECT unnest FROM unnest((SELECT string_to_array('...', ',')))))"` — 또는 단순히 동결 100 교집합 카운트(gapcheck 재실행).
Expected: 동결 100 기준 적재가 증가.

---

## Self-Review (작성자 체크)

**문제 복구:** §2(표본 100 고정) 위반 → Task 1·2 로 동결 핀. ✓
**범위:** backtest CLI + 새 모듈만. 운영·지표 불변. ✓
**적재 보존:** 기존 행 삭제 없음. 분석은 `_sample`(동결) 경유라 out-of-sample 자동 제외. ✓
**한계(명시):** 주(week) 단위 드리프트(B)는 이 수정 범위 밖 — 완료 후 민감도분석(전체 vs 드리프트종목 제외)으로 결론 강건성 입증(기합의·§8 한계 기록).
**Type consistency:** `FROZEN_SAMPLE`(Task1)→`_sample`(Task2) import 일치.

## 대안 (사용자 선택 시)
**옵션 B(전체 manifest 동결)**: (종목×주) 스냅샷을 커밋해 주 단위까지 고정·재현. §2 범위 초과·변경 큼. 주 단위 드리프트까지 코드로 제거하고 싶으면 이 plan에 Task(manifest 생성 + 백필이 manifest 기준 적재)를 추가.
