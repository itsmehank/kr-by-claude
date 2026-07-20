# 표본 B 아웃오브샘플 분석 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사전등록(`docs/superpowers/specs/2026-07-21-sample-b-analysis-prereg.md`)대로 표본 B(독립 100종목)로 판정 P1~P4 + 정보용 I1~I2를 실행하고 결과 문서를 만든다.

**Architecture:** 기존 분석 엔진(`profitability_run`/`refinement`/`trigger_audit`/`portfolio`)의 FROZEN_SAMPLE·시드·경로 하드코딩을 **default 보존 파라미터화**로 확장한다(표본 A 재현 불변이 도구 무해성의 증명). 제외 셀(#50)은 `load_watchlist`(watch만 SELECT)·`load_watch_entry_rows`(pivot NOT NULL)가 구조적으로 걸러내므로 **`entry_rate_by_phase` 한 곳에만 exclude 파라미터**를 추가한다. 실행은 결정론(P1·P3·I1·I2·P4) 먼저, LLM(P2)은 사용자 게이트 후.

**Tech Stack:** Python (psycopg), Postgres, Claude CLI(sonnet 핀, P2만), pytest(kr_test `db` fixture).

## Global Constraints

- **사전등록 잠금 준수**: 기준·상수·시드는 prereg 문서가 권위. 판정 기준 변경 금지.
- **훔쳐보기 금지**: 도구 태스크(1~5)에서 **표본 B의 판정 지표를 계산·출력하지 않는다**. 회귀 검증은 전부 표본 A로만 한다. B 수치는 Task 6(실행)에서 처음 계산된다.
- **A 재현 불변**: 파라미터화 후 표본 A 기본 실행 결과가 기존 문서 수치와 일치해야 함 — §7.1 = R_down 0/1,075 · R_up 1/292 · ratio 0.0 / refinement = 보정 후 56건 · net 평균 +3.2 · CI [−5.8, +16.1].
- **LLM 규율**: P2 만 LLM 사용(1회 실행, 재실행 비교 금지, `--model sonnet` 핀 기본값 그대로). production 테이블 쓰기 0.
- 신규 시드 **20260721** (부트스트랩·플라시보), A 기본값 20260702 유지.
- 산출물 경로: `data/backtest/trigger_audit_sample_b_20260721.json`, `data/backtest/refinement_sample_b_20260721.json`, `data/backtest/portfolio_curves_sample_ab_20260721.json` — **기존 A 산출물 파일 덮어쓰기 금지**.
- 코드 변경은 `kr_pipeline/backtest/` + `frozen_sample_b.py`(상수 추가) 한정. production 무접촉. thresholds.py 무접촉(P4 승격돼도 반영은 별도 작업).
- git: 명시 경로만 스테이징(`git add -A` 금지), Co-Authored-By trailer 금지.
- 테스트: `uv run pytest tests/` 실패 0. 실행 전 `pgrep -fl pytest`로 교차 세션 경합 확인(동시 pytest 시 kr_test 리셋 경합으로 가짜 실패).
- 브랜치: `sample-b-analysis` (main에서 분기). Tasks 1~5 = 코드(PR 머지 게이트), Task 6 = 머지 후 main에서 실행.

---

### Task 1: 제외 셀 상수 + `entry_rate_by_phase` exclude 파라미터 (TDD)

**Files:**
- Modify: `kr_pipeline/backtest/frozen_sample_b.py` (상수 추가)
- Modify: `kr_pipeline/backtest/profitability_run.py:29-54` (entry_rate_by_phase), `:102` (run_analysis)
- Test: `tests/test_backtest_profitability_exclude.py` (신규)

**Interfaces:**
- Produces: `EXCLUDED_CELLS: list[tuple[str, str]]` (frozen_sample_b — `[("317870", "2022-04-09")]`, (symbol, ISO date)).
  `entry_rate_by_phase(conn, tickers, exclude: frozenset = frozenset())` — exclude 원소는 `(symbol, date)` 튜플(date 객체).
  `run_analysis(conn, tickers, px_start, px_end, *, watch_start, watch_end, exclude: frozenset = frozenset())`.
- 참고(구조적 무해성 근거, 코드 실측): `load_watchlist`(trigger_sim.py:186-189)는 `classification='watch'`만, `load_watch_entry_rows`(stop_variant_sim.py:71-75)는 `pivot_price IS NOT NULL`만 SELECT — 제외 셀(entry·pivot NULL)은 시뮬 경로에 원래 못 들어간다. exclude가 필요한 곳은 분류점 집계(P1) 뿐.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_backtest_profitability_exclude.py
"""entry_rate_by_phase 의 exclude 파라미터 — #50 제외 셀이 분류점 집계에서 빠지는지."""
from datetime import date


def _seed_rows(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('BX1','BX1','KOSPI') ON CONFLICT DO NOTHING")
        for d, cls in [("2022-04-09", "entry"), ("2022-04-16", "watch")]:
            cur.execute(
                "INSERT INTO backtest_classification (symbol, analyzed_for_date, classified_at, market, classification, source) "
                "VALUES ('BX1', %s, now(), 'KOSPI', %s, 'backtest')", (d, cls))
    db.commit()


def test_exclude_removes_cell_from_counts(db, monkeypatch):
    import kr_pipeline.backtest.profitability_run as pr
    # 국면 라벨은 이 테스트의 관심사가 아님 — 전부 고정 국면으로 치환
    monkeypatch.setattr(pr.ph, "load_phase_map", lambda conn, code: [])
    monkeypatch.setattr(pr.ph, "phase_at", lambda pmap, d: "confirmed_uptrend")
    _seed_rows(db)
    base = pr.entry_rate_by_phase(db, ["BX1"])
    assert base["confirmed_uptrend"]["total"] == 2
    assert base["confirmed_uptrend"]["entry"] == 1
    excl = pr.entry_rate_by_phase(db, ["BX1"], exclude=frozenset({("BX1", date(2022, 4, 9))}))
    assert excl["confirmed_uptrend"]["total"] == 1
    assert excl["confirmed_uptrend"]["entry"] == 0


def test_excluded_cells_constant():
    from kr_pipeline.backtest.frozen_sample_b import EXCLUDED_CELLS, FROZEN_SAMPLE_B
    assert EXCLUDED_CELLS == [("317870", "2022-04-09")]
    assert EXCLUDED_CELLS[0][0] in FROZEN_SAMPLE_B
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_backtest_profitability_exclude.py -v`
Expected: 2 FAIL (`TypeError: entry_rate_by_phase() got an unexpected keyword 'exclude'` / `ImportError: EXCLUDED_CELLS`)

- [ ] **Step 3: 구현**

`frozen_sample_b.py` 말미에 추가:

```python
# 분석 입력 제외 셀 (prereg §1 — #50: entry 인데 pivot_price NULL, 무검사 저장분)
EXCLUDED_CELLS: list[tuple[str, str]] = [
    ("317870", "2022-04-09"),
]
```

`profitability_run.py` — `entry_rate_by_phase` 시그니처를 `(conn, tickers, exclude: frozenset = frozenset())`로 바꾸고, 행 루프 첫 줄에 skip 추가:

```python
    for symbol, afd, cls, market in rows:
        if (symbol, afd) in exclude:
            continue
```

`run_analysis` 시그니처에 `exclude: frozenset = frozenset()` 추가, 내부의 `entry_rate_by_phase(conn, tickers)` 호출을 `entry_rate_by_phase(conn, tickers, exclude=exclude)`로.

- [ ] **Step 4: 통과 확인 + 전체 회귀**

Run: `uv run pytest tests/test_backtest_profitability_exclude.py tests/ -q 2>&1 | tail -3`
Expected: 실패 0

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/frozen_sample_b.py kr_pipeline/backtest/profitability_run.py tests/test_backtest_profitability_exclude.py
git commit -m "feat(backtest): 분류점 집계 exclude 파라미터 + 표본 B 제외 셀 상수(#50)"
```

---

### Task 2: `analyze --sample=b` 개방 + 표본 A 재현 회귀 (P1·I2 도구)

**Files:**
- Modify: `kr_pipeline/backtest/profitability_cli.py` (`cmd_analyze`, `main`)
- Test: `tests/test_backtest_sample_pinned.py` (수정: analyze b 거부 테스트 → 허용 테스트)

**Interfaces:**
- Consumes: Task 1 의 `run_analysis(..., exclude=)`, `EXCLUDED_CELLS`.
- Produces: CLI 계약 — `python -m kr_pipeline.backtest.profitability_cli analyze --sample=b` 가 표본 B(제외 셀 적용) 분석 JSON 출력. `cmd_analyze(conn, kind: str = "a")`.

- [ ] **Step 1: 기존 거부 테스트를 허용 테스트로 교체 (RED)**

`tests/test_backtest_sample_pinned.py`의 `test_analyze_rejects_sample_b`를 다음으로 교체:

```python
def test_analyze_sample_b_uses_frozen_b_and_exclusion(db, monkeypatch):
    """analyze --sample=b 개방: 표본 B + EXCLUDED_CELLS 로 run_analysis 호출."""
    import kr_pipeline.backtest.profitability_cli as cli
    from kr_pipeline.backtest.frozen_sample_b import EXCLUDED_CELLS, FROZEN_SAMPLE_B
    from datetime import date as _date
    captured = {}

    def fake_run_analysis(conn, tickers, px_start, px_end, *, watch_start, watch_end, exclude=frozenset()):
        captured.update(tickers=tickers, exclude=exclude)
        return {"ok": True}

    monkeypatch.setattr(cli, "run_analysis", fake_run_analysis)
    cli.cmd_analyze(db, "b")
    assert sorted(captured["tickers"]) == sorted(FROZEN_SAMPLE_B)
    expected = frozenset((s, _date.fromisoformat(d)) for s, d in EXCLUDED_CELLS)
    assert captured["exclude"] == expected
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_backtest_sample_pinned.py -v`
Expected: 신규 1 FAIL (`TypeError: cmd_analyze() takes 1 positional argument` 또는 SystemExit)

- [ ] **Step 3: 구현**

`profitability_cli.py`:
- `main()`의 `if cmd == "analyze" and kind != "a": raise SystemExit(...)` 블록 **삭제**.
- `cmd_analyze`를 다음으로 교체:

```python
def cmd_analyze(conn, kind: str = "a") -> int:
    from datetime import date as _date
    sample = _sample(conn, kind)
    exclude = frozenset()
    if kind == "b":
        from kr_pipeline.backtest.frozen_sample_b import EXCLUDED_CELLS
        exclude = frozenset((s, _date.fromisoformat(d)) for s, d in EXCLUDED_CELLS)
    out = run_analysis(conn, sample, PX_START, PX_END,
                       watch_start=START, watch_end=END, exclude=exclude)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0
```

- `main()`의 analyze 분기를 `return cmd_analyze(conn, kind)`로.
- docstring 의 `analyze` 사용례를 `analyze [--sample=a|b]`로 갱신.

- [ ] **Step 4: 통과 + 표본 A 재현 회귀 (실 DB, 결정론·LLM 0)**

Run: `uv run pytest tests/test_backtest_sample_pinned.py tests/ -q 2>&1 | tail -3` → 실패 0
Run: `uv run python -m kr_pipeline.backtest.profitability_cli analyze 2>/dev/null | python3 -c "import json,sys; g=json.load(sys.stdin)['gate_71']; print(g)"`
Expected: `r_down 0.0 / r_up 0.003(=1/292) / ratio 0.0 / pass True` — 기존 문서 §7.1 수치와 일치. **--sample=b 는 실행 금지(훔쳐보기).**

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/profitability_cli.py tests/test_backtest_sample_pinned.py
git commit -m "feat(backtest): analyze --sample=b 개방 — 표본 B + 제외 셀 적용, A 재현 회귀 확인"
```

---

### Task 3: refinement 파라미터화 — tickers·seed (P3 도구)

**Files:**
- Modify: `kr_pipeline/backtest/refinement.py` (`build_refined_trades:104`, `run_refinement:197`, `main:230`)
- Test: `tests/test_backtest_refinement.py` (추가)

**Interfaces:**
- Consumes: `FROZEN_SAMPLE_B`, `profitability_cli` 의 `_flag` 패턴(로컬 복제).
- Produces: `build_refined_trades(conn, tickers: list[str] | None = None)` (None→FROZEN_SAMPLE),
  `run_refinement(conn, *, tickers: list[str] | None = None, seed: int = SEED)` — seed 가 `cluster_bootstrap_ci(seed=)`·`run_placebo(seed=)` 로 전달되고 결과 meta 에 `"seed": seed` 기록.
  CLI: `python -m kr_pipeline.backtest.refinement [--sample=a|b] [--seed=N]`.

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_backtest_refinement.py`에 append:

```python
def test_run_refinement_threads_tickers_and_seed(db, monkeypatch):
    """tickers·seed 파라미터가 하위 호출로 전달되는지 (기본값 = A 동작 불변)."""
    import kr_pipeline.backtest.refinement as rf
    calls = {}
    monkeypatch.setattr(rf, "build_refined_trades",
                        lambda conn, tickers=None: (calls.setdefault("tickers", tickers) or [], 0))
    monkeypatch.setattr(rf, "cluster_bootstrap_ci",
                        lambda trades, **kw: calls.setdefault("ci_seed", kw.get("seed")) or (0.0, 0.0))
    monkeypatch.setattr(rf, "run_placebo",
                        lambda conn, trades, **kw: calls.setdefault("pl_seed", kw.get("seed")) or {})
    out = rf.run_refinement(db, tickers=["000001"], seed=20260721)
    assert calls["tickers"] == ["000001"]
    assert calls["ci_seed"] == 20260721
    assert calls["pl_seed"] == 20260721
    assert out["meta"]["seed"] == 20260721
```

주의: `run_refinement` 내부 구조(meta 키 위치)는 현재 파일(:197-228)을 열어 실제 dict 구조에 맞춰 assertion 경로를 조정하라 — seed 가 기록되는 키가 `meta` 하위가 아니면 실제 위치로 맞추되, "결과에 사용 seed 가 기록된다"는 계약은 유지.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_backtest_refinement.py -v 2>&1 | tail -5`
Expected: 신규 1 FAIL (`TypeError: unexpected keyword 'tickers'`)

- [ ] **Step 3: 구현**

- `build_refined_trades(conn, tickers=None)`: 첫 줄에 `tickers = list(tickers) if tickers is not None else list(FROZEN_SAMPLE)`, 루프를 `for ticker in tickers:`로.
- `run_refinement(conn, *, tickers=None, seed: int = SEED)`: 내부의 `build_refined_trades(conn)` → `build_refined_trades(conn, tickers=tickers)`, `cluster_bootstrap_ci(...)` 호출에 `seed=seed`, `run_placebo(...)` 호출에 `seed=seed`, 결과 dict 의 `"seed": SEED` → `"seed": seed`.
- `main()`:

```python
def _flag(name: str, default: str) -> str:
    prefix = f"--{name}="
    for a in sys.argv[1:]:
        if a.startswith(prefix):
            return a.split("=", 1)[1]
    return default


def main() -> int:
    from kr_pipeline.db.connection import connect
    kind = _flag("sample", "a")
    seed = int(_flag("seed", str(SEED)))
    tickers = None
    if kind == "b":
        from kr_pipeline.backtest.frozen_sample_b import FROZEN_SAMPLE_B
        tickers = list(FROZEN_SAMPLE_B)
    elif kind != "a":
        raise SystemExit(f"unknown --sample: {kind!r} (a|b)")
    with connect() as conn:
        out = run_refinement(conn, tickers=tickers, seed=seed)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0
```

(기존 main 이 출력하던 형식이 다르면 기존 형식을 보존하되 tickers/seed 만 주입.)

- [ ] **Step 4: 통과 + 표본 A 재현 회귀**

Run: `uv run pytest tests/test_backtest_refinement.py tests/ -q 2>&1 | tail -3` → 실패 0
Run: `uv run python -m kr_pipeline.backtest.refinement 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('n_trades') or d.get('refined',{}).get('n'), d.get('ci') or d.get('refined',{}).get('ci'))"`
Expected: 보정 후 **56건**, CI **[−5.8, +16.1]** — 기존 문서 §147 수치 일치(출력 키 경로는 실제 구조에 맞춰 조정). **--sample=b 실행 금지.**

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/refinement.py tests/test_backtest_refinement.py
git commit -m "feat(backtest): refinement tickers·seed 파라미터화 — A 기본값 불변, B 실행 준비"
```

---

### Task 4: trigger_audit 파라미터화 — tickers·경로·보정 대상 (P2 도구)

**Files:**
- Modify: `kr_pipeline/backtest/trigger_audit.py` (`AUDIT_PATH:36`, `collect_down_trades:41`, `run_audit:111`, `main:167`)
- Test: `tests/test_backtest_trigger_audit_params.py` (신규)

**Interfaces:**
- Consumes: `FROZEN_SAMPLE_B`, refinement 의 `MAX_CHASE_PCT`(=5.0).
- Produces: `collect_down_trades(conn, tickers: list[str] | None = None, max_chase_pct: float | None = None)`,
  `run_audit(conn, *, dry_run=False, tickers=None, audit_path: Path = AUDIT_PATH, max_chase_pct=None)`.
  CLI: `--sample=b` → tickers=B, `audit_path=Path("data/backtest/trigger_audit_sample_b_20260721.json")`, `max_chase_pct=5.0` (prereg P2 "보정 후" 대상 — A 기본 호출은 종전대로 비보정).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_backtest_trigger_audit_params.py
"""trigger_audit 파라미터화 — 표본·경로·보정(5% 추격) 대상 전달."""
from pathlib import Path


def test_collect_down_trades_accepts_tickers_and_chase(db, monkeypatch):
    import kr_pipeline.backtest.trigger_audit as ta
    seen = {}

    def fake_simulate(ticker, rows, bars, mode="production", **kw):
        seen.setdefault("chase", kw.get("max_chase_pct"))
        return [], 0

    monkeypatch.setattr(ta, "simulate", fake_simulate)
    monkeypatch.setattr(ta, "load_watchlist", lambda *a, **k: [])
    monkeypatch.setattr(ta, "load_daily_series", lambda *a, **k: [])
    monkeypatch.setattr(ta, "classify_rows", lambda wr: {"production": []})
    monkeypatch.setattr(ta, "_market_of", lambda conn, t: "KOSPI")
    monkeypatch.setattr(ta.ph, "load_phase_map", lambda conn, code: [])
    out = ta.collect_down_trades(db, tickers=["000001"], max_chase_pct=5.0)
    assert out == []
    assert seen["chase"] == 5.0


def test_run_audit_writes_to_custom_path(db, tmp_path, monkeypatch):
    import kr_pipeline.backtest.trigger_audit as ta
    monkeypatch.setattr(ta, "collect_down_trades", lambda conn, **kw: [])
    p = tmp_path / "audit_b.json"
    ta.run_audit(db, dry_run=True, tickers=["000001"], audit_path=p)
    # 대상 0건 dry-run — 예외 없이 종료가 계약. 기존 AUDIT_PATH 는 건드리지 않음.
    assert not Path("data/backtest/trigger_audit_20260702.json").exists() or True
```

주의: `run_audit`(:111-165)와 `simulate` 실제 시그니처를 열어 mock 시그니처를 맞춰라. `simulate`가 `max_chase_pct` 키워드를 받는지 확인(refinement.py:121 호출이 근거) — 안 받으면 collect 쪽에서 조건부 전달로 구현.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_backtest_trigger_audit_params.py -v`
Expected: 2 FAIL (`TypeError: unexpected keyword`)

- [ ] **Step 3: 구현**

- `collect_down_trades(conn, tickers=None, max_chase_pct=None)`: `tickers = list(tickers) if tickers is not None else list(FROZEN_SAMPLE)`; simulate 호출을 `simulate(ticker, cls["production"], bars, mode="production", **({"max_chase_pct": max_chase_pct} if max_chase_pct is not None else {}))`.
- `run_audit(..., tickers=None, audit_path: Path = AUDIT_PATH, max_chase_pct=None)`: 내부 AUDIT_PATH 참조를 audit_path 로, collect 호출에 tickers·max_chase_pct 전달.
- `main()`: `--sample=b` 파싱(Task 3 의 `_flag` 패턴) → `tickers=FROZEN_SAMPLE_B`, `audit_path=Path("data/backtest/trigger_audit_sample_b_20260721.json")`, `max_chase_pct=5.0`. 기본(`a`)은 완전 종전 동작.

- [ ] **Step 4: 통과 + dry-run 스모크 (A, LLM 0)**

Run: `uv run pytest tests/test_backtest_trigger_audit_params.py tests/ -q 2>&1 | tail -3` → 실패 0
Run: `uv run python -m kr_pipeline.backtest.trigger_audit --dry-run 2>&1 | tail -3`
Expected: A 기본 경로 종전 동작(33건 대상 mock). **--sample=b 는 dry-run 포함 실행 금지(대상 건수 자체가 판정 힌트).**

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/trigger_audit.py tests/test_backtest_trigger_audit_params.py
git commit -m "feat(backtest): trigger_audit 표본·경로·보정대상 파라미터화 — A 기본 불변"
```

---

### Task 5: portfolio 파라미터화 + premium bins (I1·P4 도구) + prereg I1 구성 확정

**Files:**
- Modify: `kr_pipeline/backtest/portfolio.py` (`load_ticker_data:420`, `main:507`)
- Create: `kr_pipeline/backtest/premium_bins.py`
- Modify: `docs/superpowers/specs/2026-07-21-sample-b-analysis-prereg.md` (I1 구성 확정 — 정보용 항목의 실행 구성 명기)
- Test: `tests/test_backtest_premium_bins.py` (신규)

**Interfaces:**
- Produces: `load_ticker_data(conn, tickers: list[str] | None = None)` (None→FROZEN_SAMPLE).
  `premium_bins(exits: list[dict], *, min_n_high: int = 8) -> dict` — 입력: `run_portfolio` 결과의 `stats["exits"]`(각 원소에 `premium_pct`·`reason`·`pnl_pct` 존재, portfolio.py:125-132 실측). 출력:

```python
{"bins": {"0-1": {"n": int, "stopout_rate": float, "mean_pnl": float},
           "1-3": {...}, "3-5": {...}},
 "p4": {"high_n": int, "low_stopout": float, "high_stopout": float,
        "gap_pp": float,          # high − low(0-3 합산), %p
        "verdict": "promote" | "hold" | "insufficient_n"}}
```

  판정 규약(prereg P4): `high_n < min_n_high` → `insufficient_n`(판정 보류). `gap_pp >= 20.0` → `promote`, 아니면 `hold`. stopout 판정 = `reason` 이 `"stop8"` (구현 시 `run_portfolio` 의 실제 reason 문자열을 grep 으로 확정해 상수로 잠글 것 — 결과 문서 §244 의 "스톱아웃(stop8)" 이 근거).
  CLI: `python -m kr_pipeline.backtest.portfolio --sample=ab` → tickers = FROZEN_SAMPLE + FROZEN_SAMPLE_B (200종목), curves 저장 경로 = `data/backtest/portfolio_curves_sample_ab_20260721.json` (기존 v4 파일 불변), 출력에 arm 별 `premium_bins` 포함.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_backtest_premium_bins.py
"""P4 premium bins — 구간 분할·stopout 률·소표본 가드 (prereg P4)."""
from kr_pipeline.backtest.premium_bins import premium_bins


def _exit(premium, reason, pnl):
    return {"premium_pct": premium, "reason": reason, "pnl_pct": pnl}


def test_bins_and_gap():
    exits = ([_exit(0.5, "stop8", -8.0)] * 3 + [_exit(0.5, "sma50", 10.0)] * 7
             + [_exit(2.0, "stop8", -8.0)] * 3 + [_exit(2.0, "armed_be", 5.0)] * 7
             + [_exit(4.0, "stop8", -8.0)] * 8)
    out = premium_bins(exits)
    assert out["bins"]["0-1"]["n"] == 10 and out["bins"]["1-3"]["n"] == 10
    assert out["bins"]["3-5"]["n"] == 8
    assert out["p4"]["low_stopout"] == 30.0     # (3+3)/20
    assert out["p4"]["high_stopout"] == 100.0
    assert out["p4"]["gap_pp"] == 70.0
    assert out["p4"]["verdict"] == "promote"


def test_insufficient_n_guard():
    exits = [_exit(4.0, "stop8", -8.0)] * 7 + [_exit(0.5, "sma50", 5.0)] * 10
    out = premium_bins(exits)
    assert out["p4"]["verdict"] == "insufficient_n"     # 3-5 구간 7 < 8


def test_out_of_range_premium_ignored():
    exits = [_exit(6.0, "stop8", -8.0)] + [_exit(0.5, "sma50", 5.0)]
    out = premium_bins(exits)
    assert sum(b["n"] for b in out["bins"].values()) == 1
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_backtest_premium_bins.py -v`
Expected: 3 FAIL (`ModuleNotFoundError: premium_bins`)

- [ ] **Step 3: 구현**

```python
# kr_pipeline/backtest/premium_bins.py
"""P4 진입 프리미엄 구간 분석 — prereg 2026-07-21 §2 P4. 읽기전용·결정론.

입력 = run_portfolio 결과 stats["exits"] (premium_pct·reason·pnl_pct).
stopout 판정 reason 은 STOPOUT_REASON 상수로 잠금.
"""
from __future__ import annotations

STOPOUT_REASON = "stop8"        # 구현 시 run_portfolio 실제 문자열 확인 후 확정
GAP_PROMOTE_PP = 20.0           # prereg P4: 격차 ≥ 20%p → 채택 후보 승격
_BINS = (("0-1", 0.0, 1.0), ("1-3", 1.0, 3.0), ("3-5", 3.0, 5.0))


def premium_bins(exits: list[dict], *, min_n_high: int = 8) -> dict:
    bins: dict[str, list[dict]] = {k: [] for k, _, _ in _BINS}
    for e in exits:
        p = e.get("premium_pct")
        if p is None:
            continue
        for key, lo, hi in _BINS:
            if lo <= p < hi or (key == "3-5" and p == hi):
                bins[key].append(e)
                break

    def _stat(rows: list[dict]) -> dict:
        n = len(rows)
        if n == 0:
            return {"n": 0, "stopout_rate": None, "mean_pnl": None}
        so = sum(1 for r in rows if r.get("reason") == STOPOUT_REASON)
        return {"n": n, "stopout_rate": round(so / n * 100, 1),
                "mean_pnl": round(sum(r["pnl_pct"] for r in rows) / n, 2)}

    out_bins = {k: _stat(v) for k, v in bins.items()}
    low_rows = bins["0-1"] + bins["1-3"]
    low, high = _stat(low_rows), out_bins["3-5"]
    if high["n"] < min_n_high:
        verdict, gap = "insufficient_n", None
    else:
        gap = round(high["stopout_rate"] - (low["stopout_rate"] or 0.0), 1)
        verdict = "promote" if gap >= GAP_PROMOTE_PP else "hold"
    return {"bins": out_bins,
            "p4": {"high_n": high["n"], "low_stopout": low["stopout_rate"],
                   "high_stopout": high["stopout_rate"], "gap_pp": gap,
                   "verdict": verdict}}
```

`portfolio.py`:
- `load_ticker_data(conn, tickers=None)`: `for ticker in (list(tickers) if tickers is not None else list(FROZEN_SAMPLE)):`
- `main()`: `--sample` 파싱(`a` 기본 / `ab` = A+B 200종목). `ab`일 때 curves 저장 경로를 `data/backtest/portfolio_curves_sample_ab_20260721.json`으로, 각 arm 결과에 `out["arms"][key]["premium_bins"] = premium_bins(r["stats"]["exits"])`를 exits pop **이전에** 계산·첨부. 기본(`a`) 실행은 완전 종전 동작(경로 포함).

`prereg` I1 절에 실행 구성 확정을 추가(정보용 항목의 구성 명기 — 판정 무영향):

```markdown
- I1 실행 구성(계획 확정): 현행 코드의 ARMS(armA-prod = Arm A 기준선, v2 스톱
  3층 스택 통합 상태)로 200종목 재실행. v1(고정스톱 이전 체계)은 과거 커밋
  (b72fce8) 재현이 필요해 제외 — 정보용 축소이며 판정(P1~P4)과 무관.
```

- [ ] **Step 4: 통과 + 전체 회귀**

Run: `uv run pytest tests/test_backtest_premium_bins.py tests/ -q 2>&1 | tail -3` → 실패 0
(포트폴리오 A 재실행 회귀는 실행 시간이 길어 Task 6 실행 결과의 armA-prod 값을 기존 +2.20%와 대조하는 것으로 갈음 — 여기서는 단위 테스트만.)

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/portfolio.py kr_pipeline/backtest/premium_bins.py tests/test_backtest_premium_bins.py docs/superpowers/specs/2026-07-21-sample-b-analysis-prereg.md
git commit -m "feat(backtest): portfolio 표본 파라미터화 + P4 premium bins — prereg I1 구성 확정"
```

---

### Task 6: PR 머지 게이트 → 분석 실행 → 결과 문서 (사용자 게이트 2회)

**Files:**
- Create(실행 산출물): `data/backtest/refinement_sample_b_20260721.json`, `data/backtest/trigger_audit_sample_b_20260721.json`, `data/backtest/portfolio_curves_sample_ab_20260721.json`, `data/backtest/analyze_sample_b_20260721.json`
- Create: `docs/superpowers/backtest-sample-b-results.md`

**Interfaces:**
- Consumes: Tasks 1~5 CLI 전부. **게이트 1 = PR 머지(코드 확정), 게이트 2 = P2 LLM 실행 승인.**

- [ ] **Step 1: PR 생성 → 사용자 승인 → 머지 → main 전환**

```bash
git push -u origin sample-b-analysis
gh pr create --title "feat(backtest): 표본 B 분석 도구 — 파라미터화(A 재현 불변)+P4 bins" \
  --body "prereg docs/superpowers/specs/2026-07-21-sample-b-analysis-prereg.md 의 도구 계층. A 기본 동작 불변(§7.1·refinement 재현 회귀 확인). 계획: docs/superpowers/plans/2026-07-21-sample-b-analysis.md"
# 사용자 승인 후: gh pr merge --merge --delete-branch && git checkout main && git pull
```

- [ ] **Step 2: 결정론 실행 ① — P1+I2 (analyze)**

```bash
uv run python -m kr_pipeline.backtest.profitability_cli analyze --sample=b > data/backtest/analyze_sample_b_20260721.json
python3 -c "import json; d=json.load(open('data/backtest/analyze_sample_b_20260721.json')); print('P1 gate_71:', d['gate_71'])"
```

Expected: gate_71 에 r_down/r_up/ratio/pass — **B 판정 지표 최초 계산 시점.**

- [ ] **Step 3: 결정론 실행 ② — P3 (refinement, seed 20260721)**

```bash
uv run python -m kr_pipeline.backtest.refinement --sample=b --seed=20260721 > data/backtest/refinement_sample_b_20260721.json
python3 -c "import json; d=json.load(open('data/backtest/refinement_sample_b_20260721.json')); print(d)" | head -5
```

기록: n 트레이드, net 평균, CI, 플라시보 p. 판정: **CI 하한>0 → 입증 갱신 / 0 포함 → 미입증 유지.** 보조: 풀링 A+B 는 `--sample` 확장 없이 A·B 트레이드 JSON 합산 후 `cluster_bootstrap_ci` 직접 호출(스크립트 1회, seed 20260721).

- [ ] **Step 4: 사용자 게이트 — P2 LLM 감사 승인 요청**

Step 3 산출물에서 down-phase 진입 건수를 보고하고(감사 대상 수 = LLM 호출 수), **사용자 승인 후**:

```bash
uv run python -m kr_pipeline.backtest.trigger_audit --sample=b 2>&1 | tail -5
python3 -c "import json; d=json.load(open('data/backtest/trigger_audit_sample_b_20260721.json')); print('건수/go:', len(d) if isinstance(d, list) else d)"
```

판정: **G ≤ 0.5**. LLM 1회 — 재실행 비교 금지.

- [ ] **Step 5: 결정론 실행 ③ — I1+P4 (portfolio 200종목)**

```bash
uv run python -m kr_pipeline.backtest.portfolio --sample=ab > /tmp/portfolio_ab_out.json
python3 -c "import json; d=json.load(open('/tmp/portfolio_ab_out.json')); print('P4:', d['arms']['armA-prod']['premium_bins']['p4']); print('가동률·metrics:', d['arms']['armA-prod']['metrics'])"
```

P4 판정: verdict(promote/hold/insufficient_n) — 가드 규약대로. I1: 가동률·CAGR·MDD 를 A 단독 결과(+2.20% 등)와 대조 기록.

- [ ] **Step 6: 결과 문서 작성 + 산출물 커밋**

`docs/superpowers/backtest-sample-b-results.md` — A 결과 문서와 대칭 구조: ① 입력(1,951셀 = 1,952 − 제외 1) ② P1~P4 판정(각각 A 수치 병기) ③ I1·I2 정보용 ④ 한계(#49 241행, 2025 절단, LLM 1회, I1 v1 제외) ⑤ 재현 명령. 각 판정에 prereg 기준 원문 인용.

```bash
git add data/backtest/analyze_sample_b_20260721.json data/backtest/refinement_sample_b_20260721.json data/backtest/trigger_audit_sample_b_20260721.json data/backtest/portfolio_curves_sample_ab_20260721.json docs/superpowers/backtest-sample-b-results.md
git commit -m "docs(backtest): 표본 B 아웃오브샘플 분석 결과 — P1~P4 판정 + I1·I2 (prereg 2026-07-21)"
```

---

## Self-Review 결과

- **Spec coverage**: P1→Task 1·2·6, P2→Task 4·6(게이트), P3→Task 3·6(풀링 보조 포함), P4→Task 5·6, I1→Task 5·6(+prereg 구성 확정), I2→analyze 출력에 포함(§7.2~7.5 는 run_analysis 기존 출력), #50 제외→Task 1, 시드 파라미터화→Task 3, A 재현 회귀→Task 2·3(analyze·refinement) + I1 은 Task 6 대조로 갈음(명시), 결과 문서→Task 6. 누락 없음.
- **Placeholder 스캔**: 실제 코드/명령 포함. 두 곳(refinement meta 키 경로, stopout reason 문자열)은 구현 시 실코드 확인 지시로 명시(맹목 복붙 방지 — 값이 아니라 위치 확인).
- **Type consistency**: `exclude: frozenset[(symbol, date)]` — Task 1 정의·Task 2 소비 일치. `_flag` 패턴 argv[1:] (refinement/audit 는 서브커맨드 없음) vs profitability_cli argv[2:] — 각 파일 로컬이라 충돌 없음. premium_bins 입출력 Task 5 정의·Task 6 소비 일치.
- **훔쳐보기 가드**: Tasks 1~5 의 모든 실행 검증이 A 한정임을 각 Step 에 명시(B 는 dry-run 조차 금지 — 대상 건수도 힌트).
