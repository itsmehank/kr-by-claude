# P1b — 조정 드리프트 자동 감지 + 단일종목 재적재 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 통합 daily 체인이 매일 분할(조정) 발생 종목을 감지해, 그 종목만 전 기간 adj 재수신 + 시계열 지표(daily/weekly Phase A) 전체 재계산하도록 한다.

**Architecture:** 신규 `kr_pipeline/pipeline/drift.py` 가 (1) 순수 비교 함수 `is_drift`, (2) 활성 종목 30일(겹침 없으면 365일) adj_close 를 DB vs KRX 로 비교해 드리프트 종목 목록을 만드는 `detect_drifted_tickers`, (3) 한 종목을 전 기간 재적재하는 `reload_ticker` 를 제공한다. `chains.run_daily_chain` 은 **ohlcv 증분 전에** detect 를 실행(증분이 adj_close 를 덮어쓰기 전 비교해야 분할을 놓치지 않음)하고, 증분 후 감지 종목을 reload 한다. 단일종목 재계산은 indicators 의 **Phase A 전용 재계산 함수**(`recompute_ticker_daily`/`recompute_ticker_weekly`) + 주봉 가격 재집계(`weekly.run(only_tickers=...)`) 로 한다.

**Tech Stack:** Python (psycopg3, pandas, pykrx), pytest (+pytest-mock `mocker`, auto-rollback `db` fixture).

---

## 배경 / 스펙 근거

스펙: `docs/superpowers/specs/2026-06-04-pipeline-integration-drift-reload-design.md` §2 (드리프트 감지 + cascade), §1 (체인 통합 순서), §구현 노트(순서·KRX 비용).

핵심 사실(P1a 머지 후 현재 코드, 시그니처·구조 실측):

- `kr_pipeline/ohlcv/fetch.py:62` `fetch_adj_only(ticker, start, end) -> pd.DataFrame` — 컬럼 `[date, open, high, low, close, volume, value]` (전부 수정값). **`date` 는 컬럼이며 `datetime.date` 로 정규화됨**(`_fetch_one` line 49 `pd.to_datetime(...).dt.date`). → DB(`daily_prices.date`, `datetime.date`) 와 dict 키 매칭 안전.
- `kr_pipeline/ohlcv/store.py:32` `update_adj_prices(conn, rows) -> int` — **7-튜플** `(ticker, date, adj_close, adj_high, adj_low, adj_open, adj_volume)`, 매칭 없는 (ticker,date) 행은 무시.
- `kr_pipeline/weekly/load.py:75` `get_daily_min_date(conn) -> date | None` — daily_prices 전체 최소 날짜.
- **indicators 구조(중요)**: `kr_pipeline/indicators/modes.py` `run_daily`(:368) / `run_weekly`(:579) 는 단순 종목 루프가 아니라 **Phase A**(per-ticker 시계열, `_process_ticker_daily`:126 / `_process_ticker_weekly`:466) → **Phase B**(per-date 횡단면 RS Rating, `_run_phase_b_daily` / `_run_phase_b_weekly`, 날짜범위·전 종목) → **Phase C**(미너비니 pass SQL UPDATE, 날짜범위·전 종목) → (daily 만) Phase D(주봉 게이트 미러) 구조다. **Phase B/C/D 는 ticker 리스트가 아니라 날짜범위로 동작**하므로 종목 필터가 먹지 않는다. → 단일종목 재계산에 `run_daily`/`run_weekly` 를 쓰면 안 된다(1종목 위해 전 종목·전 기간 횡단면 재계산 유발 + Phase B 가 1종목 캐시로 RS 순위 오염). **대신 Phase A 만 도는 전용 함수를 추가**(Task 1).
  - `_process_ticker_daily(conn, ticker, market, load_start, load_end, upsert_start) -> int`: Phase A 전체(SMA/52w/RS line/minervini c1-c7/거래량) 계산, `upsert_start..load_end` 행 upsert, **내부에서 `conn.commit()`**(line 241), `_phase_b_cache[ticker]` 채움.
  - `_process_ticker_weekly(...)` 동일 패턴(:466, commit line 555).
  - `compute_date_range(target: Target, mode: Mode, *, window=30, conn=None) -> (load_start, load_end, upsert_start)` (:82). `Mode.FULL_REFRESH` 면 전 기간.
  - `_phase_b_cache: dict = {}` 모듈 레벨(:71, 항상 dict).
  - `Target.DAILY`/`Target.WEEKLY`, `Mode.FULL_REFRESH` (:52-55, :58~).
- `kr_pipeline/weekly/modes.py:130` `run(conn, mode, *, window_weeks=4, limit_tickers=None)` — **횡단면 Phase 없는 단순 종목 루프**(`for ticker: _process_ticker`). 주봉 *가격* 집계(daily_prices→weekly_prices). → 여기엔 `only_tickers` 필터가 안전(Task 2). `tickers = load_active_tickers(conn, limit=limit_tickers)` → `list[str]`.
- 세 모듈 모두 `RunStats(rows_affected:int, failures:list[tuple[str,str]], warnings:list[str])` 반환.
- `kr_pipeline/pipeline/chains.py` `run_daily_chain(conn, *, limit_tickers=None)` 은 현재 `run_tracking(pipeline="data_daily")` 안에서 `ohlcv.run(INCREMENTAL)` → `indicators.run_daily(INCREMENTAL)` 호출.
- `kr_pipeline/pipeline/__main__.py`: argparse `--chain` / `--limit-tickers`.
- `kr_pipeline/db/runs.py:45` `run_tracking(conn, *, pipeline, mode, params)` — yield `state` dict.
- 테스트 격리: `tests/conftest.py` `db` fixture(트랜잭션→rollback). `mocker`(pytest-mock).

## 설계 노트 (구현자·리뷰어 필독)

1. **순서가 핵심**: detect 는 ohlcv 증분 **전에** 실행. 증분이 최근 adj_close 를 분할-후 값으로 덮어쓰면 "DB vs KRX" 가 일치해 분할을 놓친다.
2. **비교는 상대오차**: adj_close 는 종목별 가격 스케일이 천차만별(₩50 ~ ₩500,000)이라 절대 tolerance 부적합. 분할은 전 기간 adj_close 를 같은 배수로 바꾸므로 겹치는 날에서 **상대차 `|db-krx|/krx`** 가 크게 벌어진다. `rel_tol=0.01`(1%) 기본.
3. **재계산 범위 = 시계열 Phase A 만(단일종목, 전 기간)**: 분할은 *전 기간* adj 를 바꾸므로 드리프트 종목의 daily/weekly **시계열 지표(Phase A)** 를 전 기간 재계산한다(SMA200/52주 고저/RS line/minervini c1-c7/거래량). **횡단면 Phase B(RS Rating 순위)/C(pass) 는 단일종목 재계산에서 제외** — 이유: 횡단면은 전 종목 분포가 필요해 1종목으로 돌리면 오염되고, *최신* 값은 체인 step4 의 daily 증분(전 종목 Phase A→B→C)과 토요일 weekly 체인이 정상 재확정한다. **알려진 한계**: 드리프트 종목의 *과거* 날짜 rs_rating/pass 는 다음 전체 재계산 전까지 (직전 adj 기준으로) 약간 stale. 최신 스크리닝·차트의 시계열 지표는 정확. 스펙 비목표("깊은 재계산 후속")와 정합.
4. **무수정 원칙(부분 완화)**: `ohlcv` 모듈 무수정 — `fetch_adj_only`+`update_adj_prices` 공개 함수만 호출. `weekly.run` 은 `only_tickers` 필터 한 줄만 추가(다른 로직 불변). `indicators` 는 기존 `run_daily`/`run_weekly` *로직 불변*, **Phase A 단일종목 재계산 공개 함수만 추가**(기존 private `_process_ticker_*` 재사용). P1 브레인스토밍의 "단일종목 재계산 entrypoint 추가" 합의 범위.
5. **비용/격리**: detect 는 활성 종목별 30일 `fetch_adj_only` 1회(겹침 0이면 365일 재조회) → 평일 1회·장마감 후 감내. 종목별 fetch 실패는 로그+skip(드리프트 아님 취급), reload 실패는 로그+`conn.rollback()`+계속.

## 파일 구조

- **신규** `kr_pipeline/pipeline/drift.py` — `is_drift`(순수), `detect_drifted_tickers`, `reload_ticker`, 헬퍼 `_active_tickers`/`_db_adj_close`/`_krx_adj_close`.
- **수정** `kr_pipeline/indicators/modes.py` — `_ticker_market`, `recompute_ticker_daily`, `recompute_ticker_weekly` **추가**(기존 함수 로직 불변).
- **수정** `kr_pipeline/weekly/modes.py` — `run` 에 `only_tickers: list[str] | None = None` 추가 + 필터.
- **수정** `kr_pipeline/pipeline/chains.py` — `run_daily_chain(conn, *, drift_check=True, limit_tickers=None)`: detect(전) → ohlcv 증분 → reload(감지분) → indicators 증분.
- **수정** `kr_pipeline/pipeline/__main__.py` — `--no-drift` 플래그.
- **신규 테스트** `tests/test_pipeline_drift.py`. **수정 테스트** `tests/test_pipeline_chains.py`, `tests/test_indicators_modes.py`, `tests/test_weekly_modes.py`.

---

### Task 1: indicators — 단일종목 Phase A 재계산 함수

**Files:**
- Modify: `kr_pipeline/indicators/modes.py` (함수 3개 추가 — 기존 로직 불변)
- Test: `tests/test_indicators_modes.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_indicators_modes.py` 에 추가(상단에 `from datetime import date` 없으면 추가):

```python
def test_recompute_ticker_daily_runs_phase_a_full_range(mocker):
    """단일종목 daily Phase A 를 FULL_REFRESH 범위로 1회 실행한다(횡단면 Phase 없음)."""
    import kr_pipeline.indicators.modes as m
    from datetime import date

    mocker.patch.object(m, "_ticker_market", return_value="KOSPI")
    mocker.patch.object(
        m, "compute_date_range",
        return_value=(date(2020, 1, 1), date(2024, 12, 31), date(2020, 1, 1)),
    )
    captured = {}
    def fake_proc(conn, ticker, market, ls, le, us):
        captured.update(ticker=ticker, market=market, ls=ls, le=le, us=us)
        return 42
    proc = mocker.patch.object(m, "_process_ticker_daily", side_effect=fake_proc)
    pb = mocker.patch.object(m, "_run_phase_b_daily")

    n = m.recompute_ticker_daily(conn=None, ticker="005930")

    assert n == 42
    assert captured == {"ticker": "005930", "market": "KOSPI",
                        "ls": date(2020, 1, 1), "le": date(2024, 12, 31), "us": date(2020, 1, 1)}
    pb.assert_not_called()  # 횡단면 Phase B 는 돌지 않음


def test_recompute_ticker_daily_unknown_market_returns_zero(mocker):
    import kr_pipeline.indicators.modes as m
    mocker.patch.object(m, "_ticker_market", return_value=None)
    proc = mocker.patch.object(m, "_process_ticker_daily")
    assert m.recompute_ticker_daily(conn=None, ticker="ZZZ") == 0
    proc.assert_not_called()


def test_recompute_ticker_weekly_runs_phase_a_full_range(mocker):
    import kr_pipeline.indicators.modes as m
    from datetime import date

    mocker.patch.object(m, "_ticker_market", return_value="KOSDAQ")
    mocker.patch.object(
        m, "compute_date_range",
        return_value=(date(2020, 1, 1), date(2024, 12, 31), date(2020, 1, 1)),
    )
    captured = {}
    def fake_proc(conn, ticker, market, ls, le, us):
        captured.update(ticker=ticker, market=market)
        return 7
    mocker.patch.object(m, "_process_ticker_weekly", side_effect=fake_proc)
    pb = mocker.patch.object(m, "_run_phase_b_weekly")

    n = m.recompute_ticker_weekly(conn=None, ticker="035720")
    assert n == 7
    assert captured == {"ticker": "035720", "market": "KOSDAQ"}
    pb.assert_not_called()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_indicators_modes.py -k recompute_ticker -v`
Expected: FAIL — `module ... has no attribute '_ticker_market'` / `recompute_ticker_daily`

- [ ] **Step 3: 구현 — 헬퍼 + 두 함수 추가**

`kr_pipeline/indicators/modes.py` 에 `run` 디스패처(:448) 위/아래 적당한 곳에 추가:

```python
def _ticker_market(conn: Connection, ticker: str) -> str | None:
    """단일 종목 시장 코드(RS 벤치마크 결정용). 없으면 None."""
    with conn.cursor() as cur:
        cur.execute("SELECT market FROM stocks WHERE ticker = %s", (ticker,))
        row = cur.fetchone()
        return row[0] if row else None


def recompute_ticker_daily(conn: Connection, ticker: str, *, window: int = 30) -> int:
    """드리프트 재적재용: 단일 종목 일봉 시계열 지표(Phase A) 를 전 기간 재계산.

    횡단면 Phase B(RS Rating)/C(pass) 는 돌리지 않는다(전 종목 분포 필요 →
    체인의 전 종목 증분/주간 실행이 최신값 확정). 설계 노트 3.
    """
    market = _ticker_market(conn, ticker)
    if market is None:
        return 0
    load_start, load_end, upsert_start = compute_date_range(
        Target.DAILY, Mode.FULL_REFRESH, window=window, conn=conn,
    )
    return _process_ticker_daily(conn, ticker, market, load_start, load_end, upsert_start)


def recompute_ticker_weekly(conn: Connection, ticker: str, *, window: int = 4) -> int:
    """드리프트 재적재용: 단일 종목 주봉 시계열 지표(Phase A) 를 전 기간 재계산."""
    market = _ticker_market(conn, ticker)
    if market is None:
        return 0
    load_start, load_end, upsert_start = compute_date_range(
        Target.WEEKLY, Mode.FULL_REFRESH, window=window, conn=conn,
    )
    return _process_ticker_weekly(conn, ticker, market, load_start, load_end, upsert_start)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_indicators_modes.py -k recompute_ticker -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/indicators/modes.py tests/test_indicators_modes.py
git commit -m "feat(indicators): recompute_ticker_daily/weekly — 단일종목 Phase A 전기간 재계산(드리프트용)"
```

---

### Task 2: weekly.run 에 `only_tickers` 필터 (주봉 가격 재집계)

**Files:**
- Modify: `kr_pipeline/weekly/modes.py:130-141`
- Test: `tests/test_weekly_modes.py`

> `kr_pipeline/weekly` 는 주봉 **가격** 집계(daily_prices→weekly_prices) 이며 횡단면 Phase 가 없는 단순 종목 루프라 `only_tickers` 가 안전하다(indicators 와 다름).

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_weekly_modes.py` 에 추가(파일 상단에 헬퍼 없으면 추가):

```python
import contextlib

def _fake_run_tracking():
    @contextlib.contextmanager
    def fake(*a, **k):
        yield {"run_id": 1, "warnings": [], "rows_affected": None, "total_count": None, "details": None}
    return fake


def test_run_only_tickers_filters_universe(mocker):
    import kr_pipeline.weekly.modes as m

    mocker.patch.object(m, "load_active_tickers", return_value=["005930", "000660", "035720"])
    mocker.patch.object(m, "compute_date_range", return_value=("2024-01-01", "2024-12-31"))
    mocker.patch.object(m, "run_tracking", _fake_run_tracking())
    seen = []
    mocker.patch.object(m, "_process_ticker", side_effect=lambda conn, ticker, start, end, today: seen.append(ticker) or 1)

    m.run(conn=None, mode=m.Mode.FULL_REFRESH, only_tickers=["000660", "035720"])
    assert seen == ["000660", "035720"]
```

> `compute_date_range` 의 실제 반환 튜플 길이를 `weekly/modes.py:138`(`start, end = compute_date_range(...)`)에서 확인 — 2개. `_process_ticker` 시그니처는 `(conn, ticker, start, end, today)`(modes.py:57).

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_weekly_modes.py::test_run_only_tickers_filters_universe -v`
Expected: FAIL — `run() got an unexpected keyword argument 'only_tickers'`

- [ ] **Step 3: 구현**

`kr_pipeline/weekly/modes.py` `run` 시그니처에 추가:

```python
def run(
    conn: Connection,
    mode: Mode,
    *,
    window_weeks: int = 4,
    limit_tickers: int | None = None,
    only_tickers: list[str] | None = None,
) -> RunStats:
```

`tickers = load_active_tickers(conn, limit=limit_tickers)` 다음 줄에:

```python
    tickers = load_active_tickers(conn, limit=limit_tickers)
    if only_tickers is not None:
        keep = set(only_tickers)
        tickers = [t for t in tickers if t in keep]
    log.info(f"weekly tickers to process: {len(tickers)}")
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_weekly_modes.py::test_run_only_tickers_filters_universe -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/weekly/modes.py tests/test_weekly_modes.py
git commit -m "feat(weekly): run only_tickers 필터 (단일종목 주봉 가격 재집계용)"
```

---

### Task 3: `is_drift` 순수 함수

**Files:**
- Create: `kr_pipeline/pipeline/drift.py`
- Test: `tests/test_pipeline_drift.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_pipeline_drift.py` (신규):

```python
"""tests/test_pipeline_drift.py — 드리프트 감지/재적재."""
from datetime import date


def test_is_drift_identical_returns_false():
    from kr_pipeline.pipeline.drift import is_drift
    db = {date(2024, 1, 2): 50000.0, date(2024, 1, 3): 50500.0}
    krx = {date(2024, 1, 2): 50000.0, date(2024, 1, 3): 50500.0}
    assert is_drift(db, krx, rel_tol=0.01) is False


def test_is_drift_split_ratio_returns_true():
    """분할 후 adj_close 가 배수로 바뀌면 겹치는 날에서 상대차 큼 → True."""
    from kr_pipeline.pipeline.drift import is_drift
    db = {date(2024, 1, 2): 50000.0, date(2024, 1, 3): 50500.0}   # 분할 전 저장값
    krx = {date(2024, 1, 2): 10000.0, date(2024, 1, 3): 10100.0}  # 분할 후 재조회(÷5)
    assert is_drift(db, krx, rel_tol=0.01) is True


def test_is_drift_tiny_float_noise_returns_false():
    from kr_pipeline.pipeline.drift import is_drift
    db = {date(2024, 1, 2): 50000.0}
    krx = {date(2024, 1, 2): 50000.4}  # 0.0008% 차이
    assert is_drift(db, krx, rel_tol=0.01) is False


def test_is_drift_no_overlap_returns_false():
    from kr_pipeline.pipeline.drift import is_drift
    db = {date(2024, 1, 2): 50000.0}
    krx = {date(2024, 2, 2): 50000.0}
    assert is_drift(db, krx, rel_tol=0.01) is False
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_drift.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kr_pipeline.pipeline.drift'`

- [ ] **Step 3: 구현 — drift.py 첫 함수**

`kr_pipeline/pipeline/drift.py` (신규):

```python
"""조정 드리프트(분할 등) 감지 + 단일종목 전 기간 재적재.

detect 는 ohlcv 증분 전에 실행해야 한다(증분이 adj_close 를 덮어쓰기 전 DB vs KRX 비교).
스펙: docs/superpowers/specs/2026-06-04-pipeline-integration-drift-reload-design.md §2.
"""
from __future__ import annotations
import logging
from datetime import date, timedelta

from psycopg import Connection

log = logging.getLogger("kr_pipeline.pipeline.drift")


def is_drift(
    db_adj: dict[date, float],
    krx_adj: dict[date, float],
    rel_tol: float,
) -> bool:
    """DB 저장 adj_close vs KRX 재조회 adj_close 비교.

    겹치는 날짜(둘 다 존재)에서 상대차 |db-krx|/|krx| 가 rel_tol 초과면 True.
    겹침이 없으면 False(호출부가 기간 확대를 책임진다).
    """
    overlap = db_adj.keys() & krx_adj.keys()
    for d in overlap:
        k = krx_adj[d]
        if k == 0:
            continue
        if abs(db_adj[d] - k) / abs(k) > rel_tol:
            return True
    return False
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_pipeline_drift.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/pipeline/drift.py tests/test_pipeline_drift.py
git commit -m "feat(drift): is_drift 순수 비교 함수 (상대오차 기반)"
```

---

### Task 4: `detect_drifted_tickers`

**Files:**
- Modify: `kr_pipeline/pipeline/drift.py`
- Test: `tests/test_pipeline_drift.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_pipeline_drift.py` 에 추가:

```python
def test_detect_drifted_tickers_flags_split(mocker):
    """한 종목은 분할(불일치), 한 종목은 동일 → 분할 종목만 반환."""
    import kr_pipeline.pipeline.drift as d

    mocker.patch.object(d, "_active_tickers", return_value=["AAA", "BBB"])
    mocker.patch.object(d, "_db_adj_close", side_effect=lambda conn, t, s, e: {
        "AAA": {date(2024, 1, 2): 50000.0},
        "BBB": {date(2024, 1, 2): 30000.0},
    }[t])
    mocker.patch.object(d, "_krx_adj_close", side_effect=lambda t, s, e: {
        "AAA": {date(2024, 1, 2): 10000.0},  # ÷5 분할
        "BBB": {date(2024, 1, 2): 30000.0},  # 동일
    }[t])

    out = d.detect_drifted_tickers(conn=None, as_of=date(2024, 1, 10), rel_tol=0.01)
    assert out == ["AAA"]


def test_detect_drifted_tickers_widens_on_no_overlap(mocker):
    """30일 겹침 0 → 365일 재조회 후 판정."""
    import kr_pipeline.pipeline.drift as d

    mocker.patch.object(d, "_active_tickers", return_value=["AAA"])
    db_calls = {30: {}, 365: {date(2023, 6, 1): 50000.0}}
    krx_calls = {30: {date(2024, 1, 2): 9000.0}, 365: {date(2023, 6, 1): 10000.0}}

    def fake_db(conn, t, s, e):
        return db_calls[(date(2024, 1, 10) - s).days]
    def fake_krx(t, s, e):
        return krx_calls[(date(2024, 1, 10) - s).days]

    mocker.patch.object(d, "_db_adj_close", side_effect=fake_db)
    mocker.patch.object(d, "_krx_adj_close", side_effect=fake_krx)

    out = d.detect_drifted_tickers(conn=None, as_of=date(2024, 1, 10),
                                   rel_tol=0.01, recent_days=30, wide_days=365)
    assert out == ["AAA"]


def test_detect_drifted_tickers_skips_fetch_error(mocker):
    """KRX fetch 실패 종목은 로그+skip(드리프트 아님 취급)."""
    import kr_pipeline.pipeline.drift as d

    mocker.patch.object(d, "_active_tickers", return_value=["AAA", "BBB"])
    mocker.patch.object(d, "_db_adj_close", return_value={date(2024, 1, 2): 50000.0})

    def fake_krx(t, s, e):
        if t == "AAA":
            raise RuntimeError("KRX timeout")
        return {date(2024, 1, 2): 50000.0}

    mocker.patch.object(d, "_krx_adj_close", side_effect=fake_krx)
    out = d.detect_drifted_tickers(conn=None, as_of=date(2024, 1, 10), rel_tol=0.01)
    assert out == []  # AAA skip, BBB 동일
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_drift.py -k detect -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_active_tickers'`

- [ ] **Step 3: 구현 — 헬퍼 + detect**

`kr_pipeline/pipeline/drift.py` 상단 import 에 추가:

```python
from kr_pipeline.ohlcv.fetch import fetch_adj_only
```

함수 추가:

```python
def _active_tickers(conn: Connection, limit: int | None = None) -> list[str]:
    sql = "SELECT ticker FROM stocks WHERE delisted_at IS NULL ORDER BY ticker"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn.cursor() as cur:
        cur.execute(sql)
        return [r[0] for r in cur.fetchall()]


def _db_adj_close(conn: Connection, ticker: str, start: date, end: date) -> dict[date, float]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, adj_close FROM daily_prices "
            "WHERE ticker = %s AND date BETWEEN %s AND %s AND adj_close IS NOT NULL",
            (ticker, start, end),
        )
        return {r[0]: float(r[1]) for r in cur.fetchall()}


def _krx_adj_close(ticker: str, start: date, end: date) -> dict[date, float]:
    df = fetch_adj_only(ticker, start, end)
    if df.empty:
        return {}
    # fetch_adj_only 의 'close' 가 수정종가, 'date' 는 datetime.date 컬럼
    return {row.date: float(row.close) for row in df.itertuples(index=False)}


def detect_drifted_tickers(
    conn: Connection,
    *,
    as_of: date,
    rel_tol: float = 0.01,
    recent_days: int = 30,
    wide_days: int = 365,
    limit_tickers: int | None = None,
) -> list[str]:
    """활성 종목별 DB(현재, 덮어쓰기 전) vs KRX 재조회 adj_close 비교 → 드리프트 종목.

    반드시 ohlcv 증분 적재 전에 호출(증분이 adj_close 를 덮으면 비교가 일치해버림).
    종목별 fetch 예외는 로그+skip.
    """
    drifted: list[str] = []
    for t in _active_tickers(conn, limit=limit_tickers):
        try:
            recent_start = as_of - timedelta(days=recent_days)
            db = _db_adj_close(conn, t, recent_start, as_of)
            krx = _krx_adj_close(t, recent_start, as_of)
            if not (db.keys() & krx.keys()):
                wide_start = as_of - timedelta(days=wide_days)
                db = _db_adj_close(conn, t, wide_start, as_of)
                krx = _krx_adj_close(t, wide_start, as_of)
            if is_drift(db, krx, rel_tol):
                drifted.append(t)
        except Exception as e:  # noqa: BLE001 — 종목 단위 격리
            log.warning("drift detect skip %s: %s", t, e)
    log.info("drift detected: %d tickers %s", len(drifted), drifted[:20])
    return drifted
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_pipeline_drift.py -k detect -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/pipeline/drift.py tests/test_pipeline_drift.py
git commit -m "feat(drift): detect_drifted_tickers (30일→365일 확대, 종목격리)"
```

---

### Task 5: `reload_ticker`

**Files:**
- Modify: `kr_pipeline/pipeline/drift.py`
- Test: `tests/test_pipeline_drift.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_pipeline_drift.py` 상단에 헬퍼 추가:

```python
class _stats:
    rows_affected = 5
    failures = []
```

테스트 추가:

```python
def test_reload_ticker_sequence(mocker):
    """단일종목: adj 재수신→update→daily Phase A 재계산→weekly 가격 재집계→weekly Phase A 재계산 순서."""
    import kr_pipeline.pipeline.drift as d
    import pandas as pd

    calls = []
    mocker.patch.object(d, "get_daily_min_date", return_value=date(2020, 1, 1))
    fake_df = pd.DataFrame(
        [{"date": date(2024, 1, 2), "open": 9.0, "high": 11.0, "low": 8.0,
          "close": 10.0, "volume": 100.0, "value": 1000.0}]
    )
    mocker.patch.object(d, "fetch_adj_only", side_effect=lambda t, s, e: calls.append("fetch") or fake_df)
    mocker.patch.object(d, "update_adj_prices", side_effect=lambda conn, rows: calls.append(("update", rows)) or len(rows))
    mocker.patch.object(d.indicators, "recompute_ticker_daily", side_effect=lambda conn, t: calls.append(("ind_daily", t)) or 5)
    mocker.patch.object(d.weekly, "run", side_effect=lambda *a, **k: calls.append(("weekly", k.get("only_tickers"))) or _stats())
    mocker.patch.object(d.indicators, "recompute_ticker_weekly", side_effect=lambda conn, t: calls.append(("ind_weekly", t)) or 3)

    out = d.reload_ticker(conn=None, ticker="AAA", as_of=date(2024, 1, 10))

    assert [c[0] if isinstance(c, tuple) else c for c in calls] == \
        ["fetch", "update", "ind_daily", "weekly", "ind_weekly"]
    # update_adj_prices 7-튜플 (ticker, date, adj_close, adj_high, adj_low, adj_open, adj_volume)
    assert calls[1][1] == [("AAA", date(2024, 1, 2), 10.0, 11.0, 8.0, 9.0, 100.0)]
    # 단일종목 재계산 호출 인자
    assert calls[2][1] == "AAA"            # recompute_ticker_daily(conn, "AAA")
    assert calls[3][1] == ["AAA"]          # weekly.run(only_tickers=["AAA"])
    assert calls[4][1] == "AAA"            # recompute_ticker_weekly(conn, "AAA")
    assert out["ticker"] == "AAA" and out["adj_rows"] == 1
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_drift.py::test_reload_ticker_sequence -v`
Expected: FAIL — `module ... has no attribute 'reload_ticker'`

- [ ] **Step 3: 구현 — reload_ticker**

`kr_pipeline/pipeline/drift.py` 상단 import 에 추가:

```python
from kr_pipeline.ohlcv.store import update_adj_prices
from kr_pipeline.weekly.load import get_daily_min_date
from kr_pipeline.weekly import modes as weekly
from kr_pipeline.indicators import modes as indicators
```

함수 추가:

```python
def reload_ticker(conn: Connection, ticker: str, *, as_of: date) -> dict:
    """드리프트 종목 전 기간 재적재.

    1) daily adj 재수신(fetch_adj_only) → update_adj_prices(매칭 행 adj_* 만 갱신, raw 불변)
    2) daily 시계열 지표 Phase A 전 기간 재계산
    3) 주봉 가격 재집계(weekly.run FULL_REFRESH, 그 종목만)
    4) 주봉 시계열 지표 Phase A 전 기간 재계산
    횡단면 RS 순위는 체인의 전 종목 증분/주간 실행이 최신값 확정(설계 노트 3).
    """
    start = get_daily_min_date(conn) or (as_of - timedelta(days=365 * 5))
    df = fetch_adj_only(ticker, start, as_of)
    rows = [
        (ticker, row.date, float(row.close), float(row.high),
         float(row.low), float(row.open), float(row.volume))
        for row in df.itertuples(index=False)
    ]
    updated = update_adj_prices(conn, rows) if rows else 0

    r_ind_d = indicators.recompute_ticker_daily(conn, ticker)
    r_wk = weekly.run(conn, weekly.Mode.FULL_REFRESH, only_tickers=[ticker])
    r_ind_w = indicators.recompute_ticker_weekly(conn, ticker)

    return {
        "ticker": ticker,
        "adj_rows": updated,
        "indicators_daily": r_ind_d,
        "weekly": r_wk.rows_affected,
        "indicators_weekly": r_ind_w,
    }
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_pipeline_drift.py::test_reload_ticker_sequence -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/pipeline/drift.py tests/test_pipeline_drift.py
git commit -m "feat(drift): reload_ticker — adj 재수신+단일종목 Phase A+주봉 재집계"
```

---

### Task 6: 체인 통합 — run_daily_chain 에 드리프트 단계

**Files:**
- Modify: `kr_pipeline/pipeline/chains.py`
- Modify: `kr_pipeline/pipeline/__main__.py`
- Test: `tests/test_pipeline_chains.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_pipeline_chains.py` 에 추가:

```python
def test_run_daily_chain_detects_before_ohlcv_then_reloads(mocker):
    """순서: detect(증분 전) → ohlcv 증분 → reload(감지분) → indicators 증분."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "detect_drifted_tickers",
                        side_effect=lambda *a, **k: calls.append("detect") or ["AAA"])
    mocker.patch.object(ch.drift, "reload_ticker",
                        side_effect=lambda *a, **k: calls.append("reload") or {"ticker": "AAA"})
    mocker.patch.object(ch.ohlcv, "run", side_effect=lambda *a, **k: calls.append("ohlcv") or _Stats())
    mocker.patch.object(ch.indicators, "run_daily", side_effect=lambda *a, **k: calls.append("ind_daily") or _Stats())

    ch.run_daily_chain(conn=None)
    assert calls == ["detect", "ohlcv", "reload", "ind_daily"]
    assert state["details"]["drift"]["detected"] == 1
    assert state["details"]["drift"]["reloaded"] == 1


def test_run_daily_chain_drift_false_skips_detect(mocker):
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "detect_drifted_tickers",
                        side_effect=lambda *a, **k: calls.append("detect") or [])
    mocker.patch.object(ch.ohlcv, "run", side_effect=lambda *a, **k: calls.append("ohlcv") or _Stats())
    mocker.patch.object(ch.indicators, "run_daily", side_effect=lambda *a, **k: calls.append("ind_daily") or _Stats())

    ch.run_daily_chain(conn=None, drift_check=False)
    assert calls == ["ohlcv", "ind_daily"]  # detect 미호출


def test_run_daily_chain_reload_failure_isolated(mocker):
    """한 종목 reload 실패는 로그+rollback+계속, indicators 증분은 그대로 실행."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "detect_drifted_tickers", side_effect=lambda *a, **k: ["AAA", "BBB"])
    def boom(conn, t, **k):
        if t == "AAA":
            raise RuntimeError("reload fail")
        return {"ticker": t}
    mocker.patch.object(ch.drift, "reload_ticker", side_effect=boom)
    mocker.patch.object(ch.ohlcv, "run", side_effect=lambda *a, **k: _Stats())
    mocker.patch.object(ch.indicators, "run_daily", side_effect=lambda *a, **k: calls.append("ind_daily") or _Stats())
    rb = mocker.patch.object(ch, "_rollback", side_effect=lambda conn: None)

    ch.run_daily_chain(conn=None)
    assert calls == ["ind_daily"]  # 실패해도 indicators 실행
    assert state["details"]["drift"] == {"detected": 2, "reloaded": 1, "failures": 1, "tickers": ["AAA", "BBB"]}
    rb.assert_called_once()  # 실패 1건에 rollback 1회
```

> `_Stats` 는 P1a 에서 추가된 클래스(`tests/test_pipeline_chains.py` 상단, `rows_affected`/`failures` 보유). `_fake_run_tracking` 도 동 파일 상단 헬퍼.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_chains.py -k "drift or reload" -v`
Expected: FAIL — `module 'kr_pipeline.pipeline.chains' has no attribute 'drift'`

- [ ] **Step 3: 구현 — chains.run_daily_chain**

`kr_pipeline/pipeline/chains.py` 상단 import 에 추가:

```python
from datetime import date
from kr_pipeline.pipeline import drift
```

`_rollback` 헬퍼(테스트에서 mock 가능하도록 모듈 함수로) + `run_daily_chain` 교체:

```python
def _rollback(conn) -> None:
    conn.rollback()


def run_daily_chain(conn: Connection, *, drift_check: bool = True, limit_tickers: int | None = None) -> dict:
    """평일 통합: (드리프트 감지) → ohlcv 증분 → (감지 종목 재적재) → indicators 일봉 증분.

    드리프트 감지는 ohlcv 증분 '전에' 실행(증분이 adj_close 덮어쓰기 전 비교). 스펙 §1/§2.
    통합 자체를 pipeline="data_daily" 로 추적. 하위 모듈도 각자 자기 이름으로 행을 남긴다.
    """
    with run_tracking(conn, pipeline="data_daily", mode="incremental",
                      params={"limit_tickers": limit_tickers, "drift": drift_check}) as state:
        as_of = date.today()
        drifted: list[str] = []
        if drift_check:
            drifted = drift.detect_drifted_tickers(conn, as_of=as_of, limit_tickers=limit_tickers)

        r_price = ohlcv.run(conn, ohlcv.Mode.INCREMENTAL, limit_tickers=limit_tickers)

        reloaded, reload_failures = 0, 0
        for t in drifted:
            try:
                drift.reload_ticker(conn, t, as_of=as_of)
                reloaded += 1
            except Exception as e:  # noqa: BLE001 — 종목 단위 격리
                reload_failures += 1
                _rollback(conn)
                log.warning("drift reload failed %s: %s", t, e)

        r_ind = indicators.run_daily(conn, indicators.Mode.INCREMENTAL, limit_tickers=limit_tickers)

        result = {
            "drift": {"detected": len(drifted), "reloaded": reloaded,
                      "failures": reload_failures, "tickers": drifted},
            "ohlcv": {"rows": r_price.rows_affected, "failures": len(r_price.failures)},
            "indicators_daily": {"rows": r_ind.rows_affected, "failures": len(r_ind.failures)},
        }
        state["rows_affected"] = (r_price.rows_affected or 0) + (r_ind.rows_affected or 0)
        state["details"] = result
        return result
```

> `run_weekly_chain` 은 변경 없음(드리프트는 daily 체인 전용 — 분할 감지·adj 재수신은 일봉 기준).

- [ ] **Step 4: __main__ 에 --no-drift 추가**

`kr_pipeline/pipeline/__main__.py` argparse 에 추가하고 daily 호출부 연결:

```python
    p.add_argument("--no-drift", action="store_true", help="daily 체인 드리프트 감지 건너뛰기")
    ...
    if args.chain == "daily":
        result = chains.run_daily_chain(conn, drift_check=not args.no_drift,
                                        limit_tickers=args.limit_tickers)
    else:
        result = chains.run_weekly_chain(conn, limit_tickers=args.limit_tickers)
```

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_pipeline_chains.py -v`
Expected: PASS (기존 + 신규 drift/reload 테스트 모두)

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/pipeline/chains.py kr_pipeline/pipeline/__main__.py tests/test_pipeline_chains.py
git commit -m "feat(pipeline): run_daily_chain 드리프트 감지(증분 전)+감지종목 재적재 / --no-drift"
```

---

### Task 7: 회귀 + 수동 확인

**Files:** 없음(검증만)

- [ ] **Step 1: 변경영역 테스트**

Run:
```bash
uv run pytest tests/test_pipeline_drift.py tests/test_pipeline_chains.py \
  tests/test_indicators_modes.py tests/test_weekly_modes.py -v
```
Expected: 전부 PASS.

- [ ] **Step 2: 단일종목 reload 수동 스모크(실 DB, 1종목)**

Run:
```bash
uv run python -c "
from kr_pipeline.common.config import Config
from kr_pipeline.db.connection import connect
from kr_pipeline.pipeline.drift import reload_ticker
from datetime import date
with connect(Config.load().database_url) as conn:
    print(reload_ticker(conn, '005930', as_of=date.today()))
    conn.commit()
"
```
Expected: `{'ticker': '005930', 'adj_rows': >0, 'indicators_daily': >0, 'weekly': >0, 'indicators_weekly': >0}` 출력, 예외 없음.

- [ ] **Step 3: 체인 드리프트 경로 수동(2종목, 감지는 보통 0건)**

Run:
```bash
uv run python -m kr_pipeline.pipeline --chain=daily --limit-tickers=2 2>&1 | grep -E "drift detected|DONE chain"
```
Expected: `drift detected: 0 tickers` 로그 + `DONE chain=daily: {'drift': {'detected': 0, 'reloaded': 0, ...}, 'ohlcv': {...}, 'indicators_daily': {...}}`.

`--no-drift` 가 detect 를 건너뛰는지:
```bash
uv run python -m kr_pipeline.pipeline --chain=daily --limit-tickers=2 --no-drift 2>&1 | grep -E "drift detected|DONE chain"
```
Expected: `drift detected` 로그 **없음**, `'drift': {'detected': 0, ...}`.

- [ ] **Step 4: 전체 회귀 base 대비**

Run:
```bash
uv run pytest tests/ -q 2>&1 | grep "^FAILED" | sed 's/ -.*//' | sort > /tmp/p1b_head.txt
wc -l < /tmp/p1b_head.txt
```
Expected: 현재 main 사전 실패 수(~26)와 동일 — 신규 회귀 0. 다르면 base 와 `comm -23` 로 신규 실패 식별 후 수정.

- [ ] **Step 5: 최종 커밋(없으면 skip)**

검증만이므로 보통 커밋 없음. 검증 중 수정 발생 시 해당 변경을 커밋.

---

## Self-Review

**1. Spec coverage (스펙 §2/§1 대비):**
- `is_drift` 순수 함수(겹침 차이>tol→True, 동일→False, 겹침0→False): Task 3 ✓
- 30일→365일 확대 비교: Task 4 ✓
- detect 가 ohlcv 증분 **전에**: Task 6 (run_daily_chain detect→ohlcv 순서, 테스트로 강제) ✓
- reload_ticker daily adj 재수신+지표+weekly cascade: Task 5 ✓
- 감지 종목만 재적재(전 종목 아님): Task 5 단일종목 Phase A + Task 6 루프 ✓ (run_daily 전체 호출로 인한 전 종목 횡단면 재계산 회피 — Task 1 전용 함수)
- 단일종목 지표 재계산 entrypoint: Task 1(indicators Phase A) + Task 2(weekly 가격) ✓
- ohlcv 무수정(공개 함수 호출만), weekly/indicators 는 추가만(기존 로직 불변): ✓
- 종목 단위 예외 격리(detect skip / reload rollback+계속): Task 4·6 ✓
- run_tracking(data_daily)에 drift 결과 details: Task 6 ✓
- baseline 회귀 0: Task 7 ✓

**2. Placeholder scan:** 모든 코드 스텝에 실제 코드/명령/기대출력. "적절히 처리" 류 없음. ✓

**3. Type consistency:**
- `recompute_ticker_daily(conn, ticker) -> int` / `recompute_ticker_weekly(conn, ticker) -> int` — Task 1 정의, Task 5 호출(`d.indicators.recompute_ticker_daily(conn, ticker)`) 일관.
- `weekly.run(..., only_tickers: list[str] | None)` — Task 2 정의, Task 5 `only_tickers=[ticker]` 호출 일관.
- `fetch_adj_only` 반환 컬럼 `close/high/low/open/volume`(+date) → `update_adj_prices` 7-튜플 `(ticker,date,adj_close,adj_high,adj_low,adj_open,adj_volume)` 매핑 일관(Task 5). `date` 는 `datetime.date`(키 매칭 안전).
- `detect_drifted_tickers(...) -> list[str]` → Task 6 `for t in drifted` 일관.
- 파라미터명 `drift_check`(모듈 `drift` 충돌 회피) — Task 6 테스트·구현·`__main__` 일관.
- `RunStats.rows_affected`/`failures` 사용 일관. reload 반환 dict 키(`indicators_daily`=int from recompute, `weekly`=RunStats.rows_affected) Task 5 테스트와 일치.

**핵심 수정 사항(초안 대비):** indicators 의 `run_daily`/`run_weekly` 는 Phase A 뒤에 **날짜범위 기준 전 종목 횡단면 Phase B/C(/D)** 를 돌리므로 `only_tickers` 로 단일종목 재계산을 흉내낼 수 없다(전 종목·전 기간 재계산 유발 + Phase B 가 1종목 캐시로 RS 순위 오염). → indicators 에는 `only_tickers` 를 넣지 않고 **Phase A 만 도는 `recompute_ticker_daily`/`recompute_ticker_weekly`** 를 추가(Task 1). `only_tickers` 는 횡단면 Phase 가 없는 `weekly.run`(주봉 가격 집계)에만 둔다(Task 2).

**알려진 한계(의도적):** 드리프트 종목의 *과거* 날짜 횡단면 지표(rs_rating/minervini pass)는 단일종목 재계산이 갱신하지 않는다 — 최신값은 체인 step4(daily 전 종목 증분 Phase B/C)·토요일 weekly 체인이 재확정. 시계열 지표(차트·스크리닝 핵심)는 전 기간 정확. 스펙 비목표("깊은 재계산 후속")와 정합.
