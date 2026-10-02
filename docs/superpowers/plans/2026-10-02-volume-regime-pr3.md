# volume_regime PR-3 — 창 유도 표지(Q-5c 2) Implementation Plan

> ⚠️ **실행 완료·리뷰 3회 반영(10-02, PR #222)** — Task 본문의 세부(주봉 창 50, decline T-D flag, `weekly_range_flag(symbol=)`, Positions COALESCE, '이관 SQL 변경 0', '2축 표 트리거 아님')는 **아래 '리뷰 반영' 절이 대체**한다. 미체크 Step 을 그대로 재실행하지 말 것.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 판정 행 `volume_regime_flag` 를 "as_of ≥ 경계 → mixed"(PR-2 임시 규칙)에서 "그 판정의 거래량 창이 경계에 걸칠 때만 mixed"(창 유도)로 바꾸고, 보유 평가 flag 를 Positions 카드에 노출한다.

**Architecture:** 봉 regime 은 날짜의 함수(`regime_for_date`/`regime_for_week`)이므로 창 상태는 **창 안 봉들의 날짜**만으로 유도한다 — 저장 컬럼을 로더에 끌고 다니지 않는다(#220 2차 리뷰의 load 유도 전례). 소비처 4곳(분류·백필·트리거·진입)은 writer 가 `conn·symbol·as_of` 를 이미 가지므로 writer 안에서 창 봉 날짜를 1쿼리로 읽어 유도(spec §5 "추가 SQL 0 목표"는 프레임이 writer 까지 오지 않아 불가 — 판정당 1쿼리·LIMIT 50 로 대체, 근거 기재). 보유 평가는 `anchor_week~as_of` 주봉 날짜로 유도. 유도 함수는 순수(`regime_window_state`), DB 헬퍼는 `common/regime_windows.py` 한 파일.

**Tech Stack:** Python 3 (psycopg, pandas 없음), FastAPI, React/TS. 테스트 pytest(kr_test db 픽스처)·vitest·tsc.

**Spec:** `docs/superpowers/specs/2026-09-30-volume-regime-design.md` §3 D3·D4·D7·D9, §5, §7 PR-3.

## Global Constraints

- 판정 규칙·숫자 변경 0(spec §1). flag 는 표시 전용 — 발화·게이트 불변(D7).
- 창 길이 = 소비처 상수 그대로: 일간 50봉(`daily_indicators.volume_ratio_50d`), 주간 50주(C3), T2/T-D = 앵커 주~평가 주(spec §5).
- flag 값: `'mixed'` 또는 NULL 만(D4). clean/new 는 저장하지 않는다.
- 기존 PR-2 행: 판정 시점의 flag 는 사실 기록이나, PR-2 창(09-28~10-02)에 찍힌 'mixed' 중 창 유도로는 NULL 인 유형(decline 행·앵커 없는/경계 후 앵커 climax·경계 후 상장)은 이관 SQL 이 되돌린다(리뷰 반영 — 초안의 '되돌림 불요·이관 SQL 변경 0' 은 철회).
- 운영 규칙(CLAUDE.md): 브랜치 `issue207-volume-regime-pr3`(worktree vr-pr3), `git add` 명시 경로, suite 판정 전 `pgrep -f pytest`, KRX 접촉 0, Co-Authored-By 트레일러 금지(사용자 CLAUDE.md).
- 산술 변경 0. 단 리뷰 반영으로 thresholds 소비처 추가·SSOT 승격(VOLUME_AVG_WINDOW_DAYS·PP_RECENT_SESSIONS)이 생겨 checklist 2축 표(축2 '없음') 작성(초안의 '트리거 아님' 철회).

---

### Task 1: 순수 유도 함수 `regime_window_state` + 창 상수, PR-2 규칙 제거

**Files:**
- Modify: `kr_pipeline/common/data_regimes.py` (regime_flag_for_as_of 제거, 함수 2개·상수 2개 추가)
- Test: `tests/test_volume_regime_bars.py` (test_regime_flag_for_as_of_pr2_rule 교체)

**Interfaces:**
- Produces: `regime_window_state(regimes: Iterable[str]) -> Literal["clean","mixed","new"]`, `window_flag(regimes: Iterable[str]) -> str | None` ('mixed' | None), `VOLUME_WINDOW_DAILY_BARS = VOLUME_AVG_WINDOW_DAYS`(50), `VOLUME_WINDOW_WEEKLY_WEEKS = CLIMAX_ANCHOR_VOL_AVG_WEEKS + 1`(51, 리뷰 반영).

- [ ] **Step 1: 실패 테스트** — `tests/test_volume_regime_bars.py` 의 `test_regime_flag_for_as_of_pr2_rule` 를 아래로 교체하고 import 에 `regime_window_state, window_flag, VOLUME_WINDOW_DAILY_BARS, VOLUME_WINDOW_WEEKLY_WEEKS` 추가, `regime_flag_for_as_of` import 제거.

```python
def test_regime_window_state_and_flag():
    assert regime_window_state([]) == "clean"
    assert regime_window_state(["regular"] * 50) == "clean"
    assert regime_window_state(["extended"] * 50) == "new"
    assert regime_window_state(["regular"] * 49 + ["extended"]) == "mixed"
    assert regime_window_state(["extended", "mixed"]) == "mixed"            # 주봉 mixed 포함
    assert window_flag(["regular"] * 50) is None and window_flag(["extended"] * 50) is None
    assert window_flag(["regular", "extended"]) == "mixed"
    assert (VOLUME_WINDOW_DAILY_BARS, VOLUME_WINDOW_WEEKLY_WEEKS) == (50, 50)


def test_pr2_interim_rule_is_gone():
    import kr_pipeline.common.data_regimes as m
    assert not hasattr(m, "regime_flag_for_as_of")
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_volume_regime_bars.py -q -k "window_state or interim_rule"` → ImportError/AttributeError.
- [ ] **Step 3: 구현** — `data_regimes.py` 에서 `regime_flag_for_as_of` 삭제, `FLAG_MIXED` 아래에:

```python
VOLUME_WINDOW_DAILY_BARS: Final[int] = 50     # daily_indicators.volume_ratio_50d / observed_breakout_volume_ratio 창(indicators/compute/volume.py)
VOLUME_WINDOW_WEEKLY_WEEKS: Final[int] = CLIMAX_ANCHOR_VOL_AVG_WEEKS + 1   # (리뷰 반영) C3 분자 주 포함 W+1


def regime_window_state(regimes: Iterable[str]) -> str:
    """창 안 봉들의 regime → clean(전부 regular) / new(전부 extended) / mixed(혼재 또는 주봉 mixed 포함). 빈 입력 = clean(spec D3)."""
    seen = set(regimes)
    if not seen or seen == {REGIME_REGULAR}:
        return "clean"
    if seen == {REGIME_EXTENDED}:
        return "new"
    return "mixed"


def window_flag(regimes: Iterable[str]) -> str | None:
    """판정 행 volume_regime_flag(D4): mixed 창만 'mixed', 그 외 NULL."""
    return FLAG_MIXED if regime_window_state(regimes) == "mixed" else None
```
(`from typing import Iterable` 복원.) store.py·runner.py 의 `regime_flag_for_as_of` import 는 Task 3·4 에서 교체되므로 이 Task 끝에서는 suite 가 ImportError 로 깨진다 — Task 3·4 까지 같은 커밋 묶음으로 진행하거나 임시로 import 를 `window_flag` 로 바꿔둔다(권장: Task 1~4 를 한 번에 RED→GREEN).
- [ ] **Step 4: 통과 확인** — 위 명령 PASS.

### Task 2: DB 창 헬퍼 `kr_pipeline/common/regime_windows.py`

**Files:**
- Create: `kr_pipeline/common/regime_windows.py`
- Test: `tests/test_regime_windows.py` (신규)

**Interfaces:**
- Consumes: `price_source(conn, ticker)` (`kr_pipeline/common/price_source.py:37`, `.daily`/`.weekly` 테이블명), `regime_for_date`, `regime_for_week`, `window_flag`, 상수 2개.
- Produces:
  - `daily_window_flag(conn, ticker: str, as_of, n: int = VOLUME_WINDOW_DAILY_BARS) -> str | None` — as_of 이하 최근 n 일봉 날짜 → regime → flag.
  - `weekly_window_flag(conn, ticker: str, as_of, n: int = VOLUME_WINDOW_WEEKLY_WEEKS) -> str | None` — as_of 이하 최근 n 주봉.
  - `weekly_range_flag(conn, ticker: str, start_week_end, as_of) -> str | None` — `week_end_date BETWEEN start AND as_of` 주봉(앵커 주~평가 주). `start_week_end` None 이면 None.
  - `judgment_flag(conn, ticker, as_of, *, daily=True, weekly=False) -> str | None` — 둘 중 하나라도 mixed 면 'mixed'(분류용).

- [ ] **Step 1: 실패 테스트** `tests/test_regime_windows.py`:

```python
"""#207 회신 21 Q-5c 2 — 판정 창(일봉 50/주봉 50/앵커~평가) 날짜로 volume_regime_flag 유도."""
from datetime import date, timedelta

from kr_pipeline.common.data_regimes import VOLUME_REGIME_BOUNDARY as B
from kr_pipeline.common.regime_windows import daily_window_flag, judgment_flag, weekly_range_flag, weekly_window_flag


def _seed_daily(db, ticker, dates):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT (ticker) DO NOTHING", (ticker, ticker))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (ticker,))
        cur.executemany("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) VALUES (%s,%s,1,1,1,1,1,1,1)",
                        [(ticker, d) for d in dates])


def _seed_weekly(db, ticker, week_ends):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT (ticker) DO NOTHING", (ticker, ticker))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (ticker,))
        cur.executemany("INSERT INTO weekly_prices (ticker, week_end_date, open, high, low, close, adj_close, volume, value, trading_days) "
                        "VALUES (%s,%s,1,1,1,1,1,1,1,5)", [(ticker, d) for d in week_ends])


def _weekdays(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_daily_window_flag_mixed_only_while_window_straddles_boundary(db):
    days = _weekdays(B - timedelta(days=120), 140)          # 경계 전후 넉넉히
    _seed_daily(db, "RWD1", days)
    before = [d for d in days if d < B]
    after = [d for d in days if d >= B]
    assert daily_window_flag(db, "RWD1", before[-1]) is None                  # 경계 전: clean
    assert daily_window_flag(db, "RWD1", after[0]) == "mixed"                 # 경계 당일: 49 regular + 1 extended
    assert daily_window_flag(db, "RWD1", after[48]) == "mixed"                # 50번째 봉 직전까지 mixed
    assert daily_window_flag(db, "RWD1", after[49]) is None                   # 경계 + 50봉: 전부 extended → new → NULL(자연 만료)


def test_daily_window_flag_with_fewer_bars_than_window(db):
    days = _weekdays(B - timedelta(days=5), 6)                                # 봉 6개뿐(신규 상장)
    _seed_daily(db, "RWD2", days)
    assert daily_window_flag(db, "RWD2", days[-1]) == "mixed"
    assert daily_window_flag(db, "RWD2", days[0]) is None


def test_weekly_window_and_range_flags(db):
    fridays = [date(2025, 10, 3) + timedelta(weeks=i) for i in range(60)]     # 금요일 60주(2025-10 ~ 2026-11)
    _seed_weekly(db, "RWW1", fridays)
    last_before = max(f for f in fridays if f < B)
    first_after = min(f for f in fridays if f >= B)
    assert weekly_window_flag(db, "RWW1", last_before) is None
    assert weekly_window_flag(db, "RWW1", first_after) == "mixed"
    assert weekly_range_flag(db, "RWW1", None, first_after) is None            # 앵커 없음 → 창 없음
    assert weekly_range_flag(db, "RWW1", first_after.isoformat(), first_after) is None   # 앵커=평가 주(extended 1주) → new
    assert weekly_range_flag(db, "RWW1", last_before.isoformat(), first_after) == "mixed"


def test_judgment_flag_combines_daily_and_weekly(db):
    days = _weekdays(B - timedelta(days=10), 60)                               # 일간 창: 경계 걸침
    _seed_daily(db, "RWJ1", days)
    fridays = [B + timedelta(days=4) + timedelta(weeks=i) for i in range(3)]   # 주간 창: 전부 extended
    _seed_weekly(db, "RWJ1", fridays)
    as_of = days[-1]
    assert judgment_flag(db, "RWJ1", as_of, daily=True, weekly=True) == "mixed"
    assert judgment_flag(db, "RWJ1", as_of, daily=False, weekly=True) is None
```

- [ ] **Step 2: 실패 확인** — `uv run pytest tests/test_regime_windows.py -q` → ModuleNotFoundError.
- [ ] **Step 3: 구현** `kr_pipeline/common/regime_windows.py`:

```python
"""(#207 회신 21 Q-5c 2) 판정 창의 봉 날짜 → volume_regime_flag 유도. regime 은 날짜의 함수라 저장 컬럼을 읽지 않는다
(data_regimes.regime_for_date/regime_for_week; #220 2차 리뷰 load 유도 전례). writer 가 conn·symbol·as_of 만 가지므로 판정당
1쿼리(LIMIT n) — spec §5 '추가 SQL 0 목표' 대체 근거."""
from __future__ import annotations

from datetime import date, datetime

from psycopg import Connection

from kr_pipeline.common.data_regimes import (
    VOLUME_WINDOW_DAILY_BARS, VOLUME_WINDOW_WEEKLY_WEEKS, regime_for_date, regime_for_week, window_flag,
)
from kr_pipeline.common.price_source import price_source


def _d(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def daily_window_flag(conn: Connection, ticker: str, as_of, n: int = VOLUME_WINDOW_DAILY_BARS) -> str | None:
    d = _d(as_of)
    if d is None:
        return None
    src = price_source(conn, ticker)
    with conn.cursor() as cur:
        cur.execute(f"SELECT date FROM {src.daily} WHERE ticker = %s AND date <= %s ORDER BY date DESC LIMIT %s", (ticker, d, n))
        return window_flag(regime_for_date(r[0]) for r in cur.fetchall())


def weekly_window_flag(conn: Connection, ticker: str, as_of, n: int = VOLUME_WINDOW_WEEKLY_WEEKS) -> str | None:
    d = _d(as_of)
    if d is None:
        return None
    src = price_source(conn, ticker)
    with conn.cursor() as cur:
        cur.execute(f"SELECT week_end_date FROM {src.weekly} WHERE ticker = %s AND week_end_date <= %s ORDER BY week_end_date DESC LIMIT %s",
                    (ticker, d, n))
        return window_flag(regime_for_week(r[0]) for r in cur.fetchall())


def weekly_range_flag(conn: Connection, ticker: str, start_week_end, as_of) -> str | None:
    """보유 평가(T2·T-D) 창 = 앵커 주 ~ 평가 주. 앵커 없음(None) = 창 없음 → NULL."""
    s, d = _d(start_week_end), _d(as_of)
    if s is None or d is None:
        return None
    src = price_source(conn, ticker)
    with conn.cursor() as cur:
        cur.execute(f"SELECT week_end_date FROM {src.weekly} WHERE ticker = %s AND week_end_date BETWEEN %s AND %s ORDER BY week_end_date",
                    (ticker, s, d))
        return window_flag(regime_for_week(r[0]) for r in cur.fetchall())


def judgment_flag(conn: Connection, ticker: str, as_of, *, daily: bool = True, weekly: bool = False) -> str | None:
    """분류 = 주간 C3 50주 ∪ 일간 50봉(둘 중 하나라도 mixed → mixed, spec §5). 트리거·진입 = 일간만."""
    flags = []
    if daily:
        flags.append(daily_window_flag(conn, ticker, as_of))
    if weekly:
        flags.append(weekly_window_flag(conn, ticker, as_of))
    return "mixed" if "mixed" in flags else None
```
- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_regime_windows.py -q` PASS.

### Task 3: store writer 4곳 창 유도로 교체

**Files:**
- Modify: `kr_pipeline/llm_runner/store.py:12`(import), `:434`, `:556`, `:678`, `:872`
- Test: `tests/test_volume_regime_tag.py` (CASES 기반 4 테스트를 창 시드 기반으로 교체)

**Interfaces:** Consumes `judgment_flag`. 시그니처 변경 0(conn·symbol·analyzed_for_date 이미 있음).

- [ ] **Step 1: 실패 테스트** — `tests/test_volume_regime_tag.py` 상단 import 를 `FLAG_MIXED, VOLUME_REGIME_BOUNDARY, ALLOW_EXCLUDED_REGIME_ENV, BACKTEST_EXCLUDED_FROM, assert_backtest_range_allowed` 로 두고, `CASES` 를 아래로 교체(일봉 시드가 창을 결정):

```python
def _seed_daily_window(db, ticker, as_of, *, straddle: bool):
    """straddle=True: 경계 전후 봉 → mixed. False: 경계 이후 봉 50개만 → new(NULL)."""
    start = (B - timedelta(days=30)) if straddle else B
    days, d = [], start
    while len(days) < 50:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT (ticker) DO NOTHING", (ticker, ticker))
        cur.execute("DELETE FROM daily_prices WHERE ticker=%s", (ticker,))
        cur.executemany("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) VALUES (%s,%s,1,1,1,1,1,1,1)",
                        [(ticker, x) for x in days])
    return days[-1]            # as_of 로 쓸 마지막 봉


CASES = [(True, FLAG_MIXED), (False, None)]      # (창이 경계에 걸침?, 기대 flag)
```
각 테스트는 `@pytest.mark.parametrize("straddle,flag", CASES)` 로 바꾸고 `as_of = _seed_daily_window(db, "VRF1", B, straddle=straddle)` 뒤 기존 insert 호출의 `analyzed_for_date=as_of` 로. 추가로 만료 테스트:

```python
def test_classification_flag_null_after_window_expires(db):
    """경계 + 50봉 이후 판정은 창이 전부 extended → NULL(자연 만료, spec §5)."""
    from kr_pipeline.llm_runner.store import insert_classification
    as_of = _seed_daily_window(db, "VRF9", B, straddle=False)
    with db.cursor() as cur:
        cur.execute("DELETE FROM weekly_classification WHERE symbol='VRF9'")
    insert_classification(db, symbol="VRF9", classified_at=datetime.now(timezone.utc), market="KOSPI",
                          result=_cls_result("watch"), source="weekend", llm_meta=_LLM_META, analyzed_for_date=as_of)
    assert _one(db, "SELECT volume_regime_flag FROM weekly_classification WHERE symbol='VRF9'")[0] is None
```
(기존 insert 호출 인자는 현재 파일의 것을 그대로 유지 — `_cls_result`/`_s9_result`/`_LLM_META`.)
- [ ] **Step 2: 실패 확인** — straddle=False 케이스가 'mixed' 로 실패(PR-2 규칙) 또는 ImportError.
- [ ] **Step 3: 구현** — `store.py:12` → `from kr_pipeline.common.regime_windows import judgment_flag`; 네 자리 교체:
  - `:434` insert_classification: `judgment_flag(conn, symbol, analyzed_for_date, daily=True, weekly=True),   # (#207 Q-5c 2) 분류 = 주간 C3 50주 ∪ 일간 50봉`
  - `:556` insert_backfill_classification: 동일(`weekly=True`).
  - `:678` insert_trigger_log: `judgment_flag(conn, symbol, analyzed_for_date),   # 일간 50봉(volume_ratio_50d 창)`
  - `:872` insert_entry_params: `judgment_flag(conn, symbol, analyzed_for_date),   # 일간 50봉(observed_breakout_volume_ratio 창)`
- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_volume_regime_tag.py tests/test_llm_runner_store.py -q` PASS.

### Task 4: 보유 평가(T2·T-D) flag = 앵커 주~평가 주 창

**Files:**
- Modify: `kr_pipeline/trade_management/runner.py:23`(import), `:189-193`·`:215-218`(호출), `:265-305`(두 헬퍼에 `symbol` 추가)
- Test: `tests/test_volume_regime_tag.py::test_position_evaluations_flag_column` 교체

**Interfaces:** `_insert_decline_eval(conn, *, position_id, symbol, as_of, ...)`, `_insert_climax_eval(conn, *, position_id, symbol, as_of, ...)` — flag = `weekly_range_flag(conn, symbol, anchor_week, as_of)`.

- [ ] **Step 1: 실패 테스트** — 기존 테스트를 교체:

```python
def _seed_weekly_range(db, ticker, week_ends):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES (%s,%s,'KOSPI') ON CONFLICT (ticker) DO NOTHING", (ticker, ticker))
        cur.execute("DELETE FROM weekly_prices WHERE ticker=%s", (ticker,))
        cur.executemany("INSERT INTO weekly_prices (ticker, week_end_date, open, high, low, close, adj_close, volume, value, trading_days) "
                        "VALUES (%s,%s,1,1,1,1,1,1,1,5)", [(ticker, d) for d in week_ends])


@pytest.mark.parametrize("anchor_offset_weeks,flag", [(-3, FLAG_MIXED), (0, None), (None, None)])
def test_position_evaluations_flag_from_anchor_window(db, anchor_offset_weeks, flag):
    """T2·T-D 창 = 앵커 주 ~ 평가 주: 경계 전 앵커 → mixed, 경계 후 앵커 → NULL, 앵커 없음 → NULL."""
    from kr_pipeline.trade_management.runner import _insert_climax_eval, _insert_decline_eval
    eval_week = B + timedelta(days=4)                                  # 10-02(금)
    fridays = [eval_week + timedelta(weeks=i) for i in range(-6, 1)]
    _seed_weekly_range(db, "VRF4", fridays)
    anchor = None if anchor_offset_weeks is None else (eval_week + timedelta(weeks=anchor_offset_weeks)).isoformat()
    with db.cursor() as cur:
        cur.execute("DELETE FROM positions WHERE symbol='VRF4'")
        cur.execute("INSERT INTO positions (symbol, entry_date, entry_price, quantity, status) VALUES ('VRF4', %s, 1000, 1, 'open') RETURNING id", (eval_week,))
        pid = cur.fetchone()[0]
    assert _insert_climax_eval(db, position_id=pid, symbol="VRF4", as_of=eval_week, fired=False, suppressed=False, hold_days=1, triggers=[],
                               anchor_week=anchor, weeks_since=None, maturity_ok=None, p2_accel_ok=None, scope_active=None, mode="quality")
    assert _insert_decline_eval(db, position_id=pid, symbol="VRF4", as_of=eval_week, fired=False, hold_days=1, signals=[], anchor_week=anchor,
                                weeks_since=None, maturity_ok=None, ta_max_decline_now=None, ta_d_daily_max_decline_now=None,
                                mode="quality", climax_also_fired=False)
    assert _one(db, "SELECT volume_regime_flag FROM position_climax_evaluations WHERE position_id=%s", pid)[0] == flag
    assert _one(db, "SELECT volume_regime_flag FROM position_decline_evaluations WHERE position_id=%s", pid)[0] == flag
```
- [ ] **Step 2: 실패 확인** — TypeError(`symbol` 미지원) 또는 (0, None) 케이스 'mixed'.
- [ ] **Step 3: 구현** — runner.py: import 를 `from kr_pipeline.common.regime_windows import weekly_range_flag` 로; 두 헬퍼 시그니처에 `symbol: str` 추가(position_id 다음), 튜플 마지막 `regime_flag_for_as_of(as_of)` → `weekly_range_flag(conn, symbol, anchor_week, as_of)`; 호출 2곳에 `symbol=p["symbol"]` 추가. docstring: "창 = 앵커 주~평가 주(spec D7), 앵커 없음 → NULL".
- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_volume_regime_tag.py tests/test_trade_held_climax.py tests/test_trade_held_decline.py tests/test_trade_positions.py -q` PASS.

### Task 5: Positions API·카드 배지(D9 잔여)

**Files:**
- Modify: `api/routers/positions.py:22-60` (LATERAL 2개 추가 + 응답 필드), `web/src/pages/PositionsPage.tsx:19-37`(타입)·`:142-155`(상태 셀)
- Test: `tests/test_api_positions.py` (케이스 추가)

**Interfaces:** 응답에 `"volume_regime_flag": "mixed" | None` (최신 climax/decline 평가 중 하나라도 mixed).

- [ ] **Step 1: 실패 테스트** `tests/test_api_positions.py` 끝에:

```python
def test_list_positions_exposes_volume_regime_flag(client, seed_position, db):
    """최신 보유 평가(climax/decline)의 volume_regime_flag 를 노출 — 둘 중 하나라도 mixed 면 mixed(spec D9 PR-3)."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO position_climax_evaluations (position_id, eval_date, fired, suppressed, hold_days, triggers, mode, volume_regime_flag) "
                    "VALUES (%s, '2026-10-01', FALSE, FALSE, 1, '[]', 'quality', NULL)", (seed_position,))
        cur.execute("INSERT INTO position_decline_evaluations (position_id, eval_date, fired, hold_days, signals, mode, climax_also_fired, volume_regime_flag) "
                    "VALUES (%s, '2026-10-01', FALSE, 1, '[]', 'quality', FALSE, 'mixed')", (seed_position,))
    db.commit()
    try:
        p = [x for x in client.get("/api/positions?status=open").json() if x["symbol"] == "APITEST1"][0]
        assert p["volume_regime_flag"] == "mixed"
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM position_climax_evaluations WHERE position_id=%s", (seed_position,))
            cur.execute("DELETE FROM position_decline_evaluations WHERE position_id=%s", (seed_position,))
        db.commit()
```
(`position_*_evaluations` NOT NULL 컬럼은 `\d` 로 확인해 보정.)
- [ ] **Step 2: 실패 확인** — KeyError `volume_regime_flag`.
- [ ] **Step 3: 구현** — SELECT 에 `c.volume_regime_flag AS climax_flag, d.volume_regime_flag AS decline_flag` 추가하고 LATERAL 2개:
```sql
LEFT JOIN LATERAL (SELECT volume_regime_flag FROM position_climax_evaluations  WHERE position_id = p.id ORDER BY eval_date DESC LIMIT 1) c ON true
LEFT JOIN LATERAL (SELECT volume_regime_flag FROM position_decline_evaluations WHERE position_id = p.id ORDER BY eval_date DESC LIMIT 1) d ON true
```
응답: `"volume_regime_flag": "mixed" if "mixed" in (r[24], r[25]) else None,   # (#207 Q-5c 2) T2·T-D 창 경계 표지`. 웹: `Position` 에 `volume_regime_flag: string | null;`, 상태 셀 `보유`/`매도 신호` 뒤에 `<VolumeRegimeBadge flag={p.volume_regime_flag} variant="inline" />`(import `../components/VolumeRegimeBadge`).
- [ ] **Step 4: 통과 확인** — `uv run pytest tests/test_api_positions.py -q` PASS, `cd web && npx tsc --noEmit -p . && npx vitest run`.

### Task 6: 문서·검증·PR

**Files:**
- Modify: `docs/superpowers/threshold-change-checklist.md`(이력 1줄), `docs/superpowers/specs/2026-09-30-volume-regime-design.md`(§7 PR-3 완료 표기·§5 "추가 SQL 0" 대체 근거), `kr_pipeline/db/schema.sql:1099` 주석(PR-2 규칙 → 창 유도)

- [ ] **Step 1: checklist 이력** — PR-2 이력 블록 끝에: "2026-10-02: #207 회신 21 Q-5c 2(PR-3, 브랜치 issue207-volume-regime-pr3) — thresholds.py·소비 룰 산술 변경 0(2축 표 트리거 아님). `volume_regime_flag` 를 창 유도로 축소: `data_regimes.regime_window_state`/`window_flag` + `common/regime_windows.py`(일봉 50·주봉 50·앵커~평가 주, 날짜 규칙 유도, 판정당 1쿼리). 소비처 5곳 writer 교체, PR-2 임시 규칙 `regime_flag_for_as_of` 삭제, Positions API·카드 배지. 자연 만료 테스트(경계+50봉 → NULL). 기존 PR-2 행 되돌림 불요(만료 전 전부 mixed 동일)."
- [ ] **Step 2: 전체 검증** — `pgrep -f "pytest tests/" || uv run pytest tests/ -q`(기대 1814+신규), `cd web && npx tsc --noEmit -p . && npx vitest run`.
- [ ] **Step 3: 커밋·push·PR** — `git add` 명시 경로, `git branch --show-current` 확인, `git push origin issue207-volume-regime-pr3`, `gh pr create --base main`. PR 본문: 요약·flag 규칙 전후·운영 영향(스키마 변경 0, 이관 불요)·검증.

## 리뷰 반영(10-02, PR #222)

`judgment_flag` → `classification_flag`/`daily_window_flag`/`entry_window_flag`(PP 탐색 +4봉), 주봉 창 W+1(SSOT import), decline 행 flag NULL(거래량 입력 없음 — spec D7 정정), run_daily_eval 이 T2 flag 1회 계산해 climax kwarg 로 전달, SAVEPOINT fail-soft·경계 전 DB 0, 이관 SQL flag 소급 삭제, `_as_date` 재사용·FLAG_MIXED·COALESCE. 기록만: 앵커 C3 분모 창(spec D7 범위).

## 리뷰 4차 반영(10-02)

이관 SQL 되돌림을 날짜 창 없이 규칙 기반(climax 는 eval_date 기준 주봉)으로, 분류 앵커 창의 우측 끝 = 주간 집계 MAX(as_of 달력 주 아님)·첫 mixed 즉시 반환·anchor_week 파싱 fail-soft, `_guarded` INERROR 선검사(psycopg 카운터 누수 방지), 진입 창 할트 여유(min_periods 40 → 10행), climax kwarg 필수·decline INSERT 컬럼 제거, `ZERO_BAR_SQL` 양의 형태로 fetcher 3곳 공유, 미사용 import 정리, spec §9 에 LLM 원시 봉 범위 밖 기록.

## 리뷰 3차 반영(10-02)

분류 창에 앵커에서 끝나는 C3 W+1 주 추가(앵커 적격 판정 분모), 앵커~평가 주는 (앵커, as_of) 양 끝 순수 유도(상한 버그 제거·SQL 0), `_guarded` 가 psycopg.Error 만 보수 'mixed'(프로그래밍 오류 전파), `PP_RECENT_SESSIONS` thresholds 승격(common→llm_runner 역방향 import 제거), zero-bar 술어 `price_source.NOT_ZERO_BAR_SQL` 공유, export_thresholds 재생성, 이관 SQL 에 PR-2 창(09-28~10-02) 되돌림 4문, 문서 모순 6건 정정·소비 경계 1줄.

## 리뷰 2차 반영(10-02)

분류 창에 앵커~평가 주 합집합(gates echo 의 anchor_week), 주봉 zero-bar 주 제외(산술과 같은 행 집합), MIN/MAX 집계 1문·DB 0 상한(일 400·주 800 달력일), fail-soft 값을 보수 'mixed' 로, 보유 climax flag 는 gates.week_ends 로 DB 0(`range_flag_from_week_ends`), decline LATERAL 제거·PR-2 잔존 행 되돌림 SQL, 상수 SSOT(`VOLUME_AVG_WINDOW_DAYS` 신설·`PP_RECENT_SESSIONS` 명명), 러너 통합 테스트, 2축 표.

## Self-Review

- **Spec coverage**: D3 유도 함수 → T1·T2; D4(mixed만) → T1 `window_flag`; §5 소비처 5곳 → T3(4곳)+T4(2곳: climax·decline); D7(발화 불변) → T4 는 INSERT 값만; D9 Positions → T5; §7 만료 테스트 → T2 `after[49]`·T3 `expires`. 백테스트 해제는 범위 외(§7 "완료 후 별건").
- **Placeholder scan**: 없음. T5 Step 1 의 NOT NULL 보정 지시는 실행 시 확인 항목.
- **Type consistency**: `judgment_flag(conn, ticker, as_of, *, daily, weekly)`, `weekly_range_flag(conn, ticker, start_week_end, as_of)`, 헬퍼 `symbol` kwarg — T2·T3·T4 동일.
