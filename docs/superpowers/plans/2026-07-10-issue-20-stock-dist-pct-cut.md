# Issue #20 — 종목레벨 분배일 하락 컷 0% → −0.2% 정합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 종목레벨 `distribution_day_flag`(현재 0% 컷 = 모든 하락일)를 prompt §6 정의(close down ≥ 0.2%)와 정합하는 −0.2% 컷으로 교정해 과대 집계(03편 확정모순 B)를 해소한다.

**Architecture:** `STOCK_DISTRIBUTION_PCT_DOWN = -0.2`를 SSOT 신설 → `distribution_day()`가 is_down_day(0% 컷) 대신 일간수익률 `≤ -0.2%` 기준을 사용(A/D ratio의 is_down은 의도적으로 불변 — 전체 하락일 대상). A 프롬프트 SSOT 블록·drift 테스트 등재 + 웹 thresholds.generated.ts 재생성. production 히스토리 재계산은 머지 후 ops(PR 본문 명시).

**Tech Stack:** Python(pandas), pytest(kr_test DB), thresholds SSOT 패턴, scripts/export_thresholds.py.

## Global Constraints

- `uv run pytest tests/` 기대 실패 **0**.
- **threshold-change-checklist 트리거 해당** (thresholds.py 상수 추가 + 소비 계산 로직 수정) → 아래 의존성 맵 필수.
- SSOT 패턴: Python import / UI는 export 스크립트 재실행 / prompt 수동 동기화 (CLAUDE.md).
- 커밋 메시지 Claude co-author trailer 금지.
- **동작 방향 주의: 완화(loosening)** — flag 감소 → §6 강등·§6.2 T-D 게이트 발동 빈도 감소. 정의 정합 복원이지만 보수성이 줄어드는 방향임을 PR에 명시, 발동률 전후 비교를 B-수치로 예약.

## 사전 확인된 사실 (main 16c5bfd)

- `modes.py:158` `is_down = adj_close < adj_close.shift(1)` (0% 컷)이 `:170` up_down_volume_ratio 와 `:173` distribution_day 에 **공용** — 전역 변경 금지, distribution_day 만 분리.
- A §6(:328-333)이 **flag 컬럼을 authoritative 로 선언** ("column is authoritative") — volume.py:101-102 주석("LLM 재계산 시 자연히 −0.2% 적용, 별도 fix 대상 아님")은 그 선언 이전의 낡은 논리 = 사문. flag 가 §6 카운트(STOCK_DISTRIBUTION_COUNT_25D=4)와 §6.2 T-D 게이트를 직접 구동.
- flag 소비처: payload_builder(indicators_recent_60d→A §6), csv_builder(daily.csv), chart_render(차트 분배일 마킹), api/routers·schemas(web), indicators/store.
- halt-day: nullify_halt_adj 로 adj_close NaN → pct_change NaN → 비교 False → `.fillna(False)` — 기존 is_down 과 동일 거동(회귀 없음).
- 기존 가드 테스트 `test_process_ticker_daily_distribution_flag_uses_ssot_threshold`: 마지막 날 **−0.5% 하락** + 1.1× 거래량 → −0.2% 컷에서도 여전히 True (회귀 없음, 전제 유지).

## 임계 변경 의존성 맵 (checklist (b) 2축 판정)

**변경**: `STOCK_DISTRIBUTION_PCT_DOWN = -0.2` 신설 + `distribution_day()` 하락 판정을 0% 컷 → 일간수익률 ≤ −0.2% 로 교정.

**1단계 (파생 신호)**: 하락 컷 → `dist_flag` (daily_indicators.distribution_day_flag) — −0.2%~0% 구간 하락일이 flag 에서 제외됨.

**2단계 (소비 룰)** — `grep -rn "distribution_day_flag"`: ① A §6 종목 분배 카운트(≥4 → watch 강등 + §6.2 T-D 게이트 공급) ② chart_render 분배일 마킹 ③ daily.csv/web UI 표시 ④ payload indicators_recent_60d.

**3단계 (룰 내부 고정 상수) — 2축 판정**:

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| STOCK_DISTRIBUTION_COUNT_25D = 4 (§6 카운트 임계) | 부분 (컷 강화 → 카운트 분포 하향 연동) | **있음** — flag 감소로 §6 강등·§6.2 게이트 발동 빈도 감소 (정의 정합 복원 방향의 의도된 완화) | 컷 −0.2 = PRESERVES (HMMS Ch.9), 4 = EXTENDS | **B-수치** — production 재계산 시 전/후 flag 수·§6 발동 종목 수 비교 기록 (완화 폭 계량) |
| STOCK_DISTRIBUTION_VOL_MULT = 1.0 (거래량 조건) | 불가 (거래량 배수) | 미미 — AND 결합의 독립 조건, 컷 변경이 이 조건 동작 불변 | EXTENDS | 모니터링 (근거: AND 독립 — 조건 자체 무변경) |
| up_down_volume_ratio 의 is_down (0% 컷) | 불가 | **없음 — 의도적 미변경** (A/D ratio 는 전체 하락일 대상이라는 별개 의미론) | EXTENDS (O'Neil A/D simplification) | 코드 주석으로 차등 명문화 (본 계획 Task 2) |
| 시장레벨 DISTRIBUTION_PCT_BASE(−0.2)×σ ratio | 부분 | 미미 — 별도 계산기(market_context)·코드 경로 분리. 단 "시장=σ보정 / 종목=미보정(prompt §6 그대로)" 차등이 생김 | PRESERVES (같은 원전) | 모니터링 + thresholds docstring 에 차등 명문화; 종목 σ보정 도입 여부는 발동률 데이터 후 재검토 |

**소비 경계 (1줄)**: `dist_flag → daily_indicators.distribution_day_flag → payload/차트/CSV/web → analyze_chart_v3 §6 카운트(≥4 강등)·§6.2 T-D 게이트` (LLM 레이어 단일 경로 + 표시 계층).

**게이트 자가 점검**: 맵 ✓ / 3단계 상수 4행 ✓ / 축1·축2 전 칸 ✓ / 축2 있음 행 후속 = B-수치 예약 ✓ / 소비 경계 1줄 ✓.

---

### Task 1: RED — 함수 단위 + 파이프라인 경로 테스트

**Files:**
- Modify: `tests/test_indicators_modes.py` (파이프라인 경로 1건 추가)
- Test(신규 함수 단위): 같은 파일에 추가

- [ ] **Step 1: 실패하는 테스트 2건 작성** — `tests/test_indicators_modes.py` 끝에 추가:

```python
def test_distribution_day_requires_02pct_drop():
    """(#20) 종목 분배일 하락 컷 — prompt §6 정의(≥0.2% 하락)와 정합.

    -0.1% 하락(0%~-0.2% 사이)은 거래량이 충분해도 분배일이 아니어야 한다.
    -0.2% 정확 경계는 포함(≤), -0.5% 는 기존과 동일 True.
    """
    import pandas as pd
    from kr_pipeline.indicators.compute.volume import distribution_day

    ret_pct = pd.Series([None, -0.1, -0.2, -0.5, 0.3])
    vol = pd.Series([1100.0] * 5)
    avg = pd.Series([1000.0] * 5)
    flags = distribution_day(ret_pct, vol, avg)
    assert flags.tolist() == [False, False, True, True, False], (
        f"got {flags.tolist()} — -0.1% 하락일이 분배일로 과대 집계되면 안 됨 (03편 확정모순 B)"
    )


def test_process_ticker_daily_distribution_cut_02pct(db):
    """(#20) 파이프라인 경로 — -0.1% 하락 + 1.1× 거래량은 flag=False 여야 한다."""
    from datetime import date, timedelta
    from kr_pipeline.indicators.modes import _process_ticker_daily

    t = "DISTCUT"
    start = date(2010, 6, 7)  # 기존 DISTSSOT 와 다른 격리 구간 (월요일)
    days = []
    d = start
    while len(days) < 61:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)

    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        for i, day in enumerate(days):
            if i < 60:
                close, vol = 100.0, 1000
            else:
                close, vol = 99.9, 1100  # -0.1% 하락 (0%~-0.2% 사이) + ratio 1.1
            cur.execute(
                """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                       adj_close, adj_high, adj_low, adj_open, adj_volume, volume, value)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)""",
                (t, day, close, close, close, close, close, close, close, close, float(vol), vol),
            )
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close)
                   VALUES ('1001', %s, 2000, 2000, 2000, 2000)
                   ON CONFLICT (index_code, date) DO NOTHING""",
                (day,),
            )
    db.commit()

    try:
        _process_ticker_daily(db, t, "KOSPI", days[0], days[-1], days[0])
        db.commit()
        with db.cursor() as cur:
            cur.execute(
                "SELECT distribution_day_flag FROM daily_indicators WHERE ticker=%s AND date=%s",
                (t, days[-1]),
            )
            flag = cur.fetchone()[0]
        assert flag is False, (
            "-0.1% 하락일이 분배일로 플래깅됨 — prompt §6 정의(≥0.2% 하락)와 불일치 (#20)"
        )
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM stocks WHERE ticker=%s", (t,))
        db.commit()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_indicators_modes.py -k "distribution" -v`
Expected: 신규 2건 FAIL (함수 단위는 시그니처 불일치로 에러 가능 — 그 경우도 "기능 부재" red 로 간주하되, 에러가 아닌 assert 실패가 되도록 GREEN 구현에서 시그니처 확정) / 기존 SSOT 테스트 PASS 유지

### Task 2: GREEN — SSOT 상수 + distribution_day 교정 + 호출부

**Files:**
- Modify: `kr_pipeline/common/thresholds.py` (STOCK_DISTRIBUTION_VOL_MULT 아래)
- Modify: `kr_pipeline/indicators/compute/volume.py:91-104`
- Modify: `kr_pipeline/indicators/modes.py:170-173`

- [ ] **Step 1: thresholds.py 상수 추가**

```python
STOCK_DISTRIBUTION_PCT_DOWN: Final[float] = -0.2
"""종목 레벨 distribution day 의 하락 컷 (% 일간 수익률, 이하 ≤).
책: O'Neil HMMS Ch.9 — 시장 레벨 DISTRIBUTION_PCT_BASE 와 같은 원전.
2026-07-10 (#20): 기존 is_down_day(0% 컷) 사용이 prompt §6 정의 (close down
≥0.2%) 와 불일치해 −0.2%~0% 하락일을 과대 집계 → 정의 정합 복원.
시장 레벨과 달리 σ 보정 미적용 (prompt §6 정의 그대로) — 보정 도입 여부는
발동률 데이터 누적 후 재검토 (B-수치). up/down volume ratio 의 is_down(0% 컷)
은 의도적으로 별개 (A/D 는 전체 하락일 대상)."""
```

- [ ] **Step 2: volume.py distribution_day 교체**

```python
def distribution_day(
    daily_return_pct: pd.Series,
    adj_volume: pd.Series,
    avg_volume_series: pd.Series,
    threshold: float = STOCK_DISTRIBUTION_VOL_MULT,
    down_pct: float = STOCK_DISTRIBUTION_PCT_DOWN,
) -> pd.Series:
    """(daily_return_pct <= down_pct) AND adj_volume > avg_volume * threshold.

    2026-05-22 (P0-2): threshold default 1.25 → 1.0 정렬.
    2026-07-10 (#20): 하락 판정을 is_down_day(0% 컷) → 일간수익률 ≤ −0.2%
    (STOCK_DISTRIBUTION_PCT_DOWN) 로 교정 — prompt §6 정의 (close down ≥0.2%
    on volume > 1.0× of 50-day average) 와 정합. §6 이 flag 컬럼을
    authoritative 로 선언하므로 (column is authoritative) 컷 불일치가 §6
    카운트를 직접 왜곡했었다. up_down_volume_ratio 의 is_down(0% 컷) 은
    A/D 의미론 (전체 하락일) 대로 의도적으로 별개.
    """
    return (
        (daily_return_pct <= down_pct)
        & (adj_volume > (avg_volume_series * threshold))
    ).fillna(False)
```
(import 줄에 `STOCK_DISTRIBUTION_PCT_DOWN` 추가.)

- [ ] **Step 3: modes.py 호출부**

`:170-173` 을:
```python
    ud_ratio_50 = up_down_volume_ratio(adj_volume, is_up, is_down, window=50)
    # threshold/down_pct 미지정 — SSOT default 사용 (VOL_MULT=1.0, PCT_DOWN=-0.2).
    # 과거 threshold=1.25 리터럴이 2026-05-22 SSOT 1.0 정렬(P0-2)을 무력화했었음.
    # (#20) 하락 컷은 §6 정의 정합 — is_down(0% 컷, A/D 용)과 의도적으로 별개.
    # fill_method=None: halt(NaN) 직후일 return 을 NaN 으로 전파 — 기존 is_down
    # 의 halt 거동(비교 False)과 정확히 동일 + pandas pad deprecation 회피 (실측 검증).
    ret_pct = adj_close.pct_change(fill_method=None) * 100.0
    dist_flag = distribution_day(ret_pct, adj_volume, avg_vol_50)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_indicators_modes.py -v`
Expected: 전체 PASS (기존 −0.5% SSOT 테스트 포함)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/common/thresholds.py kr_pipeline/indicators/compute/volume.py kr_pipeline/indicators/modes.py tests/test_indicators_modes.py
git commit -m "fix(indicators): 종목 분배일 하락 컷 0% → -0.2% — prompt §6 정의 정합 (#20)"
```

### Task 3: SSOT 동기화 — 프롬프트 블록·drift 등재·웹 export

**Files:**
- Modify: `prompts/analyze_chart_v3.md` (SSOT 블록 + §6 텍스트 1줄)
- Modify: `tests/test_prompt_threshold_drift.py` (PROMPT_SYNCED)
- Regenerate: `web/src/data/thresholds.generated.ts`

- [ ] **Step 1: drift 등재 (RED)** — PROMPT_SYNCED 의 analyze_chart 리스트에 `"STOCK_DISTRIBUTION_PCT_DOWN"` 추가 → orphan 테스트가 red (블록 미반영).

Run: `uv run pytest tests/test_prompt_threshold_drift.py -v` → Expected: FAIL 1건 (orphan)

- [ ] **Step 2: 프롬프트 반영 (GREEN)** — SSOT 블록에 `- STOCK_DISTRIBUTION_PCT_DOWN = -0.2` 추가 + §6 첫 bullet 을:

```markdown
- A stock distribution day = close down ≥ 0.2% (daily return ≤ STOCK_DISTRIBUTION_PCT_DOWN = -0.2%) on volume > 1.0× of 50-day average.
```

Run: `uv run pytest tests/test_prompt_threshold_drift.py -v` → Expected: PASS

- [ ] **Step 3: 웹 export 재실행**

Run: `uv run python scripts/export_thresholds.py`
Expected: `web/src/data/thresholds.generated.ts` 에 STOCK_DISTRIBUTION_PCT_DOWN 추가됨 (git diff 확인).
(검증됨: export 스크립트는 module-level 상수 자동 추출(:68-75) — 명시 목록 갱신 불필요, 재실행만으로 충분.)

- [ ] **Step 4: 커밋**

```bash
git add prompts/analyze_chart_v3.md tests/test_prompt_threshold_drift.py web/src/data/thresholds.generated.ts
git commit -m "chore(ssot): STOCK_DISTRIBUTION_PCT_DOWN 프롬프트·drift·웹 동기화 (#20)"
```

### Task 4: checklist 적용 이력 + 전체 회귀

- [ ] **Step 1: 적용 이력 append** — threshold-change-checklist.md:

```markdown
- 2026-07-10: #20 종목레벨 분배일 하락 컷 0%→−0.2% 정합 (03편 확정모순 B 수리). STOCK_DISTRIBUTION_PCT_DOWN 신설(SSOT·프롬프트 블록·drift·웹 export 동기). 의존성 맵 = docs/superpowers/plans/2026-07-10-issue-20-stock-dist-pct-cut.md. 방향 = 완화(flag 감소 → §6 발동 감소) — production 재계산 시 전후 발동률 비교 B-수치 예약. A/D ratio 의 is_down(0% 컷)은 의도적 별개 명문화.
```

- [ ] **Step 2: 전체 테스트**

Run: `uv run pytest tests/ -q` → Expected: 실패 0

- [ ] **Step 3: 커밋 + PR** (production 재계산 = 머지 후 ops 임을 PR 본문에 명시)

## Self-Review 체크

1. **Spec coverage**: 컷 통일 ✓ / 의도적 차등(A/D·시장σ) 명문화 ✓ / checklist 맵 ✓ / 백필 재계산 결정(머지 후 ops + B-수치) ✓.
2. **Placeholder scan**: 전 스텝 실코드 ✓.
3. **Type consistency**: `distribution_day(daily_return_pct, ...)` 시그니처가 Task 1 테스트 ↔ Task 2 구현 ↔ Task 2 호출부에서 동일 ✓. 상수명 STOCK_DISTRIBUTION_PCT_DOWN 4곳(thresholds/volume/prompt/drift) 동일 ✓.
