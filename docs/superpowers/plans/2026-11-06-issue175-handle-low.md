# #175 컵손잡이 구조 저점(handle_low) 결정론 산출 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cup_with_handle` 분류 행마다 손잡이 저점(`handle_low`)·구간을 결정론으로 항상 산출해 네 분류 테이블에 저장하고, 검출기 강등 조건을 책 사실에 맞게 교체하며(#175), 입력 창 끝 UTC 결함(#261)을 고친다.

**Architecture:** 기존 `compute_handle_quality` 를 확장한다(파일 유지, 순수 함수 2개 추출). 반환 계약을 "미평가 None / 식별되면 항상 dict(fired 여부 포함 + `structural_low`)" 로 바꾸고, `apply_phase1_gates` 가 `result["structural_low"]` 를 주입하면 세 insert 경로가 신설 컬럼에 저장한다. 과거 행 비교는 읽기 전용 readout 스크립트가 구 규칙(독립 재구현)과 신 규칙을 같은 저장본에 돌려 diff 를 낸다.

**Tech Stack:** Python 3.12 · psycopg 3 · PostgreSQL(schema.sql, kr_test 는 conftest 가 세션 시작 시 재적용) · pytest(`db` fixture) · FastAPI · React/TS(`tsc`).

**Spec:** `docs/superpowers/specs/2026-11-06-issue175-handle-low-design.md` (§3 단계표, §5 상수, §11 빌더 검토 결정). 보조: `docs/superpowers/specs/2026-11-05-issue175-handle-detector-spec.md`(현 동작 S1~S8).

## Global Constraints

- 브랜치 `issue175-handle-redesign`(worktree `.claude/worktrees/i175`, 현재 체크아웃). 커밋 전 `git branch --show-current` 확인, `git add` 는 명시 경로만.
- suite 판정 전 `pgrep -f pytest` 로 동시 실행 없음 확인. 기대 = 0 failed · 1 skipped · 1 deselected.
- KRX·DART·LLM 접촉 0. 운영 DB 쓰기 0(readout 은 SELECT 만, backfill 스크립트 `--apply` 는 이 플랜에서 실행하지 않음).
- `kr_pipeline/db/schema.sql` 변경은 `ADD COLUMN IF NOT EXISTS`. 운영 적용(kr_pipeline psql)은 머지 후 사용자 승인 단계 — 플랜 밖.
- 상수 값(spec §2·§5 그대로): `HANDLE_VOLUME_VS_50D_MAX = 1.0`, `HANDLE_SHAKEOUT_CLOSE_POS_MIN = 0.5`, `VOLUME_DRY_UP_MULT` 0.5 재사용, `HANDLE_LEGIT_MIN_DAYS` 5·`BASE_MIN_DAYS` 5 불변. 프롬프트 파일 변경 0.
- 손절·entry_params·positions·failed_breakout·§8.5 동작 불변. `triggered_rules`·`risk_flags`·`classification` 의 과거 행 불변.
- 커밋 메시지 한국어, Co-Authored-By 트레일러 금지. PR 본문에 "Closes #N" 금지(부정문 포함).

## Review Focus

1. 손잡이 봉의 `high == low`(한 호가 거래일)에 분배 플래그가 켜진 경우 — 0 나눗셈 없이 `close_pos = 0.5` 로 보고 결함으로 세지 않아야 한다 → Task 4 `test_distribution_day_with_zero_range_is_not_defect`.
2. 손잡이 시작일의 `avg_volume_50d` 가 NULL(신규 상장 50일 미만) — (B′) 만 미평가, 저점·(D′)는 정상 산출 → Task 4 `test_b_rule_unevaluated_when_avg50_null_but_low_still_returned`.
3. 신규 행(pivot 정수)에서 어떤 봉도 pivot 에 닿지 않을 때 2단 매칭이 −0.1 로 잘못 잡지 않고 미평가여야 한다 → Task 2 `test_two_pass_does_not_match_when_no_bar_reaches_pivot_minus_tick`.
4. `as_of` 없이 호출(레거시 스크립트)되면 KST 날짜로 폴백해야 하며, 토 06:00 KST 는 금요일 봉을 포함해야 한다 → Task 3 `test_fallback_without_as_of_uses_kst_date`.
5. 게이트가 identity 로 패치된 저장(기존 테스트 다수)에서 `structural_low` 가 없어도 insert 가 NULL 로 성공해야 한다 → Task 6 `test_insert_without_structural_low_stores_null`.

---

### Task 1: (Task 4 로 통합 — 2026-11-06 검토 반영)

상수 삭제·신설은 그 상수를 소비하는 검출기 규칙 교체와 **같은 커밋**이어야 중간 커밋이 깨지지 않는다(`handle_quality.py:119`·`tests/test_compute_handle_quality.py:130` 이 `HANDLE_VOLUME_NOT_CONTRACTING_RATIO` 를 참조). 내용은 Task 4 에 있다.

---

### Task 2: 검출기 S4′ 2단 매칭 · S6′ 가드 · 항상 반환(`structural_low`)

**Files:**
- Modify: `kr_pipeline/llm_runner/compute/handle_quality.py` (전체)
- Modify: `tests/test_compute_handle_quality.py` (`_seed_ohlcv`·`_run` 확장, 기존 단언 2건 변경, 신규 4건)

**Interfaces:**
- Produces: `compute_handle_quality(conn, symbol, classified_at, cls, *, as_of: date | None = None) -> dict | None`
  - `None` = 미평가(S1·S2·림 미회복·하한 미달·`handle_above_pivot`), 사유는 `log.info("[handle_quality] skipped …")`.
  - dict 키: `fired: bool`, `reasons: list[str]`, `weights: list[str]`, `metrics: dict`,
    `structural_low: {"kind": "handle_low", "price": float, "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "days": int}`.
  - `metrics` 키(이 Task 에서 확정): `handle_depth_pct, handle_start, handle_end, handle_days, handle_high(=pivot_eff), handle_low, pivot_eff, pivot_eff_source("exact"|"minus_0_1")`. (B′/D′ 키는 Task 4 가 추가.)
  - 순수 함수 추출: `find_handle_start(rows, cup_bottom_idx, pivot_price) -> tuple[int | None, float, str]`(idx, pivot_eff, source) — rows[i][1] = high.
- 이 Task 에서는 S7 조건(B·D)과 상수 참조는 **기존 코드 그대로**(교체는 Task 4).

- [ ] **Step 1: 테스트 헬퍼 확장** — `_seed_ohlcv(db, ticker, start, bars, *, avg50: float | None = 1000.0)` 로 바꾸고 `daily_indicators` INSERT 에 `avg_volume_50d` 열 추가(값 `avg50`). `_run(db, ticker, bars, start, days_after, *, pivot=100.0, as_of=None, avg50=1000.0)` 로 확장(`_cls(pivot=…)`, `compute_handle_quality(..., as_of=as_of)`).

- [ ] **Step 2: 실패 테스트 작성(4건 + 기존 2건 수정)**

```python
def test_not_fired_returns_dict_with_structural_low(db):
    """(#175) 비발화도 None 이 아니라 fired=False + structural_low 를 돌려준다."""
    start = date(2026, 3, 2)
    r = _run(db, "HQSL", _cup(2000) + _handle(5, low=96, vol=400), start, 20)
    assert r is not None and r["fired"] is False and r["reasons"] == []
    assert r["structural_low"] == {"kind": "handle_low", "price": 96.0,
                                  "start": (start + timedelta(days=5)).isoformat(),
                                  "end": (start + timedelta(days=10)).isoformat(), "days": 6}
    assert r["metrics"]["pivot_eff_source"] == "exact" and r["metrics"]["handle_days"] == 6


def test_two_pass_recovers_legacy_plus_point_one_pivot(db):
    """구 행 pivot = 고점+0.1 — ① 매칭 없음 → ② pivot−0.1 로 고점 당일 매칭(pivot_eff_source=minus_0_1)."""
    start = date(2026, 3, 16)
    cup_eq = _cup(1000)[:5] + [(100, 96, 99, 1000, False)]          # 최고가 100 == 고점
    r = _run(db, "HQLEG", cup_eq + _handle(5, low=90, vol=2000), start, 20, pivot=100.1)
    assert r is not None and r["metrics"]["pivot_eff"] == 100.0 and r["metrics"]["pivot_eff_source"] == "minus_0_1"
    assert r["structural_low"]["price"] == 90.0 and r["metrics"]["handle_start"] == (start + timedelta(days=5)).isoformat()


def test_two_pass_keeps_first_pass_when_a_bar_exceeds_pivot(db):
    """구 행이라도 pivot 을 넘은 봉이 있으면 ① 이 현행과 같은 봉을 잡는다(기존 검출 58행 불변 보장)."""
    start = date(2026, 3, 30)
    r = _run(db, "HQEXC", _cup(1000) + _handle(5, low=90, vol=2000), start, 20, pivot=100.1)   # idx5 high 101 > 100.1
    assert r is not None and r["metrics"]["pivot_eff_source"] == "exact"
    assert r["metrics"]["handle_start"] == (start + timedelta(days=5)).isoformat()


def test_two_pass_does_not_match_when_no_bar_reaches_pivot_minus_tick(db):
    """신규 행(pivot 정수 100)에서 최고가 99 — ①·② 모두 미매칭 → 미평가(None)."""
    start = date(2026, 4, 13)
    cup99 = _cup(1000)[:5] + [(99, 96, 98, 1000, False)]
    assert _run(db, "HQ99", cup99 + _handle(5, low=90, vol=2000), start, 20, pivot=100.0) is None


def test_handle_above_pivot_is_not_a_handle(db):
    """림 봉부터 저가가 전부 pivot 이상(갭상승 돌파 상태) → handle_above_pivot 미평가(None)."""
    start = date(2026, 4, 27)
    gap_rim_and_after = [(105, 101, 104, 1000, False)] * 7          # idx5 림 봉(low 101 ≥ pivot 100) + 6봉
    assert _run(db, "HQABV", _cup(1000)[:5] + gap_rim_and_after, start, 20) is None


def test_missing_base_depth_pct_is_not_a_skip_reason(db):
    """(spec §3 S1) base_depth_pct 전제 제거 — 깊이비 조건이 #177 로 사라져 소비처 없음."""
    start = date(2026, 5, 11)
    _seed_ohlcv(db, "HQNODEP", start, _cup(1000) + _handle(5, low=96, vol=400))
    cls = _cls(base_depth=None, base_start=start, classified_at=datetime(2026, 5, 31, tzinfo=timezone.utc))
    assert compute_handle_quality(db, "HQNODEP", cls["classified_at"], cls) is not None
```

기존 수정: `test_deep_handle_alone_does_not_fire` 와 `test_shallow_handle_dry_volume_no_dist_not_fired` 의 `assert r is None` → `assert r is not None and r["fired"] is False`.

- [ ] **Step 3: 실패 확인** — Run: `uv run pytest tests/test_compute_handle_quality.py -q` → Expected: 신규 5건 + 수정 2건 FAIL(`structural_low` KeyError / None)

- [ ] **Step 4: 구현** — `handle_quality.py`:
  - S1: `base_depth_pct` 존재·`> 0` 전제 두 줄 삭제(`pivot_price is None` 검사는 유지).
  - `find_handle_start(rows, cup_bottom_idx, pivot_price)`: ① `pivot_price` 로 `high ≥ pivot − 1e-6` 첫 idx, 없으면 ② `pivot_price − 0.1` 로 재탐색. 반환 `(idx|None, pivot_eff, source)`.
  - S6′: `handle_low ≥ pivot_eff` → `skip("handle_above_pivot")`.
  - 비발화 분기의 `return None` 을 dict 반환으로 교체(`fired=False, reasons=[], weights=[]`), `structural_low` 는 발화 여부 무관 공통 생성. `metrics["handle_high"] = pivot_eff`, `handle_depth_pct` 분모 `pivot_eff`.
  - 모듈 docstring 에 2026-11-06 변경 요지 + spec 경로 1줄.

- [ ] **Step 5: 통과 확인** — Run: `uv run pytest tests/test_compute_handle_quality.py tests/test_gates_phase1.py -q` → PASS (`gates` 는 `hq.get("fired")` 를 보므로 fired=False dict 에 영향 없음)

- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/llm_runner/compute/handle_quality.py tests/test_compute_handle_quality.py
git commit -m "#175: 검출기 S4′ 2단 pivot 매칭(exact→−0.1)·S6′ handle_above_pivot 가드·structural_low 항상 반환"
```

---

### Task 3: S5′ 창 끝 = `as_of` 포함(#261)

**Files:**
- Modify: `kr_pipeline/llm_runner/compute/handle_quality.py` (SQL `p.date < %s` → `p.date <= %s`, 끝 날짜 결정)
- Modify: `tests/test_compute_handle_quality.py` (신규 3건)

**Interfaces:**
- Consumes: Task 2 서명.
- Produces: 창 끝 규칙 — `as_of` 가 주어지면 `date <= as_of`; 없으면 `date < classified_at.astimezone(ZoneInfo("Asia/Seoul")).date()`(KST 날짜 당일 제외). `_to_date(classified_at)` 의 UTC `.date()` 사용 금지.

- [ ] **Step 1: 실패 테스트 작성**

```python
def test_as_of_window_includes_friday_bar(db):
    """토 06:00 KST(= 금 21:00 UTC) 실행, as_of=금요일 → 금요일 봉이 손잡이에 포함된다(#261)."""
    start = date(2026, 6, 1)
    bars = _cup(1000) + _handle(4, low=96, vol=400)            # 10봉: 06-01~06-10(시드는 달력일 연속)
    bars.append((99, 88, 98, 400, False))                      # 06-11 저가 88
    bars.append((99, 85, 98, 400, False))                      # 06-12(금) 저가 85 ← 포함돼야 함
    _seed_ohlcv(db, "HQFRI", start, bars)
    cls = _cls(base_start=start, classified_at=datetime(2026, 6, 12, 21, 0, tzinfo=timezone.utc))  # 토 06:00 KST
    r = compute_handle_quality(db, "HQFRI", cls["classified_at"], cls, as_of=date(2026, 6, 12))
    assert r is not None and r["structural_low"]["price"] == 85.0 and r["structural_low"]["end"] == "2026-06-12"


def test_as_of_window_excludes_bars_after_as_of(db):
    start = date(2026, 6, 15)
    bars = _cup(1000) + _handle(5, low=96, vol=400) + [(99, 50, 98, 400, False)]   # 마지막 봉(06-26) 저가 50 은 as_of 뒤
    _seed_ohlcv(db, "HQAFT", start, bars)
    cls = _cls(base_start=start, classified_at=datetime(2026, 6, 27, tzinfo=timezone.utc))
    r = compute_handle_quality(db, "HQAFT", cls["classified_at"], cls, as_of=date(2026, 6, 25))
    assert r is not None and r["structural_low"]["price"] == 96.0 and r["structural_low"]["end"] == "2026-06-25"


def test_fallback_without_as_of_uses_kst_date(db):
    """as_of 생략(레거시 스크립트) — KST 날짜 폴백. 금 21:00 UTC = 토 KST → 금요일 봉 포함(구 UTC 폴백이면 제외)."""
    start = date(2026, 7, 6)
    bars = _cup(1000) + _handle(4, low=96, vol=400) + [(99, 88, 98, 400, False), (99, 85, 98, 400, False)]  # 07-16 목·07-17 금
    _seed_ohlcv(db, "HQKST", start, bars)
    cls = _cls(base_start=start, classified_at=datetime(2026, 7, 17, 21, 0, tzinfo=timezone.utc))
    r = compute_handle_quality(db, "HQKST", cls["classified_at"], cls)
    assert r is not None and r["structural_low"]["price"] == 85.0
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_compute_handle_quality.py -k "as_of or fallback" -q` → FAIL(첫·셋째: price 88.0)

- [ ] **Step 3: 구현** — 끝 날짜 헬퍼 `window_end(classified_at, as_of) -> tuple[date, bool]`(끝 날짜, inclusive 여부) 또는 단순 분기; SQL 은 `as_of` 경로 `<=`, 폴백 경로 `<`. `from zoneinfo import ZoneInfo` 사용(`kr_pipeline/llm_runner/__main__.py` 와 동일 표기). `metrics["handle_end"]` 는 실제 마지막 봉 날짜.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_compute_handle_quality.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/llm_runner/compute/handle_quality.py tests/test_compute_handle_quality.py
git commit -m "#261/#175: 검출기 창 끝 = as_of 포함(KST 거래일) — UTC 날짜로 금요일 봉이 빠지던 결함 수정"
```

---

### Task 4: 상수 교체 + S7′ 결함 조건 교체 — (B′) 50일 평균, (D′) 마감 위치, 기록 지표

**Files:**
- Modify: `kr_pipeline/common/thresholds.py:425-427` (`HANDLE_VOLUME_NOT_CONTRACTING_RATIO` 블록 → 삭제·묘비 주석 + 신설 2건)
- Modify: `tests/test_common_thresholds.py:91-93`
- Regenerate: `web/src/data/thresholds.generated.ts` (`uv run python scripts/export_thresholds.py`)
- Modify: `kr_pipeline/llm_runner/compute/handle_quality.py` (SQL 에 `i.avg_volume_50d` 추가, S7 재작성)
- Modify: `tests/test_compute_handle_quality.py` (기존 B·D 테스트 3건 수정, 신규 5건)
- Modify: `tests/test_store_phase1_gate.py:54-57` (`daily_indicators` 시드에 `avg_volume_50d` 1000 추가 — 손잡이 2000 ≥ 1000 로 B′ 발화 유지)

**Interfaces:**
- Consumes: Task 2 반환 계약.
- Produces: `thresholds.HANDLE_VOLUME_VS_50D_MAX: Final[float] = 1.0` `[book-anchor]`(TLSMW Ch.10 p.226 "volume on the final contraction that is below the 50-day average" + p.198·p.245 손잡이 적용; 손잡이 일평균 ÷ `avg_volume_50d(handle_start)` 가 이 값 **이상**이면 미수축 결함), `thresholds.HANDLE_SHAKEOUT_CLOSE_POS_MIN: Final[float] = 0.5` `[design-judgment]`(개념 TLOND Ch.3 p.53~54 "closed … in the upper part of its daily trading range", 2순위; 식 `(close−low)/(high−low)`·0.5 는 설계). `HANDLE_VOLUME_NOT_CONTRACTING_RATIO` 는 존재하지 않는다(묘비 주석 1줄: 정의 원문 `specs/2026-11-05-issue175-handle-detector-spec.md` S7(B), 대체 = `HANDLE_VOLUME_VS_50D_MAX`).
- Produces: 순수 함수 `close_position(high, low, close) -> float`(high == low 면 0.5). `metrics` 추가 키: `avg_volume_50d: float | None`, `handle_avg_volume: float`, `volume_vs_50d: float | None`, `b_unevaluated: bool`, `dry_up_days: int`, `distribution_days: int`(플래그 전부), `distribution_days_lower_close: int`. `ratio_b` 키 **제거**. `reasons` 값 문자열은 기존 그대로(`volume_not_contracting`, `distribution_in_handle`).

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_common_thresholds.py:93` 단언 교체:

```python
    # (#175 2026-11-06) 0.80 컵 평균 비교 삭제 → Minervini 50일 평균 규칙(TLSMW p.226) + shakeout 마감 위치(design)
    assert not hasattr(thresholds, "HANDLE_VOLUME_NOT_CONTRACTING_RATIO")
    assert thresholds.HANDLE_VOLUME_VS_50D_MAX == 1.0
    assert thresholds.HANDLE_SHAKEOUT_CLOSE_POS_MIN == 0.5
    assert thresholds.VOLUME_DRY_UP_MULT == 0.5   # 극저 거래량일 계수(기록용) 재사용
```

`tests/test_compute_handle_quality.py` 신규:

```python
def test_b_rule_fires_when_handle_volume_at_or_above_50d_avg(db):
    start = date(2026, 8, 3)
    r = _run(db, "HQB1", _cup(500) + _handle(5, low=96, vol=1100), start, 20, avg50=1000.0)   # 손잡이 6봉 평균 (500+5×1100)/6 = 1000 ≥ 1000
    assert r["fired"] and r["reasons"] == ["volume_not_contracting"]
    assert r["metrics"]["volume_vs_50d"] == pytest.approx(1.0) and "ratio_b" not in r["metrics"]


def test_b_rule_not_fired_when_handle_volume_below_50d_avg_even_if_above_cup(db):
    """컵 평균(500)보다 많아도 50일 평균(1000) 미만이면 결함 아님 — 구 0.80 컵 비교와 갈리는 지점."""
    start = date(2026, 8, 17)
    r = _run(db, "HQB2", _cup(500) + _handle(5, low=96, vol=900), start, 20, avg50=1000.0)   # (500+5×900)/6 ≈ 833
    assert r["fired"] is False and r["metrics"]["volume_vs_50d"] == pytest.approx(0.8333, abs=1e-3)


def test_b_rule_unevaluated_when_avg50_null_but_low_still_returned(db):
    start = date(2026, 8, 31)
    r = _run(db, "HQB3", _cup(500) + _handle(5, low=96, vol=5000), start, 20, avg50=None)
    assert r is not None and r["fired"] is False and r["metrics"]["b_unevaluated"] is True
    assert r["metrics"]["volume_vs_50d"] is None and r["structural_low"]["price"] == 96.0


def test_distribution_day_lower_close_fires_upper_close_is_shakeout(db):
    """같은 분배 플래그라도 하단 마감(close_pos 0.13)만 결함, 상단 마감(0.81)은 shakeout → 비결함."""
    start = date(2026, 9, 14)
    lower = _cup(1000) + [(99, 98, 98, 400, False), (99, 90, 91, 2000, True), (99, 98, 98, 400, False),
                          (99, 98, 98, 400, False), (99, 98, 98, 400, False)]      # (91−90)/(99−90)=0.11
    upper = _cup(1000) + [(99, 98, 98, 400, False), (99, 90, 97, 2000, True), (99, 98, 98, 400, False),
                          (99, 98, 98, 400, False), (99, 98, 98, 400, False)]      # (97−90)/9=0.78
    r_lo = _run(db, "HQD1", lower, start, 20); r_up = _run(db, "HQD2", upper, start + timedelta(days=30), 20)
    assert r_lo["fired"] and r_lo["reasons"] == ["distribution_in_handle"] and r_lo["metrics"]["distribution_days_lower_close"] == 1
    assert r_up["fired"] is False and r_up["metrics"]["distribution_days"] == 1 and r_up["metrics"]["distribution_days_lower_close"] == 0


def test_distribution_day_with_zero_range_is_not_defect(db):
    start = date(2026, 10, 12)
    flat = _cup(1000) + [(99, 98, 98, 400, False), (95, 95, 95, 2000, True), (99, 98, 98, 400, False),
                         (99, 98, 98, 400, False), (99, 98, 98, 400, False)]
    r = _run(db, "HQD0", flat, start, 20)
    assert r["fired"] is False and r["metrics"]["distribution_days"] == 1 and r["metrics"]["distribution_days_lower_close"] == 0


def test_dry_up_days_counted_from_each_days_50d_avg(db):
    start = date(2026, 10, 26)
    r = _run(db, "HQDRY", _cup(1000) + _handle(5, low=96, vol=400), start, 20, avg50=1000.0)   # 림 봉 1000 제외, 5봉 400 < 500
    assert r["metrics"]["dry_up_days"] == 5 and r["fired"] is False
```

기존 수정: `test_volume_not_contracting_fires`(단언 `ratio_b > …` → `volume_vs_50d >= thresholds.HANDLE_VOLUME_VS_50D_MAX`), `test_handle_exactly_5_days_is_evaluated`·`test_metrics_have_no_ratio_a_but_echo_depth`(발화는 손잡이 3000·2000 ≥ avg50 1000 로 유지, `ratio_b` 참조 제거). `test_distribution_in_handle_fires` 는 변경 불요 — `_handle` 의 dist 봉 (99, 98, 98) 은 마감 위치 0 으로 이미 하단 마감.

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_common_thresholds.py tests/test_compute_handle_quality.py tests/test_store_phase1_gate.py -q` → FAIL(상수 부재·`volume_vs_50d` KeyError)

- [ ] **Step 3: 구현** — thresholds.py 상수 삭제·신설(Interfaces 대로) → `uv run python scripts/export_thresholds.py`(`grep -c NOT_CONTRACTING web/src/data/thresholds.generated.ts` → 0). 검출기: SQL SELECT 에 `i.avg_volume_50d` 추가(인덱스 7). `avg50 = rows[right_rim_idx][7]`; `avg50 is None` → `b_unevaluated=True, fired_b=False, volume_vs_50d=None`; else `volume_vs_50d = handle_avg / avg50`, `fired_b = volume_vs_50d >= thresholds.HANDLE_VOLUME_VS_50D_MAX`. `dry_up_days` 는 봉별 `r[7]` 기준(None 봉 제외). (D′) `close_position` + `thresholds.HANDLE_SHAKEOUT_CLOSE_POS_MIN`. 모듈 상단 docstring 의 "(B) 거래량비 0.80·(D) 분배일 ≥1 불변" 문장을 변경 후 서술로 교체.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_common_thresholds.py tests/test_prompt_threshold_drift.py tests/test_compute_handle_quality.py tests/test_store_phase1_gate.py tests/test_gates_phase1.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/common/thresholds.py tests/test_common_thresholds.py web/src/data/thresholds.generated.ts kr_pipeline/llm_runner/compute/handle_quality.py tests/test_compute_handle_quality.py tests/test_store_phase1_gate.py
git commit -m "#175: 손잡이 거래량 결함 조건 교체 — 0.80 컵 평균 삭제 → (B′) 손잡이 평균 < 50일 평균(TLSMW p.226), (D′) 분배일 ∧ 하단 마감(design 0.5), dry_up_days 기록"
```

---

### Task 5: 게이트 `as_of` 전달 + `structural_low` 주입, 호출처 갱신

**Files:**
- Modify: `kr_pipeline/llm_runner/gates.py:27-40`
- Modify: `kr_pipeline/llm_runner/store.py:331` (`as_of=analyzed_for_date`), `:510` (`as_of=analyzed_for_date`; `gate_at` 는 positional 로 유지)
- Modify: `tests/test_gates_phase1.py` (신규 2건). 게이트 패치 네 곳 **전부** `as_of=` 키워드를 받도록 수정(모두 positional 4인자 형으로 확인됨): `tests/test_llm_runner_store.py:449` `_gates_identity` → `lambda conn, s, t, r, **kw: (r, None)`, `tests/test_backfill_price_sanity.py:30` 동일, `tests/test_issue253_ratchet_replay.py:53` 동일, `tests/test_llm_backfill.py:116` `fake_gate(conn, symbol, classified_at, result, **kw)`
- Modify: `scripts/regression_phase1_2a.py:36,47`, `scripts/verify_005850_handle.py:38` (`as_of=` 는 생략 가능 — 변경 없이 폴백 동작, 주석 1줄만)

**Interfaces:**
- Consumes: Task 2~4 검출기 반환.
- Produces: `apply_phase1_gates(conn, symbol, classified_at, result, *, as_of: date | None = None) -> tuple[dict, dict | None]`. `hq is not None` 이면 `result["structural_low"] = hq["structural_low"]`(fired 무관). 발화 시 `triggered[tier]["handle_quality_metrics"] = hq["metrics"]` 불변.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_gates_phase1.py`

```python
def test_structural_low_injected_even_when_not_fired(monkeypatch, db):
    sl = {"kind": "handle_low", "price": 96.0, "start": "2026-03-09", "end": "2026-03-13", "days": 5}
    monkeypatch.setattr(gates, "compute_handle_quality",
                        lambda *a, **k: {"fired": False, "reasons": [], "weights": [], "metrics": {}, "structural_low": sl})
    monkeypatch.setattr(gates, "compute_failed_breakout", lambda *a, **k: None)
    out, tr = gates.apply_phase1_gates(db, "TSL", datetime(2026, 1, 1, tzinfo=timezone.utc), _base_result(), as_of=date(2026, 3, 13))
    assert out["structural_low"] == sl and out["classification"] == "entry" and tr is None


def test_as_of_is_forwarded_to_detector(monkeypatch, db):
    seen = {}
    def fake(conn, symbol, classified_at, cls, *, as_of=None):
        seen["as_of"] = as_of; return None
    monkeypatch.setattr(gates, "compute_handle_quality", fake)
    monkeypatch.setattr(gates, "compute_failed_breakout", lambda *a, **k: None)
    out, _ = gates.apply_phase1_gates(db, "TAS", datetime(2026, 1, 1, tzinfo=timezone.utc), _base_result(), as_of=date(2026, 3, 13))
    assert seen["as_of"] == date(2026, 3, 13) and "structural_low" not in out
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_gates_phase1.py -q` → FAIL(`as_of` unexpected keyword)

- [ ] **Step 3: 구현** — 서명 확장, `compute_handle_quality(conn, symbol, classified_at, result, as_of=as_of)`, 주입 분기. store 두 호출에 `as_of=analyzed_for_date` 추가(`insert_classification` 의 `analyzed_for_date` 는 None 가능 → 검출기 KST 폴백). identity 패치 람다들을 `lambda conn, s, t, r, **kw: (r, None)` 로.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_gates_phase1.py tests/test_llm_runner_store.py tests/test_store_phase1_gate.py tests/test_backfill_price_sanity.py tests/test_issue253_ratchet_replay.py tests/test_llm_backfill.py tests/test_climax_shadow_backstop.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/llm_runner/gates.py kr_pipeline/llm_runner/store.py tests/test_gates_phase1.py tests/test_llm_runner_store.py tests/test_backfill_price_sanity.py tests/test_issue253_ratchet_replay.py tests/test_llm_backfill.py scripts/regression_phase1_2a.py scripts/verify_005850_handle.py
git commit -m "#175: apply_phase1_gates as_of 전달·structural_low 주입, store 호출 analyzed_for_date 전달"
```

---

### Task 6: 스키마 3열 + 저장

**Files:**
- Modify: `kr_pipeline/db/schema.sql` (361행 `effective_pivot` ALTER 뒤에 네 테이블 `ALTER TABLE … ADD COLUMN IF NOT EXISTS handle_low NUMERIC(12, 4); handle_start DATE; handle_end DATE;` + 주석 블록: 산출 `compute/handle_quality.py`, 저장 `store.insert_*`, NULL 의미, spec 경로)
- Modify: `kr_pipeline/llm_runner/store.py` INSERT 두 곳(컬럼 3개·플레이스홀더·값 — `sl = result.get("structural_low") or {}`)
- Modify: `tests/test_schema_llm_runner.py:4-24`(required 에 3열), `tests/test_schema_backfill.py`(세 테이블 3열 존재 테스트 1건), `tests/test_llm_runner_store.py`(신규 2건), `tests/test_backtest_classification_store.py`(신규 1건)

**Interfaces:**
- Consumes: Task 5 의 `result["structural_low"]`.
- Produces: 컬럼 `handle_low NUMERIC(12,4)`, `handle_start DATE`, `handle_end DATE` × {weekly_classification, classification_backfill, backtest_classification, recall_audit_classification}.

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_schema_backfill.py
def test_handle_low_columns_on_all_classification_tables(db):
    for t in ("weekly_classification", "classification_backfill", "backtest_classification", "recall_audit_classification"):
        with db.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (t,))
            cols = {r[0] for r in cur.fetchall()}
        assert {"handle_low", "handle_start", "handle_end"} <= cols, f"{t}: {cols}"

# tests/test_llm_runner_store.py
def test_insert_persists_structural_low(db, mocker):
    sl = {"kind": "handle_low", "price": 960.0, "start": "2026-03-09", "end": "2026-03-13", "days": 5}
    def gate(conn, s, t, r, **kw):
        r["structural_low"] = sl; return r, None
    mocker.patch("kr_pipeline.llm_runner.store.apply_phase1_gates", side_effect=gate)
    insert_classification(db, symbol="SLW", classified_at=datetime(2026, 3, 14, tzinfo=timezone.utc), market="KOSPI",
                          result=_cls_result(pattern="cup_with_handle", pivot_basis="handle_high"), source="weekend",
                          llm_meta={}, analyzed_for_date=date(2026, 3, 13))
    with db.cursor() as cur:
        cur.execute("SELECT handle_low, handle_start, handle_end FROM weekly_classification WHERE symbol='SLW'")
        assert cur.fetchone() == (Decimal("960.0000"), date(2026, 3, 9), date(2026, 3, 13))

def test_insert_without_structural_low_stores_null(db, mocker):
    _gates_identity(mocker)
    insert_classification(db, symbol="SLN", classified_at=datetime(2026, 3, 14, tzinfo=timezone.utc), market="KOSPI",
                          result=_cls_result(), source="weekend", llm_meta={})
    with db.cursor() as cur:
        cur.execute("SELECT handle_low, handle_start, handle_end FROM weekly_classification WHERE symbol='SLN'")
        assert cur.fetchone() == (None, None, None)
```

`tests/test_backtest_classification_store.py`: 같은 패턴으로 `insert_backfill_classification(..., table="backtest_classification")` 뒤 3열 값 단언 1건(`test_backfill_insert_persists_structural_low`). `SLW` 등 종목은 테스트 안에서 `stocks` INSERT(기존 파일 헬퍼 관례 따름).

- [ ] **Step 2: 실패 확인** — conftest 가 세션 시작에 schema.sql 을 재적용하므로 스키마 테스트는 schema.sql 수정 전까지 FAIL. Run: `uv run pytest tests/test_schema_backfill.py tests/test_llm_runner_store.py -k "handle_low or structural_low" -q` → FAIL

- [ ] **Step 3: 구현** — schema.sql ALTER 4×3 + 주석. store 두 INSERT 에 `handle_low, handle_start, handle_end` 추가(값 `sl.get("price")`, `sl.get("start")`, `sl.get("end")` — ISO 문자열은 psycopg 가 DATE 로 캐스팅하도록 `%s::date` 또는 `date.fromisoformat`; 후자 선택).

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_schema_backfill.py tests/test_schema_llm_runner.py tests/test_llm_runner_store.py tests/test_backtest_classification_store.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/db/schema.sql kr_pipeline/llm_runner/store.py tests/test_schema_llm_runner.py tests/test_schema_backfill.py tests/test_llm_runner_store.py tests/test_backtest_classification_store.py
git commit -m "#175: 분류 4테이블 handle_low·handle_start·handle_end 열 신설·저장"
```

---

### Task 7: API·웹 노출

**Files:**
- Modify: `api/schemas/classification.py` (`ClassificationRow`·`ClassificationHistoryRow` 에 `handle_low: float | None = None`, `handle_start: date | None = None`, `handle_end: date | None = None`)
- Modify: `api/routers/classifications.py:43-57,98-110` (latest CTE·SELECT·매핑), `:138-170` (history: weekly·backfill 양쪽 컬럼 — 백필 테이블에도 열 있음)
- Modify: `web/src/lib/types.ts:296-312, 372-386` (`handle_low?: number | null; handle_start?: string | null; handle_end?: string | null;`)
- Modify: `web/src/components/panels/ClassificationCard.tsx:130-137` (Pivot 블록 아래 1줄: `손잡이 저점 {handle_low}원 (−{(pivot−low)/pivot*100 .toFixed(1)}%)`, 없으면 미표시)
- Test: `tests/test_api_classifications.py`(신규 1건)

**Interfaces:**
- Consumes: Task 6 컬럼.
- Produces: API 필드 3개(두 엔드포인트), 웹 타입 3필드.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_api_classifications.py` 기존 픽스처 관례로 `weekly_classification` 1행(handle_low 960, start 03-09, end 03-13) 시드 후 `GET /api/classifications?ticker=…` 응답 첫 행에 `handle_low == 960.0`, `handle_start == "2026-03-09"`; history 엔드포인트도 같은 값 — 테스트명 `test_classifications_expose_handle_low_fields`.

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_api_classifications.py -q` → FAIL(KeyError)

- [ ] **Step 3: 구현** — 스키마·쿼리·매핑(인덱스는 기존 열 뒤에 덧붙여 기존 매핑 불변), 웹 타입·카드.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_api_classifications.py -q` → PASS. Run: `/Users/hank.es/git/personal/kr-by-claude/web/node_modules/.bin/tsc --noEmit -p web` → rc 0.

- [ ] **Step 5: Commit**

```bash
git add api/schemas/classification.py api/routers/classifications.py web/src/lib/types.ts web/src/components/panels/ClassificationCard.tsx tests/test_api_classifications.py
git commit -m "#175: handle_low·handle_start·handle_end API·분류 카드 노출"
```

---

### Task 8: 저장본 재현 readout(읽기 전용) — 58/58 머지 게이트

**Files:**
- Create: `scripts/issue175_handle_low_readout.py`
- Create: `docs/superpowers/specs/2026-11-06-issue175-handle-low-readout.md` (스크립트 출력 요약 수기 정리)
- Output: `data/verification/issue175_handle_low_readout_<YYYYMMDD>.json`
- Test: `tests/test_issue175_readout.py` (순수 비교 함수 1~2건)

**Interfaces:**
- Consumes: 신 검출기 `compute_handle_quality(conn, symbol, classified_at, cls, as_of=…)`; 구 규칙 = 스크립트 내 `legacy_detect(rows, cls) -> dict | None` 독립 재구현(원본: 스크래치패드 `/private/tmp/claude-503/-Users-hank-es-git-personal-kr-by-claude/4b8ff7d4-ddeb-48ff-bdfe-6b1bff4a8eba/scratchpad/hq_spec_verify_175.py` 의 `spec_detect` — UTC 창 끝·`high ≥ pivot`·0.80 컵 평균·분배일 ≥1 그대로 복사).
- Produces: 순수 함수 `compare_fired_rows(stored_metrics: dict, new: dict) -> dict`(`handle_start`·`handle_high` 일치 여부, `handle_end` 변화) in `kr_pipeline/llm_runner/compute/handle_low_readout.py`(SELECT 없음) — 테스트 대상.
- 대상: `weekly_classification` cwh entry/watch 전 행(≈367) + `backtest_classification` cwh entry/watch(≈2,350). 신 규칙의 `as_of` = `COALESCE(analyzed_for_date, (classified_at AT TIME ZONE 'Asia/Seoul')::date − 1)`.
- 출력 항목(spec §6-2): (a) 발화 58행 `handle_start`·`handle_high` 일치 수 — **58/58 아니면 스크립트 exit 2**, (b) `handle_end` 변화 행 목록(기대 4: 053160·092230·049430·041520), (c) 발화 집합 변화(구 fired → 신 fired 2×2 표, 사유별), (d) 커버리지 전/후·skip 사유 분포·`pivot_eff_source` 분포, (e) `handle_low` 깊이(pivot_eff 대비 %) 중앙·8~12% 밴드 비율·`handle_above_pivot` 건수, (f) LLM `measurements.handle_depth_pct` 와 |차|>3pp 비율.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_issue175_readout.py::test_compare_fired_rows_flags_start_and_end_changes`(stored `{"handle_start":"2026-07-21","handle_high":100.1,"handle_end":"2026-07-24"}` vs new `{"handle_start":"2026-07-21","handle_high":100.1,"handle_end":"2026-07-25"}` → `{"start_match": True, "high_match": True, "end_changed": True}`).

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_issue175_readout.py -q` → FAIL(import)

- [ ] **Step 3: 구현** — 순수 함수 + 스크립트(`load_dotenv`, `psycopg.connect(os.environ["DATABASE_URL"])`, `dict_row`; 스타일은 `scripts/issue129_pivot_continuity_readout.py` 머리말 관례). 실행: `uv run python scripts/issue175_handle_low_readout.py` → JSON 저장 + 표준 출력 요약.

- [ ] **Step 4: 실행·판정** — Run 스크립트 → `(a) 58/58` 확인(exit 0). 결과를 readout .md 에 표로 정리(실측 숫자, 판정 아님). 58/58 이 아니면 **구현 결함**으로 Task 2 로 돌아간다(spec §11 Q3).

- [ ] **Step 5: Commit**

```bash
git add scripts/issue175_handle_low_readout.py kr_pipeline/llm_runner/compute/handle_low_readout.py tests/test_issue175_readout.py docs/superpowers/specs/2026-11-06-issue175-handle-low-readout.md data/verification/issue175_handle_low_readout_*.json
git commit -m "#175: 저장본 재현 readout — 구/신 검출기 diff(58/58 게이트·커버리지·발화 집합·깊이 분포)"
```

---

### Task 9: 과거 행 소급 스크립트(`--plan` 만 실행)

**Files:**
- Create: `scripts/issue175_handle_low_backfill.py`
- Test: `tests/test_issue175_backfill_plan.py`

**Interfaces:**
- CLI: `uv run python scripts/issue175_handle_low_backfill.py --plan [--table weekly_classification|classification_backfill|backtest_classification|recall_audit_classification|all]` / `--apply --table <t>`(기본 all 금지 — 테이블 명시 필수).
- `--plan`: 대상 = `pattern='cup_with_handle' AND handle_low IS NULL`; 신 검출기로 산출해 "채워질 행 수 / 미평가 사유 분포 / `handle_above_pivot` 수" 출력, 쓰기 0.
- `--apply`: `UPDATE <t> SET handle_low=%s, handle_start=%s, handle_end=%s WHERE <PK> AND handle_low IS NULL` 만 — PK 는 테이블별: `weekly_classification` `(symbol, classified_at)`, 나머지 세 테이블 `(symbol, analyzed_for_date)`. 다른 열 불변. **이 플랜에서는 실행하지 않는다**(spec §7, 사용자 승인 후 별도).
- 순수 함수 `plan_rows(rows_with_detect: Iterable[tuple[dict, dict | None]]) -> dict`(집계) in 스크립트 모듈 — 테스트 대상.

- [ ] **Step 1: 실패 테스트 작성** — `test_plan_rows_counts_fill_and_skip_reasons`(입력 3건: dict, None(사유 `handle_above_pivot`), None(사유 `right rim`) → `{"fill": 1, "skip": {"handle_above_pivot": 1, "right rim not recovered after cup bottom": 1}}`). 사유는 검출기 `skip()` 문자열을 스크립트가 로그 캡처 대신 **반환값으로 받도록** 검출기에 `return_skip_reason: bool = False` 키워드를 추가하지 **않고**, 스크립트가 `compute_handle_quality` 를 감싼 `detect_with_reason(conn, …) -> tuple[dict | None, str | None]` 로 로그 핸들러를 임시 부착해 사유를 읽는다(검출기 서명 불변).

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_issue175_backfill_plan.py -q` → FAIL

- [ ] **Step 3: 구현** — 스크립트 + 순수 함수. `--apply` 는 `--table` 없으면 `sys.exit(2)`.

- [ ] **Step 4: 통과·plan 실행** — Run: `uv run pytest tests/test_issue175_backfill_plan.py -q` → PASS. Run: `uv run python scripts/issue175_handle_low_backfill.py --plan --table all` → 숫자를 readout .md §7 에 추기(쓰기 0).

- [ ] **Step 5: Commit**

```bash
git add scripts/issue175_handle_low_backfill.py tests/test_issue175_backfill_plan.py docs/superpowers/specs/2026-11-06-issue175-handle-low-readout.md
git commit -m "#175: 과거 행 handle_low 소급 스크립트(--plan 집계·--apply 테이블 명시 필수)"
```

---

### Task 10: 의존성 맵·문서·용어집·전체 suite

**Files:**
- Modify: `docs/superpowers/specs/2026-11-06-issue175-handle-low-design.md` §5 (2축 표 완성: 1단계 파생·2단계 소비 룰·3단계 고정 상수 `TIER1_CONF_CAP`/`TIER2_CONF_CAP`/`STOCK_DISTRIBUTION_*`/`VOLUME_DRY_UP_MULT`/`HANDLE_LEGIT_MIN_DAYS`, 소비 경계 1줄, (c) 합격 조건 5항 대조)
- Modify: `docs/superpowers/threshold-change-checklist.md` 적용 이력 1줄(2026-11-06)
- Modify: `docs/GLOSSARY.md` §8 (`결정론 검출기`·`분배일`·`입력 창 / 창 끝`·`손잡이 길이` 항목을 변경 후 동작으로 갱신, 변경 이력 1줄)
- Modify: `docs/superpowers/specs/2026-11-05-issue175-handle-detector-spec.md` 머리말에 "S4·S5·S7 은 2026-11-06 설계로 대체(링크)" 1줄

- [ ] **Step 1: 문서 갱신** — 위 네 파일. 의존성 맵 (c) 합격 조건은 checklist §(c) 5항을 표로 대조(각 행 "충족/근거").

- [ ] **Step 1b: VCP 후속 이슈 문안** — 스크래치패드 `issue_vcp_last_contraction_body.md` 에 작성(제목 "VCP last_contraction_low 결정론 산출 — swing 분해(반등 임계 design) · #175 범위 분리", 본문: spec §1 비목표 근거, 회신 Q-D 인용(T 경계 = 되돌림→반등→되돌림, 이전 고점 회복 불요, 반등 임계 책 없음), 실전 저장 6행·백테스트 10행, 완료 조건 3개, deferred·착수 금지). `gh issue create` 는 사용자 지시 후.

- [ ] **Step 2: 전체 suite** — Run: `pgrep -f pytest; uv run pytest tests/ -q 2>&1 | tail -3` → `… passed, 1 skipped, 1 deselected`, 0 failed. Run: `/Users/hank.es/git/personal/kr-by-claude/web/node_modules/.bin/tsc --noEmit -p web` → rc 0.

- [ ] **Step 3: Commit + push + PR 초안**

```bash
git add docs/superpowers/specs/2026-11-06-issue175-handle-low-design.md docs/superpowers/threshold-change-checklist.md docs/GLOSSARY.md docs/superpowers/specs/2026-11-05-issue175-handle-detector-spec.md
git commit -m "#175: 의존성 맵(2축)·checklist 이력·용어집 §8 갱신"
git push -u origin issue175-handle-redesign
```

PR 본문(초안, `gh pr create --draft` 는 사용자 지시 후): 요약 / 변경표(Task 1~9) / 동작 영향(spec §9) / 검증(suite 수치·readout (a)~(f) 숫자·tsc) / 배포 절차(schema 양쪽 psql → 머지 → 라이브 pull → 첫 주말 관측) / 규범 인용(2-1·2-2·3-5·1-2). "Closes" 금지. 관련 #175·#261(검출기 창만 해소, failed_breakout 잔존은 #261 코멘트)·#161(입력 확보).
