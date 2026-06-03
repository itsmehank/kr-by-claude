# LLM backfill 주(weekly) 단위 기간 분류 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `backfill` 모드를 단일 시점 분류기에서 "기간 × 매주 토요일(weekly basis)" 분류기로 확장하여, 지정 종목(들) 또는 전 종목을 과거 기간에 걸쳐 주 단위로 분류한다.

**Architecture:** 토요일 반복 루프를 `backfill.run` 내부에 내장한다. 후보 선정은 기존 `get_qualifying_tickers`에 ticker 필터를 추가해 재사용하고(minervini 게이트 자동 적용), 멱등성은 기존 `_already_backfilled` + PK `(symbol, analyzed_for_date)`를 주 단위로 그대로 쓴다. CLI는 backfill 전용 `--start/--end/--tickers`를 추가하되 다른 모드와는 가드로 격리한다.

**Tech Stack:** Python 3, psycopg, pytest, uv. 대상 패키지 `kr_pipeline/llm_runner`.

**Spec:** `docs/superpowers/specs/2026-06-03-llm-backfill-weekly-range-design.md`

---

## File Structure

- `kr_pipeline/llm_runner/load.py` — `get_qualifying_tickers`에 `tickers` 필터 인자 추가 (수정).
- `kr_pipeline/llm_runner/backfill.py` — `_enumerate_saturdays` 추가, `run` 시그니처를 `start/end/tickers`로 변경하고 주별 루프로 재작성 (수정). `_already_backfilled`, `_process_one`은 변경 없음.
- `kr_pipeline/llm_runner/__main__.py` — `--start/--end/--tickers` 인자 + 가드 + backfill 분기 변경 (수정).
- `tests/test_llm_backfill.py` — 신규 테스트 추가 + 기존 2개 갱신.
- `tests/test_llm_runner_main.py` — `--date` 회귀 방지 테스트 추가.

**참고 — 테스트 실행:** 이 저장소는 `uv run pytest`를 쓴다. 사전 존재하는 isolation 실패 약 25개(weekly/llm/ohlcv DB 격리)는 baseline이며, 새 작업이 그 수를 늘리지 않아야 한다(CLAUDE.md).

---

### Task 1: `get_qualifying_tickers`에 ticker 필터 추가

**Files:**
- Modify: `kr_pipeline/llm_runner/load.py:9-39`
- Test: `tests/test_llm_backfill.py`

- [ ] **Step 1: Write the failing test**

`tests/test_llm_backfill.py` 끝에 추가:

```python
def test_get_qualifying_tickers_filters_by_tickers(db):
    """tickers 인자 지정 시 그 종목 중 minervini 통과분만, 생략 시 전체."""
    from kr_pipeline.llm_runner.load import get_qualifying_tickers
    from datetime import date as _date
    as_of = _date(2023, 1, 7)  # 실데이터 이전 → 격리
    with db.cursor() as cur:
        for t in ("QF1", "QF2", "QF3"):
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'B','KOSPI') ON CONFLICT DO NOTHING", (t,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s AND date=%s", (t, as_of))
        # QF1, QF2 통과 / QF3 미통과
        cur.execute("INSERT INTO daily_indicators (ticker,date,minervini_pass,adj_close) VALUES ('QF1',%s,TRUE,1000.0)", (as_of,))
        cur.execute("INSERT INTO daily_indicators (ticker,date,minervini_pass,adj_close) VALUES ('QF2',%s,TRUE,1000.0)", (as_of,))
        cur.execute("INSERT INTO daily_indicators (ticker,date,minervini_pass,adj_close) VALUES ('QF3',%s,FALSE,1000.0)", (as_of,))
    db.commit()
    try:
        # 지정: QF1 만 (통과)
        got = get_qualifying_tickers(db, as_of=as_of, tickers=["QF1"])
        assert [r["symbol"] for r in got] == ["QF1"]
        # 지정: QF3 (미통과) → 빈 결과 = 그 주 건너뜀
        assert get_qualifying_tickers(db, as_of=as_of, tickers=["QF3"]) == []
        # 다중 지정: QF1, QF2 통과분만
        got2 = get_qualifying_tickers(db, as_of=as_of, tickers=["QF1", "QF2", "QF3"])
        assert sorted(r["symbol"] for r in got2) == ["QF1", "QF2"]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_indicators WHERE ticker IN ('QF1','QF2','QF3') AND date=%s", (as_of,))
        db.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_backfill.py::test_get_qualifying_tickers_filters_by_tickers -v`
Expected: FAIL — `get_qualifying_tickers() got an unexpected keyword argument 'tickers'`

- [ ] **Step 3: Write minimal implementation**

`kr_pipeline/llm_runner/load.py`의 `get_qualifying_tickers`를 다음으로 교체:

```python
def get_qualifying_tickers(
    conn: Connection, as_of: date | None = None, tickers: list[str] | None = None
) -> list[dict]:
    """주말 (5) batch 후보 종목 조회.

    as_of 가 주어지면 그 날짜 이하 가장 최근 daily_indicators 의 날짜를 찾아 사용.
    tickers 가 주어지면 그 종목들로 한정 (minervini 통과분만 반환 — 미통과는 자동 제외).
    tickers=None 이면 그 날짜 minervini 통과 전 종목.

    Returns: [{"symbol", "market"}, ...]
    """
    with conn.cursor() as cur:
        if as_of is None:
            cur.execute("SELECT MAX(date) FROM daily_indicators")
        else:
            cur.execute("SELECT MAX(date) FROM daily_indicators WHERE date <= %s", (as_of,))
        row = cur.fetchone()
        target_date = row[0] if row and row[0] else (as_of or date.today())

    sql = """
        SELECT i.ticker, s.market
          FROM daily_indicators i
          JOIN stocks s ON s.ticker = i.ticker
         WHERE i.date = %s
           AND i.minervini_pass = TRUE
           AND s.delisted_at IS NULL
    """
    params: list = [target_date]
    if tickers:
        sql += " AND i.ticker = ANY(%s)"
        params.append(list(tickers))
    sql += " ORDER BY i.ticker"

    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [{"symbol": r[0], "market": r[1]} for r in cur.fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_llm_backfill.py::test_get_qualifying_tickers_filters_by_tickers -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/llm_runner/load.py tests/test_llm_backfill.py
git commit -m "feat(backfill): get_qualifying_tickers 에 ticker 필터 추가"
```

---

### Task 2: `_enumerate_saturdays` 헬퍼 추가

**Files:**
- Modify: `kr_pipeline/llm_runner/backfill.py`
- Test: `tests/test_llm_backfill.py`

- [ ] **Step 1: Write the failing test**

`tests/test_llm_backfill.py` 끝에 추가:

```python
def test_enumerate_saturdays():
    from kr_pipeline.llm_runner.backfill import _enumerate_saturdays
    from datetime import date as _date
    # 2024-05-01(수) ~ 2024-05-31(금) 사이 토요일: 4,11,18,25
    got = _enumerate_saturdays(_date(2024, 5, 1), _date(2024, 5, 31))
    assert got == [_date(2024, 5, 4), _date(2024, 5, 11), _date(2024, 5, 18), _date(2024, 5, 25)]
    # 경계가 토요일이면 포함 (start=end=토요일 → 그 토요일 1개)
    assert _enumerate_saturdays(_date(2024, 5, 4), _date(2024, 5, 4)) == [_date(2024, 5, 4)]
    # 범위 내 토요일 없음 → 빈 리스트 (월~금)
    assert _enumerate_saturdays(_date(2024, 5, 6), _date(2024, 5, 10)) == []
    # start > end → 빈 리스트
    assert _enumerate_saturdays(_date(2024, 5, 31), _date(2024, 5, 1)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_backfill.py::test_enumerate_saturdays -v`
Expected: FAIL — `cannot import name '_enumerate_saturdays'`

- [ ] **Step 3: Write minimal implementation**

`kr_pipeline/llm_runner/backfill.py`에서 import 아래(`from datetime import date, datetime, timezone` 활용), `_already_backfilled` 위에 추가. 상단에 `from datetime import timedelta`도 필요하므로 기존 import 라인을 다음으로 교체:

```python
from datetime import date, datetime, timedelta, timezone
```

그리고 헬퍼 추가:

```python
def _enumerate_saturdays(start: date, end: date) -> list[date]:
    """start~end(양끝 포함) 범위의 모든 토요일을 오름차순으로 반환.

    토요일은 weekday()==5. start>end 면 빈 리스트.
    """
    if start > end:
        return []
    # start 이상인 첫 토요일로 전진
    d = start + timedelta(days=(5 - start.weekday()) % 7)
    out: list[date] = []
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_llm_backfill.py::test_enumerate_saturdays -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/llm_runner/backfill.py tests/test_llm_backfill.py
git commit -m "feat(backfill): _enumerate_saturdays 헬퍼 추가"
```

---

### Task 3: `backfill.run` 을 주별 범위 루프로 재작성

**Files:**
- Modify: `kr_pipeline/llm_runner/backfill.py:32-65` (run 함수)
- Test: `tests/test_llm_backfill.py` (기존 `test_backfill_run_inserts_and_wires_on_date` 갱신 + 신규)

- [ ] **Step 1: 기존 테스트를 새 시그니처로 갱신 (실패하도록)**

`tests/test_llm_backfill.py`의 `test_backfill_run_inserts_and_wires_on_date` 전체를 다음으로 교체. (핵심: `as_of=` → `start=/end=`, 날짜를 토요일 `2024-01-06`으로 변경.)

```python
def test_backfill_run_inserts_and_wires_on_date(db, monkeypatch):
    import kr_pipeline.llm_runner.backfill as bf
    from datetime import date as _date
    # 토요일, 실데이터 시작(2024-05-17) 이전 → get_qualifying_tickers 가 우리가 심은 종목만 반환(격리).
    sat = _date(2024, 1, 6)  # 토요일
    with db.cursor() as cur:
        cur.execute("DELETE FROM classification_backfill WHERE analyzed_for_date=%s", (sat,))
        for t in ("BKR1", "BKR2"):
            cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'B','KOSPI') ON CONFLICT DO NOTHING", (t,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker=%s AND date=%s", (t, sat))
            cur.execute(
                """INSERT INTO daily_indicators (ticker, date, minervini_pass, adj_close)
                   VALUES (%s,%s,TRUE,1000.0)""",
                (t, sat),
            )
    db.commit()
    seen_on_date = []
    monkeypatch.setattr(bf, "build_analysis_zip",
                        lambda conn, symbol, on_date=None, **kw: seen_on_date.append(on_date) or b"zip")
    monkeypatch.setattr(bf, "call_claude",
                        lambda **kwargs: _result("watch"))
    try:
        res = bf.run(db, start=sat, end=sat, dry_run=False)
        assert res["processed"] == 2
        assert res["weeks"] == 1
        assert seen_on_date and all(d == sat for d in seen_on_date)
        with db.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM classification_backfill WHERE analyzed_for_date=%s", (sat,))
            assert cur.fetchone()[0] == 2
        # 재실행 = resume: 이미 된 것 skip
        res2 = bf.run(db, start=sat, end=sat, dry_run=False)
        assert res2["processed"] == 0
        assert res2["skipped_existing"] == 2
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE analyzed_for_date=%s", (sat,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker IN ('BKR1','BKR2') AND date=%s", (sat,))
        db.commit()
```

신규 다중 주(週) 테스트도 끝에 추가:

```python
def test_backfill_run_multi_week_with_tickers(db, monkeypatch):
    """여러 토요일 × ticker 지정 — 통과한 주만 분류, weeks 집계."""
    import kr_pipeline.llm_runner.backfill as bf
    from datetime import date as _date
    s1, s2 = _date(2024, 1, 6), _date(2024, 1, 13)  # 연속 토요일 2개
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('BKW1','B','KOSPI') ON CONFLICT DO NOTHING")
        for s in (s1, s2):
            cur.execute("DELETE FROM classification_backfill WHERE symbol='BKW1' AND analyzed_for_date=%s", (s,))
            cur.execute("DELETE FROM daily_indicators WHERE ticker='BKW1' AND date=%s", (s,))
        # s1 통과 / s2 미통과 → s2 는 건너뛰어야 함
        cur.execute("INSERT INTO daily_indicators (ticker,date,minervini_pass,adj_close) VALUES ('BKW1',%s,TRUE,1000.0)", (s1,))
        cur.execute("INSERT INTO daily_indicators (ticker,date,minervini_pass,adj_close) VALUES ('BKW1',%s,FALSE,1000.0)", (s2,))
    db.commit()
    monkeypatch.setattr(bf, "build_analysis_zip", lambda conn, symbol, on_date=None, **kw: b"zip")
    monkeypatch.setattr(bf, "call_claude", lambda **kwargs: _result("watch"))
    try:
        res = bf.run(db, start=s1, end=s2, tickers=["BKW1"], dry_run=False)
        assert res["weeks"] == 2          # 토요일 2개 순회
        assert res["processed"] == 1      # s1 만 분류 (s2 미통과 건너뜀)
        with db.cursor() as cur:
            cur.execute("SELECT analyzed_for_date FROM classification_backfill WHERE symbol='BKW1' ORDER BY analyzed_for_date")
            rows = [r[0] for r in cur.fetchall()]
        assert rows == [s1]
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM classification_backfill WHERE symbol='BKW1'")
            cur.execute("DELETE FROM daily_indicators WHERE ticker='BKW1' AND date IN (%s,%s)", (s1, s2))
        db.commit()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_backfill.py::test_backfill_run_inserts_and_wires_on_date tests/test_llm_backfill.py::test_backfill_run_multi_week_with_tickers -v`
Expected: FAIL — `run() got an unexpected keyword argument 'start'`

- [ ] **Step 3: Write minimal implementation**

`kr_pipeline/llm_runner/backfill.py`의 `run` 함수(현재 `def run(conn, *, dry_run=False, as_of=None, limit=None)` ~ return 블록)를 다음으로 교체:

```python
def run(conn: Connection, *, start: date, end: date, tickers: list[str] | None = None,
        dry_run: bool = False, limit: int | None = None) -> dict:
    """기간 × 매주 토요일 백필. 토요일마다 그 주 minervini 통과 종목(또는 지정 종목)을 분류."""
    saturdays = _enumerate_saturdays(start, end)
    agg = {
        "weeks": 0,
        "processed": 0,
        "skipped_existing": 0,
        "failures": 0,
        "failed": [],
        "start": str(start),
        "end": str(end),
    }

    for as_of in saturdays:
        candidates = get_qualifying_tickers(conn, as_of=as_of, tickers=tickers)
        done = _already_backfilled(conn, as_of)
        skipped = [c for c in candidates if c["symbol"] in done]
        candidates = [c for c in candidates if c["symbol"] not in done]
        if limit:
            candidates = candidates[:limit]

        log.info("backfill week=%s: %d candidate(s) (done %d)", as_of, len(candidates), len(done))

        for c in candidates:
            symbol = c["symbol"]
            market = c["market"]
            try:
                _process_one(conn, symbol, market, dry_run=dry_run, as_of=as_of)
                agg["processed"] += 1
                conn.commit()
            except Exception as e:  # noqa: BLE001
                log.warning("backfill %s @ %s failed: %s", symbol, as_of, e)
                agg["failed"].append([symbol, str(as_of), str(e)])
                agg["failures"] += 1
                conn.rollback()

        agg["skipped_existing"] += len(skipped)
        agg["weeks"] += 1

    return agg
```

(주의: `_already_backfilled`와 `_process_one`은 변경하지 않는다.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_backfill.py -k "run_inserts or multi_week or idempotent or gate or basic" -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/llm_runner/backfill.py tests/test_llm_backfill.py
git commit -m "feat(backfill): run 을 주별 범위 루프로 재작성 (start/end/tickers)"
```

---

### Task 4: `__main__` CLI 인자 + 가드 + backfill 분기

**Files:**
- Modify: `kr_pipeline/llm_runner/__main__.py:40,53-54,95-96`
- Test: `tests/test_llm_backfill.py` (기존 `test_backfill_mode_requires_date` 갱신 + 신규 가드), `tests/test_llm_runner_main.py` (`--date` 회귀)

- [ ] **Step 1: 기존 테스트 갱신 + 가드 테스트 작성 (실패하도록)**

`tests/test_llm_backfill.py`의 `test_backfill_mode_requires_date` 를 다음으로 교체:

```python
def test_backfill_mode_requires_start_end():
    import sys, pytest
    from kr_pipeline.llm_runner.__main__ import main
    argv = sys.argv
    try:
        # --start/--end 없음 → 에러
        sys.argv = ["prog", "--mode=backfill"]
        with pytest.raises(SystemExit):
            main()
        # --start 만 있고 --end 없음 → 에러
        sys.argv = ["prog", "--mode=backfill", "--start=2024-05-01"]
        with pytest.raises(SystemExit):
            main()
    finally:
        sys.argv = argv


def test_range_args_rejected_for_non_backfill_modes():
    """--start/--end/--tickers 는 backfill 외 모드와 쓰면 에러."""
    import sys, pytest
    from kr_pipeline.llm_runner.__main__ import main
    argv = sys.argv
    try:
        for extra in ("--start=2024-05-01", "--end=2024-05-31", "--tickers=000660"):
            sys.argv = ["prog", "--mode=weekend", extra]
            with pytest.raises(SystemExit):
                main()
    finally:
        sys.argv = argv
```

`tests/test_llm_runner_main.py` 끝에 `--date` 회귀 방지 테스트 추가:

```python
def test_date_arg_still_flows_to_weekend(mocker):
    """--date 는 backfill 외 모드(weekend)에서 그대로 동작해야 함 (회귀 방지)."""
    from datetime import date as _date
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    # --date 지정 시 MAX(date) 쿼리는 건너뛰므로, fetchone 은 run_tracking 의 RETURNING id 만 응답.
    conn.cursor.return_value.fetchone.side_effect = [(1,)]

    mocker.patch(
        "kr_pipeline.common.config.Config.load",
        return_value=MagicMock(database_url="postgresql://test"),
    )
    mocker.patch(
        "kr_pipeline.llm_runner.__main__.connect",
        side_effect=_make_mock_connect(conn),
    )
    mocker.patch(
        "kr_pipeline.llm_runner.__main__.run_tracking",
        side_effect=_make_mock_run_tracking(),
    )
    spy = mocker.patch(
        "kr_pipeline.llm_runner.modes.run_weekend",
        return_value={"processed": 1, "failures": 0},
    )

    from kr_pipeline.llm_runner.__main__ import main
    with patch.object(sys, "argv", ["llm_runner", "--mode=weekend", "--date=2024-05-17", "--dry-run"]):
        rc = main()

    assert rc == 0
    assert spy.call_args.kwargs["as_of"] == _date(2024, 5, 17)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_backfill.py::test_backfill_mode_requires_start_end tests/test_llm_backfill.py::test_range_args_rejected_for_non_backfill_modes tests/test_llm_runner_main.py::test_date_arg_still_flows_to_weekend -v`
Expected: FAIL — backfill은 `--date` 없을 때만 막으므로 `requires_start_end` 가 통과 못 하고, `--start` 인자가 정의 안 돼 `unrecognized arguments` 에러 등.

- [ ] **Step 3: Write implementation**

(a) `kr_pipeline/llm_runner/__main__.py:40` 의 `--date` 인자 정의 **아래**에 신규 인자 3개 추가:

```python
    parser.add_argument("--date", type=str, help="YYYY-MM-DD")
    parser.add_argument("--start", type=str, help="YYYY-MM-DD (backfill 범위 시작)")
    parser.add_argument("--end", type=str, help="YYYY-MM-DD (backfill 범위 종료)")
    parser.add_argument("--tickers", type=str, help="쉼표 구분 종목 코드 (backfill 전용, 생략 시 전 종목)")
```

(b) `__main__.py:53-54` 의 기존 backfill 검증 블록

```python
    if args.mode == "backfill" and not args.date:
        parser.error("--date is required with --mode=backfill (과거 기준일 없는 백필은 무의미).")
```

을 다음으로 교체:

```python
    # --start/--end/--tickers 는 backfill 전용. 다른 모드와 쓰면 조용히 무시되어
    # 의도와 다른 동작을 할 수 있으므로 명시적 에러로 차단.
    if args.mode != "backfill" and (args.start or args.end or args.tickers):
        parser.error("--start/--end/--tickers is only supported with --mode=backfill.")
    if args.mode == "backfill" and (not args.start or not args.end):
        parser.error("--start and --end are required with --mode=backfill (기간 없는 백필은 무의미).")
```

(c) `__main__.py:95-96` 의 backfill 분기

```python
            elif args.mode == "backfill":
                result = backfill.run(conn, dry_run=args.dry_run, as_of=as_of, limit=args.limit)
```

을 다음으로 교체:

```python
            elif args.mode == "backfill":
                _start = _date.fromisoformat(args.start)
                _end = _date.fromisoformat(args.end)
                _tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
                result = backfill.run(conn, start=_start, end=_end, tickers=_tickers,
                                      dry_run=args.dry_run, limit=args.limit)
```

(d) `__main__.py:75-81` 의 params dict 에 backfill 범위 정보를 기록하도록 키 추가 (run_tracking 추적용):

```python
        params = {
            "mode": args.mode,
            "dry_run": args.dry_run,
            "as_of": as_of.isoformat(),
            "limit": args.limit,
            "ticker": getattr(args, "ticker", None),
            "start": getattr(args, "start", None),
            "end": getattr(args, "end", None),
            "tickers": getattr(args, "tickers", None),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_backfill.py::test_backfill_mode_requires_start_end tests/test_llm_backfill.py::test_range_args_rejected_for_non_backfill_modes tests/test_llm_runner_main.py::test_date_arg_still_flows_to_weekend -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/llm_runner/__main__.py tests/test_llm_backfill.py tests/test_llm_runner_main.py
git commit -m "feat(backfill): CLI --start/--end/--tickers 추가 + backfill 전용 가드"
```

---

### Task 5: 전체 스위트 회귀 확인 + baseline 점검

**Files:** (없음 — 검증 단계)

- [ ] **Step 1: backfill 관련 전체 + main 테스트 실행**

Run: `uv run pytest tests/test_llm_backfill.py tests/test_llm_runner_main.py -v`
Expected: 모두 PASS (신규 포함). FAIL 0.

- [ ] **Step 2: 전체 스위트 실행 — baseline 초과 여부 확인**

Run: `uv run pytest tests/ -q`
Expected: 사전 존재 isolation fail 약 25개(weekly/llm/ohlcv DB 격리)만 남고, 이 작업으로 **새 실패가 추가되지 않음**. 실패 수가 baseline(~25)을 초과하면 원인을 조사(systematic-debugging)하고 수정.

- [ ] **Step 3: 수동 동작 확인 (dry-run)**

Run: `uv run python -m kr_pipeline.llm_runner --mode=backfill --tickers=000660 --start=2024-05-01 --end=2024-05-31 --dry-run`
Expected: 에러 없이 종료. 로그에 `backfill week=2024-05-04 ...` 등 토요일 4개가 순회되고, 마지막 `DONE backfill: {...weeks: 4...}` 출력.

- [ ] **Step 4: 가드 동작 확인**

Run: `uv run python -m kr_pipeline.llm_runner --mode=weekend --tickers=000660`
Expected: `error: --start/--end/--tickers is only supported with --mode=backfill` 로 비정상 종료(rc!=0).

- [ ] **Step 5: 최종 커밋(필요 시) 및 마무리**

변경분이 모두 커밋되었는지 확인:

```bash
git status
git log --oneline -5
```

Expected: working tree clean, Task 1~4 커밋 4개가 보임.

---

## Self-Review (작성자 점검 결과)

**1. Spec coverage**
- CLI `--start/--end/--tickers` + `--date` 유지 → Task 4 ✓
- 토요일 weekly 순회 → Task 2(`_enumerate_saturdays`) + Task 3(run 루프) ✓
- minervini 미통과 주 건너뜀 → Task 1(ticker 필터, 통과분만) + Task 3 multi_week 테스트 ✓
- ticker 생략 = 전 종목 → Task 1(tickers=None) ✓
- 멱등/resume → Task 3(skipped_existing, 재실행 processed 0) ✓
- on_date lookahead 없음 → Task 3(seen_on_date 검증, `_process_one` 불변) ✓
- 다른 모드 무영향(가드) → Task 4(reject 테스트, `--date` 회귀 테스트) ✓
- 기존 테스트 갱신 → Task 3(run 테스트), Task 4(requires_start_end) ✓
- baseline 준수 → Task 5 ✓

**2. Placeholder scan:** 없음 — 모든 코드 스텝에 실제 코드 포함.

**3. Type consistency:** `get_qualifying_tickers(conn, as_of=, tickers=)` 시그니처가 Task 1 정의와 Task 3 호출에서 일치. `run(conn, *, start, end, tickers=None, dry_run=False, limit=None)` 시그니처가 Task 3 정의와 Task 4 호출에서 일치. 반환 dict 키(`weeks/processed/skipped_existing/failures/failed/start/end`)가 Task 3 구현과 테스트 단언에서 일치.
