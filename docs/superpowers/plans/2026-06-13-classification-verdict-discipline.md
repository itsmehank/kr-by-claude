# 분류 verdict 규율 (A) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** analyze_chart_v3 분류에서 ignore 를 climax(§6.1)·topping(§6.2) 두 조건으로만 좁혀, TT 통과 주도주가 watch 기아로 평일 트리거 경로에서 누락되던 것을 해소한다.

**Architecture:** thresholds.py 에 책-literal 임계 신설 + prompt 에 §5.1(flag→verdict)·§6.1(climax)·§6.2(topping)·§5.2(wide_loose) 규칙 추가 및 §8 ignore 가이드 교정. 분류 로직은 LLM 이 prompt 로 판정(Python ignore 경로 없음 — 코드 검증 완료). 검증은 SK하이닉스(false-positive) + 분배형 천정 종목(false-negative) 양면 백필.

**Tech Stack:** Python(thresholds/taxonomy/drift pytest), prompt markdown, opus 백필.

**스펙:** `docs/superpowers/specs/2026-06-13-classification-verdict-discipline-design.md`

**파일 구조:**
- Modify: `kr_pipeline/common/thresholds.py` (신규 상수), `tests/test_common_thresholds.py`
- Modify: `kr_pipeline/llm_runner/risk_flags.py` (topping_distribution 등록), `tests/` 신규 taxonomy 테스트
- Modify: `prompts/analyze_chart_v3.md` (§5.1/§5.2/§6.1/§6.2 신설, §8·cup-tree 교정, SSOT 블록)
- Modify: `tests/test_prompt_threshold_drift.py` (신규 synced 상수)
- Create: `docs/superpowers/threshold-change-checklist` 적용본 (의존성 맵), 천정종목 선정 결과, 검증 아티팩트
- Run: `scripts/export_thresholds.py` (웹 동기화)

**상수 명명 (전 태스크 공유 — 일관성 고정):**
`CLIMAX_GAIN_PCT=25.0`, `CLIMAX_GAIN_WINDOW_WEEKS=3`, `CLIMAX_UP_DAYS_PCT=70.0`,
`CLIMAX_UP_DAYS_WINDOW_MIN=7`, `CLIMAX_UP_DAYS_WINDOW_MAX=15`,
`CLIMAX_MATURITY_WEEKS=18`, `CLIMAX_LATE_MATURITY_WEEKS=12`,
`TOPPING_BELOW_10W_WEEKS=8`, `STOCK_DISTRIBUTION_COUNT_25D=4`.
재사용: `BREAKOUT_VOL_FLOOR`(1.4), `CUP_DEPTH_MAX_NORMAL_PCT`(33.0).

---

### Task 1: thresholds.py 신규 상수 + provenance + 단위테스트

**Files:**
- Modify: `kr_pipeline/common/thresholds.py` (파일 끝에 신규 블록)
- Test: `tests/test_common_thresholds.py`

- [ ] **Step 1: 실패 테스트** — `tests/test_common_thresholds.py` 끝에 추가:

```python
def test_climax_thresholds():
    assert thresholds.CLIMAX_GAIN_PCT == 25.0
    assert thresholds.CLIMAX_GAIN_WINDOW_WEEKS == 3
    assert thresholds.CLIMAX_UP_DAYS_PCT == 70.0
    assert thresholds.CLIMAX_UP_DAYS_WINDOW_MIN == 7
    assert thresholds.CLIMAX_UP_DAYS_WINDOW_MAX == 15
    assert thresholds.CLIMAX_MATURITY_WEEKS == 18
    assert thresholds.CLIMAX_LATE_MATURITY_WEEKS == 12


def test_topping_thresholds():
    assert thresholds.TOPPING_BELOW_10W_WEEKS == 8
    assert thresholds.STOCK_DISTRIBUTION_COUNT_25D == 4
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_common_thresholds.py::test_climax_thresholds tests/test_common_thresholds.py::test_topping_thresholds -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'CLIMAX_GAIN_PCT'`

- [ ] **Step 3: 상수 추가** — `kr_pipeline/common/thresholds.py` 끝에:

```python
# ===== Climax run — §6.1 게이트 (prompts/analyze_chart_v3.md) =====

CLIMAX_GAIN_PCT: Final[float] = 25.0
"""[PRESERVES] climax 가속 상승률 임계 (max(1~3주) 수익률). O'Neil HMMS p.262-263,
Minervini TTLC Ch.9 ('25-50% in 1-3 weeks')."""
CLIMAX_GAIN_WINDOW_WEEKS: Final[int] = 3
"""[PRESERVES] climax 상승률 측정 창 상한(주). HMMS p.262-263 '1-2 weeks', TTLC '1-3 weeks'."""

CLIMAX_UP_DAYS_PCT: Final[float] = 70.0
"""[PRESERVES] climax T4 트리거: 윈도우 내 상승일 비율 임계. TTLC Ch.9 / HMMS p.263 (#4)."""
CLIMAX_UP_DAYS_WINDOW_MIN: Final[int] = 7
CLIMAX_UP_DAYS_WINDOW_MAX: Final[int] = 15
"""[PRESERVES] T4 상승일 측정 윈도우 (거래일 7~15). TTLC Ch.9."""

CLIMAX_MATURITY_WEEKS: Final[int] = 18
"""숫자 [PRESERVES] HMMS p.263 ('usually at least 18 weeks out of a first- or second-
stage base'); **적용은 EXTENDS** — advance-start 앵커에 묶은 hard P1 게이트는 시스템 채택.
drift 테스트 목적 = '이 값 변경 시 §6.1 climax 게이트 재검증 필요' 신호 (책 변경 감지 아님)."""
CLIMAX_LATE_MATURITY_WEEKS: Final[int] = 12
"""숫자 [PRESERVES] HMMS p.263 ('12 weeks or more if ... later-stage base'); 적용 EXTENDS (위와 동일)."""

# ===== Topping/distribution — §6.2 게이트 =====

TOPPING_BELOW_10W_WEEKS: Final[int] = 8
"""[PRESERVES] topping T-B: 10주선 아래 연속 주 임계. O'Neil HMMS p.269 ('living below
the 10-week line for 8-9 weeks')."""

STOCK_DISTRIBUTION_COUNT_25D: Final[int] = 4
"""[DESIGN-JUDGMENT] 종목 25세션 내 분배일 카운트 임계. 분배 *개념*은 책(O'Neil),
카운트 4 는 IBD/community convention — 책 literal 아님. §6 stock-distribution flag +
§6.2 T-D 가 공유 (기존 prompt 리터럴 '4+ distribution days' 를 SSOT 로 승격)."""
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_common_thresholds.py -q`
Expected: PASS (전체)

- [ ] **Step 5: 웹 SSOT 동기화 재생성**

Run: `uv run python scripts/export_thresholds.py && cd web && npx tsc -b`
Expected: `thresholds.generated.ts` 갱신, tsc 0

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/common/thresholds.py tests/test_common_thresholds.py web/src/data/thresholds.generated.ts
git commit -m "feat(thresholds): climax/topping 게이트 상수 신설 (provenance 태그)"
```

---

### Task 2: §6 분배 리터럴 → STOCK_DISTRIBUTION_COUNT_25D 참조 (SSOT 승격)

**Files:**
- Modify: `prompts/analyze_chart_v3.md:267` (§6 stock-distribution check)
- Modify: `tests/test_prompt_threshold_drift.py` (PROMPT_SYNCED + 블록)

**배경:** §6 의 "4+ distribution days" 하드 리터럴을 SSOT 상수로 묶어 §6.2 T-D 와 일관. drift 테스트가 prompt↔SSOT 정합을 강제.

- [ ] **Step 1: drift 테스트에 신규 synced 상수 추가** — `tests/test_prompt_threshold_drift.py` 의 `PROMPT_SYNCED` 리스트에 추가:

```python
PROMPT_SYNCED = [
    "CUP_DEPTH_MAX_NORMAL_PCT",
    "CUP_DEPTH_MAX_BEAR_RECOVERY_PCT",
    "CUP_PRIOR_UPTREND_MIN_PCT",
    "HANDLE_DEPTH_BULL_MIN_PCT",
    "HANDLE_DEPTH_BULL_MAX_PCT",
    "HANDLE_LEGIT_MIN_DAYS",
    "MEASUREMENT_TOLERANCE_PCT",
    "STOCK_DISTRIBUTION_COUNT_25D",
    "CLIMAX_GAIN_PCT",
    "CLIMAX_MATURITY_WEEKS",
    "CLIMAX_LATE_MATURITY_WEEKS",
    "CLIMAX_UP_DAYS_PCT",
    "TOPPING_BELOW_10W_WEEKS",
]
```

- [ ] **Step 2: 실패 확인 (orphan 검출)**

Run: `uv run pytest tests/test_prompt_threshold_drift.py::test_no_orphan_synced_constants -q`
Expected: FAIL — `orphan: SSOT STOCK_DISTRIBUTION_COUNT_25D 이 prompt 블록에 미반영`

- [ ] **Step 3: prompt SSOT 블록에 신규 상수 줄 추가** — `prompts/analyze_chart_v3.md` 의 `<!-- SSOT-THRESHOLDS -->` 블록 안에 추가 (기존 줄들과 같은 `- NAME = VALUE` 형식):

```
- STOCK_DISTRIBUTION_COUNT_25D = 4
- CLIMAX_GAIN_PCT = 25.0
- CLIMAX_MATURITY_WEEKS = 18
- CLIMAX_LATE_MATURITY_WEEKS = 12
- CLIMAX_UP_DAYS_PCT = 70.0
- TOPPING_BELOW_10W_WEEKS = 8
```

- [ ] **Step 4: §6 본문 리터럴을 상수 참조로** — `prompts/analyze_chart_v3.md:267` 교체:

변경 전:
```
- If 4+ distribution days within the past 25 sessions on the stock itself: this stock is being sold by institutions even while in Stage 2. Add `volume_contraction_on_advance` if volume is also drying up on up-days, or demote to `watch`.
```
변경 후:
```
- If `STOCK_DISTRIBUTION_COUNT_25D`+ (=4) distribution days within the past 25 sessions on the stock itself: institutions are selling even in Stage 2. Add `volume_contraction_on_advance` if volume is also drying up on up-days, or demote to `watch`. (This is demote-to-watch per §5.1 — NOT ignore. The same count gates §6.2 T-D for the topping force-ignore, which additionally requires G0 = below the 10-week line.)
```

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_prompt_threshold_drift.py -q`
Expected: PASS (정합 + orphan 없음)

- [ ] **Step 6: 커밋**

```bash
git add prompts/analyze_chart_v3.md tests/test_prompt_threshold_drift.py
git commit -m "feat(prompt): §6 분배 카운트 SSOT 승격 + climax/topping 상수 drift 블록 등록"
```

---

### Task 3: topping_distribution flag → RISK_FLAGS_TAXONOMY 등록

**Files:**
- Modify: `kr_pipeline/llm_runner/risk_flags.py:5-9`
- Test: `tests/test_llm_risk_flags.py` (없으면 생성)

**배경:** §6.2 가 emit 하는 신규 flag `topping_distribution` 가 taxonomy 에 없으면 `store._clean_risk_flags` 가 조용히 drop(경고 로그)함 → 감사 데이터 유실.

- [ ] **Step 1: 실패 테스트** — `tests/test_llm_risk_flags.py` 생성:

```python
from kr_pipeline.llm_runner.risk_flags import RISK_FLAGS_TAXONOMY
from kr_pipeline.llm_runner.store import _clean_risk_flags


def test_topping_distribution_in_taxonomy():
    assert "topping_distribution" in RISK_FLAGS_TAXONOMY


def test_clean_keeps_topping_distribution():
    # taxonomy 등록 flag 는 보존돼야 함 (drop 되면 §6.2 감사 데이터 유실)
    assert _clean_risk_flags(["topping_distribution"]) == ["topping_distribution"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_llm_risk_flags.py -q`
Expected: FAIL — `assert 'topping_distribution' in RISK_FLAGS_TAXONOMY`

- [ ] **Step 3: taxonomy 등록** — `kr_pipeline/llm_runner/risk_flags.py` 의 `RISK_FLAGS_TAXONOMY` frozenset 에 `"topping_distribution"` 추가 (마지막 줄 주석 `# 14종` → `# 15종`):

```python
RISK_FLAGS_TAXONOMY = frozenset({
    "climax_run", "late_stage_base", "extended_from_ma", "faulty_pivot",
    "low_volume_breakout", "narrow_base", "wide_and_loose", "thin_liquidity_us_only",
    "prior_uptrend_insufficient", "volume_contraction_on_advance",
    "reverse_split_distortion", "unfavorable_market_context",
    "etf_methodology_mismatch", "handle_quality",
    "topping_distribution",
})  # 15종
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_llm_risk_flags.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/risk_flags.py tests/test_llm_risk_flags.py
git commit -m "feat(llm): topping_distribution flag taxonomy 등록 (§6.2)"
```

---

### Task 4: prompt §5.1 — risk flag → verdict 매핑 (신설)

**Files:**
- Modify: `prompts/analyze_chart_v3.md` (risk flags 표 직후 §5.1 신설)

**배경:** flag 존재가 곧 verdict 가 아님. 이 섹션이 "ignore=climax/topping only" 의 규범 층.

- [ ] **Step 1: §5.1 삽입** — risk flags 표(`extended_from_ma` 정의가 있는 표) 바로 뒤에 다음 블록 추가:

```
### 5.1 Risk flag → classification influence

A flag's presence does NOT by itself set the verdict.

FORCE-IGNORE (verdict = ignore; stock DROPPED from weekday breakout monitoring)
— ONLY these two, because for a stock passing the Trend Template every week the
only book-grounded reasons it cannot produce a near-term buyable breakout are a
blow-off or a top:
  - climax_run           when the §6.1 gate is fully satisfied (active acceleration)
  - topping_distribution when the §6.2 gate is satisfied (Stage 3→4 / breakdown)

DEMOTE-TO-WATCH (verdict capped at watch; NEVER weekend "entry"; stock REMAINS on
the weekday path; the entry-params stage applies reduced size / tighter stop):
  - late_stage_base (4th+)        → weekday path at ×0.7 size, tighter stop
  - wide_and_loose                → current base not buyable, but may tighten —
                                    keep watching (O'Neil HMMS pp.140-143)
  - volume_contraction_on_advance → demand warning; confirm volume on breakout
  - unfavorable_market_context    → already capped at watch by §3.5; do NOT treat
                                    as a second, independent ignore

INFORMATIONAL (annotates; never changes the verdict alone):
  - extended_from_ma  → price is not a buy point now; the question remains whether a
                        valid pivot exists/forms (pivot-relative discipline)
  - faulty_pivot, narrow_base, low_volume_breakout, prior_uptrend_insufficient,
    reverse_split_distortion, thin_liquidity_us_only
    → qualify the QUALITY/sizing of a SPECIFIC entry; may block THIS pivot, but do
      not by themselves drop a Stage 2 leader to ignore. (low_volume_breakout is
      primarily a weekday entry-gate concern.)

COMBINATION RULE: ignore requires a FORCE-IGNORE condition. Any number of
DEMOTE/INFORMATIONAL flags together cap the verdict at watch — they NEVER compound
into ignore. A leader that is late-stage AND temporarily loose AND extended is
still "watch — tracking for the next clean pivot", not ignore.
```

- [ ] **Step 2: 정합 확인 (drift 테스트 회귀)**

Run: `uv run pytest tests/test_prompt_threshold_drift.py -q`
Expected: PASS (텍스트 추가는 SSOT 블록 불변이라 영향 없음)

- [ ] **Step 3: 커밋**

```bash
git add prompts/analyze_chart_v3.md
git commit -m "feat(prompt): §5.1 risk flag→verdict 매핑 (force-ignore=climax/topping only)"
```

---

### Task 5: prompt §8 + cup-tree 교정 — 잔존 ignore 경로 차단 (핵심 기제 ②)

**Files:**
- Modify: `prompts/analyze_chart_v3.md:36`, `:291` (ignore 가이드 2곳), 1차 라우팅(cup-tree)

- [ ] **Step 1: §8 ignore 가이드 교체 (line 291)** —

변경 전:
```
- **`ignore`**: climax run, wide-and-loose, no base, late-stage with multiple high-impact flags, post-reverse-split distortion, or ETF.
```
변경 후:
```
- **`ignore`**: ONLY when the §6.1 climax gate OR the §6.2 topping gate is satisfied. No other condition produces ignore. "No base / forming base" is NOT ignore — it is watch (base_forming): a TT-passing leader without a current pivot is waiting for one, not disqualified. wide-and-loose / late-stage / extended / volume-contraction / reverse-split are DEMOTE-TO-WATCH or INFORMATIONAL per §5.1, never ignore. (ETF/fund is handled upstream by the Pre-Check.)
```

- [ ] **Step 2: 상단 ignore 설명 교체 (line 36)** —

변경 전:
```
- **ignore**: Despite passing the trend template, this stock is not a Minervini/O'Neil-quality setup. Examples: thin or wide-and-loose base, climax run, late-stage advance, no clean base, post-reverse-split speculation, ETF.
```
변경 후:
```
- **ignore**: Reserved for a stock that, despite passing the trend template, is in a blow-off (climax, §6.1) or topping/distribution (Stage 3→4, §6.2). These are the ONLY two ignore conditions (see §5.1). A forming/absent base, looseness, late-stage, or extension is `watch`, not ignore.
```

- [ ] **Step 3: cup-tree 1차 라우팅 climax 문구 교정 (M3, layer 분리)** — `prompts/analyze_chart_v3.md` 의 1차 라우팅 줄에서 "명백한 climax run = ..." 부분을 다음으로 명시 (climax 가 shape 휴리스틱임을 표시, verdict 는 §6.1 이 결정):

변경 전(해당 구절):
```
**명백한** climax run = 직전 급등 + 단일봉 초대형 거래량·스프레드
```
변경 후:
```
**명백한** climax *형태*(shape 휴리스틱 — pattern 라우팅용. verdict=ignore 는 §6.1 게이트만 결정; 이 형태 신호로 climax_run flag 를 emit 하지 말 것) = 직전 급등 + 단일봉 초대형 거래량·스프레드
```

- [ ] **Step 4: 정합 확인**

Run: `uv run pytest tests/test_prompt_threshold_drift.py tests/test_api_prompts_verify_frozen.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add prompts/analyze_chart_v3.md
git commit -m "fix(prompt): §8 ignore=climax/topping only + no-base→watch + cup-tree climax layer 분리"
```

---

### Task 6: prompt §6.1 — climax_run 게이트 (재정의)

**Files:**
- Modify: `prompts/analyze_chart_v3.md` (risk flags 표의 climax_run 행 축약 + §6.1 신설)

- [ ] **Step 1: climax_run 표 행 축약** — risk flags 표의 climax_run 행을:

변경 전:
```
| `climax_run` | Price up ≥25% in 1–3 weeks; largest weekly price spread and heaviest volume of the current move (Minervini Stage 3 warning) |
```
변경 후:
```
| `climax_run` | Terminal acceleration of a mature advance — see §6.1 gate. Emit ONLY when §6.1 is satisfied; never from a loose "looks parabolic" impression. |
```

- [ ] **Step 2: §6.1 신설** — §6(stock-level distribution) 뒤에 추가:

```
#### 6.1 climax_run — qualification gate

Anchor — "advance start" (= the base-count anchor in §late_stage; SAME week):
The Stage 1→2 transition: the most recent week where, after a preceding Stage 1
(price flat/declining below a flat-or-falling 40-week SMA), price broke out of its
first base on weekly volume ≥ BREAKOUT_VOL_FLOOR (1.4×) of the 50-WEEK average AND
both the 30-week (≈SMA-150) and 40-week (≈SMA-200) lines turned up with price above
them. This one week anchors BOTH base count (= base #1) and the "entire advance"
baseline for P2/T1–T4. Compute the 30/40-week SMAs from the 104-week weekly closes
(or approximate with the supplied daily SMA-150/200); the 50-week volume average
from weekly_ohlcv_recent_104w.
If the anchor lies OUTSIDE the 104-week window (no Stage-1 base + MA turn-up visible,
i.e. >2 years in Stage 2): treat P1 as satisfied, compute P2/T1–T2 extremes over the
visible window only, label baseline "left-censored (advance predates window)". Do NOT
treat the window's left edge as a fresh move-start.

Preconditions (ALL must hold):
- P1 Maturity: ≥ CLIMAX_MATURITY_WEEKS (18) weeks since the anchor, or ≥
  CLIMAX_LATE_MATURITY_WEEKS (12) if the current run emerged from a 3rd-or-later base.
- P2 Acceleration vs the stock's OWN trend: max(1w,2w,3w) return ≥ CLIMAX_GAIN_PCT (25%)
  AND this is the steepest 1–3 week pace of the ENTIRE advance (no earlier rolling
  3-week window since the anchor exceeded it).

Triggers (≥1, measured against the ENTIRE advance since the anchor):
- T1 Largest weekly high-low spread since the advance began
- T2 Heaviest weekly volume since the advance began
- T3 Exhaustion gap on the daily chart
- T4 ≥ CLIMAX_UP_DAYS_PCT (70%) up days over a 7–15 day window (e.g. 8 of 10)
Supporting (strengthens, never sufficient alone): price ≥ 70% above SMA-200.

Exclusion (NARROW — applies ONLY to breakouts from a 1st- or 2nd-stage base):
- E1 If the ≥25% gain occurred within 3 weeks of a valid breakout from base #1 or #2,
  it is LEADERSHIP, not climax — do not emit climax_run. (O'Neil HMMS p.269
  eight-week-hold rule.)
- E1 does NOT apply to breakouts from 3rd-or-later bases: a sharp surge out of a
  late-stage base is exactly where blow-off tops occur — E1 stays silent and this
  gate decides. (Minervini TLSMW Ch.5 pp.82-83; O'Neil HMMS p.268.)

Temporal scope: climax_run describes THIS WEEK. Emit only while terminal acceleration
is in progress or ≤2 weeks past its high. Once price has corrected >15% from the
climax high or 4+ weeks have elapsed, it is post-climax consolidation: do NOT emit.
Refer to the past event in reasoning as "prior climax (history)" — exempt from
consistency rule #2.
```

- [ ] **Step 3: BREAKOUT_VOL_FLOOR 인용 spot-check (비블로킹 #2)** — anchor 가 이 상수를 재사용하므로, thresholds.py 주석의 "O'Neil HMMS Ch.2 p.117 '40% to 50% above normal'" 인용이 실제 책과 일치하는지 확인. **이 상수·인용은 P0-1(2026-05-22)에서 이미 존재하던 것으로 이번 작업의 신규 리스크 아님** — 불일치 발견 시 별도 이슈로 기록만(이 태스크 차단 안 함). 책 실물은 전문가 프로젝트에 있으므로 필요 시 사용자가 전문가에게 확인.

- [ ] **Step 4: 정합 확인**

Run: `uv run pytest tests/test_prompt_threshold_drift.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add prompts/analyze_chart_v3.md
git commit -m "feat(prompt): §6.1 climax 게이트 — anchor+P1/P2+T1~4+E1(1·2차 한정)+temporal"
```

---

### Task 7: prompt §6.2 — topping_distribution 게이트 (신설)

**Files:**
- Modify: `prompts/analyze_chart_v3.md` (§6.1 뒤 §6.2 신설)

- [ ] **Step 0: §5 taxonomy 표에 topping_distribution 행 추가 (Gap A — VD-4 리뷰 발견)** — §5(line 240~)의 risk flags 표에 `handle_quality` 행 다음에 추가 (§5 가 "Select from exactly this taxonomy" 라 표에 없으면 LLM 이 emit 불가):
```
| `topping_distribution` | Stage 3→4 top — emit ONLY when the §6.2 gate is satisfied (force-ignore). Never from a single down week. |
```

- [ ] **Step 1: §6.2 신설** — §6.1 뒤에 추가:

```
#### 6.2 topping_distribution — force-ignore gate (Stage 3→4)

GLOBAL PRECONDITION G0: this gate operates ONLY when the weekly close is BELOW the
10-week SMA. (O'Neil HMMS p.269 Breaking Support; Minervini Stage 4 = price below
declining MAs.) A leader's deepest correction often occurs mid-advance while still
ABOVE the 10-week line — that is a shakeout, not a top, and G0 keeps this gate silent
there.

Force-ignore if G0 holds AND ANY ONE of:
- T-A Largest weekly price DECLINE since the advance began (§6.1 anchor).
      (Minervini TTLC Ch.9; O'Neil HMMS p.268 #2.)
- T-B Lived below the 10-week SMA for ≥ TOPPING_BELOW_10W_WEEKS (8) consecutive weeks
      without a weekly close back above. (O'Neil HMMS p.269.) NOTE: a SINGLE weekly
      close below the 10-week line is a normal pullback, NOT topping — do not
      force-ignore on one week.
- T-C 40-week SMA (≈SMA-200) turns DOWN after a prolonged advance. (HMMS p.269 #4.)
- T-D Heaviest weekly DOWN-volume since the advance began, OR ≥
      STOCK_DISTRIBUTION_COUNT_25D (4) stock-distribution days in the last 25 sessions
      (the §6 count). (The below-10-week condition is already required by G0.)

A force-ignore here overrides any watch-eligible pivot.
```

- [ ] **Step 2: 정합 확인**

Run: `uv run pytest tests/test_prompt_threshold_drift.py -q`
Expected: PASS

- [ ] **Step 3: 커밋**

```bash
git add prompts/analyze_chart_v3.md
git commit -m "feat(prompt): §6.2 topping 게이트 — G0(10주선 아래) 전제 + T-A~D"
```

---

### Task 8: prompt §5.2 — wide_and_loose 상대 측정 (절대 10-15% 대체)

**Files:**
- Modify: `prompts/analyze_chart_v3.md` (wide_and_loose 표 행 + §5.2 신설)

- [ ] **Step 1: 표 행 교체** —

변경 전:
```
| `wide_and_loose` | Weekly price swings > 10–15% during the base; erratic, difficult to trade (O'Neil: 1.5–2.5× general market correction) |
```
변경 후:
```
| `wide_and_loose` | Base is wide/loose/erratic RELATIVE to the stock's OWN normal volatility AND the market — measured over the consolidation window, not single weeks (see §5.2). Demote-to-watch only (a loose base can tighten later — O'Neil HMMS pp.140-143). |
```

- [ ] **Step 2: §5.2 신설** — §5.1 뒤에 추가:

```
### 5.2 wide_and_loose — measurement (replaces the absolute "10–15%" rule)

Apply only if BOTH hold over the consolidation window:
(a) Relative width: the MAJORITY of the base's weekly high-low spreads exceed ~1.5×
    the stock's OWN median weekly spread over the prior ~6 months. An absolute
    10–15% cut flags a high-beta KR leader's every week (a leader's median weekly
    spread can be ~12%); normal volatility is NOT "loose". [1.5× = design-judgment,
    operationalizes O'Neil's qualitative test — not a literal book figure.]
(b) Structural fault: deep + erratic — depth exceeds CUP_DEPTH_MAX_NORMAL_PCT (33%)
    AND the action is V-shaped straight-up / wedging / "large point spreads high-to-
    low each week throughout the base" (O'Neil HMMS pp.140-143).
The old "1.5–2.5× the general-market correction" figure is IBD-workshop convention,
not literal in the source texts.
```

- [ ] **Step 3: 정합 확인**

Run: `uv run pytest tests/test_prompt_threshold_drift.py -q`
Expected: PASS

- [ ] **Step 4: 커밋**

```bash
git add prompts/analyze_chart_v3.md
git commit -m "feat(prompt): §5.2 wide_and_loose 상대측정(자기 중앙값 1.5×) — 과대적용 해소"
```

---

### Task 9: threshold-change-checklist 2축 의존성 맵 작성

**Files:**
- Create: `docs/superpowers/verification/2026-06-13-verdict-discipline-threshold-map.md`

**배경:** CLAUDE.md 규칙 — thresholds.py 변경 + 소비처 수정은 2축 판정 의존성 맵 필수.

- [ ] **Step 1: 의존성 맵 문서 작성** — `docs/superpowers/threshold-change-checklist.md` 의 (b) 템플릿(2축 판정)을 따라 작성. 최소 포함:
  - 1단계(파생): 신규 상수 6종 + 재사용 2종이 만드는 flag/verdict
  - 2단계(소비 룰): `grep -rn` 으로 각 상수 소비처 식별 (CUP_DEPTH→cup gate+§5.2, STOCK_DISTRIBUTION_COUNT_25D→§6+§6.2, BREAKOUT_VOL_FLOOR→low_volume_breakout+§6.1)
  - 3단계(룰 내부 고정상수) 2축표: 각 상수 — 축1(환산 가능?)·축2(영향?)·책정합(PRESERVES/EXTENDS/DESIGN)·후속
  - 소비 경계 1줄: `classification(ignore) → weekly_classification → 평일 트리거 경로(watch/entry 만 감시) 포함/제외`
  - 합격조건 5개 self-review 체크

- [ ] **Step 2: 커밋**

```bash
git add docs/superpowers/verification/2026-06-13-verdict-discipline-threshold-map.md
git commit -m "docs: verdict 규율 threshold 의존성 맵 (2축 판정)"
```

---

### Task 10: 분배형(non-climactic) 천정 종목 선정 — false-negative 검증용

**Files:**
- Create: `data/expert-inquiry/topping_candidates.txt` (선정 결과 기록)

**배경:** §6.2 false-negative 검증엔 *climax 가 아닌 분배형* 천정 종목 필요(climax 형이면 §6.1 이 가려 §6.2 미검증).

- [ ] **Step 1: 후보 추출 쿼리 실행** — 다음 기준으로 데이터에서 추출:

```python
# uv run python 으로 실행
# 조건: (1) 과거 minervini 통과 이력(주도주), (2) 천정 후 10주선 아래 안착(Stage4),
#       (3) 천정 구간 단일주 급락(climax성) 아닌 점진 분배형
import psycopg
conn = psycopg.connect('postgresql://localhost/kr_pipeline')
cur = conn.cursor()
cur.execute("""
  WITH w AS (
    SELECT ticker, week_end_date, adj_close,
           AVG(adj_close) OVER (PARTITION BY ticker ORDER BY week_end_date
             ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS sma10w,
           MAX(adj_close) OVER (PARTITION BY ticker) AS peak
      FROM weekly_prices WHERE week_end_date BETWEEN '2023-01-01' AND '2026-06-01'
  )
  SELECT w.ticker, s.name,
         COUNT(*) FILTER (WHERE w.adj_close < w.sma10w
                          AND w.week_end_date > (SELECT MIN(week_end_date) FROM w w2
                            WHERE w2.ticker=w.ticker AND w2.adj_close=w2.peak)) AS wks_below_after_peak
    FROM w JOIN stocks s ON s.ticker=w.ticker
   WHERE EXISTS (SELECT 1 FROM daily_indicators di
                 WHERE di.ticker=w.ticker AND di.minervini_pass AND di.rs_rating>=90)
   GROUP BY w.ticker, s.name
  HAVING COUNT(*) FILTER (WHERE w.adj_close < w.sma10w) >= 8
   ORDER BY wks_below_after_peak DESC LIMIT 20
""")
for r in cur.fetchall(): print(r)
```

- [ ] **Step 2: 후보 1~2개 수기 검증 + 선정** — 추출 목록에서 주봉 차트로 *분배형*(점진 천정, 단일주 +25% 급등 없음) 확인. climax형(직전 1~3주 급등 후 붕괴)은 제외. **추가 점검(비블로킹 #3)**: 선정 종목의 advance 가 104주 창을 초과(>2년 Stage 2)하면 §6.1 P2 left-censoring 경로를 타므로, 그 종목으로 §6.2 검증 시 anchor 가 "left-censored" 로 잡히는지(T-A 의 "advance 시작 기준" 이 창 안에서만 계산되는지) reasoning 에서 확인. 선정 종목·기간·근거(+ left-censored 여부)를 `data/expert-inquiry/topping_candidates.txt` 에 기록.

- [ ] **Step 3: 커밋**

```bash
git add data/expert-inquiry/topping_candidates.txt
git commit -m "docs: §6.2 false-negative 검증용 분배형 천정 종목 선정"
```

(주의: `data/` 는 gitignore 대상일 수 있음 — `git add -f` 필요 시 사용, 또는 docs/ 로 이동.)

---

### Task 11: 양면 백필 검증 (acceptance gate)

**Files:**
- Create: `data/expert-inquiry/validation_results.md` (결과)

**배경:** prompt 변경은 LLM 판정이라 단위테스트 불가 — opus 백필로 목표 분포 대비 검증. **실 LLM 비용 발생**(SK 47주 + 천정종목). dev API 서버 재기동(prompt 반영) 선행.

- [ ] **Step 1: SK하이닉스 47주 재백필 (false-positive)** — 기존 백필 결과 삭제 후 재실행:

```bash
# 기존 SK 백필 분류 삭제 (재분류 위해)
uv run python -c "import psycopg; c=psycopg.connect('postgresql://localhost/kr_pipeline'); cur=c.cursor(); cur.execute(\"DELETE FROM classification_backfill WHERE symbol='000660' AND analyzed_for_date>='2025-06-01'\"); c.commit(); print('deleted', cur.rowcount)"
KR_CLAUDE_MODEL=claude-opus-4-8 uv run python -m kr_pipeline.llm_runner --mode=backfill --start=2025-06-01 --end=2026-06-01 --tickers=000660
```

- [ ] **Step 2: 목표 분포 검증** — 다음 쿼리로 분포 + §6.2 침묵 확인:

```python
# ignore ~4-6 (2026-05 climax 클러스터만), watch ~46-48, topping_distribution 0건
import psycopg, json
conn=psycopg.connect('postgresql://localhost/kr_pipeline'); cur=conn.cursor()
cur.execute("SELECT classification, COUNT(*) FROM classification_backfill WHERE symbol='000660' AND analyzed_for_date>='2025-06-01' GROUP BY 1")
print("분포:", dict(cur.fetchall()))
cur.execute("SELECT analyzed_for_date FROM classification_backfill WHERE symbol='000660' AND analyzed_for_date>='2025-06-01' AND classification='ignore' ORDER BY 1")
print("ignore 주:", [str(r[0]) for r in cur.fetchall()])
cur.execute("SELECT COUNT(*) FROM classification_backfill WHERE symbol='000660' AND analyzed_for_date>='2025-06-01' AND risk_flags::text LIKE '%topping_distribution%'")
print("topping 발화:", cur.fetchone()[0], "(0 이어야 — SK 는 in-window topping 없음)")
```
Expected: ignore 4~6 (2026-05-09/16/23/30 ± 4월말), topping 0, watch 46~48.
**미달 시**: §6.1 게이트가 2026-05 에 발화하는지 / 다른 주가 여전히 ignore 인지 사유 추적 → 규칙 재조정(iterate). 목표 미달은 plan 실패가 아니라 calibration 신호.

- [ ] **Step 3: 유효 피벗 포착률 KPI** — SK 실측 3피벗(248500/306600/646000)이 실제 돌파된
주(06-17/09-15/01-26) 직전, base 가 형성돼 pivot 이 정의 가능했던 주가 watch(base_forming
또는 valid_base_awaiting_breakout)로 잡혔는지 확인:

```python
import psycopg
conn = psycopg.connect('postgresql://localhost/kr_pipeline'); cur = conn.cursor()
# 3 피벗의 돌파 직전 주(분모) — 표준 베이스 형성 주. 그 주 분류가 watch 이고
# watch_reason 이 base_forming/valid_base_awaiting_breakout 이면 포착(분자).
PIVOT_WEEKS = ['2025-06-14', '2025-09-13', '2026-01-24']  # 돌파 직전 토요일
cur.execute("""SELECT analyzed_for_date, classification, watch_reason, pattern
               FROM classification_backfill WHERE symbol='000660'
                AND analyzed_for_date = ANY(%s) ORDER BY 1""", (PIVOT_WEEKS,))
rows = cur.fetchall()
captured = sum(1 for d,c,wr,p in rows if c=='watch' and wr in ('base_forming','valid_base_awaiting_breakout'))
print(f"유효피벗 포착: {captured}/{len(PIVOT_WEEKS)}")
for r in rows: print(" ", r)
# 목표 ≥90-95% (3/3 이상적). extended-holding(10-04 류)은 fresh-pivot 아니므로 분모 제외.
```
Expected: 3/3 watch 포착 (이전 백필에선 일부가 ignore 였음 — 수정 효과의 직접 지표).

- [ ] **Step 4: 천정 종목 백필 (false-negative)** — Task 10 선정 종목·기간으로:

```bash
KR_CLAUDE_MODEL=claude-opus-4-8 uv run python -m kr_pipeline.llm_runner --mode=backfill --start=<천정시작> --end=<천정종료> --tickers=<선정종목>
```
검증: §6.2 가 천정을 force-ignore 로 잡는지 + **T-A~D 중 무엇이 발화하는지 reasoning 에서 확인, 미발화 트리거는 "미검증"으로 정직 기록**.

- [ ] **Step 5: 결과 문서화 + 커밋**

```bash
# validation_results.md: SK 분포 / KPI / 천정종목 §6.2 발화 트리거 / 미검증 트리거 목록
git add data/expert-inquiry/validation_results.md
git commit -m "docs: verdict 규율 양면 백필 검증 결과 (목표 분포 + §6.2 커버리지)"
```

- [ ] **Step 6: 푸시 + 메모리 기록**

```bash
git push origin main
```
메모리에 검증 결과(목표 달성 여부, 미검증 §6.2 트리거) 기록.
