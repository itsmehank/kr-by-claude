# 진입 변형·국면 한정 탐색 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 승률 개선 후보 두 갈래 — ① 진입 변형(익일확인·눌림대기) ② confirmed_uptrend 국면 한정 — 를 표본 A·B 데이터에서 **탐색(관찰 라벨)** 하여, 표본 C(#52) 사전등록에 넣을 가설 후보를 수치로 다듬는다.

**Architecture:** ①은 `trigger_sim.simulate` 에 **default 보존 `entry_mode` 파라미터**("breakout"=현행)를 추가하고 두 변형(next_day_confirm/pullback)을 상태기계로 구현 — 엔진 복제(drift 위험) 대신 확장 + "기본 모드 완전 동일" 회귀로 무해성을 증명한다. ②는 코드 변경 없이 기존 refinement 트레이드 JSON 의 국면 슬라이스 재집계다. 비교표 산출은 단일 탐색 스크립트가 담당한다.

**Tech Stack:** Python (psycopg), 기존 backtest 모듈 재사용, pytest(kr_test `db` 불필요 — 합성 bar 픽스처), LLM 0회(전부 결정론).

## Global Constraints

- **관찰 라벨**: 이 작업의 모든 산출 수치는 "탐색/관찰 — **채택 판정 아님**"으로 표기. 2021-24 데이터(A·B)로 본 결과이므로 여기서 파라미터를 채택하면 과적합 — 채택 판정은 표본 C(#52) 사전등록의 몫. thresholds.py·production 코드 무접촉.
- **default 보존**: `entry_mode="breakout"` 기본값에서 simulate/build_refined_trades 의 동작·산출이 **바이트 단위로 기존과 동일**해야 함(P3 판정 재현성 보존). 회귀 = A refinement 기본 실행이 56건·CI [−5.826, 16.09] 를 그대로 재현.
- 탐색 CI 시드 **20260722** 잠금(관찰용 부트스트랩·판정 아님).
- 변형 의미론(아래 Task 1 에 잠금)은 구현 중 임의 변경 금지 — 바꾸려면 계획 수정 먼저.
- git: 명시 경로만 스테이징, Co-Authored-By trailer 금지. 브랜치 `entry-phase-exploration`(main 에서 분기), 완료 후 PR.
- 전체 스위트 실행 전 `pgrep -fl pytest` 로 교차 세션 경합 확인.

---

### Task 1: `simulate` entry_mode 확장 (TDD — 합성 bar 픽스처)

**Files:**
- Modify: `kr_pipeline/backtest/trigger_sim.py:81-156` (simulate)
- Test: `tests/test_backtest_entry_variants.py` (신규)

**Interfaces:**
- Produces: `simulate(ticker, watch_rows, day_bars, *, mode, max_chase_pct=None, entry_mode: str = "breakout")`.
  entry_mode ∈ {"breakout", "next_day_confirm", "pullback"} — 그 외 ValueError.

**변형 의미론 (잠금):**
- 공통: "신호일 t" = 현행 `breakout_from_watch` 시그널이 성립하고, 같은 pivot 재진입 금지·5% 추격 룰(신호일 종가 기준)을 통과한 날. 변형 모드에서는 t 에 진입하지 않고 pending 상태로 전이. 진입 후 청산 로직은 현행과 완전 동일. pending 중 새 breakout 시그널은 무시(이미 pending). pending 중 `_active_row` 의 `sat` 이 pending 의 pivot_sat 과 달라지면(주간 행 교체) pending 소멸. 마지막 bar 까지 미체결 pending 은 무거래.
- **next_day_confirm**: t 의 다음 bar(t+1)에서 `close_{t+1} >= close_t` **AND** `close_{t+1} <= pivot × (1 + max_chase_pct/100)` (max_chase_pct None 이면 추격 조건 생략) → t+1 종가로 진입. 불충족 → pending 소멸(그 pivot 은 이후 재신호 가능 — last_entry_pivot_sat 은 진입 시에만 기록, 현행과 동일 규약).
- **pullback**: t 이후 **최대 5개 bar** 내 첫 bar 에서 `low <= pivot × 1.01` → 그 bar 종가로 진입(단 `close <= pivot × (1 + max_chase_pct/100)` 추격 조건 동일 적용, None 이면 생략). 5개 bar 내 미발생 → pending 소멸.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_backtest_entry_variants.py
"""simulate entry_mode 변형 — 익일확인·눌림대기 (탐색용, 기본 모드 불변)."""
from datetime import date, timedelta

from kr_pipeline.backtest.trigger_sim import DayBar, WatchRow, simulate


def _bars(specs):
    """specs: [(close, low, volume)] — 2021-01-04 부터 영업일 연속 가정."""
    out = []
    d = date(2021, 1, 4)
    prev = None
    for close, low, vol in specs:
        out.append(DayBar(d=d, close=close, low=low, volume=vol,
                          prev_close=prev, sma_50=50.0, avg_volume_50d=1000))
        prev = close
        d += timedelta(days=1)
    return out


def _watch(pivot=100.0):
    return [WatchRow(ticker="T", sat=date(2021, 1, 2), pivot_price=pivot,
                     base_low=80.0, watch_reason="valid_base_awaiting_breakout")]


# 검증 완료: watch_reason 은 ALLOWED_WATCH_REASONS(trigger_gate.py:45-47) 중 하나여야
# 돌파가 발화한다 — "valid_base_awaiting_breakout" 사용(검토 1회에서 실코드 확인).
# 주의: DayBar/WatchRow 실제 필드명은 trigger_sim.py:18-39 를 열어 확인 후
# 위 헬퍼를 실제 시그니처에 맞출 것(볼륨 조건: 돌파일 volume > avg_volume_50d 필요
# — gate_evaluate 의 fresh cross 조건도 확인해 돌파가 성립하는 값으로 세팅).


def test_default_mode_unchanged():
    """entry_mode 미지정 = 기존 동작(신호일 종가 진입)과 동일."""
    bars = _bars([(99, 95, 500), (105, 100, 2000), (110, 104, 900)])
    t_old, _ = simulate("T", _watch(), bars, mode="production")
    t_def, _ = simulate("T", _watch(), bars, mode="production", entry_mode="breakout")
    assert [ (t.entry_date, t.entry_close) for t in t_old ] == \
           [ (t.entry_date, t.entry_close) for t in t_def ]
    assert t_old and t_old[0].entry_date == bars[1].d          # 신호일 진입


def test_next_day_confirm_enters_on_confirmation():
    # 신호일(105) → 익일 106 >= 105 → 익일 종가 진입
    bars = _bars([(99, 95, 500), (105, 100, 2000), (106, 103, 900), (112, 105, 900)])
    tr, _ = simulate("T", _watch(), bars, mode="production", entry_mode="next_day_confirm")
    assert len(tr) == 1
    assert tr[0].entry_date == bars[2].d and tr[0].entry_close == 106


def test_next_day_confirm_signal_dies_without_confirmation():
    # 익일 104 < 105 → 소멸, 이후 재신호 없음(가격이 pivot 아래로)
    bars = _bars([(99, 95, 500), (105, 100, 2000), (104, 101, 900), (99, 95, 900)])
    tr, _ = simulate("T", _watch(), bars, mode="production", entry_mode="next_day_confirm")
    assert tr == []


def test_pullback_enters_on_dip_to_pivot():
    # 신호일(105) → 2일 뒤 low 100.5 <= 101(=pivot×1.01) → 그 날 종가 진입
    bars = _bars([(99, 95, 500), (105, 100, 2000), (107, 104, 900),
                  (103, 100.5, 900), (115, 102, 900)])
    tr, _ = simulate("T", _watch(), bars, mode="production", entry_mode="pullback")
    assert len(tr) == 1
    assert tr[0].entry_date == bars[3].d and tr[0].entry_close == 103


def test_pullback_expires_after_5_bars():
    # 5개 bar 내 눌림 없음 → 무거래
    specs = [(99, 95, 500), (105, 100, 2000)] + [(110 + i, 106, 900) for i in range(6)]
    tr, _ = simulate("T", _watch(), _bars(specs), mode="production", entry_mode="pullback")
    assert tr == []


def test_unknown_entry_mode_rejected():
    import pytest
    with pytest.raises(ValueError):
        simulate("T", _watch(), _bars([(99, 95, 500)]), mode="production", entry_mode="x")
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_backtest_entry_variants.py -v`
Expected: `TypeError: simulate() got an unexpected keyword argument 'entry_mode'` 류 전건 FAIL. (픽스처 필드명이 실제와 다르면 먼저 헬퍼를 고쳐 default 테스트가 **통과 가능한 상태**로 만든 뒤 — 그 테스트가 곧 현행 동작의 스냅샷이다.)

- [ ] **Step 3: simulate 구현**

`trigger_sim.py` simulate 수정 — 시그니처에 `entry_mode: str = "breakout"` 추가, 검증:

```python
    if entry_mode not in ("breakout", "next_day_confirm", "pullback"):
        raise ValueError(f"entry_mode must be breakout|next_day_confirm|pullback, got {entry_mode!r}")
```

루프 상태에 `pending: dict | None = None` 추가. 기존 `if sig == "breakout_from_watch":` 블록의 재진입·추격 가드는 그대로 두고, 가드 통과 후를 분기:

```python
                if entry_mode == "breakout":
                    cur = Trade(...)                       # 기존 코드 그대로
                    last_entry_pivot_sat = active.sat
                elif pending is None:
                    pending = {"pivot_sat": active.sat, "pivot": active.pivot_price,
                               "base_low": active.base_low, "watch_reason": active.watch_reason,
                               "signal_close": b.close, "bars_left": 5}
```

루프 선두(cur 없고 pending 있을 때) pending 처리 — `active` 산출 직후, gate 평가 **이전**에:

```python
        if cur is None and pending is not None:
            if active is None or active.sat != pending["pivot_sat"]:
                pending = None                              # 주간 행 교체 → 소멸
            else:
                chase_ok = (max_chase_pct is None
                            or b.close <= pending["pivot"] * (1 + max_chase_pct / 100))
                fill = False
                if entry_mode == "next_day_confirm":
                    fill = b.close >= pending["signal_close"] and chase_ok
                    pending_done = True                     # 익일 1회 판정 후 종료
                else:                                       # pullback
                    pending["bars_left"] -= 1
                    fill = b.low <= pending["pivot"] * 1.01 and chase_ok
                    pending_done = fill or pending["bars_left"] <= 0
                if fill:
                    cur = Trade(ticker=ticker, watch_reason=pending["watch_reason"],
                                pivot_sat=pending["pivot_sat"], pivot_price=pending["pivot"],
                                base_low=pending["base_low"], entry_date=b.d, entry_close=b.close,
                                exit_date=None, exit_close=None, pnl_pct=None, binding_exit=None)
                    last_entry_pivot_sat = pending["pivot_sat"]
                if pending_done:
                    pending = None
                if fill:
                    continue                                # 진입일에는 청산 판정 생략(현행과 동일 규약)
```

주의: 현행 코드에서 진입일(bar)에 invalidation 판정을 하는지 확인 — 기존 breakout 진입은 같은 bar 에서 `if cur is not None` 블록이 이미 지나간 뒤라 진입일 청산이 없다. 변형도 동일하게 `continue` 로 맞춘다. Trade 의 필드명·순서는 실제 dataclass(:41-56)를 열어 정확히 맞출 것.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_backtest_entry_variants.py tests/test_backtest_trigger_sim.py -q`
Expected: 신규 6 + 기존 trigger_sim 테스트 전부 PASS (기본 모드 불변의 1차 증명).

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/trigger_sim.py tests/test_backtest_entry_variants.py
git commit -m "feat(backtest): simulate entry_mode 확장(익일확인·눌림대기) — 기본 breakout 불변, 탐색용"
```

---

### Task 2: `build_refined_trades` entry_mode 스레딩 + A 재현 회귀

**Files:**
- Modify: `kr_pipeline/backtest/refinement.py` (build_refined_trades, run_refinement)
- Test: `tests/test_backtest_refinement.py` (추가)

**Interfaces:**
- Produces: `build_refined_trades(conn, tickers=None, entry_mode: str = "breakout")`,
  `run_refinement(conn, *, tickers=None, seed=SEED, prereg_label=..., entry_mode: str = "breakout")` —
  entry_mode 가 내부 `simulate(...)` 호출로 전달되고 결과 `params` 에 `"entry_mode"` 기록.

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_backtest_refinement.py` 에 append:

```python
def test_run_refinement_threads_entry_mode(db, monkeypatch):
    """entry_mode 가 build 로 전달되고 params 에 기록된다 (기본 breakout 불변)."""
    from datetime import date
    import kr_pipeline.backtest.refinement as rf
    seen = {}
    fake_trade = {"ticker": "000001", "market": "KOSPI",
                  "entry_date": date(2021, 1, 4), "exit_date": date(2021, 2, 1),
                  "phase": "confirmed_uptrend", "excess_net": 1.0,
                  "excess_net_hi": 1.5, "pnl_net": 2.0, "mdd_pct": -3.0}

    def fake_build(conn, tickers=None, entry_mode="breakout"):
        seen["entry_mode"] = entry_mode
        return [dict(fake_trade)], 0

    monkeypatch.setattr(rf, "build_refined_trades", fake_build)
    monkeypatch.setattr(rf, "cluster_bootstrap_ci", lambda trades, **kw: (0.0, 2.0))
    monkeypatch.setattr(rf, "run_placebo", lambda conn, trades, **kw: {"p": 1.0})
    out = rf.run_refinement(db, entry_mode="pullback")
    assert seen["entry_mode"] == "pullback"
    assert out["params"]["entry_mode"] == "pullback"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_backtest_refinement.py -q`
Expected: 신규 1 FAIL (`unexpected keyword 'entry_mode'`)

- [ ] **Step 3: 구현**

- `build_refined_trades(conn, tickers=None, entry_mode: str = "breakout")` — 내부 `simulate(..., max_chase_pct=MAX_CHASE_PCT)` 호출에 `entry_mode=entry_mode` 추가.
- `run_refinement(..., entry_mode: str = "breakout")` — build 호출에 전달, `params` dict 에 `"entry_mode": entry_mode` 추가.

- [ ] **Step 4: 통과 + A 재현 회귀 (기본 모드)**

Run: `uv run pytest tests/test_backtest_refinement.py tests/ -q 2>&1 | tail -3` → 실패 0 (pgrep 선확인)
Run: `uv run python -m kr_pipeline.backtest.refinement 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['n_trades'], d['ci95_mean_excess_net_all'])"`
Expected: `56 [-5.826, 16.09]` — 기본 모드 산출 불변 확정.

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/refinement.py tests/test_backtest_refinement.py
git commit -m "feat(backtest): refinement entry_mode 스레딩 — 기본 breakout 불변"
```

---

### Task 3: 탐색 스크립트 (① 변형 비교 + ② 국면 슬라이스)

**Files:**
- Create: `scripts/explore_entry_phase.py`

**Interfaces:**
- Consumes: `run_refinement(conn, tickers=..., seed=..., entry_mode=...)`(Task 2), `cluster_bootstrap_ci`, `FROZEN_SAMPLE`/`FROZEN_SAMPLE_B`.
- Produces: stdout JSON — 실행 조합별 {n, win_rate, payoff, mean_excess_net, ci95} 표. CI 시드 20260722.

- [ ] **Step 1: 스크립트 작성**

```python
# scripts/explore_entry_phase.py
"""탐색(관찰 라벨 — 채택 판정 아님): ① 진입 변형 ② confirmed_uptrend 한정.

표본 A·B × entry_mode 3종을 결정론 재계산하고, 각 트레이드 셋에 대해
전체/confirmed_uptrend-한정 두 슬라이스의 승률·손익비·초과수익 CI 를 출력한다.
결과는 표본 C(#52) 사전등록 가설 후보용 관찰 수치.

  uv run python scripts/explore_entry_phase.py > data/backtest/exploration_entry_phase_20260722.json
"""
from __future__ import annotations

import json

from kr_pipeline.backtest.frozen_sample import FROZEN_SAMPLE
from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
from kr_pipeline.backtest.refinement import build_refined_trades, cluster_bootstrap_ci
from kr_pipeline.db.connection import connect

EXPLORE_SEED = 20260722          # 관찰용 CI 시드(판정 아님)
ENTRY_MODES = ("breakout", "next_day_confirm", "pullback")
SAMPLES = {"A": list(FROZEN_SAMPLE), "B": list(FROZEN_SAMPLE_B)}


def stats(trades: list[dict]) -> dict:
    vals = [t["excess_net"] for t in trades if t.get("excess_net") is not None]
    n = len(vals)
    if n == 0:
        return {"n": 0}
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    payoff = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses)) \
        if wins and losses and sum(losses) != 0 else None
    lo, hi = cluster_bootstrap_ci(trades, seed=EXPLORE_SEED)
    return {"n": n, "win_rate_pct": round(len(wins) / n * 100, 1),
            "payoff": round(payoff, 2) if payoff else None,
            "mean_excess_net": round(sum(vals) / n, 3),
            "ci95": [lo, hi], "ci_contains_zero": lo <= 0.0 <= hi}


def main() -> int:
    out = {"label": "탐색/관찰 — 채택 판정 아님 (표본 C 사전등록 가설 후보용)",
           "seed": EXPLORE_SEED, "results": {}}
    with connect() as conn:
        for sname, tickers in SAMPLES.items():
            for mode in ENTRY_MODES:
                trades, _ = build_refined_trades(conn, tickers=tickers, entry_mode=mode)
                key = f"{sname}/{mode}"
                out["results"][key] = {
                    "all": stats(trades),
                    "confirmed_uptrend_only": stats(
                        [t for t in trades if t.get("phase") == "confirmed_uptrend"]),
                }
    # 풀링(A+B) — 모드별
    with connect() as conn:
        for mode in ENTRY_MODES:
            ta, _ = build_refined_trades(conn, tickers=SAMPLES["A"], entry_mode=mode)
            tb, _ = build_refined_trades(conn, tickers=SAMPLES["B"], entry_mode=mode)
            pooled = ta + tb
            out["results"][f"AB/{mode}"] = {
                "all": stats(pooled),
                "confirmed_uptrend_only": stats(
                    [t for t in pooled if t.get("phase") == "confirmed_uptrend"]),
            }
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

주의: A/B 각각과 풀링에서 build 를 중복 호출하면 실행 시간이 2배(모드당 200종목 시뮬 ×2). **결과 재사용으로 교정**: 첫 루프에서 (sname, mode)별 trades 를 dict 에 보관하고 풀링은 그 합으로 계산 — 두 번째 `with connect()` 블록 제거. (구현 시 이 최적화를 반영하라 — 위 코드는 의미 명세.)

- [ ] **Step 2: 스모크 (표본 A × breakout 만 — 기존 재현과 교차검증)**

스크립트를 임시 축소 실행하거나 전체 실행 후, `A/breakout · all` 의 n 이 **56**, mean_excess_net 이 **3.223** 과 일치하는지 확인 — Task 2 회귀와 삼각 검증.

- [ ] **Step 3: Commit**

```bash
git add scripts/explore_entry_phase.py
git commit -m "feat(backtest): 진입변형×국면한정 탐색 스크립트 — 관찰 라벨, CI seed 20260722"
```

---

### Task 4: 실행 → 관찰 문서 → PR

**Files:**
- Create(실행 산출물): `data/backtest/exploration_entry_phase_20260722.json`
- Create: `docs/superpowers/2026-07-22-entry-phase-exploration.md`

- [ ] **Step 1: 전체 실행**

```bash
uv run python scripts/explore_entry_phase.py > data/backtest/exploration_entry_phase_20260722.json
python3 -c "import json; d=json.load(open('data/backtest/exploration_entry_phase_20260722.json')); [print(k, v['all'].get('n'), v['all'].get('win_rate_pct'), v['all'].get('mean_excess_net'), v['all'].get('ci95')) for k,v in d['results'].items()]"
```

(6개 시뮬 × 100종목 — 수 분 소요 예상. 실행 전 `pgrep -f pytest` 무관, DB 읽기전용.)

- [ ] **Step 2: 관찰 문서 작성**

`docs/superpowers/2026-07-22-entry-phase-exploration.md` — 구조:
① 라벨(탐색/관찰 — 채택 판정 아님, 근거: 2021-24 데이터 재사용 = 과적합 위험, 채택은 표본 C 사전등록) ② 배경(플라시보 p=0.699 → 입구 가설 / 국면별 +7.48 vs 음수 → 국면 가설) ③ 결과표(9조합 × all/uptrend-only: n·승률·손익비·mean·CI) ④ 해석(어느 가설이 표본 C prereg 후보로 승격할 만한가 — 수치 기준 서술) ⑤ 한계(같은 기간 재사용; 눌림/익일 변형의 **미체결 신호 손실 분포** — 만기소멸/주간행교체(특히 금요일 신호의 계통적 소멸)/미확인 각각의 건수를 기록해 해석 왜곡 방지).

- [ ] **Step 3: 커밋 + PR**

```bash
git add data/backtest/exploration_entry_phase_20260722.json docs/superpowers/2026-07-22-entry-phase-exploration.md
git commit -m "docs(backtest): 진입변형×국면한정 탐색 결과 — 관찰 라벨(채택 판정 아님)"
git push -u origin entry-phase-exploration
gh pr create --title "feat(backtest): 진입변형·국면한정 탐색 — simulate entry_mode(기본 불변)+관찰 결과" \
  --body "탐색(관찰 라벨). simulate entry_mode 확장(default 보존, A 재현 회귀), 탐색 스크립트+결과. 채택 판정 아님 — 표본 C(#52) prereg 가설 후보. 계획: docs/superpowers/plans/2026-07-22-entry-phase-exploration.md"
```

머지는 사용자 게이트.

---

## Self-Review 결과

- **커버리지**: ①(두 변형)=Task 1·2·3, ②(국면 한정)=Task 3 슬라이스(코드 변경 0 — build 산출 trades 의 phase 필드 재사용), 관찰 문서·PR=Task 4. 기본 모드 불변 증명 = Task 1 Step 4(단위) + Task 2 Step 4(풀 재현) + Task 3 Step 2(삼각).
- **Placeholder 스캔**: 픽스처 필드명·Trade 생성자·gate_evaluate 돌파 조건은 "실코드 확인 후 맞춤" 지시로 명시(값 미정이 아니라 전사 정확성 지시). 통과.
- **타입 일관성**: entry_mode 문자열 3종 — Task 1 정의·Task 2 스레딩·Task 3 ENTRY_MODES 일치. stats 반환 키 = Task 4 출력 파싱과 일치.
