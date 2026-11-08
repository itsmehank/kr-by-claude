# #184 앵커 C3→C3′(B) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `find_anchor` 의 C3(주간 거래량 ≥ 1.4×50주 평균)를 C3′(B)(앵커 후보 주 안의 **상승 마감일** 중 ≥1일 일봉 거래량 ≥ 1.4×avg_volume_50d)로 바꾸고, 소비처 4곳·#207 표지 창·프롬프트 §6.1·상수 태그를 같은 PR 로 정합시킨다.

**Architecture:** 순수 함수 `find_anchor(weekly, daily)` 가 일봉 지표 시계열(저장 열 `avg_volume_50d` 그대로)을 **필수** 인자로 받는다. 일봉 조달은 `payload_builder._fetch_daily_anchor_series` 하나이고 분류·보유 평가·백테스트·재생 스크립트가 공유한다. 표지(`volume_regime_flag`)는 주간 51주 창을 버리고 앵커 C3′ 일간 창을 쓰며, 새 열 `volume_regime_flag_ver`(항상 2)로 구 정의 행(이관 SQL 로 1)과 구분한다.

**Tech Stack:** Python 3 (psycopg, 리스트 산술), PostgreSQL(schema.sql 수동 적용), pytest(`uv run pytest`), 프롬프트 Markdown + `prompts/VERSIONS.md`.

**Spec:** `docs/superpowers/specs/2026-11-07-issue184-anchor-c3prime-design.md` (승인 2026-11-08, 커밋 4a3038b). 전문가 회신 2026-11-07·11-08 은 #184 코멘트(issuecomment-6717131373).

## Global Constraints

- 브랜치 `issue184-c3-daily`(이미 체크아웃). 커밋 전 `git branch --show-current` 확인, `git add` 는 **명시 경로만**(`-A` 금지). 커밋 메시지에 Claude co-author trailer 금지.
- suite 판정 전 `pgrep -f pytest` 로 동시 실행 없음 확인. 기준: 실패 0 · 1 deselected · 1 skipped.
- `schema.sql` 변경은 자동 반영 없음 — kr_test 는 conftest 가 세션 시작 시 재적용, **운영 kr_pipeline 은 배포 단계에서 사용자가 psql 적용**(Task 8).
- KRX 실 접촉 0 · 토스 호출 0 · DB 는 테스트 픽스처(kr_test)와 읽기 전용 스크립트만.
- `find_anchor` 의 `daily` 인자에 **기본값을 두지 않는다**(spec 실패 조건: 주간 규칙으로의 조용한 폴백 금지). `BREAKOUT_VOL_FLOOR=1.4`·`min_periods=40`·`ANCHOR_MIN_HISTORY_WEEKS=50` 값 불변.
- 저장된 과거 표지·앵커 echo 는 소급 수정하지 않는다(3-4). 이관 SQL 은 `volume_regime_flag_ver` 만 채운다.
- 프롬프트 변경 커밋에는 `prompts/VERSIONS.md` 행을 같은 커밋에 추가(tests/test_prompt_versions.py). 프롬프트 §6.1 문안은 spec D5 **그대로**(수정 금지).
- 일봉 행 규약(전 소비처 공통): `{"date": "YYYY-MM-DD", "close": float, "volume": float|None, "avg_volume_50d": float|None}` — `{src.indicators}` 의 `date, adj_close, volume, avg_volume_50d`, `date ≤ as_of`, 오름차순, LIMIT 없음. halt 일은 `volume`·`avg_volume_50d` NULL, `adj_close` 는 직전 종가 carry(NOT NULL).

## Review Focus

1. 앵커 후보 주의 일봉 행이 전부 halt(`volume` NULL)이거나 일봉이 아예 비어 있으면 C3′ 미충족으로 **다음 후보로 계속 탐색**하고(전부 없으면 `no_transition`), 예외를 내지 않는다 — Task 2 테스트 (c)·(h).
2. `week_end` 가 금요일이 아닌 주(목요일 휴장 등)에서도 ISO 주 소속으로 일봉을 찾는다 — Task 2 테스트 (e).
3. 보유 평가 러너의 `decline_metrics(*fetch_series(...), anchor)` 가 3-튜플 반환으로 깨지지 않는다 — Task 3 에서 호출을 분해하고 decline 발화 경로 테스트가 실제 `fetch_series` 를 탄다.
4. `held_window_flag` 에 앵커 주의 일봉 날짜가 없을 때(방어) 앵커 주 자체를 창 시작으로 쓰고 None 이 아닌 값을 낸다 — Task 4 테스트.
5. 이관 SQL 재실행이 writer 가 쓴 `ver=2` 행을 1 로 덮지 않는다(멱등, `IS NULL` 조건) — Task 5 테스트.

---

### Task 1: 상수 개명·주석 정정·프롬프트·VERSIONS·export (동작 변화 0)

**Files:**
- Modify: `kr_pipeline/common/thresholds.py:80-95` (BREAKOUT_VOL_FLOOR·VOLUME_AVG_WINDOW_DAYS docstring), `:487-489` (상수 개명·재태그)
- Modify: `kr_pipeline/llm_runner/compute/climax_topping.py:9,38,73` · `kr_pipeline/common/data_regimes.py:27,65` · `kr_pipeline/common/regime_windows.py:31,106` · `scripts/issue184_anchor_shift_report.py:27,74` (import 이름만)
- Modify: `prompts/analyze_chart_v3.md:1-5`(변경 선언 주석 추가) `:46` `:408` `:423`
- Modify: `prompts/VERSIONS.md` (`### analyze_chart_v3.md` 절 끝에 행 1개)
- Modify: `tests/test_prompt_threshold_drift.py:41`, `tests/test_volume_regime_bars.py:41,43`, `tests/test_regime_windows.py:83`
- Regenerate: `web/src/data/thresholds.generated.ts` (`uv run python scripts/export_thresholds.py`)

**Interfaces:**
- Produces: `thresholds.ANCHOR_MIN_HISTORY_WEEKS: Final[int] = 50` (구 `CLIMAX_ANCHOR_VOL_AVG_WEEKS` 삭제, 별칭 없음).

- [ ] **Step 1: 상수 개명 + docstring 3건**

`thresholds.py:487` 를 다음으로 교체(값 불변):
```python
ANCHOR_MIN_HISTORY_WEEKS: Final[int] = 50
"""[design-judgment] 앵커 탐색 최소 주봉 이력(주). 이력 ≤ 이 값 → left_censored, 후보 주 인덱스 하한 i ≥ 이 값(climax_topping.find_anchor).
책 근거 없음(#184 회신 2026-11-07 Q-2: 구 'CLIMAX_ANCHOR_VOL_AVG_WEEKS' 의 "prompt §6.1 '50-WEEK average' 문언" 근거는 층위 오귀속이라 삭제).
산술 하한은 45주(C1 4주 + 40주 SMA + C2 기울기 4주) — 45주 재유도는 별건(사전등록 후 threshold-change-checklist). #207 표지 창 길이는 이 상수에서 유도하지 않는다."""
```
`BREAKOUT_VOL_FLOOR` docstring(:81-83) 의 "책: O'Neil HMMS Ch.2 p.117 — '40% to 50% above normal'. 하한 = 40% (=1.4×)." 를 "책: 1.4(=+40%) 는 O'Neil HMMS Ch.2 p.117 — '40% to 50% above normal'; **50거래일 창은 HMMS Ch.15 p.349**(IBD Volume Percent Change, 최근 50거래일 평균) + TLSMW Ch.10 p.226. (#184 회신 11-07 Q-1b: 출처 분리.) 소비처 2곳: entry_params_calc(돌파일) · climax_topping.find_anchor C3′(앵커 주 상승 마감일, 2026-11)." 로 교체.
`VOLUME_AVG_WINDOW_DAYS` docstring(:93) 의 "책: O'Neil HMMS p.117 '50-day average volume', TLOND p.134 (breakout 비교 기준 = 50일 평균)." 를 "책: 50거래일 창 = O'Neil HMMS Ch.15 p.349(IBD Volume Percent Change: 최근 50거래일 평균), TLSMW Ch.10 p.226('50-day average'); TLOND p.134 는 돌파 비교 기준이 '평균 대비, 선호 +50%' 라는 출처(창 길이 미명시). (#184 회신 11-08 Q-4-3: p.117 은 일수를 말하지 않음 — 출처 정정.)" 로 교체.

- [ ] **Step 2: import 이름 교체 5파일**

`climax_topping.py`(:9 docstring 문구 `CLIMAX_ANCHOR_VOL_AVG_WEEKS(50)` → `ANCHOR_MIN_HISTORY_WEEKS(50)`, :38 import, :73 `W = ANCHOR_MIN_HISTORY_WEEKS`), `data_regimes.py`(:27 import, :65 `VOLUME_WINDOW_WEEKLY_WEEKS = ANCHOR_MIN_HISTORY_WEEKS + 1` — 삭제는 Task 4), `regime_windows.py`(:31, :106), `scripts/issue184_anchor_shift_report.py`(:27, :74), 테스트 3곳(`test_prompt_threshold_drift.py:41` 문자열, `test_volume_regime_bars.py:41,43`, `test_regime_windows.py:83`).

- [ ] **Step 3: 프롬프트 3곳 + 변경 선언 + VERSIONS 행**

`analyze_chart_v3.md:46` `- CLIMAX_ANCHOR_VOL_AVG_WEEKS = 50` → `- ANCHOR_MIN_HISTORY_WEEKS = 50`. `:423` `CLIMAX_ANCHOR_VOL_AVG_WEEKS(50)주` → `ANCHOR_MIN_HISTORY_WEEKS(50)주`. `:408` 의
```
breakout week on volume ≥ BREAKOUT_VOL_FLOOR of the 50-week average with the close above
the 30/40-week lines — all in the SAME week;
```
를 다음으로 교체(spec D5 원문, 줄바꿈만 자유):
```
breakout week in which at least one up-close day (close > prior close) traded volume ≥
BREAKOUT_VOL_FLOOR × its 50-day average volume (`avg_volume_50d`), with the close above
the 30/40-week lines — all in the SAME week;
```
파일 상단 11-05 변경 선언 주석 바로 아래에 같은 형식으로 1블록 추가:
```
<!-- 변경 선언(governance 4-6) 2026-11-08: §6.1 anchor 정의의 C3 "주간 거래량 ≥ BREAKOUT_VOL_FLOOR × 50-week average" → C3′
     "앵커 주 안의 상승 마감일(close > prior close) 중 ≥1일 일봉 거래량 ≥ BREAKOUT_VOL_FLOOR × avg_volume_50d"
     (HMMS Ch.2 p.117·p.349, TLSMW Ch.5 p.70 — 전문가 판정 #184 [Q-1](B)·[Q-4-1] 승인). 상수 CLIMAX_ANCHOR_VOL_AVG_WEEKS →
     ANCHOR_MIN_HISTORY_WEEKS(값 50 불변, 역할 = 최소 이력). 분류 결과 영향: anchor_week 가 더 최근으로 이동(배포 전 보고 43.4%).
     기록 = docs/superpowers/specs/2026-11-07-issue184-anchor-c3prime-design.md -->
```
`uv run pytest tests/test_prompt_versions.py -q` 를 돌려 실패 메시지가 주는 행(`| \`<해시>\` | 2026-11-08 | — | ... |`)을 `### analyze_chart_v3.md` 절 끝에 추가. 변경 요지: "#184 §6.1 anchor C3→C3′(B) 일봉 상승 마감일 1.4×avg_volume_50d, CLIMAX_ANCHOR_VOL_AVG_WEEKS→ANCHOR_MIN_HISTORY_WEEKS(50 불변); 전문가 [Q-1](B)·[Q-4-1] 승인. specs/2026-11-07-issue184-anchor-c3prime-design.md".

- [ ] **Step 4: export 재실행 + 검증**

Run: `uv run python scripts/export_thresholds.py && grep -n "ANCHOR_MIN_HISTORY_WEEKS\|CLIMAX_ANCHOR_VOL_AVG_WEEKS" web/src/data/thresholds.generated.ts`
Expected: `ANCHOR_MIN_HISTORY_WEEKS: number = 50;` 1줄, 구 이름 0건. 그리고 `grep -rn CLIMAX_ANCHOR_VOL_AVG_WEEKS kr_pipeline api scripts tests prompts web/src` → 0건.
Run: `uv run pytest tests/test_prompt_threshold_drift.py tests/test_prompt_versions.py tests/test_volume_regime_bars.py tests/test_regime_windows.py tests/test_climax_topping.py -q`
Expected: 전부 PASS.

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/common/thresholds.py kr_pipeline/llm_runner/compute/climax_topping.py kr_pipeline/common/data_regimes.py kr_pipeline/common/regime_windows.py scripts/issue184_anchor_shift_report.py prompts/analyze_chart_v3.md prompts/VERSIONS.md tests/test_prompt_threshold_drift.py tests/test_volume_regime_bars.py tests/test_regime_windows.py web/src/data/thresholds.generated.ts
git commit -m "#184: CLIMAX_ANCHOR_VOL_AVG_WEEKS→ANCHOR_MIN_HISTORY_WEEKS(50 불변, design-judgment), 주석 출처 정정 2건(p.349), 프롬프트 §6.1 C3′ 문안(전문가 승인)·VERSIONS 행·export"
```

---

### Task 2: `c3prime_weeks` + `find_anchor(weekly, daily)` (순수 함수, TDD)

**Files:**
- Modify: `kr_pipeline/llm_runner/compute/climax_topping.py:1-30`(docstring C3 설명), `:64-97`(find_anchor)
- Test: `tests/test_climax_topping.py`

**Interfaces:**
- Produces: `c3prime_weeks(daily: list[dict]) -> frozenset[tuple[int, int]]` — C3′ 를 충족하는 ISO (year, week) 집합. 충족일 = `prev is not None and close > prev and volume is not None and avg is not None and avg > 0 and volume >= BREAKOUT_VOL_FLOOR * avg`, `prev` = 직전 행의 `close`(첫 행은 None; halt 행의 carry 종가 그대로). 입력 빈 리스트 → 빈 집합.
- Produces: `c3prime_week(daily: list[dict], week_end: str) -> bool` = `date.fromisoformat(week_end).isocalendar()[:2] in c3prime_weeks(daily)` (테스트·표지 가독용 래퍼).
- Produces: `find_anchor(weekly: list[dict], daily: list[dict]) -> dict` — 반환 키 불변(`anchor_week, left_censored, no_transition, weeks_since`). C1·C2·C5·탐색 순서·`n <= W` left_censored·루프 하한 `range(n-1, W-1, -1)` 불변. C3 자리를 `iso(weekly[i]["week_end"]) in ok` 로 교체(`ok = c3prime_weeks(daily)` 는 루프 밖에서 1회). 주간 `volume` 은 더 이상 읽지 않는다(`vols`·`v_avg` 삭제).
- Produces(테스트 헬퍼, 다른 테스트 파일이 import): `tests/test_climax_topping._mk_daily_from_weeks(weekly: list[dict], ratio_week_idx: int | None = None) -> list[dict]` — 주봉 픽스처에서 일봉 합성: 주 i(week_end=금요일 가정)마다 월~금 5행, 날짜 = week_end−4..week_end; 종가 = 월~목 `0.99*c`, 금 `c`(금요일이 유일한 상승 마감일); `avg = mean(vols[i-50:i])` (i ≥ 50) 또는 `vols[i]`(i < 50); 거래량 = 월~목 `avg`, 금 `vols[i]`; `avg_volume_50d = avg`. 따라서 금요일의 C3′ 비율 = 구 C3 의 주간 비율 → 구 픽스처의 앵커 위치 보존.

- [ ] **Step 1: 실패 테스트 작성** (`tests/test_climax_topping.py` 에 추가; 기존 `find_anchor(wk)` 호출은 아직 두지 말고 아래 새 테스트만)

```python
def _mk_daily(rows, start="2020-01-06"):
    """rows = [(close, volume, avg50)] 연속 거래일(주말 건너뜀). volume/avg50 None 허용(halt)."""
    from datetime import date, timedelta
    out, d = [], date.fromisoformat(start)
    for c, v, a in rows:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"date": d.isoformat(), "close": c, "volume": v, "avg_volume_50d": a})
        d += timedelta(days=1)
    return out

def test_c3prime_weeks_up_close_day_at_floor():                       # (a)
    daily = _mk_daily([(100, 1000, 1000), (101, 1400, 1000)])          # 화: 상승 + 1.4×
    assert c3prime_weeks(daily) == {date(2020, 1, 7).isocalendar()[:2]}
    assert c3prime_week(daily, "2020-01-10") is True and c3prime_week(daily, "2020-01-17") is False

def test_c3prime_down_close_heavy_volume_excluded():                   # (b) 021240 형태
    daily = _mk_daily([(100, 1000, 1000), (99, 2400, 1000), (99.5, 1310, 1000)])
    assert c3prime_weeks(daily) == frozenset()

def test_c3prime_null_days_unmet_and_halt_resume():                    # (c)(d)(g)
    daily = _mk_daily([(100, 1000, 1000), (100, None, None), (103, 2000, 1000)])   # 화 halt(carry 100), 수 재개 103>100 + 2.0×
    assert c3prime_weeks(daily) == {date(2020, 1, 8).isocalendar()[:2]}
    assert c3prime_weeks(_mk_daily([(100, 1000, None), (105, 3000, None)])) == frozenset()   # avg 전부 NULL
    assert c3prime_weeks([]) == frozenset()

def test_c3prime_iso_week_membership_thursday_week_end():              # (e)
    daily = _mk_daily([(100, 1000, 1000), (101, 1500, 1000)], start="2020-01-06")   # 월·화
    assert c3prime_week(daily, "2020-01-09") is True                   # 목요일 week_end 도 같은 ISO 주

def test_find_anchor_requires_daily_and_keeps_fixture_anchor():        # 시그니처 + 보존
    wk = _fixture_single_transition()
    with pytest.raises(TypeError):
        find_anchor(wk)
    r = find_anchor(wk, _mk_daily_from_weeks(wk))
    assert r["anchor_week"] == wk[65]["week_end"] and r["weeks_since"] == 19

def test_find_anchor_c3prime_not_pure_relaxation():                    # (b) 주 단위: 하락일만 대량 → 미충족 → 다음 후보
    wk = _fixture_single_transition()
    daily = _mk_daily_from_weeks(wk)
    we = wk[65]["week_end"]
    for d in daily:                                                    # 돌파 주 금요일을 하락 마감으로 바꾼다
        if d["date"] == we:
            d["close"] = 0.98 * wk[65]["close"]
    assert find_anchor(wk, daily)["no_transition"] is True

def test_find_anchor_empty_daily_is_no_transition_not_error():         # (h)
    r = find_anchor(_fixture_single_transition(), [])
    assert r == {"anchor_week": None, "left_censored": False, "no_transition": True, "weeks_since": None}

def test_find_anchor_left_censored_boundary_unchanged():               # (f)
    wk50 = _mk_weeks(_drift(50, 1000.0, 980.0)); wk51 = _mk_weeks(_drift(51, 1000.0, 980.0))
    assert find_anchor(wk50, _mk_daily_from_weeks(wk50))["left_censored"] is True
    assert find_anchor(wk51, _mk_daily_from_weeks(wk51))["left_censored"] is False
```
(`import pytest`, `from datetime import date`, `c3prime_week, c3prime_weeks` import 추가.)

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_climax_topping.py -q -k "c3prime or requires_daily or not_pure or empty_daily or boundary_unchanged"`
Expected: FAIL (ImportError `c3prime_weeks` / `_mk_daily_from_weeks` 미정의).

- [ ] **Step 3: 구현** — `c3prime_weeks`·`c3prime_week`·`find_anchor(weekly, daily)` 를 Interfaces 대로. `_mk_daily_from_weeks` 를 테스트 파일에 구현. 모듈 docstring의 "C3 w 에서 volume ≥ BREAKOUT_VOL_FLOOR × 50주 평균 거래량 (돌파 거래량)" 줄을 "C3′ w 의 ISO 주 안에 상승 마감일(close > 직전 행 close) 중 volume ≥ BREAKOUT_VOL_FLOOR × avg_volume_50d 인 날 ≥1 (#184 2026-11, HMMS p.117·p.349; NULL 날 불충족 — governance 4-2)" 로 교체하고 `find_anchor` docstring 에 `daily` 행 규약(Global Constraints 문구) 추가.

- [ ] **Step 4: 기존 호출 40여 곳 갱신** — `tests/test_climax_topping.py` 안의 `find_anchor(X)` 를 전부 `find_anchor(X, _mk_daily_from_weeks(X))` 로(`X` 가 식이면 지역변수로 빼기). `grep -c "find_anchor(" tests/test_climax_topping.py` 와 `grep -c "_mk_daily_from_weeks" tests/test_climax_topping.py` 가 호출 수 기준으로 맞는지 확인.

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_climax_topping.py -q`
Expected: 전부 PASS. (다른 모듈 테스트는 Task 3 까지 red — 정상.)

- [ ] **Step 6: Commit**

```bash
git add kr_pipeline/llm_runner/compute/climax_topping.py tests/test_climax_topping.py
git commit -m "#184: find_anchor(weekly, daily) — C3→C3′(B) 상승 마감일 ≥1일 1.4×avg_volume_50d(c3prime_weeks, NULL 불충족), 일봉 필수 인자, 합성 일봉 헬퍼로 기존 픽스처 보존"
```

---

### Task 3: 소비처 4곳 배관 + 스크립트 (파리티)

**Files:**
- Modify: `api/services/payload_builder.py:152-155`(호출), `:386`(뒤에 `_fetch_daily_anchor_series` 신설)
- Modify: `kr_pipeline/trade_management/held_climax.py:78-125,150-157`, `kr_pipeline/trade_management/held_decline.py:129-134`, `kr_pipeline/trade_management/runner.py:194`
- Modify: `kr_pipeline/backtest/portfolio.py:71-72,241,613-617`
- Modify: `scripts/stage3_replay_climax_topping.py:57-66,210-211`, `scripts/issue184_anchor_shift_report.py`
- Test: `tests/test_climax_payload.py`, `tests/test_trade_held_climax.py`, `tests/test_trade_held_decline.py`, `tests/test_api_payload_builder.py`(필요 시 시드 보강)

**Interfaces:**
- Produces: `payload_builder._fetch_daily_anchor_series(conn, ticker: str, on_date: date) -> list[dict]` — Global Constraints 의 일봉 행 규약, `price_source(conn, ticker).indicators` 에서 1쿼리(`SELECT date, adj_close, volume, avg_volume_50d ... WHERE ticker=%s AND date<=%s ORDER BY date`).
- Produces: `held_climax.fetch_series(conn, symbol, as_of) -> tuple[list, list, list]` = `(weekly_full, daily_flagged, daily_ind)`.
- Produces: `held_climax.slice_upto(weekly, daily, daily_ind, as_of) -> tuple[list, list, list]` (세 목록 모두 `bisect_right` 절단; `daily_ind` 키 = `"date"`).
- Produces: `held_climax.gates_from_series(weekly, daily, daily_ind) -> dict` — `find_anchor(weekly, daily_ind)`; 반환에 `"daily_dates": [d["date"] for d in daily_ind]` 추가(Task 4 의 `held_window_flag` 입력).
- Produces: `portfolio.TickerData.daily_ind: list = field(default_factory=list)`.
- Consumes: Task 2 `find_anchor`.

- [ ] **Step 1: 실패 테스트 — 파리티·배관**

`tests/test_climax_payload.py`: 헬퍼 추가
```python
def _seed_anchor_week_indicators(db, ticker, week_end: date, close: float, ratio: float = 2.0):
    """앵커 주(ISO 주) 월~금 daily_prices+daily_indicators: 금요일만 상승 마감 + volume = ratio × avg_volume_50d(1e6)."""
    monday = week_end - timedelta(days=week_end.weekday())
    with db.cursor() as cur:
        for k in range(5):
            d, c = monday + timedelta(days=k), (close * 0.99 if k < 4 else close)
            v = int(1_000_000 * (ratio if k == 4 else 1.0))
            cur.execute("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (ticker, d, c, c * 1.01, c * 0.99, c, c, v, v * c))
            cur.execute("INSERT INTO daily_indicators (ticker, date, adj_close, volume, avg_volume_50d) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (ticker, date) DO UPDATE SET volume=EXCLUDED.volume, avg_volume_50d=EXCLUDED.avg_volume_50d",
                        (ticker, d, c, v, 1_000_000))
    db.commit()
```
`test_build_payload_climax_topping_gates_anchor_consistent`(:94)·`test_build_payload_daily_extremes_anchored_matches_direct_compute`(:288): 주봉 시드 직후 `_seed_anchor_week_indicators(db, ticker, weekly[65]["week_end"], weekly[65]["close"])` 호출, `expected = find_anchor(weekly_iso, _fetch_daily_anchor_series(db, ticker, on_date))`, 두 번째 테스트의 직접 비교도 같은 `anchor` 를 쓴다(:291 단언 `== weekly[65]` 유지). 추가 테스트:
```python
def test_build_payload_anchor_absent_without_up_close_breakout_day(db):
    """주봉은 구 C3 를 통과해도 앵커 주 일봉에 1.4× 상승 마감일이 없으면 no_transition(새 정의 = 일봉 기준)."""
    ticker = "CLPD7"; _seed_stock(db, ticker); start = date(2018, 1, 5)
    weekly = _weekly_rows(_drift(65, 1000.0, 980.0) + [(1100.0, 260_000)] + [(1100.0 + 15 * i, 110_000) for i in range(1, 20)], start)
    _seed_weekly(db, ticker, weekly)
    _seed_anchor_week_indicators(db, ticker, weekly[65]["week_end"], 1100.0, ratio=1.0)
    g = build_payload(db, ticker, weekly[-1]["week_end"])["climax_topping_gates"]
    assert g["anchor_week"] is None and g["no_transition"] is True
```
`tests/test_trade_held_climax.py`: `:84 gates_from_series(weekly, daily)` → `gates_from_series(weekly, daily, _mk_daily_from_weeks(weekly))`(import `from tests.test_climax_topping import _mk_daily_from_weeks`); `:153` `weekly, daily, daily_ind = fetch_series(...)`, `gates_from_series(weekly, daily, daily_ind)`, 직접 계산 `anchor = find_anchor(wk, daily_ind)`; `:165-166` 3-튜플 `slice_upto(wk_all, dl_all, di_all, on_date)`. 이 테스트들의 DB 시드에 `_seed_anchor_week_indicators`(위 헬퍼를 import)로 앵커 주 지표 행 추가. `tests/test_trade_held_decline.py:101-119`: `find_anchor(wk, _mk_daily_from_weeks(wk))`, `gates_from_series(wk, [], _mk_daily_from_weeks(wk))`. 러너 decline 발화 테스트(같은 파일의 runner 통합 테스트)가 `fetch_series` 를 실제로 타는지 확인 — 타지 않으면 `compute_held_gates` 만 mock 하고 `fetch_series` 는 실 DB 로 두는 케이스 1개를 추가해 `decline_metrics` 호출이 TypeError 없이 지나가게 한다.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_climax_payload.py tests/test_trade_held_climax.py tests/test_trade_held_decline.py -q`
Expected: FAIL (`_fetch_daily_anchor_series` ImportError, `find_anchor()` TypeError, 튜플 언팩 ValueError).

- [ ] **Step 3: 구현** — Interfaces 대로. `payload_builder:154` `anchor = find_anchor(weekly_full, _fetch_daily_anchor_series(conn, ticker, on_date))`. `held_climax`: `fetch_series` 3-튜플(`_fetch_daily_anchor_series` import), `slice_upto` 3목록, `gates_from_series(weekly, daily, daily_ind)` + `daily_dates`, `compute_held_gates`/`compute_held_climax` 언팩 갱신. `held_decline.compute_held_decline:132-134` `weekly, daily, daily_ind = fetch_series(...)`, `gates_from_series(weekly, daily, daily_ind)`, `decline_metrics(weekly, daily, ...)`. `runner.py:194` → `wk_, dl_, _ = fetch_series(conn, p["symbol"], as_of); dm = decline_metrics(wk_, dl_, gates.get("anchor_week"))`. `portfolio.py`: 필드 추가, `:615` 뒤 `daily_ind = _fetch_daily_anchor_series(conn, ticker, end)`(같은 지역 import), `TickerData(..., daily_ind=daily_ind, ...)`, `:241` `wk_, dl_, di_ = slice_upto(td_.weekly_full, td_.daily_flagged, td_.daily_ind, d)`, `gates_from_series(wk_, dl_, di_)`. 재생 스크립트 `:57-66` `daily_ind = _fetch_daily_anchor_series(conn, symbol, on_date)`, `find_anchor(weekly_full, daily_ind)`; `:210-211` 재조회 2회차도 일봉 재조회 후 `find_anchor(weekly_full_2, daily_ind_2)`.
보고 스크립트: `find_anchor_c3prime`·`c3prime_week`·`_fetch_daily_ind` 삭제 → `from api.services.payload_builder import _fetch_daily_anchor_series, _fetch_weekly_full`, `from kr_pipeline.llm_runner.compute.climax_topping import _sma, find_anchor`; 구 C3 는 `find_anchor_legacy_c3(weekly) -> dict`(#184 이전 본체의 동결 사본, docstring 에 "배포 후 관측 전용 — 본체는 C3′" 명기)로 스크립트 안에 유지; `run()` 에서 `old = find_anchor_legacy_c3(weekly)`, `new = find_anchor(weekly, _fetch_daily_anchor_series(conn, t, as_of))`. 모듈 docstring 을 "C3(구, 사본) vs C3′(본체)" 로 갱신.

- [ ] **Step 4: 파리티 실측(읽기 전용)**

Run: `uv run python scripts/issue184_anchor_shift_report.py --as-of 2026-11-06 --skip-universe`
Expected: 분류 모집단 `changed=66 (0.4342)`, `shift` 가 `data/verification/issue184_anchor_shift_2026-11-06.json` 의 첫 모집단과 동일(detail 의 ticker→shift 가 교집합에서 전부 일치). 결과 JSON 은 같은 경로를 덮어쓰므로 `git diff --stat data/verification/` 로 수치 변화 0 확인 후 변경 없으면 그대로 둔다.

- [ ] **Step 5: 전체 suite (green 체크포인트)**

Run: `pgrep -f pytest; uv run pytest tests/ -q 2>&1 | tail -5`
Expected: `failed` 0, `1 deselected`, `1 skipped`. 실패가 payload 시드 부족(앵커 기대가 anchored 인데 no_transition)이면 그 테스트에 `_seed_anchor_week_indicators` 를 추가하고 근거를 커밋 메시지에 적는다. 그 외 실패는 회귀.

- [ ] **Step 6: Commit**

```bash
git add api/services/payload_builder.py kr_pipeline/trade_management/held_climax.py kr_pipeline/trade_management/held_decline.py kr_pipeline/trade_management/runner.py kr_pipeline/backtest/portfolio.py scripts/stage3_replay_climax_topping.py scripts/issue184_anchor_shift_report.py tests/test_climax_payload.py tests/test_trade_held_climax.py tests/test_trade_held_decline.py
git commit -m "#184: 소비처 4곳 일봉 조달 단일화(_fetch_daily_anchor_series) — 분류 payload·보유 평가(fetch_series 3-튜플, daily_dates)·백테스트 TickerData.daily_ind·재생 스크립트; 보고 스크립트는 본체 import + 구 C3 동결 사본"
```

---

### Task 4: #207 표지 창 재정의 (주간 51주 창 삭제, 앵커 C3′ 일간 창)

**Files:**
- Modify: `kr_pipeline/common/data_regimes.py:27,65`(VOLUME_WINDOW_WEEKLY_WEEKS 삭제, import 정리)
- Modify: `kr_pipeline/common/regime_windows.py:1-16,27-31,36,87-142`
- Modify: `kr_pipeline/trade_management/runner.py:183`
- Test: `tests/test_regime_windows.py`, `tests/test_volume_regime_bars.py:41-43`, `tests/test_volume_regime_tag.py:133-156`

**Interfaces:**
- Produces: `held_window_flag(week_ends: Iterable, anchor_week, daily_dates: Iterable) -> str | None` — 창 = 앵커 C3′ 창 시작 ~ 마지막 주. 시작 = `daily_dates`(오름차순, 산술이 쓴 지표 행 날짜) 중 앵커 ISO 주의 첫 날짜 인덱스 j 에 대해 `daily_dates[max(0, j − (VOLUME_AVG_WINDOW_DAYS − 1))]`(regime_for_date); 앵커 주 일봉이 없으면(방어) 앵커 주 자체(regime_for_week). 끝 = `week_ends[bisect_left(weeks, a):]` 의 주들(regime_for_week). `window_flag([start_regime, *week_regimes])`. 앵커 None → None. 순수·DB 0.
- Produces: `classification_flag(conn, ticker, as_of, *, anchor_week=None)` 시그니처 불변, 창 = 일간 50봉(as_of 끝) ∪ 앵커~마지막 주봉 ∪ 앵커 C3′ 창. 조회 분기: `want_daily = _within_cap(d, False)`; `want_range = a is not None and a < B`(a ≥ B 면 전부 extended → DB 0); `want_c3 = a is not None and a >= B and _within_cap(a, False)`(a < B 면 전부 regular → DB 0). `want_range and not _within_cap(d, True)` → 즉시 MIXED(종전 상한 트레이드오프 유지). body: 일간 50봉 → MIXED면 반환; `want_range` 면 `w_last = _edges(weekly=True, end=d, n=1)[1]`, `_edges_flag(a, w_last, regime_for_week)`; `want_c3` 면 `first_day = _anchor_week_first_day(conn, src, ticker, a)`(`SELECT MIN(date) FROM {src.daily} WHERE ticker=%s AND date BETWEEN %s AND %s`, 월요일(`a − a.weekday()`)~a; None 이면 생략), `s, _ = _edges(weekly=False, end=first_day, n=VOLUME_AVG_WINDOW_DAYS)`, `_edges_flag(s, a, regime_for_date)`.
- Removes: `weekly_window_flag`, `data_regimes.VOLUME_WINDOW_WEEKLY_WEEKS`, `WEEKLY_WINDOW_MAX_CAL_DAYS` 는 유지(앵커~마지막 주 상한에 사용).
- Consumes: Task 3 `gates["daily_dates"]`.

- [ ] **Step 1: 실패 테스트** — `tests/test_regime_windows.py`:
  - `test_weekly_window_flag_and_zero_bar_weeks_excluded` 삭제, import 에서 `weekly_window_flag` 제거, `:99,:103,:135,:145` 의 `weekly_window_flag` 단언 삭제.
  - `test_held_window_flag_is_pure` 호출을 3-인자로(`daily_dates=[]` 전달 시 앵커 주 자체 기준 — 기존 기대값 유지: `held_window_flag(fridays, None, [])`, `held_window_flag([...], "2026-08-21", [])` == "mixed", `held_window_flag([], "2026-08-21", [])` is None, `held_window_flag(after, after[0], [])` is None 유지 — 10-02 주는 월요일 09-28 ≥ 경계라 extended).
  - `test_held_window_flag_includes_anchor_c3_denominator` 를 다음으로 교체:
```python
def test_held_window_flag_uses_anchor_c3prime_daily_window():
    """창 시작 = 앵커 주 첫 거래일에서 끝나는 50봉의 첫 날(spec D3). 그 날이 경계 전이면 mixed, 50봉 전부 경계 후면 None."""
    from kr_pipeline.common.thresholds import VOLUME_AVG_WINDOW_DAYS as N
    days = _weekdays(B - timedelta(days=200), 300)
    after = [d for d in days if d >= B]                                                  # B(09-28) 는 월요일
    fridays = [B + timedelta(days=4) + timedelta(weeks=i) for i in range(60)]          # 10-02 ~ (전부 extended)
    def anchor_at(k):                                                                    # 경계 후 k번째 거래일 이후 첫 월요일 주의 금요일
        monday = next(d for d in after[k:] if d.weekday() == 0); return monday + timedelta(days=4)
    a_early = anchor_at(0)                                                               # 10-02: 첫 거래일 09-28 끝 50봉 → 49봉 전 = 경계 전
    assert held_window_flag(fridays, a_early, days) == FLAG_MIXED
    a_late = anchor_at(N + 5)                                                            # 첫 거래일 인덱스 ≥ 55 → 50봉 전부 경계 후
    assert held_window_flag(fridays, a_late, days) is None
    assert held_window_flag(fridays, a_late, []) is None                                 # 방어: 일봉 없음 → 앵커 주 자체(extended)
    assert held_window_flag(fridays, (B - timedelta(days=31)).isoformat(), days) == FLAG_MIXED   # 08-28(금) 경계 전 앵커 + 경계 후 주 → mixed
```
  - `test_classification_flag_combines_daily_weekly_and_anchor_range` 갱신: `:143` 기대를 `is None`(주간 51주 창 삭제)으로, `:148-151` 은 C3′ 일간 창 기준으로 유지(`anchor_week="2026-12-04"` → 11-30 끝 50봉 시작 ≈ 09-24 < B → "mixed"; `late_anchor` → None) + 추가 단언 `classification_flag(db, "RWJ2", far, anchor_week=(B + timedelta(days=4)).isoformat()) == "mixed"`(경계 첫 주 앵커: 첫 거래일 09-28 끝 50봉이 경계 전 포함).
  - `test_flags_short_circuit_without_db_before_boundary_and_after_cap`: `weekly_window_flag` 단언 제거, 나머지 기대 유지(`anchor_week=far` → a−B > 400 → None DB 0; `"2026-08-07"` → MIXED DB 0).
  - `tests/test_volume_regime_bars.py:41-43` 의 `VOLUME_WINDOW_WEEKLY_WEEKS` import·단언 삭제, `assert not hasattr(m, "VOLUME_WINDOW_WEEKLY_WEEKS")` 를 `test_pr2_interim_rule_is_gone` 에 추가.
  - `tests/test_volume_regime_tag.py:133-156`: `held_window_flag([...], anchor, [])` 3-인자; 파라미터 `anchor_offset_weeks` 의 기대 flag 를 새 규칙으로 재계산(`[]` 전달 → 앵커 주 자체 기준: 경계 전 앵커 mixed, 경계 첫 주(10-02) 앵커 = extended 주 + 이후 extended → **None**(종전 mixed), None → None) — 픽스처 값 표를 그에 맞게 수정하고 docstring 에 "ver 2 창(#184)" 명기.

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_regime_windows.py tests/test_volume_regime_bars.py tests/test_volume_regime_tag.py -q`
Expected: FAIL (시그니처·기대값 불일치).

- [ ] **Step 3: 구현** — Interfaces 대로. 모듈 docstring(:12-14) 의 창 서술을 "분류 = 일간 50봉 ∪ 앵커 주~마지막 주봉 ∪ 앵커 C3′ 창(앵커 주 첫 거래일 끝 50봉의 첫 날 ~ 앵커 주) / 보유 = 앵커 C3′ 창 시작 ~ 평가 주(#184 2026-11, ver 2)" 로 교체. `runner.py:183` → `held_window_flag(gates.get("week_ends") or [], gates.get("anchor_week"), gates.get("daily_dates") or [])`. `data_regimes.py` 에서 `VOLUME_WINDOW_WEEKLY_WEEKS` 와 `ANCHOR_MIN_HISTORY_WEEKS` import 삭제.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_regime_windows.py tests/test_volume_regime_bars.py tests/test_volume_regime_tag.py tests/test_trade_held_climax.py -q`
Expected: 전부 PASS. `grep -rn "VOLUME_WINDOW_WEEKLY_WEEKS\|weekly_window_flag" kr_pipeline api scripts tests` → 0건.

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/common/data_regimes.py kr_pipeline/common/regime_windows.py kr_pipeline/trade_management/runner.py tests/test_regime_windows.py tests/test_volume_regime_bars.py tests/test_volume_regime_tag.py
git commit -m "#184: 표지 창 ver 2 — 주간 51주 창(VOLUME_WINDOW_WEEKLY_WEEKS·weekly_window_flag) 삭제, 앵커 C3′ 일간 창(첫 거래일 끝 50봉) 분류·보유 창에 편입, held_window_flag(daily_dates)"
```

---

### Task 5: `volume_regime_flag_ver` 열 + writer + 이관 SQL

**Files:**
- Modify: `kr_pipeline/db/schema.sql:1146-1154` 뒤에 8 ALTER 추가
- Modify: `kr_pipeline/common/data_regimes.py` (상수 신설)
- Modify: `kr_pipeline/llm_runner/store.py:397-470,506-610,686-730,876-920`, `kr_pipeline/trade_management/runner.py:262-300`
- Create: `scripts/sql/issue184_flag_ver_migrate.sql`
- Test: `tests/test_volume_regime_tag.py`, `tests/test_volume_regime_ver_migrate.py`(신규)

**Interfaces:**
- Produces: `data_regimes.VOLUME_REGIME_FLAG_VER: Final[int] = 2` — docstring "표지 창 정의 버전. 1 = 2026-09-28~#184 배포 전(주간 51주·앵커 끝 51주 창, 이관 SQL 이 채움), 2 = C3′ 일간 창(#184). writer 는 항상 현재 값을 쓴다 — as_of 가 경계 전이라 flag 가 NULL 이어도 '정의 2 로 평가했음'."
- Produces: 8테이블 `volume_regime_flag_ver SMALLINT` (NULL 허용, DEFAULT 없음).
- Produces: writer 6함수가 INSERT 열 목록에 `volume_regime_flag_ver` 를 추가하고 값 `VOLUME_REGIME_FLAG_VER` 를 쓴다: `store.insert_classification`(:397), 백필 insert(`table` 파라미터 함수, :506), `insert_trigger_log`(:688), `insert_entry_params`(:878), `runner._insert_decline_eval`(:271), `runner._insert_climax_eval`(:291).
- Produces: 이관 SQL(멱등, 파일 안 BEGIN/COMMIT 없음, 207 파일과 같은 주석 규약): 8테이블 각각 `UPDATE <t> SET volume_regime_flag_ver = 1 WHERE volume_regime_flag_ver IS NULL AND <as_of> >= '2026-09-28'` — `<as_of>` = `analyzed_for_date`(weekly_classification·classification_backfill·backtest_classification·recall_audit_classification·trigger_evaluation_log·entry_params) / `eval_date`(position_climax_evaluations·position_decline_evaluations). weekly_classification 만 `AND source NOT LIKE 'system\_%'`(표지 미평가 행).

- [ ] **Step 1: 실패 테스트**

`tests/test_volume_regime_tag.py` 의 기존 writer 테스트 4종(:82 분류, :94 백필, :106 트리거, :120 진입)과 :133 보유 테스트의 SELECT 에 `volume_regime_flag_ver` 를 함께 읽어 `== 2` 단언 추가. 신규 `tests/test_volume_regime_ver_migrate.py`:
```python
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
SQL = Path(__file__).parent.parent / "scripts" / "sql" / "issue184_flag_ver_migrate.sql"
B = date(2026, 9, 28)

def test_migrate_sets_ver1_only_for_null_rows_on_or_after_boundary(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRV1','VRV1','KOSPI') ON CONFLICT DO NOTHING")
        rows = [(B - timedelta(days=3), None), (B, None), (B + timedelta(days=7), 2)]          # 전·후·이미 2
        for i, (d, ver) in enumerate(rows):
            cur.execute("INSERT INTO weekly_classification (symbol, classified_at, analyzed_for_date, market, classification, source, volume_regime_flag_ver) "
                        "VALUES ('VRV1', %s, %s, 'KOSPI', 'watch', 'llm', %s)", (datetime(2026, 9, 25 + i, tzinfo=timezone.utc), d, ver))
        cur.execute("INSERT INTO weekly_classification (symbol, classified_at, analyzed_for_date, market, classification, source) "
                    "VALUES ('VRV1', %s, %s, 'KOSPI', 'disqualified', 'system_disqualify')", (datetime(2026, 10, 9, tzinfo=timezone.utc), B + timedelta(days=10)))
        cur.execute(SQL.read_text()); cur.execute(SQL.read_text())                            # 2회 = 멱등
        cur.execute("SELECT analyzed_for_date, source, volume_regime_flag_ver FROM weekly_classification WHERE symbol='VRV1' ORDER BY classified_at")
        got = cur.fetchall()
    assert [r[2] for r in got] == [None, 1, 2, None]
```
(`db` 픽스처가 테스트 끝에 rollback 하므로 시드가 남지 않는다 — 207 테스트 규약.)

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_volume_regime_tag.py tests/test_volume_regime_ver_migrate.py -q`
Expected: FAIL (`column "volume_regime_flag_ver" does not exist` / 파일 없음).

- [ ] **Step 3: 구현** — schema.sql 8 ALTER(기존 8줄 바로 아래, 주석 "(#184 2026-11) 표지 창 정의 버전 — 1 = 주간 51주 창(이관 SQL), 2 = C3′ 일간 창(writer)"), 상수, writer 6곳, 이관 SQL. kr_test 는 conftest 가 세션 시작 시 schema.sql 을 다시 적용하므로 **새 pytest 세션**으로 돌린다.

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_volume_regime_tag.py tests/test_volume_regime_ver_migrate.py tests/test_trade_held_climax.py tests/test_llm_store_load.py -q`
Expected: 전부 PASS.

- [ ] **Step 5: Commit**

```bash
git add kr_pipeline/db/schema.sql kr_pipeline/common/data_regimes.py kr_pipeline/llm_runner/store.py kr_pipeline/trade_management/runner.py scripts/sql/issue184_flag_ver_migrate.sql tests/test_volume_regime_tag.py tests/test_volume_regime_ver_migrate.py
git commit -m "#184: volume_regime_flag_ver SMALLINT 8테이블 — writer 항상 2(VOLUME_REGIME_FLAG_VER), 이관 SQL 은 as_of ≥ 2026-09-28 NULL 행만 1(멱등, system 행 제외)"
```

---

### Task 6: 문서 — 용어집·checklist 이력·spec 2026-09-30 §5·spec 상태

**Files:**
- Modify: `docs/GLOSSARY.md:327-352`(§9), `:366`(변경 이력 맨 위에 1줄) — 미커밋 §9/§10 변경(11-06)도 이 커밋에 포함
- Modify: `docs/superpowers/threshold-change-checklist.md` 적용 이력 끝에 1항목
- Modify: `docs/superpowers/specs/2026-09-30-volume-regime-design.md:56-60`(분류·보유 2행)
- Modify: `docs/superpowers/specs/2026-11-07-issue184-anchor-c3prime-design.md:3`(상태 줄)

- [ ] **Step 1: 용어집 §9** — "앵커" 항목의 C3 설명을 C3′(B) 로("C3′ 그 주 안에 **종가가 전일보다 오른 날** 중 하루라도 일봉 거래량 ≥ 1.4 × 50일 평균 거래량(`avg_volume_50d`) — 예: 월 120만/평균 100만 하락 마감(제외), 금 150만/평균 100만 상승 마감 → 1.5× 충족"), "C3 의 층위 오귀속" 항목 끝에 "2026-11 구현으로 해소(#184)" 1문장, "C3′(대체 후보)" 항목을 "C3′(현행, 2026-11)" 로 바꾸고 (B) 정의·NULL 불충족·`volume_regime_flag_ver`(1=구 창, 2=새 창) 1문장·출처(`climax_topping.c3prime_weeks`, spec 2026-11-07) 로 갱신. 변경 이력 맨 위: `- 2026-11-08: §9 C3′ 를 (B) 구현 정의로 갱신, 표지 버전 열 추가(#184 구현).`
- [ ] **Step 2: checklist 이력** — 2026-11-06 항목 아래에 `- 2026-11-08: #184 앵커 C3→C3′(B) — ...` 1항목: 트리거 사실(상수 개명 값 불변·BREAKOUT_VOL_FLOOR 소비 로직 주간→일간·VOLUME_AVG_WINDOW_DAYS 간접 소비·프롬프트 §6.1), 의존성 맵 = spec 2026-11-07 §6(고정 상수 11행, B-수치 = 배포 후 1회 집계 + 4주 발화·억제 + late_stage_base 발화율), 전문가 회신 11-07·11-08, 성과 목적 아님(3-5), 표지 ver 열.
- [ ] **Step 3: spec 2026-09-30 §5 표** — 분류 행과 보유 climax·decline 행 끝에 "**갱신 2026-11(#184, ver 2)**: 주간 C3 W+1 주·앵커 끝 C3 W+1 주 → 앵커 C3′ 일간 창(앵커 주 첫 거래일 끝 50봉의 첫 날 ~ 앵커 주); 보유 창 = 그 시작 ~ 평가 주(`held_window_flag(week_ends, anchor_week, daily_dates)`). 구 서술은 ver 1 행 해석용으로 유지." 추가. 자연 만료 문단에 "ver 2: 앵커 C3′ 창은 앵커 주 첫 거래일이 경계+50봉 이후면 만료" 1문장.
- [ ] **Step 4: spec 상태 줄** `:3` → `> 상태: **승인(2026-11-08)·구현 plan = docs/superpowers/plans/2026-11-08-issue184-anchor-c3prime.md**`.
- [ ] **Step 5: Commit**

```bash
git add docs/GLOSSARY.md docs/superpowers/threshold-change-checklist.md docs/superpowers/specs/2026-09-30-volume-regime-design.md docs/superpowers/specs/2026-11-07-issue184-anchor-c3prime-design.md
git commit -m "#184: 문서 — 용어집 §9 C3′(B) 현행화, checklist 적용 이력, 표지 spec §5 ver 2 갱신, 설계 spec 상태"
```

---

### Task 7: 최종 검증 + 브랜치 마무리

- [ ] **Step 1: 전체 suite** — `pgrep -f pytest` 가 비어 있는지 확인 후 `uv run pytest tests/ -q 2>&1 | tail -5`. Expected: `failed` 0 · `1 deselected` · `1 skipped`. 통과 수를 기록(새 기준).
- [ ] **Step 2: 잔존 참조 0 확인** — `grep -rn "CLIMAX_ANCHOR_VOL_AVG_WEEKS\|VOLUME_WINDOW_WEEKLY_WEEKS\|weekly_window_flag\|find_anchor_c3prime" kr_pipeline api scripts tests prompts web/src` → 0건. `grep -rn "find_anchor(" kr_pipeline api scripts | grep -v "legacy\|def find_anchor"` 의 모든 호출이 2-인자인지 눈으로 확인.
- [ ] **Step 3: 재생 스크립트 import 건전성** — `uv run python -c "import scripts.stage3_replay_climax_topping, scripts.issue184_anchor_shift_report"` Expected: 에러 없음.
- [ ] **Step 4: 코드 리뷰** — superpowers:requesting-code-review(또는 `/code-review`)로 브랜치 전체 리뷰. 지적은 superpowers:receiving-code-review 로 검증 후 반영·커밋.
- [ ] **Step 5: 마무리** — superpowers:finishing-a-development-branch. PR 본문에 "Closes #184" 류 키워드 **금지**(부정문 포함). PR 본문 = 의도(책 정합 교정, 3-5)·전문가 판정 링크(#184 코멘트)·배포 전 보고 수치·배포 절차(Task 8)·관측 계획(spec §7).

---

### Task 8: 배포 절차(머지 후, 사용자 수행 — 계획서에 기록만)

1. **먼저 DB**(pull 전 — writer 6곳이 새 열을 INSERT 하므로 pull 뒤 ALTER 전에 launchd 잡이 돌면 실행 전체가 실패한다; `ADD COLUMN IF NOT EXISTS` 는 구 코드와 호환): 운영 `psql $DATABASE_URL -f kr_pipeline/db/schema.sql`(ALTER IF NOT EXISTS 8줄) → `psql $DATABASE_URL -1 -f scripts/sql/issue184_flag_ver_migrate.sql`. kr_test 도 같은 두 명령(conftest 는 세션 리셋에서 다시 적용하지만 수동 규칙 4 준수). 머지된 main 의 두 파일을 쓴다.
2. 그 다음 라이브 체크아웃 `git pull`(사용자 터미널).
3. 첫 효과 = 다음 주말 분류·다음 보유 평가. 관측(spec §7-3): 첫 주말 분류 anchored/no_transition/left_censored 분포 1회 + `late_stage_base` 발화율(배포 전후 4주) + 4주 후 climax/decline 발화·억제 건수 → readout 부록. 10-05 사전등록 본문은 `volume_regime_flag_ver = 1` 행만.
4. 별건 이슈 2건 등록: 45주 최소 이력 재유도 · 앵커 주 자체의 상승 마감 요건(TLSMW Ch.5 p.70 기준 5·6).
