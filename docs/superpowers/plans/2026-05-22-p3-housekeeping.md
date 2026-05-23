# P3 Housekeeping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 책 평가와 무관한 코드/문서/주석 결함 6 건을 정리. 매수/매도 동작 변화 0, 사용자 신뢰·운영자 혼동 제거 목적.

**Architecture:** 모두 *작은* 단발 변경 — prompt validation 불일치 / cron 시각 / stale 흔적 정리 / 운영쿼리 주석 / 죽은 필드 제거 / 죽은 라벨 정정. 각 task 독립적 commit. 테스트는 baseline (343 passed / 25 사전 존재 fail) 유지.

**Tech Stack:** Python (FastAPI), TypeScript, markdown prompts, pytest

**Spec:** `docs/superpowers/specs/2026-05-22-book-audit-findings.md` P3-1 ~ P3-6 (commit `c2591e3`)

---

## Implementation Order

P3 action 6개는 거의 모두 독립 (P3-2 → P3-3 가 유일한 의존성). spec 의 P3-N 순서대로 task 1-6.

| Task | Action | 의존성 |
|---|---|---|
| 1 | P3-1: entry_mode validation (3 → 2 enum) | 없음 |
| 2 | P3-2: cron.example 16:30 → 20:00 | 없음 |
| 3 | P3-3: stale 16:30 흔적 정리 | Task 2 (cron.example 갱신 후) |
| 4 | P3-4: README RS 80 운영쿼리 주석 | 없음 |
| 5 | P3-5: is_blue_dot 죽은 필드 제거 | 없음 |
| 6 | P3-6: under_pressure 죽은 라벨 정정 | 없음 |

---

## File Structure

### 수정 (Modified)

| Path | What |
|---|---|
| `prompts/calculate_entry_params_v2_0.md:36` (§1.1) | entry_mode 3 enum → 2 (early_entry 제거) |
| `web/src/data/llm-pipeline-audit/stages.ts:240, 254` | audit 페이지의 entry_mode 3 표기도 2 로 정정 |
| `scripts/cron.example:47-53` | LLM runner 16:30 → 20:00 + 주석 갱신 |
| `tests/test_api_cron.py:70` | fixture 더미 시각 16:30 → 20:00 (혼동 제거) |
| `tests/test_cron_manager.py:14` | fixture 더미 시각 16:30 → 20:00 |
| `docs/superpowers/specs/2026-05-17-llm-runner-design.md` | 옛 spec 의 16:30 사례에 superseded 주석 |
| `docs/superpowers/plans/2026-05-17-llm-runner.md` | 옛 plan 의 16:30 라인에 주석 |
| `docs/superpowers/plans/2026-05-18-all-pipelines-dashboard.md` | 옛 default_cron 값에 주석 |
| `docs/superpowers/plans/2026-05-18-runner-dashboard.md` | 옛 plan 의 16:30 다수 위치에 주석 |
| `README.md:62-68` | 운영쿼리 #4 rs_rating>=80 주석화 |
| `api/services/payload_builder.py:49` | is_blue_dot 필드 제거 |
| `prompts/analyze_chart_v3.md:29` | §Inputs 의 is_blue_dot 참조 제거 |
| `tests/test_api_payload_builder.py:38` | is_blue_dot 단언 제거 |
| `prompts/analyze_chart_v3.md:270` | under_pressure 죽은 라벨 → 4-enum |

---

## Task 1: P3-1 — entry_mode validation 일치

**Files:**
- Modify: `prompts/calculate_entry_params_v2_0.md` (§1.1 line 36, 필요 시 §11)
- Modify: `web/src/data/llm-pipeline-audit/stages.ts:240, 254`

`§10 validation` 이 entry_mode 를 `pivot_breakout | pocket_pivot` 2 개만 허용하는데 `§1.1` (line 36) 와 audit `stages.ts` 는 3 개 (`+ early_entry`) 표기. `early_entry` 가 출력되면 validation 위반. v2.0 코드/mock 모두 2 개만 생성하므로 *제거* 가 올바른 정렬.

- [ ] **Step 1: Edit prompt §1.1 (line 36)**

Read `prompts/calculate_entry_params_v2_0.md` line 30-50 부근. 기존 line 36:

```markdown
- entry_mode (pivot_breakout | pocket_pivot | early_entry)
```

변경:

```markdown
- entry_mode (pivot_breakout | pocket_pivot)
```

- [ ] **Step 2: Check §11 for any remaining 3-enum**

Run: `grep -n "early_entry" prompts/calculate_entry_params_v2_0.md`

만약 §11 (대략 line 240) 또는 다른 곳에서 `early_entry` 가 나오면 함께 제거. *§10 validation 표 자체는 이미 2 개라 변경 불필요.*

만약 발견된 다른 위치도 정정 후 다음 step 으로.

- [ ] **Step 3: Edit audit stages.ts**

Read `web/src/data/llm-pipeline-audit/stages.ts` line 235-260 부근. 기존 line 240 + 254:

```ts
- 정의 값 3개: pivot_breakout | pocket_pivot | early_entry
...
1. entry_mode (pivot_breakout / pocket_pivot / early_entry)
```

변경 (두 위치 모두):

```ts
- 정의 값 2개: pivot_breakout | pocket_pivot
...
1. entry_mode (pivot_breakout / pocket_pivot)
```

- [ ] **Step 4: tsc clean**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 5: Commit**

```bash
git add prompts/calculate_entry_params_v2_0.md web/src/data/llm-pipeline-audit/stages.ts
git commit -m "fix(p3-1): entry_mode validation 일치 — early_entry 제거

prompt §10 validation 은 pivot_breakout | pocket_pivot 2개만 허용하나
§1.1 와 audit stages.ts 는 3개 표기 (+ early_entry). v2.0 코드/mock 모두
2개만 생성. early_entry 는 dead enum — prompt §1.1 + audit 양쪽에서 제거."
```

---

## Task 2: P3-2 — cron.example LLM runner 16:30 → 20:00

**Files:**
- Modify: `scripts/cron.example:47-53` (LLM runner 섹션)

라이브 cron 등록 경로 (`cron_manager.register` → `pipeline_specs.py:181`) 는 20:00. `scripts/cron.example` 만 stale 16:30 — 게다가 의존 데이터 적재 (18:30 ohlcv / 19:00 indicators / 19:30 market_context) 보다 앞서는 *역순*. 사용자가 손으로 crontab 등록 시 위험.

- [ ] **Step 1: Edit cron.example LLM runner section**

Read `scripts/cron.example` line 45-60 부근. 기존 LLM runner 섹션 (line 47-51):

```
# ─── #4 LLM Analysis Runner (B v3 갭 1-8 day-1 통합) ───────────────────────
# 장 마감 (15:30 KST) 후 30분 버퍼 + 각 10분 간격.
# 일봉/지표/시장컨텍스트는 위 cron 으로 이미 수행되므로 16:30 부터 LLM runner 실행.

# 평일 16:30 — 평일 LLM runner: daily-delta + trigger + (5b) + (6) + perf backfill
30 16 * * 1-5  cd $PROJECT_DIR && uv run python -m kr_pipeline.llm_runner --mode=full-daily >> $LOG_DIR/llm_runner.log 2>&1
```

변경 (주석 + cron 라인 모두):

```
# ─── #4 LLM Analysis Runner (B v3 갭 1-8 day-1 통합) ───────────────────────
# 데이터 적재 (위 cron 의 18:30 ohlcv / 19:00 indicators / 19:30 market_context) 완료
# 후 20:00 부터 LLM runner 실행. pipeline_specs.py 의 default_cron 과 일치.

# 평일 20:00 — 평일 LLM runner: daily-delta + trigger + (5b) + (6) + perf backfill
0 20 * * 1-5  cd $PROJECT_DIR && uv run python -m kr_pipeline.llm_runner --mode=full-daily >> $LOG_DIR/llm_runner.log 2>&1
```

- [ ] **Step 2: Verify no test impact**

cron.example 은 *예시 파일* 이라 코드/테스트 무관. sanity check:

Run: `grep -l "cron\.example\|cron_example" tests/ 2>/dev/null` (출력 없으면 OK)

- [ ] **Step 3: Commit**

```bash
git add scripts/cron.example
git commit -m "fix(p3-2): cron.example LLM runner 16:30 → 20:00

라이브 cron 등록 경로 (cron_manager.register → pipeline_specs.py:181) 는
0 20 * * 1-5. cron.example 만 stale 16:30 — 게다가 의존 데이터 적재
(18:30/19:00/19:30) 보다 앞서는 역순. 사용자 손으로 crontab -e 등록 시
잘못된 시각 사용 방지."
```

---

## Task 3: P3-3 — stale 16:30 흔적 7곳 정리

**Files:**
- Modify: `tests/test_api_cron.py:70` (fixture 더미)
- Modify: `tests/test_cron_manager.py:14` (fixture 더미)
- Modify: `docs/superpowers/plans/2026-05-17-llm-runner.md:3842` (옛 plan)
- Modify: `docs/superpowers/plans/2026-05-18-all-pipelines-dashboard.md:305` (옛 plan)
- Modify: `docs/superpowers/plans/2026-05-18-runner-dashboard.md` (다수 위치)
- Modify: `docs/superpowers/specs/2026-05-17-llm-runner-design.md` (옛 spec, 다수 위치)

전략 분리:
- **테스트 fixture 2 파일** (`test_api_cron.py`, `test_cron_manager.py`): 더미 시각이라 cron 문자열 파싱 검증만 수행. 16:30 → 20:00 *값만 갱신* (혼동 제거)
- **옛 plan/spec docs**: 시점 스냅샷. 값 자체는 *유지* (역사 기록) 하되 한 줄 주석 추가 ("Superseded — 현행은 0 20 * * 1-5") . 옛 plan/spec 의 *모든* 16:30 라인에 인라인 주석 추가하면 산만 — *파일 상단* 또는 첫 등장 위치에 한 번만.

- [ ] **Step 1: Update test fixtures (test_api_cron.py)**

Read `tests/test_api_cron.py` line 65-75 부근. 기존 line 70 에 `30 16 * * 1-5 /path/llm_runner` 더미 — 16:30 부분을 20:00 으로 변경:

```
0 20 * * 1-5 /path/llm_runner
```

- [ ] **Step 2: Update test fixtures (test_cron_manager.py)**

Read `tests/test_cron_manager.py` line 10-20 부근. 기존 line 14 에 `30 16 * * 1-5 /path/llm_runner --mode=full-daily` 더미 — 16:30 부분을 20:00 으로 변경:

```
0 20 * * 1-5 /path/llm_runner --mode=full-daily
```

- [ ] **Step 3: Run fixture-affected tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_api_cron.py tests/test_cron_manager.py -v 2>&1 | tail -20`
Expected: 모든 테스트 PASS (cron 파싱은 시각 값에 무관)

만약 어떤 테스트가 *구체적인* 16:30 값을 expected 로 사용하면, 그 expected 도 함께 20:00 으로 갱신.

- [ ] **Step 4: Add superseded note to plan/spec docs**

`docs/superpowers/plans/2026-05-17-llm-runner.md`, `docs/superpowers/plans/2026-05-18-all-pipelines-dashboard.md`, `docs/superpowers/plans/2026-05-18-runner-dashboard.md`, `docs/superpowers/specs/2026-05-17-llm-runner-design.md` 4 파일 *각각* 의 *최상단* (제목 H1 직후) 에 다음 한 줄 주석 블록 삽입:

```markdown

> **⚠️ 시점 스냅샷 (2026-05-17~18)** — 본 문서의 LLM runner cron 시각 `30 16 * * 1-5` (16:30) 은 옛 설계. 현행은 `0 20 * * 1-5` (20:00, `kr_pipeline/llm_runner/pipeline_specs.py:181`). 문서 본문의 16:30 표기는 역사적 기록으로 유지.

```

본문의 개별 16:30 라인은 *변경하지 않음* — 시점 스냅샷의 역사적 일관성 유지.

- [ ] **Step 5: Commit**

```bash
git add tests/test_api_cron.py tests/test_cron_manager.py \
        docs/superpowers/plans/2026-05-17-llm-runner.md \
        docs/superpowers/plans/2026-05-18-all-pipelines-dashboard.md \
        docs/superpowers/plans/2026-05-18-runner-dashboard.md \
        docs/superpowers/specs/2026-05-17-llm-runner-design.md
git commit -m "fix(p3-3): stale 16:30 흔적 정리 — 테스트 fixture 갱신 + 옛 docs 에 superseded 주석

테스트 fixture (test_api_cron, test_cron_manager) 의 더미 시각 16:30 →
20:00 (현행과 일관). 옛 plan/spec docs (2026-05-17/18) 4 파일에는 본문
유지 (역사 스냅샷) + 최상단에 superseded 주석 한 줄. 사용자가 옛 문서를
보고 16:30 으로 오해하는 것 방지."
```

---

## Task 4: P3-4 — README RS 80 운영쿼리 주석

**Files:**
- Modify: `README.md:62-68` (운영 점검 #4 쿼리)

운영 점검 쿼리 #4 가 `rs_rating >= 80` 사용하나 실제 LLM 후보 게이트 (`load.py` / `delta.py`) 는 `minervini_pass = TRUE` (= rs_rating ≥ 70). 운영자가 README 로 후보 확인 시 *진짜 LLM 분석 대상보다 좁은* 목록을 봄.

- [ ] **Step 1: Add inline comment to README query #4**

Read `README.md` line 58-70 부근. 기존 line 61-68:

```sql
-- 미너비니 통과 + RS Rating 80 이상 종목 (#4 분석 대상)
SELECT i.date, s.ticker, s.name, s.sector, i.rs_rating, i.adj_close
  FROM daily_indicators i
  JOIN stocks s USING (ticker)
 WHERE i.date = (SELECT MAX(date) FROM daily_indicators)
   AND i.minervini_pass = TRUE
   AND i.rs_rating >= 80
 ORDER BY i.rs_rating DESC;
```

변경 (주석 명확화 — "예시 vs 실제" 분리):

```sql
-- 미너비니 통과 + RS Rating 80 이상 종목 (운영 점검 예시 — 더 엄격하게 좁힘)
-- ⚠️ 실제 LLM 후보 게이트는 minervini_pass = TRUE (= rs_rating ≥ 70). RS≥80 은 추가 정밀 필터링용.
SELECT i.date, s.ticker, s.name, s.sector, i.rs_rating, i.adj_close
  FROM daily_indicators i
  JOIN stocks s USING (ticker)
 WHERE i.date = (SELECT MAX(date) FROM daily_indicators)
   AND i.minervini_pass = TRUE
   AND i.rs_rating >= 80
 ORDER BY i.rs_rating DESC;
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "fix(p3-4): README 운영쿼리 #4 RS 80 주석 명확화

쿼리 자체는 유지 (운영 점검용 — RS 80 으로 더 엄격 필터). 다만 ⚠️
주석으로 '실제 LLM 후보 게이트는 minervini_pass (= rs_rating ≥ 70)'
명시 — 운영자가 80 을 진짜 컷오프로 오해 방지."
```

---

## Task 5: P3-5 — is_blue_dot 죽은 필드 제거

**Files:**
- Modify: `api/services/payload_builder.py:49` (필드 제거)
- Modify: `prompts/analyze_chart_v3.md:29` (§Inputs 의 is_blue_dot 참조 제거)
- Modify: `tests/test_api_payload_builder.py:38` (assert 제거)

`is_blue_dot` 은 IBD/MarketSmith 개념 — 제공된 4 권 책의 핵심 신호 아님. payload 에 항상 `False` 하드코딩인데 prompt 가 입력 신호로 안내 → 죽은 입력. 제거가 단순.

- [ ] **Step 1: Remove from payload_builder.py**

Read `api/services/payload_builder.py` line 40-55 부근. 기존 line 49:

```python
        "is_blue_dot": False,
```

이 줄을 *완전히 제거*. 위/아래 쉼표 등 dict 구조가 깨지지 않게 — 즉 단순히 그 한 줄만 삭제하면 됨 (Python dict literal 은 trailing comma 허용).

만약 그 줄 위/아래에 주석이 붙어 있으면 그 주석도 함께 제거.

- [ ] **Step 2: Remove from prompt §Inputs**

Read `prompts/analyze_chart_v3.md` line 25-35 부근. 기존 line 29:

```markdown
- **Minervini screening results**: `conditions_met` (8 boolean conditions) AND `conditions_detail` (margin of pass for each condition), `rs_rating`, `is_blue_dot`
```

변경 (`is_blue_dot` 만 제거):

```markdown
- **Minervini screening results**: `conditions_met` (8 boolean conditions) AND `conditions_detail` (margin of pass for each condition), `rs_rating`
```

- [ ] **Step 3: Remove assert from test**

Read `tests/test_api_payload_builder.py` line 30-45 부근. 기존 line 38:

```python
    assert payload["is_blue_dot"] is False
```

이 줄을 *완전히 제거*. 함수 다른 단언은 그대로.

- [ ] **Step 4: Run test**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_api_payload_builder.py -v 2>&1 | tail -20`
Expected: 모든 테스트 PASS

만약 *다른* 테스트 (예: schema 검증) 가 `is_blue_dot` 필드 존재를 expect 하면 그것도 갱신:

Run: `grep -rn "is_blue_dot" tests/ api/ kr_pipeline/`
이 명령 출력 *남는 게 있으면* 그 위치도 정리 (안 남으면 정리 완료).

- [ ] **Step 5: Commit**

```bash
git add api/services/payload_builder.py prompts/analyze_chart_v3.md tests/test_api_payload_builder.py
git commit -m "fix(p3-5): is_blue_dot 죽은 입력 필드 제거

is_blue_dot 은 IBD/MarketSmith 개념으로 본 시스템 4권 (Minervini TLSMW/
TTLC, O'Neil HMMS, Morales & Kacher TLOND) 의 핵심 신호 아님. payload 에
항상 False 하드코딩 (api/services/payload_builder.py:49) 인데 prompt 가
입력 신호로 안내 — LLM 이 활용 불가한 죽은 입력.

제거: payload_builder 의 필드 + prompt §Inputs 참조 + test assert."
```

---

## Task 6: P3-6 — under_pressure 죽은 라벨 정정

**Files:**
- Modify: `prompts/analyze_chart_v3.md:270` (reasoning 템플릿 예시)

prompt line 270 의 reasoning 한국어 템플릿 예시가 시장 추세 단계 enum 으로 `under_pressure` 언급 — `status.py` 가 *산출 안 하는* 죽은 라벨 (IBD 용어). 실제 산출 enum 은 4 개: `confirmed_uptrend / downtrend / correction / rally_attempt`. 예시 정정으로 LLM 이 잘못된 라벨 출력 유도 방지.

- [ ] **Step 1: Edit reasoning template**

Read `prompts/analyze_chart_v3.md` line 265-275 부근. 기존 line 270:

```markdown
  KOSPI/KOSDAQ 추세 단계 (confirmed_uptrend / under_pressure / correction 등),
```

변경 (실제 코드 산출 4-enum 으로):

```markdown
  KOSPI/KOSDAQ 추세 단계 (confirmed_uptrend / downtrend / correction / rally_attempt),
```

- [ ] **Step 2: Verify build (sanity check)**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 3: Commit**

```bash
git add prompts/analyze_chart_v3.md
git commit -m "fix(p3-6): prompt reasoning 템플릿의 under_pressure 죽은 라벨 정정

prompt line 270 의 reasoning 예시가 시장 enum 으로 'under_pressure' 사용
— IBD 용어로 status.py 가 산출 안 함. 실제 4-enum (confirmed_uptrend /
downtrend / correction / rally_attempt) 으로 정정. LLM 이 잘못된 라벨
출력 유도 방지."
```

---

## Self-Review

**1. Spec coverage**: spec P3-1 ~ P3-6 매핑:
- ✅ P3-1 entry_mode validation 일치 → Task 1
- ✅ P3-2 cron.example 16:30 → 20:00 → Task 2
- ✅ P3-3 stale 16:30 7곳 정리 → Task 3
- ✅ P3-4 README RS 80 주석 → Task 4
- ✅ P3-5 is_blue_dot 제거 → Task 5
- ✅ P3-6 under_pressure 라벨 정정 → Task 6

**2. Placeholder scan**: 모든 step 에 정확 코드 + 명령. "TODO" / "appropriate" 없음. ✅

**3. Type consistency**:
- Task 1 의 enum (`pivot_breakout | pocket_pivot`) 가 spec 의 P3-1 정의 + 실제 코드 (v2.0 mock) 와 일치 ✅
- Task 3 의 stale 16:30 7 곳이 spec 의 list (test fixtures 2 + plan docs 4 형태로 매핑) 와 일치 ✅
- Task 5 의 3 파일 (`payload_builder.py` + prompt §Inputs + test) 이 spec P3-5 의 권장 (b) "prompt 에서 is_blue_dot 언급 제거 + payload 에서 필드 삭제" 와 일치 ✅

**4. 제외 / 한계**:
- Task 3 의 옛 plan/spec docs 본문 16:30 라인을 *건드리지 않음* — 시점 스냅샷 유지가 옳다는 판단. 다만 *첫 등장*에 superseded 주석으로 사용자 혼동 방지.
- Task 5 는 `is_blue_dot` 의 *재계산 구현* 옵션 (spec 의 옵션 (a)) 은 채택 안 함 — 본 시스템 4 권 외 개념이라 의미 없음.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-22-p3-housekeeping.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
