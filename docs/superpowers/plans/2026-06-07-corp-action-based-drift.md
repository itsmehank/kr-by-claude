# 공시기반 drift 감지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** drift 감지를 "매 평일 전 종목 KRX 재조회"에서 "평일=corporate_actions 최근 공시 후보만 / 토요일=전 종목 전체스윕(넓은 비교창)"으로 바꾸고, 공시 수집을 평일 매일로 옮긴다.

**Architecture:** `is_drift`·`reload_ticker` 판정/재적재 로직은 그대로 두고 (1) `detect_drifted_tickers` 에 검사 대상 `tickers` 인자 추가, (2) `recent_corp_action_tickers` 후보 쿼리 추가, (3) `run_daily_chain` 은 후보만, `run_weekly_chain` 은 전 종목 전체스윕(비교창 90일), (4) `corporate-actions` cron 을 평일 아침으로 변경. 기존 ohlcv/weekly/indicators/corporate_actions 모듈 내부는 무수정.

**Tech Stack:** Python, psycopg(raw SQL), pytest + pytest-mock(mocker), pandas. DB 테스트는 `db` 픽스처(트랜잭션→rollback 격리, `TEST_DATABASE_URL`).

**설계 스펙:** `docs/superpowers/specs/2026-06-07-corp-action-based-drift-design.md`

---

## File Structure

- `kr_pipeline/pipeline/drift.py` — 후보 쿼리(`recent_corp_action_tickers`), 영향 이벤트 상수, 운영 상수(`CA_LOOKBACK_DAYS`/`SWEEP_RECENT_DAYS`), `detect_drifted_tickers(tickers=...)`. **이 작업의 핵심.**
- `kr_pipeline/pipeline/chains.py` — 평일 후보 배선, 토요일 전체스윕 단계.
- `kr_pipeline/pipeline/__main__.py` — `--no-sweep` 플래그.
- `kr_pipeline/llm_runner/pipeline_specs.py` — `corporate-actions` cron/label/long_description.
- 테스트: `tests/test_pipeline_drift.py`, `tests/test_pipeline_chains.py`, `tests/test_pipeline_specs.py` (모두 기존 파일 갱신).

**기존 동작 보존 주의:** `detect_drifted_tickers` 의 `tickers=None` 은 기존대로 전 종목, `tickers=[]` 는 "검사 0건"(전 종목 아님). 이 구분이 깨지면 평일 후보 0인 날 전 종목을 다시 긁는 버그가 된다.

---

## Task 1: `detect_drifted_tickers` 에 검사 대상 `tickers` 인자 추가

**Files:**
- Modify: `kr_pipeline/pipeline/drift.py` (`detect_drifted_tickers`)
- Test: `tests/test_pipeline_drift.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_pipeline_drift.py` 맨 아래에 추가

```python
def test_detect_drifted_tickers_uses_given_tickers(mocker):
    """tickers 인자가 주어지면 _active_tickers 대신 그 목록만 검사."""
    import kr_pipeline.pipeline.drift as d

    active = mocker.patch.object(d, "_active_tickers")
    mocker.patch.object(d, "_db_adj_close", return_value={date(2024, 1, 2): 50000.0})
    mocker.patch.object(d, "_krx_adj_close", return_value={date(2024, 1, 2): 10000.0})

    out = d.detect_drifted_tickers(conn=None, as_of=date(2024, 1, 10),
                                   rel_tol=0.01, tickers=["AAA"])
    assert out == ["AAA"]
    active.assert_not_called()


def test_detect_drifted_tickers_empty_list_checks_nothing(mocker):
    """tickers=[] 는 '검사 0건' — _active_tickers/_krx 호출 없이 빈 리스트."""
    import kr_pipeline.pipeline.drift as d

    active = mocker.patch.object(d, "_active_tickers")
    krx = mocker.patch.object(d, "_krx_adj_close")

    out = d.detect_drifted_tickers(conn=None, as_of=date(2024, 1, 10),
                                   rel_tol=0.01, tickers=[])
    assert out == []
    active.assert_not_called()
    krx.assert_not_called()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_drift.py::test_detect_drifted_tickers_empty_list_checks_nothing tests/test_pipeline_drift.py::test_detect_drifted_tickers_uses_given_tickers -v`
Expected: FAIL — `TypeError: detect_drifted_tickers() got an unexpected keyword argument 'tickers'`

- [ ] **Step 3: 구현** — `detect_drifted_tickers` 시그니처와 스캔 대상 선정부 교체

기존:
```python
def detect_drifted_tickers(
    conn: Connection,
    *,
    as_of: date,
    rel_tol: float = 0.01,
    recent_days: int = 30,
    wide_days: int = 365,
    limit_tickers: int | None = None,
) -> list[str]:
```
교체 후 (시그니처에 `tickers` 추가 + 루프 시작부 변경):
```python
def detect_drifted_tickers(
    conn: Connection,
    *,
    as_of: date,
    rel_tol: float = 0.01,
    recent_days: int = 30,
    wide_days: int = 365,
    tickers: list[str] | None = None,
    limit_tickers: int | None = None,
) -> list[str]:
    """활성 종목별 DB(현재, 덮어쓰기 전) vs KRX 재조회 adj_close 비교 → 드리프트 종목.

    tickers=None 이면 활성 전 종목(전체스윕). tickers 가 리스트면 그 목록만 검사
    (빈 리스트 = 검사 0건, 전 종목 아님). 반드시 ohlcv 증분 적재 전에 호출.
    종목별 fetch 예외는 로그+skip.
    """
    if tickers is None:
        scan = _active_tickers(conn, limit=limit_tickers)
    else:
        scan = list(tickers[:limit_tickers]) if limit_tickers else list(tickers)
    drifted: list[str] = []
    for t in scan:
```
(루프 본문 `try:` 이하 ~ `return drifted` 는 그대로 둔다. 기존 `for t in _active_tickers(conn, limit=limit_tickers):` 줄만 위 `for t in scan:` 로 바뀐다.)

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_pipeline_drift.py -v`
Expected: PASS (신규 2개 + 기존 전부; 기존 `test_detect_drifted_tickers_flags_split` 등은 `tickers` 생략→None→`_active_tickers` 경로라 그대로 통과)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/pipeline/drift.py tests/test_pipeline_drift.py
git commit -m "feat(drift): detect_drifted_tickers 에 검사 대상 tickers 인자 추가"
```

---

## Task 2: 영향 이벤트 상수 + `recent_corp_action_tickers` 후보 쿼리

**Files:**
- Modify: `kr_pipeline/pipeline/drift.py` (상수 + 신규 함수)
- Test: `tests/test_pipeline_drift.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_pipeline_drift.py` 에 추가 (파일 상단 `from datetime import date` 는 이미 있음; `timedelta` 는 테스트 내 import)

```python
def test_recent_corp_action_tickers_filters(db):
    """영향 이벤트·창 내·활성 종목만 distinct 반환. 비영향/창밖/상폐 제외."""
    from datetime import timedelta
    from kr_pipeline.pipeline.drift import recent_corp_action_tickers

    as_of = date(2026, 6, 1)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker,name,market) VALUES "
            "('AAA','a','KOSPI'),('BBB','b','KOSPI'),('DEL','d','KOSPI')"
        )
        cur.execute("UPDATE stocks SET delisted_at=%s WHERE ticker='DEL'", (as_of,))
        cur.execute(
            "INSERT INTO corporate_actions (ticker,event_date,event_type,dart_rcept_no) VALUES "
            "('AAA',%s,'rights_offering','r1'),"   # 창 내·영향 → 포함
            "('AAA',%s,'bonus_issue','r2'),"       # 창 내·영향(중복 종목) → distinct 로 1회
            "('AAA',%s,'rights_offering','r3'),"   # 창 밖(200일 전) → 제외
            "('BBB',%s,'cash_dividend','r4'),"     # 창 내지만 비영향 → 제외
            "('DEL',%s,'bonus_issue','r5')",       # 창 내·영향이나 상폐 → 제외
            (as_of - timedelta(days=10), as_of - timedelta(days=20),
             as_of - timedelta(days=200), as_of - timedelta(days=5),
             as_of - timedelta(days=3)),
        )
    out = recent_corp_action_tickers(db, as_of=as_of, lookback_days=90)
    assert out == ["AAA"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_drift.py::test_recent_corp_action_tickers_filters -v`
Expected: FAIL — `ImportError: cannot import name 'recent_corp_action_tickers'` (또는 `TEST_DATABASE_URL not set` 으로 skip 시 환경변수 먼저 세팅)

- [ ] **Step 3: 구현** — `drift.py` 의 `log = logging.getLogger(...)` 줄 바로 아래에 상수, `_active_tickers` 함수 위에 신규 함수 추가

```python
# 수정주가를 바꾸는 corporate action 유형 (현금배당 제외 — 수정주가 무관).
# 목록이 넉넉해도 안전: 실제 재적재 판정은 is_drift(가격 대조)가 한다.
ADJ_AFFECTING_EVENT_TYPES = (
    "stock_split", "reverse_split", "bonus_issue", "rights_offering",
    "merger", "spinoff", "capital_reduction",
)

CA_LOOKBACK_DAYS = 90   # 평일 후보: 최근 N일 공시. 결정→권리락 간격(수 주) 흡수.
SWEEP_RECENT_DAYS = 90  # 토요일 스윕 비교창. ohlcv window_days(30)보다 커야
                        # 증분이 덮은 최근 구간 너머 옛 구간에서 놓친 split 을 잡는다.


def recent_corp_action_tickers(conn: Connection, *, as_of: date, lookback_days: int) -> list[str]:
    """corporate_actions 에 [as_of-lookback, as_of] 영향 이벤트가 있는 활성 종목(distinct).

    event_type 가 ADJ_AFFECTING_EVENT_TYPES 이고 상장 유지(delisted_at IS NULL)인 종목만.
    인덱스 idx_corp_actions_event_type_date(event_type, event_date) 활용.
    """
    since = as_of - timedelta(days=lookback_days)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ca.ticker FROM corporate_actions ca "
            "JOIN stocks s ON s.ticker = ca.ticker "
            "WHERE ca.event_type = ANY(%s) AND ca.event_date >= %s "
            "AND s.delisted_at IS NULL "
            "ORDER BY ca.ticker",
            (list(ADJ_AFFECTING_EVENT_TYPES), since),
        )
        return [r[0] for r in cur.fetchall()]
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_pipeline_drift.py::test_recent_corp_action_tickers_filters -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/pipeline/drift.py tests/test_pipeline_drift.py
git commit -m "feat(drift): 공시 후보 쿼리 recent_corp_action_tickers + 영향 이벤트/운영 상수"
```

---

## Task 3: `run_daily_chain` — 평일 drift 를 공시 후보로 한정

**Files:**
- Modify: `kr_pipeline/pipeline/chains.py` (`run_daily_chain`)
- Test: `tests/test_pipeline_chains.py`

- [ ] **Step 1: 기존 테스트 갱신 + 신규 테스트** — `tests/test_pipeline_chains.py`

(1) 기존 `test_run_daily_chain_detects_before_ohlcv_then_reloads` 함수 본문 시작에 `recent_corp_action_tickers` 패치 한 줄 추가:
```python
def test_run_daily_chain_detects_before_ohlcv_then_reloads(mocker):
    """순서: detect(증분 전) → ohlcv 증분 → reload(감지분) → indicators 증분."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "recent_corp_action_tickers", return_value=["AAA"])
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
```

(2) 기존 `test_run_daily_chain_reload_failure_isolated` 함수 본문에 `recent_corp_action_tickers` 패치 추가 (detect 패치 줄 위에):
```python
    mocker.patch.object(ch.drift, "recent_corp_action_tickers", return_value=["AAA", "BBB"])
    mocker.patch.object(ch.drift, "detect_drifted_tickers", side_effect=lambda *a, **k: ["AAA", "BBB"])
```

(3) 신규 테스트 추가 (후보가 detect 로 전달되는지):
```python
def test_run_daily_chain_passes_corp_action_candidates(mocker):
    """detect 가 recent_corp_action_tickers 의 후보 목록을 tickers 로 받아 호출된다."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    mocker.patch.object(ch.drift, "recent_corp_action_tickers", return_value=["AAA", "BBB"])
    det = mocker.patch.object(ch.drift, "detect_drifted_tickers", return_value=[])
    mocker.patch.object(ch.ohlcv, "run", side_effect=lambda *a, **k: _Stats())
    mocker.patch.object(ch.indicators, "run_daily", side_effect=lambda *a, **k: _Stats())

    ch.run_daily_chain(conn=None)
    assert det.call_args.kwargs["tickers"] == ["AAA", "BBB"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_chains.py::test_run_daily_chain_passes_corp_action_candidates -v`
Expected: FAIL — `AttributeError: <module 'kr_pipeline.pipeline.drift'> does not have the attribute 'recent_corp_action_tickers'` 면 Task 2 미적용; Task 2 적용 상태라면 `KeyError: 'tickers'` (detect 가 tickers 없이 호출됨)

- [ ] **Step 3: 구현** — `run_daily_chain` 의 drift 감지 블록 교체

기존:
```python
        drifted: list[str] = []
        if drift_check:
            drifted = drift.detect_drifted_tickers(conn, as_of=as_of, limit_tickers=limit_tickers)
```
교체 후:
```python
        drifted: list[str] = []
        if drift_check:
            candidates = drift.recent_corp_action_tickers(
                conn, as_of=as_of, lookback_days=drift.CA_LOOKBACK_DAYS)
            drifted = drift.detect_drifted_tickers(
                conn, as_of=as_of, tickers=candidates, limit_tickers=limit_tickers)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_pipeline_chains.py -v`
Expected: PASS (신규 + 갱신 + 기존 전부. `drift_check=False` 테스트는 후보 쿼리 미호출 경로라 영향 없음)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/pipeline/chains.py tests/test_pipeline_chains.py
git commit -m "feat(drift): 평일 체인 drift 를 공시 후보(recent_corp_action_tickers)로 한정"
```

---

## Task 4: `run_weekly_chain` — 토요일 전체스윕 백업 단계

**Files:**
- Modify: `kr_pipeline/pipeline/chains.py` (`run_weekly_chain`)
- Test: `tests/test_pipeline_chains.py`

- [ ] **Step 1: 기존 테스트 갱신 + 신규** — `tests/test_pipeline_chains.py`

(1) 기존 `test_run_weekly_chain_calls_weekly_then_indicators_in_order` 를 아래로 교체 (full_sweep=False 로 호출, sweep 키 포함한 details 검증):
```python
def test_run_weekly_chain_calls_weekly_then_indicators_in_order(mocker):
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.weekly, "run", side_effect=lambda *a, **k: calls.append("weekly") or _Stats())
    mocker.patch.object(ch.indicators, "run_weekly", side_effect=lambda *a, **k: calls.append("ind_weekly") or _Stats())
    ch.run_weekly_chain(conn=None, full_sweep=False)
    assert calls == ["weekly", "ind_weekly"]
    assert fake.kwargs["pipeline"] == "data_weekly"
    assert state["details"] == {
        "sweep": {"detected": 0, "reloaded": 0, "failures": 0},
        "weekly": {"rows": 0, "failures": 0},
        "indicators_weekly": {"rows": 0, "failures": 0},
    }
```

(2) 신규 테스트 2개:
```python
def test_run_weekly_chain_full_sweep_reloads_before_weekly(mocker):
    """full_sweep: 전 종목(tickers=None) detect+reload 가 weekly 단계 '전'에 90일 창으로 실행."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "detect_drifted_tickers",
                        side_effect=lambda *a, **k: calls.append(("detect", k.get("tickers"), k.get("recent_days"))) or ["AAA"])
    mocker.patch.object(ch.drift, "reload_ticker",
                        side_effect=lambda *a, **k: calls.append("reload") or {"ticker": "AAA"})
    mocker.patch.object(ch.weekly, "run", side_effect=lambda *a, **k: calls.append("weekly") or _Stats())
    mocker.patch.object(ch.indicators, "run_weekly", side_effect=lambda *a, **k: calls.append("ind_weekly") or _Stats())

    ch.run_weekly_chain(conn=None)
    assert [c[0] if isinstance(c, tuple) else c for c in calls] == ["detect", "reload", "weekly", "ind_weekly"]
    assert calls[0][1] is None    # tickers=None → 전 종목
    assert calls[0][2] == 90      # SWEEP_RECENT_DAYS
    assert state["details"]["sweep"] == {"detected": 1, "reloaded": 1, "failures": 0}


def test_run_weekly_chain_sweep_reload_failure_isolated(mocker):
    """스윕 reload 실패는 rollback+계속, weekly/indicators 는 그대로."""
    import kr_pipeline.pipeline.chains as ch

    state, fake = _fake_run_tracking(mocker, ch)
    calls = []
    mocker.patch.object(ch.drift, "detect_drifted_tickers", side_effect=lambda *a, **k: ["AAA", "BBB"])
    def boom(conn, t, **k):
        if t == "AAA":
            raise RuntimeError("reload fail")
        return {"ticker": t}
    mocker.patch.object(ch.drift, "reload_ticker", side_effect=boom)
    mocker.patch.object(ch.weekly, "run", side_effect=lambda *a, **k: calls.append("weekly") or _Stats())
    mocker.patch.object(ch.indicators, "run_weekly", side_effect=lambda *a, **k: calls.append("ind_weekly") or _Stats())
    rb = mocker.patch.object(ch, "_rollback", side_effect=lambda conn: None)

    ch.run_weekly_chain(conn=None)
    assert calls == ["weekly", "ind_weekly"]
    assert state["details"]["sweep"] == {"detected": 2, "reloaded": 1, "failures": 1}
    rb.assert_called_once()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_chains.py::test_run_weekly_chain_full_sweep_reloads_before_weekly -v`
Expected: FAIL — `TypeError: run_weekly_chain() got an unexpected keyword argument 'full_sweep'`

- [ ] **Step 3: 구현** — `run_weekly_chain` 전체 교체

기존 `run_weekly_chain` 함수를 아래로 교체:
```python
def run_weekly_chain(conn: Connection, *, limit_tickers: int | None = None, full_sweep: bool = True) -> dict:
    """토요일 통합: (전체스윕 drift) → weekly 증분 → indicators 주봉 증분.

    full_sweep: corporate_actions 가 놓친 드리프트를 잡는 안전망. 전 종목을 넓은
    비교창(SWEEP_RECENT_DAYS)으로 검사 — 평일 증분이 덮은 최근 구간 너머 옛 구간에서
    놓친 split 을 포착. 종목 단위 예외 격리(평일 체인과 동일). 통합 자체를
    pipeline="data_weekly" 로 추적.
    """
    with run_tracking(conn, pipeline="data_weekly", mode="incremental",
                      params={"limit_tickers": limit_tickers, "full_sweep": full_sweep}) as state:
        as_of = date.today()
        swept: list[str] = []
        sweep_reloaded, sweep_failures = 0, 0
        if full_sweep:
            swept = drift.detect_drifted_tickers(
                conn, as_of=as_of, tickers=None,
                recent_days=drift.SWEEP_RECENT_DAYS, limit_tickers=limit_tickers)
            for t in swept:
                try:
                    drift.reload_ticker(conn, t, as_of=as_of)
                    sweep_reloaded += 1
                except Exception as e:  # noqa: BLE001 — 종목 단위 격리
                    sweep_failures += 1
                    _rollback(conn)
                    log.warning("weekly sweep reload failed %s: %s", t, e)

        r_price = weekly.run(conn, weekly.Mode.INCREMENTAL, limit_tickers=limit_tickers)
        r_ind = indicators.run_weekly(conn, indicators.Mode.INCREMENTAL, limit_tickers=limit_tickers)
        result = {
            "sweep": {"detected": len(swept), "reloaded": sweep_reloaded, "failures": sweep_failures},
            "weekly": {"rows": r_price.rows_affected, "failures": len(r_price.failures)},
            "indicators_weekly": {"rows": r_ind.rows_affected, "failures": len(r_ind.failures)},
        }
        state["rows_affected"] = (r_price.rows_affected or 0) + (r_ind.rows_affected or 0)
        state["details"] = result
        return result
```
(참고: `drift`·`date`·`_rollback`·`run_tracking` 은 `chains.py` 에 이미 import/정의되어 있음.)

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_pipeline_chains.py -v`
Expected: PASS (신규 2 + 갱신 1 + 기존 전부)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/pipeline/chains.py tests/test_pipeline_chains.py
git commit -m "feat(drift): 토요일 weekly 체인에 전 종목 전체스윕(비교창 90일) 백업 추가"
```

---

## Task 5: `__main__.py` — `--no-sweep` 플래그

**Files:**
- Modify: `kr_pipeline/pipeline/__main__.py`
- Test: `tests/test_pipeline_chains.py` (CLI 배선 검증)

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_pipeline_chains.py` 에 추가

```python
def test_main_weekly_no_sweep_passes_full_sweep_false(mocker):
    """CLI --no-sweep → run_weekly_chain(full_sweep=False)."""
    import importlib
    m = importlib.import_module("kr_pipeline.pipeline.__main__")

    mocker.patch.object(m, "Config")
    mocker.patch.object(m, "setup_logging")
    conn_cm = mocker.patch.object(m, "connect")
    conn_cm.return_value.__enter__.return_value = "CONN"
    rw = mocker.patch.object(m.chains, "run_weekly_chain", return_value={})
    mocker.patch("sys.argv", ["prog", "--chain=weekly", "--no-sweep"])

    m.main()
    rw.assert_called_once_with("CONN", limit_tickers=None, full_sweep=False)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_chains.py::test_main_weekly_no_sweep_passes_full_sweep_false -v`
Expected: FAIL — `SystemExit: 2` (argparse: unrecognized arguments: --no-sweep) 또는 호출 인자 불일치(full_sweep 미전달)

- [ ] **Step 3: 구현** — `__main__.py` 의 argparse 추가 + weekly 호출 수정

`p.add_argument("--no-drift", ...)` 줄 아래에 추가:
```python
    p.add_argument("--no-sweep", action="store_true", help="weekly 체인 전체스윕 건너뛰기")
```
weekly 분기 교체:
```python
        else:
            result = chains.run_weekly_chain(conn, limit_tickers=args.limit_tickers,
                                             full_sweep=not args.no_sweep)
```
또한 도움말 문자열(파일 1행 docstring)에 `[--no-sweep]` 반영:
```python
"""CLI: python -m kr_pipeline.pipeline --chain=daily|weekly [--limit-tickers N] [--no-drift] [--no-sweep]"""
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_pipeline_chains.py::test_main_weekly_no_sweep_passes_full_sweep_false -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/pipeline/__main__.py tests/test_pipeline_chains.py
git commit -m "feat(drift): pipeline CLI 에 --no-sweep 플래그 추가"
```

---

## Task 6: `corporate-actions` 수집을 평일 매일로 (cron/label/desc)

**Files:**
- Modify: `kr_pipeline/llm_runner/pipeline_specs.py` (`corporate-actions` spec)
- Test: `tests/test_pipeline_specs.py`

- [ ] **Step 1: 실패 테스트 추가** — `tests/test_pipeline_specs.py` 에 추가

```python
def test_corporate_actions_scheduled_weekday_daily():
    """공시 수집을 평일 매일로 — drift 평일 후보 명단을 매일 갱신."""
    from kr_pipeline.llm_runner.pipeline_specs import get_spec

    ca = get_spec("corporate-actions")
    assert ca["default_cron"] == "0 8 * * 1-5"
    assert ca["schedule_label"] == "평일 매일"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_pipeline_specs.py::test_corporate_actions_scheduled_weekday_daily -v`
Expected: FAIL — `assert '30 4 * * 6' == '0 8 * * 1-5'`

- [ ] **Step 3: 구현** — `corporate-actions` spec 의 cron/label 변경 + long_description 후속작업 보강

`kr_pipeline/llm_runner/pipeline_specs.py` 의 `corporate-actions` 블록에서:
```python
        "default_cron": "30 4 * * 6",
        "schedule_label": "주 1회 (토)",
```
→
```python
        "default_cron": "0 8 * * 1-5",
        "schedule_label": "평일 매일",
```
그리고 같은 블록 `long_description` 끝부분 `"선행 작업: 없음 (외부 KRX/DART API)\n후속 작업: indicators-daily, indicators-weekly (지표 계산 시 가격 조정)"` 를
`"선행 작업: 없음 (외부 KRX/DART API)\n후속 작업: indicators-daily, indicators-weekly (지표 계산 시 가격 조정), data-daily (drift 평일 후보 공급)"` 로 변경.

- [ ] **Step 4: 통과 확인 (specs + cron 영향 회귀)**

Run: `uv run pytest tests/test_pipeline_specs.py tests/test_cron_manager.py -v`
Expected: PASS — `corporate-actions` 는 여전히 비-빈 cron 이라 예약 spec 수 8 유지(`test_default_cron_lines_contains_three_modes`), cron 문자열 값은 검증 대상 아님.

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/llm_runner/pipeline_specs.py tests/test_pipeline_specs.py
git commit -m "feat(drift): corporate-actions 수집을 평일 매일(08:00)로 변경 (drift 후보 신선도)"
```

---

## Task 7: 회귀 검증 + 운영 메모

**Files:** (코드 변경 없음 — 검증/문서)

- [ ] **Step 1: 전체 drift/chains/specs 테스트**

Run: `uv run pytest tests/test_pipeline_drift.py tests/test_pipeline_chains.py tests/test_pipeline_specs.py tests/test_cron_manager.py -v`
Expected: 모두 PASS.

- [ ] **Step 2: baseline 회귀 비교** — 새 작업이 사전 실패 수를 늘리지 않았는지

Run: `uv run pytest tests/ -q 2>&1 | tail -15`
Expected: 실패 수가 base(main) 대비 증가 없음 (사전 isolation 실패 ~31개는 baseline; `corporate_actions`/`stocks` DB 테스트는 `TEST_DATABASE_URL` 미설정 시 skip). 증가분이 있으면 그 테스트만 조사.

- [ ] **Step 3: 운영 메모를 PR/완료 보고에 명시 (코드 아님)**

배포 시 필요한 수동 단계 — 완료 보고에 포함:
1. **크론탭 재설치**: `corporate-actions` cron 이 토→평일로 바뀌었으므로 크론 관리자로 재등록 필요(`get_default_cron_lines`/cron_manager 경로).
2. **첫 토요일 스윕 주의**: 그동안 미수정 drift 를 한꺼번에 치유해 재적재가 평소보다 많을 수 있음(정상). 원하면 배포 전 1회 수동 ohlcv full-refresh 로 선치유 가능.
3. 스키마 변경 없음 → DB 마이그레이션 불필요.

- [ ] **Step 4: (변경 있을 경우) 커밋**

```bash
git status --short   # 코드 변경 없으면 커밋 없음
```

---

## Self-Review 결과 (작성자 확인)

- **Spec coverage**: §1 후보선정→Task2, §2 detect 인자→Task1, §3 평일배선→Task3, §4 토요일스윕→Task4, §5 공시 cron→Task6, `--no-sweep`→Task5, 테스트/회귀→Task7. 누락 없음.
- **빈 후보 처리**(`[]`≠`None`): Task1 Step3 분기 + Task1 전용 테스트로 고정.
- **Type/이름 일관성**: `recent_corp_action_tickers`·`detect_drifted_tickers(tickers=...)`·`CA_LOOKBACK_DAYS`·`SWEEP_RECENT_DAYS`·`full_sweep`·details `sweep` 키가 전 Task 에서 동일 사용.
- **기존 테스트 깨짐 처리**: Task3(평일 detect 패치에 recent_corp_action_tickers 추가)·Task4(weekly 호출 full_sweep=False + details sweep 키) 명시적 갱신.
