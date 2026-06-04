# P1b — 조정 드리프트 자동 감지 + 단일종목 재적재 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 통합 daily 체인이 매일 분할(조정) 발생 종목을 감지해, 그 종목만 전 기간 adj 재수신 + 지표(daily/weekly) 전체 재계산하도록 한다.

**Architecture:** 신규 `kr_pipeline/pipeline/drift.py` 가 (1) 순수 비교 함수 `is_drift`, (2) 활성 종목 30일(겹침 없으면 365일) adj_close 를 DB vs KRX 로 비교해 드리프트 종목 목록을 만드는 `detect_drifted_tickers`, (3) 한 종목을 전 기간 full-refresh 하는 `reload_ticker` 를 제공한다. `chains.run_daily_chain` 은 **ohlcv 증분 전에** detect 를 실행(증분이 adj_close 를 덮어쓰기 전 비교해야 분할을 놓치지 않음)하고, 증분 후 감지 종목을 reload 한다. 단일종목 재계산을 위해 `indicators.run_daily`/`run_weekly`/`weekly.run` 에 `only_tickers` 필터를 추가한다(기존 `ohlcv`/`indicators`/`weekly` 의 다른 내부 로직은 무수정 — 호출·필터만).

**Tech Stack:** Python (psycopg3, pandas, pykrx), pytest (+pytest-mock `mocker`, auto-rollback `db` fixture).

---

## 배경 / 스펙 근거

스펙: `docs/superpowers/specs/2026-06-04-pipeline-integration-drift-reload-design.md` §2 (드리프트 감지 + cascade), §1 (체인 통합 순서), §구현 노트(순서·KRX 비용).

핵심 사실(P1a 머지 후 현재 코드, 시그니처 실측):
- `kr_pipeline/ohlcv/fetch.py:62` `fetch_adj_only(ticker, start, end) -> pd.DataFrame` — 컬럼 `[date, open, high, low, close, volume, value]` (전부 수정값, raw 호출 안 함).
- `kr_pipeline/ohlcv/store.py:32` `update_adj_prices(conn, rows) -> int` — **7-튜플** `(ticker, date, adj_close, adj_high, adj_low, adj_open, adj_volume)`, 매칭 없는 (ticker,date) 행은 무시.
- `kr_pipeline/weekly/load.py:75` `get_daily_min_date(conn) -> date | None` — daily_prices 전체 최소 날짜.
- `kr_pipeline/indicators/modes.py:368` `run_daily(conn, mode, *, window=30, limit_tickers=None)`, `:579` `run_weekly(conn, mode, *, window=4, limit_tickers=None)`. 둘 다 `tickers = load_active_tickers_with_market(conn, limit=limit_tickers)` → `list[tuple[ticker, market]]`.
- `kr_pipeline/weekly/modes.py:130` `run(conn, mode, *, window_weeks=4, limit_tickers=None)`. `tickers = load_active_tickers(conn, limit=limit_tickers)` → `list[str]`.
- 세 `run` 모두 `Mode.FULL_REFRESH` 존재(전 기간), `RunStats(rows_affected:int, failures:list[tuple[str,str]], warnings:list[str])` 반환.
- `kr_pipeline/pipeline/chains.py` `run_daily_chain(conn, *, limit_tickers=None)` 은 현재 `run_tracking(pipeline="data_daily")` 안에서 `ohlcv.run(INCREMENTAL)` → `indicators.run_daily(INCREMENTAL)` 호출.
- `kr_pipeline/db/runs.py:45` `run_tracking(conn, *, pipeline, mode, params)` — yield `state` dict(`rows_affected`/`details` 설정 가능).
- 테스트 격리: `tests/conftest.py` `db` fixture(트랜잭션→rollback). `mocker`(pytest-mock) 사용 가능.

## 설계 노트 (구현자·리뷰어 필독)

1. **순서가 핵심**: detect 는 ohlcv 증분 **전에** 실행. 증분이 최근 adj_close 를 분할-후 값으로 덮어쓰면 "DB vs KRX" 가 일치해 분할을 놓친다.
2. **비교는 상대오차**: adj_close 는 종목별 가격 스케일이 천차만별(₩50 ~ ₩500,000)이라 절대 tolerance 는 부적합. 분할은 전 기간 adj_close 를 같은 배수로 바꾸므로 겹치는 날에서 **상대차 `|db-krx|/krx`** 가 크게 벌어진다. `rel_tol=0.01`(1%) 기본.
3. **재계산 범위**: 분할은 *전 기간* adj 를 바꾸므로 드리프트 종목은 daily/weekly 지표를 **FULL_REFRESH** 로 재계산해야 한다(체인 step4 의 INCREMENTAL 은 최근 30일만이라 과거 SMA200/52주 고저가 갱신 못 함). 단일종목 FULL_REFRESH 시 지표의 횡단면(RS 순위) Phase 는 1종목 기준이 되지만, 같은 체인의 step4(전 종목 INCREMENTAL) 와 야간 full 실행이 최신 횡단면을 다시 확정하므로 허용(최신 스크리닝 영향 없음).
4. **무수정 원칙**: `ohlcv` 모듈은 손대지 않고 `fetch_adj_only`+`update_adj_prices` 공개 함수만 호출. `indicators`/`weekly` 는 `only_tickers` 필터 한 줄만 추가(다른 로직 불변) — P1 브레인스토밍에서 합의된 추가.
5. **비용**: detect 는 활성 종목별 30일 `fetch_adj_only` 1회(겹침 0이면 365일 재조회) → 평일 1회·장마감 후 감내. 종목별 fetch 실패는 로그+skip(드리프트 아님 취급), reload 실패는 로그+계속.

## 파일 구조

- **신규** `kr_pipeline/pipeline/drift.py` — `is_drift`(순수), `detect_drifted_tickers`, `reload_ticker`, 내부 헬퍼 `_db_adj_close`/`_krx_adj_close`.
- **수정** `kr_pipeline/indicators/modes.py` — `run_daily`/`run_weekly` 에 `only_tickers: list[str] | None = None` 추가 + 필터.
- **수정** `kr_pipeline/weekly/modes.py` — `run` 에 `only_tickers` 추가 + 필터.
- **수정** `kr_pipeline/pipeline/chains.py` — `run_daily_chain(conn, *, drift=True, limit_tickers=None)`: detect(전) → ohlcv 증분 → reload(감지분) → indicators 증분.
- **수정** `kr_pipeline/pipeline/__main__.py` — `--no-drift` 플래그.
- **신규 테스트** `tests/test_pipeline_drift.py`. **수정 테스트** `tests/test_pipeline_chains.py`, `tests/test_indicators_modes.py`, `tests/test_weekly_modes.py`.

---

### Task 1: `only_tickers` 필터 — indicators.run_daily / run_weekly

**Files:**
- Modify: `kr_pipeline/indicators/modes.py:368-385` (run_daily), `:579-596` (run_weekly)
- Test: `tests/test_indicators_modes.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_indicators_modes.py` 에 추가:

```python
def test_run_daily_only_tickers_filters_universe(mocker):
    """only_tickers 지정 시 그 종목만 처리한다."""
    import kr_pipeline.indicators.modes as m

    mocker.patch.object(
        m, "load_active_tickers_with_market",
        return_value=[("005930", "KOSPI"), ("000660", "KOSPI"), ("035720", "KOSDAQ")],
    )
    mocker.patch.object(m, "compute_date_range", return_value=("2024-01-01", "2024-12-31", "2024-12-01"))
    seen = []
    mocker.patch.object(m, "run_tracking", _fake_run_tracking())
    mocker.patch.object(m, "_process_ticker_daily", side_effect=lambda conn, ticker, market, *a, **k: seen.append(ticker) or 1)

    m.run_daily(conn=None, mode=m.Mode.FULL_REFRESH, only_tickers=["000660"])
    assert seen == ["000660"]
```

테스트 상단(파일에 없으면)에 헬퍼 추가:

```python
import contextlib

def _fake_run_tracking():
    @contextlib.contextmanager
    def fake(*a, **k):
        yield {"run_id": 1, "warnings": [], "rows_affected": None, "total_count": None, "details": None}
    return fake
```

> 주의: `_process_ticker_daily` 의 실제 인자 시그니처는 `modes.py:126` 에서 확인해 `side_effect` 람다를 맞춘다(첫 위치/키워드로 ticker 가 오도록). 위 람다는 `(conn, ticker, market, ...)` 가정 — 실제와 다르면 `*a, **k` 로 받고 `a`/`k` 에서 ticker 를 집어 `seen` 에 넣는다.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_indicators_modes.py::test_run_daily_only_tickers_filters_universe -v`
Expected: FAIL — `run_daily() got an unexpected keyword argument 'only_tickers'`

- [ ] **Step 3: 구현 — run_daily 에 파라미터+필터**

`kr_pipeline/indicators/modes.py` `run_daily` 시그니처에 `only_tickers` 추가:

```python
def run_daily(
    conn: Connection,
    mode: Mode,
    *,
    window: int = 30,
    limit_tickers: int | None = None,
    only_tickers: list[str] | None = None,
) -> RunStats:
```

`tickers = load_active_tickers_with_market(conn, limit=limit_tickers)` 바로 다음 줄에 필터 삽입:

```python
    tickers = load_active_tickers_with_market(conn, limit=limit_tickers)
    if only_tickers is not None:
        keep = set(only_tickers)
        tickers = [t for t in tickers if t[0] in keep]
    log.info(f"daily indicators tickers: {len(tickers)}")
```

- [ ] **Step 4: run_weekly 에도 동일 적용**

`run_weekly` 시그니처에 `only_tickers: list[str] | None = None` 추가, `tickers = load_active_tickers_with_market(conn, limit=limit_tickers)` 다음에 동일 필터(튜플 `t[0]` 기준) 삽입.

- [ ] **Step 5: run_weekly 테스트 추가**

```python
def test_run_weekly_only_tickers_filters_universe(mocker):
    import kr_pipeline.indicators.modes as m

    mocker.patch.object(
        m, "load_active_tickers_with_market",
        return_value=[("005930", "KOSPI"), ("000660", "KOSPI")],
    )
    mocker.patch.object(m, "compute_date_range", return_value=("2024-01-01", "2024-12-31", "2024-12-01"))
    seen = []
    mocker.patch.object(m, "run_tracking", _fake_run_tracking())
    mocker.patch.object(m, "_process_ticker_weekly", side_effect=lambda *a, **k: seen.append((a, k)) or 1)

    m.run_weekly(conn=None, mode=m.Mode.FULL_REFRESH, only_tickers=["005930"])
    # 005930 만 처리됐는지: 호출 1회, 인자에 005930 포함
    assert len(seen) == 1
    assert "005930" in str(seen[0])
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `uv run pytest tests/test_indicators_modes.py -k only_tickers -v`
Expected: PASS (2 passed)

- [ ] **Step 7: 커밋**

```bash
git add kr_pipeline/indicators/modes.py tests/test_indicators_modes.py
git commit -m "feat(indicators): run_daily/run_weekly only_tickers 필터 (단일종목 재계산용)"
```

---

### Task 2: `only_tickers` 필터 — weekly.run

**Files:**
- Modify: `kr_pipeline/weekly/modes.py:130-141`
- Test: `tests/test_weekly_modes.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_weekly_modes.py` 에 추가(파일 상단에 `_fake_run_tracking` 헬퍼 없으면 Task 1 Step 1 의 것을 복붙):

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

> `compute_date_range` 의 실제 반환 튜플 길이를 `weekly/modes.py` 에서 확인(위 `run` 은 `start, end = compute_date_range(...)` 2개). 다르면 return_value 길이를 맞춘다.

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
git commit -m "feat(weekly): run only_tickers 필터 (단일종목 재집계용)"
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

    겹치는 날짜(둘 다 존재)에서 상대차 |db-krx|/krx 가 rel_tol 초과면 True.
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
    # 30일: 겹침 없음 / 365일: 겹침 있고 분할
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

`kr_pipeline/pipeline/drift.py` 에 추가(상단 import 에 `from kr_pipeline.ohlcv.fetch import fetch_adj_only` 추가):

```python
from kr_pipeline.ohlcv.fetch import fetch_adj_only


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
    # fetch_adj_only 의 'close' 가 수정종가
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

`tests/test_pipeline_drift.py` 에 추가:

```python
def test_reload_ticker_full_refresh_sequence(mocker):
    """단일종목: adj 재수신→update→daily지표 FULL→weekly FULL→weekly지표 FULL 순서."""
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
    mocker.patch.object(d.indicators, "run_daily", side_effect=lambda *a, **k: calls.append(("ind_daily", k.get("only_tickers"))) or _stats())
    mocker.patch.object(d.weekly, "run", side_effect=lambda *a, **k: calls.append(("weekly", k.get("only_tickers"))) or _stats())
    mocker.patch.object(d.indicators, "run_weekly", side_effect=lambda *a, **k: calls.append(("ind_weekly", k.get("only_tickers"))) or _stats())

    d.reload_ticker(conn=None, ticker="AAA", as_of=date(2024, 1, 10))

    assert [c[0] if isinstance(c, tuple) else c for c in calls] == \
        ["fetch", "update", "ind_daily", "weekly", "ind_weekly"]
    # update_adj_prices 7-튜플 형태 (ticker, date, adj_close, adj_high, adj_low, adj_open, adj_volume)
    rows = calls[1][1]
    assert rows == [("AAA", date(2024, 1, 2), 10.0, 11.0, 8.0, 9.0, 100.0)]
    # 지표/weekly 는 only_tickers=["AAA"] 로 호출
    assert calls[2][1] == ["AAA"] and calls[3][1] == ["AAA"] and calls[4][1] == ["AAA"]
```

테스트 파일 상단에 `_stats` 헬퍼 추가:

```python
class _stats:
    rows_affected = 0
    failures = []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_drift.py::test_reload_ticker_full_refresh_sequence -v`
Expected: FAIL — `module ... has no attribute 'reload_ticker'`

- [ ] **Step 3: 구현 — reload_ticker**

`kr_pipeline/pipeline/drift.py` 에 추가(상단 import 에 추가):

```python
from kr_pipeline.ohlcv.store import update_adj_prices
from kr_pipeline.weekly.load import get_daily_min_date
from kr_pipeline.weekly import modes as weekly
from kr_pipeline.indicators import modes as indicators
```

함수:

```python
def reload_ticker(conn: Connection, ticker: str, *, as_of: date) -> dict:
    """드리프트 종목 전 기간 재적재: daily adj 재수신 → 지표 FULL → weekly FULL → weekly 지표 FULL.

    daily_prices 의 매칭 (ticker,date) 행 adj_* 만 갱신(update_adj_prices). raw 불변.
    분할은 전 기간 adj 를 바꾸므로 지표/weekly 는 FULL_REFRESH 로 재계산한다.
    """
    start = get_daily_min_date(conn) or (as_of - timedelta(days=365 * 5))
    df = fetch_adj_only(ticker, start, as_of)
    rows = [
        (ticker, row.date, float(row.close), float(row.high),
         float(row.low), float(row.open), float(row.volume))
        for row in df.itertuples(index=False)
    ]
    updated = update_adj_prices(conn, rows) if rows else 0

    r_ind_d = indicators.run_daily(conn, indicators.Mode.FULL_REFRESH, only_tickers=[ticker])
    r_wk = weekly.run(conn, weekly.Mode.FULL_REFRESH, only_tickers=[ticker])
    r_ind_w = indicators.run_weekly(conn, indicators.Mode.FULL_REFRESH, only_tickers=[ticker])

    return {
        "ticker": ticker,
        "adj_rows": updated,
        "indicators_daily": r_ind_d.rows_affected,
        "weekly": r_wk.rows_affected,
        "indicators_weekly": r_ind_w.rows_affected,
    }
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_pipeline_drift.py::test_reload_ticker_full_refresh_sequence -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/pipeline/drift.py tests/test_pipeline_drift.py
git commit -m "feat(drift): reload_ticker 단일종목 전 기간 재적재(adj+지표+weekly FULL)"
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
```

> `_Stats` 는 Task(P1a)에서 추가된 클래스(현재 `tests/test_pipeline_chains.py` 상단). `rows_affected=0`, `failures=[]` 보장 확인.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_chains.py -k drift -v`
Expected: FAIL — `module 'kr_pipeline.pipeline.chains' has no attribute 'drift'`

- [ ] **Step 3: 구현 — chains.run_daily_chain**

`kr_pipeline/pipeline/chains.py` 상단 import 에 추가:

```python
from datetime import date
from kr_pipeline.pipeline import drift
```

`run_daily_chain` 교체:

```python
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

> 파라미터 이름은 `drift_check`(모듈 `drift` 와 이름 충돌 회피). Step 1 테스트는 이미 `drift_check=False` 로 작성돼 있으니 구현 시그니처도 `drift_check` 로 맞춘다.

- [ ] **Step 4: __main__ 에 --no-drift 추가**

`kr_pipeline/pipeline/__main__.py` argparse 에 추가하고 호출부 연결:

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
Expected: PASS (기존 + 신규 drift 테스트 모두; `drift=False`→`drift_check=False` 정정 반영)

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
Expected: `{'ticker': '005930', 'adj_rows': <>0, 'indicators_daily': >0, 'weekly': >0, 'indicators_weekly': >0}` 출력, 예외 없음.

- [ ] **Step 3: 체인 드리프트 경로 수동(2종목, 감지는 보통 0건)**

Run:
```bash
uv run python -m kr_pipeline.pipeline --chain=daily --limit-tickers=2 2>&1 | grep "DONE chain"
```
Expected: `DONE chain=daily: {'drift': {'detected': 0, ...}, 'ohlcv': {...}, 'indicators_daily': {...}}` (감지 0건이 정상).

또 `--no-drift` 가 detect 를 건너뛰는지:
```bash
uv run python -m kr_pipeline.pipeline --chain=daily --limit-tickers=2 --no-drift 2>&1 | grep -E "drift detected|DONE chain"
```
Expected: `drift detected` 로그 없음, `'drift': {'detected': 0, ...}`.

- [ ] **Step 4: 전체 회귀 base 대비**

Run:
```bash
uv run pytest tests/ -q 2>&1 | grep -c "^FAILED"
```
Expected: base(현재 main)의 사전 실패 수(~26)와 동일 — 신규 회귀 0. base 와 다르면 `comm -23` 로 신규 실패 식별 후 수정.

- [ ] **Step 5: 최종 커밋(없으면 skip)**

검증만이므로 보통 커밋 없음. 검증 중 수정 발생 시 해당 변경을 커밋.

---

## Self-Review

**1. Spec coverage (스펙 §2/§1 대비):**
- `is_drift` 순수 함수(겹침 차이>tol→True, 동일→False, 겹침0→False): Task 3 ✓
- 30일→365일 확대 비교: Task 4 ✓
- detect 가 ohlcv 증분 **전에**: Task 6 (run_daily_chain 에서 detect→ohlcv 순서, 테스트로 강제) ✓
- reload_ticker daily adj 재수신+지표+weekly cascade: Task 5 ✓ (FULL_REFRESH)
- 감지 종목만 재적재(전 종목 아님): Task 6 루프 ✓
- 단일종목 지표 재계산 entrypoint(only_tickers): Task 1·2 ✓
- ohlcv/weekly/indicators 내부 로직 무수정(필터 한 줄·공개 함수 호출만): ✓
- 종목 단위 예외 격리(detect·reload): Task 4·6 ✓
- run_tracking(data_daily)에 drift 결과 details: Task 6 ✓
- baseline 회귀 0: Task 7 ✓

**2. Placeholder scan:** 모든 코드 스텝에 실제 코드/명령/기대출력 기재. "적절히 처리" 류 없음. ✓

**3. Type consistency:**
- `only_tickers: list[str] | None` — Task 1·2·5·6 일관.
- `fetch_adj_only` 반환 컬럼 `close/high/low/open/volume` → `update_adj_prices` 7-튜플 `(ticker,date,adj_close,adj_high,adj_low,adj_open,adj_volume)` 매핑 일관(Task 5).
- 파라미터명 `drift_check`(모듈 `drift` 충돌 회피) — Task 6 테스트·구현·`__main__` 일관.
- `RunStats.rows_affected`/`failures` 사용 일관.
- detect 반환 `list[str]` → chains 루프 `for t in drifted` 일관.

**알려진 한계(의도적):** 단일종목 FULL_REFRESH 시 지표 횡단면(RS 순위) Phase 는 1종목 기준 → 같은 체인 step4(전 종목 INCREMENTAL)와 야간 full 이 최신 횡단면 재확정(설계 노트 3). 스펙 비목표와 정합.
