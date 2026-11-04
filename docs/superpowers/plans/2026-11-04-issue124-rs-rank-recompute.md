# #124 RS 순위 표적 재계산(방법 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 저장된 과거 `rs_rating`(일봉·주봉)과 그에 종속된 `minervini_c8/minervini_pass` 를, 저장된 수정종가로부터 전 종목 강도 점수를 즉석 계산해 현재 수정주가 빈티지로 다시 매긴다(1차 대상 = #122 재적재 17종목/18사건이 영향을 준 구간, 사용자 결정에 따라 전 기간). 같은 17종목의 일봉 `rs_line_not_declining_7m` 미러 잔존 오류도 고친다.

**Architecture:** 새 모듈 `kr_pipeline/indicators/rs_rank_recompute.py` 가 (1) daily_prices/weekly_prices 의 adj_close 를 종목별로 읽어 기존 `compute_ibd_strength_factor` 로 날짜×종목 강도 점수 표를 만들고, (2) 날짜별로 기존 `assign_rs_rating_percentiles` 에 넣어 순위를 내며, (3) 저장값과 셀 단위로 비교해 **달라진 셀만** 백업·UPDATE 한다. Phase C(c8·pass)는 기존 `update_*_minervini_pass` 에 **셀 한정 필터**를 추가해 변경 셀만 재유도한다(thresholds 소비 로직 수정 → 의존성 맵 체크리스트 작성). 수동 스크립트 `scripts/issue124_rs_rank_recompute.py` 가 `--plan/--apply/--restore` 를 제공한다(#122 재적재 스크립트와 같은 틀). DB 컬럼 추가 없음, 스키마 변경 없음, 외부 접촉 0.

**Tech Stack:** Python 3 / psycopg / pandas, 기존 `kr_pipeline.indicators.compute.rs_rating`, `kr_pipeline.indicators.store`, kr_test 스키마 테스트(conftest 리셋).

**Spec:** 별도 spec 문서 없음. 근거 = GitHub 이슈 #124 본문(옵션 B 표적 재계산) + `docs/superpowers/specs/2026-11-03-issue122-adj-missing-readout.md` §7 "재계산하지 않은 것 … 이 범위는 #124" + 2026-11-04 대화 결정(방법 1: 저장 없이 즉석 계산, 컬럼 추가 안 함) + 2026-11-04 독립 리뷰 R1(차단 3·권고 6·메모 1 반영, 아래 "리뷰 반영" 참조).

## Global Constraints

- KRX·DART·Naver 접촉 0. 스크립트는 kr_pipeline import 전에 `KRX_ID`/`KRX_PW` 를 빈 문자열로 만든다(#122 스크립트와 동일 이유: pykrx 가 import 시 로그인).
- 운영 DB 쓰기(`--apply`, `--restore`)는 사용자 명시 승인 후에만, evening-chain 창(20:25~) 밖, `pgrep -f kr_pipeline` 0, bt-110 웹 스위치 OFF 에서 실행.
- **유니버스 = 그 날짜에 지표 행이 있는 종목**(`daily_indicators`/`weekly_indicators` 의 DISTINCT ticker 전체를 읽고, 날짜별 N 은 그 날짜에 행이 있는 종목 수). "현재 활성 종목"(`stocks.delisted_at IS NULL`)을 쓰면 안 된다 — 저장 순위의 마지막 전체 산출은 2026-07-11(실측 `pipeline_runs`)이고 그 뒤 25종목이 상폐됐지만 과거 지표 행은 남아 있어(예: 2023-12-28 에 상폐 24종목이 rs_rating 보유) N 이 ~1% 달라 전 종목 순위가 ±1 흔들린다(리뷰 R1-1).
- **패리티 전제**: 일봉 `--plan/--apply` 는 2026-11-04 20:25 체인 성공 후(최신 지표 날짜 ≥ 11-04), 주봉은 11-07(토) data_weekly 체인 성공 후. 11-03 저장 순위는 재적재(21:15) 이전 Phase B(20:37) 산출이라 2026-05 사건 3종목(003060·007460·009310, 창이 오늘까지 열려 있음) 때문에 반드시 불일치한다(R1-2).
- **패리티 대조군 = 야간 증분 창(최근 30일) 전체에서 변경 셀 0**(최신 1일이 아님). 실패 시 쓰기 없이 종료 2, 출력에 날짜별 `N_stored/N_recomputed`·불일치 셀 ≤10·그 날짜 Phase B 실행 시각(`pipeline_runs`)을 찍어 "전제 미충족"과 "계산 경로 불일치"를 구분한다.
- `kr_pipeline/common/thresholds.py` 는 수정하지 않는다. 그러나 `update_daily_indicators_minervini_pass`/`update_weekly_indicators_minervini_pass`(C8 소비처)에 셀 필터를 추가하므로 **`docs/superpowers/threshold-change-checklist.md` 의존성 맵(2축 판정)을 작성**한다(공식 불변·범위 인자만 추가 — 한 줄 판정이지만 트리거는 사실 기준). 새 코드는 `C8_RS_RATING_MIN` 을 직접 읽지 않는다.
- 저장된 과거 판정(classification·backtest 셀)은 불변(#122 §7 채택 결정 유지). 백테스트 RS(`bt_rs_*`) 불변(`common/price_source.py` 별도 경로).
- 쓰기 범위 = 대상 날짜의 **모든 종목 셀 중 값이 달라진 셀**(17종목만 쓰면 같은 날짜에 같은 순위가 둘 생겨 순위가 깨짐).
- 영향 구간 정의(일봉): 사건 종목의 행 기준 `[gap_date 행, gap_date 행 + 251행]` (강도 점수가 t−252 행까지 보므로 그 뒤는 네 시점이 모두 새 수정종가 → 값 불변; 그 앞은 네 시점이 같은 배수 → 불변). 주봉: `[gap 주 행, + 51행]`. 행이 모자라면 마지막 행까지(2026-05 사건 3건은 현재 120행 — 창이 매일 자람). 실측: 18사건 창의 합집합 = 거래일 1,934/2,549(76%), 병합 구간 4개 → "창 한정"과 "전 기간" 차이가 작으므로 **적용 범위는 사용자 결정**(Task 7 Step 2, R1-8).
- **bt-110 순서**: bt-110 은 on 시 `minervini_pass ∧ rs_line_not_declining_7m` 셀을 스냅샷·동결하고 대상 연도 2021·2024 가 영향 구간 안에 있다 → **bt-110 최초 on 이전에 #124 적용을 끝내고**, 적용 후 0단계 견적(`scripts/issue110_stage0_estimate.py`)을 재실행한다(R1-9).
- 브랜치 먼저(`git checkout -b issue124-rs-rank-recompute origin/main` 기반 worktree), `git add` 명시 경로만, 커밋에 Co-Authored-By 금지, PR 본문에 "Closes #N" 문구(부정문 포함) 금지, PR 본문 끝 "🤖 Generated with [Claude Code](https://claude.com/claude-code)".
- 테스트: `uv run pytest tests/` 기대 실패 0 · 1 deselected · 1 skipped. 판정 전 `pgrep -f pytest` 0 확인.

## Review Focus

1. **상장 후 252행 미만 종목·상폐됐지만 과거 행이 있는 종목** — 전자는 강도 점수 NaN → 순위 NULL(저장도 NULL → 변경 없음), 후자는 그 날짜 N 에 포함돼야 저장값과 같은 순위가 나온다. 거래정지 행은 `adj_close` 가 NULL 이 아니라 carry 값(실측 NULL 0/5,471,347)이므로 아무 행도 거르지 않는다(`adj_close > 0` 필터 금지). (Task 1 `test_rank_table_equals_phase_b_daily` 에 두 종목 포함)
2. **패리티 가드** — 최근 30일 창에서 즉석 계산 순위와 저장 순위가 하나라도 다르면 쓰기 없이 종료 2. (Task 3 `test_plan_aborts_when_parity_window_fails`)
3. **gap_date 뒤 행이 252개 미만(2026-05 사건 3건)** — 구간 끝 = 마지막 행. (Task 2 `test_window_truncates_to_last_row`)
4. **같은 종목 사건 2건(228760 2017-11-09·2018-09-14, 사이 209행) 구간 겹침** — 날짜 집합은 합집합, Phase C 는 셀 한정이라 구간 병합은 보고용. (Task 2 `test_windows_merge_overlapping_dates`)
5. **재실행 멱등성·복원 정확성** — `--apply` 직후 `--plan` 은 변경 셀 0, `--restore` 후 rs_rating·c8·pass 가 백업의 old 값과 정확히 같다. (Task 3 `test_apply_then_diff_is_empty`, `test_restore_returns_exact_old_values`)
6. **테스트 공허 통과 방지** — Phase A 직접 호출 테스트는 `index_daily`(1001) 시드가 없으면 0행을 쓰고 캐시가 비어 "모든 셀 동일"이 빈 집합으로 통과한다. 모든 동치 테스트는 저장 행 수 > 0 을 단언하고 시작·종료에 `modes._phase_b_cache.clear()`. (Task 1)

---

### Task 1: 전 종목 강도 점수 표 + 날짜별 순위 (기존 Phase B 와 동치)

**Files:**
- Create: `kr_pipeline/indicators/rs_rank_recompute.py`
- Test: `tests/test_rs_rank_recompute_124.py`

**Interfaces:**
- Consumes: `kr_pipeline.indicators.compute.rs_rating.compute_ibd_strength_factor(adj_close, q1, q2, q3, q4)`, `assign_rs_rating_percentiles(returns: pd.Series) -> pd.Series`(이미 `round().astype(int)` 정수화), `kr_pipeline.indicators.modes.Target`.
- Produces:
  - `SF_Q = {Target.DAILY: (63, 126, 189, 252), Target.WEEKLY: (13, 26, 39, 52)}`
  - `universe_tickers(conn, target) -> list[str]` — `SELECT DISTINCT ticker FROM daily_indicators`(WEEKLY: `weekly_indicators`). 활성 여부 무관.
  - `strength_table(conn, target, *, tickers: list[str], end: date) -> pd.DataFrame` — index = 날짜(오름차순), columns = tickers, 값 = 강도 점수(float, NaN 허용). **종목별 SELECT**(`SELECT date, adj_close FROM daily_prices WHERE ticker=%s AND date<=%s ORDER BY date`, 행 필터 없음)로 스트리밍 → 종목별 SF → `concat(axis=1)`. 종목이 그 날짜에 행이 없으면 NaN(= Phase B 캐시에 그 날짜가 없는 것과 같음, N 제외).
  - `rank_table(sf: pd.DataFrame, dates: list[date]) -> pd.DataFrame` — 날짜마다 `assign_rs_rating_percentiles(sf.loc[d])` → `Int64`(NaN → `pd.NA`). 추가 반올림·절삭 없음(Phase B 의 `int(rating)` 은 무연산).

- [ ] **Step 1: 동치 테스트 작성** — kr_test 에 `index_daily`(1001) + 종목 4개 시드: A·B 300행, C 150행(신규상장 → 마지막 날 SF NaN), D 300행이되 `stocks.delisted_at` 을 채움(상폐·과거 행 보유). `modes._phase_b_cache.clear()` → `modes._process_ticker_daily` 4종목 → `modes._run_phase_b_daily(db, d0, d1)` → 저장 `rs_rating` 행 수 > 0 단언 → `rank_table(strength_table(db, Target.DAILY, tickers=universe_tickers(db, Target.DAILY), end=d1), dates)` 와 모든 (종목, 날짜) 비교(NULL↔NA 포함) → 끝에 캐시 clear.

```python
def test_rank_table_equals_phase_b_daily(db):
    ...
    assert len(stored_rows) > 0
    for (t, d, stored) in stored_rows:
        v = got.at[d, t]
        assert (pd.isna(v) and stored is None) or (not pd.isna(v) and int(v) == stored)
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_rs_rank_recompute_124.py::test_rank_table_equals_phase_b_daily -v` → FAIL (`ImportError`).
- [ ] **Step 3: 구현** — 위 시그니처대로.
- [ ] **Step 4: 통과 확인** — 같은 명령 → PASS.
- [ ] **Step 5: 주봉 동치 테스트** — `test_rank_table_equals_phase_b_weekly`(`weekly_index` 1001 + weekly_prices 60행 시드, `_process_ticker_weekly` + `_run_phase_b_weekly`, 같은 격리). 실패 → 통과.
- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/indicators/rs_rank_recompute.py tests/test_rs_rank_recompute_124.py
git commit -m "feat(#124): 전 종목 강도 점수 표·날짜별 RS 순위 즉석 계산(기존 Phase B 동치, 유니버스=지표 행 보유 종목, 일봉·주봉)"
```

### Task 2: 영향 구간(윈도) 산출

**Files:**
- Modify: `kr_pipeline/indicators/rs_rank_recompute.py`
- Test: `tests/test_rs_rank_recompute_124.py`

**Interfaces:**
- Consumes: `kr_pipeline.ohlcv.adj_reload_events.FROZEN_TARGETS: frozenset[(ticker, 'YYYY-MM-DD', coef)]`.
- Produces:
  - `ROWS_AFTER = {Target.DAILY: 252, Target.WEEKLY: 52}`
  - `@dataclass(frozen=True) class Window: ticker: str; start: date; end: date` (양끝 포함)
  - `event_windows(conn, target, events: list[tuple[str, date]]) -> list[Window]` — 종목별 `SELECT date FROM <prices> WHERE ticker=%s AND date >= %s ORDER BY date LIMIT rows_after` 의 첫·끝 날짜(주봉: `week_end_date >= gap`). 행이 없으면 생략.
  - `affected_dates(conn, target, windows) -> list[date]` — 윈도별 날짜를 실제 지표 날짜(`SELECT DISTINCT date FROM <ind> WHERE date BETWEEN …`)로 펼쳐 합집합·정렬.
  - `merged_ranges(dates: list[date], trading_dates: list[date]) -> list[tuple[date, date]]` — 거래일 인덱스 연속 구간 병합(보고용).
  - `all_dates(conn, target) -> list[date]` — 전 기간 모드용(`--full`).

- [ ] **Step 1: 테스트** — `test_window_is_252_rows_from_gap`(300행 시드, gap=100번째 행 → end = 351번째 행), `test_window_truncates_to_last_row`(gap 뒤 120행뿐 → end = 마지막 행), `test_windows_merge_overlapping_dates`(같은 종목 두 gap 이 209행 간격 → affected_dates 길이 = 252+209, merged_ranges 1개), `test_weekly_window_uses_week_end`(gap 이 수요일 → start = 그 주 week_end_date).
- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_rs_rank_recompute_124.py -k window -v` → FAIL.
- [ ] **Step 3: 구현. Step 4: 통과 확인.**
- [ ] **Step 5: Commit** — `-m "feat(#124): 사건별 영향 구간(일봉 252행·주봉 52행)·날짜 합집합·연속 구간 병합·전 기간 모드"`.

### Task 3: Phase C 셀 한정 필터 + 비교·백업·적용·복원

**Files:**
- Modify: `kr_pipeline/indicators/store.py` (`update_daily_indicators_minervini_pass` L94-121, `update_weekly_indicators_minervini_pass` L186-210)
- Modify: `kr_pipeline/indicators/rs_rank_recompute.py`
- Create: `docs/superpowers/threshold-change-checklist.md` 양식의 의존성 맵 → `docs/superpowers/specs/2026-11-04-issue124-rs-rank-recompute-readout.md` §0 에 기재(C8_RS_RATING_MIN 소비처에 범위 인자 추가, 값·공식 불변, 다른 소비처 영향 없음)
- Test: `tests/test_rs_rank_recompute_124.py`

**Interfaces:**
- Produces(store): `update_daily_indicators_minervini_pass(conn, start_date, end_date, *, cells: list[tuple[str, date]] | None = None) -> int` — `cells` 가 주어지면 `AND (d.ticker, d.date) IN (SELECT ticker, date FROM <TEMP VALUES>)` 로 한정. 기본 `None` = 기존 동작·호출처 무변경. 주봉 동형(`(ticker, week_end_date)`).
  - 주의: `update_daily_indicators_rs_rating` 은 `ON COMMIT DROP` TEMP TABLE 을 쓰므로(`store.py:73-79`) **한 트랜잭션에 한 번만** 호출한다(target 당 셀 전체를 한 번에).
- Produces(module):
  - `diff_cells(conn, target, ranks: pd.DataFrame) -> list[dict]` — `{ticker, date, old, new, old_c8, old_pass}` 중 `old != new` 만. 저장 행이 없는 (ticker,date) 는 건너뜀. 날짜 구간을 나눠 `SELECT ticker, date, rs_rating, minervini_c8, minervini_pass FROM <ind> WHERE date = ANY(%s)` 로 읽는다(메모리).
  - `parity_window(conn, target, sf, *, days: int = 30) -> dict` — 최근 30일 지표 날짜에서 `{"dates": n, "mismatch": n, "sample": [...≤10], "n_by_date": {date: (N_stored, N_recomputed)}, "last_phase_b_at": pipeline_runs 최신 finished_at}`.
  - `plan(conn, target, dates) -> dict` — `{parity, dates: n, cells: n, by_target_ticker: n, by_other: n, delta_hist: {"1","2",">=3","null_flip"}, pass_flip: n(new c8 기준 pass 가 바뀔 셀), ranges}`. 읽기 전용.
  - `apply(conn, target, cells) -> dict` — 한 트랜잭션: `update_*_rs_rating(conn, [(t,d,new)])` → `update_*_minervini_pass(conn, min_d, max_d, cells=keys)` → commit; 예외 시 rollback 후 재raise. 반환 `{cells, pass_rows}`.
  - `restore(conn, target, cells) -> dict` — 한 트랜잭션: rs_rating ← `old`, 그리고 **c8/pass 를 백업의 `old_c8/old_pass` 로 직접 UPDATE**(재유도 아님 → 정확 복원, R1-6). 주의: `restore` 는 Phase C 를 부르지 않는다.
- 백업 파일 형식(스크립트가 씀): `{"generated_at", "target", "mode": "windows|full", "events", "windows", "ranges", "cells": [{ticker,date,old,new,old_c8,old_pass}]}` — 변경 셀만.

- [ ] **Step 1: store 필터 테스트** — `test_minervini_pass_cells_filter`: 두 종목 두 날짜 중 `cells=[(A,d1)]` 만 주면 그 행만 `updated_at` 변경·다른 행 불변. 기본 호출은 기존 테스트(`tests/test_indicators_store.py` 류)로 회귀 확인.
- [ ] **Step 2: 실패 확인 → 구현 → 통과.** 의존성 맵 §0 작성.
- [ ] **Step 3: 모듈 테스트** — Task 1 시드 재사용 후 종목 A 의 gap 이전 adj_close 를 ×2 로 바꾸고 Phase B 를 다시 돌리지 않은 상태(= 빈티지 드리프트 모사):
  - `test_diff_cells_only_changed`: 바뀐 셀만, old/new/old_c8/old_pass 가 저장값·재계산값.
  - `test_plan_aborts_when_parity_window_fails`: 최근 30일 창 안의 저장 rs_rating 하나를 +1 → `parity_window()["mismatch"] >= 1`.
  - `test_apply_then_diff_is_empty`: `apply` 후 `diff_cells` 빈 리스트 + 변경 셀에서 `minervini_c8 = (rs_rating >= C8_RS_RATING_MIN)` 성립(thresholds 는 테스트가 **읽기만**) + 변경 셀 외 행의 `updated_at` 불변.
  - `test_restore_returns_exact_old_values`: `restore` 후 rs_rating·c8·pass == 백업 old 값.
- [ ] **Step 4: 실패 확인 → 구현 → 통과.**
- [ ] **Step 5: Commit** — `git add kr_pipeline/indicators/store.py kr_pipeline/indicators/rs_rank_recompute.py tests/test_rs_rank_recompute_124.py docs/superpowers/specs/2026-11-04-issue124-rs-rank-recompute-readout.md`, `-m "feat(#124): Phase C 셀 한정 필터(의존성 맵 §0) + 변경 셀 비교·30일 패리티 가드·적용/정확 복원"`.

### Task 4: 일봉 rs 게이트 미러를 종목 한정으로 재실행

**Files:**
- Modify: `kr_pipeline/indicators/store.py:212-235` (`update_daily_rs_gate_from_weekly`)
- Test: `tests/test_rs_rank_recompute_124.py`

**Interfaces:**
- Produces: `update_daily_rs_gate_from_weekly(conn, start_date, end_date, *, tickers: list[str] | None = None) -> int` — `tickers` 가 주어지면 `AND d.ticker = ANY(%s)`. 기본 `None` = 기존 동작(호출처 무변경).
- 근거(실측 2026-11-04, 운영 DB 읽기): `upsert_daily_indicators_phase_a` 가 이 컬럼을 UPDATE 에서 제외(`store.py:45-48`)하고 `recompute_ticker_daily`·`adj_reload_events.recompute_ticker` 는 Phase D 를 부르지 않으므로, 재적재 17종목은 주봉 게이트는 전 기간 갱신됐지만 일봉 미러는 야간 30일 창만 갱신돼 사건 직후 구간이 옛 값(078860 84행 2023-12-28~2024-05-02, 009310 107행, 221800 82행; 대조 종목 005930·000660·035720·068270 은 0행). 범위 = **17종목 전 기간**(주봉 게이트가 바뀐 종목은 이들뿐). 같은 계열 결함이 평일 drift 재적재 종목(`chains.py` → `drift.reload_ticker`)에도 잠재 → readout 에 "17종목 한정 수리, drift 재적재 종목은 별도 관찰" 명시(R1-7).

- [ ] **Step 1: 테스트** — `test_rs_gate_mirror_ticker_filter`: 종목 A·B 의 weekly_indicators 값을 바꾼 뒤 `tickers=["A"]` → A 의 daily 미러만 변경, B 불변.
- [ ] **Step 2: 실패 확인(`TypeError`) → 구현 → 통과.** `tests/test_indicators_modes.py::test_recompute_ticker_daily_preserves_rs_gate_history` PASS 확인.
- [ ] **Step 3: Commit** — `-m "feat(#124): 일봉 rs 게이트 미러에 종목 필터 추가(기본 동작 불변)"`.

### Task 5: 수동 스크립트 `--plan / --apply / --restore`

**Files:**
- Create: `scripts/issue124_rs_rank_recompute.py`
- Test: `tests/test_rs_rank_recompute_124.py` (`events_from_frozen()` 만)

**Interfaces:**
- CLI:
  - `--plan [--target daily|weekly|both] [--full]` : 읽기 전용(`conn.read_only = True`). 패리티 창 가드 → (창 모드) 윈도·날짜 수·변경 셀(17종목/그 외)·|Δ| 분포·pass_flip / (`--full`) 전 기간 같은 숫자 → 미러 불일치 행 수(17종목). 두 모드 숫자를 함께 보고하려면 두 번 호출. 종료 0 / 패리티 실패 2.
  - `--apply --target … [--full]` : plan 과 같은 계산 → 백업 JSON `data/verification/issue124_rs_rank_backup_<stamp>.json` → `apply` → 미러 `update_daily_rs_gate_from_weekly(conn, min_date, max_date, tickers=17종목)`(daily 만) → 결과 JSON `data/verification/issue124_rs_rank_<stamp>.json` → 같은 프로세스에서 재비교해 변경 셀 0 확인. 종료 0 / 오류 1 / 패리티 실패 2(쓰기 없음).
  - `--restore <backup.json>` : 백업 셀 정확 복원(rs·c8·pass) + 미러 재실행(미러 옛 값은 복원하지 않음 — readout 에 명시).
  - `events_from_frozen() -> list[tuple[str, date]]` : `FROZEN_TARGETS` → (ticker, gap_date) 18건.
- 머리말: `load_dotenv()` 직후 `os.environ["KRX_ID"] = ""; os.environ["KRX_PW"] = ""` 를 kr_pipeline import 보다 먼저. `run_tracking` 미사용(#122 동형, `/runner` 에 흔적 없음 → 결과 JSON 경로를 #124 코멘트에 남김).

- [ ] **Step 1: 테스트** `test_events_from_frozen_has_18_events_17_tickers` → 실패 → 구현(`cmd_plan/cmd_apply/cmd_restore`, #122 스크립트 구조 복제) → 통과.
- [ ] **Step 2: kr_test 스모크** — `DATABASE_URL=$TEST_DATABASE_URL uv run python scripts/issue124_rs_rank_recompute.py --plan` 이 오류 없이 종료(0 또는 2).
- [ ] **Step 3: Commit** — `-m "feat(#124): 수동 러너 --plan/--apply/--restore (--full, KRX 접촉 0, 백업·결과 JSON, 종료 코드)"`.

### Task 6: 용어집·문서·PR

**Files:**
- Modify: `docs/GLOSSARY.md` §5 끝에 추가: **빈티지 드리프트**(저장 지표가 계산 당시 수정주가 기준으로 굳어 현재 수정주가와 어긋난 상태, 예: 199800 2022-06-15 저장 15 vs 재계산 38), **횡단면 지표**(한 날짜의 전 종목을 함께 봐야 나오는 값 — RS 등급·minervini_c8/pass; 종목 단위 재계산 불가), **강도 점수(StrengthFactor)**(2·C/C[-63] + C/C[-126] + C/C[-189] + C/C[-252], 주봉 13/26/39/52). 각 항목 끝 `출처:`.
- Modify: `docs/superpowers/specs/2026-11-04-issue124-rs-rank-recompute-readout.md` — §0 의존성 맵(Task 3) §1 배경(#122 §7 인계, 미러 실측) §2 방법 1·리뷰 R1 반영 §3 `--plan` 실측(창/전 기간) §4 적용 기록·첫 평일 체인 차분(적용 후 채움) §5 주의: 라이브 테이블을 읽는 백테스트(`backtest/minervini_forward.py`, `portfolio.py`, recall_*)는 적용 후 #111·#115 과거 결과를 구 빈티지로 재현할 수 없음(재실행 금지 메모와 함께); `bt_rs_*` 불변.

- [ ] **Step 1: 용어집·readout §0~§2 작성 후 commit** — `-m "docs(#124): 용어집(빈티지 드리프트·횡단면·강도 점수) + 판독 문서 §0~§2"`.
- [ ] **Step 2: 전체 suite** — `pgrep -f pytest` 0 → `uv run pytest tests/ -q` → 실패 0 · 1 deselected · 1 skipped.
- [ ] **Step 3: PR 생성** — 제목 `#124 RS 순위 표적 재계산 도구(방법 1) + Phase C 셀 필터 + 일봉 rs 게이트 미러 종목 필터`, 본문: 목적·변경 3줄·운영 절차·"Closes" 금지·꼬리말. 독립 리뷰 1회 → 반영 → 사용자 지시 후 머지.

### Task 7: 운영 적용(사용자 승인 게이트 2회)

- [ ] **Step 0: 전제 확인** — 일봉: 11-04 20:25 체인 성공(최신 지표 날짜 ≥ 11-04). 주봉: 11-07 data_weekly 성공. bt-110 스위치 아직 OFF·`backfill_control` 0행.
- [ ] **Step 1: 운영 `--plan --target both` 와 `--plan --target both --full`(읽기 전용, 승인 불필요)** — 패리티(30일 창 0), 창 모드/전 기간 모드 각각의 날짜 수·변경 셀(17종목/그 외)·|Δ| 분포·pass_flip, 미러 불일치 행 보고.
- [ ] **Step 2: (확인 필요) 적용 범위(창 한정 vs 전 기간)와 적용 승인** — 사용자 결정. 추천은 숫자를 본 뒤 제시(창 합집합이 이미 76% 이므로 전 기간 1회가 쓰기 총량·설명 모두 단순할 가능성 큼).
- [ ] **Step 3: `--apply`** — 체인 창 밖·`pgrep -f kr_pipeline` 0·bt-110 OFF 확인 후 실행. 결과 JSON·백업 경로 보고. 직후 `--plan` 재실행으로 변경 셀 0·미러 불일치 0 확인.
- [ ] **Step 4: 다음 평일 체인 1회 관측** — 최신 날짜 셀이 바뀌었으면 LLM 체인이 반응한다(`llm_runner/load.py` pass=FALSE 강등, `delta.py` pass=TRUE 후보, `recent_transition.py` 63일 전환 수). 강등·후보 차분을 readout §4 에 1회 기록.
- [ ] **Step 5: readout §3·§4·이슈 #124 코멘트(결과 JSON 경로)·메모리 갱신·0단계 견적 재실행(`scripts/issue110_stage0_estimate.py`) 후 bt-110 on 은 사용자 몫.**

## 리뷰 반영(2026-11-04 R1)

| # | 등급 | 지적 | 반영 |
|---|---|---|---|
| 1 | 차단 | 유니버스를 현재 활성 종목으로 잡으면 저장 빈티지(상폐 25종목 포함)와 N 이 달라 전 종목 ±1 | 유니버스 = 지표 행 보유 종목, 상폐 종목 동치 테스트 |
| 2 | 차단 | 최신 날짜 패리티는 11-04 체인(주봉 11-07) 뒤에만 성립 | 전제 명시, 30일 창 대조군, 실패 출력에 N·실행 시각 |
| 3 | 차단 | Phase C 날짜 구간 재실행 = 4.23M행(77%) 재기록, NULL pass 3,525행 전환 | Phase C 셀 한정 필터 + 의존성 맵 §0 |
| 4 | 권고 | 050090 은 850행(잘리지 않음), adj_close NULL 은 운영에 0 | Review Focus 1·3 교체, 행 필터 금지 |
| 5 | 권고 | 동치 테스트가 index_daily 미시드·캐시 누수로 공허 통과 가능 | 시드·clear·행 수 > 0 단언 |
| 6 | 권고 | c8/pass 재유도는 정확 복원이 아님 | 백업에 old_c8/old_pass, restore 직접 UPDATE |
| 7 | 권고 | 미러 범위 17종목 전 기간 적정, drift 재적재 종목 잠재 | readout 명시 |
| 8 | 권고 | 창 합집합 76% → 전 기간 1회를 승인 항목으로 | `--full`, Task 7 Step 2 |
| 9 | 권고 | bt-110 최초 on 전에 #124 선행 | Global Constraints |
| 10 | 메모 | LLM 체인 반응·백테스트 재현성·메모리·run_tracking | Task 7 Step 4, readout §5, 종목별 스트리밍 |
