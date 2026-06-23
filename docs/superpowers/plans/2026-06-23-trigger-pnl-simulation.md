# 2024 결정론 트리거 + P&L 시뮬레이션 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 8종목 2024 watch pivot에 프로덕션 `trigger_gate.evaluate`를 일봉으로 replay해 매수 트리거·모의 진입→청산 P&L(시장대비)을 결정론으로 측정하고, watch_reason 적격 게이트의 효과를 shadow 비교로 검정한다.

**Architecture:** 신설 읽기전용 패키지 `kr_pipeline/backtest/`. 코어는 순수 함수 `simulate()`(in-memory watch rows + day bars 위에서 `trigger_gate.evaluate` 호출). DB 로더는 분리. 프로덕션 테이블 쓰기 0, LLM 0. 프로덕션은 backtest를 import하지 않는다(단방향: backtest → trigger_gate).

**Tech Stack:** Python 3 (dataclasses, psycopg), pytest, PostgreSQL. 재사용: `kr_pipeline.llm_runner.compute.trigger_gate.evaluate`.

## Global Constraints

- 커밋 메시지에 `Co-Authored-By: Claude` 류 트레일러 금지.
- 읽기전용: `classification_backfill`/`daily_prices`/`daily_indicators`/`index_daily`만 읽고 **프로덕션 테이블에 쓰지 않음**. LLM 호출 0.
- **트리거 로직 재구현 금지** — `trigger_gate.evaluate`(keyword-only)를 그대로 호출.
- 격리: 프로덕션 코드(`kr_pipeline/llm_runner/*`, cron)는 `kr_pipeline/backtest`를 import하지 않음. 의존은 backtest → trigger_gate 단방향만.
- 사전 고정(변경 금지): 진입=발화일 종가, 청산=`trigger_gate` invalidation(close<base_low/sma_50, 거래량 미고려=보수적), 재진입=active pivot(토요일) 갱신 후만, look-ahead 차단(그날 bar까지만).
- thresholds 변경 없음 → threshold-change-checklist 비대상.
- 8종목: 003230,101930,399720,200470,257720,000320,900340,267260. 기간 2024-01-06~2024-12-28(분류), forward 가격은 2025 데이터까지 사용.
- 지수 매핑: KOSPI→index_code `1001`, KOSDAQ→`2001`(빌드 시 지수 레벨로 sanity 확인: 2024 KOSPI~2500, KOSDAQ~700).
- `trigger_gate.evaluate` 시그니처(keyword-only): `evaluate(*, close, pivot_price, volume, avg_volume_50d, stop_loss, sma_50, classification, prev_close=None, watch_reason=None) -> "breakout"|"breakout_from_watch"|"invalidation"|"promotion"|None`. 평가순서: invalidation→breakout(entry)→breakout_from_watch→promotion→None.
- `ALLOWED_WATCH_REASONS = {unfavorable_market, marginal_tt, valid_base_awaiting_breakout}` (trigger_gate.py:45).

---

## File Structure

- **Create** `kr_pipeline/backtest/__init__.py` — 빈 패키지 마커.
- **Create** `kr_pipeline/backtest/trigger_sim.py` — 코어: dataclasses(WatchRow/DayBar/Trade) + `simulate()`(순수) + DB 로더(`load_watchlist`/`load_daily_series`/`load_index_series`) + `classify_rows()` + `market_relative()`.
- **Create** `kr_pipeline/backtest/__main__.py` — 얇은 CLI: 8종목 production+shadow 실행 → 표·census 출력.
- **Create** `tests/test_backtest_trigger_sim.py` — `simulate()` 합성 단위테스트(8 케이스) + 로더 스모크.
- **Create** `docs/superpowers/backtest-2024-trigger-sim-results.md` — 결과 문서(Task 4).

---

## Task 1: 코어 `simulate()` (순수 함수) + 합성 단위테스트

**Files:**
- Create: `kr_pipeline/backtest/__init__.py`
- Create: `kr_pipeline/backtest/trigger_sim.py` (dataclasses + simulate만; 로더는 Task 2)
- Test: `tests/test_backtest_trigger_sim.py`

**Interfaces:**
- Consumes: `trigger_gate.evaluate`, `ALLOWED_WATCH_REASONS`.
- Produces:
  - `@dataclass WatchRow(ticker:str, sat:date, pivot_price:float, base_low:float|None, watch_reason:str|None)`
  - `@dataclass DayBar(d:date, close:float, volume:int, sma_50:float|None, avg_volume_50d:float|None, prev_close:float|None)`
  - `@dataclass Trade(ticker, watch_reason, pivot_sat, pivot_price, base_low, entry_date, entry_close, exit_date, exit_close, pnl_pct, binding_exit)`
  - `simulate(ticker:str, watch_rows:list[WatchRow], day_bars:list[DayBar], *, mode:str) -> tuple[list[Trade], int]` (mode='production'|'shadow'; 반환 (trades, promotion_count))

- [ ] **Step 1: 패키지 마커 생성**

Create `kr_pipeline/backtest/__init__.py`:
```python
"""백테스트 분석 도구 (읽기전용). 프로덕션 파이프라인은 이 패키지를 import 하지 않는다."""
```

- [ ] **Step 2: 실패 테스트 작성 (8 케이스)**

Create `tests/test_backtest_trigger_sim.py`:
```python
from datetime import date

from kr_pipeline.backtest.trigger_sim import WatchRow, DayBar, simulate


def _bars(seq):
    """seq: list of (day, close, volume, sma_50, avgvol, prev_close)"""
    return [DayBar(d=d, close=c, volume=v, sma_50=s, avg_volume_50d=a, prev_close=p)
            for (d, c, v, s, a, p) in seq]


def _watch(sat, pivot, base_low, reason):
    return WatchRow(ticker="T", sat=sat, pivot_price=pivot, base_low=base_low, watch_reason=reason)


def test_fresh_cross_with_volume_enters():
    wr = [_watch(date(2024, 1, 6), 100.0, 90.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0),    # below pivot
        (date(2024, 1, 9), 105.0, 200, 95.0, 100.0, 98.0),   # fresh cross + vol>=avg
    ])
    trades, promo = simulate("T", wr, bars, mode="production")
    assert len(trades) == 1
    assert trades[0].entry_date == date(2024, 1, 9)
    assert trades[0].entry_close == 105.0


def test_cross_without_volume_no_entry():
    wr = [_watch(date(2024, 1, 6), 100.0, 90.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 50, 95.0, 100.0, 97.0),
        (date(2024, 1, 9), 105.0, 50, 95.0, 100.0, 98.0),    # vol < avg -> no breakout
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert trades == []


def test_extended_no_fresh_cross_no_entry():
    # production: extended reason not allowed -> never breakout_from_watch
    wr = [_watch(date(2024, 1, 6), 100.0, 90.0, "extended")]
    bars = _bars([
        (date(2024, 1, 8), 110.0, 200, 95.0, 100.0, 108.0),  # already above pivot, no fresh cross
        (date(2024, 1, 9), 115.0, 200, 95.0, 100.0, 110.0),
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert trades == []
    # shadow: reason gate bypassed, but fresh_cross still false (already above) -> still no entry
    trades_s, _ = simulate("T", wr, bars, mode="shadow")
    assert trades_s == []


def test_exit_on_close_below_sma50():
    wr = [_watch(date(2024, 1, 6), 100.0, 80.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0),
        (date(2024, 1, 9), 105.0, 200, 95.0, 100.0, 98.0),   # enter @105
        (date(2024, 1, 10), 94.0, 200, 95.0, 100.0, 105.0),  # close<sma50(95) -> exit, base_low=80 not hit
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert len(trades) == 1
    assert trades[0].exit_date == date(2024, 1, 10)
    assert trades[0].binding_exit == "sma_50"
    assert abs(trades[0].pnl_pct - ((94.0 / 105.0 - 1) * 100)) < 1e-6


def test_exit_on_close_below_base_low():
    wr = [_watch(date(2024, 1, 6), 100.0, 96.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 90.0, 100.0, 97.0),
        (date(2024, 1, 9), 105.0, 200, 90.0, 100.0, 98.0),   # enter @105 (sma50=90)
        (date(2024, 1, 10), 95.0, 200, 90.0, 100.0, 105.0),  # close 95 < base_low 96, but > sma50 90 -> base_low binding
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert len(trades) == 1
    assert trades[0].binding_exit == "base_low"


def test_no_reentry_same_pivot():
    wr = [_watch(date(2024, 1, 6), 100.0, 80.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0),
        (date(2024, 1, 9), 105.0, 200, 95.0, 100.0, 98.0),   # enter
        (date(2024, 1, 10), 94.0, 200, 95.0, 100.0, 105.0),  # exit (close<sma50)
        (date(2024, 1, 11), 98.0, 200, 95.0, 100.0, 94.0),   # below pivot again
        (date(2024, 1, 12), 106.0, 200, 95.0, 100.0, 98.0),  # fresh cross SAME pivot -> no re-entry
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert len(trades) == 1  # only the first


def test_reentry_after_pivot_update():
    wr = [
        _watch(date(2024, 1, 6), 100.0, 80.0, "valid_base_awaiting_breakout"),
        _watch(date(2024, 1, 13), 100.0, 80.0, "valid_base_awaiting_breakout"),  # new Saturday -> pivot refreshed
    ]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0),
        (date(2024, 1, 9), 105.0, 200, 95.0, 100.0, 98.0),   # enter (pivot sat 1/6)
        (date(2024, 1, 10), 94.0, 200, 95.0, 100.0, 105.0),  # exit
        (date(2024, 1, 15), 98.0, 200, 95.0, 100.0, 94.0),   # after new sat 1/13
        (date(2024, 1, 16), 106.0, 200, 95.0, 100.0, 98.0),  # fresh cross under new pivot -> re-entry
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert len(trades) == 2


def test_open_position_marked_to_last_bar():
    wr = [_watch(date(2024, 1, 6), 100.0, 80.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 98.0, 200, 95.0, 100.0, 97.0),
        (date(2024, 1, 9), 105.0, 200, 95.0, 100.0, 98.0),   # enter
        (date(2024, 1, 10), 120.0, 200, 95.0, 100.0, 105.0),  # never invalidated
    ])
    trades, _ = simulate("T", wr, bars, mode="production")
    assert len(trades) == 1
    assert trades[0].binding_exit == "open"
    assert trades[0].exit_date == date(2024, 1, 10)


def test_promotion_counted_not_entered():
    # close in [pivot*0.95, pivot] with volume -> promotion, no entry
    wr = [_watch(date(2024, 1, 6), 100.0, 80.0, "valid_base_awaiting_breakout")]
    bars = _bars([
        (date(2024, 1, 8), 97.0, 200, 95.0, 100.0, 96.0),   # 0.95*100=95 <= 97 <=100 -> promotion
    ])
    trades, promo = simulate("T", wr, bars, mode="production")
    assert trades == []
    assert promo == 1
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/test_backtest_trigger_sim.py -q`
Expected: FAIL (ModuleNotFoundError: kr_pipeline.backtest.trigger_sim).

- [ ] **Step 4: `simulate()` 구현**

Create `kr_pipeline/backtest/trigger_sim.py`:
```python
"""결정론 트리거+P&L 시뮬레이션 코어. trigger_gate.evaluate 를 그대로 호출(재구현 금지).

읽기전용 분석 도구. 프로덕션은 이 모듈을 import 하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from kr_pipeline.llm_runner.compute.trigger_gate import evaluate as gate_evaluate

# shadow 모드에서 watch_reason 적격 게이트만 우회(가격/거래량/fresh_cross 로직은 동일 유지).
_SHADOW_REASON = "valid_base_awaiting_breakout"


@dataclass
class WatchRow:
    ticker: str
    sat: date
    pivot_price: float
    base_low: float | None
    watch_reason: str | None


@dataclass
class DayBar:
    d: date
    close: float
    volume: int
    sma_50: float | None
    avg_volume_50d: float | None
    prev_close: float | None


@dataclass
class Trade:
    ticker: str
    watch_reason: str | None
    pivot_sat: date
    pivot_price: float
    base_low: float | None
    entry_date: date
    entry_close: float
    exit_date: date | None
    exit_close: float | None
    pnl_pct: float | None
    binding_exit: str | None   # 'base_low' | 'sma_50' | 'open'


def _active_row(rows: list[WatchRow], d: date) -> WatchRow | None:
    """sat<=d 인 가장 최근 pivot 보유 watch row (rows 는 sat 오름차순 가정)."""
    cur = None
    for r in rows:
        if r.sat <= d:
            cur = r
        else:
            break
    return cur


def simulate(ticker: str, watch_rows: list[WatchRow], day_bars: list[DayBar],
             *, mode: str) -> tuple[list[Trade], int]:
    """일별 walk 로 트리거 발화→진입→청산 시뮬. mode: 'production'|'shadow'.

    production: watch_reason 을 그대로 전달(비적격은 자연 불발). shadow: 적격 사유로 치환해
    가격/거래량/fresh_cross 로직만 태움(이유 게이트 우회). 반환 (trades, promotion_count).
    """
    rows = sorted([r for r in watch_rows if r.pivot_price is not None], key=lambda r: r.sat)
    bars = sorted(day_bars, key=lambda b: b.d)
    trades: list[Trade] = []
    promotion_count = 0
    cur: Trade | None = None
    last_entry_pivot_sat: date | None = None

    for b in bars:
        active = _active_row(rows, b.d)
        if active is None or b.sma_50 is None or b.avg_volume_50d is None:
            continue
        # 보유 중이면 진입 시점 base_low 로 invalidation 판정; 아니면 active 의 base_low.
        stop_for_gate = cur.base_low if cur is not None else active.base_low
        reason_for_gate = _SHADOW_REASON if mode == "shadow" else active.watch_reason
        sig = gate_evaluate(
            close=b.close,
            pivot_price=active.pivot_price,
            volume=b.volume,
            avg_volume_50d=b.avg_volume_50d,
            stop_loss=stop_for_gate,
            sma_50=b.sma_50,
            classification="watch",
            prev_close=b.prev_close,
            watch_reason=reason_for_gate,
        )
        if cur is not None:
            if sig == "invalidation":
                binding = "base_low" if (cur.base_low is not None and b.close < cur.base_low) else "sma_50"
                cur.exit_date = b.d
                cur.exit_close = b.close
                cur.pnl_pct = (b.close / cur.entry_close - 1) * 100
                cur.binding_exit = binding
                trades.append(cur)
                cur = None
        else:
            if sig == "breakout_from_watch":
                if last_entry_pivot_sat == active.sat:
                    continue  # 재진입 상한: 같은 pivot 재진입 금지
                cur = Trade(
                    ticker=ticker, watch_reason=active.watch_reason, pivot_sat=active.sat,
                    pivot_price=active.pivot_price, base_low=active.base_low,
                    entry_date=b.d, entry_close=b.close,
                    exit_date=None, exit_close=None, pnl_pct=None, binding_exit=None,
                )
                last_entry_pivot_sat = active.sat
            elif sig == "promotion" and mode == "production":
                promotion_count += 1

    if cur is not None and bars:
        last = bars[-1]
        cur.exit_date = last.d
        cur.exit_close = last.close
        cur.pnl_pct = (last.close / cur.entry_close - 1) * 100
        cur.binding_exit = "open"
        trades.append(cur)

    return trades, promotion_count
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_backtest_trigger_sim.py -q`
Expected: PASS (9 tests).

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/backtest/__init__.py kr_pipeline/backtest/trigger_sim.py tests/test_backtest_trigger_sim.py
git commit -m "feat(backtest): 결정론 트리거+P&L 시뮬 코어 simulate() (trigger_gate 재사용, TDD)"
```

---

## Task 2: DB 로더 + 행 분류 (production/shadow/census)

**Files:**
- Modify: `kr_pipeline/backtest/trigger_sim.py` (로더·분류 함수 추가)
- Test: `tests/test_backtest_trigger_sim.py` (로더 스모크 추가)

**Interfaces:**
- Consumes: WatchRow/DayBar (Task 1), `ALLOWED_WATCH_REASONS`.
- Produces:
  - `load_watchlist(conn, ticker, start:date, end:date) -> list[WatchRow]` (classification_backfill의 watch 행)
  - `load_daily_series(conn, ticker, start:date, end:date) -> list[DayBar]`
  - `load_index_series(conn, market:str, start:date, end:date) -> dict[date,float]`
  - `classify_rows(watch_rows) -> dict` (production/shadow/census 건수·행 분류; ALLOWED 기준)

- [ ] **Step 1: 로더·분류 함수 추가**

`kr_pipeline/backtest/trigger_sim.py` 끝에 추가:
```python
from psycopg import Connection
from kr_pipeline.llm_runner.compute.trigger_gate import ALLOWED_WATCH_REASONS

_INDEX_CODE = {"KOSPI": "1001", "KOSDAQ": "2001"}


def load_watchlist(conn: Connection, ticker: str, start: date, end: date) -> list[WatchRow]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT analyzed_for_date, pivot_price, base_low, watch_reason
              FROM classification_backfill
             WHERE symbol = %s AND classification = 'watch'
               AND analyzed_for_date BETWEEN %s AND %s
             ORDER BY analyzed_for_date
            """,
            (ticker, start, end),
        )
        return [
            WatchRow(ticker=ticker, sat=r[0],
                     pivot_price=float(r[1]) if r[1] is not None else None,
                     base_low=float(r[2]) if r[2] is not None else None,
                     watch_reason=r[3])
            for r in cur.fetchall()
        ]


def load_daily_series(conn: Connection, ticker: str, start: date, end: date) -> list[DayBar]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.date, p.adj_close, p.volume, i.sma_50, i.avg_volume_50d,
                   LAG(p.adj_close) OVER (ORDER BY p.date) AS prev_close
              FROM daily_prices p
              LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = %s AND p.date BETWEEN %s AND %s
             ORDER BY p.date
            """,
            (ticker, start, end),
        )
        return [
            DayBar(d=r[0], close=float(r[1]), volume=int(r[2]) if r[2] is not None else 0,
                   sma_50=float(r[3]) if r[3] is not None else None,
                   avg_volume_50d=float(r[4]) if r[4] is not None else None,
                   prev_close=float(r[5]) if r[5] is not None else None)
            for r in cur.fetchall()
        ]


def load_index_series(conn: Connection, market: str, start: date, end: date) -> dict[date, float]:
    code = _INDEX_CODE[market]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date, close FROM index_daily WHERE index_code = %s AND date BETWEEN %s AND %s",
            (code, start, end),
        )
        return {r[0]: float(r[1]) for r in cur.fetchall()}


def classify_rows(watch_rows: list[WatchRow]) -> dict:
    """production(적격 reason+pivot) / shadow(비적격 reason+pivot) / census(pivot 없음) 분류."""
    production, shadow, census = [], [], []
    for r in watch_rows:
        if r.pivot_price is None:
            census.append(r)
        elif r.watch_reason in ALLOWED_WATCH_REASONS:
            production.append(r)
        else:
            shadow.append(r)
    return {"production": production, "shadow": shadow, "census": census}
```

- [ ] **Step 2: 로더 스모크 테스트 추가**

`tests/test_backtest_trigger_sim.py` 끝에 추가:
```python
def test_loaders_smoke():
    """실 DB 에서 8종목 중 하나(가온칩스 399720)의 watch/일봉/지수 로드 동작."""
    from datetime import date
    from kr_pipeline.db.connection import connect
    from kr_pipeline.backtest.trigger_sim import (
        load_watchlist, load_daily_series, load_index_series, classify_rows,
    )
    with connect() as conn:
        wr = load_watchlist(conn, "399720", date(2024, 1, 6), date(2024, 12, 28))
        assert len(wr) >= 1
        bars = load_daily_series(conn, "399720", date(2024, 1, 1), date(2024, 12, 31))
        assert len(bars) > 200  # 2024 거래일
        idx = load_index_series(conn, "KOSDAQ", date(2024, 1, 1), date(2024, 12, 31))
        assert len(idx) > 200
        cls = classify_rows(wr)
        assert set(cls) == {"production", "shadow", "census"}
```

- [ ] **Step 3: 테스트 통과 확인**

Run: `uv run pytest tests/test_backtest_trigger_sim.py -q`
Expected: PASS (10 tests). (실 DB 연결 필요 — kr_pipeline DB.)

- [ ] **Step 4: 커밋**

```bash
git add kr_pipeline/backtest/trigger_sim.py tests/test_backtest_trigger_sim.py
git commit -m "feat(backtest): DB 로더(watchlist/daily/index)+행분류(production/shadow/census)"
```

---

## Task 3: `market_relative` + CLI 오케스트레이션

**Files:**
- Modify: `kr_pipeline/backtest/trigger_sim.py` (`market_relative` 추가)
- Create: `kr_pipeline/backtest/__main__.py`
- Test: `tests/test_backtest_trigger_sim.py` (market_relative 단위테스트)

**Interfaces:**
- Consumes: Trade, 로더들 (Task 1·2).
- Produces: `market_relative(trade:Trade, index_series:dict[date,float]) -> float|None` (보유기간 지수수익 차감한 초과수익%).

- [ ] **Step 1: market_relative 실패 테스트 추가**

`tests/test_backtest_trigger_sim.py` 끝에 추가:
```python
def test_market_relative_subtracts_index():
    from datetime import date
    from kr_pipeline.backtest.trigger_sim import Trade, market_relative
    t = Trade(ticker="T", watch_reason="x", pivot_sat=date(2024, 1, 6), pivot_price=100.0,
              base_low=90.0, entry_date=date(2024, 1, 9), entry_close=100.0,
              exit_date=date(2024, 1, 16), exit_close=110.0, pnl_pct=10.0, binding_exit="open")
    idx = {date(2024, 1, 9): 1000.0, date(2024, 1, 16): 1040.0}  # 시장 +4%
    # 종목 +10% - 시장 +4% = +6% 초과
    assert abs(market_relative(t, idx) - 6.0) < 1e-6
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_backtest_trigger_sim.py::test_market_relative_subtracts_index -q`
Expected: FAIL (market_relative 미정의).

- [ ] **Step 3: market_relative 구현**

`kr_pipeline/backtest/trigger_sim.py`에 추가:
```python
def _nearest_on_or_before(series: dict[date, float], d: date) -> float | None:
    cands = [k for k in series if k <= d]
    return series[max(cands)] if cands else None


def market_relative(trade: Trade, index_series: dict[date, float]) -> float | None:
    """트레이드 보유기간 지수수익을 차감한 초과수익%. 데이터 없으면 None."""
    if trade.pnl_pct is None or trade.exit_date is None:
        return None
    base = _nearest_on_or_before(index_series, trade.entry_date)
    end = _nearest_on_or_before(index_series, trade.exit_date)
    if base is None or end is None or base == 0:
        return None
    index_pct = (end / base - 1) * 100
    return trade.pnl_pct - index_pct
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_backtest_trigger_sim.py::test_market_relative_subtracts_index -q`
Expected: PASS.

- [ ] **Step 5: CLI 작성**

Create `kr_pipeline/backtest/__main__.py`:
```python
"""CLI: 8종목 2024 결정론 트리거+P&L 시뮬 (production + shadow). 읽기전용."""
from __future__ import annotations

import json
from datetime import date

from kr_pipeline.db.connection import connect
from kr_pipeline.backtest.trigger_sim import (
    load_watchlist, load_daily_series, load_index_series, classify_rows,
    simulate, market_relative,
)

TICKERS = ["003230", "101930", "399720", "200470", "257720", "000320", "900340", "267260"]
START, END = date(2024, 1, 6), date(2024, 12, 28)
PX_START, PX_END = date(2024, 1, 1), date(2025, 6, 30)  # forward 가격 포함


def _market_of(conn, ticker: str) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT market FROM stocks WHERE ticker = %s", (ticker,))
        return cur.fetchone()[0]


def _trade_row(t, idx):
    return {
        "ticker": t.ticker, "watch_reason": t.watch_reason, "pivot_sat": str(t.pivot_sat),
        "entry_date": str(t.entry_date), "entry_close": t.entry_close,
        "exit_date": str(t.exit_date), "exit_close": t.exit_close,
        "pnl_pct": round(t.pnl_pct, 1) if t.pnl_pct is not None else None,
        "excess_pct": round(market_relative(t, idx), 1) if market_relative(t, idx) is not None else None,
        "binding_exit": t.binding_exit,
    }


def main() -> int:
    out = {"production": [], "shadow": [], "census": {"no_pivot": 0, "promotion_fires": 0},
           "counts": {"production": 0, "shadow": 0, "census": 0}}
    with connect() as conn:
        for ticker in TICKERS:
            market = _market_of(conn, ticker)
            wr = load_watchlist(conn, ticker, START, END)
            bars = load_daily_series(conn, ticker, PX_START, PX_END)
            idx = load_index_series(conn, market, PX_START, PX_END)
            cls = classify_rows(wr)
            out["counts"]["production"] += len(cls["production"])
            out["counts"]["shadow"] += len(cls["shadow"])
            out["counts"]["census"] += len(cls["census"])
            out["census"]["no_pivot"] += len(cls["census"])
            # production: 적격 행만 active pivot 으로 (실제 시스템 행동)
            prod_trades, promo = simulate(ticker, cls["production"], bars, mode="production")
            out["census"]["promotion_fires"] += promo
            for t in prod_trades:
                out["production"].append(_trade_row(t, idx))
            # shadow: 비적격(pivot有) 행을 게이트 우회로
            shadow_trades, _ = simulate(ticker, cls["shadow"], bars, mode="shadow")
            for t in shadow_trades:
                out["shadow"].append(_trade_row(t, idx))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: 전체 테스트 + CLI 스모크**

Run: `uv run pytest tests/test_backtest_trigger_sim.py -q`
Expected: PASS (11 tests).
Run: `uv run python -m kr_pipeline.backtest`
Expected: JSON 출력 — `counts.production`+`counts.shadow`+`counts.census`가 8종목 watch 합계와 일치, production/shadow trade 배열·census 출력. 에러 없음.

- [ ] **Step 7: 커밋**

```bash
git add kr_pipeline/backtest/trigger_sim.py kr_pipeline/backtest/__main__.py tests/test_backtest_trigger_sim.py
git commit -m "feat(backtest): market_relative 초과수익 + CLI 오케스트레이션(production/shadow/census)"
```

---

## Task 4: 실행 + 결과 문서

**Files:**
- Create: `docs/superpowers/backtest-2024-trigger-sim-results.md`

- [ ] **Step 1: 실행 + 건수 확정**

Run: `uv run python -m kr_pipeline.backtest > /tmp/trigsim.json 2>/dev/null; cat /tmp/trigsim.json`
Expected: production/shadow/census 건수 확정(spec의 근사 7/14/170 실제값으로). production·shadow 트레이드별 pnl_pct·excess_pct·binding_exit, promotion_fires 확인.

- [ ] **Step 2: 결과 문서 작성**

`docs/superpowers/backtest-2024-trigger-sim-results.md` 작성. 필수 구조:
- **범위 라벨(최상단)**: "8종목 워치리스트 한정, 결정론 트리거 하한 추정 — 신규후보·LLM확인·사이징 제외, 시스템 전체 수익성 아님."
- **production(적격) 표**: 트레이드별 ticker/watch_reason/entry·exit/pnl_pct/**excess_pct**/binding_exit + 요약(트레이드수·평균 초과수익).
- **shadow 표(사유별 분리)**: extended / base_forming 나눠서. 각주: "게이트 우회 가정, 시스템이 한 일 아님."
- **census**: pivot 없는 watch 건수 + promotion_fires(적격이 pivot 근접했으나 못 넘은 횟수).
- **해석(사전등록 규율대로)**: ① extended가 shadow에서 0~소수 발화 → "추격 차단 정당(fresh_cross 가격조건)". ② base_forming shadow가 +수익이어도 "미완성 베이스 우연 적중, 과보수 증거 아님". ③ census가 이슈2의 진짜 답("watch 대부분 구조적 매수불가=설계"). ④ 청산은 거래량 미고려 게이트 결정론=LLM보다 빨리 파는 보수적 청산(각주). ⑤ 진입=종가는 "하루 슬리피지 없는 근사".
- **한계**: 적격+shadow=소표본, 8종목·2024·큐레이션, 입력 pivot/base_low는 저장된 1회 LLM 분류본 고정.

- [ ] **Step 3: 커밋**

```bash
git add docs/superpowers/backtest-2024-trigger-sim-results.md
git commit -m "docs(backtest): 2024 결정론 트리거+P&L 시뮬 결과·해석"
```

---

## Self-Review (작성자 점검)

- **Spec 커버리지**: 읽기전용·결정론·trigger_gate 재사용(Task1) / production·shadow·census 분류(Task2 classify_rows) / 사전고정 진입·청산·재진입·look-ahead(Task1 simulate + 테스트 6·7·8) / 시장대비 초과수익(Task3 market_relative) / promotion 카운트(Task1 + 테스트 9) / binding_exit 기록(Task1 + 테스트 4·5) / 격리(backtest→trigger_gate 단방향, Global Constraints) / 결과 라벨·해석 규율(Task4). 전부 태스크 존재.
- **Placeholder**: 없음(모든 코드 단계에 실제 코드).
- **Type 일관성**: `simulate(ticker, watch_rows, day_bars, *, mode) -> (list[Trade], int)` Task1 정의 ↔ Task3 CLI 호출 일치. WatchRow/DayBar/Trade 필드가 로더(Task2)·CLI(Task3)·테스트에서 동일. `trigger_gate.evaluate` keyword-only 호출이 Global Constraints 시그니처와 일치. `market_relative(trade, index_series)` Task3 정의↔CLI 사용 일치.
