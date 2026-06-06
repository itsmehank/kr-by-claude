# LLM 체인 가격 눈금 adjusted 통일 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM 분류→돌파→매수→성과 체인의 모든 가격을 adjusted 단일 눈금으로 통일한다(생산 측 입력을 adj 로 전환, raw 를 읽던 게이트를 adj 로 전환).

**Architecture:** 저장된 `adj_*` 컬럼을 읽기만(새 계산 0). 모든 전환점에 `COALESCE(adj_x, raw_x)` (adj_* 가 nullable). 생산 측 빌더는 `zip_builder` 가 weekend·daily_delta·backfill 셋에 공유하므로 한 번 고치면 전 진입점 커버.

**Tech Stack:** Python (psycopg3, pandas, matplotlib for PNG), pytest auto-rollback `db` 픽스처. 프롬프트는 `prompts/*.md`.

---

## 배경 / 스펙 근거

스펙: `docs/superpowers/specs/2026-06-06-llm-chain-adjusted-price-coherence-design.md`.

실측 확인(현재 코드):
- `payload_builder._fetch_daily_ohlcv`: `SELECT date, open, high, low, close, volume FROM daily_prices ... ORDER BY date DESC LIMIT %s`, dict 키 open/high/low/close/volume 로 반환(`reversed`). `_fetch_weekly_ohlcv`: `SELECT week_end_date, open, high, low, close, volume FROM weekly_prices ...`.
- `payload_lite.build_for_5b`: `SELECT date, open, high, low, close, volume FROM daily_prices ... LIMIT 20`. `build_for_6`: `SELECT i.adj_close, i.volume, i.avg_volume_50d, p.high, p.low, p.open, ... FROM daily_indicators i LEFT JOIN daily_prices p` → `current_state.intraday_high/low/open` = p.high/low/open (raw).
- `failed_breakout`: `SELECT date, close FROM daily_prices WHERE ticker=%s AND date>=%s AND date<%s`. 함수 `compute_failed_breakout(conn, symbol, classified_at_dt, pivot, base_start)`.
- `handle_quality`: `SELECT p.date, p.high, p.low, p.close, p.volume, i.sma_50, COALESCE(i.distribution_day_flag,FALSE) FROM daily_prices p LEFT JOIN daily_indicators i ...`. 함수 `compute_handle_quality(conn, symbol, classified_at, cls)`. 반환 `{fired, reasons, weights, metrics{handle_high, handle_low, ratio_a, ratio_b, ...}}`. `handle_low = min(raw low)`, `handle_high = cls["pivot_price"]`.
- `chart_render.render_daily_chart`/`render_weekly_chart`: 캔들 `df["open/high/low/close"]`(raw), 거래량 `df["volume"]`(raw), 마커 `low*0.99`/`high*1.01`. adj_close 는 SELECT 되나 미사용. SMA 등 오버레이는 daily_indicators(adj).
- 무변경(검증): `csv_builder`(adj_close only), `trigger_gate`(adj close), `evaluate_pivot`, `load.get_active_with_current`(`i.adj_close AS close`), `performance.py`(future=adj_close; 생산 측 전환 후 매수가도 adj → 눈금 정합).
- **adj_high/adj_low/adj_open/adj_volume 는 nullable**(close/adj_close 만 NOT NULL). COALESCE 필수. 기존 테스트 seed 들은 adj_high/low/volume 을 안 넣음(NULL) → COALESCE 가 raw 로 fallback 하므로 기존 테스트 동작 보존.
- 프롬프트 4개: `prompts/analyze_chart_v3.md`, `evaluate_pivot_trigger_v1.md`, `calculate_entry_params_v2_0.md`, `verify_analysis_v1.md`.

**비목표:** 기존 저장 행 마이그레이션, entry_price 출력-계약 버그(별도 후속), CSV/지수/웹차트/ChartMetaBar.

## 테스트 전략 (함정 회피)

최신일 adj≈raw 라 평범한 픽스처로는 안 드러남 → **분할 픽스처(raw≠adj)** 필수. 게이트(failed_breakout/handle_quality)는 **스케일 등가성**으로 검증: **raw 를 의미없는 garbage(real×배수)로, adj_* 에 실값**을 넣으면, adj 만 읽는 함수는 실값 기준 결과를 내야 한다(raw 를 읽으면 garbage 때문에 결과가 달라짐). 데이터 pass-through(payload/payload_lite)는 반환값이 adj 와 같고 raw 와 다른지 직접 단언.

---

### Task 1: payload_builder — daily/weekly OHLCV adj 전환

**Files:**
- Modify: `api/services/payload_builder.py` (`_fetch_daily_ohlcv`, `_fetch_weekly_ohlcv`)
- Test: `tests/test_api_payload_builder.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_api_payload_builder.py` 에 추가:

```python
def test_fetch_daily_ohlcv_uses_adjusted(db):
    from datetime import date
    from api.services.payload_builder import _fetch_daily_ohlcv
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('ADJD','t','KOSPI') ON CONFLICT DO NOTHING")
        # raw 와 adj 를 다르게: raw=10000대, adj=2000대 (분할)
        cur.execute("""INSERT INTO daily_prices
            (ticker,date,open,high,low,close,adj_close,adj_open,adj_high,adj_low,adj_volume,volume,value)
            VALUES ('ADJD',%s,10000,10500,9800,10000,2000,2000,2100,1960,500.0,1000,10000000)
            ON CONFLICT DO NOTHING""", (date(2026,1,2),))
    db.commit()
    out = _fetch_daily_ohlcv(db, "ADJD", date(2026,1,31), days=60)
    assert len(out) == 1
    bar = out[0]
    assert bar["open"] == 2000.0 and bar["high"] == 2100.0
    assert bar["low"] == 1960.0 and bar["close"] == 2000.0
    assert bar["volume"] == 500   # adj_volume (int 변환)


def test_fetch_weekly_ohlcv_uses_adjusted(db):
    from datetime import date
    from api.services.payload_builder import _fetch_weekly_ohlcv
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('ADJW','t','KOSPI') ON CONFLICT DO NOTHING")
        cur.execute("""INSERT INTO weekly_prices
            (ticker,week_end_date,open,high,low,close,adj_close,adj_open,adj_high,adj_low,adj_volume,volume,value,trading_days)
            VALUES ('ADJW',%s,10000,10500,9800,10000,2000,2000,2100,1960,500.0,1000,10000000,5)
            ON CONFLICT DO NOTHING""", (date(2026,1,2),))
    db.commit()
    out = _fetch_weekly_ohlcv(db, "ADJW", date(2026,1,31), weeks=104)
    assert out[0]["open"] == 2000.0 and out[0]["high"] == 2100.0
    assert out[0]["low"] == 1960.0 and out[0]["close"] == 2000.0
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_api_payload_builder.py -k adjusted -v` → FAIL (open==10000, raw 반환).

- [ ] **Step 3: 구현** — `_fetch_daily_ohlcv` 의 SELECT 를 교체:

```python
        cur.execute("""
            SELECT date,
                   COALESCE(adj_open,  open)   AS o,
                   COALESCE(adj_high,  high)   AS h,
                   COALESCE(adj_low,   low)    AS l,
                   COALESCE(adj_close, close)  AS c,
                   COALESCE(adj_volume,volume) AS v
              FROM daily_prices
             WHERE ticker = %s AND date <= %s
             ORDER BY date DESC LIMIT %s
        """, (ticker, on_date, days))
```

dict 빌드의 `int(r[5])` 는 adj_volume(float) 이므로 `int(round(r[5]))` 로(또는 `int(float(r[5]))`). `_fetch_weekly_ohlcv` 도 동일하게 `COALESCE(adj_*, raw)` 로 교체하고 `volume` 매핑은 `int(round(r[5])) if r[5] else None`.

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_api_payload_builder.py -v` → 신규 2 + 기존 전부 PASS (기존은 adj=raw fixture 라 불변).

- [ ] **Step 5: 커밋**

```bash
git add api/services/payload_builder.py tests/test_api_payload_builder.py
git commit -m "feat(llm): payload OHLCV(일/주봉) adjusted 전환 (COALESCE)"
```

---

### Task 2: payload_lite — build_for_5b / build_for_6 adj 전환

**Files:**
- Modify: `kr_pipeline/llm_runner/compute/payload_lite.py` (`build_for_5b`, `build_for_6`)
- Test: `tests/test_llm_compute_payload_lite.py`

- [ ] **Step 1: 실패 테스트 작성** — 기존 파일의 seed 헬퍼를 참고해, build_for_5b 의 `recent_daily_ohlcv_20d` 와 build_for_6 의 `current_state.intraday_*` 가 adj 값인지 검증하는 테스트 추가. 분할 행(raw≠adj)을 seed 하고:

```python
def test_build_for_5b_recent_ohlcv_adjusted(db, ...):  # 기존 픽스처/헬퍼 재사용
    # daily_prices 최근 행을 raw=10000, adj_*=2000 으로 seed + 활성 classification 필요
    ...
    payload = build_for_5b(db, symbol, as_of)
    last = payload["recent_daily_ohlcv_20d"][-1]
    assert last["high"] == 2100.0 and last["low"] == 1960.0 and last["close"] == 2000.0


def test_build_for_6_intraday_adjusted(db, ...):
    payload = build_for_6(db, symbol, evaluation_at)
    cs = payload["current_state"]
    assert cs["intraday_high"] == 2100.0 and cs["intraday_low"] == 1960.0 and cs["intraday_open"] == 2000.0
```

> 주의: build_for_5b/6 는 활성 `weekly_classification`·`trigger_evaluation_log` 행이 있어야 동작. 기존 `tests/test_llm_compute_payload_lite.py` 의 seed 함수를 그대로 재사용하되, daily_prices 의 최신 행만 adj_* 를 raw 와 다르게 덮어쓴다. 정확한 키/시드 형태는 기존 테스트에서 복사.

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_llm_compute_payload_lite.py -k adjusted -v` → FAIL (raw 값 반환).

- [ ] **Step 3: 구현**
- `build_for_5b` 의 `SELECT date, open, high, low, close, volume FROM daily_prices ... LIMIT 20` → `SELECT date, COALESCE(adj_open,open), COALESCE(adj_high,high), COALESCE(adj_low,low), COALESCE(adj_close,close), COALESCE(adj_volume,volume) FROM daily_prices ... LIMIT 20`. (ohlcv dict 매핑에서 volume 이 float 이면 `int(round(...))`)
- `build_for_6` 의 `p.high, p.low, p.open` → `COALESCE(p.adj_high,p.high), COALESCE(p.adj_low,p.low), COALESCE(p.adj_open,p.open)`. (close 는 이미 `i.adj_close`)

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_llm_compute_payload_lite.py -v` → 신규 + 기존 PASS.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/compute/payload_lite.py tests/test_llm_compute_payload_lite.py
git commit -m "feat(llm): payload_lite 5b OHLCV·6 intraday adjusted 전환"
```

---

### Task 3: chart_render — 캔들/거래량/마커 adj 전환

**Files:**
- Modify: `api/services/chart_render.py` (`render_daily_chart`, `render_weekly_chart`)
- Test: `tests/test_api_chart_render.py`

> PNG 픽셀 단언은 비실용적 → 분할종목 스모크(에러 없이 valid PNG) + 데이터 컬럼이 adj 로 바뀌었는지는 SELECT/df 레벨에서 보장. 캔들 가격 정합 자체의 값-정확성은 Task 1·2 의 동일 adj 컬럼 검증으로 커버됨.

- [ ] **Step 1: 실패/스모크 테스트 작성** — `tests/test_api_chart_render.py` 에 분할 픽스처 스모크 추가:

```python
def test_render_daily_chart_split_ticker_smoke(db):
    import io
    from datetime import date, timedelta
    from PIL import Image
    from api.services.chart_render import render_daily_chart
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('SPLT','t','KOSPI') ON CONFLICT DO NOTHING")
        d = date(2026,1,1)
        for i in range(60):
            if d.weekday() < 5:
                # raw 는 크게, adj 는 1/5 (분할)
                cur.execute("""INSERT INTO daily_prices
                    (ticker,date,open,high,low,close,adj_close,adj_open,adj_high,adj_low,adj_volume,volume,value)
                    VALUES ('SPLT',%s,10000,10500,9800,10000,2000,2000,2100,1960,500.0,1000,10000000)
                    ON CONFLICT DO NOTHING""", (d,))
                cur.execute("""INSERT INTO daily_indicators (ticker,date,adj_close,sma_50)
                    VALUES ('SPLT',%s,2000,1950) ON CONFLICT DO NOTHING""", (d,))
            d += timedelta(days=1)
    db.commit()
    png = render_daily_chart(db, "SPLT", range_days=60)
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG" and img.width > 0
```

- [ ] **Step 2: 실패/베이스라인 확인** — `uv run pytest tests/test_api_chart_render.py -k split -v` → 현 코드로도 PASS(스모크)하지만, 구현 전엔 캔들이 raw(10000대)로 그려짐. 이 테스트는 회귀 안전망(전환 후에도 크래시 없음). 값 전환은 Step 3 후 코드 리뷰로 확인.

- [ ] **Step 3: 구현** — `render_daily_chart`/`render_weekly_chart` 의 가격 데이터 로딩 SELECT 에서 캔들에 쓰는 `open/high/low/close` 와 `volume` 을 `COALESCE(adj_open,open)`…`COALESCE(adj_volume,volume)` 로 교체(별칭은 기존 df 컬럼명 `open/high/low/close/volume` 유지 → 그리기 코드 무변경). 마커(`low*0.99`/`high*1.01`)는 df 의 (이제 adj) low/high 를 그대로 써서 자동 정합. SMA 등 오버레이는 daily_indicators(이미 adj) — 무변경.

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_api_chart_render.py -v` → 신규 스모크 + 기존(adj=raw) PASS. 구현자는 diff 에서 캔들 SELECT 가 adj 컬럼(별칭 유지)을 쓰는지 자체 확인.

- [ ] **Step 5: 커밋**

```bash
git add api/services/chart_render.py tests/test_api_chart_render.py
git commit -m "feat(llm): chart_render 캔들/거래량/마커 adjusted 전환 (LLM PNG 정합)"
```

---

### Task 4: failed_breakout — adj_close 전환

**Files:**
- Modify: `kr_pipeline/llm_runner/compute/failed_breakout.py`
- Test: `tests/test_compute_failed_breakout.py`

- [ ] **Step 1: 실패 테스트 작성(스케일 등가성)** — `tests/test_compute_failed_breakout.py` 에 추가. raw close 는 pivot 위 garbage, adj_close 는 발화 패턴:

```python
def test_failed_breakout_uses_adjusted_close(db):
    from datetime import date, datetime, timezone
    from kr_pipeline.llm_runner.compute.failed_breakout import compute_failed_breakout
    start = date(2026, 4, 6)
    pivot = 100.0
    # adj_close = [101,98,97,102,103,104] (P1 발화), raw close = 전부 700+ (pivot 위 garbage)
    adj = [101, 98, 97, 102, 103, 104]
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES ('FBADJ','t','KOSPI') ON CONFLICT DO NOTHING")
        d = start
        for a in adj:
            raw = a * 7  # garbage, 전부 pivot 위
            cur.execute("""INSERT INTO daily_prices (ticker,date,open,high,low,close,adj_close,volume,value)
                VALUES ('FBADJ',%s,%s,%s,%s,%s,%s,1000,1000000) ON CONFLICT DO NOTHING""",
                (d, raw, raw, raw, raw, a))
            d += __import__("datetime").timedelta(days=1)
    db.commit()
    r = compute_failed_breakout(db, "FBADJ", datetime(2026,4,16,tzinfo=timezone.utc), pivot, start)
    # adj_close 를 읽으면 발화(raw 였다면 전부 pivot 위라 미발화)
    assert r is not None and r["fired"]
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_compute_failed_breakout.py::test_failed_breakout_uses_adjusted_close -v` → FAIL (raw close=700+ 읽어 미발화 → r None 또는 fired False).

- [ ] **Step 3: 구현** — SELECT 교체:

```python
            SELECT date, COALESCE(adj_close, close) FROM daily_prices
             WHERE ticker = %s AND date >= %s AND date < %s
             ORDER BY date
```

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_compute_failed_breakout.py -v` → 신규 + 기존 PASS (기존 seed 는 adj_close=close 라 불변).

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/compute/failed_breakout.py tests/test_compute_failed_breakout.py
git commit -m "feat(llm): failed_breakout adj_close 비교 전환"
```

---

### Task 5: handle_quality — high/low/close/volume 4컬럼 adj 전환

**Files:**
- Modify: `kr_pipeline/llm_runner/compute/handle_quality.py`
- Test: `tests/test_compute_handle_quality.py`

- [ ] **Step 1: 실패 테스트 작성(스케일 등가성)** — 기존 `_seed_ohlcv`/`_cup`/`_cls` 헬퍼 재사용. 발화 픽스처(`test_deep_handle_fires` 와 동일 구조)를 만들되, **raw high/low/close/volume 을 garbage(×7)로, adj_high/adj_low/adj_close/adj_volume 에 실값**을 넣는 seed 헬퍼를 추가:

```python
def _seed_ohlcv_adj(db, ticker, start, bars):
    """raw 는 garbage(×7), adj_* 에 실값. adj 만 읽으면 _seed_ohlcv 와 동일 결과."""
    from datetime import timedelta
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker,name,market) VALUES (%s,%s,'KOSPI') ON CONFLICT DO NOTHING",(ticker,ticker))
        d = start
        for (high, low, close, vol, dist) in bars:
            cur.execute("""INSERT INTO daily_prices
                (ticker,date,open,high,low,close,adj_close,adj_open,adj_high,adj_low,adj_volume,volume,value)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (ticker,d, close*7, high*7, low*7, close*7, close, close, high, low, float(vol), vol*7, vol*close*7))
            cur.execute("""INSERT INTO daily_indicators (ticker,date,adj_close,sma_50,distribution_day_flag)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",(ticker,d,close,close*0.95,dist))
            d += timedelta(days=1)


def test_handle_quality_uses_adjusted(db):
    from datetime import date, datetime, timezone
    from kr_pipeline.llm_runner.compute.handle_quality import compute_handle_quality
    start = date(2026, 5, 4)
    handle = [(99,85,86,700,False),(97,82,84,600,False),(98,90,96,700,False)]
    _seed_ohlcv_adj(db, "HQADJ", start, _cup(1000) + handle)
    cls = _cls(base_depth=30.0, base_start=start, classified_at=datetime(2026,5,22,tzinfo=timezone.utc))
    r = compute_handle_quality(db, "HQADJ", cls["classified_at"], cls)
    # adj high/low 를 읽으면 deep_handle 발화 + handle_low==82 (raw=574 였다면 구조·발화가 깨짐)
    assert r is not None and r["fired"]
    assert r["metrics"]["handle_low"] == 82.0
    assert "deep_handle" in r["reasons"]
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_compute_handle_quality.py::test_handle_quality_uses_adjusted -v` → FAIL (raw high/low=×7 읽어 handle_low≠82, 구조 깨져 미발화/오값).

- [ ] **Step 3: 구현** — SELECT 의 4개 raw 컬럼을 COALESCE adj 로:

```python
            SELECT p.date,
                   COALESCE(p.adj_high,  p.high)   AS high,
                   COALESCE(p.adj_low,   p.low)    AS low,
                   COALESCE(p.adj_close, p.close)  AS close,
                   COALESCE(p.adj_volume,p.volume) AS volume,
                   i.sma_50, COALESCE(i.distribution_day_flag, FALSE)
              FROM daily_prices p
              LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = %s AND p.date >= %s AND p.date < %s
             ORDER BY p.date
```

(컬럼 순서/인덱스 동일 유지: rows[idx][1]=high, [2]=low, [3]=close, [4]=volume — 기존 인덱싱 코드 무변경.)

- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_compute_handle_quality.py -v` → 신규 + 기존 PASS (기존 `_seed_ohlcv` 는 adj_high/low/volume NULL → COALESCE 가 raw 로 fallback 하여 불변).

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/compute/handle_quality.py tests/test_compute_handle_quality.py
git commit -m "feat(llm): handle_quality high/low/close/volume adjusted 전환 (4컬럼)"
```

---

### Task 6: 프롬프트 4개 adjusted 명시 + 소비 측 무변경 검증

**Files:**
- Modify: `prompts/analyze_chart_v3.md`, `prompts/evaluate_pivot_trigger_v1.md`, `prompts/calculate_entry_params_v2_0.md`, `prompts/verify_analysis_v1.md`
- Test: 없음(프롬프트 텍스트) + 검증 명령

- [ ] **Step 1: 4개 프롬프트에 명시 한 줄 추가** — 각 프롬프트의 입력 데이터 설명 섹션(또는 상단)에 다음 한 줄을 추가(한국어 프롬프트 톤 유지):

```
**가격 데이터 규약:** 제공되는 모든 가격(OHLCV·차트·지표·current_metrics)은 수정주가(split-adjusted) 기준입니다. 분할/액면병합은 이미 반영되어 있으므로 가격 단차로 오인하지 마세요.
```

`analyze_chart_v3.md` 의 기존 line 60 ("adjusted prices being used") 은 이제 사실이므로 유지(중복되면 위 한 줄로 통합 가능). 출력 스키마는 건드리지 않는다(entry_price 계약은 비목표).

- [ ] **Step 2: 소비 측 무변경 검증(읽기만)** — 다음이 이미 adj 임을 grep 으로 재확인(코드 변경 없음):

```bash
grep -n "adj_close AS close\|i.adj_close" kr_pipeline/llm_runner/load.py
grep -n "adj_close" kr_pipeline/llm_runner/performance.py
```
Expected: `load.get_active_with_current` 가 `i.adj_close AS close`, `performance.py` future 가 `adj_close`. → trigger_gate/performance 무변경 정당화 기록.

- [ ] **Step 3: 커밋**

```bash
git add prompts/analyze_chart_v3.md prompts/evaluate_pivot_trigger_v1.md prompts/calculate_entry_params_v2_0.md prompts/verify_analysis_v1.md
git commit -m "docs(prompts): 가격은 수정주가 기준 명시 (4개 프롬프트)"
```

---

### Task 7: 회귀 + 범위 무영향 + performance 눈금 검증

**Files:** 없음(검증) + performance 테스트 1개

- [ ] **Step 1: performance 눈금 정합 테스트** — `tests/test_llm_performance.py` 에 adj 매수가 vs adj 미래가 수익률 정확성 테스트 추가(분할 무관 단순 케이스로 눈금 일치 확인):

```python
def test_performance_return_uses_adjusted_consistently(db):
    """entry_price(adj) vs future adj_close → 수익률 정확. (눈금 정합 검증)"""
    # 기존 test_llm_performance.py 의 seed 패턴 재사용: signal_performance 행 + 미래 daily_prices.adj_close.
    # entry_price=2000(adj), 미래 adj_close=2200 → return_1w_pct == 10.0
    ...  # 기존 테스트 헬퍼로 seed, run 후 return_*_pct == (2200-2000)/2000*100 == 10.0 단언
```

> 기존 `tests/test_llm_performance.py` 구조를 따라 작성. 핵심 단언: 미래가/매수가가 같은 adj 눈금이면 분할 없는 케이스에서 수익률이 산술적으로 정확.

- [ ] **Step 2: 변경영역 + 인접 테스트**

```bash
uv run pytest tests/test_api_payload_builder.py tests/test_llm_compute_payload_lite.py \
  tests/test_api_chart_render.py tests/test_compute_failed_breakout.py \
  tests/test_compute_handle_quality.py tests/test_llm_performance.py tests/test_api_csv_builder.py -v
```
Expected: 신규 + 기존 전부 PASS. csv_builder(무변경) 통과로 범위 밖 무영향 확인.

- [ ] **Step 3: 전체 회귀 base 대비**

```bash
uv run pytest tests/ -q 2>&1 | grep "^FAILED" | sed 's/ -.*//' | sort > /tmp/llmadj_head.txt
wc -l < /tmp/llmadj_head.txt
```
Expected: 현재 main 사전 실패 수(~26)와 동일 — 신규 회귀 0. 다르면 base 와 `comm -23` 로 신규 실패 식별 후 수정.

- [ ] **Step 4: 최종 커밋(있으면)**

```bash
git add tests/test_llm_performance.py
git commit -m "test(llm): performance adjusted 눈금 정합 검증"
```

---

## Self-Review

**1. Spec coverage:**
- 생산 측 payload OHLCV adj: Task 1 ✓; payload_lite 5b/6: Task 2 ✓; chart_render: Task 3 ✓
- 프롬프트 4개 명시: Task 6 ✓
- 소비 측 게이트: failed_breakout Task 4 ✓, handle_quality 4컬럼 Task 5 ✓
- 무변경 검증(trigger_gate/performance/load/csv): Task 6 Step 2 + Task 7 ✓
- performance 눈금 정합: Task 7 Step 1 ✓
- COALESCE(nullable) 전 전환점 적용: Task 1~5 모든 SELECT ✓
- 분할 픽스처/스케일 등가성 테스트: Task 1·2(값), 4·5(등가성) ✓
- 마이그레이션/entry_price 비목표: 계획에 미포함(정합) ✓
- 회귀 0: Task 7 ✓

**2. Placeholder scan:** Task 2·7 의 일부 테스트는 "기존 헬퍼 재사용" 으로 시드 세부를 위임(build_for_5b/6·performance 는 활성 classification/trigger/performance 행 등 사전 상태가 많아 기존 테스트 픽스처 복사가 정확). 그 외 Task 1·3·4·5 는 완전한 시드+단언 코드 제공. → Task 2·7 구현자는 해당 기존 테스트 파일의 seed 패턴을 복사해 분할 행만 덮어쓸 것(파일·함수 명시됨).

**3. Type consistency:** COALESCE 별칭으로 df/튜플 인덱스·dict 키 불변(handle_quality rows[idx] 순서 유지, payload dict 키 open/high/low/close/volume 유지). adj_volume float → payload `int(round())`, performance/게이트는 비교만이라 무관.

**알려진 한계(의도적):** 기존 저장 행(raw 피벗) 미변경 → 옛 활성 신호는 수명 내 분할 시 일시 불일치(스펙 결정). entry_price 출력-계약 버그는 별도 후속.
