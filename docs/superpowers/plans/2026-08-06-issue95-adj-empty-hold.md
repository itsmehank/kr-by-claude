> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# 빈 adj 처리 설계 변경 — 적재 보류 + 경고 + run 내 재시도 (PR #97 반영) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR #97의 빈 adj 처리를 "raw fallback으로 적재"에서 "그 종목 적재 통째 보류 + `adj_empty_fetch` 경고 + run 내 재시도 1회"로 바꿔, 일시 빈 응답이 기존 올바른 adj를 raw로 덮어쓰는 오염 경로를 차단한다(리뷰 major 지적 + 사용자 설계 결정).

**Architecture:** 3층 분담 — ① `fetch_many_datewise`(fetch.py)가 "raw 있음+adj 빈" 종목을 run 안에서 1회 재요청(일시 장애 흡수) ② `_run_upsert`(modes.py)가 그래도 빈 종목의 **upsert를 건너뛰고**(기존 DB 행 불변) `adj_empty_fetch` 경고로 승격 ③ `merge_raw_and_adjusted`의 기존 가드(PR #97 본체)는 방어층으로 유지(이슈 #95 완료 조건 ①의 단위 계약). 보류된 종목은 다음 정상 run의 30일 창 재수집이 자연 보충한다.

**Tech Stack:** Python 3.14, pandas, pytest(+kr_test DB fixture)

## Global Constraints

- 작업 브랜치: `issue-95-empty-adj-guard` (PR #97, 로컬 존재 확인됨 — main repo에서 checkout하여 진행. worktree는 삭제됨)
- 테스트 기준: `uv run pytest tests/` 실패 0, 1 skipped, 1 deselected. 브랜치 baseline 1195 passed → 본 계획 완료 후 **1198 passed** 예상(신규 +3)
- 전체 suite 실행 전 `pgrep -fl pytest`로 교차 세션 경합 확인(kr_test 스키마 리셋 경합)
- KRX/Naver 실 접촉 금지 — 신규 테스트 전부 monkeypatch
- 커밋: 한국어 명령문, co-author 트레일러 금지, 스테이징은 명시 경로만, `.env`·`.loop/` 커밋 금지
- adj_* 컬럼의 NULL은 거래정지(halt) 마커 의미로 예약 — "부분 저장(raw만 갱신)" 방식을 쓰지 않는 이유(별도 upsert SQL 필요·의미 충돌). 보류는 **종목 통째 skip**으로 구현
- 이슈 #95 완료 조건 정합: ①(merge 단위 raw fallback — 기존 단위 테스트 불변) ②(다른 종목 적재 불차단 — 통합 테스트를 새 의미로 재작성) ③(suite 기준) 전부 유지

---

## File Structure

- Modify: `kr_pipeline/ohlcv/fetch.py` — `fetch_many_datewise` 끝부분에 빈-adj 재시도 블록 추가
- Modify: `kr_pipeline/ohlcv/modes.py:221-233` — `_run_upsert` 루프에 보류 분기 + 경고 승격
- Modify: `kr_pipeline/ohlcv/transform.py` — `#95` 가드 주석에 파이프라인 보류 관계 1문장 추가(코드 불변)
- Test: `tests/test_ohlcv_fetch_datewise.py` (신규 2건), `tests/test_ohlcv_modes.py` (기존 통합 1건 의미 재작성)

---

### Task 1: fetch_many_datewise — 빈-adj 재시도 1회

**Files:**
- Modify: `kr_pipeline/ohlcv/fetch.py` (`fetch_many_datewise`의 `return successes, failures` 직전)
- Test: `tests/test_ohlcv_fetch_datewise.py`

**Interfaces:**
- Consumes: 기존 `_adj_task(t)` 내부 함수(adj 1회 요청 + 0.15s 페이싱), `successes: dict[str, tuple[raw, adj]]`
- Produces: 반환 계약 불변. "raw 비어있지 않음 + adj.empty" 종목만 `_adj_task` 1회 재시도 — 성공하면 successes의 adj 교체, 여전히 비면 그대로 둔다(**failures에 넣지 않음** — 계정은 Task 2의 경고가 담당). **재시도 상한 `_EMPTY_ADJ_RETRY_MAX = 20`**: 빈-adj 종목이 상한 초과면 광역 장애(전 종목 빈 응답 등)로 보고 재시도를 통째로 생략한다 — 일시 장애 흡수가 목적이지 광역 장애 2배 접촉이 목적이 아님(#92 시도 상한 원칙). 재시도 중 **예외** 발생 시 failures에 기록하되 successes의 (raw, 빈 adj)도 남긴다 — 그 종목은 failures(로그)와 adj_empty_fetch 경고(영속) **양쪽에 의도적으로 이중 계정**된다(failures는 DB에 영속되지 않으므로 경고가 주 신호).

- [ ] **Step 1: 실패하는 테스트 2건 작성** — `tests/test_ohlcv_fetch_datewise.py` 끝에 추가

```python
def test_datewise_empty_adj_retried_once_and_filled(monkeypatch):
    """raw 있음 + adj 빈 응답이면 run 안에서 1회 재시도 — 성공 시 adj 교체."""
    calls = {"n": 0}

    def adj_flaky(t, s, e, adjusted):
        calls["n"] += 1
        if calls["n"] == 1:
            return pd.DataFrame()          # 1차: 빈 응답 (일시 장애)
        return _adj_frame([date(2026, 8, 4)], [1.0])
    monkeypatch.setattr(fetch_mod, "fetch_market_snapshot",
                        lambda d, market="ALL": _snap(d, {
                            "ticker": ["A"], "open": [3], "high": [3], "low": [3],
                            "close": [3], "volume": [30], "value": [300],
                        }))
    monkeypatch.setattr(fetch_mod, "_fetch_one", adj_flaky)
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)

    successes, failures = fetch_mod.fetch_many_datewise(
        ["A"], date(2026, 8, 4), date(2026, 8, 4), max_workers=1)

    assert calls["n"] == 2                       # 본 시도 + 빈-adj 재시도
    assert not successes["A"][1].empty           # 재시도 성공분으로 교체됨
    assert failures == []


def test_datewise_empty_adj_still_empty_after_retry_kept(monkeypatch):
    """재시도해도 빈 adj 면 (raw, 빈 adj) 그대로 유지 — 계정은 _run_upsert 몫,
    failures 에 넣지 않는다(예외가 아니므로)."""
    calls = {"n": 0}

    def adj_always_empty(t, s, e, adjusted):
        calls["n"] += 1
        return pd.DataFrame()
    monkeypatch.setattr(fetch_mod, "fetch_market_snapshot",
                        lambda d, market="ALL": _snap(d, {
                            "ticker": ["A"], "open": [3], "high": [3], "low": [3],
                            "close": [3], "volume": [30], "value": [300],
                        }))
    monkeypatch.setattr(fetch_mod, "_fetch_one", adj_always_empty)
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)

    successes, failures = fetch_mod.fetch_many_datewise(
        ["A"], date(2026, 8, 4), date(2026, 8, 4), max_workers=1)

    assert calls["n"] == 2
    assert successes["A"][1].empty
    assert failures == []


def test_datewise_empty_adj_retry_skipped_over_cap(monkeypatch):
    """빈-adj 종목이 상한(_EMPTY_ADJ_RETRY_MAX) 초과면 재시도 생략 — 광역 장애에서
    Naver 접촉 2배·run 팽창 방지(#92 시도 상한 원칙)."""
    tickers = [f"T{i:03d}" for i in range(fetch_mod._EMPTY_ADJ_RETRY_MAX + 1)]
    calls = {"n": 0}

    def adj_always_empty(t, s, e, adjusted):
        calls["n"] += 1
        return pd.DataFrame()
    monkeypatch.setattr(fetch_mod, "fetch_market_snapshot",
                        lambda d, market="ALL": _snap(d, {
                            "ticker": tickers, "open": [3] * len(tickers),
                            "high": [3] * len(tickers), "low": [3] * len(tickers),
                            "close": [3] * len(tickers), "volume": [30] * len(tickers),
                            "value": [300] * len(tickers),
                        }))
    monkeypatch.setattr(fetch_mod, "_fetch_one", adj_always_empty)
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: None)

    fetch_mod.fetch_many_datewise(
        tickers, date(2026, 8, 4), date(2026, 8, 4), max_workers=1)

    assert calls["n"] == len(tickers)   # 본 시도만 — 재시도 0회
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_ohlcv_fetch_datewise.py -v -k "empty_adj"`
Expected: 3 FAIL — 앞 2건은 `calls["n"] == 2`에서 `assert 1 == 2`(재시도 없음), cap 테스트는 `_EMPTY_ADJ_RETRY_MAX` 미정의 AttributeError

- [ ] **Step 3: 구현** — `fetch.py` `fetch_many_datewise`의 adj 1차 실패 재시도 블록 뒤, `return` 직전에 추가

모듈 상수(파일 상단 `SNAPSHOT_COLUMNS` 근처):

```python
# 빈-adj run 내 재시도 상한 — 초과면 광역 장애로 보고 재시도 생략(#92 시도 상한 원칙)
_EMPTY_ADJ_RETRY_MAX = 20
```

`return successes, failures` 직전:

```python
    # 빈-adj 재시도 (#95 후속) — 빈 DF 는 예외가 아니라 위 재시도에 안 잡힌다.
    # raw 는 정상인데 adj 만 빈 종목은 일시 장애일 수 있어 run 안에서 1회 재요청.
    # 그래도 비면 그대로 둔다 — 적재 보류·경고 계정은 _run_upsert 가 담당.
    # 예외 시 failures 에도 기록(의도적 이중 계정 — failures 는 영속되지 않아 경고가 주 신호).
    empty_adj = [t for t, (r, a) in successes.items() if not r.empty and a.empty]
    if len(empty_adj) > _EMPTY_ADJ_RETRY_MAX:
        log.warning(
            f"empty-adj {len(empty_adj)}종목 > 상한 {_EMPTY_ADJ_RETRY_MAX} — "
            f"광역 장애 의심, run 내 재시도 생략(보류·경고는 _run_upsert 가 계정)")
    else:
        for ticker in empty_adj:
            raw_df = successes[ticker][0]
            try:
                retried = _adj_task(ticker)
                if not retried.empty:
                    successes[ticker] = (raw_df, retried)
            except Exception as e:
                failures.append((ticker, str(e)))
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_ohlcv_fetch_datewise.py -v`
Expected: 전부 PASS (기존 11건 + 신규 3건 = 14)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/ohlcv/fetch.py tests/test_ohlcv_fetch_datewise.py
git commit -m "feat(#95): 빈 adj 응답 run 내 1회 재시도 — 일시 장애 흡수"
```

---

### Task 2: _run_upsert — 빈-adj 종목 적재 보류 + adj_empty_fetch 경고

**Files:**
- Modify: `kr_pipeline/ohlcv/modes.py:225-233` (`_run_upsert` 루프)·`:246` 부근(warnings 조립)
- Modify: `kr_pipeline/ohlcv/transform.py` (#95 가드 주석 1문장 추가 — 코드 불변)
- Test: `tests/test_ohlcv_modes.py:486-533` (기존 통합 테스트를 새 의미로 재작성)

**Interfaces:**
- Consumes: Task 1 반영된 `fetch_many_datewise` (재시도 후에도 빈 adj면 `(raw, 빈 DF)` 유지)
- Produces: `_run_upsert` 시그니처·RunStats 계약 불변. 새 경고 형식: `adj_empty_fetch: N종목 적재 보류 [티커 최대 20개] — 재시도 후에도 adj 빈 응답, 기존 행 불변·다음 run 자연 보충`

- [ ] **Step 1: 기존 통합 테스트를 새 의미로 재작성** — `tests/test_ohlcv_modes.py`의 `test_run_upsert_empty_adj_does_not_block_other_tickers` 전체 교체

```python
def test_run_upsert_empty_adj_held_with_warning_others_proceed(monkeypatch, db):
    """adj 빈 응답 종목은 적재 통째 보류 + adj_empty_fetch 경고, 다른 종목은 정상 적재 (#95 설계 변경).

    구 설계(raw fallback 적재)는 upsert 의 ON CONFLICT 가 adj_* 를 무조건 교체해
    기존 올바른 adj 30일 창을 raw 로 덮어쓸 수 있었다(리뷰 major). 보류 설계는
    기존 행을 건드리지 않고 다음 run 의 창 재수집이 자연 보충한다.
    """
    from kr_pipeline.ohlcv import modes

    def _raw(close):
        return pd.DataFrame({
            "date": [date(2026, 7, 2)], "open": [close - 100], "high": [close + 100],
            "low": [close - 200], "close": [close], "volume": [1000], "value": [close * 1000],
        })

    adj_ok = pd.DataFrame({
        "date": [date(2026, 7, 2)], "open": [450.0], "high": [550.0],
        "low": [350.0], "close": [500.0], "volume": [2000.0],
    })
    # 빈-adj 종목을 dict 앞에 둬서, 격리 실패 시 뒤 종목 적재가 확실히 막히게 한다.
    monkeypatch.setattr(
        modes, "fetch_many_datewise",
        lambda tickers, s, e, max_workers: (
            {"EAJ": (_raw(7000), pd.DataFrame()), "OKJ": (_raw(1000), adj_ok)}, [],
        ),
    )
    monkeypatch.setattr(modes, "fetch_index", lambda code, s, e: pd.DataFrame())
    monkeypatch.setattr(modes, "_run_sanity_checks", lambda conn, mode: [])

    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO stocks (ticker, name, market) VALUES "
                "('EAJ', '빈수정주', 'KOSPI'), ('OKJ', '정상주', 'KOSPI') "
                "ON CONFLICT (ticker) DO NOTHING")
            db.commit()

        stats = modes._run_upsert(
            db, ["EAJ", "OKJ"], date(2026, 7, 1), date(2026, 7, 7), 2, modes.Mode.INCREMENTAL)

        with db.cursor() as cur:
            cur.execute(
                "SELECT ticker, close, adj_close FROM daily_prices "
                "WHERE ticker IN ('EAJ', 'OKJ') AND date='2026-07-02' ORDER BY ticker")
            rows = cur.fetchall()
        # 보류: EAJ 는 적재되지 않는다 (기존 행도 없으므로 0행) — OKJ 만 적재
        assert rows == [("OKJ", 1000, 500.0)], f"보류/적재 판정 오류: {rows}"
        joined = " ".join(stats.warnings)
        assert "adj_empty_fetch" in joined and "EAJ" in joined
        # 정상 종목은 경고 목록에 없어야 한다
        assert "OKJ" not in joined
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM daily_prices WHERE ticker IN ('EAJ','OKJ')")
            cur.execute("DELETE FROM stocks WHERE ticker IN ('EAJ','OKJ')")
        db.commit()
```

(리뷰 minor 지적 반영: try/finally 정리 — 파일 관례와 정렬)

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_ohlcv_modes.py -v -k "empty_adj"`
Expected: 1 FAIL — 현재 구현은 EAJ를 raw fallback으로 적재하므로 `rows == [("OKJ", ...)]`에서 실패

- [ ] **Step 3: 구현** — `modes.py` `_run_upsert` 루프 교체

```python
    rows_total = 0
    empties: list[str] = []
    adj_empties: list[str] = []
    for ticker, (raw, adj) in successes.items():
        if raw.empty:
            # 성공도 실패도 아닌 소멸 금지 — 계정 후 skip (P1-5 B)
            empties.append(ticker)
            continue
        if adj.empty:
            # #95 설계: 빈 adj(재시도 후에도)는 적재 통째 보류 — raw fallback 으로
            # 적재하면 upsert 의 ON CONFLICT 가 기존 올바른 adj 30일 창을 raw 로
            # 덮어쓴다(조용한 오염). 기존 행 불변, 다음 run 창 재수집이 자연 보충.
            adj_empties.append(ticker)
            continue
        merged = merge_raw_and_adjusted(raw, adj)
        rows = to_price_rows(ticker, merged)
        rows_total += upsert_daily_prices(conn, rows)
        conn.commit()
```

경고 조립부(`warnings = _empty_fetch_warning(...)` 다음 줄)에 추가:

```python
    if adj_empties:
        warnings.append(
            f"adj_empty_fetch: {len(adj_empties)}종목 적재 보류 {adj_empties[:20]} — "
            f"재시도 후에도 adj(Naver) 빈 응답, 기존 행 불변·다음 run 자연 보충"
        )
```

`transform.py`의 #95 가드 주석 끝에 1문장 추가(코드 불변):

```python
    # #95: adj 빈 응답 방어 — pykrx(Naver) 경로는 빈 응답을 컬럼 없는 빈 DF 로
    # 그대로 반환하며, 그 경우 아래 rename-select 가 KeyError 로 run 전체를
    # 중단시켰다. empty 면(컬럼 유무 무관) merge 를 건너뛰고 raw fallback 직행.
    # 단 production 파이프라인(_run_upsert)은 빈-adj 종목을 적재 보류로 먼저
    # 거르므로(#95 설계 변경) 이 fallback 은 방어층(defense-in-depth)이다.
```

- [ ] **Step 4: 통과 + 회귀 확인**

Run: `uv run pytest tests/test_ohlcv_modes.py tests/test_ohlcv_fetch_datewise.py tests/test_ohlcv_transform.py -v`
Expected: 전부 PASS (merge 단위 가드 테스트 2건은 불변 통과 — 이슈 완료 조건 ①)

- [ ] **Step 5: 커밋**

```bash
git add kr_pipeline/ohlcv/modes.py kr_pipeline/ohlcv/transform.py tests/test_ohlcv_modes.py
git commit -m "feat(#95): 빈 adj 종목 적재 보류 + adj_empty_fetch 경고 — 조용한 adj 덮어쓰기 차단"
```

---

### Task 3: 전체 검증 + PR #97 본문 갱신 + push

**Files:**
- Modify: PR #97 본문 (gh pr edit — 설계 변경 반영)

**Interfaces:**
- Consumes: Task 1·2 완료 상태
- Produces: PR #97 최신화(push), suite green

- [ ] **Step 1: 전체 suite**

Run: `pgrep -fl pytest; uv run pytest tests/`
Expected: **1198 passed, 1 skipped, 1 deselected, 실패 0** (baseline 1195 + 신규 3)

- [ ] **Step 2: push**

```bash
git push
```

- [ ] **Step 3: PR 본문 갱신** — `gh pr edit 97 --body-file <갱신 본문>`. 갱신 요지: "변경 요약"의 fallback 서술을 3층 설계(재시도[상한 20]→보류+경고→merge 가드는 방어층)로 교체하고, "후속 후보" 섹션을 "리뷰 major 반영 완료"로 대체. 완료 조건 ①②③ 충족 근거(단위 가드 불변·보류 통합 테스트·suite 수치) 명시. **트레이드오프 1문장 필수**: "Naver가 특정 종목을 지속적으로 빈 응답하면 그 종목 일봉은 계속 보류된다(매 run adj_empty_fetch 경고로 관측 가능) — 연속 보류 escalation은 범위 밖".

- [ ] **Step 4: 최종 확인**

Run: `gh pr view 97 --json commits -q '.commits | length'` 및 `git log origin/main..HEAD --oneline`
Expected: 커밋 3개(4a4cbef + 신규 2), PR diff에 `.loop/`·`.env` 없음

---

## Self-Review 결과

- 스펙 커버리지: 사용자 결정 3요소(보류/경고/재시도 1회) = Task 2/2/1. 리뷰 minor(try/finally)도 Task 2 테스트에 반영. 이슈 #95 완료 조건 ①②③ 각각 Task 2 Step 4·Step 1·Task 3 Step 1이 담보
- 플레이스홀더: 없음(전 단계 실코드)
- 타입 일관성: `_adj_task(t)->pd.DataFrame`(기존), `adj_empties: list[str]`, `_EMPTY_ADJ_RETRY_MAX: int`, 경고 접두사 `adj_empty_fetch` — Task 1 Produces와 Task 2 Consumes 정합
- 유의: Task 1 재시도는 `_adj_task` 재사용으로 0.15s 페이싱 자동 적용

## 독립 검토 반영 (1회 수행, 2026-08-06)

발견 4건 전부 반영: ① Task 1 Step 4 기대 테스트 수 오기(9→**11**+3=14) 정정 + 전체 baseline 산술은 정확 판정(1195+3=1198) ② **재시도 무상한 리스크** → `_EMPTY_ADJ_RETRY_MAX=20` 상한 추가(광역 장애 시 재시도 생략, 테스트 포함 — 유일하게 운영 시간에 영향 주는 변경이라는 검토 판단 수용) ③ 재시도 예외 시 failures+경고 이중 계정을 **의도로 명문화**(failures는 영속되지 않아 경고가 주 신호) ④ 영속-빈 adj 종목의 무기한 보류 트레이드오프를 PR 본문 갱신 요지에 필수 문장으로 추가. 그 외 검토가 실물 확증한 항목: 삽입 지점·테스트 헬퍼·Task 2 앵커 자구 일치·리뷰 major 기술 근거(ON CONFLICT)·기존 테스트 4건 무충돌·완료 조건 정합·순서 의존성 무결.
