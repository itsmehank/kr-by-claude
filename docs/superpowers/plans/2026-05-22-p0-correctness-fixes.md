# P0 Correctness Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 책 평가에서 식별된 P0 (CORRECTNESS) 5 action 을 적용해 LLM 분석 파이프라인이 *능동적으로 만드는* 잘못된 매수 위험을 제거.

**Architecture:** SSOT 인프라 (이미 commit `cdac6fe` 까지 완성) 가 깔려 있어 *값 변경은 SSOT 1곳* 수정으로 전파. 본 plan 의 변경은 (a) SSOT 값 갱신 + 테스트 + generated.ts 재생성, (b) prompt (.md) 텍스트 수정 (LLM 지시 변경), (c) UI 텍스트 정정 (사용자 메시지 일관성). 새 코드 로직 추가 없음 — 임계 / 정의 / 지시문 변경만.

**Tech Stack:** Python 3.12+, pytest, TypeScript, markdown prompts

**Spec:** `docs/superpowers/specs/2026-05-22-book-audit-findings.md` P0-1 ~ P0-5 (commit `c2591e3`)

---

## Implementation Order

P0 action 5 개를 책 critical 순서 + 의존성에 따라 5 task 로:

| Task | Action | 의존성 | 영향 |
|---|---|---|---|
| 1 | P0-2: distribution day 종목 정의 통일 | 없음 | 유일 책 VIOLATES — 기관 매도중 종목 차단 |
| 2 | P0-3: prompt §6 column 참조 한 줄 | Task 1 | LLM 경로 비대칭 제거 |
| 3 | P0-4: prompt §4 cup 핸들 품질 블록 | 없음 | wedging handle 돌파 차단 |
| 4 | P0-1: breakout 1.4× → 1.5× 선호 + 1.4× 하한 경고 | 없음 | UI 자동 정렬 + 책 선호치 |
| 5 | P0-5: UI 게이트 1.5× 오기 정정 | Task 4 | 사용자 신뢰 (게이트 vs 매수 확정 분리) |

---

## File Structure

### 수정 (Modified)

| Path | What |
|---|---|
| `kr_pipeline/common/thresholds.py` | `STOCK_DISTRIBUTION_VOL_MULT` 1.25→1.0 (Task 1). 신규 `BREAKOUT_VOL_FLOOR`=1.4, `BREAKOUT_VOL_PREFERRED`=1.5 추가 (Task 4) |
| `tests/test_common_thresholds.py` | 값 변경 + 신규 상수 테스트 |
| `kr_pipeline/indicators/compute/volume.py:91-103` | distribution_day docstring 갱신 (Task 1) |
| `web/src/data/thresholds.generated.ts` | 자동 재생성 (Task 1, Task 4) |
| `prompts/analyze_chart_v3.md:200` | distribution_day_flag column 참조 추가 (Task 2) |
| `prompts/analyze_chart_v3.md:89` | cup_with_handle 정의에 핸들 품질 블록 (Task 3) |
| `prompts/calculate_entry_params_v2_0.md:319-320, 379` | breakout volume 표 + known_warnings 화이트리스트 (Task 4) |
| `web/src/components/InfoTooltip.tsx:68` | breakout 1.5× 오기 정정 (Task 5) |
| `web/src/data/llm-pipeline-simulation.ts:93, 267` | 게이트 1.5× 오기 정정 (Task 5) |

---

## Task 1: P0-2 — distribution_day 종목 정의 통일

**Files:**
- Modify: `kr_pipeline/common/thresholds.py:62` (`STOCK_DISTRIBUTION_VOL_MULT`)
- Modify: `tests/test_common_thresholds.py` (값 변경)
- Modify: `kr_pipeline/indicators/compute/volume.py:91-103` (docstring 갱신)
- Modify: `web/src/data/thresholds.generated.ts` (자동 재생성)

거래량 임계만 변경. *하락 임계* (현재 `is_down`, 0%) → -0.2% 변경은 함수 시그니처를 바꿔야 하므로 별도 결정. 이 task 는 **거래량만** 정렬 (1.25× → 1.0×). 하락 임계 정렬은 P0-3 의 prompt 텍스트로 흡수 (LLM 이 §6 정의대로 OHLCV 에서 재계산하면 -0.2% 적용됨). **[superseded by #20/#31 — 이후 §6 이 flag 컬럼을 authoritative 로 선언(재계산 경로 폐기)했고, 컷은 코드(STOCK_DISTRIBUTION_PCT_DOWN)가 적용, 5b 도 #31 로 flag 전달. 이 문장의 '재계산 흡수' 논리와 다음 문장의 '두 경로 빈도 일치' 전제까지 사문 — 현재는 단일 경로(flag).]** ~~코드 flag 의 거래량 기준 (1.0×) 이 prompt §6 (1.0×) 와 일치하면 두 경로가 같은 빈도로 distribution 을 잡는다.~~

- [ ] **Step 1: Update SSOT value + docstring**

Edit `kr_pipeline/common/thresholds.py` line 62-66 의 `STOCK_DISTRIBUTION_VOL_MULT` 블록:

```python
STOCK_DISTRIBUTION_VOL_MULT: Final[float] = 1.0
"""종목 레벨 distribution day 의 거래량 임계 (50일 평균 배수).
2026-05-22 (P0-2): 1.25 → 1.0 정렬 — prompt §6 의 정의 (close down ≥0.2%
on volume > 1.0× of 50-day average) 와 일치. 책 표준 (O'Neil HMMS Ch.9:
'전일 거래량 초과') 의 IBD 실무 근사."""
```

- [ ] **Step 2: Update test**

Edit `tests/test_common_thresholds.py` 의 `test_volume_constants`:

```python
def test_volume_constants():
    assert thresholds.STOCK_DISTRIBUTION_VOL_MULT == 1.0
    assert thresholds.VOLUME_DRY_UP_MULT == 0.5
```

- [ ] **Step 3: Run SSOT test**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_common_thresholds.py -v`
Expected: PASS — 8 tests (값 변경 반영됨)

- [ ] **Step 4: Update volume.py docstring**

`kr_pipeline/indicators/compute/volume.py` 의 `distribution_day` 함수 (line 91 부근) 의 docstring 을 변경:

기존:
```python
def distribution_day(
    is_down_day: pd.Series,
    adj_volume: pd.Series,
    avg_volume_series: pd.Series,
    threshold: float = STOCK_DISTRIBUTION_VOL_MULT,
) -> pd.Series:
    """is_down_day AND adj_volume > avg_volume * threshold.

    1.25 는 IBD/community 임계 (책 명시 아님).
    """
```

변경 후:
```python
def distribution_day(
    is_down_day: pd.Series,
    adj_volume: pd.Series,
    avg_volume_series: pd.Series,
    threshold: float = STOCK_DISTRIBUTION_VOL_MULT,
) -> pd.Series:
    """is_down_day AND adj_volume > avg_volume * threshold.

    2026-05-22 (P0-2): threshold default 1.25 → 1.0 정렬. prompt §6 의
    정의 (close down ≥0.2% on volume > 1.0× of 50-day average) 와 일치.
    is_down_day (현재 0% 컷) vs prompt 의 -0.2% 컷 차이는 별도 fix 대상이
    아니며, LLM 이 §6 텍스트대로 OHLCV 재계산할 때 자연스럽게 -0.2% 적용.
    """
```

- [ ] **Step 5: Run volume tests**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/ -v -k "volume" 2>&1 | tail -20`
Expected: 모든 기존 volume 테스트 PASS (값 자체는 임계로 함수에 들어가서 sample 데이터 통과 여부가 갈리지만, 기존 테스트가 1.0 / 1.25 가리지 않는다면 통과). 만약 깨지면 그 테스트 파일을 확인해 임계 변경에 맞춰 갱신.

- [ ] **Step 6: Regenerate thresholds.generated.ts**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run python scripts/export_thresholds.py`
Expected: `Wrote .../thresholds.generated.ts (21 constants)`

검증: `grep "STOCK_DISTRIBUTION_VOL_MULT" web/src/data/thresholds.generated.ts` 가 `1.0` 표시.

- [ ] **Step 7: tsc clean**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 8: Commit**

```bash
git add kr_pipeline/common/thresholds.py tests/test_common_thresholds.py \
        kr_pipeline/indicators/compute/volume.py \
        web/src/data/thresholds.generated.ts
git commit -m "fix(p0-2): 종목 distribution_day 거래량 임계 1.25× → 1.0×

prompt §6 (close down ≥0.2% on volume > 1.0× of 50-day average) 와 정합.
유일한 책 VIOLATES (Phase 2 B3) 해소.

SSOT 1곳 (STOCK_DISTRIBUTION_VOL_MULT) 변경 → 코드 flag 자동 갱신 +
thresholds.generated.ts 재생성으로 UI 도 일관. 책 표준: O'Neil HMMS Ch.9
'전일 거래량 초과' (IBD 실무에서 50일 평균 1.0×로 근사)."
```

---

## Task 2: P0-3 — prompt §6 에 column 참조 추가

**Files:**
- Modify: `prompts/analyze_chart_v3.md:200` (§6 본문)

prompt §4.5 line 119 가 `pocket_pivot_flag` column 을 명시 참조하나, §6 distribution 은 텍스트 재계산 룰만 줘서 비대칭. Task 1 으로 코드 flag 가 §6 정의와 일치했으니, §6 가 column 을 authoritative 로 가리키게.

- [ ] **Step 1: Edit prompt §6**

Edit `prompts/analyze_chart_v3.md` line 200 부근. 현재 내용 (Task 1 grep 결과):

```markdown
### 6. Stock-Level Distribution Check

Separate from the market-level distribution count in `market_context`, evaluate the stock's own distribution pattern over the past 25 sessions:

- A stock distribution day = close down ≥ 0.2% on volume > 1.0× of 50-day average.
- If 4+ distribution days within the past 25 sessions on the stock itself: this stock is being sold by institutions even while in Stage 2. Add `volume_contraction_on_advance` if volume is also drying up on up-days, or demote to `watch`.
- A single distribution day is normal; clusters are warnings.
```

변경: 첫 bullet 다음에 column 참조 줄을 추가.

```markdown
### 6. Stock-Level Distribution Check

Separate from the market-level distribution count in `market_context`, evaluate the stock's own distribution pattern over the past 25 sessions:

- A stock distribution day = close down ≥ 0.2% on volume > 1.0× of 50-day average.
- **Use the `distribution_day_flag` series in `indicators_recent_60d` as the authoritative per-day signal for this count; the textual definition above describes how that flag is computed.** (Same convention as `pocket_pivot_flag` in §4.5 — column is authoritative.)
- If 4+ distribution days within the past 25 sessions on the stock itself: this stock is being sold by institutions even while in Stage 2. Add `volume_contraction_on_advance` if volume is also drying up on up-days, or demote to `watch`.
- A single distribution day is normal; clusters are warnings.
```

- [ ] **Step 2: Verify prompt re-imports correctly**

Web app 이 prompt 를 `?raw` import 로 로드하므로 빌드 통과 확인:

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

(Vite `?raw` 는 markdown 의 content 변경에 영향 안 받음 — sanity check.)

- [ ] **Step 3: Commit**

```bash
git add prompts/analyze_chart_v3.md
git commit -m "fix(p0-3): prompt §6 에 distribution_day_flag column 참조 명시

기존엔 §4.5 pocket_pivot_flag 만 column 참조 명시, §6 distribution 은
텍스트 재계산만 안내 — LLM 경로 비대칭. P0-2 로 코드 flag 정의가 §6
텍스트와 일치하므로 column 차용 = 텍스트 재계산 결과. 이중 방어."
```

---

## Task 3: P0-4 — prompt §4 cup_with_handle 핸들 품질 블록

**Files:**
- Modify: `prompts/analyze_chart_v3.md:89` (§4 cup_with_handle 정의 줄)

UI (`ClassificationsPage.tsx:57`) 가 이미 "cup 상반부 짧은 손잡이 (8~12% pullback)" 텍스트 보유 — LLM 이 보는 prompt 에는 8-12% 핸들 룰 / 10-week 선 / wedging 누락 (Turn 1 B1 INCOMPLETE). 책 인용으로 보강.

- [ ] **Step 1: Edit prompt §4 cup_with_handle row**

Edit `prompts/analyze_chart_v3.md` line 89. 현재:

```markdown
| `cup_with_handle` | U-shape (not V); 7–45 weeks; depth ≤33% (up to 50% if forming during/after bear market recovery, per O'Neil); handle forms in upper half of cup on lower volume; handle ≥1 week | O'Neil, *HMMS* Ch.2 |
```

이 줄 *직후* 에 핸들 품질 하위 블록 추가 (표 다음에 별도 단락):

기존 표 끝나는 자리 (line 92-93 부근, "narrow_base" 식별 안내 직전) 를 확인하고, **표 다음 / narrow_base 안내 이전** 에 다음을 삽입:

```markdown

**Handle quality (cup_with_handle only) — all should hold or downgrade toward `none` / `watch`:**

- **Handle depth ≤ 8–12% from its own peak** in a normal market, measured separately from the total cup depth. A handle deeper than ~12% is loose; treat the structure with caution. (O'Neil HMMS Ch.2 p.116: "A price drop in a proper handle should be contained within 8% to 12% of its peak during bull markets unless the stock forms a very large cup".)
- **Handle low must sit above the stock's 10-week (≈ SMA-50 on the weekly chart) moving average** AND in the upper half of the cup. A handle in the lower half or below the 10-week line is failure-prone. (O'Neil HMMS Ch.2 p.116: "The handle should also be above the stock's 10-week moving average price line. Handles that form in the lower half ... or completely below the stock's 10-week line are weak and failure-prone".)
- **Beware wedging handles**: if the handle's lows drift *upward* or run flat (rather than drifting down with a shakeout), the breakout is failure-prone and often signals a 3rd/4th-stage or laggard base. If a wedging handle is visible on the weekly chart, prefer `watch` and note "wedging handle" in reasoning; consider adding `late_stage_base` to `risk_flags`. (O'Neil HMMS Ch.2 p.116: "handles that consistently wedge up ... have a much higher probability of failing when they break out", and "tends to occur in third- or fourth-stage bases, in laggard stock bases".)

```

- [ ] **Step 2: Verify build**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 3: Commit**

```bash
git add prompts/analyze_chart_v3.md
git commit -m "fix(p0-4): prompt §4 cup_with_handle 에 핸들 품질 블록 추가

O'Neil HMMS Ch.2 p.116 의 핸들 품질 3요소 명시 — (1) 핸들 깊이 8-12%,
(2) 10-week 선 위, (3) wedging handle 경계. wedging 은 책이 실패율 최고로
지목한 패턴이나 prompt 에 누락 (Phase 2 B1 + Turn 1 INCOMPLETE).
잘못된 cup_with_handle entry 통과 차단.

UI (ClassificationsPage.tsx:57) 에 이미 비슷한 8-12% 텍스트 존재 — prompt
이식으로 LLM 도 같은 룰 적용."
```

---

## Task 4: P0-1 — breakout 1.4× 하한 + 1.5× 선호

**Files:**
- Modify: `kr_pipeline/common/thresholds.py` (신규 상수 추가)
- Modify: `tests/test_common_thresholds.py` (신규 상수 테스트)
- Modify: `prompts/calculate_entry_params_v2_0.md:319-320, 379` (표 + 화이트리스트)
- Modify: `web/src/data/thresholds.generated.ts` (자동 재생성)

`ge_1.4x_50day_avg` 디폴트를 `ge_1.5x_50day_avg` 로 올리고, 1.4× 는 허용 하한으로 강등. 1.4-1.5 구간에 신규 known_warning `breakout_volume_below_preferred_50pct` emit.

- [ ] **Step 1: Add new SSOT constants**

Edit `kr_pipeline/common/thresholds.py`. `STOCK_DISTRIBUTION_VOL_MULT` 다음 (대략 line 66) 에 새 블록 추가:

```python
# ===== Breakout Volume — 책 표준 (prompts/calculate_entry_params_v2_0.md §6.1) =====

BREAKOUT_VOL_FLOOR: Final[float] = 1.4
"""Breakout 거래량 허용 하한 (50일 평균 배수).
책: O'Neil HMMS Ch.2 p.117 — '40% to 50% above normal'. 하한 = 40% (=1.4×).
1.4×~1.5× 구간은 'preferred 미달' 경고 emit."""

BREAKOUT_VOL_PREFERRED: Final[float] = 1.5
"""Breakout 거래량 선호치 (50일 평균 배수).
책: O'Neil HMMS p.117 / p.185 — '40% to 50% above normal', 선호 50%+.
TLOND p.134 — 'standard breakout = 50% above average or more'.
2026-05-22 (P0-1): 디폴트를 1.4× → 1.5× 로 상향, 1.4× 는 허용 하한."""
```

- [ ] **Step 2: Add tests for new constants**

Edit `tests/test_common_thresholds.py`. 새 테스트 함수 추가 (예: `test_volume_constants` 다음에):

```python
def test_breakout_volume_constants():
    assert thresholds.BREAKOUT_VOL_FLOOR == 1.4
    assert thresholds.BREAKOUT_VOL_PREFERRED == 1.5
```

- [ ] **Step 3: Run SSOT test**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run pytest tests/test_common_thresholds.py -v`
Expected: PASS — 9 tests (1 추가)

- [ ] **Step 4: Edit prompt §6.1 table (line 318-320)**

Edit `prompts/calculate_entry_params_v2_0.md` line 318-320 의 표. 현재:

```markdown
| `ge_1.3x_50day_avg` | tight VCP only — `pattern_basis == "vcp"` with final contraction range ≤ 6% of pivot AND volume contracting through the contraction |
| `ge_1.4x_50day_avg` | **default** — `flat_base`, `cup_with_handle`, `double_bottom`, standard `vcp` |
| `ge_1.5x_50day_avg` | `pattern_basis == "3c_cheat"` (earliest entry) |
```

변경:

```markdown
| `ge_1.3x_50day_avg` | tight VCP only — `pattern_basis == "vcp"` with final contraction range ≤ 6% of pivot AND volume contracting through the contraction |
| `ge_1.4x_50day_avg` | acceptable floor (book "40% above normal") — emit `breakout_volume_below_preferred_50pct` if observed in [1.4×, 1.5×) |
| `ge_1.5x_50day_avg` | **default** — `flat_base`, `cup_with_handle`, `double_bottom`, standard `vcp` AND `pattern_basis == "3c_cheat"` (book preferred 50%+) |
```

- [ ] **Step 5: Edit prompt §6.1 default selection text**

Edit `prompts/calculate_entry_params_v2_0.md` 같은 표 위/아래의 default 안내 텍스트. 현재 line 326 부근에 "When choosing `ge_1.3x_50day_avg`: add `breakout_volume_requirement_relaxed`." 가 있음. 그 부근에 다음 추가 (정확한 삽입 위치: 같은 안내 블록 내, line 326 직전 또는 직후):

```markdown

**Default selection (v2.1, P0-1)**: For standard patterns (`flat_base`, `cup_with_handle`, `double_bottom`, standard `vcp`, `3c_cheat`), default to `ge_1.5x_50day_avg` (책 선호치 50%). When observed ratio is in `[1.4, 1.5)` — i.e. ≥ floor but < preferred — emit `known_warnings: ["breakout_volume_below_preferred_50pct"]` and still allow entry.
```

- [ ] **Step 6: Edit §8.1 known_warnings whitelist (line 374)**

Edit `prompts/calculate_entry_params_v2_0.md` 의 §8.1 화이트리스트 표. 현재 line 374 에 `breakout_volume_requirement_relaxed` 항목이 있음. 그 *직후* 에 새 코드 추가:

기존:
```markdown
| `breakout_volume_requirement_relaxed` | `ge_1.3x_50day_avg` was chosen (tight VCP only) |
| `breakout_volume_below_requirement` | populated `observed_breakout_volume_ratio` < requirement threshold |
```

변경:
```markdown
| `breakout_volume_requirement_relaxed` | `ge_1.3x_50day_avg` was chosen (tight VCP only) |
| `breakout_volume_below_preferred_50pct` | observed in [1.4×, 1.5×) — meets book floor (40%) but below preferred (50%) |
| `breakout_volume_below_requirement` | populated `observed_breakout_volume_ratio` < requirement threshold |
```

- [ ] **Step 7: Update §10 validation (whitelist count)**

§8.1 헤더가 "v2.0: 15 codes" 인데 화이트리스트가 16 codes 됨. §8.1 헤더 + §10 validation 의 codes count 도 갱신:

Edit `prompts/calculate_entry_params_v2_0.md` line 361 부근 `### 8.1 \`known_warnings\` whitelist (v2.0: 15 codes)` → `### 8.1 \`known_warnings\` whitelist (v2.1: 16 codes)`.

§10 validation table 의 `known_warnings | array from §8.1 whitelist (15 codes)` 도 `(16 codes)` 로 갱신 (line 488 부근).

- [ ] **Step 8: Regenerate thresholds.generated.ts**

Run: `cd /Users/hank.es/git/personal/kr-by-claude && uv run python scripts/export_thresholds.py`
Expected: `Wrote .../thresholds.generated.ts (23 constants)` — 21 → 23 (2 추가)

검증: `grep "BREAKOUT_VOL_" web/src/data/thresholds.generated.ts` 가 `1.4` + `1.5` 표시.

- [ ] **Step 9: tsc clean**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 10: Commit**

```bash
git add kr_pipeline/common/thresholds.py tests/test_common_thresholds.py \
        prompts/calculate_entry_params_v2_0.md \
        web/src/data/thresholds.generated.ts
git commit -m "fix(p0-1): breakout 거래량 디폴트 1.4× → 1.5× 선호 + 1.4× 하한 경고

책 (O'Neil HMMS p.117 + TLOND p.134): 40-50% 범위, 선호 50%+. 시스템 디폴트
는 40% 하한 — 책 선호 미반영 (Phase 2 A1b AMBIGUOUS).

변경:
- SSOT 에 BREAKOUT_VOL_FLOOR=1.4, BREAKOUT_VOL_PREFERRED=1.5 추가
- prompt §6.1 표: ge_1.5x 가 default, ge_1.4x 는 acceptable floor
- 신규 known_warning 'breakout_volume_below_preferred_50pct' — [1.4×, 1.5×)
  구간 emit (entry 허용하되 선호 미달 표시)
- §8.1 whitelist 15 → 16 codes
- thresholds.generated.ts 재생성 (UI 의 1.5× 표기와 자동 정렬)"
```

---

## Task 5: P0-5 — UI 게이트 1.5× 오기 정정

**Files:**
- Modify: `web/src/components/InfoTooltip.tsx:68`
- Modify: `web/src/data/llm-pipeline-simulation.ts:93, 267`

UI 가 결정론 게이트를 "거래량 1.5×" 로 표기 — 실제 게이트는 1.0× (`trigger_gate.py:22`, `GATE_BREAKOUT_VOL_MULT`). Task 4 후 1.5× 는 *책 선호치* + *entry_params 디폴트* 라 의미가 다름. UI 를 "게이트 ≥ 평균 / 매수 확정 ≥ 1.5× 선호" 로 분리.

- [ ] **Step 1: Edit InfoTooltip.tsx TRIGGER_TYPE_HELP**

Edit `web/src/components/InfoTooltip.tsx` line 68 부근. 현재 (Step 1 grep 결과):

```tsx
      <li>
        <span className="font-semibold">breakout</span>{" "}
        — 종가가 pivot 가격을 돌파 + 거래량 1.5× 이상.
      </li>
```

변경:

```tsx
      <li>
        <span className="font-semibold">breakout</span>{" "}
        — 종가가 pivot 가격을 돌파 + 거래량이 50일 평균 이상 (게이트 통과 = ≥ 1.0×). 매수 확정 (entry_params) 은 LLM 이 책 표준 1.5× 선호치 / 1.4× 허용 하한을 적용.
      </li>
```

(같은 InfoTooltip 안의 `VOLUME_RATIO_HELP` (line 116 부근) 의 "1.50×" 메시지는 *책 선호치* 라 정확함 — 변경 불필요. Task 4 의 디폴트 1.5× 와 자동 정렬.)

- [ ] **Step 2: Edit simulation.ts 게이트 텍스트 2 곳**

Edit `web/src/data/llm-pipeline-simulation.ts`.

**위치 1**: line 93 부근의 `"close > pivot AND volume ≥ 1.5× avg → breakout"`. 변경:

```ts
            { label: "결정론 게이트", value: "close > pivot AND volume ≥ avg (1.0×) → breakout (정밀 1.5× 선호치는 LLM)" },
```

**위치 2**: line 267 부근의 `"evaluate_pivot 의 entry 게이트. close > pivot + volume 1.5× 시 breakout."`. 변경:

```ts
          impact: "evaluate_pivot 의 entry 게이트. close > pivot + volume ≥ avg (1.0×) 시 breakout 트리거 (매수 확정 1.5× 는 LLM).",
```

(같은 파일 line 101 부근의 reasoning 텍스트 `"거래량 1.82× (1.4× 기준 충족)"` 는 시뮬레이션의 *LLM 출력* 부분이라 그대로 — `breakout_volume_below_preferred_50pct` 가 emit 되지 않은 정상 케이스 보여줌.)

- [ ] **Step 3: tsc clean**

Run: `cd /Users/hank.es/git/personal/kr-by-claude/web && npx tsc --noEmit && echo CLEAN`
Expected: `CLEAN`

- [ ] **Step 4: Commit**

```bash
git add web/src/components/InfoTooltip.tsx web/src/data/llm-pipeline-simulation.ts
git commit -m "fix(p0-5): UI 게이트 1.5× 오기 정정

InfoTooltip / simulation 이 결정론 게이트를 '거래량 1.5×' 로 표기 —
실제 게이트는 GATE_BREAKOUT_VOL_MULT=1.0×. 사용자가 '1.5× 미만이면
트리거 안 뜬다' 고 오해 (UI 감사 발견).

게이트 (1.0×) 와 매수 확정 (1.5× 선호 / 1.4× 하한 — Task 4 의 P0-1 정합)
을 메시지로 분리. 책 무관, 사실 정정."
```

---

## Self-Review

**1. Spec coverage**: spec 의 P0 5 action 매핑:
- ✅ P0-1 breakout 1.4 → 1.5× 선호 → Task 4
- ✅ P0-2 distribution_day 종목 정의 → Task 1
- ✅ P0-3 prompt §6 column 참조 → Task 2
- ✅ P0-4 핸들 품질 → Task 3
- ✅ P0-5 UI 게이트 정정 → Task 5

**2. Placeholder scan**: 모든 step 에 정확 코드 + 명령. "TODO" / "appropriate" / "etc." 없음. ✅

**3. Type consistency**:
- 신규 SSOT 상수 (BREAKOUT_VOL_FLOOR, BREAKOUT_VOL_PREFERRED) 가 export_thresholds.py 의 자동 추출 로직 (대문자 시작 + Final 제외) 에 자연 부합 — generated.ts 에 자동 포함 ✅
- prompt §8.1 의 새 코드명 `breakout_volume_below_preferred_50pct` 가 Task 4 의 표 안내 / §6.1 표 안내 / commit message 모두 동일하게 사용 ✅
- `STOCK_DISTRIBUTION_VOL_MULT` 값 1.0 이 Task 1 의 SSOT / test / volume.py docstring / commit message 모두 일치 ✅

**4. 제외 / 한계**:
- 종목 distribution 의 *하락 임계* (is_down 0% vs prompt -0.2%) 정렬은 함수 시그니처 변경이 필요해 별도 결정 — 이 plan 은 거래량 임계만 정렬. LLM 이 §6 텍스트 (-0.2%) 와 column (1.0×avg) 양쪽을 동일 결과로 보게 됨 (Task 1 docstring 에 명시).
- prompt 변경의 LLM 동작 검증은 *실 LLM 호출* 필요 — 이 plan 의 자동화 테스트로는 검증 불가. 후속 작업.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-22-p0-correctness-fixes.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
