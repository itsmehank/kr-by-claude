# §6.1/§6.2 (climax·topping) 정량 게이트 이관 구현 계획 (#44) — v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) 구문으로 추적.

> v2 (2026-07-21): 독립 검토 2기(결정 정합/기술) 발견 상 3·중 7·하 6 전부 반영.
> 핵심 수리 — ① 제3안 enum 강제 지점을 store→프롬프트(§8.5 표·출력 스키마)로 정정,
> ② `climax_topping_gates_echo` 배선 주체 명시(inline_builder 반환 확장+호출자 3곳),
> ③ left-censored "전환 부재" 케이스를 원 확정 규칙(P1 충족 간주)으로 복원(무단 방향
> 변경 회수), ④ 테스트 픽스처 전면 재설계(drift-down — 엄격 부등호·성숙 주수 성립),
> ⑤ Stage1 재형성·50주 창 상수 신설/승격, SCOPE_STALE 상수 제외(지배 규약상 사문).

**Goal:** analyze_chart(A)의 climax(§6.1)·topping(§6.2) 게이트 산술을 결정론 코드로 이관하고, E1 판정 불능 시 제3안(watch 강등+매수 잠금)과 §6.2 shadow backstop을 배선한다.

**Architecture:** gate_precompute(#37) 패턴 재사용 — 순수 함수 모듈(`climax_topping.py`)이 주봉 전 이력을 받아 anchor·게이트를 계산하고, payload_builder 가 `climax_topping_gates` 로 payload 에 탑재(authoritative). 같은 dict 를 inline_builder 가 호출자에 반환 → 호출자가 result 에 echo 주입 → gates.py shadow 가 소비(결정론 값 경로 — LLM 경유 없음). 사후층은 D3 수정안 v1 — book-mandated 분지(G0+T-B / G0+T-D분배일)만 shadow 로그로 시작.

**Tech Stack:** Python(psycopg·순수 함수), pytest(kr_test — conftest 가 `kr_pipeline/db/schema.sql` 재적용), prompts/analyze_chart_v3.md 수동 동기화(SSOT 규약).

## Global Constraints (확정 결정 D1~D6 — 2026-07-20 사용자 확정)

- **D1**: anchor 는 코드가 확정(authoritative). 탐색은 **DB 전 이력**, "가장 최근" Stage 1→2 전환(Stage 4 후 리셋 내장). 코드 anchor 를 payload 에 명시(`anchor_week`)해 LLM base 카운팅과 단일 원점.
- **D1 부속(검토 복원)**: left-censored 는 **진짜 결측(이력 ≤50주)만** — **§6.1 게이트·anchor 의존 필드만 None**(null=보수). §6.2 의 anchor 비의존 게이트(G0/T-B/T-D분배일)는 이력 내 판정 가능하므로 계산한다(판정 가능한 것을 null 화하지 않음 — 라운드 2 N3 확정). **전 이력에 전환이 없는 케이스(줄곧 Stage 2)는 별도 플래그 `no_transition`** — 원 규칙(:365-368) 보존: P1 충족 간주 + 극값은 전체 이력 기준 계산(보호 게이트를 침묵시키지 않음).
- **D2**: base 카운트는 LLM 잔류. P1 후기 완화(12주)·E1 은 LLM 재량(코드 anchor 기점).
- **D2-b**: E1 판정 불능 + 전제·트리거 충족 시 **제3안** — verdict=watch, `watch_reason=suspected_climax_stage_indeterminate`. 강제 지점은 **프롬프트 enum**(§8.5 표·출력 스키마·검증 문구 — store 는 pass-through, 검토 실측). trigger_gate.ALLOWED_WATCH_REASONS **비포함** → breakout_from_watch 미발화, promotion 은 go_now 금지 유형 = 하드 블록(entry_params.py:77-80 SQL 강제 실측 확인).
- **D3**: backstop 수정안 v1 — ①전 입력 결정론 확정+non-null+quality_flag 없음 ②book-mandated 분지만: shadow `would_force` 판정은 G0+T-B / G0+T-D분배일. T-C 는 design-judgment(D5②) — **런타임 shadow 기록에 관측 필드로만 포함**(would_force 판정 비참여; "shadow 로그 전용"의 의미 확정) ③노출 축소 방향만. 활성화 전 shadow 1사이클 + 강제율 상한 사전등록(Task 8 문서에 포함하되 활성화 유예 명시) + 원본 verdict 별도 보존 + gate_version 스탬프. 이 계획은 shadow 까지만.
- **D4**: 검증은 0단계 방법론 + D5 규약별 민감도 + **제3안 발생률 카운터**(watch_reason 발생률 판독 — prereg §7 확약 이행). 소급 재분류 없음.
- **D5**: T4 창(종점=평가일 trailing, 길이=max(7~15) 잠정 — Task 8 민감도 후 확정), T-C 'prolonged'=CLIMAX_MATURITY_WEEKS 재사용, anchor 세부 신설 상수(평탄 밴드·전환 창·**Stage1 재형성 최소 주수**·50주 창 승격). SCOPE_STALE(4주)은 "≤2주 절 지배" 규약상 도달 불가 분기라 **상수 신설 제외**(프롬프트 개정에서 잉여 명시 — 검토 발견).
- **D6**: 프롬프트 §6 이관부만 authoritative-소비 문구로 개정 + **§8.5 watch_reason 표(:454-465)·출력 스키마(:498)·enum 검증 문구(:576)에 6번째 값 추가** + P2 풀링 규약·supporting 70%(프롬프트 잔류) 명문화 + left-censored/no_transition 조항 개정. 코드와 같은 PR.
- 프로젝트 규약: null=보수, 의존성 맵 준수, `scripts/export_thresholds.py` 재실행, 테스트 기대 실패 0, git add 명시 경로만, 이슈 참조는 커밋 본문에만.

## File Structure

- Create `kr_pipeline/llm_runner/compute/climax_topping.py` — anchor + §6.1/§6.2 순수 함수.
- Modify `kr_pipeline/common/thresholds.py` — 신설/승격 상수 6개 (Task 1).
- Modify `api/services/payload_builder.py` — `_fetch_weekly_full`(zero-bar 제외 규약 포함) + `_dist_count_25s` + payload 탑재.
- Modify `api/services/inline_builder.py` — build_analysis_inline 이 `climax_topping_gates` dict 를 함께 반환.
- Modify `kr_pipeline/llm_runner/weekend.py` · `daily_delta.py` · `backfill.py` — 반환된 gates 를 `result["climax_topping_gates_echo"]` 로 주입(echo 배선 — 검토 상2 수리).
- Modify `kr_pipeline/llm_runner/gates.py` — §6.2 shadow backstop.
- Modify `kr_pipeline/llm_runner/store.py` — verdict_original 기록(+watch_reason pass-through 주석).
- Modify `kr_pipeline/db/schema.sql` — `verdict_original TEXT` **4테이블**(weekly_classification·classification_backfill·backtest_classification·recall_audit_classification — 공용 INSERT allowlist 전부, 검토 실측). production 은 psql 수동 양쪽 DB.
- Modify `prompts/analyze_chart_v3.md` — Task 9 범위.
- Create `scripts/stage3_replay_climax_topping.py` + `docs/superpowers/specs/2026-07-21-issue44-stage3-verification-prereg.md`.
- Tests: `tests/test_climax_topping.py`, `tests/test_climax_payload.py`, `tests/test_climax_shadow_backstop.py`.

## 의존성 맵 (threshold-change-checklist — 트리거: 상수 추가/승격 + 소비처 이동 + prompt 임계 텍스트 개정)

**1단계 (파생 신호)**: CLIMAX_*/TOPPING_* → `climax_topping.py` 산출(`anchor_week`·`left_censored`·`no_transition`, `maturity_ok`, `p2_*`, `t1~t4`, `scope_active`, `g0`·`ta~td`, `quality_flag`) → payload `climax_topping_gates` + result echo.

**2단계 (소비 룰)**: ① prompt §6.1/§6.2(개정 후 authoritative 소비) ② gates.py shadow(G0+T-B/G0+T-D분배일) ③ §6 demote-to-watch(:351 — 분배일 상수 공유) ④ trigger_gate.ALLOWED_WATCH_REASONS(제3안 비포함 차단) ⑤ §8.5 표·출력 스키마(enum 6번째 값).

**3단계 고정 상수 — 2축 판정** (값 변경 없음 — 소비 이동/신설/승격):

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| CLIMAX_MATURITY_WEEKS=18 | 불가(주수) | 있음 — 소비 이동 + T-C 'prolonged' 공유 신설(D5②) | PRESERVES(HMMS p.263) | 값 불변·소비 이동. T-C 공유는 D4 재생 발화율 + 런타임 shadow 관측 필드로 실측(근거: 값은 책 그대로, 부적합 시 발화율 이상으로 검출) |
| CLIMAX_LATE_MATURITY_WEEKS=12 | 불가 | 미미 — LLM 잔류(D2), 코드 미소비 | PRESERVES | 모니터링(프롬프트 현행 유지가 곧 후속) |
| CLIMAX_GAIN_PCT=25.0 / GAIN_WINDOW_WEEKS=3 | 부분 | 있음 — P2 소비 이동(k∈{1,2,3} 풀링 규약 — 프롬프트보다 엄격=발화 억제 보수 방향, Task 9 명문화) | PRESERVES | 값 불변·소비 이동, D4 재생 검증 |
| CLIMAX_UP_DAYS_PCT=70 / WINDOW_MIN=7 / MAX=15 | 불가 | 있음 — T4 소비 이동 + 창 규약(D5① trailing·max 잠정) | PRESERVES(수치)/EXTENDS(규약) | Task 8 민감도(max vs 고정 10일) 후 확정 |
| TOPPING_BELOW_10W_WEEKS=8 | 불가 | 있음 — T-B 소비 이동 + shadow 분지 | PRESERVES(HMMS p.269) | 값 불변. shadow 1사이클 후 활성화 별도 결정 |
| STOCK_DISTRIBUTION_COUNT_25D=4 | 부분 | 있음 — T-D 소비 이동 + §6 demote(:351) 공유 유지(실물 확인) | PRESERVES | prompt SSOT 블록에 공유 명시(Task 9) |
| BREAKOUT_VOL_FLOOR=1.4 | 가능 | 있음 — anchor 신규 소비로 3중 공유(§6.1 텍스트·B vol band·anchor) | PRESERVES | 값 불변. 이 행이 3중 공유 기록 — 값 변경 시 3곳 동시 재검토 트리거 |
| **승격** CLIMAX_ANCHOR_VOL_AVG_WEEKS=50 | 불가(주수) | 있음 — anchor 거래량 평균 창 + **left-censored 결측 임계 겸용**(이력 ≤50주) — v1 맵 누락분(검토 중5) | PRESERVES(:359 "50-WEEK average") | 프롬프트 문언 승격, 하드코딩 금지 |
| **신설** CLIMAX_ANCHOR_FLAT_BAND_PCT=2.0 | 가능(%) | 있음 — Stage1 '평평/하락' 40주선 기울기 밴드 | EXTENDS | **B-수치** — D4 anchor 안정성 검증 후 재검토 |
| **신설** CLIMAX_ANCHOR_TURNUP_WEEKS=4 | 불가 | 있음 — 30/40주선 상승 전환 판정 창 | EXTENDS | **B-수치** — 동상 |
| **신설** CLIMAX_ANCHOR_STAGE1_MIN_WEEKS=4 | 불가 | 있음 — Stage1 재형성: 직전 N주 **연속** close<40주선 요구. 1주 단일 조건이면 상승 중반 shakeout 1주가 anchor 오탈취(검토 중6 — D1 '가장 최근' 의도 훼손 방지) | EXTENDS(D5 결정문 예고분) | **B-수치** — D4 재생에서 anchor 안정성·오탈취 0 검증 |
| **신설** CLIMAX_SCOPE_PAST_HIGH_WEEKS=2 / SCOPE_CORRECTION_PCT=15.0 | 부분 | 있음 — temporal scope 소비 이동(:394-396 승격). CORRECTION 은 고점 후 0~2주 창 내 유효. **STALE(4주)은 지배 규약상 도달 불가 → 신설 제외**(검토 중 — 사문 상수 방지), 프롬프트 개정에서 잉여 명시 | PRESERVES(승격) | 값 불변 승격. 회색지대 "≤2주 절 지배" 코드화 |

**소비 경계 (1줄)**: `climax_topping_gates` → prompt §6.1/§6.2 verdict + gates.py shadow(triggered_rules) → weekly_classification(verdict_original 병기) → 평일 트리거·entry_params 상류.

**합격 조건 self-check**: 맵 존재 ✓ / 3단계 상수 전 행(50주 창 포함) ✓ / 축1·축2 전 칸 ✓ / 영향있음 행 후속 전부 예약 또는 근거 있는 모니터링 ✓ / 소비 경계 ✓.

---

### Task 1: 상수 6개(신설 5+승격 1) + export

**Files:** Modify `kr_pipeline/common/thresholds.py` / 재실행 `scripts/export_thresholds.py`

**Interfaces:** Produces — `CLIMAX_ANCHOR_VOL_AVG_WEEKS=50`, `CLIMAX_ANCHOR_FLAT_BAND_PCT=2.0`, `CLIMAX_ANCHOR_TURNUP_WEEKS=4`, `CLIMAX_ANCHOR_STAGE1_MIN_WEEKS=4`, `CLIMAX_SCOPE_PAST_HIGH_WEEKS=2`, `CLIMAX_SCOPE_CORRECTION_PCT=15.0` (전부 `Final`, 의존성 맵 행 요약 주석 + 출처 태그).

- [ ] Step 1: 상수 6개 추가(§6.1 블록 인근). SCOPE_STALE 은 넣지 않음 — 주석으로 "4주 절은 ≤2주 지배 규약상 잉여(§6.1 개정 참조)" 기록.
- [ ] Step 2: `uv run python scripts/export_thresholds.py` → generated.ts diff 확인.
- [ ] Step 3: `uv run pytest tests/ -q -k threshold` PASS.
- [ ] Step 4: 커밋 `feat(thresholds): 44번 D5 anchor·scope 상수 6종`.

### Task 2: find_anchor (TDD — drift-down 픽스처)

**Files:** Create `kr_pipeline/llm_runner/compute/climax_topping.py` / Test `tests/test_climax_topping.py`

**Interfaces:** Produces —
```python
def find_anchor(weekly: list[dict]) -> dict
# weekly: 오름차순 [{week_end, open, high, low, close, volume}] (adj 전 이력, zero-bar 제외 입력)
# 반환: {"anchor_week": str|None, "left_censored": bool, "no_transition": bool, "weeks_since": int|None}
#  - left_censored: 이력 ≤ CLIMAX_ANCHOR_VOL_AVG_WEEKS(50)주 (탐색 자체 불가) → 게이트 전부 None
#  - no_transition: 이력 충분한데 전환 부재(줄곧 Stage 2 등) → P1 충족 간주 모드(원 규칙 보존)
# anchor 판정(가장 최근 주 w): Stage1 선행 = 직전 CLIMAX_ANCHOR_STAGE1_MIN_WEEKS(4)주 연속
#  close < 그 주의 40주 SMA AND 40주 SMA 4주 기울기 ≤ +CLIMAX_ANCHOR_FLAT_BAND_PCT(2.0)% ;
#  w 에서 volume ≥ BREAKOUT_VOL_FLOOR×50주 평균 AND s30/s40 이 TURNUP_WEEKS(4)주 전 대비 상승
#  AND close > s30, s40.
```

- [ ] Step 1: 픽스처 생성기 + 실패 테스트 4본. **픽스처 원칙(검토 상1·중4 수리)**: 평탄 구간은 정확 상수가 아니라 **완만한 하락 드리프트**로 만들어 `close < SMA` 엄격 부등호가 항상 성립하게 한다(하락 시계열에서 close 는 trailing 평균보다 항상 낮다).

```python
def _mk_weeks(rows: list[tuple[float, int]], start="2018-01-05") -> list[dict]:
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [{"week_end": str(d0 + timedelta(weeks=i)), "open": p, "high": p * 1.02,
             "low": p * 0.98, "close": p, "volume": v} for i, (p, v) in enumerate(rows)]

def _drift(n: int, top: float, bot: float, vol: int = 100_000) -> list[tuple[float, int]]:
    step = (top - bot) / max(n - 1, 1)
    return [(top - step * i, vol) for i in range(n)]

def _fixture_single_transition():
    # 65주 완만 하락(1000→980, close<SMA 상시 성립) + 돌파주(1100, 2.6×vol) + 19주 상승
    rows = _drift(65, 1000.0, 980.0) + [(1100.0, 260_000)] \
         + [(1100.0 + 15 * i, 110_000) for i in range(1, 20)]
    return _mk_weeks(rows)

def test_anchor_finds_transition():
    wk = _fixture_single_transition()
    r = find_anchor(wk)
    assert r["left_censored"] is False and r["no_transition"] is False
    assert r["anchor_week"] == wk[65]["week_end"]
    assert r["weeks_since"] == 19

def test_anchor_resets_after_stage4():
    # 1차 상승 → Stage 4 급락 → 55주 하락 드리프트 → 2차 돌파: '가장 최근' 전환을 잡아야
    rows = ([(1000.0 + 30 * i, 100_000) for i in range(30)]        # 1차 상승
            + _drift(20, 1900.0, 700.0)                            # Stage 4
            + _drift(55, 700.0, 660.0)                             # Stage 1 재형성
            + [(800.0, 300_000)]                                   # 2차 전환 (idx 105)
            + [(800.0 + 20 * i, 110_000) for i in range(1, 6)])
    wk = _mk_weeks(rows)
    assert find_anchor(wk)["anchor_week"] == wk[105]["week_end"]

def test_anchor_left_censored_short_history():
    wk = _mk_weeks(_drift(40, 1000.0, 980.0))          # 이력 40주 ≤ 50주
    assert find_anchor(wk) == {"anchor_week": None, "left_censored": True,
                               "no_transition": False, "weeks_since": None}

def test_anchor_no_transition_long_stage2():
    # 80주 내내 완만 상승(전환 조건 부재, 이력 충분) → no_transition (P1 간주 모드)
    wk = _mk_weeks([(1000.0 + 10 * i, 100_000) for i in range(80)])
    r = find_anchor(wk)
    assert r["left_censored"] is False and r["no_transition"] is True
    assert r["anchor_week"] is None
```

- [ ] Step 2: `uv run pytest tests/test_climax_topping.py -q` → FAIL(모듈 없음) 확인.
- [ ] Step 3: 구현 —

```python
from kr_pipeline.common.thresholds import (
    BREAKOUT_VOL_FLOOR, CLIMAX_ANCHOR_FLAT_BAND_PCT, CLIMAX_ANCHOR_STAGE1_MIN_WEEKS,
    CLIMAX_ANCHOR_TURNUP_WEEKS, CLIMAX_ANCHOR_VOL_AVG_WEEKS,
)

def _sma(vals, i, n):
    return sum(vals[i - n + 1 : i + 1]) / n if i + 1 >= n else None

def find_anchor(weekly: list[dict]) -> dict:
    closes = [w["close"] for w in weekly]
    vols = [w["volume"] or 0 for w in weekly]
    n = len(weekly)
    W = CLIMAX_ANCHOR_VOL_AVG_WEEKS
    if n <= W:  # 이력 ≤50주 = 탐색 불가 결측 (실효 경계 문서 일치 — 검토 하 수리)
        return {"anchor_week": None, "left_censored": True,
                "no_transition": False, "weeks_since": None}
    k = CLIMAX_ANCHOR_TURNUP_WEEKS
    s1 = CLIMAX_ANCHOR_STAGE1_MIN_WEEKS
    for i in range(n - 1, W - 1, -1):  # i=W(=50) 포함 — n=51 폴스루가 no_transition(P1 간주)으로 새는 회귀 방지(라운드 2 N2)
        s30, s40 = _sma(closes, i, 30), _sma(closes, i, 40)
        s30p, s40p = _sma(closes, i - k, 30), _sma(closes, i - k, 40)
        v_avg = sum(vols[i - W : i]) / W
        if None in (s30, s40, s30p, s40p) or v_avg <= 0:
            continue
        # Stage1 재형성: 직전 s1(4)주 연속 close < 그 주의 40주 SMA (검토 중6)
        stage1 = all(
            (sm := _sma(closes, j, 40)) is not None and closes[j] < sm
            for j in range(i - s1, i))
        prev_s40, prev_s40k = _sma(closes, i - 1, 40), _sma(closes, i - 1 - k, 40)
        slope_ok = (prev_s40 and prev_s40k
                    and (prev_s40 - prev_s40k) / prev_s40k * 100 <= CLIMAX_ANCHOR_FLAT_BAND_PCT)
        if (stage1 and slope_ok and vols[i] >= BREAKOUT_VOL_FLOOR * v_avg
                and s30 > s30p and s40 > s40p
                and closes[i] > s30 and closes[i] > s40):
            return {"anchor_week": weekly[i]["week_end"], "left_censored": False,
                    "no_transition": False, "weeks_since": n - 1 - i}
    return {"anchor_week": None, "left_censored": False,
            "no_transition": True, "weeks_since": None}
```

- [ ] Step 4: PASS 확인. 픽스처 여유 검산(테스트 내 주석): 드리프트 하락 구간에서 close<SMA 성립·slope 음수·돌파주 SMA 상회 마진. 실패 시 **로직 완화 금지** — 픽스처 마진만 조정.
- [ ] Step 5: 커밋 `feat(climax): anchor 전 이력 탐색 — D1·Stage1 재형성 규약`.

### Task 3: §6.1 게이트 (TDD)

**Files:** Modify `climax_topping.py` / Test `tests/test_climax_topping.py`

**Interfaces:** Produces —
```python
def compute_climax_gates(weekly, daily_20d, anchor) -> dict
# 키: maturity_weeks, maturity_ok, p2_best_roll_pct, p2_is_steepest, p2_accel_ok,
#     t1_max_spread_now, t2_max_volume_now, t3_gap_up_today, t4_up_days_pct_max, t4_ok,
#     supporting_ext_sma200_pct(값만 — 70% 판정은 프롬프트 잔류, Task 9 명문화),
#     scope_active, baseline("anchored"|"no_transition"|None), quality_flag
# 모드: left_censored → 전부 None / no_transition → maturity_ok=True(간주),
#      극값·P2 는 전체 이력 기준, baseline="no_transition" (원 규칙 보존 — v2 복원)
# quality_flag: 입력 주봉에 close<=0/None 존재 시 True + 해당 게이트 None (검토 하 수리)
```

- [ ] Step 1: 실패 테스트 4본 — anchored 발화 / scope 만료 / left-censored 전부 None / no_transition P1 간주:

```python
def _fixture_climax_run():
    # anchor(idx 65) + 상승 19주 + 클라이맥스 3주 = anchor 후 22주 (maturity 22 ≥ 18 — 검토 상2 수리)
    rows = _drift(65, 1000.0, 980.0) + [(1100.0, 260_000)] \
         + [(1100.0 + 15 * i, 110_000) for i in range(1, 20)] \
         + [(1500.0, 300_000), (1700.0, 350_000), (1950.0, 900_000)]
    return _mk_weeks(rows)

def test_climax_gates_fire_on_vertical_run():
    wk = _fixture_climax_run()
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=8), find_anchor(wk))
    assert g["baseline"] == "anchored" and g["maturity_weeks"] == 22
    assert g["maturity_ok"] is True
    # 3주 롤링: 1950/1385(k=3, idx 87/84) ≈ +40.8% ≥ 25%, 상승 전체 최급 (검토: k 주석 정정)
    assert g["p2_accel_ok"] is True
    assert g["t2_max_volume_now"] is True and g["t4_ok"] is True
    assert g["scope_active"] is True

def test_climax_gates_scope_expires():
    rows = _drift(65, 1000.0, 980.0) + [(1100.0, 260_000)] \
         + [(1100.0 + 40 * i, 110_000) for i in range(1, 20)] \
         + [(1850.0, 120_000), (1840.0, 100_000), (1830.0, 100_000)]  # 고점 후 3주 횡보
    wk = _mk_weeks(rows)
    assert compute_climax_gates(wk, _mk_daily_updays(10, up=5), find_anchor(wk))["scope_active"] is False

def test_climax_gates_all_none_when_left_censored():
    wk = _mk_weeks(_drift(40, 1000.0, 980.0))
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=5), find_anchor(wk))
    assert g["maturity_ok"] is None and g["p2_accel_ok"] is None and g["baseline"] is None

def test_climax_gates_no_transition_presumes_p1():
    wk = _mk_weeks([(1000.0 + 10 * i, 100_000) for i in range(80)])
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=5), find_anchor(wk))
    assert g["baseline"] == "no_transition" and g["maturity_ok"] is True  # 간주(원 규칙)
```

(`_mk_daily_updays(n, up)` — 최근 n 거래일 중 up 일 전일比 상승 합성 일봉, 테스트 파일 상단 정의.)

- [ ] Step 2: FAIL → Step 3: 구현 — P2 는 k∈{1,2,3} 풀링 best_now ≥ best_ever(동률 허용 — 프롬프트보다 엄격=보수, Task 9 에서 문언 동기화). T4 는 종점=마지막 거래일 고정, 길이 7~15 전부의 상승일 비율 max(D5① 잠정 주석). scope: 고점 주 경과 ≤ CLIMAX_SCOPE_PAST_HIGH_WEEKS(2) AND 고점 대비 조정 ≤ CLIMAX_SCOPE_CORRECTION_PCT(15%) — 2주 초과 즉시 False(지배 규약, STALE 분기 없음). no_transition 모드는 극값·P2 를 전체 이력로 계산하고 maturity_ok=True.
- [ ] Step 4: PASS → Step 5: 커밋.

### Task 4: §6.2 게이트 (TDD)

**Files:** Modify `climax_topping.py` / Test `tests/test_climax_topping.py`

**Interfaces:** Produces —
```python
def compute_topping_gates(weekly, dist_count_25s, anchor) -> dict
# g0_below_10w, tb_weeks_below_10w, tb_ok, td_max_down_volume_now(anchor 의존),
# td_dist_ok(분배일≥4 — book 분지), ta_max_decline_now(anchor 의존),
# tc_sma40_turndown, tc_prolonged_ok(D5② — shadow 관측 전용), quality_flag
# anchor 의존 필드는 anchored 가 아니면(no_transition 은 전체 이력 기준으로 계산) —
# left_censored 면 None. G0/T-B/T-D분배일은 anchor 비의존(검토 확인 — 항상 계산).
```

- [ ] Step 1: 실패 테스트 3본 — v1 픽스처가 손계산 검증을 통과했으므로 유지(`test_topping_g0_tb_fire`(40상승+12하락, tb 9주 연속) / `test_topping_silent_without_g0` / `test_topping_dist_none_conservative`(dist_count None→td_dist_ok None)). 단 `_mk_weeks` 신형 시그니처로 이식.
- [ ] Step 2: FAIL → Step 3: 구현 → Step 4: PASS → Step 5: 커밋.

### Task 5: payload 통합

**Files:** Modify `api/services/payload_builder.py` / Test `tests/test_climax_payload.py`

**Interfaces:** Produces — payload 키 `climax_topping_gates`(두 dict 병합 + anchor_week·left_censored·no_transition), `_fetch_weekly_full(conn, ticker, on_date)`(LIMIT 없음 + **zero-bar 제외**: `NOT (open=0 AND high=0 AND low=0 AND volume=0)` — daily(:199)와 동일 규약, 검토 하 수리), `_dist_count_25s(indicators_60d) -> int|None`(**마지막 25행 미만 또는 flag None 포함 시 None** — null=보수, 검토 하 수리).

- [ ] Step 1: 실패 테스트 — kr_test 시드 후 build_payload: 키 존재·anchor_week 일치·기존 키 보존·dist 부분결측 시 td_dist_ok None.
- [ ] Step 2: FAIL → Step 3: 구현(빌드 스니펫은 v1 과 동일하되 `_dist_count_25s` 사용) → Step 4: 전체 suite 0 실패 → Step 5: 커밋.

### Task 6: 제3안 — 차단 고정 테스트 + 문서화 (v2 재기술: 검토 상1)

**Files:** Modify `kr_pipeline/llm_runner/store.py`(주석만 — pass-through 인 `_watch_reason` 에 6번째 enum 존재와 프롬프트가 강제 지점임을 기록) / Test `tests/test_climax_shadow_backstop.py`

**Interfaces:** enum 값 `suspected_climax_stage_indeterminate` (36자 ≤ VARCHAR(40) 확인 완료). ALLOWED_WATCH_REASONS 는 수정하지 않음(비포함=차단).

- [ ] Step 1: **고정(characterization) 테스트** 2본 — 이미 green 임을 명시(red 단계 없음 — store 는 pass-through 라는 검토 실측 반영). ① trigger 차단(v1 테스트 그대로 — `evaluate(...)` 가 `breakout_from_watch` 아닌 `"promotion"` 반환 assert), ② store 왕복: 이 watch_reason 으로 insert 후 재조회 일치(스키마 CHECK 부재 확인 겸 회귀 고정).
- [ ] Step 2: 두 테스트 즉시 PASS 확인(고정 목적) → Step 3: store.py `_watch_reason` 주석 추가 → Step 4: 커밋 `test(store): 제3안 watch_reason 차단·왕복 고정 — D2-b`.

### Task 7: echo 배선 + §6.2 shadow backstop + verdict_original

**Files:** Modify `api/services/inline_builder.py` · `kr_pipeline/llm_runner/weekend.py` · `daily_delta.py` · `backfill.py` (echo 배선 — 검토 상2 수리) · `kr_pipeline/llm_runner/gates.py` · `store.py` · `kr_pipeline/db/schema.sql` / Test `tests/test_climax_shadow_backstop.py`

**Interfaces:** Consumes — Task 5 payload. Produces —
```python
build_analysis_inline(...) -> tuple[str, list[str], bytes, dict]
# (inline_text, png_paths, freeze_bytes, climax_topping_gates) — 기존 3-튜플에 4번째
# 원소 추가(첨부 PNG·freeze ZIP 경로 보존 — 라운드 2 N1). 호출자 3곳 언팩 갱신.
# 호출자 3곳: result["climax_topping_gates_echo"] = gates  (LLM 출력 파싱 직후 주입 —
# 결정론 값 경로, LLM 경유 없음 = D3 ① '결정론 확정' 충족)
# gates.py: triggered_rules["6_2_topping_shadow"] = {shadow: True, would_force: "ignore",
#   inputs: {g0, tb_ok, td_dist_ok}, observe: {tc_sma40_turndown, tc_prolonged_ok},  ← T-C 관측 전용
#   gate_version: "44-v1"}  # verdict 무변경
# store: verdict_original 컬럼(4테이블) = 게이트 적용 전 LLM 원본 classification
```

- [ ] Step 1: 실패 테스트 — ① 반환형은 **inline_builder 단위**(4-튜플·gates dict 내용), 주입은 **호출자 함수 단위 모킹**(build_analysis_inline 자체를 모킹해 echo 주입만 검증 — weekend 실경로는 차트 렌더·freeze 비용이 커서 분리, 라운드 2 N5), ② G0+T-B 충족·quality_flag 없음·LLM=watch 입력 시 verdict watch 유지 + shadow 기록 + `verdict_original == "watch"` 저장, ③ quality_flag=True 면 shadow 미기록.
- [ ] Step 2: FAIL → Step 3: 구현(스니펫 v1 + observe 필드·echo 주입 3곳) + schema.sql 4테이블 `verdict_original TEXT` → Step 4: PASS(conftest 가 schema 재적용 — kr_test 자동) → Step 5: 커밋. PR 본문에 production psql ALTER 4문 명시.

### Task 8: D4 검증 재생 + 민감도 + 제3안 카운터 (사전등록 선행)

**Files:** Create `docs/superpowers/specs/2026-07-21-issue44-stage3-verification-prereg.md` · `scripts/stage3_replay_climax_topping.py`

- [ ] Step 1: 사전등록 — 판독 기준: 발화율 상한, 기존 LLM ignore 패턴 정합 하한, anchor 안정성(재실행 동일성 100% + Stage1 오탈취 표본 검수 0), T4 규약별(max vs 고정 10일) 발화율 비교표, **제3안 발생률 판독 절차**(watch_reason 발생률 — prereg §7 이행), **강제율 상한 등록 + 활성화 유예 명시**(D3). 실행 전 커밋.
- [ ] Step 2: 재생 스크립트(0단계 하네스 패턴) → Step 3: 실행·판독 → D5① 확정 → append → Step 4: 커밋.

### Task 9: 프롬프트 개정 (D6 — 코드와 같은 PR)

**Files:** Modify `prompts/analyze_chart_v3.md`

- [ ] Step 1: 개정 —
  ① §6.1/§6.2 이관부: "`climax_topping_gates.*` 그대로 사용(재계산 금지)" + P2 풀링 규약 명문화 + supporting "≥70% above SMA-200" 은 **프롬프트 잔류 판정값**(코드는 값만 공급) 명시 + temporal scope 문언을 지배 규약으로 개정(4주 절 = 잉여 명시).
  ② 잔류부 유지: 후기 완화(12주)·E1(base 원점=`anchor_week`)·T3 소진 해석·"(history)".
  ③ 제3안 규칙 신설(§6.1): E1 판정 불능 + 전제·트리거 충족 → verdict=watch, watch_reason=`suspected_climax_stage_indeterminate`.
  ④ **§8.5 watch_reason 표(:454-465)에 6번째 행 + 출력 스키마(:498)·enum 검증 문구(:577)에 값 추가 + 그 문구의 개수 리터럴 "5개"→"6개" 갱신**(검토 상1·라운드 2 N4 — 값만 넣고 개수 안 고치면 자기모순 재발) + "ALLOWED_WATCH_REASONS 비포함=재트리거 비대상(extended 와 동급)" 명시.
  ⑤ left-censored(:365-368) 개정: "전 이력 기준. 이력 ≤50주 = 진짜 결측(게이트 null=발화 금지) / 전환 부재 = `no_transition`(P1 충족 간주, 극값은 전체 이력)" — 코드와 문언 일치(검토 상3 복원).
  ⑥ SSOT 블록: 신설/승격 상수 6종 + STOCK_DISTRIBUTION_COUNT_25D 공유(§6 demote·T-D) 명시.
- [ ] Step 2: 프롬프트-코드 키 전수 대조(수동 diff) → Step 3: 커밋.

### Task 10: 최종 — suite + 리뷰 + PR

- [ ] `uv run pytest tests/ -q` 기대 실패 0 → push → PR(제목 클로즈 키워드 금지, 본문에 psql ALTER 4문·의존성 맵 링크) → code-review high → 수리 → 사용자 머지 게이트.

---

## Self-Review (v2 재수행)

1. **Spec coverage**: D1(T2·5)+부속 복원(T2·3·9⑤)·D2(T3·9②)·D2-b(T6·9③④)·D3(T7 — echo 배선 포함)·D4(T8 — 카운터 포함)·D5(T1·3·4·8)·D6(T9①~⑥). 검토 발견 상3·중7·하6 → 전부 태스크에 귀속(상1→T6·T9④, 상2→T7, 상3→T2·3·9⑤, 중4→T2·3 픽스처, 중5→맵 50주 행, 중6→STAGE1_MIN_WEEKS, 중7→T7 observe 필드, 중8(scope 사문)→T1·9①, 하 6건→T2 경계·T5 헬퍼·T7 4테이블·T8 파일명·T9 풀링/70%·스키마 경로).
2. **Placeholder scan**: "XX" 파일명 제거(07-21 확정), `_dist_count_25s` 명세 추가, 코드 스텝 전부 코드 포함. `test_climax_gates_scope_expires` 첫 줄의 자기참조 오타 제거 확인 — rows 정의로 대체됨.
3. **Type consistency**: anchor dict 4키를 T3~5·7 이 동일 소비, `climax_topping_gates`/`climax_topping_gates_echo` 명칭 T5·7·9 일치, `build_analysis_inline` tuple 반환을 T7 호출자 3곳이 소비 — 일치.
