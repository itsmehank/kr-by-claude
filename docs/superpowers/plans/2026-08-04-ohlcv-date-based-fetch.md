# raw OHLCV 날짜별 전종목 수집 전환 (#94) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** daily/backfill의 raw OHLCV 수집을 종목별 KRX 스윕(2,549요청)에서 날짜별 전종목 스냅샷(달력일당 1요청, MDCSTAT01501)으로 교체해 KRX 차단 재발 원인을 제거한다.

**Architecture:** `fetch.py`에 날짜별 스냅샷 함수(`fetch_market_snapshot`)와 그것으로 raw를 조립하고 Naver adj를 종목별로 붙이는 `fetch_many_datewise`를 추가한다. 반환 계약을 기존 `fetch_many`와 동일하게 유지해 `_run_upsert`·`merge_raw_and_adjusted`·`nullify_halt_adj`·P1-5 empty 계정 경로를 그대로 재사용한다. 종목별 KRX 스윕 함수(`fetch_many`·`fetch_ohlcv_pair`)는 제거한다(재사용 사고 방지).

**Tech Stack:** Python 3.14, pandas, pykrx(로컬 .venv), pytest(+kr_test DB fixture), bash(launchd probe)

## Global Constraints

- 테스트 기준: `uv run pytest tests/` 실패 0, 1 skipped, 1 deselected (+이번 작업 신규 테스트)
- 실 KRX 접촉 테스트는 `krx` 마커 필수(기본 deselect). **이번 구현·테스트에서 KRX 실 접촉 금지** — 유일한 예외는 계약 검증 실측(아래 §계약 검증, 이미 수행)과 probe_krx.sh 수동 실행(08-06 이후)
- 커밋 제목은 한국어 명령문, `Co-Authored-By` 트레일러 금지, `git add`는 명시 경로만
- push는 게이트②(사용자 승인) 전 금지
- thresholds.py 의존성 맵: **비트리거** — ohlcv 모듈은 thresholds.py를 소비하지 않음(grep 0건 확인)

---

## 계약 검증 결과 (이슈 #94 할 일 1 — 계획 단계 필수)

| 항목 | 판정 | 근거 |
|---|---|---|
| 거래정지 표현 | **행 존재, OHLC·거래량=0, 종가만 직전가** | pykrx `stock_api.py` docstring NOTE("거래정지 종목은 종가만 존재하며 나머지는 0") — 기존 종목별 raw와 동일 계약이므로 `nullify_halt_adj`(OHLV=0 & close>0 검출) 그대로 정합. 실측 대조는 차단 해제 후 첫 실행의 sanity(bad_prices·halt 트립와이어)가 커버 |
| 컬럼 매핑 | 시가/고가/저가/종가/거래량/거래대금 → open/high/low/close/volume/value, 티커=index | pykrx `krx/market/wrap.py:116-160` — 응답에 등락률(FLUC_RT)·시가총액(MKTCAP)도 있으나 미소비. `to_price_rows`가 요구하는 raw 컬럼(open/high/low/close/volume/value) 전부 공급 가능 |
| 휴일 응답 | **빈 DF 아님 — 전 종목 OHLC=0 행 반환**(기본 `alternative=False`) | pykrx `stock_api.py:297` holiday 판정 로직. → 전량-0 스냅샷은 적재 금지(스킵)로 처리, 거래일 판별에 추가 KRX 접촉 불필요 |
| 차단 중 MDCSTAT01501 통과 | **불통(판정 불능) — 2026-08-04 18:25 실측: 로그인 단계부터 비-JSON 거부** | 인증 실측 1회(로그인 1 + 시도). 08-04 17:33 탐침은 3/3 성공했으므로 17:33 대량 스윕 재트리거 후 차단이 로그인까지 강화된 것으로 판정. **즉시 재개 전제 미충족** — 재실측은 probe_krx.sh(08-06+)에 스냅샷 판정을 통합해 수행(Task 4) |
| 시장 커버리지 | `market="ALL"`(STK+KSQ+KNX)이 1요청 — universe(KOSPI/KOSDAQ) 필터는 우리 쪽에서 | `wrap.py:134` market2mktid. KOSPI/KOSDAQ 2요청 대신 ALL 1요청 후 요청 티커 교집합 필터 |

**BACKFILL 적용 결정(이슈 할 일 6):** INCREMENTAL·BACKFILL 모두 같은 `_run_upsert` 경로이므로 **둘 다 날짜별로 전환**한다(모드 분기 없음). 요청 수: incremental 30달력일 ≈ 30요청(현행 2,549), backfill 2년 ≈ 730요청(현행 2,549). 두 모드 모두 감소하고 코드 경로가 하나로 유지된다.

**요청 수 주석:** "1~2요청/일"은 신규 1거래일만 증분할 때의 이론치다. 현행 incremental은 30일 window를 매일 재-upsert하므로 실제로는 평일당 1요청 × ~22 = **~22요청/일**이 된다(주말은 달력으로 skip — 리뷰 반영; 그래도 100×+ 감소). window 축소 최적화는 이 이슈 범위 밖(YAGNI).

**구현 후 독립 리뷰 반영(08-04):** ① 차단 실경로는 pykrx 가 KeyError 로 표면화(빈 DF 분기는 도달 불가) → try/except 정규화로 재시도 증폭(날짜당 3회) 차단 ② 주말 skip(접촉 ~30% 감소) ③ probe: 전종목시세 불통 시 rc=1(재개 오판 방지) ④ adj(Naver) 워커 페이싱 0.15s 복원. pre-existing 발견(adj 빈 DF 시 run 중단, merge_raw_and_adjusted KeyError)은 별도 이슈로 분리(#95).

**PR 코드리뷰 반영(08-04, 5각도+스코어링):** ⑤ 창 중간 하루 차단/실패가 무신호로 소멸하던 관측성 구멍 수리 — 스냅샷 status(blocked/holiday) 구분 → blocked 날짜를 failures 계정 → `_run_upsert`가 `snapshot_gap` 경고로 승격(failures 는 run_tracking 에 영속되지 않음을 실측 확인. INCREMENTAL 은 30일 window 재-upsert 로 자가치유되나 BACKFILL 은 1회성이라 경고 필수) ⑥ probe_krx.sh 헤더 접촉 산식 정정(python 서브프로세스 2개 = 로그인 2회 + 전종목시세 1회) ⑦ `fetch_many_datewise` docstring "달력일 수"→"평일 수" 정정.

---

## File Structure

- Modify: `kr_pipeline/ohlcv/fetch.py` — `fetch_market_snapshot`·`fetch_many_datewise` 추가, `fetch_many`·`fetch_ohlcv_pair` 삭제 (`_fetch_one`은 probe_krx.sh·adj 경로가 사용하므로 유지)
- Modify: `kr_pipeline/ohlcv/modes.py` — `_run_upsert`가 `fetch_many_datewise` 사용
- Modify: `scripts/launchd/probe_krx.sh` — 전종목시세 1요청 판정 추가
- Test: `tests/test_ohlcv_fetch_datewise.py` (신규), `tests/test_ohlcv_modes.py` (기존 2건 갱신 + halt 통합 1건 추가)

---

### Task 1: fetch_market_snapshot — 날짜별 전종목 스냅샷

**Files:**
- Modify: `kr_pipeline/ohlcv/fetch.py`
- Test: `tests/test_ohlcv_fetch_datewise.py` (신규)

**Interfaces:**
- Consumes: `pykrx.stock.get_market_ohlcv_by_ticker(date_str, market=...)` (티커 index, 한글 컬럼)
- Produces: `fetch_market_snapshot(d: date, market: str = "ALL") -> pd.DataFrame` — 컬럼 `ticker/date/open/high/low/close/volume/value`. 휴일(전량 OHLC=0)·빈 응답이면 **빈 DataFrame(위 컬럼 보유)**. 거래정지 행(OHLV=0, close>0)은 그대로 통과.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_ohlcv_fetch_datewise.py`

```python
"""#94 — 날짜별 전종목 스냅샷 수집 테스트 (KRX 실 접촉 없음, 전부 monkeypatch)."""
from datetime import date

import pandas as pd

import kr_pipeline.ohlcv.fetch as fetch_mod


def _krx_frame(rows: dict) -> pd.DataFrame:
    """pykrx get_market_ohlcv_by_ticker 모양(티커 index, 한글 컬럼)의 프레임."""
    df = pd.DataFrame(rows)
    return df.set_index("티커")


def test_snapshot_maps_columns_and_stamps_date(monkeypatch):
    krx = _krx_frame({
        "티커": ["005930", "000660"],
        "시가": [70000, 120000], "고가": [71000, 122000],
        "저가": [69500, 119000], "종가": [70500, 121000],
        "거래량": [1000, 2000], "거래대금": [70_500_000, 242_000_000],
        "등락률": [0.5, -1.0], "시가총액": [1, 2],
    })
    monkeypatch.setattr(fetch_mod.stock, "get_market_ohlcv_by_ticker",
                        lambda ds, market: krx)
    out = fetch_mod.fetch_market_snapshot(date(2026, 8, 4))
    assert list(out.columns) == ["ticker", "open", "high", "low", "close", "volume", "value", "date"]
    assert out.loc[out["ticker"] == "005930", "value"].item() == 70_500_000
    assert (out["date"] == date(2026, 8, 4)).all()
    assert "등락률" not in out.columns


def test_snapshot_holiday_all_zero_returns_empty(monkeypatch):
    """휴일: KRX 가 전 종목 OHLC=0 행을 반환 — 적재 금지 계약이므로 빈 DF."""
    krx = _krx_frame({
        "티커": ["005930", "000660"],
        "시가": [0, 0], "고가": [0, 0], "저가": [0, 0], "종가": [0, 0],
        "거래량": [0, 0], "거래대금": [0, 0], "등락률": [0.0, 0.0], "시가총액": [0, 0],
    })
    monkeypatch.setattr(fetch_mod.stock, "get_market_ohlcv_by_ticker",
                        lambda ds, market: krx)
    out = fetch_mod.fetch_market_snapshot(date(2026, 8, 2))
    assert out.empty
    assert list(out.columns) == ["ticker", "open", "high", "low", "close", "volume", "value", "date"]


def test_snapshot_empty_response_returns_empty(monkeypatch):
    """차단/빈 응답: pykrx 빈 DF → 빈 스냅샷 (호출자가 empty 계정 — P1-5 보존)."""
    monkeypatch.setattr(fetch_mod.stock, "get_market_ohlcv_by_ticker",
                        lambda ds, market: pd.DataFrame())
    out = fetch_mod.fetch_market_snapshot(date(2026, 8, 4))
    assert out.empty


def test_snapshot_halt_row_passes_through(monkeypatch):
    """거래정지(OHLV=0, 종가만 존재) 행은 raw 계약 그대로 보존 — nullify 는 adj 층 몫."""
    krx = _krx_frame({
        "티커": ["005930", "HALTD"],
        "시가": [70000, 0], "고가": [71000, 0], "저가": [69500, 0], "종가": [70500, 5000],
        "거래량": [1000, 0], "거래대금": [70_500_000, 0],
        "등락률": [0.5, 0.0], "시가총액": [1, 0],
    })
    monkeypatch.setattr(fetch_mod.stock, "get_market_ohlcv_by_ticker",
                        lambda ds, market: krx)
    out = fetch_mod.fetch_market_snapshot(date(2026, 8, 4))
    halt = out[out["ticker"] == "HALTD"].iloc[0]
    assert halt["open"] == 0 and halt["close"] == 5000
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_ohlcv_fetch_datewise.py -v`
Expected: 4 FAIL — `AttributeError: ... has no attribute 'fetch_market_snapshot'`

- [ ] **Step 3: 최소 구현** — `kr_pipeline/ohlcv/fetch.py`의 `fetch_index` 아래에 추가

```python
SNAPSHOT_COLUMNS = ["ticker", "open", "high", "low", "close", "volume", "value", "date"]

_SNAPSHOT_RENAME = {
    "티커": "ticker", "시가": "open", "고가": "high",
    "저가": "low", "종가": "close", "거래량": "volume", "거래대금": "value",
}


def _empty_snapshot() -> pd.DataFrame:
    return pd.DataFrame(columns=SNAPSHOT_COLUMNS)


@with_retry(attempts=3, wait_seconds=1.0)
def fetch_market_snapshot(d: date, market: str = "ALL") -> pd.DataFrame:
    """일자별 전종목 raw OHLCV — KRX 전종목시세(MDCSTAT01501) 단일 요청 (#94).

    종목별 스윕(2,549요청)이 차단 재트리거로 실측돼(run 1235, 86.2% 빈 응답)
    날짜별 1요청으로 대체. market="ALL" 이면 KOSPI+KOSDAQ+KONEX 가 한 번에 오고
    universe 교집합은 호출자(fetch_many_datewise)가 거른다.

    - 휴일: KRX 가 전 종목 OHLC=0 행을 반환(빈 DF 아님) → 빈 스냅샷으로 정규화
      (적재 금지 — bad_prices sanity·halt 마커 규약·weekly 파생 오염 방지).
    - 차단/빈 응답: 빈 스냅샷 — 호출자의 empty 계정(P1-5)이 경고로 승격.
    - 거래정지 행(OHLV=0, close>0)은 그대로 통과 — raw 의 halt 마커 계약이며
      adj NULL 화는 merge_raw_and_adjusted → nullify_halt_adj 가 수행.
    """
    df = stock.get_market_ohlcv_by_ticker(d.strftime("%Y%m%d"), market=market)
    if df.empty:
        log.info(f"snapshot {d}: empty response")
        return _empty_snapshot()
    if (df[["시가", "고가", "저가", "종가"]] == 0).all(axis=None):
        log.info(f"snapshot {d}: holiday (all-zero)")
        return _empty_snapshot()
    df = df.reset_index().rename(columns=_SNAPSHOT_RENAME)
    df["date"] = d
    return df[SNAPSHOT_COLUMNS]
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_ohlcv_fetch_datewise.py -v`
Expected: 4 PASS

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/ohlcv/fetch.py tests/test_ohlcv_fetch_datewise.py
git commit -m "feat(#94): 날짜별 전종목 스냅샷 fetch_market_snapshot 추가 — 휴일 전량-0 정규화 포함"
```

---

### Task 2: fetch_many_datewise — raw 조립 + Naver adj 결합

**Files:**
- Modify: `kr_pipeline/ohlcv/fetch.py`
- Test: `tests/test_ohlcv_fetch_datewise.py`

**Interfaces:**
- Consumes: Task 1의 `fetch_market_snapshot(d, market="ALL")`, 기존 `_fetch_one(ticker, start, end, adjusted=True)`(Naver adj, 컬럼 date/open/high/low/close/volume/value)
- Produces: `fetch_many_datewise(tickers: list[str], start: date, end: date, *, max_workers: int = 3) -> tuple[dict[str, tuple[pd.DataFrame, pd.DataFrame]], list[tuple[str, str]]]` — **기존 `fetch_many`와 동일 반환 계약**: `{ticker: (raw, adj)}` + `[(식별자, 오류)]`. raw가 빈 종목도 dict에 남는다(P1-5 empty 계정용). 스냅샷 실패 식별자는 `"snapshot:YYYY-MM-DD"`.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_ohlcv_fetch_datewise.py`에 추가

```python
def _snap(d, rows):
    df = pd.DataFrame(rows)
    df["date"] = d
    return df[fetch_mod.SNAPSHOT_COLUMNS]


def _adj_frame(dates, closes):
    return pd.DataFrame({
        "date": dates, "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": [1] * len(dates), "value": [1] * len(dates),
    })


def test_datewise_assembles_raw_and_filters_universe(monkeypatch):
    """날짜 2일 스냅샷 → 종목별 raw 조립. universe 밖 티커(NEWIPO)는 제외."""
    snaps = {
        date(2026, 8, 3): _snap(date(2026, 8, 3), {
            "ticker": ["A", "B", "NEWIPO"], "open": [1, 2, 9], "high": [1, 2, 9],
            "low": [1, 2, 9], "close": [1, 2, 9], "volume": [10, 20, 90], "value": [100, 200, 900],
        }),
        date(2026, 8, 4): _snap(date(2026, 8, 4), {
            "ticker": ["A"], "open": [3], "high": [3], "low": [3], "close": [3],
            "volume": [30], "value": [300],
        }),
    }
    monkeypatch.setattr(fetch_mod, "fetch_market_snapshot",
                        lambda d, market="ALL": snaps.get(d, fetch_mod._empty_snapshot()))
    monkeypatch.setattr(fetch_mod, "_fetch_one",
                        lambda t, s, e, adjusted: _adj_frame([date(2026, 8, 3)], [1.0]))
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)

    successes, failures = fetch_mod.fetch_many_datewise(
        ["A", "B", "C"], date(2026, 8, 3), date(2026, 8, 4), max_workers=2)

    assert failures == []
    assert set(successes) == {"A", "B", "C"}          # NEWIPO 없음, 미출현 C 는 남음
    raw_a = successes["A"][0]
    assert list(raw_a["date"]) == [date(2026, 8, 3), date(2026, 8, 4)]  # 날짜 정렬
    assert successes["B"][0].shape[0] == 1
    assert successes["C"][0].empty                     # 활성인데 미출현 → empty 계정 대상


def test_datewise_snapshot_failure_recorded_others_continue(monkeypatch):
    """한 날짜의 스냅샷 예외는 failures 로 남고 다른 날짜는 계속 처리."""
    def snap(d, market="ALL"):
        if d == date(2026, 8, 3):
            raise RuntimeError("boom")
        return _snap(d, {"ticker": ["A"], "open": [3], "high": [3], "low": [3],
                         "close": [3], "volume": [30], "value": [300]})
    monkeypatch.setattr(fetch_mod, "fetch_market_snapshot", snap)
    monkeypatch.setattr(fetch_mod, "_fetch_one",
                        lambda t, s, e, adjusted: pd.DataFrame())
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)

    successes, failures = fetch_mod.fetch_many_datewise(
        ["A"], date(2026, 8, 3), date(2026, 8, 4), max_workers=1)

    assert ("snapshot:2026-08-03" in dict(failures))
    assert successes["A"][0].shape[0] == 1


def test_datewise_adj_failure_retried_then_recorded(monkeypatch):
    """adj(Naver) 실패는 1회 재시도 후 실패 기록 — fetch_many 패턴 보존."""
    calls = {"n": 0}

    def adj_fail(t, s, e, adjusted):
        calls["n"] += 1
        raise RuntimeError("naver down")
    monkeypatch.setattr(fetch_mod, "fetch_market_snapshot",
                        lambda d, market="ALL": fetch_mod._empty_snapshot())
    monkeypatch.setattr(fetch_mod, "_fetch_one", adj_fail)
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)

    successes, failures = fetch_mod.fetch_many_datewise(
        ["A"], date(2026, 8, 4), date(2026, 8, 4), max_workers=1)

    assert calls["n"] == 2                 # 본 시도 + 재시도
    assert "A" in dict(failures)
    assert "A" not in successes
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_ohlcv_fetch_datewise.py -v`
Expected: 신규 3건 FAIL — `fetch_many_datewise` 미정의

- [ ] **Step 3: 구현** — `fetch.py`의 `fetch_market_snapshot` 아래에 추가 (`from datetime import date, timedelta`로 import 갱신)

```python
def fetch_many_datewise(
    tickers: list[str],
    start: date,
    end: date,
    *,
    max_workers: int = 3,
) -> tuple[dict[str, tuple[pd.DataFrame, pd.DataFrame]], list[tuple[str, str]]]:
    """날짜별 전종목 스냅샷으로 raw 를 조립하고 종목별 Naver adj 를 붙인다 (#94).

    KRX 접촉 = 달력일 수 × 1요청(전종목시세). 종목별 KRX 스윕 0회.
    adj(수정 OHLCV)는 Naver 경유(adjusted=True)라 차단과 무관 — 종목별 유지.
    반환 계약은 구 fetch_many 와 동일: ({ticker: (raw, adj)}, [(식별자, 오류)]).
    raw 미출현 종목도 (빈 raw, adj) 로 dict 에 남아 P1-5 empty 계정이 잡는다.
    """
    wanted = set(tickers)
    frames: list[pd.DataFrame] = []
    failures: list[tuple[str, str]] = []

    d = start
    while d <= end:
        try:
            snap = fetch_market_snapshot(d)
            if not snap.empty:
                frames.append(snap[snap["ticker"].isin(wanted)])
        except Exception as e:
            failures.append((f"snapshot:{d.isoformat()}", str(e)))
        time.sleep(0.2)  # 날짜 간 페이싱 — 재탐지 방지
        d += timedelta(days=1)

    raw_by_ticker: dict[str, pd.DataFrame] = {}
    if frames:
        raw_all = pd.concat(frames, ignore_index=True)
        raw_by_ticker = {
            t: g.drop(columns=["ticker"]).sort_values("date").reset_index(drop=True)
            for t, g in raw_all.groupby("ticker")
        }

    def _raw_for(t: str) -> pd.DataFrame:
        got = raw_by_ticker.get(t)
        if got is not None:
            return got
        return pd.DataFrame(columns=[c for c in SNAPSHOT_COLUMNS if c != "ticker"])

    successes: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    adj_failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_one, t, start, end, True): t for t in tickers}
        for i, fut in enumerate(as_completed(futures), 1):
            ticker = futures[fut]
            try:
                successes[ticker] = (_raw_for(ticker), fut.result())
            except Exception as e:
                adj_failures.append((ticker, str(e)))
            if i % 100 == 0:
                log.info(f"adj progress: {i}/{len(tickers)} (failures so far: {len(adj_failures)})")

    # adj 1차 실패 재시도 (구 fetch_many 패턴)
    if adj_failures:
        log.warning(f"Retrying {len(adj_failures)} failed adj tickers")
        for ticker, _ in adj_failures:
            try:
                successes[ticker] = (_raw_for(ticker), _fetch_one(ticker, start, end, True))
            except Exception as e:
                failures.append((ticker, str(e)))

    return successes, failures
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_ohlcv_fetch_datewise.py -v`
Expected: 7 PASS (Task 1의 4건 포함)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/ohlcv/fetch.py tests/test_ohlcv_fetch_datewise.py
git commit -m "feat(#94): fetch_many_datewise — 스냅샷 raw 조립 + Naver adj 결합, fetch_many 반환 계약 유지"
```

---

### Task 3: _run_upsert 전환 + 구 스윕 함수 제거

**Files:**
- Modify: `kr_pipeline/ohlcv/modes.py:10` (import), `modes.py:221-250` (`_run_upsert`)
- Modify: `kr_pipeline/ohlcv/fetch.py` (`fetch_many`·`fetch_ohlcv_pair` 삭제)
- Test: `tests/test_ohlcv_modes.py:230-267` (기존 2건 갱신) + halt 통합 테스트 1건 추가

**Interfaces:**
- Consumes: Task 2의 `fetch_many_datewise` (동일 반환 계약)
- Produces: `_run_upsert` 시그니처 불변. `fetch_many`·`fetch_ohlcv_pair`는 코드베이스에서 사라짐(참조 0 확인 후 삭제).

- [ ] **Step 1: 기존 테스트 2건을 새 이름으로 갱신** — `tests/test_ohlcv_modes.py`

`test_run_upsert_accounts_empty_fetches`(239-242행)와 `test_run_upsert_no_empty_no_warning`(262행)의 monkeypatch 대상을 교체:

```python
    monkeypatch.setattr(
        modes, "fetch_many_datewise",
        lambda tickers, s, e, max_workers: ({t: (empty, empty) for t in tickers}, []),
    )
```

```python
    monkeypatch.setattr(modes, "fetch_many_datewise", lambda tickers, s, e, max_workers: ({}, []))
```

그리고 halt 통합 테스트를 추가 (스냅샷 halt 행 → daily_prices에 adj_* NULL·raw 보존):

```python
def test_run_upsert_datewise_halt_row_nullifies_adj(monkeypatch, db):
    """날짜별 수집 경로에서도 거래정지 행은 raw 0/종가 보존 + adj_* NULL (#94).

    스냅샷의 halt 계약(OHLV=0, close>0)이 merge_raw_and_adjusted →
    nullify_halt_adj chokepoint 를 그대로 통과하는지 DB 실물로 확인.
    """
    from kr_pipeline.ohlcv import modes

    raw = pd.DataFrame({
        "date": [date(2026, 7, 2)], "open": [0], "high": [0], "low": [0],
        "close": [5000], "volume": [0], "value": [0],
    })
    adj = pd.DataFrame({
        "date": [date(2026, 7, 2)], "open": [0.0], "high": [0.0], "low": [0.0],
        "close": [5000.0], "volume": [0.0], "value": [0.0],
    })
    monkeypatch.setattr(
        modes, "fetch_many_datewise",
        lambda tickers, s, e, max_workers: ({"HLT": (raw, adj)}, []),
    )
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])

    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES ('HLT', '정지주', 'KOSPI') "
            "ON CONFLICT (ticker) DO NOTHING")
        db.commit()

    modes._run_upsert(db, ["HLT"], date(2026, 7, 1), date(2026, 7, 7), 2, modes.Mode.INCREMENTAL)

    with db.cursor() as cur:
        cur.execute(
            "SELECT open, close, adj_close, adj_open, adj_volume FROM daily_prices "
            "WHERE ticker='HLT' AND date='2026-07-02'")
        row = cur.fetchone()
    assert row is not None
    o, c, adj_close, adj_open, adj_volume = row
    assert o == 0 and c == 5000            # raw halt 마커 보존
    assert adj_close is not None            # 종가는 유지
    assert adj_open is None and adj_volume is None  # OHLV → NULL
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_ohlcv_modes.py -v -k "run_upsert"`
Expected: 갱신 2건 — `AttributeError: ... 'fetch_many_datewise'` (modes에 아직 없음), 신규 1건 동일 사유 FAIL

- [ ] **Step 3: modes.py 전환**

`modes.py:10`:

```python
from kr_pipeline.ohlcv.fetch import fetch_many_datewise, fetch_index
```

`modes.py:222` (`_run_upsert` 첫 줄):

```python
    successes, failures = fetch_many_datewise(tickers, start, end, max_workers=max_workers)
```

- [ ] **Step 4: 구 함수 삭제 전 참조 0 확인**

Run: `grep -rn "fetch_many\b\|fetch_ohlcv_pair" kr_pipeline scripts tests --include="*.py" --include="*.sh" | grep -v datewise`
Expected: `fetch.py` 정의 2곳만 남음 → `fetch.py`에서 `fetch_ohlcv_pair`(82-87행)·`fetch_many`(120-153행) 삭제. `_fetch_one`·`fetch_adj_only`·`fetch_index`는 유지(각각 adj 경로/probe·full-refresh·지수가 사용).

- [ ] **Step 5: 통과 확인 + 회귀 확인**

Run: `uv run pytest tests/test_ohlcv_modes.py tests/test_ohlcv_fetch_datewise.py tests/test_ohlcv_transform.py -v`
Expected: 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add kr_pipeline/ohlcv/modes.py kr_pipeline/ohlcv/fetch.py tests/test_ohlcv_modes.py
git commit -m "feat(#94): _run_upsert 를 날짜별 수집으로 전환, 종목별 raw 스윕(fetch_many) 제거"
```

---

### Task 4: probe_krx.sh 스냅샷 판정 추가 + 전체 검증

**Files:**
- Modify: `scripts/launchd/probe_krx.sh` (3종목 판정 뒤에 추가)

**Interfaces:**
- Consumes: Task 1의 `fetch_market_snapshot`
- Produces: probe 출력에 `[probe] 전종목시세: N행` 판정 1줄 — #94 경로의 차단 해제 여부를 3종목 판정과 별도로 보고 (KRX 접촉 +1요청)

- [ ] **Step 1: probe_krx.sh 수정** — `exit 0` 직전(마지막 판정 후)에 추가

```bash
# #94 날짜별 수집 경로 판정 — 전종목시세(MDCSTAT01501) 1요청.
# 3종목(개별 조회) 통과 ≠ 전종목시세 통과 (08-04 실측: endpoint 별로 차단이 갈림).
echo "[probe] 전종목시세(MDCSTAT01501) 1요청 판정 (#94)"
SNAP_OUT=$(uv run python -c "
from kr_pipeline.common import config  # noqa: F401 — .env 로드(KRX 인증)
from datetime import date, timedelta
from kr_pipeline.ohlcv.fetch import fetch_market_snapshot

d = date.today()
while d.weekday() >= 5:   # 주말이면 직전 평일 (KRX 추가 접촉 없는 순수 달력 계산)
    d -= timedelta(days=1)
try:
    df = fetch_market_snapshot(d)
    print('SNAP_ROWS', len(df))
except Exception as e:  # noqa: BLE001
    print(f'SNAP_ROWS -1 {type(e).__name__}')
" 2>&1)
echo "$SNAP_OUT" | grep -v '로그인 ID'
SNAP_ROWS=$(echo "$SNAP_OUT" | grep -E '^SNAP_ROWS ' | awk '{print $2}')
if [ -z "$SNAP_ROWS" ] || [ "$SNAP_ROWS" = "-1" ] || [ "$SNAP_ROWS" = "0" ]; then
  echo "[probe] 전종목시세 판정: 불통(0행/오류 — 평일 공휴일이면 오판 가능, 수동 재확인)"
else
  echo "[probe] 전종목시세 판정: 통과(${SNAP_ROWS}행) — 날짜별 수집 재개 가능"
fi
```

주의: 기존 `exit 0`/`exit 1` 구조 유지 — 스냅샷 판정은 exit code 를 바꾸지 않는다(3종목 판정이 기존 재개 게이트, 스냅샷 판정은 #94 경로 정보 제공).

- [ ] **Step 2: 문법 검증 (실행 아님 — 날짜 가드가 08-06 전 실행을 막고, 실행 자체가 KRX 접촉)**

Run: `bash -n scripts/launchd/probe_krx.sh`
Expected: 출력 없음(문법 OK)

- [ ] **Step 3: 전체 suite 실행**

Run: `uv run pytest tests/`
Expected: 실패 0, 1 skipped, 1 deselected (+신규 8건 포함 passed)

- [ ] **Step 4: 커밋**

```bash
git add scripts/launchd/probe_krx.sh
git commit -m "feat(#94): probe_krx.sh 에 전종목시세 1요청 판정 추가 — 날짜별 경로 해제 확인용"
```

---

## Self-Review 결과

- 이슈 #94 완료 조건 대응: 종목별 raw 스윕 0회(Task 3에서 함수 자체 삭제) / 휴일 전량-0 미적재(Task 1) / halt 동등 처리(Task 3 통합 테스트) / universe 교집합·미출현 empty 계정(Task 2) / 계약 검증 기록(본 문서 §계약 검증) / suite 기준(Task 4) / krx 마커(신규 테스트 전부 mock — 실 접촉 0)
- 타입 일관성: `fetch_many_datewise` 반환 계약 = 구 `fetch_many` 와 동일함을 Task 2 Produces 에 명시, Task 3 이 그대로 소비
- 유의: `_load_active_tickers` 가 요청 티커의 단일 출처 — 스냅샷의 신규상장 필터는 `wanted` 교집합으로 처리(별도 stocks 조회 없음)
