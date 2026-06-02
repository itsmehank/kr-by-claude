# as-of 시계열 정합화 (on_date 결선) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 차트 2개 + CSV 3개 빌더가 `on_date`(기준 데이터 날짜)를 존중해 그 시점까지의 시계열만 담도록 하고, `build_analysis_zip` 이 보유한 `on_date` 를 이들에 마저 전달한다.

**Architecture:** 5개 빌더에 `on_date: date | None = None` 파라미터 추가. 제공 시 `AND <date_col> <= on_date` 필터(named params로 조건부 결합), None이면 기존 동작(최신 N개) 유지. `build_analysis_zip` 의 5개 호출에 `on_date` 전달. 라이브는 `on_date=date.today()` 로 흘러 동작 불변.

**Tech Stack:** Python (psycopg named params, pandas/matplotlib for charts), PostgreSQL, pytest. 모든 변경은 인라인 SQL.

**핵심 규칙 (A안):** `on_date` 제공 시 `<date_col> <= on_date` 중 최신 N개. 이력 부족하면 LIMIT가 자연 처리(있는 만큼). `on_date=None` 이면 필터 없음(기존과 동일).

**테스트 규약 (CLAUDE.md):** `uv run pytest tests/` — 사전 isolation fail 약 26개 baseline, 늘리지 않을 것. 개별: `uv run pytest tests/<file>::<test> -v`. 테스트는 고유 ticker + try/finally 정리, `db` 픽스처 사용.

---

### Task 1: build_daily_csv 에 on_date

**Files:**
- Modify: `api/services/csv_builder.py` (`build_daily_csv`)
- Test: `tests/test_api_csv_builder.py`

- [ ] **Step 1: 실패 테스트 작성** — 파일 끝에 추가

```python
def test_build_daily_csv_respects_on_date(db):
    from datetime import date, timedelta
    t = "ASOFD1"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'D','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        for i in range(20):
            d = date(2025, 6, 1) + timedelta(days=i)
            cur.execute(
                """INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value)
                   VALUES (%s,%s,100,105,95,100,%s,1000,100000) ON CONFLICT DO NOTHING""",
                (t, d, 100 + i),
            )
    db.commit()
    try:
        text = build_daily_csv(db, t, days=60, on_date=date(2025, 6, 10)).decode("utf-8")
        dates = [l.split(",")[0] for l in text.strip().split("\n")[1:]]
        assert "2025-06-10" in dates           # on_date 포함
        assert "2025-06-11" not in dates        # on_date 이후 제외
        assert max(dates) == "2025-06-10"
        # on_date=None 회귀: 최신(D20) 포함
        text2 = build_daily_csv(db, t, days=60).decode("utf-8")
        dates2 = [l.split(",")[0] for l in text2.strip().split("\n")[1:]]
        assert "2025-06-20" in dates2
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        db.commit()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_csv_builder.py::test_build_daily_csv_respects_on_date -v`
Expected: FAIL — `build_daily_csv() got an unexpected keyword argument 'on_date'`.

- [ ] **Step 3: 구현** — `csv_builder.py`

파일 상단 import에 `from datetime import date` 추가 (없으면). `build_daily_csv` 를 named params + 조건부 필터로 교체:

```python
def build_daily_csv(conn: Connection, ticker: str, days: int = 60, on_date: date | None = None) -> bytes:
    """daily_prices(가격·거래량) + daily_indicators(지표) JOIN → CSV bytes.

    on_date 제공 시 그 날짜 이하 최신 days 개. None이면 최신 days 개.
    """
    indicator_cols_sql = ", ".join(f"i.{c}" for c in DAILY_INDICATOR_COLUMNS)
    date_filter = "AND p.date <= %(on_date)s" if on_date is not None else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT p.date, p.adj_close, p.volume,
                   {indicator_cols_sql}
              FROM daily_prices p
              LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = %(ticker)s {date_filter}
             ORDER BY p.date DESC
             LIMIT %(days)s
            """,
            {"ticker": ticker, "days": days, "on_date": on_date},
        )
        rows = cur.fetchall()
    rows = list(reversed(rows))

    buf = io.StringIO()
    writer = csv.writer(buf)
    header = ["date", "adj_close", "volume"] + DAILY_INDICATOR_COLUMNS
    writer.writerow(header)
    for row in rows:
        writer.writerow([_fmt(v) for v in row])
    return buf.getvalue().encode("utf-8")
```

- [ ] **Step 4: 통과 확인 + 회귀**

Run: `uv run pytest tests/test_api_csv_builder.py -v`
Expected: 신규 PASS, 기존 CSV 테스트 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add api/services/csv_builder.py tests/test_api_csv_builder.py
git commit -m "feat(as-of): build_daily_csv on_date 윈도잉"
```

---

### Task 2: build_weekly_csv 에 on_date

**Files:**
- Modify: `api/services/csv_builder.py` (`build_weekly_csv`)
- Test: `tests/test_api_csv_builder.py`

- [ ] **Step 1: 실패 테스트 작성** — 파일 끝에 추가

```python
def test_build_weekly_csv_respects_on_date(db):
    from datetime import date, timedelta
    t = "ASOFW1"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'W','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
        for i in range(10):
            wk = date(2025, 3, 7) + timedelta(weeks=i)  # 금요일들
            cur.execute(
                """INSERT INTO weekly_indicators (ticker, week_end_date, adj_close, volume)
                   VALUES (%s,%s,%s,1000) ON CONFLICT DO NOTHING""",
                (t, wk, 100 + i),
            )
    db.commit()
    try:
        cutoff = date(2025, 3, 7) + timedelta(weeks=4)  # 5번째 주 (i=4)
        text = build_weekly_csv(db, t, weeks=104, on_date=cutoff).decode("utf-8")
        dates = [l.split(",")[0] for l in text.strip().split("\n")[1:]]
        later = (date(2025, 3, 7) + timedelta(weeks=5)).isoformat()
        assert cutoff.isoformat() in dates
        assert later not in dates
        assert max(dates) == cutoff.isoformat()
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_indicators WHERE ticker=%s", (t,))
        db.commit()
```

> 구현자 주의: `weekly_indicators` 에 NOT NULL 컬럼이 더 있어 INSERT가 실패하면, `\d weekly_indicators` 로 확인해 최소값을 채워라(테스트 의도 유지). `WEEKLY_COLUMNS` 의 첫 컬럼이 `week_end_date` 이므로 CSV 첫 칸 = 주말일.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_csv_builder.py::test_build_weekly_csv_respects_on_date -v`
Expected: FAIL — unexpected keyword argument 'on_date'.

- [ ] **Step 3: 구현** — `build_weekly_csv` 교체

```python
def build_weekly_csv(conn: Connection, ticker: str, weeks: int = 104, on_date: date | None = None) -> bytes:
    cols_sql = ", ".join(WEEKLY_COLUMNS)
    date_filter = "AND week_end_date <= %(on_date)s" if on_date is not None else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {cols_sql}
              FROM weekly_indicators
             WHERE ticker = %(ticker)s {date_filter}
             ORDER BY week_end_date DESC
             LIMIT %(weeks)s
            """,
            {"ticker": ticker, "weeks": weeks, "on_date": on_date},
        )
        rows = cur.fetchall()
    rows = list(reversed(rows))

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(WEEKLY_COLUMNS)
    for row in rows:
        writer.writerow([_fmt(v) for v in row])
    return buf.getvalue().encode("utf-8")
```

- [ ] **Step 4: 통과 확인 + 회귀**

Run: `uv run pytest tests/test_api_csv_builder.py -v`
Expected: 신규 PASS, 기존 PASS.

- [ ] **Step 5: 커밋**

```bash
git add api/services/csv_builder.py tests/test_api_csv_builder.py
git commit -m "feat(as-of): build_weekly_csv on_date 윈도잉"
```

---

### Task 3: build_index_csv 에 on_date

**Files:**
- Modify: `api/services/csv_builder.py` (`build_index_csv`)
- Test: `tests/test_api_csv_builder.py`

- [ ] **Step 1: 실패 테스트 작성** — 파일 끝에 추가

```python
def test_build_index_csv_respects_on_date(db):
    from datetime import date, timedelta
    code = "ASOFIDX"
    with db.cursor() as cur:
        cur.execute("DELETE FROM index_daily WHERE index_code=%s", (code,))
        for i in range(15):
            d = date(2025, 6, 1) + timedelta(days=i)
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value)
                   VALUES (%s,%s,10,11,9,10,1000,100000) ON CONFLICT DO NOTHING""",
                (code, d),
            )
    db.commit()
    try:
        text = build_index_csv(db, code, "daily", lookback=60, on_date=date(2025, 6, 8)).decode("utf-8")
        dates = [l.split(",")[0] for l in text.strip().split("\n")[1:]]
        assert "2025-06-08" in dates
        assert "2025-06-09" not in dates
        assert max(dates) == "2025-06-08"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM index_daily WHERE index_code=%s", (code,))
        db.commit()
```

> 구현자 주의: `index_daily` 에 NOT NULL 컬럼이 더 있으면 `\d index_daily` 로 확인해 최소값 채워라.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_csv_builder.py::test_build_index_csv_respects_on_date -v`
Expected: FAIL — unexpected keyword argument 'on_date'.

- [ ] **Step 3: 구현** — `build_index_csv` 교체 (daily/weekly 각각 date_col 다름)

```python
def build_index_csv(conn: Connection, index_code: str, timeframe: str, lookback: int = 60,
                    on_date: date | None = None) -> bytes:
    """index_daily 또는 weekly_index 의 가격 시계열. on_date 제공 시 그 날짜 이하 최신 lookback 개."""
    if timeframe == "daily":
        cols_sql = ", ".join(INDEX_COLUMNS_DAILY)
        date_filter = "AND date <= %(on_date)s" if on_date is not None else ""
        sql = (f"SELECT {cols_sql} FROM index_daily "
               f"WHERE index_code = %(code)s {date_filter} ORDER BY date DESC LIMIT %(lookback)s")
    elif timeframe == "weekly":
        cols = ["week_end_date AS date", "open", "high", "low", "close", "volume", "value"]
        cols_sql = ", ".join(cols)
        date_filter = "AND week_end_date <= %(on_date)s" if on_date is not None else ""
        sql = (f"SELECT {cols_sql} FROM weekly_index "
               f"WHERE index_code = %(code)s {date_filter} ORDER BY week_end_date DESC LIMIT %(lookback)s")
    else:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    with conn.cursor() as cur:
        cur.execute(sql, {"code": index_code, "lookback": lookback, "on_date": on_date})
        rows = cur.fetchall()
    rows = list(reversed(rows))

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(INDEX_COLUMNS_DAILY)
    for row in rows:
        writer.writerow([_fmt(v) for v in row])
    return buf.getvalue().encode("utf-8")
```

- [ ] **Step 4: 통과 확인 + 회귀**

Run: `uv run pytest tests/test_api_csv_builder.py -v`
Expected: 신규 PASS, 기존 PASS.

- [ ] **Step 5: 커밋**

```bash
git add api/services/csv_builder.py tests/test_api_csv_builder.py
git commit -m "feat(as-of): build_index_csv on_date 윈도잉 (daily/weekly)"
```

---

### Task 4: render_daily_chart 에 on_date

**Files:**
- Modify: `api/services/chart_render.py` (`render_daily_chart`)
- Test: `tests/test_api_chart_render.py`

- [ ] **Step 1: 실패(변별) 테스트 작성** — 파일 끝에 추가

차트 PNG 내용은 날짜를 직접 못 읽으므로, "on_date가 모든 데이터 이전이면 빈 차트(작음) / 데이터 포함이면 채워진 차트(큼)" 로 변별한다. 필터 미적용(버그)이면 on_date 무시하고 항상 채워져 → 두 크기가 같아져 실패.

```python
def test_render_daily_chart_respects_on_date(db):
    from datetime import date, timedelta
    t = "ASOFC1"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'C','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        for i in range(20):
            d = date(2025, 6, 2) + timedelta(days=i)
            if d.weekday() >= 5:
                continue
            price = 1000 + i * 10
            cur.execute(
                """INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,1000,100000) ON CONFLICT DO NOTHING""",
                (t, d, price, price + 20, price - 20, price, price),
            )
    db.commit()
    try:
        populated = render_daily_chart(db, t, range_days=60, on_date=date(2025, 6, 20))
        before_all = render_daily_chart(db, t, range_days=60, on_date=date(2025, 1, 1))  # 모든 데이터 이전
        assert isinstance(populated, bytes) and len(populated) > 1000   # 정상 렌더
        # on_date 이전 → 행 없음 → 빈 차트(채워진 차트보다 작음). 필터 미적용이면 둘이 같아짐.
        assert len(before_all) < len(populated)
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        db.commit()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_chart_render.py::test_render_daily_chart_respects_on_date -v`
Expected: FAIL — `render_daily_chart() got an unexpected keyword argument 'on_date'`.

- [ ] **Step 3: 구현** — `chart_render.py`

파일 상단 import에 `from datetime import date` 추가 (없으면). `render_daily_chart` 의 시그니처/쿼리:

```python
def render_daily_chart(conn: Connection, ticker: str, range_days: int = 365, on_date: date | None = None) -> bytes:
    """일봉 차트 PNG bytes. on_date 제공 시 그 날짜 이하 최신 range_days 개."""
    date_filter = "AND p.date <= %(on_date)s" if on_date is not None else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT p.date, p.open, p.high, p.low, p.close, p.adj_close, p.volume,
                   i.sma_50, i.sma_150, i.sma_200, i.w52_high, i.w52_low,
                   i.rs_line, i.rs_line_52w_high,
                   i.avg_volume_50d, i.pocket_pivot_flag, i.distribution_day_flag
              FROM daily_prices p
              LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = %(ticker)s {date_filter}
             ORDER BY p.date DESC
             LIMIT %(range_days)s
            """,
            {"ticker": ticker, "range_days": range_days, "on_date": on_date},
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

    if not rows:
        return _render_empty_chart(f"{ticker} (no data)")

    df = pd.DataFrame(rows, columns=cols).sort_values("date").reset_index(drop=True)
    df = _coerce_numeric(df)
    return _render_ohlc_chart(df, title=f"{ticker} Daily", x_label="Date")
```

- [ ] **Step 4: 통과 확인 + 회귀**

Run: `uv run pytest tests/test_api_chart_render.py -v`
Expected: 신규 PASS, 기존 차트 테스트 PASS.

- [ ] **Step 5: 커밋**

```bash
git add api/services/chart_render.py tests/test_api_chart_render.py
git commit -m "feat(as-of): render_daily_chart on_date 윈도잉"
```

---

### Task 5: render_weekly_chart 에 on_date

**Files:**
- Modify: `api/services/chart_render.py` (`render_weekly_chart`)
- Test: `tests/test_api_chart_render.py`

- [ ] **Step 1: 실패(변별) 테스트 작성** — 파일 끝에 추가

```python
def test_render_weekly_chart_respects_on_date(db):
    from datetime import date, timedelta
    t = "ASOFC2"
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'C','KOSPI') ON CONFLICT DO NOTHING", (t,))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
        for i in range(12):
            wk = date(2025, 3, 7) + timedelta(weeks=i)
            price = 1000 + i * 10
            cur.execute(
                """INSERT INTO weekly_prices (ticker, week_end_date, open, high, low, close, adj_close, volume, value)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,1000,100000) ON CONFLICT DO NOTHING""",
                (t, wk, price, price + 20, price - 20, price, price),
            )
    db.commit()
    try:
        populated = render_weekly_chart(db, t, range_weeks=104, on_date=date(2025, 3, 7) + timedelta(weeks=11))
        before_all = render_weekly_chart(db, t, range_weeks=104, on_date=date(2025, 1, 1))
        assert isinstance(populated, bytes) and len(populated) > 1000
        assert len(before_all) < len(populated)
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
        db.commit()
```

> 구현자 주의: `weekly_prices` NOT NULL 컬럼 부족 시 `\d weekly_prices` 로 확인해 채워라.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_chart_render.py::test_render_weekly_chart_respects_on_date -v`
Expected: FAIL — unexpected keyword argument 'on_date'.

- [ ] **Step 3: 구현** — `render_weekly_chart` 시그니처/쿼리

```python
def render_weekly_chart(conn: Connection, ticker: str, range_weeks: int = 104, on_date: date | None = None) -> bytes:
    """주봉 차트 PNG bytes. on_date 제공 시 그 날짜 이하 최신 range_weeks 개."""
    date_filter = "AND p.week_end_date <= %(on_date)s" if on_date is not None else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT p.week_end_date AS date, p.open, p.high, p.low, p.close, p.adj_close, p.volume,
                   i.sma_10w, i.sma_30w, i.sma_40w, i.w52_high, i.w52_low,
                   i.rs_line, i.rs_line_52w_high,
                   i.avg_volume_10w
              FROM weekly_prices p
              LEFT JOIN weekly_indicators i ON i.ticker = p.ticker AND i.week_end_date = p.week_end_date
             WHERE p.ticker = %(ticker)s {date_filter}
             ORDER BY p.week_end_date DESC
             LIMIT %(range_weeks)s
            """,
            {"ticker": ticker, "range_weeks": range_weeks, "on_date": on_date},
        )
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

    if not rows:
        return _render_empty_chart(f"{ticker} (no data)")
```

> 주의: Step 3은 위 쿼리 블록만 교체한다. `if not rows:` 이후의 기존 본문(df 생성·렌더 반환)은 그대로 둔다 — 시그니처와 cur.execute 의 파라미터를 named params로 바꾸고 `date_filter` 를 끼우는 것이 변경의 전부.

- [ ] **Step 4: 통과 확인 + 회귀**

Run: `uv run pytest tests/test_api_chart_render.py -v`
Expected: 신규 PASS, 기존 PASS.

- [ ] **Step 5: 커밋**

```bash
git add api/services/chart_render.py tests/test_api_chart_render.py
git commit -m "feat(as-of): render_weekly_chart on_date 윈도잉"
```

---

### Task 6: build_analysis_zip 가 on_date 를 5개 빌더에 전달

**Files:**
- Modify: `api/services/zip_builder.py` (`build_analysis_zip` 내 5개 호출, 약 175-182행)
- Test: Task 7 의 통합 테스트로 검증 (이 Task는 배선만)

- [ ] **Step 1: 구현** — 5개 호출에 `on_date=on_date` 추가

기존:
```python
    daily_csv = build_daily_csv(conn, ticker, days=60)
    weekly_csv = build_weekly_csv(conn, ticker, weeks=104)
    index_code = INDEX_CODE_MAP.get(market, "1001")
    market_index_daily_csv = build_index_csv(conn, index_code, "daily", lookback=60)
    market_index_weekly_csv = build_index_csv(conn, index_code, "weekly", lookback=104)

    daily_chart_png = render_daily_chart(conn, ticker, range_days=365)
    weekly_chart_png = render_weekly_chart(conn, ticker, range_weeks=104)
```
변경:
```python
    daily_csv = build_daily_csv(conn, ticker, days=60, on_date=on_date)
    weekly_csv = build_weekly_csv(conn, ticker, weeks=104, on_date=on_date)
    index_code = INDEX_CODE_MAP.get(market, "1001")
    market_index_daily_csv = build_index_csv(conn, index_code, "daily", lookback=60, on_date=on_date)
    market_index_weekly_csv = build_index_csv(conn, index_code, "weekly", lookback=104, on_date=on_date)

    daily_chart_png = render_daily_chart(conn, ticker, range_days=365, on_date=on_date)
    weekly_chart_png = render_weekly_chart(conn, ticker, range_weeks=104, on_date=on_date)
```
(이 시점 `on_date` 는 함수 상단에서 `date.today()` 로 기본 설정돼 있어 항상 non-None — 라이브는 today, 백필은 as_of.)

- [ ] **Step 2: 회귀 확인 (배선만, 동작 변화 없어야 — 라이브 today 경로)**

Run: `uv run pytest tests/test_api_zip_builder.py -v`
Expected: 기존 통과분 유지 (사전 baseline 실패 `test_build_analysis_zip_contains_13_files` 는 무관, 늘지 않음).

- [ ] **Step 3: 커밋**

```bash
git add api/services/zip_builder.py
git commit -m "feat(as-of): build_analysis_zip 가 on_date 를 차트·CSV 빌더에 전달"
```

---

### Task 7: 통합 테스트 — ZIP 누수 없음

**Files:**
- Test: `tests/test_api_zip_builder.py`

- [ ] **Step 1: 통합 테스트 작성** — 파일 끝에 추가

on_date 이후의 가격/인덱스 행을 심고, `build_analysis_zip(on_date=과거)` ZIP의 CSV들에 on_date 이후 날짜가 없음을 단언.

```python
def test_build_analysis_zip_excludes_data_after_on_date(db):
    from datetime import date, timedelta
    import io, zipfile, csv as _csv
    from api.services.zip_builder import build_analysis_zip
    from api.services.market_context_builder import INDEX_CODE_MAP
    t = "ASOFZIP1"
    on_date = date(2025, 6, 10)
    market = "KOSPI"
    idx = INDEX_CODE_MAP.get(market, "1001")
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,'Z',%s) ON CONFLICT DO NOTHING", (t, market))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
        # on_date 전후로 일봉 (D1..D20: 6/1~6/20)
        for i in range(20):
            d = date(2025, 6, 1) + timedelta(days=i)
            cur.execute(
                """INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value)
                   VALUES (%s,%s,100,105,95,100,%s,1000,100000) ON CONFLICT DO NOTHING""",
                (t, d, 100 + i),
            )
        # 인덱스 일봉도 전후로
        for i in range(20):
            d = date(2025, 6, 1) + timedelta(days=i)
            cur.execute(
                """INSERT INTO index_daily (index_code, date, open, high, low, close, volume, value)
                   VALUES (%s,%s,10,11,9,10,1000,100000) ON CONFLICT DO NOTHING""",
                (idx, d),
            )
    db.commit()
    try:
        zip_bytes = build_analysis_zip(db, t, on_date=on_date)
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        for name in ("daily.csv", "market_index_daily.csv"):
            text = zf.read(name).decode("utf-8")
            rows = list(_csv.reader(io.StringIO(text)))
            dates = [r[0] for r in rows[1:] if r and r[0]]
            assert dates, f"{name}: 행이 있어야 함"
            assert max(dates) <= on_date.isoformat(), f"{name}: on_date 이후 데이터 누수 — max={max(dates)}"
            assert on_date.isoformat() in dates, f"{name}: on_date 당일 포함되어야"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (t,))
            cur.execute("DELETE FROM index_daily WHERE index_code=%s AND date >= '2025-06-01' AND date <= '2025-06-30'", (idx,))
        db.commit()
```

> 구현자 주의: `build_analysis_zip` 은 integrity_guard·payload 등 다른 입력도 만든다. 위 종목/날짜 시드로 예외(DataIntegrityError 등)가 나면, 예외 원인을 보고 최소 시드(daily_indicators 등)를 보강하되 **핵심 단언(누수 없음)은 유지**하라. index_daily 정리 시 다른 테스트 데이터를 지우지 않도록 날짜 범위로 한정했다.

- [ ] **Step 2: 통과 확인**

Run: `uv run pytest tests/test_api_zip_builder.py::test_build_analysis_zip_excludes_data_after_on_date -v`
Expected: PASS (on_date 이후 데이터가 ZIP에 없음).

- [ ] **Step 3: 변별 확인 (선택, 권장)** — Task 1·3의 필터를 임시로 제거하면 이 테스트가 FAIL함을 1회 확인 후 원복(커밋하지 말 것). 시간 없으면 생략 가능 — 단위 테스트들이 이미 각 필터를 변별함.

- [ ] **Step 4: 커밋**

```bash
git add tests/test_api_zip_builder.py
git commit -m "test(as-of): build_analysis_zip on_date 누수없음 통합 테스트"
```

---

### Task 8: 전체 회귀 + baseline 점검

**Files:** 없음 (검증만)

- [ ] **Step 1: 전체 테스트**

Run: `uv run pytest tests/ -q`
Expected: 신규 테스트 전부 PASS. 실패는 사전 baseline(~26 isolation fail) 이내 — 그 수가 늘지 않았는지 확인.

- [ ] **Step 2: 라이브 무변경 확인** — `build_analysis_zip` 을 `on_date` 없이 호출하는 경로(라이브 러너)가 그대로인지: `grep -rn "build_analysis_zip(conn, symbol)" kr_pipeline/` 로 호출부가 변경 없음을 확인(②는 배선 안 함, ③ 몫).

- [ ] **Step 3: 최종 커밋 체인 확인**

Run: `git log --oneline main..HEAD`
Expected: Task 1~7 커밋 존재.

---

## 자기 점검 결과 (작성자)

- **스펙 커버리지**: 5개 빌더 on_date = Task1~5, build_analysis_zip 결선 = Task6, 누수없음 통합 = Task7, 회귀/라이브불변 = Task8. 누락 없음.
- **placeholder**: 차트 테스트는 크기 비교(빈<채워짐)로 변별 — PNG 내용 검증 불가 제약을 우회한 구체 단언. weekly/index 시드의 NOT NULL 보강은 구현자 확인 지시(① 에서 검증된 패턴). 그 외 구체 코드.
- **타입 일관성**: 5개 함수 모두 `on_date: date | None = None`, named params 키(`on_date`/`ticker`/`days`/`weeks`/`lookback`/`range_days`/`range_weeks`/`code`) 일관. build_analysis_zip 호출 키워드 일치.
