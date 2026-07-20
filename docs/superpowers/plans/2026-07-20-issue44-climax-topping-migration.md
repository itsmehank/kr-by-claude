# §6.1/§6.2 (climax·topping) 정량 게이트 이관 구현 계획 (#44)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) 구문으로 추적.

**Goal:** analyze_chart(A)의 climax(§6.1)·topping(§6.2) 게이트 산술을 결정론 코드로 이관하고, E1 판정 불능 시 제3안(watch 강등+매수 잠금)과 §6.2 shadow backstop을 배선한다.

**Architecture:** gate_precompute(#37) 패턴 재사용 — 순수 함수 모듈(`climax_topping.py`)이 주봉 전 이력을 받아 anchor·게이트를 계산하고, payload_builder 가 `climax_topping_gates` 로 payload 에 탑재(authoritative). 사후층은 D3 수정안 v1 — book-mandated 분지(G0+T-B / G0+T-D분배일)만 shadow 로그로 시작.

**Tech Stack:** Python(psycopg·순수 함수), pytest(kr_test 스키마), prompts/analyze_chart_v3.md 수동 동기화(SSOT 규약).

## Global Constraints (확정 결정 D1~D6 — 2026-07-20 사용자 확정)

- **D1**: anchor 는 코드가 확정(authoritative). 탐색은 **DB 전 이력**, "가장 최근" Stage 1→2 전환. 코드 anchor 를 payload 에 명시(`anchor_week`)해 LLM base 카운팅과 단일 원점.
- **D2**: base 카운트는 LLM 잔류. P1 후기 완화(12주)·E1 은 LLM 재량(코드 anchor 기점).
- **D2-b**: E1 판정 불능 + 전제·트리거 충족 시 **제3안** — verdict=watch, `watch_reason=suspected_climax_stage_indeterminate` (ALLOWED_WATCH_REASONS **비포함** → breakout_from_watch 미발화 = go_now 하드 블록). 선결 측정 완료(진성 불능률 3.4~20%, 정식 wiring 확정).
- **D3**: backstop 수정안 v1 — ①전 입력 결정론 확정+non-null+데이터 품질 플래그 없음 ②book-mandated 분지만(§6.2 G0+T-B, G0+T-D분배일. T-C 는 D5② design-judgment → shadow 로그 전용) ③노출 축소 방향만. **활성화 전 shadow 1사이클 + 강제율 상한 사전등록 + 원본 verdict 별도 보존 + gate_version 스탬프.** 이 계획은 shadow 단계까지만 — 활성화는 별도 사용자 결정.
- **D4**: 검증은 0단계 방법론(재생→발화율·패턴 정합→소표본) + D5 규약별 민감도. 소급 재분류 없음.
- **D5**: 신설 규약 — T4 창(종점=평가일 trailing 고정, 길이=max(7~15) 잠정·민감도 실측 후 확정), T-C 'prolonged'=CLIMAX_MATURITY_WEEKS 재사용, anchor 세부(평탄 밴드·전환 창·Stage1 재형성) 신설 상수.
- **D6**: 프롬프트 §6 은 이관부만 authoritative-소비 문구로 개정, 잔류부(후기 완화·E1·T3 '소진' 해석·history 표기) 현행 유지. left-censored 조항은 전 이력 기준으로 개정.
- 프로젝트 규약: null=보수(판정 불능 게이트는 발화 안 함 — None), 신설/공유 상수는 아래 **의존성 맵** 준수, `scripts/export_thresholds.py` 재실행, 테스트 기대 실패 0, git add 는 명시 경로만, 커밋 본문에만 이슈 참조(자동 클로즈 방지).

## File Structure

- Create `kr_pipeline/llm_runner/compute/climax_topping.py` — anchor 탐색 + §6.1/§6.2 게이트 순수 함수 (DB 접근 없음).
- Modify `kr_pipeline/common/thresholds.py` — 신설 상수 5개 (아래 Task 1).
- Modify `api/services/payload_builder.py` — 주봉 전 이력 fetch + `climax_topping_gates`·`anchor_week` payload 탑재.
- Modify `kr_pipeline/llm_runner/store.py` — watch_reason enum 에 `suspected_climax_stage_indeterminate` 허용 + 원본 verdict 보존 컬럼 기록.
- Modify `kr_pipeline/llm_runner/gates.py` — §6.2 shadow backstop (로그 전용).
- Modify `prompts/analyze_chart_v3.md` — §6.1/§6.2 개정 + SSOT 블록 + 제3안 규칙 (코드와 같은 PR).
- Modify `schema.sql` — `verdict_original` 컬럼(weekly_classification·backfill 3테이블), 수동 psql 양쪽 DB 적용.
- Create `scripts/stage3_replay_climax_topping.py` — D4 검증 재생(발화율·민감도).
- Tests: `tests/test_climax_topping.py`, `tests/test_climax_payload.py`, `tests/test_climax_shadow_backstop.py`.

## 의존성 맵 (threshold-change-checklist §(b) — 트리거: thresholds.py 상수 추가 + 소비처 이동 + prompt 임계 텍스트 개정)

**1단계 (파생 신호)**: CLIMAX_*/TOPPING_* 상수 → `climax_topping.py` 산출 필드(`anchor_week`, `maturity_ok`, `p2_accel_ok`, `t1_max_spread`~`t4_up_days`, `scope_active`, `g0_below_10w`, `ta_max_decline`~`td_dist`) → payload `climax_topping_gates`.

**2단계 (소비 룰)**: ① prompt §6.1/§6.2 (authoritative 소비 — 개정 후), ② gates.py shadow backstop (G0+T-B / G0+T-D분배일), ③ §6 demote-to-watch(:351 — STOCK_DISTRIBUTION_COUNT_25D 공유), ④ trigger_gate.ALLOWED_WATCH_REASONS (제3안 watch_reason 비포함 = 차단).

**3단계 고정 상수 — 2축 판정** (전 행: 값 변경 없음, 소비 주체 이동/신설):

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| CLIMAX_MATURITY_WEEKS=18 | 불가(주수) | 있음 — 소비 이동(LLM→코드) + **T-C 'prolonged' 공유 신설(D5②)** | PRESERVES(HMMS p.263) | 값 불변·소비 이동. T-C 공유는 shadow 지표로 관측(신설 소비라 즉시 행동 대신 D4 재생에서 발화율 실측 — 근거: 값 자체는 책 그대로, 공유가 부적합하면 발화율 이상으로 드러남) |
| CLIMAX_LATE_MATURITY_WEEKS=12 | 불가 | 미미 — **LLM 잔류(D2)**, 코드 미소비 | PRESERVES | 모니터링(코드 이관 없음 — 프롬프트 현행 유지가 곧 후속) |
| CLIMAX_GAIN_PCT=25.0 / GAIN_WINDOW_WEEKS=3 | 부분(수익률) | 있음 — P2 소비 이동 | PRESERVES | 값 불변·소비 이동, D4 재생으로 P2 발화율 검증 |
| CLIMAX_UP_DAYS_PCT=70 / WINDOW_MIN=7 / MAX=15 | 불가 | 있음 — T4 소비 이동 + **창 규약 신설(D5① 종점 trailing·길이 max)** | PRESERVES(수치)/EXTENDS(창 규약) | D4 민감도(max vs 고정 단일창) 실측 후 규약 확정 — 계획 Task 8 |
| TOPPING_BELOW_10W_WEEKS=8 | 불가 | 있음 — T-B 소비 이동 + backstop 분지 | PRESERVES(HMMS p.269) | 값 불변·소비 이동. backstop 은 shadow 1사이클 후 활성화 결정 |
| STOCK_DISTRIBUTION_COUNT_25D=4 | 부분 | 있음 — T-D 소비 이동. **§6 demote-to-watch(:351)와 공유 소비 유지** — 코드 T-D 와 프롬프트 demote 가 같은 값 참조(어긋나면 강등↔강제제외 임계 분리 사고) | PRESERVES(HMMS p.269) | 값 불변. prompt SSOT 블록에 공유 명시(Task 9) — 두 소비처 단일 인용 |
| BREAKOUT_VOL_FLOOR=1.4 | 가능(배수) | 있음 — anchor 판정(신규 소비). 기존 소비처(§6.1 anchor 텍스트·B 게이트 vol band)와 3중 공유가 됨 | PRESERVES | 값 불변. 의존성 맵에 3중 공유 기록(이 행) — 향후 이 값 변경 시 anchor·vol band·prompt 세 곳 동시 재검토 트리거 |
| **신설** CLIMAX_ANCHOR_FLAT_BAND_PCT=2.0 | 가능(%) | 있음 — Stage1 '평평/하락' 판정(40주선 기울기 허용 밴드) | EXTENDS(책은 개념만) | **B-수치** — D4 재생에서 anchor 안정성(주차 흔들림 0 확인) + 실전 축적 후 재검토 |
| **신설** CLIMAX_ANCHOR_TURNUP_WEEKS=4 | 불가(주수) | 있음 — 30/40주선 '상승 전환' 판정 창(직전 N주 대비 상승) | EXTENDS | **B-수치** — 동상 |
| **신설** CLIMAX_SCOPE_PAST_HIGH_WEEKS=2 / SCOPE_CORRECTION_PCT=15.0 / SCOPE_STALE_WEEKS=4 | 부분 | 있음 — temporal scope(A12) 소비 이동. 프롬프트 :394-396 문언의 수치를 SSOT 승격 | PRESERVES(문언 그대로 승격) | 값 불변 승격. 회색지대는 "≤2주 절 지배" 규약(1단계 확정) 코드화 |

**소비 경계 (1줄)**: `climax_topping_gates` → prompt §6.1/§6.2 (verdict=ignore 여부) + gates.py shadow → weekly_classification verdict/triggered_rules → 평일 트리거·entry_params 상류.

**합격 조건 self-check**: 맵 존재 ✓ / 3단계 상수 전 행 ✓ / 축1·축2 전 칸 기입 ✓ / 영향있음 행 전부 후속 예약(B-수치·소비이동 검증·민감도) 또는 근거 있는 모니터링 ✓ / 소비 경계 1줄 ✓.

---

### Task 1: 신설 상수 5개 + export 재생성

**Files:** Modify `kr_pipeline/common/thresholds.py` (§6.1 블록 인근, :390 부근) / Test `tests/test_thresholds_export.py`(기존 있으면 추가) / 재실행 `scripts/export_thresholds.py`

**Interfaces:** Produces — `CLIMAX_ANCHOR_FLAT_BAND_PCT: float = 2.0`, `CLIMAX_ANCHOR_TURNUP_WEEKS: int = 4`, `CLIMAX_SCOPE_PAST_HIGH_WEEKS: int = 2`, `CLIMAX_SCOPE_CORRECTION_PCT: float = 15.0`, `CLIMAX_SCOPE_STALE_WEEKS: int = 4` (전부 `Final`).

- [ ] **Step 1**: thresholds.py 에 상수 5개 추가 — 각각 위 의존성 맵 행을 요약한 주석(출처 태그 EXTENDS/PRESERVES 명시) 포함:

```python
# (#44 D5③) anchor Stage1 판정 — 40주선 '평평/하락' 허용 밴드(%). 책은 개념만
# (Minervini Stage 1 정의) — 수치는 EXTENDS. B-수치: D4 재생 안정성 검증 후 재검토.
CLIMAX_ANCHOR_FLAT_BAND_PCT: Final[float] = 2.0
# (#44 D5③) 30/40주선 '상승 전환' 판정 창(직전 N주 대비 상승). EXTENDS, B-수치.
CLIMAX_ANCHOR_TURNUP_WEEKS: Final[int] = 4
# (#44 A12) temporal scope — prompt §6.1 :394-396 문언의 SSOT 승격 (PRESERVES).
CLIMAX_SCOPE_PAST_HIGH_WEEKS: Final[int] = 2
CLIMAX_SCOPE_CORRECTION_PCT: Final[float] = 15.0
CLIMAX_SCOPE_STALE_WEEKS: Final[int] = 4
```

- [ ] **Step 2**: `uv run python scripts/export_thresholds.py` 실행 → `web/src/data/thresholds.generated.ts` 재생성 확인 (diff 에 신설 5개).
- [ ] **Step 3**: `uv run pytest tests/ -q -k threshold` PASS 확인.
- [ ] **Step 4**: 커밋 `feat(thresholds): #44 D5 신설 상수 5종 + export` (본문에 의존성 맵 행 참조).

### Task 2: climax_topping.py — anchor 탐색 (TDD)

**Files:** Create `kr_pipeline/llm_runner/compute/climax_topping.py` / Test `tests/test_climax_topping.py`

**Interfaces:** Produces —
```python
def find_anchor(weekly: list[dict]) -> dict
# weekly: 오름차순 [{week_end, open, high, low, close, volume}] (adj, 전 이력)
# 반환: {"anchor_week": "YYYY-MM-DD" | None, "left_censored": bool, "weeks_since": int | None}
# 규칙(D1·프롬프트 :356-368 그대로): '가장 최근' 주 w — w 이전이 Stage 1
# (close 가 40주 SMA 아래 AND 40주 SMA 기울기 ≤ +CLIMAX_ANCHOR_FLAT_BAND_PCT/CLIMAX_ANCHOR_TURNUP_WEEKS주)
# 이고, w 에서 volume ≥ BREAKOUT_VOL_FLOOR × 50주 평균 AND 30주·40주 SMA 가
# 직전 CLIMAX_ANCHOR_TURNUP_WEEKS 주 대비 상승 AND close > 30주·40주 SMA.
# 이력 < 50주 → left_censored=True, anchor_week=None (진짜 결측 — D1-b).
```

- [ ] **Step 1**: 실패 테스트 3본 작성 — 합성 주봉 픽스처(함수로 생성):

```python
def _mk_weeks(prices: list[float], vols: list[int], start="2020-01-03") -> list[dict]:
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return [{"week_end": str(d0 + timedelta(weeks=i)), "open": p, "high": p * 1.02,
             "low": p * 0.98, "close": p, "volume": v}
            for i, (p, v) in enumerate(zip(prices, vols))]

def test_anchor_finds_most_recent_transition():
    # 60주 횡보(1000, 40주선 아래·평탄) → 61주차 거래량 2× 돌파 + 이후 상승
    prices = [1000.0] * 60 + [1100.0 + 20 * i for i in range(20)]
    vols = [100_000] * 60 + [250_000] + [120_000] * 19
    r = find_anchor(_mk_weeks(prices, vols))
    assert r["left_censored"] is False
    assert r["anchor_week"] == _mk_weeks(prices, vols)[60]["week_end"]
    assert r["weeks_since"] == 19

def test_anchor_resets_after_stage4():
    # 상승 → 깊은 하락(Stage 4·40주선 아래 복귀) → 재횡보 → 2차 전환: 최근 전환을 잡아야
    up1 = [1000.0 + 30 * i for i in range(30)]
    down = [1900.0 - 60 * i for i in range(20)]
    flat = [700.0] * 55
    up2 = [800.0 + 25 * i for i in range(10)]
    prices = up1 + down + flat + up2
    vols = [100_000] * (len(prices))
    vols[len(up1) + len(down) + len(flat)] = 300_000  # 2차 전환 주 거래량 스파이크
    r = find_anchor(_mk_weeks(prices, vols))
    assert r["anchor_week"] == _mk_weeks(prices, vols)[len(up1) + len(down) + len(flat)]["week_end"]

def test_anchor_left_censored_short_history():
    prices = [1000.0 + 10 * i for i in range(30)]  # 이력 30주 < 50주
    r = find_anchor(_mk_weeks(prices, [100_000] * 30))
    assert r == {"anchor_week": None, "left_censored": True, "weeks_since": None}
```

- [ ] **Step 2**: `uv run pytest tests/test_climax_topping.py -q` → FAIL (모듈 없음) 확인.
- [ ] **Step 3**: `find_anchor` 구현 — pandas 없이 리스트 산술(모듈 규약: 순수 함수·의존 최소):

```python
from kr_pipeline.common.thresholds import (
    BREAKOUT_VOL_FLOOR, CLIMAX_ANCHOR_FLAT_BAND_PCT, CLIMAX_ANCHOR_TURNUP_WEEKS,
)

def _sma(vals: list[float], i: int, n: int) -> float | None:
    if i + 1 < n:
        return None
    return sum(vals[i - n + 1 : i + 1]) / n

def find_anchor(weekly: list[dict]) -> dict:
    closes = [w["close"] for w in weekly]
    vols = [w["volume"] or 0 for w in weekly]
    n = len(weekly)
    if n < 50:
        return {"anchor_week": None, "left_censored": True, "weeks_since": None}
    turnup = CLIMAX_ANCHOR_TURNUP_WEEKS
    for i in range(n - 1, 49, -1):  # 가장 최근부터 역방향 (D1: most recent)
        s30, s40 = _sma(closes, i, 30), _sma(closes, i, 40)
        s30p, s40p = _sma(closes, i - turnup, 30), _sma(closes, i - turnup, 40)
        v50 = sum(vols[i - 50 : i]) / 50
        if None in (s30, s40, s30p, s40p) or v50 <= 0:
            continue
        # 선행 Stage 1: 직전 주 close 가 40주선 아래, 40주선이 평탄/하락
        prev_s40 = _sma(closes, i - 1, 40)
        s40_slope_pct = (prev_s40 - _sma(closes, i - 1 - turnup, 40)) / prev_s40 * 100 \
            if prev_s40 and _sma(closes, i - 1 - turnup, 40) else None
        stage1 = (prev_s40 is not None and closes[i - 1] < prev_s40
                  and s40_slope_pct is not None
                  and s40_slope_pct <= CLIMAX_ANCHOR_FLAT_BAND_PCT)
        turned_up = s30 > s30p and s40 > s40p
        if (stage1 and vols[i] >= BREAKOUT_VOL_FLOOR * v50
                and turned_up and closes[i] > s30 and closes[i] > s40):
            return {"anchor_week": weekly[i]["week_end"], "left_censored": False,
                    "weeks_since": n - 1 - i}
    # 전 이력에 전환 부재 = 상장 후 줄곧 Stage 2 등 — left-censored 준용 (D1-b)
    return {"anchor_week": None, "left_censored": True, "weeks_since": None}
```

- [ ] **Step 4**: 테스트 PASS 확인. 픽스처가 조건을 못 만들면(스텝 3 구현이 옳은데 픽스처가 비현실적) 픽스처를 조정하되 구현 로직 완화 금지(null=보수).
- [ ] **Step 5**: 커밋 `feat(climax): anchor 전 이력 탐색 — D1 확정 규약`.

### Task 3: §6.1 게이트 계산 (TDD)

**Files:** Modify `kr_pipeline/llm_runner/compute/climax_topping.py` / Test `tests/test_climax_topping.py`

**Interfaces:** Produces —
```python
def compute_climax_gates(weekly: list[dict], daily_20d: list[dict], anchor: dict) -> dict
# 반환 키(전부 None 가능 — null=보수, 프롬프트가 None 을 '판정 불능=발화 근거 금지'로 소비):
# {"maturity_weeks", "maturity_ok",          # P1 기본 18주 (후기 12주는 LLM 몫 — D2)
#  "p2_best_roll_pct", "p2_is_steepest", "p2_accel_ok",
#  "t1_max_spread_now", "t2_max_volume_now", # 이번 주가 anchor 후 최대인가 (bool)
#  "t3_gap_up_today",                        # 갭 '사실'만 (해석은 LLM — A8)
#  "t4_up_days_pct_max", "t4_ok",            # D5①: 종점=평가일 trailing, 길이 max(7~15) 잠정
#  "supporting_ext_sma200_pct",
#  "scope_active"}                           # A12: 가속 중 or 고점 후 ≤2주, 15%/4주 규칙
```

- [ ] **Step 1**: 실패 테스트 — 대표 케이스 3본(가속 충족/스코프 만료/anchor 결측 시 전부 None):

```python
def test_climax_gates_fire_on_vertical_run():
    prices = [1000.0] * 60 + [1000.0 + 10 * i for i in range(15)] + [1200.0, 1400.0, 1650.0]
    vols = [100_000] * 60 + [250_000] + [110_000] * 14 + [300_000, 350_000, 900_000]
    wk = _mk_weeks(prices, vols)
    anchor = find_anchor(wk)
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=8), anchor)
    assert g["maturity_ok"] is True            # anchor 후 18주 이상
    assert g["p2_accel_ok"] is True            # 3주 롤링 (1650/1200-1) ≈ +37.5% ≥ 25%, 최급
    assert g["t2_max_volume_now"] is True      # 마지막 주 900k = 사상 최대
    assert g["t4_ok"] is True                  # 10일 중 8일 상승 = 80% ≥ 70%
    assert g["scope_active"] is True

def test_climax_gates_scope_expires():
    # 고점 후 3주 경과(2주 초과) — 회색지대 규약: 즉시 비활성
    prices = [1000.0] * 60 + [1000.0 + 40 * i for i in range(20)] + [1750.0, 1740.0, 1730.0]
    wk = _mk_weeks(prices, [100_000] * 60 + [250_000] + [110_000] * 22)
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=5), find_anchor(wk))
    assert g["scope_active"] is False

def test_climax_gates_null_on_missing_anchor():
    wk = _mk_weeks([1000.0] * 30, [100_000] * 30)  # left-censored
    g = compute_climax_gates(wk, _mk_daily_updays(10, up=5), find_anchor(wk))
    assert g["maturity_ok"] is None and g["p2_accel_ok"] is None  # null=보수
```

(`_mk_daily_updays(n, up)` = 최근 n 거래일 중 up 일이 전일比 상승인 합성 일봉 헬퍼 — 테스트 파일에 정의.)

- [ ] **Step 2**: FAIL 확인 → **Step 3**: 구현. 핵심 산술(발췌 — 전체는 구현 시 이 시그니처 준수):

```python
def compute_climax_gates(weekly, daily_20d, anchor):
    if anchor["anchor_week"] is None:
        # left-censored: P1 충족 간주가 아니라 전부 None — 프롬프트 :365-368 의
        # '충족 간주'는 D1-b(전 이력)에서 진짜 결측(이력<50주)으로 재정의됐고,
        # 진짜 결측은 판정 불능 = null 보수 (개정 프롬프트 D6 와 동기화).
        return {k: None for k in _CLIMAX_KEYS}
    ai = next(i for i, w in enumerate(weekly) if w["week_end"] == anchor["anchor_week"])
    adv = weekly[ai:]                                   # anchor 포함 상승 전체
    closes = [w["close"] for w in adv]
    maturity_weeks = len(adv) - 1
    maturity_ok = maturity_weeks >= CLIMAX_MATURITY_WEEKS
    # P2: 1~3주 롤링 수익 최대 ≥25% AND 그 값이 상승 전체의 최급
    def roll(seq, k):
        return [(seq[j] / seq[j - k] - 1) * 100 for j in range(k, len(seq))]
    best_now = max((roll(closes, k)[-1] for k in (1, 2, 3) if len(closes) > k), default=None)
    best_ever = max((max(roll(closes, k)) for k in (1, 2, 3) if len(closes) > k), default=None)
    ...
```

t4: `for win in range(CLIMAX_UP_DAYS_WINDOW_MIN, CLIMAX_UP_DAYS_WINDOW_MAX + 1)` 로 **평가일 종점 trailing** 창들의 상승일 비율 max(D5① 잠정 — Task 8 민감도 확정 전까지 상수로 두지 않고 로직 주석에 D5① 표기). scope: 고점 주 인덱스로 경과주·조정폭 계산, `경과 > CLIMAX_SCOPE_PAST_HIGH_WEEKS`(가속 종료 후) 즉시 False(회색지대 규약).

- [ ] **Step 4**: PASS 확인 → **Step 5**: 커밋 `feat(climax): §6.1 게이트 산술 이관`.

### Task 4: §6.2 게이트 계산 (TDD)

**Files:** Modify `kr_pipeline/llm_runner/compute/climax_topping.py` / Test `tests/test_climax_topping.py`

**Interfaces:** Produces —
```python
def compute_topping_gates(weekly: list[dict], dist_count_25s: int | None, anchor: dict) -> dict
# {"g0_below_10w", "tb_weeks_below_10w", "tb_ok",       # book-mandated (backstop 후보)
#  "td_max_down_volume_now", "td_dist_ok",              # td_dist = 분배일≥4 (book) / down-vol 은 anchor 의존
#  "ta_max_decline_now",                                # anchor 의존 (None if anchor 결측)
#  "tc_sma40_turndown", "tc_prolonged_ok",              # T-C: prolonged 는 D5②(shadow 전용)
#  "quality_flag"}                                      # D3 조건① — 주봉 결측·halt 구간 감지 시 True
```

- [ ] **Step 1**: 실패 테스트 — G0+T-B 발화 / G0 미충족 시 전체 침묵 / dist_count None → td_dist_ok None:

```python
def test_topping_g0_tb_fire():
    prices = [1000.0 + 20 * i for i in range(40)] + [1800.0 - 30 * i for i in range(12)]
    wk = _mk_weeks(prices, [100_000] * 52)
    g = compute_topping_gates(wk, dist_count_25s=2, anchor=find_anchor(wk))
    assert g["g0_below_10w"] is True and g["tb_ok"] is True  # 8주+ 연속 10주선 아래

def test_topping_silent_without_g0():
    prices = [1000.0 + 20 * i for i in range(52)]
    g = compute_topping_gates(_mk_weeks(prices, [100_000] * 52), 9, find_anchor(_mk_weeks(prices, [100_000] * 52)))
    assert g["g0_below_10w"] is False and g["tb_ok"] is False

def test_topping_dist_none_conservative():
    prices = [1000.0 + 20 * i for i in range(40)] + [1800.0 - 30 * i for i in range(12)]
    wk = _mk_weeks(prices, [100_000] * 52)
    assert compute_topping_gates(wk, None, find_anchor(wk))["td_dist_ok"] is None
```

- [ ] **Step 2**: FAIL → **Step 3**: 구현(10주 SMA·연속 카운트·40주선 turn-down + `tc_prolonged_ok = maturity_weeks >= CLIMAX_MATURITY_WEEKS`(D5②)·anchor 의존 극값은 anchor 결측 시 None) → **Step 4**: PASS → **Step 5**: 커밋 `feat(topping): §6.2 게이트 산술 이관`.

### Task 5: payload 통합 + anchor 단일 원점

**Files:** Modify `api/services/payload_builder.py`(build_payload, :100-148 + fetch 함수 추가) / Test `tests/test_climax_payload.py`

**Interfaces:** Consumes — Task 2~4 함수. Produces — payload 키 `climax_topping_gates`(위 두 dict 병합 + `anchor_week`·`left_censored`), 기존 키 불변(additive).

- [ ] **Step 1**: 실패 테스트 — kr_test 스키마에 합성 주봉 시드 후 build_payload 호출, `climax_topping_gates` 존재·`anchor_week` 일치·기존 키 보존 assert.
- [ ] **Step 2**: FAIL 확인.
- [ ] **Step 3**: 구현 — `_fetch_weekly_full(conn, ticker, on_date)` (LIMIT 없는 `_fetch_weekly_ohlcv` 변형, 동일 COALESCE(adj,raw) 규약) + build_payload 에:

```python
    weekly_full = _fetch_weekly_full(conn, ticker, on_date)
    anchor = find_anchor(weekly_full)
    gates = {
        **compute_climax_gates(weekly_full, daily_ohlcv[-20:], anchor),
        **compute_topping_gates(weekly_full, _dist_count_from(indicators_60d), anchor),
        "anchor_week": anchor["anchor_week"], "left_censored": anchor["left_censored"],
    }
    payload["climax_topping_gates"] = gates   # (#44) §6.1/§6.2 authoritative 입력
```

- [ ] **Step 4**: PASS + `uv run pytest tests/ -q` 전체 0 실패 확인 → **Step 5**: 커밋.

### Task 6: 제3안 wiring — watch_reason 신설 + 차단 고정 테스트

**Files:** Modify `kr_pipeline/llm_runner/store.py`(watch_reason 허용 목록) / Test `tests/test_climax_shadow_backstop.py`

**Interfaces:** Produces — enum 값 `suspected_climax_stage_indeterminate` (store 허용). trigger_gate.ALLOWED_WATCH_REASONS 는 **수정하지 않음** — 비포함이 곧 차단(D2-b 확정 메커니즘).

- [ ] **Step 1**: 실패 테스트 2본 — ① store 가 이 watch_reason 을 거부하지 않음, ② `trigger_gate.evaluate(classification="watch", watch_reason="suspected_climax_stage_indeterminate", fresh cross 조건 전부 충족)` 이 `breakout_from_watch` 를 반환하지 **않음**(promotion 만 가능 — promotion 은 go_now 금지 유형이므로 하드 블록 성립):

```python
def test_suspected_climax_watch_reason_blocks_bfw():
    from kr_pipeline.llm_runner.compute.trigger_gate import evaluate
    trig = evaluate(close=1060.0, pivot_price=1000.0, volume=2_000_000,
                    avg_volume_50d=1_000_000.0, stop_loss=None, sma_50=900.0,
                    classification="watch", prev_close=990.0,
                    watch_reason="suspected_climax_stage_indeterminate")
    assert trig != "breakout_from_watch"   # ALLOWED 비포함 → 정당 돌파 경로 차단
```

- [ ] **Step 2**: FAIL(store 거부) 확인 → **Step 3**: store 허용 목록에 추가(§8.5 'extended' 와 동급 — 재트리거 비대상 주석) → **Step 4**: PASS → **Step 5**: 커밋 `feat(store): 제3안 watch_reason 신설 — D2-b 확정`.

### Task 7: §6.2 shadow backstop + 원본 verdict 보존

**Files:** Modify `kr_pipeline/llm_runner/gates.py`(apply_phase1_gates 말미) · `kr_pipeline/llm_runner/store.py`(verdict_original 기록) · `schema.sql` / Test `tests/test_climax_shadow_backstop.py`

**Interfaces:** Consumes — payload 의 `climax_topping_gates`(store 경유 전달 or gates 내 재계산 금지 — **payload 값을 result 에 echo 한 것을 소비**). Produces — triggered_rules 키 `6_2_topping_shadow`(**verdict 무변경** — shadow), 컬럼 `verdict_original`.

- [ ] **Step 1**: 실패 테스트 — G0+T-B 확정 충족 + quality_flag 없음 + LLM verdict=watch 입력 시: verdict 는 **watch 유지**(shadow), triggered_rules 에 `6_2_topping_shadow.would_force=ignore`·`gate_version` 기록, `verdict_original == "watch"` 저장.
- [ ] **Step 2**: FAIL → **Step 3**: 구현 — D3 수정안 v1 조건 명문:

```python
    # === (#44 D3 수정안 v1) §6.2 shadow backstop — 로그 전용, 활성화는 별도 결정 ===
    # 자격: book-mandated 분지(G0+T-B / G0+T-D분배일)만 · 전 입력 non-null ·
    # quality_flag 없음 · 방향 = 노출 축소(would_force=ignore, 명시적 FORCE-IGNORE).
    ct = (result.get("climax_topping_gates_echo") or {})
    if (ct.get("g0_below_10w") is True and ct.get("quality_flag") is not True
            and (ct.get("tb_ok") is True or ct.get("td_dist_ok") is True)
            and result.get("classification") != "ignore"):
        triggered["6_2_topping_shadow"] = {
            "fired": False, "shadow": True, "would_force": "ignore",
            "inputs": {k: ct.get(k) for k in ("g0_below_10w", "tb_ok", "td_dist_ok")},
            "gate_version": "44-v1",
        }
```

- [ ] **Step 4**: PASS + schema.sql 에 `verdict_original TEXT` 3테이블 추가(적용 절차는 PR 본문에 psql 명령 명시 — kr_pipeline·kr_test 수동) → **Step 5**: 커밋.

### Task 8: D4 검증 재생 + T4 민감도 (사전등록 별도 문서 후 실행)

**Files:** Create `scripts/stage3_replay_climax_topping.py` · Create `docs/superpowers/specs/2026-07-XX-issue44-stage3-verification-prereg.md`

- [ ] **Step 1**: 사전등록 문서 — 판독 기준(발화율 상한·기존 LLM ignore 와 패턴 정합 하한·anchor 안정성=재실행 동일성 100%·T4 창 규약별 발화율 비교표) 을 실행 전 커밋.
- [ ] **Step 2**: 재생 스크립트 — backtest 모집단에 `find_anchor`+두 게이트 실행(0단계 하네스 패턴 재사용), T4 는 max/고정10일 두 규약 병산.
- [ ] **Step 3**: 실행·판독 → D5① 창 규약 확정(계획 갱신) → 결과를 사전등록 문서에 append.
- [ ] **Step 4**: 커밋.

### Task 9: 프롬프트 §6 개정 (D6 — 코드와 같은 PR)

**Files:** Modify `prompts/analyze_chart_v3.md` §6.1(:354-398)·§6.2(:400-420)·SSOT 블록

- [ ] **Step 1**: 개정 — ① P1 기본·P2·T1/T2/T4·scope·G0~T-D: "`climax_topping_gates.*` 를 그대로 사용(재계산 금지)" 문구(column-is-authoritative 관례). ② 잔류부 유지: 후기 완화(12주)·E1(단, base 카운트 원점은 `anchor_week` 사용 명시)·T3 '소진' 해석·"(history)" 표기. ③ **제3안 규칙 신설**: "E1 전제(base 서수) 판정 불능인데 §6.1 전제·트리거가 charged 이면 verdict=watch, watch_reason=suspected_climax_stage_indeterminate". ④ left-censored 조항 → "전 이력 기준·진짜 결측(이력<50주)만, 이 경우 게이트 전부 null=발화 금지". ⑤ SSOT 블록에 신설 상수 5종 + STOCK_DISTRIBUTION_COUNT_25D 공유(§6 demote 와 T-D) 명시.
- [ ] **Step 2**: 프롬프트-코드 키 이름 대조(수동 diff — climax_topping_gates 키 전부) → **Step 3**: 커밋 `feat(prompt): §6 authoritative 소비 개정 — D6`.

### Task 10: 최종 — 전체 suite + 8각도 리뷰 + PR

- [ ] `uv run pytest tests/ -q` 기대 실패 0 → 브랜치 push → PR 생성(제목에 이슈 클로즈 키워드 금지) → code-review high → 수리 → 사용자 머지 게이트.

---

## Self-Review (writing-plans §Self-Review 수행 기록)

1. **Spec coverage**: D1(Task 2·5)·D2(Task 3 주석+Task 9②)·D2-b(Task 6·9③)·D3(Task 7)·D4(Task 8)·D5(Task 1·3 T4·4 T-C·8 민감도)·D6(Task 9) — 전 결정 매핑 확인. 잔여: backstop **활성화**는 의도적 범위 외(shadow 1사이클 후 별도 결정 — D3 확정 그대로).
2. **Placeholder scan**: "TBD/적절히/나중에" 없음. Task 3 Step 3 은 발췌임을 명시하고 시그니처·키 계약을 Interfaces 에 고정(전체 코드는 해당 Task 구현 시 계약 준수) — t4/scope 산술 규약은 문장으로 완결 기술.
3. **Type consistency**: `find_anchor`→`anchor` dict 를 Task 3~5 가 동일 키로 소비, payload 키 `climax_topping_gates` 를 Task 7·9 가 동일 명칭 소비 — 일치 확인. `climax_topping_gates_echo`(Task 7)는 store 가 payload 값을 result 로 전달하는 신규 경로 — Task 7 Step 3 주석에 재계산 금지 명시.
