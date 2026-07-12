# 백테스트 백필 — 동시성 수정 + 서킷브레이커 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (또는 executing-plans). Steps use checkbox (`- [ ]`) syntax.

**Goal:** 백테스트 백필의 ~90% rc=1 실패(동시성 원인)를 없애고, 진짜 사용량 한도/CLI 장애 시 헛돌지 않고 깨끗이 멈추게 한다.

**Architecture:** 진단 결과 `claude` CLI를 4-way 동시 호출하면 ~90%가 rc=1 빈출력으로 실패하고, **2-way(c2)·1-way(c1)는 100% 성공**(실측 c1 5/5, c2 5/5, c4 9.6%). 한 건 ≈103s. 그래서 (1) 백테스트 백필 기본 동시성을 **2**로 낮추고, (2) **고-실패율 서킷브레이커**(한 주 실패율 ≥ 임계인 '나쁜 주'가 K=2회 연속이면 클린 중단)를 추가한다. 서킷브레이커는 **실패율 기반**이라 하드 한도(100% 실패)뿐 아니라 **만성 부분실패**(예: 1건만 성공+대량 실패 = c4 패턴)도 잡는다 — `processed==0`만 보면 1건이라도 성공한 주가 카운터를 리셋해 못 잡으므로. 둘 다 `kr_pipeline/backtest/backfill.py` 안에서만 — 운영 코드(`claude_cli`, `parallel.py`, 운영 `llm_runner/backfill.py`)는 안 건드린다.

**Tech Stack:** Python, pytest(monkeypatch — 실 LLM/DB 작업 없음).

## Global Constraints

- **수정 범위 격리**: `kr_pipeline/backtest/backfill.py` 만 변경. 운영 backfill/claude_cli/parallel 불변(운영 동시성 4 default 유지 — 이 이슈는 백테스트의 대량·연속 호출에서 드러난 것).
- **동시성 기본 = 2** (실측 안전 상한; c4는 9.6%로 실패). 명시적 `concurrency=` 인자는 그대로 override 가능.
- **서킷브레이커**: 한 주 실패율 ≥ **0.5**(`CIRCUIT_BREAKER_FAIL_RATE`)인 '나쁜 주'가 **K=2** 연속이면 클린 중단(적재분 보존, rerun=resume). '좋은 주'(실패율<임계) 1회면 카운터 리셋. 시도수 < **3**(`CIRCUIT_BREAKER_MIN_SAMPLE`)인 주는 판정 보류(카운터 유지). **`processed==0`(전부실패)만이 아니라 만성 부분실패(1건 성공+대량 실패)도 잡도록 실패율 기반.**
- **claude_cli 의 rc=1 빈출력 → UsageLimitError 재분류는 하지 않는다**(공유 코드·오탐 위험). 서킷브레이커가 systemic 실패(한도·CLI깨짐·인증만료)를 원인 불문 커버.
- **LLM 비결정성·멱등 규율 유지**: 적재분 보존, rerun 시 skip. 이 plan에 실백필 실행은 포함하지 않음(도구 수정만).
- 커밋 메시지에 Co-Authored-By trailer 금지.
- 회귀 판정: base↔HEAD 실패 수 비교(현 baseline 24). 새 실패 0.

---

### Task 1: 백테스트 백필 기본 동시성 = 2

**Files:**
- Modify: `kr_pipeline/backtest/backfill.py` (모듈 상수 추가 + `run_backtest_backfill` line 68)
- Test: `tests/test_backtest_backfill_concurrency.py` (create)

**Interfaces:**
- Consumes: 기존 `run_backtest_backfill(conn, *, start, end, tickers, dry_run=False, concurrency=None)`
- Produces: `BT_CONCURRENCY = 2` 모듈 상수. `concurrency=None` 일 때 2 사용(기존엔 env BACKFILL_CONCURRENCY or 4). 명시 인자 우선.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_backtest_backfill_concurrency.py
from datetime import date


def _ok_batch():
    return {"processed": 1, "failed_tickers": [], "integrity_skipped": [],
            "usage_limited": False, "usage_error": None}


def test_default_concurrency_is_2(db, monkeypatch):
    from kr_pipeline.backtest import backfill as bt
    captured = {}
    monkeypatch.setattr(bt, "get_qualifying_tickers",
                        lambda conn, as_of, tickers=None: [{"symbol": "X", "market": "KOSPI"}])
    monkeypatch.setattr(bt, "already_done", lambda conn, as_of: set())

    def fake_batch(*, dsn, candidates, process_fn, concurrency, dry_run, as_of, run_id=None, abort=None):
        captured["concurrency"] = concurrency
        return _ok_batch()
    monkeypatch.setattr(bt, "run_parallel_batch", fake_batch)

    bt.run_backtest_backfill(db, start=date(2022, 9, 5), end=date(2022, 9, 11),
                             tickers=["X"], dry_run=False)        # no concurrency arg
    assert captured["concurrency"] == 2


def test_explicit_concurrency_overrides(db, monkeypatch):
    from kr_pipeline.backtest import backfill as bt
    captured = {}
    monkeypatch.setattr(bt, "get_qualifying_tickers",
                        lambda conn, as_of, tickers=None: [{"symbol": "X", "market": "KOSPI"}])
    monkeypatch.setattr(bt, "already_done", lambda conn, as_of: set())
    def fake_batch(*, dsn, candidates, process_fn, concurrency, dry_run, as_of, run_id=None, abort=None):
        captured["concurrency"] = concurrency
        return _ok_batch()
    monkeypatch.setattr(bt, "run_parallel_batch", fake_batch)

    bt.run_backtest_backfill(db, start=date(2022, 9, 5), end=date(2022, 9, 11),
                             tickers=["X"], dry_run=False, concurrency=1)
    assert captured["concurrency"] == 1
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_backtest_backfill_concurrency.py::test_default_concurrency_is_2 -v`
Expected: FAIL — `assert 4 == 2` (현재 env-or-4 default).

- [ ] **Step 3: 구현**

`kr_pipeline/backtest/backfill.py` 상수 블록(`BT_SOURCE = "backtest"` 아래)에 추가:

```python
BT_CONCURRENCY = 2   # 실측 안전 동시성 상한 (c1·c2=100%, c4=9.6% rc=1 실패). 한 건 ≈103s.
```

line 68 을 교체:

```python
    concurrency = concurrency or BT_CONCURRENCY
```

`import os`(line 10) **제거** — line 68 이 유일 사용처라 교체 후 미사용 import 가 됨(확인필: backfill.py 내 `os.` 다른 사용 없음).

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_backtest_backfill_concurrency.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/backfill.py tests/test_backtest_backfill_concurrency.py
git commit -m "fix(backtest): 백필 기본 동시성 4→2 (claude CLI 4-way rc=1 대량실패 회피)"
```

---

### Task 2: 고-실패율 서킷브레이커 (클린 중단)

**Files:**
- Modify: `kr_pipeline/backtest/backfill.py` (`run_backtest_backfill` 루프 + agg 초기화 + 상수)
- Test: `tests/test_backtest_backfill_circuit_breaker.py` (create)

**Interfaces:**
- Produces: 상수 `CIRCUIT_BREAKER_WEEKS = 2`, `CIRCUIT_BREAKER_FAIL_RATE = 0.5`, `CIRCUIT_BREAKER_MIN_SAMPLE = 3`. `run_backtest_backfill` 반환 agg 에 `circuit_broken: bool`, (트립 시) `stop_reason: str` 추가.
- 동작: 한 주 `fail_rate = failures/(processed+failures)`. 시도수(`processed+failures`) ≥ MIN_SAMPLE 인 주에 대해 — fail_rate ≥ FAIL_RATE 면 '나쁜 주'(카운터+1), 미만이면 '좋은 주'(카운터 0). 시도수 < MIN_SAMPLE 인 주는 판정 보류(카운터 유지). 나쁜 주 K연속이면 루프 break + agg 반환(raise 아님 — 요약 출력·적재분 보존). **`processed==0`(전부실패)뿐 아니라 1건만 성공+대량 실패(만성 부분실패)도 트립.**

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_backtest_backfill_circuit_breaker.py
from datetime import date


def _batch(processed, failed):
    return {"processed": processed,
            "failed_tickers": [{"symbol": f"X{i}", "error": "rc=1"} for i in range(failed)],
            "integrity_skipped": [], "usage_limited": False, "usage_error": None}


def _wire(monkeypatch, bt, results):
    """results: 호출 순서대로 반환할 배치결과 리스트(소진되면 마지막 반복)."""
    monkeypatch.setattr(bt, "get_qualifying_tickers",
                        lambda conn, as_of, tickers=None: [{"symbol": "X", "market": "KOSPI"}])
    monkeypatch.setattr(bt, "already_done", lambda conn, as_of: set())
    seq = {"i": 0}
    def fake_batch(**kwargs):
        i = seq["i"]; seq["i"] += 1
        return results[i] if i < len(results) else results[-1]
    monkeypatch.setattr(bt, "run_parallel_batch", fake_batch)


def test_trips_on_total_failure(db, monkeypatch):
    from kr_pipeline.backtest import backfill as bt
    _wire(monkeypatch, bt, [_batch(0, 10)])           # 매주 100% 실패
    agg = bt.run_backtest_backfill(db, start=date(2022, 1, 1), end=date(2022, 2, 28),
                                   tickers=["X"], dry_run=False)
    assert agg["circuit_broken"] is True
    assert agg["weeks"] == 2 and "stop_reason" in agg


def test_trips_on_chronic_partial_failure(db, monkeypatch):
    """핵심: 1건만 성공 + 나머지 대량 실패(=c4 패턴)도 트립해야 함."""
    from kr_pipeline.backtest import backfill as bt
    _wire(monkeypatch, bt, [_batch(1, 9)])            # 매주 90% 실패
    agg = bt.run_backtest_backfill(db, start=date(2022, 1, 1), end=date(2022, 2, 28),
                                   tickers=["X"], dry_run=False)
    assert agg["circuit_broken"] is True
    assert agg["weeks"] == 2          # processed>0 이어도 fail_rate 기준으로 트립


def test_good_week_resets_counter(db, monkeypatch):
    from kr_pipeline.backtest import backfill as bt
    # 나쁨(90%), 좋음(20%), 나쁨, 나쁨 → 4주차에 2연속 채워 트립
    _wire(monkeypatch, bt, [_batch(1, 9), _batch(8, 2), _batch(1, 9), _batch(1, 9)])
    agg = bt.run_backtest_backfill(db, start=date(2022, 1, 1), end=date(2022, 2, 28),
                                   tickers=["X"], dry_run=False)
    assert agg["circuit_broken"] is True
    assert agg["weeks"] == 4


def test_no_trip_low_failure_rate(db, monkeypatch):
    from kr_pipeline.backtest import backfill as bt
    _wire(monkeypatch, bt, [_batch(9, 1)])            # 매주 10% 실패 — 정상
    agg = bt.run_backtest_backfill(db, start=date(2022, 1, 1), end=date(2022, 1, 31),
                                   tickers=["X"], dry_run=False)
    assert agg["circuit_broken"] is False
    assert agg["weeks"] >= 4          # 전 주 순회 완료


def test_tiny_week_deferred(db, monkeypatch):
    """시도수 < MIN_SAMPLE 인 주는 판정 보류(단독으로 트립 안 함)."""
    from kr_pipeline.backtest import backfill as bt
    _wire(monkeypatch, bt, [_batch(0, 1)])            # 매주 1건 시도·실패 (sample=1 < 3)
    agg = bt.run_backtest_backfill(db, start=date(2022, 1, 1), end=date(2022, 1, 31),
                                   tickers=["X"], dry_run=False)
    assert agg["circuit_broken"] is False
    assert agg["weeks"] >= 4          # 보류라 트립 없이 완주
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_backtest_backfill_circuit_breaker.py -v`
Expected: FAIL — `KeyError: 'circuit_broken'` (아직 미구현).

- [ ] **Step 3: 구현**

상수 블록에 추가:

```python
CIRCUIT_BREAKER_WEEKS = 2        # 나쁜 주 K연속 시 클린 중단
CIRCUIT_BREAKER_FAIL_RATE = 0.5  # 한 주 실패율 >= 50% 면 '나쁜 주'
CIRCUIT_BREAKER_MIN_SAMPLE = 3   # 시도수 < 3 인 주는 판정 보류(노이즈 회피)
```

agg 초기화(line 69-70)에 `circuit_broken` 추가:

```python
    agg = {"weeks": 0, "processed": 0, "skipped_existing": 0, "failures": 0,
           "failed": [], "integrity_skipped": [], "start": str(start), "end": str(end),
           "circuit_broken": False}
```

루프 진입 전(`abort = threading.Event()` 다음 줄)에 카운터 초기화:

```python
    consec_bad_weeks = 0
```

루프 끝(기존 `if r["usage_limited"]: ... raise ...` 블록 **다음**, `return agg` 전)에 서킷브레이커 추가:

```python
        # 서킷브레이커: 한 주 실패율이 임계 이상인 '나쁜 주'가 K연속이면 systemic 실패로
        # 클린 중단. processed==0(하드 한도)뿐 아니라 1건만 성공+대량 실패(만성 부분실패=
        # 동시성 저하 등)도 잡는다. 시도수 적은 주는 판정 보류(노이즈 회피).
        # (rc=1 빈출력 형태의 한도/장애가 UsageLimitError 로 안 잡혀도 여기서 멈춤.)
        week_total = r["processed"] + len(r["failed_tickers"])
        if week_total >= CIRCUIT_BREAKER_MIN_SAMPLE:
            fail_rate = len(r["failed_tickers"]) / week_total
            if fail_rate >= CIRCUIT_BREAKER_FAIL_RATE:
                consec_bad_weeks += 1
                if consec_bad_weeks >= CIRCUIT_BREAKER_WEEKS:
                    agg["circuit_broken"] = True
                    agg["stop_reason"] = (
                        f"{consec_bad_weeks} consecutive weeks with fail-rate "
                        f">= {CIRCUIT_BREAKER_FAIL_RATE:.0%} (likely usage limit / "
                        f"concurrency / CLI failure) — 적재분 보존, rerun=resume"
                    )
                    log.warning("bt-backfill circuit breaker: %s", agg["stop_reason"])
                    break
            else:
                consec_bad_weeks = 0
        # week_total < MIN_SAMPLE: 판정 보류(카운터 유지)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_backtest_backfill_circuit_breaker.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 백테스트 회귀 확인**

Run: `uv run pytest tests/ -k "backtest" -q`
Expected: 새 테스트 전부 PASS, 기존 backtest 테스트 불변(특히 `test_backtest_backfill.py` dry_run·idempotent skip).

- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/backtest/backfill.py tests/test_backtest_backfill_circuit_breaker.py
git commit -m "feat(backtest): 백필 고-실패율 서킷브레이커 — 한도/만성부분실패/장애 시 클린 중단"
```

---

## Self-Review (작성자 체크)

**Spec(우리 합의) coverage:**
- 동시성 수정(필수) → Task 1(default 2). 서킷브레이커(안전망) → Task 2. 캡(비권장) → 미채택, 합의대로.
- 운영 코드 불변(claude_cli/parallel/운영 backfill) → 두 Task 모두 backtest/backfill.py 한정. ✓
- claude_cli rc=1 재분류 안 함 → Global Constraints 명시, 서킷브레이커로 대체. ✓

**Placeholder scan:** 모든 step에 실제 코드/명령. 없음.

**Type consistency:** `BT_CONCURRENCY`(Task 1), `CIRCUIT_BREAKER_WEEKS`/`CIRCUIT_BREAKER_FAIL_RATE`/`CIRCUIT_BREAKER_MIN_SAMPLE`(Task 2) 상수, 변수 `consec_bad_weeks`, agg 키 `circuit_broken`/`stop_reason` — 테스트와 구현 일치. 기존 `already_done`/`run_parallel_batch`/`get_qualifying_tickers` monkeypatch 대상 = 모듈 네임스페이스 이름(import된 형태), 패치 유효.

**한계(의도된):**
- 서킷브레이커는 **주 단위·실패율 기반**. 만성 부분실패(1건 성공+대량 실패)도 잡지만, 트립까지 최대 K(=2)주의 호출은 churn(각 claude_cli 4회 재시도, rc=1은 즉시라 ~주당 수십초). 운영 parallel.py(공유) 안 건드리려는 의도적 트레이드오프 — 이전 2시간 churn 대비 무시할 수준.
- 임계값(FAIL_RATE 0.5 / MIN_SAMPLE 3 / WEEKS 2)은 c2 정상=~0% 실패 vs systemic=≥90% 를 분리하는 실측 기반 보수값. 정상 산발실패(소수%)엔 안 트립.
- 동시성 2는 실측 안전값. c3 미검(필요 시 별도 probe). c2로 c1 대비 활성 작업시간 절반.

## 실행 후 (이 plan 범위 밖, 사용자 별도 지시)
- resume: `python -m kr_pipeline.backtest.profitability_cli backfill` (이제 c2 + 서킷브레이커). 한도 도달 시 서킷브레이커로 클린 중단 → 리셋 후 rerun=resume. 현재 적재 119건은 skip.
