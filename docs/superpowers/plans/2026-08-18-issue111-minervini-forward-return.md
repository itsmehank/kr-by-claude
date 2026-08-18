# #111 미너비니 필터 forward return 검증 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LOCKED 스펙(`docs/superpowers/specs/2026-08-18-issue111-minervini-forward-return-design.md`)대로 전환일 이벤트 스터디 확증 판정 + 탐색 부속을 결정론으로 구현·1회 실행한다.

**Architecture:** 순수 함수 모듈(`kr_pipeline/backtest/minervini_forward.py`)에 전환 추출·초과수익·집계 부트스트랩을 두고, 얇은 러너 스크립트 2개(확증/탐색)가 DB를 읽어 JSON 산출. 전 과정 읽기 전용.

**Tech Stack:** Python(psycopg, stdlib만 — pandas/numpy 불사용), pytest(kr_test `db` 픽스처).

## Global Constraints

- 스펙 LOCKED — 판정 기준·정의 변경 금지. 확증 실행은 **머지 후 main 에서 1회**.
- seed=20260721, B=10,000, percentile 95% CI (`refinement.cluster_bootstrap_ci` 관례).
- 초과수익(%p) = 종목 수익률(%) − 지수 수익률(%), 기준 = T+1 adj_close → T+1+h 관측행 adj_close. h ∈ {20(주 판정), 40, 65}.
- 판정 어휘: CI 하한>0 = "유효" / 0 포함 = "미입증" / 상한<0 = "역효과".
- DB 는 SELECT 만. `thresholds.py` 및 소비처 무접촉(의존성 맵 체크리스트 비트리거).
- 커밋 메시지에 Claude co-author trailer 금지. `git add` 는 명시 경로만.
- 산출물: `data/backtest/issue111_minervini_transition_judge_YYYYMMDD.json`(확증), `data/backtest/exploratory_issue111_minervini_YYYYMMDD.json`(탐색). 실행 후 LOOK_LOG 각 1행.

---

### Task 1: 순수 로직 — 전환 추출·초과수익·판정 어휘

**Files:**
- Create: `kr_pipeline/backtest/minervini_forward.py`
- Test: `tests/test_minervini_forward.py`

**Interfaces:**
- Produces: `Row = tuple[date, float, bool | None, int | None]` (date, adj_close, minervini_pass, 조건개수), `extract_transitions(rows: list[Row]) -> list[int]`, `forward_excess(rows: list[Row], i: int, horizon: int, index_close: dict[date, float]) -> float | None`, `verdict_of(lo: float, hi: float) -> str`, 상수 `SEED=20260721`, `BOOT_B=10_000`, `HORIZONS=(20, 40, 65)`, `PRIMARY_H=20`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
"""#111 minervini_forward 단위 테스트 — 스펙 §2 정의 검증."""
from datetime import date, timedelta

import pytest

from kr_pipeline.backtest.minervini_forward import (
    extract_transitions, forward_excess, verdict_of,
)


def _row(i, close, label, cc=None):
    return (date(2024, 1, 1) + timedelta(days=i), close, label, cc)


def test_extract_transitions_basic():
    rows = [_row(0, 100, False), _row(1, 100, False), _row(2, 100, True),
            _row(3, 100, True), _row(4, 100, False), _row(5, 100, True)]
    assert extract_transitions(rows) == [2, 5]


def test_extract_transitions_first_row_and_null_excluded():
    # 최초 관측·직전 NULL 은 전환 아님 (스펙 §2.1)
    assert extract_transitions([_row(0, 100, True)]) == []
    assert extract_transitions([_row(0, 100, None), _row(1, 100, True)]) == []
    rows = [_row(0, 100, False), _row(1, 100, None), _row(2, 100, True)]
    assert extract_transitions(rows) == []


def test_forward_excess_known_values():
    rows = [_row(0, 50, True), _row(1, 100, True), _row(2, 105, True),
            _row(3, 110, True)]
    iclose = {rows[1][0]: 1000.0, rows[3][0]: 1050.0}
    # T=행0 → 기준 T+1(행1)=100, 2행 뒤(행3)=110: 종목 +10% − 지수 +5% = +5.0
    assert forward_excess(rows, 0, 2, iclose) == pytest.approx(5.0)


def test_forward_excess_insufficient_rows_returns_none():
    rows = [_row(0, 100, True), _row(1, 100, True)]
    assert forward_excess(rows, 0, 2, {rows[1][0]: 1.0}) is None


def test_forward_excess_missing_index_returns_none():
    rows = [_row(0, 50, True), _row(1, 100, True), _row(2, 105, True),
            _row(3, 110, True)]
    assert forward_excess(rows, 0, 2, {rows[1][0]: 1000.0}) is None


def test_verdict_of():
    assert verdict_of(0.1, 2.0) == "유효"
    assert verdict_of(-0.5, 1.0) == "미입증"
    assert verdict_of(-2.0, -0.1) == "역효과"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_minervini_forward.py -q`
Expected: FAIL — `ModuleNotFoundError` 또는 ImportError

- [ ] **Step 3: 최소 구현**

```python
"""#111 — 미너비니 전환일 forward return 결정론 검증. 읽기전용.

사전등록(LOCKED 2026-08-18):
docs/superpowers/specs/2026-08-18-issue111-minervini-forward-return-design.md
"""
from __future__ import annotations

import random
from datetime import date
from itertools import groupby
from typing import Iterator

from psycopg import Connection

SEED = 20260721
BOOT_B = 10_000
HORIZONS = (20, 40, 65)   # 4주(주 판정)·8주·13주 — 스펙 §2.2·§3
PRIMARY_H = 20

Row = tuple[date, float, bool | None, int | None]


def extract_transitions(rows: list[Row]) -> list[int]:
    """전환일 인덱스 — 직전 행 False AND 당일 True (스펙 §2.1)."""
    return [i for i in range(1, len(rows))
            if rows[i][2] is True and rows[i - 1][2] is False]


def forward_excess(rows: list[Row], i: int, horizon: int,
                   index_close: dict[date, float]) -> float | None:
    """행 i 기준 T+1 close → T+1+horizon 관측행 close 초과수익(%p). 결손 → None."""
    j, k = i + 1, i + 1 + horizon
    if k >= len(rows):
        return None
    d1, p1 = rows[j][0], rows[j][1]
    d2, p2 = rows[k][0], rows[k][1]
    i1, i2 = index_close.get(d1), index_close.get(d2)
    if i1 is None or i2 is None:
        return None
    return (p2 / p1 - 1) * 100 - (i2 / i1 - 1) * 100


def verdict_of(lo: float, hi: float) -> str:
    """스펙 §2.4 3분류."""
    if lo > 0:
        return "유효"
    if hi < 0:
        return "역효과"
    return "미입증"
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_minervini_forward.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/minervini_forward.py tests/test_minervini_forward.py
git commit -m "feat(#111): 전환 추출·초과수익·판정 어휘 순수 함수"
```

---

### Task 2: 집계 부트스트랩(등가 구현) + horizon 통계

**Files:**
- Modify: `kr_pipeline/backtest/minervini_forward.py` (함수 추가)
- Test: `tests/test_minervini_forward.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 1 의 상수·`verdict_of`
- Produces: `agg_bootstrap_ci(by_ticker: dict[str, tuple[float, int]], *, b: int = BOOT_B, seed: int = SEED) -> tuple[float, float]` — `refinement.cluster_bootstrap_ci` 와 동일 rng 시퀀스의 (합, 개수) 등가 구현(스펙 §2.5). `horizon_stats(events: list[dict], h: int) -> dict` — `{n, tickers, mean, median, ci95}` 또는 `{n: 0}`. events 원소는 `{"ticker": str, "excess_20": float, ...}` 꼴(결손 horizon 키 부재).

- [ ] **Step 1: 실패하는 테스트 추가**

```python
from kr_pipeline.backtest.minervini_forward import agg_bootstrap_ci, horizon_stats
from kr_pipeline.backtest.refinement import cluster_bootstrap_ci


def test_agg_bootstrap_matches_refinement():
    # 등가성: 같은 seed·b 에서 기존 함수와 동일 결과 (스펙 §2.5)
    vals = {"A": [1.0, 2.0], "B": [-3.0], "C": [0.5, 4.5, -1.0]}
    trades = [{"ticker": t, "excess_net": v} for t, vs in vals.items() for v in vs]
    expected = cluster_bootstrap_ci(trades, b=500, seed=20260721)
    agg = {t: (sum(vs), len(vs)) for t, vs in vals.items()}
    assert agg_bootstrap_ci(agg, b=500, seed=20260721) == expected


def test_horizon_stats_counts_mean_median():
    events = [{"ticker": "A", "excess_20": 1.0}, {"ticker": "A", "excess_20": 3.0},
              {"ticker": "B", "excess_20": -1.0}, {"ticker": "B"}]  # 마지막 = 결손
    st = horizon_stats(events, 20)
    assert st["n"] == 3 and st["tickers"] == 2
    assert st["mean"] == 1.0 and st["median"] == 1.0
    assert len(st["ci95"]) == 2


def test_horizon_stats_empty():
    assert horizon_stats([{"ticker": "A"}], 20) == {"n": 0}
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_minervini_forward.py -q`
Expected: 새 3개 FAIL (ImportError), 기존 6개 PASS

- [ ] **Step 3: 구현**

```python
def agg_bootstrap_ci(by_ticker: dict[str, tuple[float, int]], *, b: int = BOOT_B,
                     seed: int = SEED) -> tuple[float, float]:
    """cluster_bootstrap_ci 등가 — 같은 rng 시퀀스, (합, 개수) 집계 (스펙 §2.5)."""
    keys = sorted(by_ticker)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(b):
        s, c = 0.0, 0
        for _ in range(len(keys)):
            ts, tc = by_ticker[rng.choice(keys)]
            s += ts
            c += tc
        means.append(s / c)
    means.sort()
    lo = means[int(0.025 * b)]
    hi = means[min(int(0.975 * b), b - 1)]
    return (round(lo, 3), round(hi, 3))


def horizon_stats(events: list[dict], h: int) -> dict:
    """horizon 별 표본·평균·중앙값·클러스터 CI. 결손(키 부재) 이벤트는 제외."""
    key = f"excess_{h}"
    by_ticker: dict[str, tuple[float, int]] = {}
    vals: list[float] = []
    for e in events:
        v = e.get(key)
        if v is None:
            continue
        vals.append(v)
        s, c = by_ticker.get(e["ticker"], (0.0, 0))
        by_ticker[e["ticker"]] = (s + v, c + 1)
    if not vals:
        return {"n": 0}
    vs = sorted(vals)
    n = len(vs)
    median = vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2
    lo, hi = agg_bootstrap_ci(by_ticker)
    return {"n": n, "tickers": len(by_ticker), "mean": round(sum(vals) / n, 3),
            "median": round(median, 3), "ci95": [lo, hi]}
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_minervini_forward.py -q`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/minervini_forward.py tests/test_minervini_forward.py
git commit -m "feat(#111): 집계 부트스트랩 등가 구현 + horizon 통계"
```

---

### Task 3: DB 로더 + 전환 이벤트 조립

**Files:**
- Modify: `kr_pipeline/backtest/minervini_forward.py` (함수 추가)
- Test: `tests/test_minervini_forward.py` (DB 테스트 추가 — `db` 픽스처)

**Interfaces:**
- Consumes: Task 1·2 전부, `kr_pipeline.backtest.phases.INDEX_OF`
- Produces: `load_index_closes(conn: Connection) -> dict[str, dict[date, float]]`, `load_markets(conn: Connection) -> dict[str, str]`, `iter_ticker_rows(conn: Connection) -> Iterator[tuple[str, list[Row]]]`, `transition_events(conn: Connection) -> tuple[list[dict], dict[int, int]]` — (이벤트 리스트, horizon별 제외 건수). 이벤트 = `{"ticker", "date"(iso), "excess_20"?, "excess_40"?, "excess_65"?}` (결손 키 부재, 값 round 4).

- [ ] **Step 1: 실패하는 테스트 추가**

```python
from datetime import date as _date

from kr_pipeline.backtest.minervini_forward import (
    iter_ticker_rows, load_index_closes, load_markets, transition_events,
)


def _seed_db(db):
    d0 = _date(2024, 1, 1)
    with db.cursor() as cur:
        for t in ("111110", "111120"):
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES (%s,'T','KOSPI') "
                "ON CONFLICT DO NOTHING", (t,))
        for i in range(30):
            d = d0 + timedelta(days=i)
            cur.execute(
                "INSERT INTO index_daily (index_code, date, open, high, low, close) "
                "VALUES ('1001', %s, 1, 1, 1, %s)", (d, 1000 + i))
            for t, base in (("111110", 100), ("111120", 200)):
                cur.execute(
                    "INSERT INTO daily_indicators (ticker, date, adj_close, minervini_pass) "
                    "VALUES (%s, %s, %s, %s)",
                    (t, d, base + i, i >= 5 if t == "111110" else False))
    return d0


def test_loaders(db):
    d0 = _seed_db(db)
    idx = load_index_closes(db)
    assert idx["1001"][d0] == 1000.0
    assert load_markets(db)["111110"] == "KOSPI"
    rows_by = dict(iter_ticker_rows(db))
    rows = rows_by["111110"]
    assert rows[0][0] == d0 and rows[0][1] == 100.0   # date 오름차순·float 변환
    assert extract_transitions(rows) == [5]
    assert extract_transitions(rows_by["111120"]) == []


def test_transition_events_and_exclusions(db):
    _seed_db(db)
    events, excluded = transition_events(db)
    assert len(events) == 1
    e = events[0]
    assert e["ticker"] == "111110" and "excess_20" in e
    # 행 30개: 전환 i=5, T+1=6, 20행 뒤=26 존재 / 40·65 는 부족 → horizon별 제외
    assert "excess_40" not in e and "excess_65" not in e
    assert excluded == {20: 0, 40: 1, 65: 1}
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_minervini_forward.py -q`
Expected: 새 2개 FAIL (ImportError), 기존 9개 PASS

- [ ] **Step 3: 구현**

```python
def load_index_closes(conn: Connection) -> dict[str, dict[date, float]]:
    out: dict[str, dict[date, float]] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT index_code, date, close FROM index_daily")
        for code, d, c in cur.fetchall():
            out.setdefault(code, {})[d] = float(c)
    return out


def load_markets(conn: Connection) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT ticker, market FROM stocks")
        return dict(cur.fetchall())


def iter_ticker_rows(conn: Connection) -> Iterator[tuple[str, list[Row]]]:
    """종목별 date 오름차순 행 — 서버측 커서 스트리밍(532만 행 메모리 회피)."""
    with conn.cursor(name="minervini_forward_rows") as cur:
        cur.itersize = 50_000
        cur.execute(
            "SELECT ticker, date, adj_close, minervini_pass, "
            "(minervini_c1::int + minervini_c2::int + minervini_c3::int"
            " + minervini_c4::int + minervini_c5::int + minervini_c6::int"
            " + minervini_c7::int + minervini_c8::int) "
            "FROM daily_indicators ORDER BY ticker, date")
        for ticker, grp in groupby(cur, key=lambda r: r[0]):
            yield ticker, [(d, float(a), p, cc) for _, d, a, p, cc in grp]


def transition_events(conn: Connection) -> tuple[list[dict], dict[int, int]]:
    """전 종목 전환 이벤트 + horizon 별 제외 건수 (스펙 §2.1~§2.3·§3)."""
    from kr_pipeline.backtest.phases import INDEX_OF
    idx = load_index_closes(conn)
    markets = load_markets(conn)
    events: list[dict] = []
    excluded = {h: 0 for h in HORIZONS}
    for ticker, rows in iter_ticker_rows(conn):
        iclose = idx.get(INDEX_OF.get(markets.get(ticker), "1001"), {})
        for i in extract_transitions(rows):
            ev: dict = {"ticker": ticker, "date": rows[i][0].isoformat()}
            for h in HORIZONS:
                x = forward_excess(rows, i, h, iclose)
                if x is None:
                    excluded[h] += 1
                else:
                    ev[f"excess_{h}"] = round(x, 4)
            events.append(ev)
    return events, excluded
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_minervini_forward.py -q`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/backtest/minervini_forward.py tests/test_minervini_forward.py
git commit -m "feat(#111): DB 로더 + 전환 이벤트 조립"
```

---

### Task 4: 러너 스크립트 2종 (확증 판정 / 탐색 부속)

**Files:**
- Create: `scripts/issue111_minervini_forward.py`
- Create: `scripts/exploratory_issue111_minervini.py`

**Interfaces:**
- Consumes: Task 1~3 전부, `kr_pipeline.db.connection.connect`, `kr_pipeline.backtest.phases` (`load_phase_map`, `phase_at`, `INDEX_OF`)
- Produces: JSON 산출물 2종 (Global Constraints 의 경로). 스크립트는 얇은 조립만 — 로직은 전부 모듈(단위 테스트 완료분). 별도 단위 테스트 없음(Task 5 full suite + 코드리뷰로 검증).

- [ ] **Step 1: 확증 러너 작성**

```python
"""#111 확증 판정 러너 — 전환일 4주 시장대비 초과수익. 읽기전용, 1회 실행.

사전등록(LOCKED 2026-08-18):
docs/superpowers/specs/2026-08-18-issue111-minervini-forward-return-design.md
판정(§2.4): CI 하한>0 유효 / 0 포함 미입증 / 상한<0 역효과. 실행 후 LOOK_LOG 기입.
"""
from __future__ import annotations

import json
import sys
from datetime import date

from kr_pipeline.backtest.minervini_forward import (
    BOOT_B, HORIZONS, PRIMARY_H, SEED, horizon_stats, transition_events,
    verdict_of,
)
from kr_pipeline.db.connection import connect

SPEC = "docs/superpowers/specs/2026-08-18-issue111-minervini-forward-return-design.md"


def main() -> int:
    with connect() as conn:
        events, excluded = transition_events(conn)
    primary = horizon_stats(events, PRIMARY_H)
    verdict = verdict_of(*primary["ci95"])
    out = {
        "issue": 111, "spec": SPEC, "grade": "confirmatory",
        "seed": SEED, "b": BOOT_B,
        "n_transitions_total": len(events),
        "excluded_by_horizon": {str(h): excluded[h] for h in HORIZONS},
        "primary_h20": primary, "verdict": verdict,
        "secondary": {"h40": horizon_stats(events, 40),
                      "h65": horizon_stats(events, 65)},
    }
    path = (f"data/backtest/issue111_minervini_transition_judge_"
            f"{date.today():%Y%m%d}.json")
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: out[k] for k in
                      ("n_transitions_total", "primary_h20", "verdict")},
                     ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 탐색 러너 작성**

```python
"""#111 탐색 부속 ①~⑤ (스펙 §4) — exploratory, 채택 근거 불가. 읽기전용.

① 통과일 풀링 vs 미통과 ② 조건 개수 계단 ③ 국면 분해 ④ 모멘텀 교락(5분위)
⑤ 시간(월) 클러스터 강건성.
"""
from __future__ import annotations

import json
import sys
from datetime import date

from kr_pipeline.backtest import phases as ph
from kr_pipeline.backtest.minervini_forward import (
    PRIMARY_H, agg_bootstrap_ci, extract_transitions, forward_excess,
    iter_ticker_rows, load_index_closes, load_markets, verdict_of,
)
from kr_pipeline.db.connection import connect


def _add(agg: dict, key, x: float) -> None:
    s, c = agg.get(key, (0.0, 0))
    agg[key] = (s + x, c + 1)


def _group_mean(agg: dict) -> dict:
    return {str(k): {"n": c, "mean": round(s / c, 3)}
            for k, (s, c) in sorted(agg.items()) if c}


def main() -> int:
    pooled: dict[bool, dict] = {True: {}, False: {}}  # label→ticker→(합, 개수)
    stair: dict[int, tuple[float, int]] = {}
    by_phase: dict[str, tuple[float, int]] = {}
    by_month: dict[str, tuple[float, int]] = {}
    mom: list[tuple[float, float]] = []               # (전환 전 20행 수익, 초과수익)

    with connect() as conn:
        idx = load_index_closes(conn)
        markets = load_markets(conn)
        pmaps = {c: ph.load_phase_map(conn, c) for c in ("1001", "2001")}
        for ticker, rows in iter_ticker_rows(conn):
            code = ph.INDEX_OF.get(markets.get(ticker), "1001")
            iclose = idx.get(code, {})
            for i in range(len(rows)):                # ①② 모든 행
                x = forward_excess(rows, i, PRIMARY_H, iclose)
                if x is None:
                    continue
                if rows[i][2] is not None:
                    _add(pooled[rows[i][2]], ticker, x)
                if rows[i][3] is not None:
                    _add(stair, rows[i][3], x)
            for i in extract_transitions(rows):       # ③④⑤ 전환 이벤트
                x = forward_excess(rows, i, PRIMARY_H, iclose)
                if x is None:
                    continue
                d = rows[i][0]
                _add(by_phase, ph.phase_at(pmaps[code], d) or "unknown", x)
                _add(by_month, d.strftime("%Y-%m"), x)
                if i >= PRIMARY_H:
                    mom.append(((rows[i][1] / rows[i - PRIMARY_H][1] - 1) * 100, x))

    out: dict = {"issue": 111, "grade": "exploratory", "h": PRIMARY_H}
    pol: dict = {}
    for label, agg in pooled.items():                 # ①
        n = sum(c for _, c in agg.values())
        lo, hi = agg_bootstrap_ci(agg)
        pol["pass" if label else "fail"] = {
            "n": n, "tickers": len(agg),
            "mean": round(sum(s for s, _ in agg.values()) / n, 3), "ci95": [lo, hi]}
    pol["mean_diff"] = round(pol["pass"]["mean"] - pol["fail"]["mean"], 3)
    out["pooled"] = pol
    out["staircase"] = _group_mean(stair)             # ②
    out["by_phase"] = _group_mean(by_phase)           # ③
    mom.sort()                                        # ④ 5분위
    k = len(mom) // 5
    out["momentum_quintiles"] = [
        {"q": q + 1, "n": len(seg),
         "prior_mean": round(sum(p for p, _ in seg) / len(seg), 2),
         "excess_mean": round(sum(x for _, x in seg) / len(seg), 3)}
        for q in range(5)
        for seg in [mom[q * k:(q + 1) * k] if q < 4 else mom[4 * k:]]]
    lo, hi = agg_bootstrap_ci(by_month)               # ⑤
    out["month_cluster"] = {"months": len(by_month), "ci95": [lo, hi],
                            "verdict_sensitivity": verdict_of(lo, hi)}

    path = f"data/backtest/exploratory_issue111_minervini_{date.today():%Y%m%d}.json"
    with open(path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out["pooled"], ensure_ascii=False))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: import·문법 검증 (실행은 아님 — 확증 1회 규율)**

Run: `uv run python -m py_compile scripts/issue111_minervini_forward.py scripts/exploratory_issue111_minervini.py && echo OK`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add scripts/issue111_minervini_forward.py scripts/exploratory_issue111_minervini.py
git commit -m "feat(#111): 확증 판정·탐색 부속 러너 스크립트"
```

---

### Task 5: full suite + PR

- [ ] **Step 1: full suite**

Run: `DATABASE_URL=postgresql://localhost/kr_pipeline TEST_DATABASE_URL=postgresql://localhost/kr_test uv run pytest tests/ -q`
Expected: 기존 1238 + 신규 11 = **1249 passed, 1 skipped, 1 deselected**, 실패 0 (실행 전 `pgrep -f pytest` 로 교차 세션 경합 확인)

- [ ] **Step 2: PR 생성·리뷰·머지**

superpowers:requesting-code-review 로 리뷰 후 PR 생성 (base: main). PR 본문에 스펙 경로 명시. 사용자 게이트: 머지 승인.

---

### Task 6: 확증 1회 실행 + 판정 보고 (머지 후 main 에서)

- [ ] **Step 1: 확증 러너 1회 실행** (이 시점 이후 스펙 기준 변경 불가 — 이미 LOCKED)

Run: `DATABASE_URL=postgresql://localhost/kr_pipeline uv run python scripts/issue111_minervini_forward.py`
Expected: `data/backtest/issue111_minervini_transition_judge_YYYYMMDD.json` 생성, verdict ∈ {유효, 미입증, 역효과}

- [ ] **Step 2: 탐색 러너 실행**

Run: `DATABASE_URL=postgresql://localhost/kr_pipeline uv run python scripts/exploratory_issue111_minervini.py`
Expected: `data/backtest/exploratory_issue111_minervini_YYYYMMDD.json` 생성

- [ ] **Step 3: LOOK_LOG 2행 기입** (`data/backtest/LOOK_LOG.md`)

확증 1행: 데이터 = daily_indicators 전 구간(2016-06~) 전 종목 / 가설 계열 = "1차 필터 유효성" / 등급 = 확증 / 산출물 경로 / 커밋. 탐색 1행: 동일 데이터, 등급 = 탐색(부속 ①~⑤).

- [ ] **Step 4: 산출물·LOOK_LOG 커밋 + 판정 보고**

```bash
git add data/backtest/issue111_minervini_transition_judge_*.json data/backtest/exploratory_issue111_minervini_*.json data/backtest/LOOK_LOG.md
git commit -m "judge(#111): 미너비니 전환일 4주 초과수익 확증 판정 + 탐색 부속"
```

판정 보고: 스펙 §2.4 어휘로 결과 요약(§5 한계 4건 인용 포함), `gh issue comment 111` 기록. 클로즈 여부는 사용자 결정.
