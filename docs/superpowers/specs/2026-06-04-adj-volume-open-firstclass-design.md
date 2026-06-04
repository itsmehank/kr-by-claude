# P0 — adj_open·adj_volume 1급화 + 정합성 가드 수정 설계

날짜: 2026-06-04
대상: `kr_pipeline/ohlcv`, `kr_pipeline/weekly`, `kr_pipeline/indicators`, `api/services/integrity_guard.py`, `kr_pipeline/db/schema.sql`

## 배경 / 문제

`daily_prices`는 raw OHLCV + 수정 종가/고가/저가(adj_close/adj_high/adj_low)를 저장하지만, **수정 시가(adj_open)와 수정 거래량(adj_volume)은 없다.** indicators는 거래량 지표를 위해 매 실행마다 `adj_volume = volume × close/adj_close`로 **재계산**해 `daily_indicators.volume`에 저장한다(= 보정값). 그런데 정합성 가드는 `daily_prices.volume`(원시) vs `daily_indicators.volume`(보정)을 같다고 비교 → **분할/조정 종목마다 가드 실패** → 백필·주말 분류가 무더기 스킵된다.

검증: pykrx `adjusted=True`는 가격뿐 아니라 **거래량도 보정해서 반환**한다(010120 실측: 가격 ÷5, 거래량 ×5; 파생식 `volume×close/adj_close` 와 정확히 일치). 즉 adj_volume은 **이미 받아오는데 버리던** 값이라 "줍기"만 하면 된다.

## 목표 (P0)

수정 거래량/시가를 **원천(daily_prices/weekly_prices)의 1급 컬럼**으로 저장하고, indicators가 그것을 **읽어** 쓰게 하며, 정합성 가드의 거래량 비교를 **보정 vs 보정**으로 바로잡는다. 이로써 데이터 정합성을 확보하고 가드 오탐(백필·주말 무더기 스킵)을 해소한다.

## 비목표 (Non-goals)

- **LLM 산출물·웹 표시 변경 안 함**: 차트 PNG(`chart_render`), CSV(`csv_builder`), payload(`payload_builder`/`payload_lite`), 웹 차트는 **현행 raw 유지**. (수정가 표시 통일은 P3.)
- 파이프라인 통합/드리프트 자동화 안 함 (P1).
- thresholds.py 상수 변경 없음 → threshold-change-checklist 불필요.
- 지수(index)·`value`(거래대금)는 분할 무관 → 손대지 않음.

## 핵심 결정

1. **adj_volume·adj_open을 pykrx adjusted=True에서 "줍기"** (adj_high/low와 동일 소스·패턴). 파생 안 함 → 검증 불가한 가정 제거, adj_close와 자동 정합.
2. **indicators는 재계산하지 않고 daily_prices.adj_volume(주봉은 weekly_prices.adj_volume)를 읽는다.**
3. **`split_adjusted_volume` 함수 제거** (미사용이 되어 혼란 방지) — 함수 + 그 단위테스트 + import 제거.
4. **정합성 가드**: 거래량 비교를 `daily_prices.adj_volume` vs `daily_indicators.volume`(보정 vs 보정)으로. adj_close 비교 유지. NULL-safe.
5. **adj_open은 계산 미사용(P3 표시용)이지만 P0에 포함** — 스키마/적재/백필을 1회로 묶어 2차 마이그레이션·2차 백필 회피.

## 아키텍처 / 변경 상세

### 1. 스키마 (양쪽 DB: kr_pipeline·kr_test 수동 적용)
- `daily_prices`: `adj_open NUMERIC(12,4)`, `adj_volume NUMERIC(20,2)` 추가 (nullable).
- `weekly_prices`: 동일 2컬럼 추가 (nullable).

### 2. ohlcv 적재 (증분 경로 — raw+adjusted 동시 호출)
- `transform.merge_raw_and_adjusted`: adjusted df rename에 `open→adj_open`, `volume→adj_volume` 추가(현 close/high/low에 더함). adjusted에 없으면 raw로 fallback(기존 adj_high/low 패턴 동일).
- `transform.to_price_rows`: 튜플에 `adj_open`(float), `adj_volume`(float) 추가.
- `store.upsert_daily_prices`: INSERT 컬럼 + ON CONFLICT SET에 `adj_open`, `adj_volume` 추가.

### 3. ohlcv 신선도 경로 (full-refresh = 분할 재동기화)
- `store.update_adj_prices`: temp table + JOIN-UPDATE에 `adj_open`, `adj_volume` 추가 (현 adj_close/high/low → +2).
- `ohlcv/modes._run_full_refresh._process_ticker`: `fetch_adj_only`가 반환하는 adjusted df에서 row 튜플에 `r["open"]`(→adj_open), `r["volume"]`(→adj_volume) 추가.
  - **중요**: 이 경로가 빠지면 분할 발생 시 adj_open/adj_volume이 갱신되지 않아 stale.

### 4. weekly 집계
- `weekly/load`(daily_prices 읽는 SELECT): `adj_open`, `adj_volume` 추가.
- `weekly/transform.aggregate_to_weekly`: agg에 `adj_open = grouped["adj_open"].first()`, `adj_volume = grouped["adj_volume"].sum(min_count=1)` 추가. 입력/출력 컬럼 목록(`WEEKLY_COLUMNS`) 갱신.
- `weekly/store.upsert_weekly_prices`: INSERT에 2컬럼 추가.

### 5. indicators — 읽기 전환 + 함수 제거
- `indicators/load.py` `load_daily_prices`/`load_weekly_prices`: SELECT에 `adj_volume` 추가. **미사용이 되는 `close`, raw `volume` 제거**(astype 포함). (adj_high/low/adj_close는 유지 — SMA·w52에 필요.)
- `indicators/modes.py`(`_process_ticker_daily`, weekly 처리): `adj_volume = split_adjusted_volume(...)` 호출 제거 → `adj_volume = df["adj_volume"]`. `volume_raw`/`close` 지역변수 제거. avg_volume/volume_ratio/pocket_pivot/volume_dry_up/up_down_volume_ratio/distribution_day 입력은 그대로 adj_volume.
- `daily_indicators.volume`/`weekly_indicators.volume`: 그 adj_volume 값으로 **계속 저장**(소비처·가드 호환).
- `compute/volume.py`: **`split_adjusted_volume` 함수 삭제** + `modes.py` import에서 제거. (avg_volume 등 나머지 함수는 유지.)
- `tests/test_indicators_volume.py`: `split_adjusted_volume` 관련 테스트 삭제(나머지 함수 테스트 유지).

### 6. 정합성 가드 (`api/services/integrity_guard.py`)
- SELECT를 `p.adj_close, p.adj_volume, i.adj_close, i.volume`로 변경(현재 `p.volume`).
- 거래량 비교: `abs(p.adj_volume - i.volume) > VOLUME_TOLERANCE` → 보정 vs 보정. 두 값은 정상 시 일치(indicators가 prices.adj_volume를 그대로 저장), 어긋나면 indicators stale 신호.
- `p.adj_volume`가 NULL(백필 전 과도기)이면 기존 `is not None` 가드로 거래량 검사 스킵 → 안전.
- adj_close 비교는 유지.

## 동작 변화 / 검증 포인트

- `daily_indicators.volume` 출처가 "파생(×factor)" → "pykrx 보정값"으로 바뀐다. 010120 실측은 동일했으나, 비정수 조정계수 종목은 pykrx가 정본이라 **거래량 파생 플래그(pocket_pivot/distribution_day/volume_dry_up/avg_volume_50d/volume_ratio_50d)가 미세하게 달라질 수 있음** → 백필 후 표본 검증.
- 사용자 눈에 보이는 표시/LLM 동작은 가드·정합성 외 **불변**(비목표).

## 백필 / 운영 순서 (P0 머지 후 1회, KRX 자격증명 필요)

1. `ohlcv full-refresh` (adj_close/high/low/**open/volume** 갱신)
2. `weekly full-refresh` (주봉 재집계 — adj_open/adj_volume 포함)
3. `indicators full-refresh` (weekly→daily)

- **백필 전 indicators 실행 금지**: adj_* 컬럼이 NULL이면 w52·거래량 지표가 NaN → 미너비니 후보 0 붕괴. (동료의 adj_high/low 백필 대기 건을 이 1회 백필이 흡수 — 사용자가 미리 안 돌리기로 함.)

## 영향 파일 요약

- 스키마: `kr_pipeline/db/schema.sql` (+ 양쪽 DB ALTER)
- ohlcv: `transform.py`, `store.py`, `modes.py`
- weekly: `load.py`, `transform.py`, `store.py`
- indicators: `load.py`, `modes.py`, `compute/volume.py`(함수 삭제)
- 가드: `api/services/integrity_guard.py`
- 테스트: `test_ohlcv_transform.py`, `test_ohlcv_store.py`(or modes), `test_weekly_transform.py`, `test_indicators_*`(load/modes/volume), `test_*integrity*`, schema 테스트

## 테스트 (TDD)

- ohlcv transform: merged에 adj_open/adj_volume 포함, adjusted 누락 시 raw fallback.
- ohlcv store: upsert/update_adj_prices가 adj_open/adj_volume 적재·갱신.
- weekly transform: adj_open=주 첫날, adj_volume=주간 합.
- indicators: load가 adj_volume 반환; modes가 stored adj_volume로 동일 결과(회귀); split_adjusted_volume 제거 후 import/호출 없음.
- guard: 보정 vs 보정 일치 시 통과, indicators stale 시 검출, adj_volume NULL 시 거래량 검사 스킵.
- baseline isolation fail 수(~31) 늘리지 않기.
