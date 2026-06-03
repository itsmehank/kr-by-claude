# w52_high / w52_low 를 수정 고가·저가 기준으로 — 설계

날짜: 2026-06-04
대상: OHLCV 적재(`kr_pipeline/ohlcv/`), 주봉 집계(`kr_pipeline/weekly/`),
지표 계산(`kr_pipeline/indicators/`), 스키마(`kr_pipeline/db/schema.sql`).

## 배경 / 문제

`w52_high`/`w52_low` 는 현재 **수정종가(adj_close)의 52주 rolling max/min** 으로 계산된다
(`kr_pipeline/indicators/compute/high_low.py:w52_high_low(adj_close, ...)`,
호출 `indicators/modes.py`). 즉 "최고/최저 **종가**"이지, 교과서적(IBD·오닐) "52주
**장중** 신고가/저가"가 아니다. 종가 고점 ≤ 장중 고점이므로 52주 고가가 실제보다 낮게
잡혀, 미너비니 **C7**(현재가 ≥ 52주고가×0.75)·**C6**(현재가 ≥ 52주저점×1.25) 판정과
화면/LLM 표시값이 교과서 정의와 어긋난다.

**핵심 발견**: 적재 단계가 pykrx `adjusted=True` 로 **수정 OHLC 전체를 이미 받아오지만**,
`transform.merge_raw_and_adjusted` 가 거기서 `adj_close` 만 빼내고 **수정 고가/저가를
버린다**. 따라서 비율 파생이 아니라 **이미 받는 KRX 공식 수정값을 저장만** 하면 된다.

## 목표

- `daily_prices`·`weekly_prices` 에 `adj_high`/`adj_low`(KRX 수정 고가/저가) 적재.
- `w52_high`/`w52_low` 를 **수정 고가의 52주 max / 수정 저가의 52주 min** 으로 재정의.

## 비목표 (YAGNI)

- 차트·CSV의 캔들 고가/저가 변경(아래 D2 — raw 유지).
- RS Line 52주 신고가(`rs_line_52w_high`) 변경(비율이라 장중 개념 없음 — 무관).
- open/raw 컬럼 정밀도·기타 지표 변경.

## 핵심 결정 (브레인스토밍 합의)

| # | 결정 | 선택 |
|---|---|---|
| D1 | 구현 방식 | **접근 B — 적재단 저장**(이미 fetch하는 KRX 수정 고가/저가 보존). 비율 파생(A) 기각: 정밀도 손해·엣지케이스. |
| D2 | 차트/CSV 고가·저가 | **raw(실제 체결가) 유지**. 수정값은 분석 지표(w52)에만. |
| D3 | 범위 | `w52_high` **및** `w52_low` 둘 다(대칭). |
| D4 | 컬럼 타입 | `NUMERIC(12,4)`(adj_close 동일, 수정값 소수). 추가 시 **nullable**(기존 행 백필 전 NULL). |
| D5 | 백필 | ohlcv full-refresh(수정 OHLC 재fetch)로 전 과거 채움 → indicators full-refresh로 w52 재계산. |

## 데이터 모델

- `daily_prices` + `adj_high NUMERIC(12,4)`, `adj_low NUMERIC(12,4)` (adj_close 뒤, nullable).
- `weekly_prices` + 동일 2컬럼.
- 마이그레이션: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` — **kr_pipeline·kr_test 양쪽 DB 수동 적용**
  ([[schema_manual_apply_both_dbs]] 패턴).

## 영향 범위 (검토 결과, 교정본)

### A. 적재 — 증분(incremental)
- `ohlcv/transform.py:merge_raw_and_adjusted` — adjusted df에서 `adj_close`만 보존하던 것을
  `adj_high`/`adj_low`(adjusted df의 high/low)도 보존. **이 작업의 적재측 핵심.**
- `ohlcv/transform.py:to_price_rows` — 튜플에 adj_high/adj_low 추가.
- `ohlcv/store.py:upsert_daily_prices` — INSERT 컬럼/VALUES/ON CONFLICT SET 에 2개 추가.
- `ohlcv/modes.py` 증분 흐름 — 위 함수 의존, 직접 변경 없음.

### B. 적재 — full-refresh
- `ohlcv/fetch.py:fetch_adj_only` — 이미 수정 OHLC 반환(high/low 포함). 시그니처 변경 불필요,
  소비측에서 high/low도 추출.
- `ohlcv/store.py:update_adj_close_only` — adj_close만 갱신하던 것을 adj_high/adj_low도 갱신
  (TEMP TABLE 컬럼 + JOIN-UPDATE SET 확장). 함수명/주석도 의미에 맞게 갱신.
- `ohlcv/modes.py` full-refresh 분기 — 행 튜플 `(ticker,date,adj_close)` → `(...,adj_high,adj_low)`.

### C. 주봉 집계
- `weekly/transform.py:aggregate_to_weekly` — 주간 `adj_high = max(일별 adj_high)`,
  `adj_low = min(일별 adj_low)`. 컬럼 목록(`WEEKLY_COLUMNS` 류)·`to_weekly_rows` 튜플 확장.
- `weekly/store.py:upsert_weekly_prices` — 컬럼 2개 추가.
- `weekly/modes.py` — 위 의존, 직접 변경 없음.

### D. 지표 계산 ⭐ (이 작업의 핵심 — 정의 변경 지점)
- `indicators/load.py:load_daily_prices`/`load_weekly_prices` — **SELECT에 adj_high/adj_low 추가**(현재 미로드).
- `indicators/compute/high_low.py:w52_high_low` — 시그니처 `(adj_high, adj_low, window)` 로 변경:
  `high = adj_high.rolling(window).max()`, `low = adj_low.rolling(window).min()`.
- `indicators/modes.py`(일 window=252 / 주 window=52) — `w52_high_low(adj_high, adj_low, ...)` 로 호출 교체.
- `pct_from_high_low(adj_close, high, low)` — 변경 없음(분자=현재가 adj_close, 분모=새 w52).

### E. 소비처 (대부분 불변 — w52는 computed 컬럼)
- 미너비니 `compute/minervini.py` C6/C7 — `w52_high`/`w52_low` 를 그대로 소비. 코드 불변, **동작만 정확해짐**.
- API/payload/csv/web — `daily_indicators.w52_high/low`(computed) 읽음. 코드 불변.

### F. 차트/CSV (D2: 불변)
- `chart_render.py`·`csv_builder.py`·payload OHLCV — 캔들·내보내기는 **raw high/low 유지**. 변경 없음.
  (52주 밴드 라인은 w52_high/low(computed)라 자동으로 정확해짐.)

### G. sanity check (선택)
- `ohlcv/modes.py`·`weekly/modes.py` 가격 이상치 점검에 `adj_high>0`, `adj_low>0`,
  `adj_high>=adj_low` 추가 검토(권장, 필수 아님).

## 마이그레이션 / 백필 순서

1. 스키마 ALTER(양쪽 DB) — nullable 2컬럼.
2. 코드 반영(적재 A/B + 주봉 C + 지표 D + 테스트).
3. `ohlcv full-refresh`(일·주) — 수정 OHLC 재fetch로 adj_high/adj_low 전 과거 채움.
4. `indicators full-refresh`(주 → 일) — w52 재계산.
5. 검증: C6/C7 통과 분포·후보 수 변화, adj_high≥adj_low NULL 커버리지.

## SSOT / threshold-change-checklist

w52 정의 변경은 `C6_W52LOW_MULT`·`C7_W52HIGH_MULT`(thresholds.py) 를 소비하는 계산
동작을 바꾸므로 **threshold-change-checklist 의존성 맵 작성 필수**(CLAUDE.md 규칙).
상수 값 자체는 불변이나 입력 정의(w52)가 바뀌므로 트리거 해당.

## 회귀 위험

- 적재 튜플/컬럼 변경 → ohlcv·weekly transform/store 테스트.
- `w52_high_low` 시그니처 변경 → `test_indicators_high_low.py` 갱신.
- 차트/CSV는 raw 유지라 무관(회귀 표면 최소화).
- 베이스라인 `uv run pytest tests/` — 사전 DB-격리 실패 수(약 26)를 늘리지 않을 것.

## 테스트

- transform: merge가 adj_high/adj_low 보존, to_price_rows/to_weekly_rows 튜플 크기, 주간 max/min.
- store: upsert 컬럼 round-trip, update_adj_close_only 확장.
- indicators: w52_high_low 가 adj_high max / adj_low min, 일·주봉 호출 정합.
- full-refresh full path는 DB-격리 카테고리(베이스라인) 따름.
