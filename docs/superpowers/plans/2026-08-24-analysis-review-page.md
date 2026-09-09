> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# 분석 회고 페이지 (/review) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LLM 분석 1건 단위로 "분석 → 트리거 → 이후 가격 진행(pivot 대비 T+5/T+20)"을 보여주는 읽기 전용 회고 페이지를 만든다.

**Architecture:** 신규 서비스 모듈(`api/services/review_builder.py`)이 SQL로 회고 행·트리거 귀속·성과 구간을 조립하고 python으로 성과·스파크라인을 계산한다. 신규 라우터(`GET /api/review/analyses`) 1개가 이를 노출하고, React 페이지(`/review`)가 렌더한다. **스키마 변경 없음, DB 읽기 전용.**

**Tech Stack:** FastAPI + psycopg(raw SQL), pytest(kr_test 스키마, TestClient), React + TypeScript + vite, inline SVG(의존성 추가 금지).

**Spec:** `docs/superpowers/specs/2026-08-22-analysis-review-page-design.md` (v3+2회 검토 반영본). 이 계획의 모든 규칙 정의는 스펙이 원본이다 — 충돌 시 스펙 우선.

## Global Constraints

- 스키마 변경 금지, production 테이블 쓰기 금지 (읽기 전용 화면).
- 테스트: `uv run pytest tests/` 기대 = **실패 0, 1 deselected, 1 skipped** (kr_test 리셋 관례, 실행 전 `pgrep -f pytest`로 교차 세션 확인).
- 커밋: 한국어 제목(명령형), **Claude co-author 트레일러 금지**, `git add`는 명시 경로만(`-A` 금지).
- 프론트: 새 npm 의존성 추가 금지. 스파크라인은 inline SVG.
- 시간 규칙(스펙 §1): key_date = `COALESCE(analyzed_for_date, classified_at::date)`, 트리거 날짜 D = `COALESCE(t.analyzed_for_date, (t.evaluated_at AT TIME ZONE 'UTC')::date)`.
- thresholds.py 무접촉(임계 변경 아님 — 의존성 맵 체크리스트 비발동).

## File Structure

- Create `api/services/review_builder.py` — 회고 행 조립 + 성과 계산 (Task 1·2)
- Create `api/schemas/review.py` — 응답 pydantic 모델 (Task 3)
- Create `api/routers/review.py` — GET /api/review/analyses (Task 3)
- Modify `api/main.py` — 라우터 등록 1줄 (Task 3)
- Create `web/src/pages/ReviewPage.tsx` — 페이지 (Task 4)
- Create `web/src/components/Sparkline.tsx` — inline SVG 차트 (Task 4)
- Modify `web/src/lib/types.ts`, `web/src/App.tsx` — 타입·라우트·내비 (Task 4)
- Create `tests/test_api_review_builder.py`, `tests/test_api_review_router.py`

---

### Task 1: review_builder — 회고 행 조립 (귀속·구간·상태)

**Files:**
- Create: `api/services/review_builder.py`
- Test: `tests/test_api_review_builder.py`

**Interfaces:**
- Produces: `fetch_analysis_rows(conn, *, date_from: date, date_to: date, classification: str|None, source: str|None, pattern: str|None, ticker: str|None, include_pivot_null: bool, limit: int, offset: int) -> list[dict]` — dict 키: `symbol, name, market, source, classified_at(datetime), analyzed_for_date(date|None), key_date(date), next_key_date(date|None), classification, pattern, pivot_price(float|None), triggers(list[dict])`. triggers 원소: `{evaluated_at, trigger_type, decision, close, pivot_price, reasoning, d(date)}` (d = D 규칙).
- Produces: `count_orphan_triggers(conn, *, date_from: date, date_to: date) -> int`
- Produces: `derive_status(triggers: list[dict], t5_pct, t20_pct) -> str` — 반환: `"미발동"|"staging"|"돌파-진행중"|"돌파-완료"`
- Produces: `first_breakout(triggers) -> dict|None`, `first_promotion_d(triggers) -> date|None` — "최초" = D 기준 min, 동률이면 evaluated_at (스펙 §1)
- 상수: `BREAKOUT_TYPES = frozenset({"breakout", "breakout_from_watch"})`

- [ ] **Step 1: 실패하는 테스트 작성 — 귀속·구간·상태**

`tests/test_api_review_builder.py` 생성. 기존 `tests/test_api_triggers.py`의 fixture 패턴(프리픽스 네임스페이스 + 사전 DELETE)을 따른다. conftest의 `db` fixture(kr_test) 사용.

```python
from datetime import date, datetime, timezone, timedelta

import pytest

from api.services.review_builder import (
    fetch_analysis_rows, count_orphan_triggers, derive_status,
    first_breakout, first_promotion_d, BREAKOUT_TYPES,
)

KST = timezone(timedelta(hours=9))


@pytest.fixture
def seed(db):
    with db.cursor() as cur:
        cur.execute("DELETE FROM trigger_evaluation_log WHERE symbol LIKE 'RVTEST%'")
        cur.execute("DELETE FROM weekly_classification WHERE symbol LIKE 'RVTEST%'")
        cur.execute("DELETE FROM stocks WHERE ticker LIKE 'RVTEST%'")
        cur.execute(
            """INSERT INTO stocks (ticker, name, market, sector, listed_at)
               VALUES ('RVTEST01','회고1','KOSPI','반도체','2020-01-01'),
                      ('RVTEST02','회고2','KOSDAQ','제약','2020-01-01')"""
        )
        # RVTEST01 — 스펙 §1 backdate 시나리오 (000430 실사례 재현):
        #  화 19:41 delta watch(pivot 4520) → 화 21:01 promotion 트리거
        #  → 수 02:53 weekend ignore 가 key_date 를 화요일로 소급.
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES
                 ('RVTEST01','2026-06-02 19:41:48+09','KOSPI','watch','flat_base',
                  4520,'daily_delta','2026-06-02'),
                 ('RVTEST01','2026-06-03 02:53:06+09','KOSPI','ignore',NULL,
                  NULL,'weekend','2026-06-02'),
                 ('RVTEST02','2026-06-01 10:00:00+09','KOSDAQ','watch','cup_with_handle',
                  10000,'weekend','2026-05-30')"""
        )
        cur.execute(
            """INSERT INTO trigger_evaluation_log
                 (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                  decision, reasoning, prior_classification_at, analyzed_for_date)
               VALUES
                 ('RVTEST01','2026-06-02 21:01:40+09','promotion',4400,100000,4520,
                  'wait','접근','2026-06-02 19:41:48+09','2026-06-02'),
                 -- 고아: prior 가 어떤 분류 행과도 불일치
                 ('RVTEST02','2026-06-04 21:00:00+09','promotion',9800,100000,10000,
                  'wait','고아','2026-01-01 00:00:00+09','2026-06-04')"""
        )
    db.commit()
    yield


def test_backdated_weekend_does_not_steal_trigger(db, seed):
    rows = fetch_analysis_rows(
        db, date_from=date(2026, 5, 25), date_to=date(2026, 6, 30),
        classification=None, source=None, pattern=None, ticker="RVTEST01",
        include_pivot_null=True, limit=100, offset=0,
    )
    # 회고 행은 delta watch 1건뿐 (ignore 는 회고 행 아님)
    assert len(rows) == 1
    r = rows[0]
    assert r["source"] == "daily_delta"
    # 직접 조인: promotion 트리거가 delta watch 행에 귀속
    assert len(r["triggers"]) == 1
    assert r["triggers"][0]["trigger_type"] == "promotion"
    assert r["triggers"][0]["d"] == date(2026, 6, 2)


def test_next_key_date_uses_all_rows_including_ignore(db, seed):
    rows = fetch_analysis_rows(
        db, date_from=date(2026, 5, 25), date_to=date(2026, 6, 30),
        classification=None, source=None, pattern=None, ticker="RVTEST01",
        include_pivot_null=True, limit=100, offset=0,
    )
    # 다음 행이 ignore 여도 구간은 거기서 끝난다 (LEAD 는 필터 전 전체 행)
    assert rows[0]["next_key_date"] == date(2026, 6, 2)  # 소급된 ignore 의 key_date


def test_orphan_trigger_counted_not_dropped(db, seed):
    n = count_orphan_triggers(db, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
    assert n == 1  # RVTEST02 의 고아 1건
    rows = fetch_analysis_rows(
        db, date_from=date(2026, 5, 25), date_to=date(2026, 6, 30),
        classification=None, source=None, pattern=None, ticker="RVTEST02",
        include_pivot_null=True, limit=100, offset=0,
    )
    assert rows and rows[0]["triggers"] == []  # 고아는 행에 붙지 않음


def test_derive_status_table():
    promo = {"trigger_type": "promotion", "d": date(2026, 6, 2),
             "evaluated_at": datetime(2026, 6, 2, 21, 0, tzinfo=KST)}
    bfw = {"trigger_type": "breakout_from_watch", "d": date(2026, 6, 4),
           "evaluated_at": datetime(2026, 6, 4, 21, 0, tzinfo=KST)}
    inval = {"trigger_type": "invalidation", "d": date(2026, 6, 3),
             "evaluated_at": datetime(2026, 6, 3, 21, 0, tzinfo=KST)}
    assert derive_status([], None, None) == "미발동"
    assert derive_status([inval], None, None) == "미발동"        # invalidation-only
    assert derive_status([promo, inval], None, None) == "staging"  # 공존해도 staging
    assert derive_status([promo, bfw], 0.02, None) == "돌파-진행중"  # T+20 미도래
    assert derive_status([promo, bfw], 0.02, 0.11) == "돌파-완료"
    assert first_breakout([promo, bfw])["trigger_type"] == "breakout_from_watch"
    assert first_promotion_d([promo, bfw]) == date(2026, 6, 2)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_review_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: api.services.review_builder`

- [ ] **Step 3: 최소 구현**

`api/services/review_builder.py`:

```python
"""분석 회고(/review) 조립 — 스펙 docs/superpowers/specs/2026-08-22-….md 가 규칙 원본.

핵심 규칙 (스펙 §1):
- 회고 행 = weekly_classification 에서 source∈(weekend,daily_delta) AND
  classification∈(entry,watch).
- 트리거 귀속 = (symbol, prior_classification_at) 직접 조인. 시간창 추측 금지
  (backdate 로 최대 24/142 오귀속 실증).
- 구간 끝 next_key_date = LEAD(...) — 반드시 필터 **전** 전체 행에 적용
  (ignore·disqualify 가 구간을 끝낸다).
"""
from __future__ import annotations

from datetime import date

from psycopg import Connection
from psycopg.rows import dict_row

BREAKOUT_TYPES = frozenset({"breakout", "breakout_from_watch"})

_ROWS_SQL = """
WITH ordered AS (
    SELECT symbol, classified_at, market, source, classification, pattern,
           pivot_price, analyzed_for_date,
           COALESCE(analyzed_for_date, classified_at::date) AS key_date,
           LEAD(COALESCE(analyzed_for_date, classified_at::date)) OVER (
               PARTITION BY symbol
               ORDER BY COALESCE(analyzed_for_date, classified_at::date), classified_at
           ) AS next_key_date
      FROM weekly_classification
)
SELECT o.symbol, s.name, o.market, o.source, o.classified_at, o.analyzed_for_date,
       o.key_date, o.next_key_date, o.classification, o.pattern, o.pivot_price
  FROM ordered o
  LEFT JOIN stocks s ON s.ticker = o.symbol
 WHERE o.source IN ('weekend', 'daily_delta')
   AND o.classification IN ('entry', 'watch')
   AND o.key_date BETWEEN %(date_from)s AND %(date_to)s
   AND (%(classification)s::text IS NULL OR o.classification = %(classification)s)
   AND (%(source)s::text IS NULL OR o.source = %(source)s)
   AND (%(pattern)s::text IS NULL OR o.pattern = %(pattern)s)
   AND (%(ticker)s::text IS NULL OR o.symbol = %(ticker)s)
   AND (%(include_pivot_null)s OR o.pivot_price IS NOT NULL)
 ORDER BY o.key_date DESC, o.symbol
 LIMIT %(limit)s OFFSET %(offset)s
"""

_TRIGGERS_SQL = """
SELECT t.symbol, t.prior_classification_at, t.evaluated_at, t.trigger_type,
       t.decision, t.close, t.pivot_price, t.reasoning,
       COALESCE(t.analyzed_for_date,
                (t.evaluated_at AT TIME ZONE 'UTC')::date) AS d
  FROM trigger_evaluation_log t
 WHERE (t.symbol, t.prior_classification_at) = ANY(%(keys)s)
 ORDER BY d, t.evaluated_at
"""

_ORPHAN_SQL = """
SELECT COUNT(*)
  FROM trigger_evaluation_log t
 WHERE NOT EXISTS (SELECT 1 FROM weekly_classification wc
                    WHERE wc.symbol = t.symbol
                      AND wc.classified_at = t.prior_classification_at)
   AND COALESCE(t.analyzed_for_date, (t.evaluated_at AT TIME ZONE 'UTC')::date)
       BETWEEN %(date_from)s AND %(date_to)s
"""


def fetch_analysis_rows(conn: Connection, *, date_from: date, date_to: date,
                        classification: str | None, source: str | None,
                        pattern: str | None, ticker: str | None,
                        include_pivot_null: bool, limit: int, offset: int) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_ROWS_SQL, {
            "date_from": date_from, "date_to": date_to,
            "classification": classification, "source": source,
            "pattern": pattern, "ticker": ticker,
            "include_pivot_null": include_pivot_null,
            "limit": limit, "offset": offset,
        })
        rows = cur.fetchall()
        for r in rows:
            r["pivot_price"] = float(r["pivot_price"]) if r["pivot_price"] is not None else None
            r["triggers"] = []
        if rows:
            keys = [(r["symbol"], r["classified_at"]) for r in rows]
            by_key = {(r["symbol"], r["classified_at"]): r for r in rows}
            cur.execute(_TRIGGERS_SQL, {"keys": keys})
            for t in cur.fetchall():
                t["close"] = float(t["close"]) if t["close"] is not None else None
                t["pivot_price"] = float(t["pivot_price"]) if t["pivot_price"] is not None else None
                by_key[(t["symbol"], t["prior_classification_at"])]["triggers"].append(t)
    return rows


def count_orphan_triggers(conn: Connection, *, date_from: date, date_to: date) -> int:
    with conn.cursor() as cur:
        cur.execute(_ORPHAN_SQL, {"date_from": date_from, "date_to": date_to})
        return cur.fetchone()[0]


def _sorted_by_d(triggers: list[dict]) -> list[dict]:
    # "최초" 순서 기준 = D, 동률이면 evaluated_at (스펙 §1 — catch-up 어긋남 대비)
    return sorted(triggers, key=lambda t: (t["d"], t["evaluated_at"]))


def first_breakout(triggers: list[dict]) -> dict | None:
    for t in _sorted_by_d(triggers):
        if t["trigger_type"] in BREAKOUT_TYPES:
            return t
    return None


def first_promotion_d(triggers: list[dict]) -> date | None:
    for t in _sorted_by_d(triggers):
        if t["trigger_type"] == "promotion":
            return t["d"]
    return None


def derive_status(triggers: list[dict], t5_pct, t20_pct) -> str:
    """스펙 §1 상태 판정 표. 돌파≥1 → 진행중/완료(T+20 도래), promotion≥1 → staging,
    나머지(invalidation-only 포함) → 미발동."""
    if first_breakout(triggers) is not None:
        return "돌파-완료" if t20_pct is not None else "돌파-진행중"
    if any(t["trigger_type"] == "promotion" for t in triggers):
        return "staging"
    return "미발동"
```

참고: `(symbol, prior_classification_at) = ANY(%(keys)s)` 는 psycopg3 가 tuple 리스트를
row 값 배열로 어댑트하지 못하면 `WHERE (t.symbol, t.prior_classification_at) IN
(SELECT unnest(%(syms)s::text[]), unnest(%(ats)s::timestamptz[]))` 패턴(배열 2개 zip)으로
대체한다 — 테스트가 판정한다.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_api_review_builder.py -v`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add api/services/review_builder.py tests/test_api_review_builder.py
git commit -m "회고 행 조립을 추가한다 — prior_classification_at 직접 귀속·전체행 LEAD 구간"
```

---

### Task 2: review_builder — 성과·스파크라인 계산

**Files:**
- Modify: `api/services/review_builder.py` (함수 추가)
- Test: `tests/test_api_review_builder.py` (테스트 추가)

**Interfaces:**
- Consumes: Task 1 의 행 dict(`key_date, next_key_date, pivot_price, triggers`)와 `first_breakout`.
- Produces: `fetch_price_series(conn, symbol: str, start: date, end: date) -> list[tuple[date, float]]` — daily_prices 의 (date, adj_close), date 오름차순. **행이 있는 날 = 거래일**(거래정지 포함 — adj_close 는 carry 값, 스펙 §0-6).
- Produces: `chain_tn(series, d: date, pivot_delta: float, n: int) -> float | None` — 체인식 `(1+pivot_delta) × adj(D+n거래일)/adj(D) − 1`. D 또는 D+n 시점 데이터 없으면 None.
- Produces: `max_reach(series, key_date: date, next_key_date: date|None, pivot: float, today: date) -> float | None` — 창 `(key_date, t')` (key_date 당일 제외, 스펙 §1). 창이 비면 None.
- Produces: `build_spark(series, anchor: date, end: date, cap: int = 60) -> list[float]` — anchor~end 의 adj_close. cap 초과 시 균등 다운샘플하되 **최고·최저점 인덱스는 보존**.
- Produces: `corp_action_flags(conn, pairs: list[tuple[str, date]], today: date) -> set[tuple[str, date]]` — `(symbol, key_date)` 중 `corporate_actions.event_date ∈ [key_date, today]` 인 것.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_api_review_builder.py` 에 추가:

```python
from api.services.review_builder import (
    fetch_price_series, chain_tn, max_reach, build_spark, corp_action_flags,
)

# 시리즈는 (date, adj_close) 튜플 리스트 — DB 불필요한 순수 계산 테스트
def _series(*pairs):
    return [(date.fromisoformat(d), float(v)) for d, v in pairs]


def test_chain_tn_renormalization_invariant():
    # 돌파일 D=6/4, pivot_delta=+2% (스냅샷). T+2 종가가 D 대비 +10% 라면
    # T+2 = 1.02 × 1.10 − 1 = +12.2%
    s = _series(("2026-06-04", 100), ("2026-06-05", 104), ("2026-06-08", 110))
    t2 = chain_tn(s, date(2026, 6, 4), 0.02, 2)
    assert abs(t2 - 0.122) < 1e-9
    # 기업행위 재정규화: 전체 시리즈가 1/5 로 rescale 돼도 값 불변 (스펙 §1 체인식)
    s5 = [(d, v / 5) for d, v in s]
    assert abs(chain_tn(s5, date(2026, 6, 4), 0.02, 2) - t2) < 1e-9


def test_chain_tn_none_when_not_arrived():
    s = _series(("2026-06-04", 100), ("2026-06-05", 104))
    assert chain_tn(s, date(2026, 6, 4), 0.02, 5) is None


def test_trading_day_counting_skips_calendar_holidays():
    # 6/5(금) 다음 거래일 행이 6/9(화)라면 — 6/8(월, 대체공휴일 가정)은 행이 없어
    # 자동 배제되고, 6/9 가 D+2 거래일이다.
    s = _series(("2026-06-04", 100), ("2026-06-05", 102), ("2026-06-09", 108))
    assert abs(chain_tn(s, date(2026, 6, 4), 0.0, 2) - 0.08) < 1e-9


def test_max_reach_excludes_day_zero():
    # key_date 당일(6/2, 120 — 분석의 입력)은 제외. 창 내 최고 110 → +10%
    s = _series(("2026-06-02", 120), ("2026-06-03", 105), ("2026-06-04", 110))
    r = max_reach(s, date(2026, 6, 2), None, 100.0, today=date(2026, 6, 30))
    assert abs(r - 0.10) < 1e-9


def test_max_reach_window_ends_at_next_key_date():
    # t'=6/4 → 6/4 이후(포함) 가격 130 은 계상 금지 (연장 없음)
    s = _series(("2026-06-02", 100), ("2026-06-03", 105), ("2026-06-04", 130))
    r = max_reach(s, date(2026, 6, 2), date(2026, 6, 4), 100.0, today=date(2026, 6, 30))
    assert abs(r - 0.05) < 1e-9


def test_max_reach_zero_length_window_is_none():
    s = _series(("2026-06-02", 100))
    assert max_reach(s, date(2026, 6, 2), date(2026, 6, 2), 100.0,
                     today=date(2026, 6, 30)) is None


def test_build_spark_downsample_preserves_extremes():
    vals = list(range(100))          # 0..99 오름차순
    vals[37] = 500                   # 최고점
    vals[71] = -500                  # 최저점
    s = [(date(2026, 1, 1), 0.0)] * 0
    s = [(date.fromordinal(738000 + i), float(v)) for i, v in enumerate(vals)]
    spark = build_spark(s, s[0][0], s[-1][0], cap=60)
    assert len(spark) <= 60
    assert 500.0 in spark and -500.0 in spark
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_review_builder.py -v -k "chain or reach or spark or trading"`
Expected: FAIL — `ImportError: cannot import name 'chain_tn'`

- [ ] **Step 3: 구현**

`api/services/review_builder.py` 에 추가:

```python
_PRICES_SQL = """
SELECT date, adj_close FROM daily_prices
 WHERE ticker = %(symbol)s AND date >= %(start)s AND date <= %(end)s
 ORDER BY date
"""


def fetch_price_series(conn: Connection, symbol: str, start: date, end: date
                       ) -> list[tuple[date, float]]:
    with conn.cursor() as cur:
        cur.execute(_PRICES_SQL, {"symbol": symbol, "start": start, "end": end})
        return [(r[0], float(r[1])) for r in cur.fetchall()]


def chain_tn(series: list[tuple[date, float]], d: date, pivot_delta: float,
             n: int) -> float | None:
    """(1+pivot_delta) × adj(D+n거래일)/adj(D) − 1. 거래일 = 시리즈의 행."""
    idx = {dt: i for i, (dt, _) in enumerate(series)}
    if d not in idx or idx[d] + n >= len(series):
        return None
    base = series[idx[d]][1]
    later = series[idx[d] + n][1]
    if base <= 0:
        return None
    return (1.0 + pivot_delta) * (later / base) - 1.0


def max_reach(series: list[tuple[date, float]], key_date: date,
              next_key_date: date | None, pivot: float, *, today: date
              ) -> float | None:
    """창 = (key_date, t') — key_date 당일 제외(분석 입력), 연장 없음 (스펙 §1)."""
    end = next_key_date if next_key_date is not None else today
    window = [v for dt, v in series if key_date < dt < end] if next_key_date \
        else [v for dt, v in series if key_date < dt <= end]
    if not window or pivot <= 0:
        return None
    return max(window) / pivot - 1.0


def build_spark(series: list[tuple[date, float]], anchor: date, end: date,
                cap: int = 60) -> list[float]:
    vals = [v for dt, v in series if anchor <= dt <= end]
    if len(vals) <= cap:
        return vals
    hi, lo = vals.index(max(vals)), vals.index(min(vals))
    step = len(vals) / cap
    picked = sorted({int(i * step) for i in range(cap)} | {hi, lo, len(vals) - 1})
    return [vals[i] for i in picked]


_CORP_SQL = """
SELECT DISTINCT ticker FROM corporate_actions
 WHERE ticker = ANY(%(symbols)s) AND event_date BETWEEN %(min_kd)s AND %(today)s
"""


def corp_action_flags(conn: Connection, pairs: list[tuple[str, date]], *,
                      today: date) -> set[tuple[str, date]]:
    """(symbol, key_date) 별 event_date ∈ [key_date, today] 존재 여부.
    상한이 '오늘'인 이유: 기업행위는 이전 전체 adj 이력을 rescale (스펙 §1)."""
    if not pairs:
        return set()
    symbols = sorted({s for s, _ in pairs})
    min_kd = min(kd for _, kd in pairs)
    with conn.cursor() as cur:
        cur.execute(_CORP_SQL, {"symbols": symbols, "min_kd": min_kd, "today": today})
        hit_symbols = {r[0] for r in cur.fetchall()}
    out: set[tuple[str, date]] = set()
    for sym, kd in pairs:
        if sym not in hit_symbols:
            continue
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM corporate_actions WHERE ticker=%s "
                "AND event_date BETWEEN %s AND %s LIMIT 1", (sym, kd, today))
            if cur.fetchone():
                out.add((sym, kd))
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_api_review_builder.py -v`
Expected: 전부 passed (Task 1 의 4개 포함 11개)

- [ ] **Step 5: 커밋**

```bash
git add api/services/review_builder.py tests/test_api_review_builder.py
git commit -m "성과 계산을 추가한다 — 체인식 T+N·구간 한정 최고 도달률·극점 보존 스파크"
```

---

### Task 3: 라우터 GET /api/review/analyses

**Files:**
- Create: `api/schemas/review.py`
- Create: `api/routers/review.py`
- Modify: `api/main.py` (import + `app.include_router(review.router)` — 기존 `:31-40` 블록에 1줄)
- Test: `tests/test_api_review_router.py`

**Interfaces:**
- Consumes: Task 1·2 의 모든 함수 (시그니처 그대로).
- Produces: `GET /api/review/analyses` — 응답 `{"rows": [ReviewRowOut...], "orphan_trigger_count": int}`. 쿼리: `from`(alias, 기본 오늘−28일)·`to`(기본 오늘)·`classification`·`source`·`triggered`(bool|None)·`pattern`·`ticker`·`include_pivot_null`(기본 false)·`limit`(기본 200, ≤500)·`offset`.
- `ReviewRowOut` 필드: `symbol, name, market, source, classified_at, analyzed_for_date, key_date, classification, pattern, pivot_price, status, first_breakout_at(date|None), first_breakout_type, first_breakout_decision, promotion_at(date|None), trigger_count(int), t5_pct, t20_pct, max_reach_pct, corp_action_flag(bool), spark(list[float]), pivot_baseline(float|None), triggers(list[ReviewTriggerOut])`. `ReviewTriggerOut`: `evaluated_at, d, trigger_type, decision, close, pivot_price, reasoning`.
- `pivot_baseline` = 스파크라인 기준선: 돌파 행은 체인 기저 `adj_close(D)/(1+pivot_delta(D))`, 그 외 저장된 pivot (스펙 §1 스파크라인).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_api_review_router.py` — `tests/test_api_triggers.py` 의 client/override 패턴 복제. seed 는 Task 1 fixture 에 daily_prices 를 추가한 변형:

```python
from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.deps import get_conn


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed(db):
    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    with db.cursor() as cur:
        for tbl, col in [("trigger_evaluation_log", "symbol"),
                         ("weekly_classification", "symbol"),
                         ("daily_prices", "ticker"), ("stocks", "ticker")]:
            cur.execute(f"DELETE FROM {tbl} WHERE {col} LIKE 'RVAPI%'")
        cur.execute("""INSERT INTO stocks (ticker, name, market, sector, listed_at)
                       VALUES ('RVAPI01','에이','KOSPI','반도체','2020-01-01')""")
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES ('RVAPI01','2026-06-01 10:00:00+09','KOSPI','watch',
                       'cup_with_handle', 10000, 'weekend', '2026-05-30')""")
        cur.execute(
            """INSERT INTO trigger_evaluation_log
                 (symbol, evaluated_at, trigger_type, close, volume, pivot_price,
                  decision, reasoning, prior_classification_at, analyzed_for_date)
               VALUES ('RVAPI01','2026-06-04 21:00:00+09','breakout_from_watch',
                       10200, 500000, 10000, 'wait', '돌파',
                       '2026-06-01 10:00:00+09', '2026-06-04')""")
        # 거래일 8개: D=6/4, T+5 = 6/12 종가 11000
        cur.execute(
            """INSERT INTO daily_prices (ticker, date, open, high, low, close,
                                         adj_close, volume, value)
               SELECT 'RVAPI01', d::date, 1,1,1,1, v, 1000, 1000
                 FROM (VALUES ('2026-06-02',9500.0),('2026-06-03',9800.0),
                              ('2026-06-04',10200.0),('2026-06-05',10400.0),
                              ('2026-06-08',10500.0),('2026-06-09',10600.0),
                              ('2026-06-10',10800.0),('2026-06-11',10900.0),
                              ('2026-06-12',11000.0)) AS t(d, v)""")
    db.commit()
    yield
    app.dependency_overrides.pop(get_conn, None)


def test_breakout_row_chain_t5(client, seed):
    r = client.get("/api/review/analyses?from=2026-05-25&to=2026-06-30&ticker=RVAPI01")
    assert r.status_code == 200
    body = r.json()
    assert body["orphan_trigger_count"] == 0
    row = body["rows"][0]
    assert row["status"].startswith("돌파")
    assert row["first_breakout_at"] == "2026-06-04"
    assert row["first_breakout_type"] == "breakout_from_watch"
    # pivot_delta(D) = (10200−10000)/10000 = +2%; adj(D)=10200, T+5=adj(6/12)=11000
    # T+5 = 1.02 × 11000/10200 − 1 = 0.1  (부동소수 오차 허용)
    assert abs(row["t5_pct"] - 0.10) < 1e-6
    assert row["t20_pct"] is None            # 미도래
    assert row["trigger_count"] == 1
    # 체인 기저 기준선 = 10200 / 1.02 = 10000
    assert abs(row["pivot_baseline"] - 10000.0) < 1e-6


def test_triggered_filter_and_limit_cap(client, seed):
    r = client.get("/api/review/analyses?from=2026-05-25&to=2026-06-30&triggered=false")
    assert all(row["first_breakout_at"] is None for row in r.json()["rows"])
    r2 = client.get("/api/review/analyses?limit=9999")
    assert r2.status_code == 200   # limit 은 500 으로 캡 (에러 아님)


def test_pivot_null_hidden_by_default(client, seed, db):
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO weekly_classification
                 (symbol, classified_at, market, classification, pattern,
                  pivot_price, source, analyzed_for_date)
               VALUES ('RVAPI01','2026-06-15 10:00:00+09','KOSPI','watch',
                       NULL, NULL, 'weekend', '2026-06-13')""")
    db.commit()
    r = client.get("/api/review/analyses?from=2026-05-25&to=2026-06-30&ticker=RVAPI01")
    assert len(r.json()["rows"]) == 1        # pivot null 행 숨김
    r2 = client.get("/api/review/analyses?from=2026-05-25&to=2026-06-30"
                    "&ticker=RVAPI01&include_pivot_null=true")
    assert len(r2.json()["rows"]) == 2
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_api_review_router.py -v`
Expected: FAIL — 404 (라우터 미등록)

- [ ] **Step 3: 구현**

`api/schemas/review.py`:

```python
from datetime import date, datetime

from pydantic import BaseModel


class ReviewTriggerOut(BaseModel):
    evaluated_at: datetime
    d: date
    trigger_type: str
    decision: str
    close: float | None = None
    pivot_price: float | None = None
    reasoning: str | None = None


class ReviewRowOut(BaseModel):
    symbol: str
    name: str | None = None
    market: str | None = None
    source: str
    classified_at: datetime
    analyzed_for_date: date | None = None
    key_date: date
    classification: str
    pattern: str | None = None
    pivot_price: float | None = None
    status: str
    first_breakout_at: date | None = None
    first_breakout_type: str | None = None
    first_breakout_decision: str | None = None
    promotion_at: date | None = None
    trigger_count: int
    t5_pct: float | None = None
    t20_pct: float | None = None
    max_reach_pct: float | None = None
    corp_action_flag: bool = False
    spark: list[float] = []
    pivot_baseline: float | None = None
    triggers: list[ReviewTriggerOut] = []


class ReviewResponse(BaseModel):
    rows: list[ReviewRowOut]
    orphan_trigger_count: int
```

`api/routers/review.py`:

```python
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from psycopg import Connection

from api.deps import get_conn
from api.schemas.review import ReviewResponse, ReviewRowOut, ReviewTriggerOut
from api.services.review_builder import (
    BREAKOUT_TYPES, build_spark, chain_tn, corp_action_flags,
    count_orphan_triggers, derive_status, fetch_analysis_rows,
    fetch_price_series, first_breakout, first_promotion_d, max_reach,
)

router = APIRouter(prefix="/api/review", tags=["review"])

SPARK_TRADING_DAYS = 20


@router.get("/analyses", response_model=ReviewResponse)
def list_analyses(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    classification: str | None = None,
    source: str | None = None,
    triggered: bool | None = None,
    pattern: str | None = None,
    ticker: str | None = None,
    include_pivot_null: bool = False,
    limit: int = 200,
    offset: int = 0,
    conn: Connection = Depends(get_conn),
):
    today = date.today()
    date_to = to or today
    date_from = from_ or (date_to - timedelta(days=28))
    limit = min(limit, 500)

    rows = fetch_analysis_rows(
        conn, date_from=date_from, date_to=date_to, classification=classification,
        source=source, pattern=pattern, ticker=ticker,
        include_pivot_null=include_pivot_null, limit=limit, offset=offset,
    )
    flags = corp_action_flags(
        conn, [(r["symbol"], r["key_date"]) for r in rows], today=today)

    out: list[ReviewRowOut] = []
    for r in rows:
        fb = first_breakout(r["triggers"])
        series = fetch_price_series(conn, r["symbol"], r["key_date"], today)
        t5 = t20 = reach = baseline = None
        spark: list[float] = []
        if fb is not None and fb["close"] and fb["pivot_price"]:
            pivot_delta = (fb["close"] - fb["pivot_price"]) / fb["pivot_price"]
            t5 = chain_tn(series, fb["d"], pivot_delta, 5)
            t20 = chain_tn(series, fb["d"], pivot_delta, 20)
            idx = {dt: i for i, (dt, _) in enumerate(series)}
            if fb["d"] in idx:
                d_i = idx[fb["d"]]
                baseline = series[d_i][1] / (1.0 + pivot_delta)
                end_i = min(d_i + SPARK_TRADING_DAYS, len(series) - 1)
                spark = build_spark(series, fb["d"], series[end_i][0])
        elif r["pivot_price"]:
            reach = max_reach(series, r["key_date"], r["next_key_date"],
                              r["pivot_price"], today=today)
            baseline = r["pivot_price"]
            end = r["next_key_date"] or today
            window = [(dt, v) for dt, v in series if r["key_date"] < dt
                      and (dt < end if r["next_key_date"] else dt <= end)]
            if window:
                spark = build_spark(window, window[0][0], window[-1][0])

        status = derive_status(r["triggers"], t5, t20)
        out.append(ReviewRowOut(
            symbol=r["symbol"], name=r["name"], market=r["market"],
            source=r["source"], classified_at=r["classified_at"],
            analyzed_for_date=r["analyzed_for_date"], key_date=r["key_date"],
            classification=r["classification"], pattern=r["pattern"],
            pivot_price=r["pivot_price"], status=status,
            first_breakout_at=fb["d"] if fb else None,
            first_breakout_type=fb["trigger_type"] if fb else None,
            first_breakout_decision=fb["decision"] if fb else None,
            promotion_at=first_promotion_d(r["triggers"]),
            trigger_count=len(r["triggers"]),
            t5_pct=t5, t20_pct=t20, max_reach_pct=reach,
            corp_action_flag=(r["symbol"], r["key_date"]) in flags,
            spark=spark, pivot_baseline=baseline,
            triggers=[ReviewTriggerOut(
                evaluated_at=t["evaluated_at"], d=t["d"],
                trigger_type=t["trigger_type"], decision=t["decision"],
                close=t["close"], pivot_price=t["pivot_price"],
                reasoning=t["reasoning"]) for t in r["triggers"]],
        ))
    if triggered is True:
        out = [r for r in out if r.first_breakout_at is not None]
    elif triggered is False:
        out = [r for r in out if r.first_breakout_at is None]
    orphans = count_orphan_triggers(conn, date_from=date_from, date_to=date_to)
    return ReviewResponse(rows=out, orphan_trigger_count=orphans)
```

`api/main.py` — 기존 라우터 import 줄에 `review` 추가 후 `:40` 근처에:

```python
app.include_router(review.router)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_api_review_router.py tests/test_api_review_builder.py -v`
Expected: 전부 passed

- [ ] **Step 5: 커밋**

```bash
git add api/schemas/review.py api/routers/review.py api/main.py tests/test_api_review_router.py
git commit -m "분석 회고 API 를 추가한다 — GET /api/review/analyses"
```

---

### Task 4: 프론트 — /review 페이지

**Files:**
- Create: `web/src/pages/ReviewPage.tsx`
- Create: `web/src/components/Sparkline.tsx`
- Modify: `web/src/lib/types.ts` (타입 추가), `web/src/App.tsx` (내비 항목 + Route)

**Interfaces:**
- Consumes: Task 3 응답 형태 그대로 (`ReviewResponse`).
- Produces: 라우트 `/review`. 내비 라벨 `{ to: "/review", label: "Review", kr: "분석 회고" }` (App.tsx:57 근처의 기존 배열 패턴).

- [ ] **Step 1: 타입 추가**

`web/src/lib/types.ts` 에:

```typescript
export interface ReviewTrigger {
  evaluated_at: string;
  d: string;
  trigger_type: string;
  decision: TriggerDecision;
  close: number | null;
  pivot_price: number | null;
  reasoning: string | null;
}

export interface ReviewRow {
  symbol: string;
  name: string | null;
  market: string | null;
  source: "weekend" | "daily_delta";
  classified_at: string;
  analyzed_for_date: string | null;
  key_date: string;
  classification: "entry" | "watch";
  pattern: string | null;
  pivot_price: number | null;
  status: string;
  first_breakout_at: string | null;
  first_breakout_type: string | null;
  first_breakout_decision: TriggerDecision | null;
  promotion_at: string | null;
  trigger_count: number;
  t5_pct: number | null;
  t20_pct: number | null;
  max_reach_pct: number | null;
  corp_action_flag: boolean;
  spark: number[];
  pivot_baseline: number | null;
  triggers: ReviewTrigger[];
}

export interface ReviewResponse {
  rows: ReviewRow[];
  orphan_trigger_count: number;
}
```

- [ ] **Step 2: Sparkline 컴포넌트**

`web/src/components/Sparkline.tsx`:

```tsx
export default function Sparkline({ values, baseline, width = 120, height = 28 }: {
  values: number[];
  baseline: number | null;
  width?: number;
  height?: number;
}) {
  if (values.length < 2) return <span className="text-faint">—</span>;
  const all = baseline != null ? [...values, baseline] : values;
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const x = (i: number) => (i / (values.length - 1)) * width;
  const y = (v: number) => height - ((v - min) / span) * height;
  const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} className="inline-block align-middle">
      {baseline != null && (
        <line x1={0} x2={width} y1={y(baseline)} y2={y(baseline)}
              stroke="#9ca3af" strokeDasharray="3 2" strokeWidth={1} />
      )}
      <polyline points={points} fill="none" stroke="#2563eb" strokeWidth={1.5} />
    </svg>
  );
}
```

- [ ] **Step 3: ReviewPage**

`web/src/pages/ReviewPage.tsx` — `TriggersPage.tsx` 의 구조(useSearchParams 필터·useQuery·행 확장·DecisionPill)를 그대로 따른다. 핵심 골격:

```tsx
import { useMemo, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api } from "../lib/api";
import { nDaysAgoKstISO, todayKstISO } from "../lib/dates";
import type { ReviewResponse, ReviewRow } from "../lib/types";
import Sparkline from "../components/Sparkline";

const pct = (v: number | null) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;

export default function ReviewPage() {
  const [sp, setSp] = useSearchParams();
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const from = sp.get("from") ?? nDaysAgoKstISO(28);
  const to = sp.get("to") ?? todayKstISO();
  const triggered = sp.get("triggered") ?? "";
  const source = sp.get("source") ?? "";
  const includePivotNull = sp.get("include_pivot_null") === "true";

  const q = useQuery<ReviewResponse>({
    queryKey: ["review", { from, to, triggered, source, includePivotNull }],
    queryFn: () => {
      const p = new URLSearchParams({ from, to, limit: "500" });
      if (triggered) p.set("triggered", triggered);
      if (source) p.set("source", source);
      if (includePivotNull) p.set("include_pivot_null", "true");
      return api<ReviewResponse>(`/review/analyses?${p.toString()}`);
    },
  });
  // 필터 바(from/to/source/triggered/pivot-null 토글) — TriggersPage 의
  // updateParam 패턴 복제. 테이블 컬럼 (스펙 §3):
  // 종목 | 분석일+유형배지 | 분류·패턴 | pivot | 상태(+첫 돌파일·decision)
  // | T+5 | T+20(미발동은 최고 도달률 + 기업행위 ⚠ 배지) | 스파크라인
  // 행 클릭 → expanded 토글 → triggers 타임라인 (날짜 d·type·decision·
  // 당시 close/pivot·reasoning 접기). 종목명 클릭 → navigate(`/chart/${symbol}`).
  // 하단: q.data.orphan_trigger_count > 0 이면
  // "귀속 불가 트리거 N건 (재분석으로 대체된 기록)" 안내.
  // …(TriggersPage 스타일 그대로 — 전체 JSX 는 구현 시 TriggersPage 를 열어 복제)
}
```

주의: 상태별 표기 —
- `status === "staging"` 이고 `max_reach_pct != null && max_reach_pct >= 0` 이면 상태 셀에 `staging (pivot 상회)` 로 구분 표기 (스펙 §1·§3).
- `corp_action_flag` 이고 미발동·staging 행이면 성과 셀에 `⚠ 기업행위` 배지.

`web/src/App.tsx`: 내비 배열(`:57` 근처)에 `{ to: "/review", label: "Review", kr: "분석 회고", Icon: History }` (lucide-react 의 `History` — 이미 의존성에 있는 아이콘 팩), Route 블록(`:262` 근처)에 `<Route path="/review" element={<ReviewPage />} />` + import.

- [ ] **Step 4: 빌드·기존 프론트 테스트 확인**

Run: `cd web && npm run build && npx vitest run`
Expected: 빌드 성공(tsc 에러 0), 기존 vitest 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add web/src/pages/ReviewPage.tsx web/src/components/Sparkline.tsx web/src/lib/types.ts web/src/App.tsx
git commit -m "분석 회고 페이지를 추가한다 — /review 라우트·스파크라인·트리거 타임라인"
```

---

### Task 5: 전체 검증·실데이터 확인

**Files:** 없음 (검증만)

- [ ] **Step 1: 전체 suite**

Run: `pgrep -f pytest || uv run pytest tests/ -q`
Expected: **실패 0, 1 deselected, 1 skipped** (baseline +신규 테스트만큼 증가)

- [ ] **Step 2: production 읽기 전용 스모크**

메인 repo(dev 서버가 아니라 로컬 파이썬)에서:

```bash
uv run python -c "
import os, psycopg
from datetime import date
from dotenv import load_dotenv; load_dotenv()
from api.services.review_builder import fetch_analysis_rows, count_orphan_triggers
with psycopg.connect(os.environ['DATABASE_URL']) as conn:
    rows = fetch_analysis_rows(conn, date_from=date(2026,5,1), date_to=date(2026,8,24),
        classification=None, source=None, pattern=None, ticker=None,
        include_pivot_null=False, limit=500, offset=0)
    n_trig = sum(len(r['triggers']) for r in rows)
    print(f'행 {len(rows)}, 귀속 트리거 {n_trig}, 고아 {count_orphan_triggers(conn, date_from=date(2026,5,1), date_to=date(2026,8,24))}')
    conn.rollback()
"
```

Expected: 행 수 > 0, 고아 = 1 (033200 — 스펙 §1 실측), 예외 없음. **트리거 pivot 스냅샷 대조**(스펙 §5-2): 귀속된 트리거의 `pivot_price` 와 행의 `pivot_price` 가 다른 케이스 수를 출력해 0 인지 확인.

- [ ] **Step 3: 최종 커밋 확인**

`git log --oneline` 으로 Task 1~4 커밋 4개 + `.loop/`·빌드 산출물 미포함(`git show --stat`) 확인.

---

## Self-Review 결과 (계획 작성 후 점검)

1. **스펙 커버리지**: §1 귀속(직접 조인·고아)→Task 1, §1 성과(체인·max_reach·day0 제외·창 한정)→Task 2, §1 스파크(앵커·극점 보존·체인 기저선)→Task 2·3, §2 API(필터·메타·limit 캡)→Task 3, §3 프론트(컬럼·확장·배지·orphan 안내)→Task 4, §5 테스트 12건→Task 1·2·3 테스트 + Task 5 (§5-2 스냅샷 대조는 Task 5 Step 2, §5-9 무회귀는 Task 5 Step 1). 갭 없음.
2. **플레이스홀더**: Task 4 Step 3 의 JSX 골격은 "TriggersPage 를 열어 복제"로 위임 — 반복 렌더 코드라 의도적 위임이며 컬럼·동작 명세는 주석에 전부 명시함. 그 외 TBD 없음.
3. **타입 일관성**: `chain_tn`/`max_reach`/`build_spark` 시그니처가 Task 2 정의와 Task 3 사용처 일치. `ReviewRowOut` 필드 = types.ts `ReviewRow` 필드 1:1. `first_breakout` 반환 dict 의 키(`d, trigger_type, decision, close, pivot_price`)는 Task 1 트리거 dict 정의와 일치.
