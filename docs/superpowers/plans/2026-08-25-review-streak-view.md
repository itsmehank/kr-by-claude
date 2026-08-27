# /review 종목 행 회고 뷰 (streak view) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** /review 기본 뷰를 "종목 1행 + 연속 유효 묶음(streak) 색띠 + pivot 계단 그래프"로 교체하고 기존 분석 행 표는 토글로 유지한다.

**Architecture:** 신규 서비스 모듈 `api/services/review_streaks.py`가 스코프드 UNION 조회 → 묶음 분할 → stage/성과 → 시계열·pivot 계단까지 조립하고, 신규 `GET /api/review/stocks`가 노출한다. 프론트는 좌표 계산을 순수 함수(`lib/streakChart.ts`)로 분리해 SVG로 그린다. **스키마 변경 없음, 읽기 전용, 기존 `review_builder.py` 무수정(import만).**

**Tech Stack:** FastAPI + psycopg(raw SQL), pytest(kr_test, TestClient), React + TS + vite, inline SVG.

**Spec:** `docs/superpowers/specs/2026-08-25-review-stock-streak-view-design.md` — 모든 규칙의 원본. 충돌 시 스펙 우선.

## Global Constraints

- `REVIEW_COVERAGE_START = date(2026, 5, 18)` — **라이브·백필 양 테이블 전역 하한**(스펙 §1).
- key_date = `COALESCE(analyzed_for_date, classified_at::date)`, 정렬 `(key_date, classified_at)`.
- 유효 행 = classification ∈ {entry, watch} AND source ∈ {weekend, daily_delta, backfill}; 닫는 행 = classification='ignore'(source 무관) OR source='system_disqualify'.
- 성과는 pivot 기준만(stage 4분류 표 — 스펙 §2). 묶음 시작 종가 수익률 금지.
- 트리거 점 색은 **trigger_type 매핑**(돌파=초록·promotion=노랑·invalidation=회색) — DecisionPill(decision 축) 재사용 금지.
- 테스트 기대: `uv run pytest tests/` 실패 0(1 deselected·1 skipped 관례), 실행 전 `pgrep -f pytest`.
- 커밋 한국어 제목·co-author 트레일러 금지·`git add` 명시 경로만. 새 npm 의존성 금지.

## File Structure

- Create `api/services/review_streaks.py` — 스코프 조회·묶음 분할(Task 1) + 트리거·stage·성과(Task 2) + 시계열·계단·응답 조립(Task 3)
- Create `tests/test_api_review_streaks.py` — Task 1~3 테스트
- Modify `api/schemas/review.py`, `api/routers/review.py`, (등록은 기존이라 `api/main.py` 무수정) — Task 4
- Create `tests/test_api_review_stocks_router.py` — Task 4
- Create `web/src/lib/streakChart.ts` + `web/src/lib/streakChart.test.ts` — Task 5
- Create `web/src/components/StreakChart.tsx`, `web/src/components/StockStreakRow.tsx`; Modify `web/src/lib/types.ts`, `web/src/lib/stockTimeline.ts`(+`components/StockTimeline.tsx`) 타입 완화, `web/src/pages/ReviewPage.tsx` — Task 6
- Task 7 — 전체 검증(코드 변경 없음)

---

### Task 1: review_streaks — 스코프 조회·묶음 분할

**Files:**
- Create: `api/services/review_streaks.py`
- Test: `tests/test_api_review_streaks.py`

**Interfaces:**
- Produces: `REVIEW_COVERAGE_START: date` (#132 이후 정의는 `review_builder.py`, 여기선 re-export)
- Produces: `fetch_scoped_rows(conn, *, symbols: list[str]) -> list[dict]` — 스코프드 UNION(라이브 우선 dedup) 전 이력, dict 키: `symbol, key_date(date), classified_at(datetime), market, source, classification, pattern, pivot_price(float|None), backfilled(bool)`
- Produces: `find_period_symbols(conn, *, date_from: date, date_to: date, source: str|None, ticker: str|None) -> list[str]` — 기간 내 유효 행 보유 종목
- Produces: `segment_streaks(rows: list[dict]) -> list[dict]` — 입력은 한 종목의 정렬된 전 이력. 반환 streak dict: `symbol, start(date), end(date|None), closed_by("ignore"|"disqualify"|None), censored(bool), backfilled(bool — 유효 행 중 하나라도), has_gap(bool — 연속 유효 kd 간격>10일), analyses(list[dict] — 유효 행들, 각각 "triggers": [] 초기화)`
- Produces: `intersect_period(streaks, date_from, date_to) -> list[dict]` — start ≤ to AND (end is None OR end ≥ from)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_api_review_streaks.py` (fixture 관례: tests/test_api_review_builder.py 의 db·프리픽스 DELETE 패턴):

```python
from datetime import date, datetime, timedelta, timezone

import pytest

from api.services.review_streaks import (
    REVIEW_COVERAGE_START, fetch_scoped_rows, find_period_symbols,
    segment_streaks, intersect_period,
)

KST = timezone(timedelta(hours=9))


def _row(symbol, kd, cls, source, pivot=None, hour=10):
    return {
        "symbol": symbol, "key_date": date.fromisoformat(kd),
        "classified_at": datetime(2026, 1, 1, hour, tzinfo=KST).replace(
            year=int(kd[:4]), month=int(kd[5:7]), day=int(kd[8:10])),
        "market": "KOSPI", "source": source, "classification": cls,
        "pattern": None, "pivot_price": pivot, "backfilled": source == "backfill",
    }


def test_segment_closes_on_ignore_and_disqualify_and_continues_over_gap():
    rows = [
        _row("A", "2026-06-05", "watch", "weekend", 100.0),
        _row("A", "2026-06-12", "watch", "weekend", 110.0),
        # 20일 공백(>10일) — 이어짐 + has_gap
        _row("A", "2026-07-02", "entry", "daily_delta", 120.0),
        _row("A", "2026-07-04", "ignore", "weekend"),          # 닫힘 1
        _row("A", "2026-07-11", "watch", "weekend", 130.0),     # 새 묶음
        _row("A", "2026-07-15", "disqualified", "system_disqualify"),  # 닫힘 2
    ]
    s = segment_streaks(rows)
    assert len(s) == 2
    assert s[0]["start"] == date(2026, 6, 5)
    assert s[0]["end"] == date(2026, 7, 4) and s[0]["closed_by"] == "ignore"
    assert s[0]["has_gap"] is True and len(s[0]["analyses"]) == 3
    assert s[1]["start"] == date(2026, 7, 11)
    assert s[1]["end"] == date(2026, 7, 15) and s[1]["closed_by"] == "disqualify"
    assert s[1]["has_gap"] is False


def test_segment_open_streak_and_censored_badge():
    early = REVIEW_COVERAGE_START.isoformat()
    rows = [_row("B", early, "watch", "weekend", 50.0)]
    s = segment_streaks(rows)
    assert s[0]["end"] is None and s[0]["closed_by"] is None
    assert s[0]["censored"] is True          # 시작 ≤ COVERAGE_START+7d
    late = [_row("B", "2026-08-01", "watch", "weekend", 50.0)]
    assert segment_streaks(late)[0]["censored"] is False


def test_intersect_period_rules():
    s_before = {"start": date(2026, 6, 1), "end": date(2026, 6, 20), "closed_by": "ignore"}
    s_spanning = {"start": date(2026, 6, 1), "end": None, "closed_by": None}
    s_after = {"start": date(2026, 9, 1), "end": None, "closed_by": None}
    got = intersect_period([s_before, s_spanning, s_after],
                           date(2026, 7, 1), date(2026, 8, 1))
    assert got == [s_spanning]   # before: end<from 제외 / after: start>to 제외


@pytest.fixture
def seed(db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol LIKE 'RVSTK%'")
        cur.execute("DELETE FROM classification_backfill WHERE symbol LIKE 'RVSTK%'")
        cur.execute("DELETE FROM stocks WHERE ticker LIKE 'RVSTK%'")
        cur.execute("""INSERT INTO stocks (ticker, name, market, sector, listed_at)
                       VALUES ('RVSTK01','스톡1','KOSPI','반도체','2020-01-01')""")
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES
                 -- 전역 하한 이전 라이브 행 → 제외되어야 함
                 ('RVSTK01','2026-05-10 10:00:00+09','KOSPI','watch',NULL,90,'weekend','2026-05-08'),
                 ('RVSTK01','2026-06-06 10:00:00+09','KOSPI','watch',NULL,100,'weekend','2026-06-05')""")
        cur.execute(
            """INSERT INTO classification_backfill
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES
                 -- 하한 이전 백필 → 제외
                 ('RVSTK01','2026-08-01 10:00:00+09','KOSPI','watch',NULL,80,'backfill','2026-04-03'),
                 -- 하한 이후 백필, 라이브와 같은 key_date → 라이브 우선 dedup 제외
                 ('RVSTK01','2026-08-01 10:01:00+09','KOSPI','entry',NULL,999,'backfill','2026-06-05'),
                 -- 하한 이후 백필, 라이브 없음 → 유입 + backfilled=true
                 ('RVSTK01','2026-08-01 10:02:00+09','KOSPI','watch',NULL,105,'backfill','2026-06-19')""")
    db.commit()
    yield


def test_fetch_scoped_rows_global_floor_and_live_first_dedup(db, seed):
    rows = fetch_scoped_rows(db, symbols=["RVSTK01"])
    kds = [(r["key_date"].isoformat(), r["source"], r["backfilled"]) for r in rows]
    assert kds == [("2026-06-05", "weekend", False),      # 05-08 라이브 제외, 06-05 dedup 라이브 승
                   ("2026-06-19", "backfill", True)]      # 04-03 백필 제외
    assert rows[0]["pivot_price"] == 100.0                # 999(백필) 아님


def test_find_period_symbols_filters(db, seed):
    assert find_period_symbols(db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
                               source=None, ticker=None).count("RVSTK01") == 1
    assert "RVSTK01" not in find_period_symbols(
        db, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30), source=None, ticker=None)
    assert "RVSTK01" not in find_period_symbols(
        db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
        source="daily_delta", ticker=None)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_review_streaks.py -v`
Expected: FAIL — `ModuleNotFoundError: api.services.review_streaks`

- [ ] **Step 3: 구현**

`api/services/review_streaks.py`:

```python
"""/review 종목 행(streak) 뷰 조립 — 스펙 docs/superpowers/specs/2026-08-25-….md 가 원본.

핵심 규칙:
- 전역 하한 REVIEW_COVERAGE_START(라이브·백필 모두) — 이전 행은 산발 표본이라 제외.
- 묶음 종결 = ignore(모든 source) 또는 system_disqualify. 공백은 이어짐(>10일이면 has_gap).
- 좌측 절단 = 묶음 시작 ≤ 하한+7일.
"""
from __future__ import annotations

from datetime import date, timedelta

from psycopg import Connection
from psycopg.rows import dict_row

REVIEW_COVERAGE_START = date(2026, 5, 18)  # 라이브 weekly_classification 최초 key_date
_CENSOR_WINDOW = timedelta(days=7)
_GAP_DAYS = 10
_VALID_SOURCES = ("weekend", "daily_delta", "backfill")

_SCOPED_SQL = """
WITH live AS (
    SELECT symbol, classified_at, market, source, classification, pattern, pivot_price,
           COALESCE(analyzed_for_date, classified_at::date) AS key_date,
           false AS backfilled
      FROM weekly_classification
     WHERE symbol = ANY(%(symbols)s)
       AND COALESCE(analyzed_for_date, classified_at::date) >= %(floor)s
), bf AS (
    SELECT b.symbol, b.classified_at, b.market, b.source, b.classification, b.pattern,
           b.pivot_price, b.analyzed_for_date AS key_date, true AS backfilled
      FROM classification_backfill b
     WHERE b.symbol = ANY(%(symbols)s)
       AND b.analyzed_for_date >= %(floor)s
       -- 라이브 우선 dedup: 같은 (symbol, key_date)에 라이브가 있으면 백필 제외
       AND NOT EXISTS (SELECT 1 FROM live l
                        WHERE l.symbol = b.symbol AND l.key_date = b.analyzed_for_date)
)
SELECT * FROM live UNION ALL SELECT * FROM bf
ORDER BY symbol, key_date, classified_at
"""

_PERIOD_SYMBOLS_SQL = """
SELECT DISTINCT symbol FROM (
    SELECT symbol, source, classification,
           COALESCE(analyzed_for_date, classified_at::date) AS key_date
      FROM weekly_classification
    UNION ALL
    SELECT symbol, source, classification, analyzed_for_date FROM classification_backfill
) u
WHERE key_date BETWEEN GREATEST(%(date_from)s, %(floor)s) AND %(date_to)s
  AND classification IN ('entry', 'watch')
  AND source = ANY(%(sources)s)
  AND (%(ticker)s::text IS NULL OR symbol = %(ticker)s)
ORDER BY symbol
"""


def fetch_scoped_rows(conn: Connection, *, symbols: list[str]) -> list[dict]:
    if not symbols:
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SCOPED_SQL, {"symbols": symbols, "floor": REVIEW_COVERAGE_START})
        rows = cur.fetchall()
    for r in rows:
        r["pivot_price"] = float(r["pivot_price"]) if r["pivot_price"] is not None else None
    return rows


def find_period_symbols(conn: Connection, *, date_from: date, date_to: date,
                        source: str | None, ticker: str | None) -> list[str]:
    sources = [source] if source else list(_VALID_SOURCES)
    with conn.cursor() as cur:
        cur.execute(_PERIOD_SYMBOLS_SQL, {
            "date_from": date_from, "date_to": date_to, "floor": REVIEW_COVERAGE_START,
            "sources": sources, "ticker": ticker,
        })
        return [r[0] for r in cur.fetchall()]


def _is_valid(row: dict) -> bool:
    return row["classification"] in ("entry", "watch") and row["source"] in _VALID_SOURCES


def _closer_kind(row: dict) -> str | None:
    if row["classification"] == "ignore":
        return "ignore"
    if row["source"] == "system_disqualify":
        return "disqualify"
    return None


def segment_streaks(rows: list[dict]) -> list[dict]:
    """한 종목의 정렬된 전 이력 → streak 리스트 (스펙 §1)."""
    streaks: list[dict] = []
    cur: dict | None = None
    for row in rows:
        if _is_valid(row):
            row.setdefault("triggers", [])
            if cur is None:
                cur = {"symbol": row["symbol"], "start": row["key_date"], "end": None,
                       "closed_by": None, "has_gap": False, "backfilled": False,
                       "analyses": []}
            else:
                prev_kd = cur["analyses"][-1]["key_date"]
                if (row["key_date"] - prev_kd).days > _GAP_DAYS:
                    cur["has_gap"] = True
            cur["analyses"].append(row)
            cur["backfilled"] = cur["backfilled"] or row["backfilled"]
        else:
            kind = _closer_kind(row)
            if kind and cur is not None:
                cur["end"] = row["key_date"]
                cur["closed_by"] = kind
                streaks.append(cur)
                cur = None
            # 닫는 행인데 열린 묶음 없음 → 무시 (스펙 §6: 닫는 행만 있는 종목은 행 아님)
    if cur is not None:
        streaks.append(cur)
    for s in streaks:
        s["censored"] = s["start"] <= REVIEW_COVERAGE_START + _CENSOR_WINDOW
    return streaks


def intersect_period(streaks: list[dict], date_from: date, date_to: date) -> list[dict]:
    return [s for s in streaks
            if s["start"] <= date_to and (s["end"] is None or s["end"] >= date_from)]
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_api_review_streaks.py -v`
Expected: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add api/services/review_streaks.py tests/test_api_review_streaks.py
git commit -m "종목 행 뷰의 스코프 조회와 묶음 분할을 추가한다 — 전역 하한·라이브 우선·절단 배지"
```

---

### Task 2: review_streaks — 트리거 중첩·stage·성과

**Files:**
- Modify: `api/services/review_streaks.py`
- Test: `tests/test_api_review_streaks.py` (추가)

**Interfaces:**
- Consumes: Task 1 streak dict / `review_builder`의 `chain_tn(series, d, pivot_delta, n)`·`max_reach(series, key_date, next_key_date, pivot, *, today)`·`first_breakout(triggers)`·`corp_action_flags(conn, pairs, *, today)`·`BREAKOUT_TYPES`.
- Produces: `attach_triggers(conn, streaks: list[dict]) -> None` — 각 analysis["triggers"] 에 prior 직접 조인 결과(dict: evaluated_at, d(date), trigger_type, decision, close, pivot_price, reasoning) 채움.
- Produces: `derive_stage(streak) -> str` — "breakout"|"staging"|"watching"|"base_forming" (스펙 §2 표).
- Produces: `compute_metrics(streak, series: list[tuple[date, float]], *, today: date, corp_flagged: bool) -> dict` — `{stage, t5_pct, t20_pct, max_reach_pct, corp_action_flag, first_breakout_at}` (버킷별 해당 없는 값은 None).

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_api_review_streaks.py` 추가)

```python
from api.services.review_streaks import attach_triggers, derive_stage, compute_metrics


def _trig(d, ttype, close=None, pivot=None):
    return {"d": date.fromisoformat(d), "trigger_type": ttype, "decision": "wait",
            "close": close, "pivot_price": pivot, "reasoning": None,
            "evaluated_at": datetime(2026, 6, 1, 21, tzinfo=KST)}


def _streak(analyses, triggers_by_idx=None):
    for i, a in enumerate(analyses):
        a["triggers"] = (triggers_by_idx or {}).get(i, [])
    return {"symbol": "A", "start": analyses[0]["key_date"], "end": None,
            "closed_by": None, "censored": False, "backfilled": False,
            "has_gap": False, "analyses": analyses}


def test_derive_stage_four_buckets():
    a_pivot = _row("A", "2026-06-05", "watch", "weekend", 100.0)
    a_nopivot = _row("A", "2026-06-05", "watch", "weekend", None)
    assert derive_stage(_streak([dict(a_pivot)], {0: [_trig("2026-06-10", "breakout_from_watch", 102, 100)]})) == "breakout"
    assert derive_stage(_streak([dict(a_pivot)], {0: [_trig("2026-06-10", "promotion")]})) == "staging"
    assert derive_stage(_streak([dict(a_pivot)])) == "watching"
    assert derive_stage(_streak([dict(a_nopivot)])) == "base_forming"
    # invalidation만 있으면 staging 아님 → watching(pivot 있음)
    assert derive_stage(_streak([dict(a_pivot)], {0: [_trig("2026-06-10", "invalidation")]})) == "watching"


def test_compute_metrics_breakout_chain_and_watching_reach():
    series = [(date(2026, 6, 10), 100.0), (date(2026, 6, 11), 104.0),
              (date(2026, 6, 12), 108.0), (date(2026, 6, 15), 112.0),
              (date(2026, 6, 16), 116.0), (date(2026, 6, 17), 120.0)]
    a = _row("A", "2026-06-05", "watch", "weekend", 100.0)
    st = _streak([dict(a)], {0: [_trig("2026-06-10", "breakout_from_watch", close=102.0, pivot=100.0)]})
    m = compute_metrics(st, series, today=date(2026, 6, 30), corp_flagged=False)
    # pivot_delta=2%; T+5 = 1.02×120/100−1 = 0.224
    assert m["stage"] == "breakout" and abs(m["t5_pct"] - 0.224) < 1e-9
    assert m["t20_pct"] is None and m["first_breakout_at"] == date(2026, 6, 10)
    st2 = _streak([dict(a)])
    m2 = compute_metrics(st2, series, today=date(2026, 6, 30), corp_flagged=True)
    # watching: 마지막 pivot(100), 창 (06-05, 오늘] → max 120 → +20%
    assert m2["stage"] == "watching" and abs(m2["max_reach_pct"] - 0.20) < 1e-9
    assert m2["corp_action_flag"] is True and m2["t5_pct"] is None


@pytest.fixture
def seed_trigger(db, seed):
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol LIKE 'RVSTK%'")
        cur.execute(
            """INSERT INTO trigger_evaluation_log
                 (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                  decision, reasoning, prior_classification_at, analyzed_for_date)
               VALUES ('RVSTK01','2026-06-08 21:00:00+09','promotion',98,1000,100,
                       'wait','접근','2026-06-06 10:00:00+09','2026-06-08')""")
    db.commit()
    yield


def test_attach_triggers_nested_by_prior(db, seed_trigger):
    rows = fetch_scoped_rows(db, symbols=["RVSTK01"])
    streaks = segment_streaks(rows)
    attach_triggers(db, streaks)
    a0 = streaks[0]["analyses"][0]           # 06-05 라이브 분석
    assert len(a0["triggers"]) == 1
    assert a0["triggers"][0]["trigger_type"] == "promotion"
    assert a0["triggers"][0]["d"] == date(2026, 6, 8)
    # 백필 분석(06-19)에는 트리거 없음
    assert streaks[0]["analyses"][1]["triggers"] == []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_review_streaks.py -v -k "stage or metrics or attach"`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현** (`review_streaks.py` 추가)

```python
from api.services.review_builder import (  # 파일 상단 import 절에 추가
    BREAKOUT_TYPES, chain_tn, corp_action_flags, first_breakout, max_reach,
)

_TRIGGERS_SQL = """
SELECT t.symbol, t.prior_classification_at, t.evaluated_at, t.trigger_type,
       t.decision, t.close, t.pivot_price, t.reasoning,
       COALESCE(t.analyzed_for_date,
                (t.evaluated_at AT TIME ZONE 'UTC')::date) AS d
  FROM trigger_evaluation_log t
  JOIN unnest(%(syms)s::text[], %(ats)s::timestamptz[]) AS k(symbol, classified_at)
    ON t.symbol = k.symbol AND t.prior_classification_at = k.classified_at
 ORDER BY d, t.evaluated_at
"""


def attach_triggers(conn: Connection, streaks: list[dict]) -> None:
    """prior_classification_at 직접 조인 — 분석별 중첩 (review_builder 와 동일 규칙.
    SQL 을 복제하는 이유: review_builder 무수정 계약(스펙 §4) — 사설 상수 import 회피."""
    index: dict[tuple, dict] = {}
    for s in streaks:
        for a in s["analyses"]:
            a["triggers"] = []
            index[(a["symbol"], a["classified_at"])] = a
    if not index:
        return
    syms = [k[0] for k in index]
    ats = [k[1] for k in index]
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_TRIGGERS_SQL, {"syms": syms, "ats": ats})
        for t in cur.fetchall():
            t["close"] = float(t["close"]) if t["close"] is not None else None
            t["pivot_price"] = float(t["pivot_price"]) if t["pivot_price"] is not None else None
            index[(t["symbol"], t["prior_classification_at"])]["triggers"].append(t)


def _streak_triggers(streak: dict) -> list[dict]:
    return [t for a in streak["analyses"] for t in a["triggers"]]


def derive_stage(streak: dict) -> str:
    trigs = _streak_triggers(streak)
    if any(t["trigger_type"] in BREAKOUT_TYPES for t in trigs):
        return "breakout"
    if any(t["trigger_type"] == "promotion" for t in trigs):
        return "staging"
    if any(a["pivot_price"] is not None for a in streak["analyses"]):
        return "watching"
    return "base_forming"


def _last_pivot_analysis(streak: dict) -> dict | None:
    for a in reversed(streak["analyses"]):
        if a["pivot_price"] is not None:
            return a
    return None


def compute_metrics(streak: dict, series: list[tuple[date, float]], *,
                    today: date, corp_flagged: bool) -> dict:
    stage = derive_stage(streak)
    out = {"stage": stage, "t5_pct": None, "t20_pct": None, "max_reach_pct": None,
           "corp_action_flag": False, "first_breakout_at": None}
    if stage == "breakout":
        fb = first_breakout(_streak_triggers(streak))
        out["first_breakout_at"] = fb["d"]
        if fb["close"] and fb["pivot_price"]:
            delta = (fb["close"] - fb["pivot_price"]) / fb["pivot_price"]
            out["t5_pct"] = chain_tn(series, fb["d"], delta, 5)
            out["t20_pct"] = chain_tn(series, fb["d"], delta, 20)
    elif stage in ("staging", "watching"):
        anchor = _last_pivot_analysis(streak)
        if anchor is not None:
            out["max_reach_pct"] = max_reach(
                series, anchor["key_date"], streak["end"], anchor["pivot_price"],
                today=today)
            out["corp_action_flag"] = corp_flagged
    return out
```

주의: `derive_stage`가 staging 이어도 pivot 없는 analyses 뿐이면 `_last_pivot_analysis`가 None → max_reach 없음(숫자 전부 None, stage="staging") — 스펙 §2 표의 조건 순서 그대로.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_api_review_streaks.py -v`
Expected: 전부 passed (Task 1 포함 누적 8개)

- [ ] **Step 5: 커밋**

```bash
git add api/services/review_streaks.py tests/test_api_review_streaks.py
git commit -m "묶음의 트리거 중첩과 stage 4분류·pivot 성과를 추가한다"
```

---

### Task 3: review_streaks — 시계열·pivot 계단·응답 조립

**Files:**
- Modify: `api/services/review_streaks.py`
- Test: `tests/test_api_review_streaks.py` (추가)

**Interfaces:**
- Consumes: Task 1·2 전부 + `review_builder.fetch_price_series(conn, symbol, start, end)`·`count_orphan_triggers(conn, *, date_from, date_to)`.
- Produces: `chart_window_start(conn, symbol: str, earliest_start: date) -> date` — earliest_start 직전 120거래일(행 기준 OFFSET 119), 부족하면 그 종목 최초 행 날짜, 행 없으면 earliest_start.
- Produces: `build_pivot_steps(streaks: list[dict]) -> list[tuple[date, date|None, float]]` — (from_kd, to_kd|None, pivot). 경계 = 같은 묶음 내 다음 분석 kd 또는 **묶음 end**(닫는 행 kd — 스펙 §3 ②). pivot 없는 분석은 구간을 만들지 않음(직전 계단은 그 분석 kd 에서 끊김).
- Produces: `build_stock_rows(conn, *, date_from: date, date_to: date, source: str|None, ticker: str|None, status: str|None, limit: int, offset: int, today: date) -> dict` — `{"rows": [...], "orphan_trigger_count": int}` (스펙 §4 응답 모양의 dict 버전 — 라우터가 pydantic 으로 감쌈). status 필터·정렬(최근 묶음 시작 내림차순)·슬라이스는 전체 계산 후 Python 적용.

- [ ] **Step 1: 실패하는 테스트 작성** (추가)

```python
from api.services.review_streaks import (
    build_pivot_steps, build_stock_rows, chart_window_start,
)


def test_build_pivot_steps_cuts_at_streak_close():
    a1 = _row("A", "2026-06-05", "watch", "weekend", 100.0)
    a2 = _row("A", "2026-06-12", "watch", "weekend", 110.0)
    a3 = _row("A", "2026-07-11", "watch", "weekend", None)     # pivot 없음
    a4 = _row("A", "2026-07-18", "watch", "weekend", 130.0)
    s1 = _streak([a1, a2]); s1["end"] = date(2026, 6, 20); s1["closed_by"] = "ignore"
    s2 = _streak([a3, a4])
    steps = build_pivot_steps([s1, s2])
    assert steps == [
        (date(2026, 6, 5), date(2026, 6, 12), 100.0),
        (date(2026, 6, 12), date(2026, 6, 20), 110.0),   # 닫는 행에서 끊김 (07-11 아님)
        (date(2026, 7, 18), None, 130.0),                 # 진행중 → to_kd None
    ]


@pytest.fixture
def seed_prices(db, seed_trigger):
    with db.cursor() as cur:
        cur.execute("DELETE FROM daily_prices WHERE ticker LIKE 'RVSTK%'")
        cur.execute(
            """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                                         adj_close, volume, value)
               SELECT 'RVSTK01', d::date, 1,1,1,1, 100 + row_number() OVER (), 1000, 1000
                 FROM generate_series('2026-05-20'::date, '2026-08-20', '1 day') d
                WHERE extract(isodow FROM d) < 6""")
    db.commit()
    yield


def test_chart_window_start_offset_and_clamp(db, seed_prices):
    # 06-05 직전 120거래일이 없으면(5/20 시작) 최초 행으로 클램프
    assert chart_window_start(db, "RVSTK01", date(2026, 6, 5)) == date(2026, 5, 20)
    assert chart_window_start(db, "NOROWS", date(2026, 6, 5)) == date(2026, 6, 5)


def test_build_stock_rows_end_to_end(db, seed_prices):
    got = build_stock_rows(db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
                           source=None, ticker="RVSTK01", status=None,
                           limit=200, offset=0, today=date(2026, 8, 20))
    assert len(got["rows"]) == 1
    row = got["rows"][0]
    assert row["latest"]["stage"] == "staging"          # promotion 만 존재
    assert row["latest"]["streak_count"] == 1
    assert row["streaks"][0]["analyses"][1]["backfilled"] is True
    assert row["series"][0][0] == date(2026, 5, 20)     # 클램프된 창 시작
    assert row["pivot_steps"][0][2] == 100.0
    # (I1) 표시 클램프: 응답 series·analyses 는 to(06-30) 이하만
    assert row["series"][-1][0] <= date(2026, 6, 30)
    assert all(a["key_date"] <= date(2026, 6, 30)
               for s in row["streaks"] for a in s["analyses"])
    # (I2) metrics 는 오늘(08-20)까지의 데이터 사용 — 6월 말까지의 도달률(~+30%)로는
    # 불가능한 값이어야 함 (가격이 하루 +1 씩 8월까지 상승하는 픽스처)
    assert row["latest"]["max_reach_pct"] > 0.5
    # status 필터: open 만 → 포함 / closed → 제외
    assert build_stock_rows(db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
                            source=None, ticker="RVSTK01", status="closed",
                            limit=200, offset=0, today=date(2026, 8, 20))["rows"] == []


def test_display_clamp_keeps_closed_by(db, seed_prices):
    # 닫는 행(ignore)을 to 이후(07-10)에 심으면: end 는 to 로 절단되되 status 는 closed
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES ('RVSTK01','2026-07-10 10:00:00+09','KOSPI','ignore',NULL,
                       NULL,'weekend','2026-07-10')""")
    db.commit()
    got = build_stock_rows(db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30),
                           source=None, ticker="RVSTK01", status=None,
                           limit=200, offset=0, today=date(2026, 8, 20))
    row = got["rows"][0]
    assert row["latest"]["status"] == "closed"                      # 원본 기준
    assert row["streaks"][0]["closed_by"] == "ignore"               # 유지
    assert row["streaks"][0]["end"] == date(2026, 6, 30)            # 표시 절단
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_review_streaks.py -v -k "steps or window or end_to_end"`
Expected: FAIL — ImportError

- [ ] **Step 3: 구현** (`review_streaks.py` 추가)

```python
from api.services.review_builder import count_orphan_triggers, fetch_price_series  # import 절 추가

_WINDOW_SQL = """
SELECT date FROM daily_prices
 WHERE ticker = %(symbol)s AND date < %(before)s
 ORDER BY date DESC OFFSET 119 LIMIT 1
"""
_FIRST_ROW_SQL = "SELECT min(date) FROM daily_prices WHERE ticker = %(symbol)s"


def chart_window_start(conn: Connection, symbol: str, earliest_start: date) -> date:
    with conn.cursor() as cur:
        cur.execute(_WINDOW_SQL, {"symbol": symbol, "before": earliest_start})
        r = cur.fetchone()
        if r:
            return r[0]
        cur.execute(_FIRST_ROW_SQL, {"symbol": symbol})
        first = cur.fetchone()[0]
    return first or earliest_start


def _clamp_display(streak: dict, date_to: date) -> dict:
    """(I1) 표시용 to 절단 — 스펙 §1. metrics·closed_by 는 원본 유지."""
    s = dict(streak)
    s["analyses"] = [
        dict(a, triggers=[t for t in a["triggers"] if t["d"] <= date_to])
        for a in streak["analyses"] if a["key_date"] <= date_to
    ]
    if s["end"] is not None and s["end"] > date_to:
        s["end"] = date_to          # closed_by 는 그대로 (스펙 §1)
    return s


def build_pivot_steps(streaks: list[dict]) -> list[tuple[date, date | None, float]]:
    steps: list[tuple[date, date | None, float]] = []
    for s in streaks:
        analyses = s["analyses"]
        for i, a in enumerate(analyses):
            if a["pivot_price"] is None:
                continue
            if i + 1 < len(analyses):
                boundary: date | None = analyses[i + 1]["key_date"]
            else:
                boundary = s["end"]          # 닫는 행 kd, 진행중이면 None (스펙 §3 ②)
            steps.append((a["key_date"], boundary, a["pivot_price"]))
    return steps


def build_stock_rows(conn: Connection, *, date_from: date, date_to: date,
                     source: str | None, ticker: str | None, status: str | None,
                     limit: int, offset: int, today: date) -> dict:
    symbols = find_period_symbols(conn, date_from=date_from, date_to=date_to,
                                  source=source, ticker=ticker)
    all_rows = fetch_scoped_rows(conn, symbols=symbols)
    by_symbol: dict[str, list[dict]] = {}
    for r in all_rows:
        by_symbol.setdefault(r["symbol"], []).append(r)

    displayed: list[dict] = []
    for sym, rows in by_symbol.items():
        streaks = intersect_period(segment_streaks(rows), date_from, date_to)
        if streaks:
            displayed.append({"symbol": sym, "market": rows[0]["market"],
                              "streaks": streaks})
    flat = [s for d in displayed for s in d["streaks"]]
    attach_triggers(conn, flat)
    flags = corp_action_flags(
        conn,
        [(s["symbol"], a["key_date"]) for s in flat
         for a in ([_last_pivot_analysis(s)] if _last_pivot_analysis(s) else [])],
        today=today)

    out_rows = []
    for d in displayed:
        streaks = d["streaks"]
        earliest = min(s["start"] for s in streaks)
        w_start = chart_window_start(conn, d["symbol"], earliest)
        # (I2) metrics 창은 "오늘까지"(스펙 §2) — 과거 to 조회에서도 도달률이
        # 과소평가되지 않도록 오늘까지 fetch. 응답 series 는 아래 클램프에서 to 로 슬라이스.
        series = fetch_price_series(conn, d["symbol"], w_start, max(date_to, today))
        for s in streaks:
            anchor = _last_pivot_analysis(s)
            corp = anchor is not None and (d["symbol"], anchor["key_date"]) in flags
            s["metrics"] = compute_metrics(s, series, today=today, corp_flagged=corp)
            s["stage"] = s["metrics"]["stage"]
        latest = max(streaks, key=lambda s: s["start"])
        out_rows.append({
            "symbol": d["symbol"], "market": d["market"],
            "latest": {
                "status": "open" if latest["closed_by"] is None else "closed",
                "closed_by": latest["closed_by"], **latest["metrics"],
                "censored": latest["censored"], "backfilled": latest["backfilled"],
                "streak_count": len(streaks),
            },
            "streaks": streaks, "series": series,
            "pivot_steps": build_pivot_steps(streaks),
            "_sort_key": latest["start"],
        })

    for r in out_rows:  # (I1) 표시 클램프 — 스펙 §1 "to 절단": 응답의 analyses/트리거/end/
        # pivot_steps 는 date_to 로 자르되 closed_by·status·metrics 는 원본(오늘 기준) 유지
        r["streaks"] = [_clamp_display(s, date_to) for s in r["streaks"]]
        r["pivot_steps"] = build_pivot_steps(r["streaks"])
        r["series"] = [p for p in r["series"] if p[0] <= date_to]

    if status:  # 원본 종결 기준 (스펙 §4) — 전체 계산 후 Python 필터
        out_rows = [r for r in out_rows if r["latest"]["status"] == status]
    out_rows.sort(key=lambda r: r["_sort_key"], reverse=True)
    out_rows = out_rows[offset:offset + limit]
    for r in out_rows:
        r.pop("_sort_key")

    orphans = count_orphan_triggers(conn, date_from=date_from, date_to=date_to)
    return {"rows": out_rows, "orphan_trigger_count": orphans}
```

참고: `name`은 라우터에서 stocks JOIN 으로 채운다(Task 4 — 조회 1회).

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_api_review_streaks.py -v`
Expected: 전부 passed (누적 12개 — Task 3 은 클램프 테스트 포함 4개 추가)

- [ ] **Step 5: 커밋**

```bash
git add api/services/review_streaks.py tests/test_api_review_streaks.py
git commit -m "묶음 시계열 창·pivot 계단·종목 행 응답 조립을 추가한다"
```

---

### Task 4: 라우터 GET /api/review/stocks

**Files:**
- Modify: `api/schemas/review.py` (클래스 추가), `api/routers/review.py` (엔드포인트 추가)
- Test: `tests/test_api_review_stocks_router.py`

**Interfaces:**
- Consumes: `build_stock_rows(...)` (Task 3 시그니처 그대로).
- Produces: `GET /api/review/stocks` — 응답 스키마(스펙 §4):
  `StreakAnalysisOut(symbol, key_date, classified_at, source, classification, pattern, pivot_price, backfilled, triggers: list[ReviewTriggerOut])` /
  `StreakOut(start, end, closed_by, censored, backfilled, has_gap, stage, analyses, metrics: StreakMetricsOut)` /
  `StreakMetricsOut(stage, t5_pct, t20_pct, max_reach_pct, corp_action_flag, first_breakout_at)` /
  `StockRowOut(symbol, name, market, latest: StockLatestOut, streaks, series: list[tuple[date, float]], pivot_steps: list[tuple[date, date|None, float]])` /
  `StockLatestOut(status, closed_by, stage, t5_pct, t20_pct, max_reach_pct, corp_action_flag, first_breakout_at, censored, backfilled, streak_count)` /
  `StockRowsResponse(rows, orphan_trigger_count)`.
  파라미터: `from`(alias)·`to`·`source`·`ticker`·`status`·`limit=Query(default=200, ge=0)`·`offset=Query(default=0, ge=0)`; `limit = min(limit, 500)`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_api_review_stocks_router.py` — client/override 패턴은 `tests/test_api_review_router.py` 와 동일. ⚠️ **날짜는 10월대 사용** — 6월(`test_api_review_builder.py` 의 RVTEST02 고아 6/4 커밋 지뢰)·7월 초중순(기존 라우터 테스트)·7/21·7/24(트리거 게이트 테스트) 구간은 다른 픽스처가 커밋을 남겨 오염됨. 완전한 seed:

```python
@pytest.fixture
def seed(db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    with db.cursor() as cur:
        for tbl, col in [("trigger_evaluation_log", "symbol"),
                         ("weekly_classification", "symbol"),
                         ("daily_prices", "ticker"), ("stocks", "ticker")]:
            cur.execute(f"DELETE FROM {tbl} WHERE {col} LIKE 'RVSAPI%'")
        cur.execute("""INSERT INTO stocks (ticker, name, market, sector, listed_at)
                       VALUES ('RVSAPI01','에이피','KOSPI','반도체','2020-01-01')""")
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES ('RVSAPI01','2026-10-05 10:00:00+09','KOSPI','watch',
                       'cup_with_handle', 100, 'weekend', '2026-10-05')""")
        cur.execute(
            """INSERT INTO trigger_evaluation_log
                 (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                  decision, reasoning, prior_classification_at, analyzed_for_date)
               VALUES ('RVSAPI01','2026-10-07 21:00:00+09','promotion',
                       98, 1000, 100, 'wait', '접근',
                       '2026-10-05 10:00:00+09', '2026-10-07')""")
        cur.execute(
            """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                                         adj_close, volume, value)
               SELECT 'RVSAPI01', d::date, 1,1,1,1,
                      90 + row_number() OVER (), 1000, 1000
                 FROM generate_series('2026-09-28'::date, '2026-10-30', '1 day') d
                WHERE extract(isodow FROM d) < 6""")
    db.commit()
    yield
    app.dependency_overrides.pop(get_conn, None)


def test_stocks_endpoint_shape_and_filters(client, seed):
    r = client.get("/api/review/stocks?from=2026-10-01&to=2026-10-31&ticker=RVSAPI01")
    assert r.status_code == 200
    body = r.json()
    assert body["orphan_trigger_count"] == 0
    row = body["rows"][0]
    assert row["name"] == "에이피"                     # stocks JOIN
    assert row["latest"]["stage"] == "staging"
    assert row["streaks"][0]["analyses"][0]["triggers"][0]["trigger_type"] == "promotion"
    assert row["pivot_steps"][0][2] == 100.0
    # status·음수 방어
    assert client.get("/api/review/stocks?status=closed&ticker=RVSAPI01"
                      "&from=2026-10-01&to=2026-10-31").json()["rows"] == []
    assert client.get("/api/review/stocks?limit=-1").status_code == 422
    assert client.get("/api/review/stocks?limit=9999").status_code == 200
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_api_review_stocks_router.py -v` / Expected: 404

- [ ] **Step 3: 구현**

`api/schemas/review.py` 에 위 Interfaces 의 pydantic 클래스 6개 추가(필드·타입 그대로, 전부 `BaseModel`, Optional 은 `| None = None`). `api/routers/review.py` 에:

```python
from api.schemas.review import StockRowsResponse
from api.services.review_streaks import build_stock_rows


@router.get("/stocks", response_model=StockRowsResponse)
def list_stocks(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    source: str | None = None,
    ticker: str | None = None,
    status: str | None = None,
    limit: int = Query(default=200, ge=0),
    offset: int = Query(default=0, ge=0),
    conn: Connection = Depends(get_conn),
):
    today = date.today()
    date_to = to or today
    date_from = from_ or (date_to - timedelta(days=28))
    limit = min(limit, 500)
    result = build_stock_rows(conn, date_from=date_from, date_to=date_to,
                              source=source, ticker=ticker, status=status,
                              limit=limit, offset=offset, today=today)
    names = {}
    if result["rows"]:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker, name FROM stocks WHERE ticker = ANY(%s)",
                        ([r["symbol"] for r in result["rows"]],))
            names = dict(cur.fetchall())
    for r in result["rows"]:
        r["name"] = names.get(r["symbol"])
    return StockRowsResponse(**result)
```

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_api_review_stocks_router.py tests/test_api_review_streaks.py -v` / Expected: 전부 passed
- [ ] **Step 5: 커밋**

```bash
git add api/schemas/review.py api/routers/review.py tests/test_api_review_stocks_router.py
git commit -m "종목 행 회고 API 를 추가한다 — GET /api/review/stocks"
```

---

### Task 5: 프론트 좌표 계산 순수 함수 (streakChart)

**Files:**
- Create: `web/src/lib/streakChart.ts`, `web/src/lib/streakChart.test.ts`

**Interfaces:**
- Produces:
```typescript
export type TriggerKind = "breakout" | "promotion" | "invalidation";
export function triggerColor(triggerType: string): string;
// breakout|breakout_from_watch → "#16a34a"(초록), promotion → "#f59e0b"(노랑),
// invalidation·기타 → "#9ca3af"(회색) — trigger_type 축 매핑 (DecisionPill 재사용 금지)

export interface StreakBandIn { start: string; end: string | null;
  closed_by: "ignore" | "disqualify" | null; censored: boolean;
  backfilled: boolean; has_gap: boolean; }
export interface ChartIn { width: number; height: number; to: string;
  series: [string, number][];                      // 오름차순 (date, adj_close)
  pivotSteps: [string, string | null, number][];   // (from, to|null, pivot)
  streaks: StreakBandIn[];
  triggers: { d: string; trigger_type: string }[]; }
export interface ChartOut {
  pricePoints: string;                              // polyline points
  steps: { x1: number; x2: number; y: number }[];
  bands: { x1: number; x2: number; dashed: boolean;
           marker: "x" | "o" | null; censored: boolean }[];
  dots: { x: number; y: number; color: string }[]; }
export function buildChart(input: ChartIn): ChartOut;
```
- x 스케일 = **series 인덱스 기준**(거래일 등간격 — 휴장 공백 없음), 날짜→x 는 이분 탐색으로 가장 가까운 거래일 인덱스. y 스케일 = series 값 ∪ pivot 값의 min/max. 진행중 streak/step 의 끝 = 차트 우측 끝.

- [ ] **Step 1: 실패하는 테스트 작성** (`web/src/lib/streakChart.test.ts`, 기존 lib/*.test.ts vitest 관례)

```typescript
import { describe, expect, it } from "vitest";
import { buildChart, triggerColor } from "./streakChart";

const series: [string, number][] = [
  ["2026-06-01", 100], ["2026-06-02", 102], ["2026-06-03", 101],
  ["2026-06-04", 105], ["2026-06-05", 110],
];

describe("triggerColor", () => {
  it("trigger_type 축 매핑 — decision 축 아님", () => {
    expect(triggerColor("breakout")).toBe("#16a34a");
    expect(triggerColor("breakout_from_watch")).toBe("#16a34a");
    expect(triggerColor("promotion")).toBe("#f59e0b");
    expect(triggerColor("invalidation")).toBe("#9ca3af");
  });
});

describe("buildChart", () => {
  const base = { width: 100, height: 40, to: "2026-06-05", series,
    pivotSteps: [["2026-06-02", "2026-06-04", 104] as [string, string | null, number]],
    streaks: [{ start: "2026-06-02", end: "2026-06-04", closed_by: "ignore" as const,
                censored: false, backfilled: false, has_gap: false }],
    triggers: [{ d: "2026-06-03", trigger_type: "promotion" }] };

  it("가격 폴리라인은 5점, x 는 인덱스 등간격", () => {
    const out = buildChart(base);
    expect(out.pricePoints.split(" ")).toHaveLength(5);
    expect(out.pricePoints.startsWith("0.0,")).toBe(true); // toFixed(1) → "0.0"
  });
  it("계단·띠·점의 x 범위가 날짜에 대응하고 닫힘 마커가 붙는다", () => {
    const out = buildChart(base);
    expect(out.steps).toHaveLength(1);
    expect(out.steps[0].x1).toBeLessThan(out.steps[0].x2);
    expect(out.bands[0].marker).toBe("o");        // ignore → ○
    expect(out.dots[0].color).toBe("#f59e0b");
  });
  it("진행중 streak 는 우측 끝까지, disqualify 는 x 마커", () => {
    const out = buildChart({ ...base,
      streaks: [{ start: "2026-06-02", end: null, closed_by: null,
                  censored: true, backfilled: false, has_gap: true }] });
    expect(out.bands[0].x2).toBe(100);
    expect(out.bands[0].marker).toBeNull();
    expect(out.bands[0].dashed).toBe(true);       // has_gap → 점선
    expect(out.bands[0].censored).toBe(true);
    const closed = buildChart({ ...base,
      streaks: [{ start: "2026-06-02", end: "2026-06-04",
                  closed_by: "disqualify" as const,
                  censored: false, backfilled: false, has_gap: false }] });
    expect(closed.bands[0].marker).toBe("x");     // 실격 → ✕ (스펙 §3 회귀 가드)
  });
});
```

- [ ] **Step 2: 실패 확인** — Run: `cd web && npx vitest run src/lib/streakChart.test.ts` / Expected: FAIL(모듈 없음)
- [ ] **Step 3: 구현** (`web/src/lib/streakChart.ts`)

```typescript
export type TriggerKind = "breakout" | "promotion" | "invalidation";

const GREEN = "#16a34a";
const AMBER = "#f59e0b";
const GRAY = "#9ca3af";

export function triggerColor(triggerType: string): string {
  if (triggerType === "breakout" || triggerType === "breakout_from_watch") return GREEN;
  if (triggerType === "promotion") return AMBER;
  return GRAY;
}

export interface StreakBandIn { start: string; end: string | null;
  closed_by: "ignore" | "disqualify" | null; censored: boolean;
  backfilled: boolean; has_gap: boolean; }
export interface ChartIn { width: number; height: number; to: string;
  series: [string, number][]; pivotSteps: [string, string | null, number][];
  streaks: StreakBandIn[]; triggers: { d: string; trigger_type: string }[]; }
export interface ChartOut {
  pricePoints: string;
  steps: { x1: number; x2: number; y: number }[];
  bands: { x1: number; x2: number; dashed: boolean;
           marker: "x" | "o" | null; censored: boolean }[];
  dots: { x: number; y: number; color: string }[]; }

export function buildChart(input: ChartIn): ChartOut {
  const { width, height, series } = input;
  const n = series.length;
  if (n < 2) return { pricePoints: "", steps: [], bands: [], dots: [] };
  const values = series.map(([, v]) => v);
  const pivots = input.pivotSteps.map(([, , p]) => p);
  const min = Math.min(...values, ...(pivots.length ? pivots : [Infinity]));
  const max = Math.max(...values, ...(pivots.length ? pivots : [-Infinity]));
  const span = max - min || 1;
  const x = (i: number) => (i / (n - 1)) * width;
  const y = (v: number) => height - ((v - min) / span) * height;
  // 날짜 → 가장 가까운(같거나 직전) 거래일 인덱스
  const idx = (d: string) => {
    let lo = 0, hi = n - 1, ans = 0;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (series[mid][0] <= d) { ans = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return ans;
  };
  const pricePoints = series
    .map(([, v], i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const steps = input.pivotSteps.map(([from, to, pivot]) => ({
    x1: x(idx(from)), x2: to == null ? width : x(idx(to)), y: y(pivot) }));
  const bands = input.streaks.map((s) => ({
    x1: x(idx(s.start)),
    x2: s.end == null ? width : x(idx(s.end)),
    dashed: s.has_gap || s.backfilled,
    marker: s.closed_by == null ? null : s.closed_by === "disqualify" ? "x" as const : "o" as const,
    censored: s.censored }));
  const dots = input.triggers.map((t) => ({
    x: x(idx(t.d)), y: y(series[idx(t.d)][1]), color: triggerColor(t.trigger_type) }));
  return { pricePoints, steps, bands, dots };
}
```

- [ ] **Step 4: 통과 확인** — Run: `cd web && npx vitest run` / Expected: 기존 + 신규 전부 통과
- [ ] **Step 5: 커밋**

```bash
git add web/src/lib/streakChart.ts web/src/lib/streakChart.test.ts
git commit -m "묶음 차트 좌표 계산 순수 함수를 추가한다 — trigger_type 색 매핑 포함"
```

---

### Task 6: 프론트 컴포넌트·페이지 통합

**Files:**
- Create: `web/src/components/StreakChart.tsx`, `web/src/components/StockStreakRow.tsx`
- Modify: `web/src/lib/types.ts`(응답 타입), `web/src/lib/stockTimeline.ts` + `web/src/components/StockTimeline.tsx`(입력 타입을 구조적 최소 인터페이스 `TimelineRow` 로 완화 — ReviewRow 는 이를 자동 충족, #127 동작 불변), `web/src/pages/ReviewPage.tsx`

**Interfaces:**
- Consumes: Task 4 응답(`StockRowsResponse` — TS 미러 타입 `StockRow`·`Streak`·`StreakAnalysis`·`StreakMetrics`·`StockLatest` 를 types.ts 에 1:1 추가), Task 5 `buildChart`/`triggerColor`, #127 `StockTimeline`.
- Produces: ReviewPage 라우팅 — **기본 뷰 = 종목 행**, `view=analysis` → 기존 분석 표, 구 `view=timeline` 은 무시되어 기본 뷰(에러 없음, 스펙 §5).

- [ ] **Step 1: types.ts 에 응답 타입 추가** — Task 4 Interfaces 의 6개 스키마를 TS 로 1:1 미러(`StreakAnalysis` 는 `triggers: ReviewTrigger[]` 포함).

- [ ] **Step 2: StreakChart.tsx** — `buildChart` 결과를 SVG 로 렌더:

```tsx
import { buildChart, type ChartIn } from "../lib/streakChart";

export default function StreakChart(props: Omit<ChartIn, "width" | "height">) {
  const width = 420, height = 64, bandY = height + 6;
  const out = buildChart({ ...props, width, height });
  if (!out.pricePoints) return <span className="text-faint">—</span>;
  return (
    <svg width={width} height={height + 14} className="block">
      {out.steps.map((s, i) => (
        <line key={`s${i}`} x1={s.x1} x2={s.x2} y1={s.y} y2={s.y}
              stroke="#9ca3af" strokeDasharray="4 3" strokeWidth={1.2} />))}
      <polyline points={out.pricePoints} fill="none" stroke="#2563eb" strokeWidth={1.4} />
      {out.bands.map((b, i) => (
        <g key={`b${i}`}>
          <line x1={b.x1} x2={b.x2} y1={bandY} y2={bandY} stroke="#16a34a"
                strokeWidth={4} strokeDasharray={b.dashed ? "6 4" : undefined} />
          {b.censored && <text x={b.x1} y={bandY + 4} fontSize={9} fill="#b45309">⟵</text>}
          {b.marker && (
            <text x={b.x2} y={bandY + 4} fontSize={10}
                  fill={b.marker === "x" ? "#dc2626" : "#6b7280"}>
              {b.marker === "x" ? "✕" : "○"}</text>)}
        </g>))}
      {out.dots.map((d, i) => (
        <circle key={`d${i}`} cx={d.x} cy={d.y} r={3} fill={d.color} />))}
    </svg>
  );
}
```

- [ ] **Step 3: StockStreakRow.tsx** — 컬럼(스펙 §5): 종목(클릭→`/chart/<symbol>`) | 최근 묶음 상태(진행중/닫힘·사유 pill + censored "관찰 시작=시스템 시작" 배지 + backfilled "백필" 배지) | 묶음 수 | 최근 pivot | 성과(stage 별: breakout→`T+5 x% · T+20 y%`, staging/watching→`최고 +z%`(corp_action_flag 시 "⚠ 기업행위"), base_forming→"베이스 형성 중") | `<StreakChart …/>`. 행 클릭 → 펼침: 묶음별 헤더(기간·closed_by·stage) + `<StockTimeline rows={streak.analyses} />` (#127 재사용 — analyses 가 TimelineRow 충족).

- [ ] **Step 4: stockTimeline 타입 완화** — `stockTimeline.ts` 에 `export interface TimelineRow { symbol: string; key_date: string; **classified_at: string;** source: string; classification: string; pattern: string | null; pivot_price: number | null; triggers: ReviewTrigger[]; }` 추가(⚠️ `classified_at` 필수 — 기존 `StockTimeline.tsx:123` 이 React key 로 사용, 빠지면 tsc 실패), `buildStockTimeline(rows: TimelineRow[])` 및 `StockTimeline` props 를 `TimelineRow[]` 로 변경(ReviewRow 는 구조적으로 충족 — 기존 호출부 무수정). 기존 stockTimeline.test.ts 그대로 통과해야 함.

- [ ] **Step 5: ReviewPage 통합** — `view = sp.get("view")`; `view === "analysis"` → 기존 분석 표(현행 코드 유지), 그 외(기본·구 timeline 값 포함) → 종목 행 뷰(`useQuery` → `/review/stocks`, 필터: 기간·유형·종목·상태). 토글 UI: "종목 행 보기 | 분석 단위 보기". 기존 타임라인 토글 체크박스 제거.

- [ ] **Step 6: 검증** — Run: `cd web && npm run build && npx vitest run` / Expected: tsc 0, vitest 전부 통과(기존 stockTimeline 10개 포함)
- [ ] **Step 7: 커밋**

```bash
git add web/src/components/StreakChart.tsx web/src/components/StockStreakRow.tsx web/src/lib/types.ts web/src/lib/stockTimeline.ts web/src/components/StockTimeline.tsx web/src/pages/ReviewPage.tsx
git commit -m "종목 행 뷰를 기본으로 전환한다 — 묶음 색띠·pivot 계단 차트·분석 표 토글"
```

---

### Task 7: 전체 검증·실데이터 확인

**Files:** 없음 (검증 전용 — 코드·커밋 생성 금지)

- [ ] **Step 1: full suite** — Run: `pgrep -f pytest || uv run pytest tests/ -q` / Expected: 실패 0(1 deselected·1 skipped 관례)
- [ ] **Step 2: production 읽기 전용 스모크** — worktree 에서:

```bash
uv run python -c "
import os, psycopg
from datetime import date
from dotenv import load_dotenv; load_dotenv()
from api.services.review_streaks import build_stock_rows
with psycopg.connect(os.environ['DATABASE_URL']) as conn:
    got = build_stock_rows(conn, date_from=date(2026,7,28), date_to=date(2026,8,25),
        source=None, ticker=None, status=None, limit=500, offset=0, today=date(2026,8,25))
    rows = got['rows']
    from collections import Counter
    print('행', len(rows), '| stage', Counter(r['latest']['stage'] for r in rows),
          '| status', Counter(r['latest']['status'] for r in rows),
          '| censored', sum(r['latest']['censored'] for r in rows),
          '| orphan', got['orphan_trigger_count'])
    conn.rollback()
"
```
Expected: 예외 없음, 행>0, stage 분포에 breakout·staging·watching·base_forming 이 상식적으로 분포(§0 실측과 정합 — 예: 4주 창 종목 수십~이백), DB 쓰기 없음(rollback).
- [ ] **Step 3: 실화면** — 임시 vite(별도 포트, VITE_API_TARGET=로컬 API)로 `/review` 열어 종목 행 그래프·펼침 타임라인·`view=analysis` 토글·구 `view=timeline` URL 무해 폴백을 확인 후 서버 정리.

---

## Self-Review 결과

1. **스펙 커버리지**: §1(하한·dedup·분할·절단·소급) → Task 1, §1 트리거·§2 stage/성과/corp → Task 2, §3 창·계단(닫힘 경계) → Task 3(데이터)·Task 5·6(렌더), §4 API/status 원본 기준/ge=0/limit 캡 → Task 3·4, §5 프론트/구 URL → Task 6, §6 엣지(같은 kd tie·닫는 행만·클램프) → Task 1·3 테스트, §7 테스트 12항목 → Task 1~6 테스트 + Task 7(무회귀·스모크). 갭 없음.
2. **플레이스홀더**: Task 6 Step 3·5 는 기존 파일 패턴 복제 지시 + 컬럼·동작 전량 명세(반복 JSX 위임 — Task 4 의 스키마 나열도 필드·타입 전량 명시). 그 외 TBD 없음.
3. **타입 일관성**: `build_stock_rows` 시그니처 Task 3 정의 = Task 4 소비 일치. `ChartIn/ChartOut` Task 5 정의 = Task 6 소비 일치. `TimelineRow` 완화는 기존 stockTimeline 테스트 무수정 통과를 요건으로 명시. streak dict 키(start/end/closed_by/censored/backfilled/has_gap/analyses/metrics/stage)가 Task 1→3→4 스키마와 1:1.
