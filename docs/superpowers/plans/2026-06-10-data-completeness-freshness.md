# D-4 데이터 완전성·신선도 보장 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 불완전 적재 시 indicators 계산을 fail-fast 로 막고(①), LLM 이 stale 데이터로 조용히 돌지 않게 거래캘린더 기반 신선도 가드를 추가한다(②).

**Architecture:** ① `indicators.run_daily` 시작부에서 최신 daily_prices 커버리지<90% 면 `IncompleteIngestionError` raise(체인·단독 모두 보호). ② `trading_calendar` 모듈이 라이브 KRX 지수로 ELTD(기대 최신 거래일)를 계산, `__main__` 가드가 `as_of < ELTD` 면 `StaleDataError`. pykrx 실패는 fail-closed.

**Tech Stack:** Python, psycopg, pandas, pykrx(`get_index_ohlcv` via 기존 `fetch_index`), pytest(monkeypatch). 임계 0.90, 마감버퍼 17:00 KST. spec: `docs/superpowers/specs/2026-06-10-data-completeness-freshness-design.md`.

---

## File Structure

- Create: `kr_pipeline/indicators/completeness.py` — `IncompleteIngestionError` + `check_daily_ohlcv_complete(conn, *, active_count, threshold=0.90)`.
- Modify: `kr_pipeline/indicators/modes.py` `run_daily` — `run_tracking` 블록 첫 줄에 게이트 호출(INCREMENTAL & limit 없을 때).
- Create: `kr_pipeline/common/trading_calendar.py` — `TradingCalendarUnavailable`, `StaleDataError`, `expected_latest_trading_day(now)`, `assert_data_fresh(as_of, now)`.
- Modify: `kr_pipeline/llm_runner/__main__.py` — imports + `run_tracking` 블록 첫 줄에 신선도 가드.
- Create: `tests/test_indicators_completeness_gate.py`, `tests/test_trading_calendar.py`, `tests/test_freshness_guard.py`.

참고 사실:
- `indicators/modes.py run_daily`: `compute_date_range` → `tickers = load_active_tickers_with_market(conn, limit=limit_tickers)` → `with run_tracking(... pipeline="indicators" ...) as state:` → `# Phase A`. **게이트는 `with run_tracking` 직후, `# Phase A` 앞.** `Mode` enum: `BACKFILL/INCREMENTAL/FULL_REFRESH` (modes.py:52-55).
- 분모: `limit_tickers is None` 일 때 `len(tickers)` == 활성 종목 수(stocks delisted_at IS NULL, load_active_tickers_with_market 정의와 동일).
- `fetch_index(index_code, start, end)` (kr_pipeline/ohlcv/fetch.py): pandas DataFrame, `df["date"]`(date 객체) 컬럼, 데이터 없으면 `df.empty`.
- `__main__.py`: `explicit = _date.fromisoformat(args.date) if args.date else None` → `as_of = resolve_as_of(conn, explicit)` → `with run_tracking(conn, pipeline=pipeline_db_name, mode=args.mode, params=params) as state:` → `if args.mode == "weekend":` dispatch.
- `db` fixture(tests/conftest.py): teardown `rollback` → 테스트에서 `commit` 금지(같은 connection 미커밋 가시). 격리용 sentinel 미래 날짜(2099) 사용.

---

### Task 1: 완전성 게이트 (①) — completeness 헬퍼 + run_daily 배선

**Files:**
- Create: `kr_pipeline/indicators/completeness.py`
- Test: `tests/test_indicators_completeness_gate.py`
- Modify: `kr_pipeline/indicators/modes.py` (run_daily)

- [ ] **Step 1: Write the failing tests**

`tests/test_indicators_completeness_gate.py`:
```python
from datetime import date
import pytest


def _seed_prices(cur, n_rows, *, d=date(2099, 7, 1)):
    """sentinel 미래 날짜 d 에 n_rows 개 종목의 daily_prices 행 시드(MAX(date)=d 보장).

    daily_prices.ticker 는 stocks(ticker) 로 FK → 각 ticker 를 stocks 에 먼저 INSERT 필수.
    """
    for i in range(n_rows):
        t = f"CMP{i:04d}"
        cur.execute(
            "INSERT INTO stocks (ticker,name,market) VALUES (%s,'x','KOSPI') ON CONFLICT DO NOTHING",
            (t,),
        )
        cur.execute(
            "INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value) "
            "VALUES (%s,%s,100,100,100,100,100,1000,100000) ON CONFLICT DO NOTHING",
            (t, d),
        )


def test_complete_passes(db):
    from kr_pipeline.indicators.completeness import check_daily_ohlcv_complete
    with db.cursor() as cur:
        _seed_prices(cur, 10)
    # active=10, 최신일 10행 → 100% → raise 없음
    check_daily_ohlcv_complete(db, active_count=10)


def test_partial_raises(db):
    from kr_pipeline.indicators.completeness import (
        check_daily_ohlcv_complete, IncompleteIngestionError)
    with db.cursor() as cur:
        _seed_prices(cur, 1)
    # active=10, 최신일 1행 → 10% → raise
    with pytest.raises(IncompleteIngestionError):
        check_daily_ohlcv_complete(db, active_count=10)


def test_threshold_boundary_passes(db):
    from kr_pipeline.indicators.completeness import check_daily_ohlcv_complete
    with db.cursor() as cur:
        _seed_prices(cur, 9)
    # active=10, 최신일 9행 → 90% → 통과(>=0.90)
    check_daily_ohlcv_complete(db, active_count=10)


def test_just_below_threshold_raises(db):
    from kr_pipeline.indicators.completeness import (
        check_daily_ohlcv_complete, IncompleteIngestionError)
    with db.cursor() as cur:
        _seed_prices(cur, 89)
    # active=100, 89행 → 89% < 90% → raise
    with pytest.raises(IncompleteIngestionError):
        check_daily_ohlcv_complete(db, active_count=100)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_indicators_completeness_gate.py -v`
Expected: FAIL (`ModuleNotFoundError: kr_pipeline.indicators.completeness`).

- [ ] **Step 3: Implement the helper**

Create `kr_pipeline/indicators/completeness.py`:
```python
"""적재 완전성 게이트 — 최신 daily_prices 커버리지가 미달이면 지표 계산을 막는다."""
from __future__ import annotations

from psycopg import Connection

DEFAULT_COVERAGE_THRESHOLD = 0.90


class IncompleteIngestionError(RuntimeError):
    """최신 daily_prices 적재 커버리지가 임계 미만 — 지표 계산 중단(fail-fast)."""


def check_daily_ohlcv_complete(
    conn: Connection,
    *,
    active_count: int,
    threshold: float = DEFAULT_COVERAGE_THRESHOLD,
) -> None:
    """최신 daily_prices 날짜의 종목 커버리지가 threshold 미만이면 IncompleteIngestionError.

    active_count: 기대 종목 수(활성 유니버스). coverage = (최신일 행수) / active_count.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(date) FROM daily_prices")
        row = cur.fetchone()
        latest = row[0] if row else None
        if latest is None:
            raise IncompleteIngestionError("daily_prices 비어 있음 — 적재 선행 필요")
        cur.execute("SELECT count(*) FROM daily_prices WHERE date = %s", (latest,))
        rows = cur.fetchone()[0]
    coverage = (rows / active_count) if active_count else 0.0
    if coverage < threshold:
        raise IncompleteIngestionError(
            f"최신 적재 불완전: date={latest} rows={rows}/{active_count} "
            f"coverage={coverage:.1%} < threshold {threshold:.0%}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_indicators_completeness_gate.py -v`
Expected: 4 passed.

- [ ] **Step 5: Wire the gate into `run_daily`**

`kr_pipeline/indicators/modes.py` — `run_daily` 안 `with run_tracking(...) as state:` 바로 다음, `# Phase A` 주석 앞에 삽입. **anchor: `# Phase A` 는 파일 전체에서 398행 한 곳뿐**(run_daily 고유)이라 `) as state:\n        # Phase A` 2줄로 edit 하면 weekly(641행)와 안 헷갈림. 파일 상단 import 에 추가:
```python
from kr_pipeline.indicators.completeness import check_daily_ohlcv_complete
```
run_tracking 블록 첫 줄:
```python
    ) as state:
        # ① 완전성 게이트: INCREMENTAL 전체실행에서 최신 ohlcv 커버리지<90% 면 지표 미계산.
        # limit_tickers 설정(테스트/부분) 및 BACKFILL/FULL_REFRESH(end=어제) 는 제외.
        if mode == Mode.INCREMENTAL and limit_tickers is None:
            check_daily_ohlcv_complete(conn, active_count=len(tickers))
        # Phase A
```

- [ ] **Step 6: Run full indicators test module (회귀)**

Run: `uv run pytest tests/test_indicators_completeness_gate.py tests/test_indicators_integration.py -v`
Expected: 신규 4 passed. `test_indicators_integration.py` 는 base 대비 실패 수 불변(사전 baseline 실패는 무관 — base↔HEAD 동일하면 회귀 아님).

- [ ] **Step 7: Commit**

```bash
git add kr_pipeline/indicators/completeness.py kr_pipeline/indicators/modes.py tests/test_indicators_completeness_gate.py
git commit -m "feat(indicators): ① 완전성 게이트 — 최신 ohlcv 커버리지<90% 면 run_daily fail-fast(체인·단독 보호)"
```

---

### Task 2: 거래 캘린더 + 신선도 로직 (②-a) — trading_calendar 모듈

**Files:**
- Create: `kr_pipeline/common/trading_calendar.py`
- Test: `tests/test_trading_calendar.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_trading_calendar.py`:
```python
from datetime import date, datetime
import pandas as pd
import pytest

import kr_pipeline.common.trading_calendar as tc


def _patch_fetch(monkeypatch, days, *, raises=False):
    def fake(index_code, start, end):
        if raises:
            raise RuntimeError("KRX timeout")
        return pd.DataFrame({"date": list(days), "close": [1] * len(days)})
    monkeypatch.setattr(tc, "fetch_index", fake)


def test_eltd_today_after_buffer(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 8), date(2026, 6, 9), date(2026, 6, 10)])
    assert tc.expected_latest_trading_day(datetime(2026, 6, 10, 18, 0)) == date(2026, 6, 10)


def test_eltd_today_before_buffer(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 8), date(2026, 6, 9), date(2026, 6, 10)])
    # 11:00 < 17:00 → 오늘 제외, 직전 거래일
    assert tc.expected_latest_trading_day(datetime(2026, 6, 10, 11, 0)) == date(2026, 6, 9)


def test_eltd_holiday(monkeypatch):
    # 오늘(6/6)이 거래일 목록에 없음 → 직전 거래일(6/5)
    _patch_fetch(monkeypatch, [date(2026, 6, 4), date(2026, 6, 5)])
    assert tc.expected_latest_trading_day(datetime(2026, 6, 6, 18, 0)) == date(2026, 6, 5)


def test_unavailable_on_empty(monkeypatch):
    monkeypatch.setattr(tc, "fetch_index", lambda *a, **k: pd.DataFrame())
    with pytest.raises(tc.TradingCalendarUnavailable):
        tc.expected_latest_trading_day(datetime(2026, 6, 10, 18, 0))


def test_unavailable_on_exception(monkeypatch):
    _patch_fetch(monkeypatch, [], raises=True)
    with pytest.raises(tc.TradingCalendarUnavailable):
        tc.expected_latest_trading_day(datetime(2026, 6, 10, 18, 0))


def test_assert_fresh_passes(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    # as_of == ELTD(=6/10, after buffer) → 통과
    tc.assert_data_fresh(date(2026, 6, 10), datetime(2026, 6, 10, 18, 0))


def test_assert_fresh_stale_raises(monkeypatch):
    _patch_fetch(monkeypatch, [date(2026, 6, 9), date(2026, 6, 10)])
    # as_of(6/9) < ELTD(6/10) → StaleDataError
    with pytest.raises(tc.StaleDataError):
        tc.assert_data_fresh(date(2026, 6, 9), datetime(2026, 6, 10, 18, 0))


def test_assert_fresh_calendar_unavailable_propagates(monkeypatch):
    _patch_fetch(monkeypatch, [], raises=True)
    # fail-closed: 캘린더 조회 실패 → TradingCalendarUnavailable 전파
    with pytest.raises(tc.TradingCalendarUnavailable):
        tc.assert_data_fresh(date(2026, 6, 10), datetime(2026, 6, 10, 18, 0))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_trading_calendar.py -v`
Expected: FAIL (`ModuleNotFoundError: kr_pipeline.common.trading_calendar`).

- [ ] **Step 3: Implement the module**

Create `kr_pipeline/common/trading_calendar.py`:
```python
"""거래 캘린더 — 라이브 KRX 지수로 '기대 최신 거래일(ELTD)' 산출 + 신선도 단정.

pykrx 의존(get_index_ohlcv via fetch_index). 조회 실패는 fail-closed(예외 전파).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from kr_pipeline.ohlcv.fetch import fetch_index

log = logging.getLogger("kr_pipeline.common.trading_calendar")

CLOSE_BUFFER = time(17, 0)   # KST. KRX 마감 15:30 후 pykrx EOD 안정화 시점.
_KOSPI_INDEX = "1001"
_LOOKBACK_DAYS = 14          # 최근 거래일 목록 확보(연휴 대비 충분).


class TradingCalendarUnavailable(RuntimeError):
    """거래 캘린더(라이브 KRX 지수) 조회 실패 — fail-closed."""


class StaleDataError(RuntimeError):
    """최신 완전 데이터가 기대 최신 거래일보다 뒤처짐 — 분석 중단."""


def expected_latest_trading_day(now: datetime) -> date:
    """기대 최신 거래일(ELTD).

    라이브 KRX 지수로 실제 거래일 목록을 얻고 마감버퍼로 오늘 포함 여부 결정:
    - 오늘이 거래일 & now.time() >= CLOSE_BUFFER → 오늘
    - 그 외 → 오늘 직전 거래일
    조회 실패/빈 결과/직전거래일 없음 → TradingCalendarUnavailable(fail-closed).
    """
    today = now.date()
    try:
        df = fetch_index(_KOSPI_INDEX, today - timedelta(days=_LOOKBACK_DAYS), today)
    except Exception as e:  # noqa: BLE001 — 모든 조회 실패를 fail-closed 로 수렴
        raise TradingCalendarUnavailable(f"거래 캘린더 조회 실패: {e}") from e
    if df is None or df.empty or "date" not in df.columns:
        raise TradingCalendarUnavailable("거래 캘린더 조회 결과 없음")
    trading_days = sorted({d for d in df["date"]})
    if today in trading_days and now.time() >= CLOSE_BUFFER:
        return today
    prior = [d for d in trading_days if d < today]
    if not prior:
        raise TradingCalendarUnavailable(
            f"직전 거래일 없음(lookback {_LOOKBACK_DAYS}d, today={today})"
        )
    return max(prior)


def assert_data_fresh(as_of: date, now: datetime) -> None:
    """as_of(최신 완전 지표일)가 ELTD 보다 뒤처지면 StaleDataError.

    ELTD 산출 실패(pykrx) 시 TradingCalendarUnavailable 전파(fail-closed).
    """
    eltd = expected_latest_trading_day(now)
    if as_of < eltd:
        raise StaleDataError(
            f"최신 거래일 {eltd} 데이터 미적재 (현재 최신 {as_of}) — 분석 중단"
        )
    log.info("freshness OK: as_of=%s eltd=%s", as_of, eltd)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_trading_calendar.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/common/trading_calendar.py tests/test_trading_calendar.py
git commit -m "feat(common): ②-a 거래캘린더 — ELTD(라이브 KRX지수+17:00버퍼) + assert_data_fresh(fail-closed)"
```

---

### Task 3: 신선도 가드 배선 (②-b) — __main__

**Files:**
- Modify: `kr_pipeline/llm_runner/__main__.py`
- Test: `tests/test_freshness_guard.py`

- [ ] **Step 1: Write the failing test (가드 헬퍼 호출 계약)**

가드 로직 자체는 Task 2 의 `assert_data_fresh` 가 테스트됨. 여기서는 **__main__ 이 모듈을 올바르게 import 하는지**(배선 smoke) 확인.

`tests/test_freshness_guard.py`:
```python
def test_main_imports_freshness_symbols():
    # __main__ 이 신선도 가드 심볼을 import 했는지(배선 회귀 방지).
    import kr_pipeline.llm_runner.__main__ as m
    assert hasattr(m, "assert_data_fresh")
    assert hasattr(m, "ZoneInfo")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_freshness_guard.py -v`
Expected: FAIL (`AssertionError`: module 에 assert_data_fresh 없음).

- [ ] **Step 3: Add imports + guard to `__main__.py`**

상단 import 수정/추가:
```python
from datetime import date as _date, datetime
from zoneinfo import ZoneInfo
```
그리고 기존 import 블록 근처에 추가:
```python
from kr_pipeline.common.trading_calendar import assert_data_fresh
```
`with run_tracking(conn, pipeline=pipeline_db_name, mode=args.mode, params=params) as state:` 블록의 **첫 줄**(`if args.mode == "weekend":` 앞)에 가드 삽입:
```python
        with run_tracking(conn, pipeline=pipeline_db_name, mode=args.mode, params=params) as state:
            # ② 신선도 가드: 자동 as_of(명시 --date 아님) & backfill 아닐 때만.
            #    as_of < ELTD 면 StaleDataError, pykrx 실패면 TradingCalendarUnavailable(fail-closed).
            if explicit is None and args.mode != "backfill":
                assert_data_fresh(as_of, datetime.now(ZoneInfo("Asia/Seoul")))
            if args.mode == "weekend":
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_freshness_guard.py -v`
Expected: 1 passed.

- [ ] **Step 5: Sanity — __main__ import 깨짐 없나(컴파일)**

Run: `uv run python -c "import kr_pipeline.llm_runner.__main__"`
Expected: 에러 없음(import 성공).

- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/llm_runner/__main__.py tests/test_freshness_guard.py
git commit -m "feat(llm): ②-b 신선도 가드 배선 — 자동 as_of 가 ELTD 보다 stale 이면 분석 중단(backfill/명시date 제외)"
```

---

## Self-Review (작성자 체크 결과)

- **Spec coverage:** ①게이트(Task1: completeness.py+run_daily 배선), ②-a캘린더+assert_data_fresh(Task2), ②-b가드 배선(Task3), 임계0.90·버퍼17:00·fail-closed·limit/backfill 예외·①②분담 모두 반영. weekly 범위 밖(미작업) — spec 과 일치. ✓
- **Placeholder scan:** 없음(모든 코드/테스트/명령 구체). ✓
- **Type consistency:** `check_daily_ohlcv_complete(conn,*,active_count,threshold)`·`expected_latest_trading_day(now)->date`·`assert_data_fresh(as_of,now)`·예외명(`IncompleteIngestionError`/`TradingCalendarUnavailable`/`StaleDataError`) 전 Task 일치. fetch_index monkeypatch 경로 `tc.fetch_index` 일치. ✓
- **테스트 격리:** db fixture rollback(no commit), sentinel 2099 날짜, 캘린더는 monkeypatch(네트워크 없음). ✓
- **FK 정합(재검토 반영):** `daily_prices.ticker → stocks(ticker)` FK 존재 → `_seed_prices` 가 각 ticker 를 stocks 에 먼저 INSERT(ON CONFLICT DO NOTHING)하도록 수정. ✓
- **회귀 안전(재검토 확인):** 기존 테스트는 `indicators.run_daily` 를 mock(test_pipeline_chains) 하거나 `compute_date_range` 만 호출(test_indicators_modes) — 실제 run_daily(INCREMENTAL, no-limit) 를 도는 테스트가 없어 게이트가 기존 테스트를 깨지 않음. 게이트는 INCREMENTAL 전용이라 BACKFILL/FULL_REFRESH 초기 적재도 무영향. ✓
- **주의(리뷰 확인):** run_daily 게이트 배선(`if mode==INCREMENTAL and limit_tickers is None`)은 1줄 호출이라 단위테스트 대신 spec-리뷰어가 diff 로 확인(헬퍼 로직은 Task1 에서 검증). __main__ 가드 조건(`explicit is None and mode!="backfill"`)도 동일.
