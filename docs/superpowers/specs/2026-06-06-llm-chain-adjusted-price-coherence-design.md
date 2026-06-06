# LLM 분류 체인 가격 눈금 adjusted 통일 설계

날짜: 2026-06-06
대상(변경): `api/services/payload_builder.py`, `api/services/chart_render.py`, `kr_pipeline/llm_runner/compute/payload_lite.py`, `kr_pipeline/llm_runner/compute/failed_breakout.py`, `kr_pipeline/llm_runner/compute/handle_quality.py`, `prompts/analyze_chart_v3.md`·`prompts/evaluate_pivot_trigger_v1.md`·`prompts/calculate_entry_params_v2_0.md`·`prompts/verify_analysis_v1.md`
대상(무변경·검증만): `api/services/csv_builder.py`, `kr_pipeline/llm_runner/compute/trigger_gate.py`, `kr_pipeline/llm_runner/evaluate_pivot.py`, `kr_pipeline/llm_runner/load.py`(get_active_with_current), `kr_pipeline/llm_runner/performance.py`

## 배경 / 문제

LLM 트레이딩 체인이 가격 눈금을 섞어 쓴다. **생산 측**(LLM 입력: payload OHLCV, 차트 PNG)은 **raw**, **소비 측**(결정론 게이트의 종가, performance 미래가격)은 **adjusted**(`daily_indicators.adj_close` 등). pykrx 보정 규약상 최신일은 adj≈raw 라 평소엔 드러나지 않지만, **분할이 윈도우(60일/104주/감시기간)에 끼면** 어긋난다:
- LLM이 raw 봉/차트로 피벗·베이스를 산출 → 저장 → adj 종가로 비교하는 게이트와 불일치 (돌파/탈락 오판)
- `performance.py`: adj 미래가 vs (raw 봉 기반) 매수가 → 수익률 왜곡
- 차트 PNG: raw 캔들 + adj 이동평균선 → 분할 윈도우 종목에서 LLM이 어긋난 그림을 봄
- `prompts/analyze_chart_v3.md:60` 은 "adjusted prices being used" 라 **명시하지만 실제 입력은 raw** (거짓)

시스템 나머지(지표·스크리너·웹차트[P3]·교과서 기준)는 이미 adjusted. 생산 측만 adj 로 맞추면 전 구간 정합된다.

## 목표

LLM 분류→돌파→매수→성과 체인의 **모든 가격을 adjusted 단일 눈금**으로 통일한다. 구체적으로 생산 측(LLM 입력)을 adj 로 전환하고, raw 를 읽던 결정론 게이트를 adj 로 전환하여, 이미 adj 인 소비 측과 정합시킨다.

## 비목표 (Non-goals)

- **기존 저장 행 마이그레이션 없음** (결정): 새 신호만 adj 로 생성. 옛 활성 신호(raw 피벗)는 수명(돌파/탈락/만료, 보통 수 주) 다해 자연 소멸 — 그 짧은 기간에 분할이 끼는 드문 경우만 일시 불일치(허용). `weekly_classification`/`entry_params`/`trigger_evaluation_log`/`signal_performance` 의 과거 행을 손대지 않는다.
- **entry_price 출력-계약 버그 수정 없음** (별도 후속): `calculate_entry_params_v2_0.md` 가 `entry_price`/`stop_loss`/`risk_reward_ratio`/`position_size_pct` 등을 출력 스키마에 정의하지 않는데 `store.insert_entry_params` 는 그 키들을 읽는 **프롬프트↔store 계약 불일치**가 있다. 이는 가격 눈금과 무관한 별개 버그이므로 본 범위에서 제외(후속 후보로 등록). 본 작업은 "LLM 입력이 모두 adj 가 되어 LLM 이 산출하는 가격이 adj 눈금이 된다"는 **눈금 정합**까지만 보장한다.
- CSV(이미 adj_close), 지수 가격(index_daily 는 adjusted 컬럼 없음 — 본질상 unadjusted), 웹차트(P3 완료), `ChartMetaBar` 주간 누적거래량(후속 후보).

## 핵심 결정 (브레인스토밍 합의)

1. **기준 눈금 = adjusted.** 시스템 전체가 이미 adj 정렬, 책 기준도 adj, 최신일 adj≈raw 라 실제 주문가 의미도 유지.
2. **마이그레이션 없음.** 새 신호 adj, 옛 신호 소멸.
3. **범위 = 가격 눈금만.** entry_price 계약 버그는 별도.

## 아키텍처

P3 와 동일 패턴: 저장된 `adj_*` 컬럼을 **읽기만**(새 계산 0). 생산 측을 adj 로 맞추면 소비 측(이미 adj)과 자동 정합. `adj_*` 가 nullable 이므로 모든 전환점에 `COALESCE(adj_x, raw_x)`(SQL) 또는 동등한 코드 fallback 적용.

**적용 범위(한 번 고치면 전 진입점 커버):** `payload_builder`·`chart_render`·`csv_builder` 는 `zip_builder.build_analysis_zip` 이 묶고, 이를 **`weekend.py`·`daily_delta.py`·`backfill.py` 셋이 공유**한다(실측). 따라서 생산 측 빌더를 한 번 adj 로 바꾸면 주말·일일델타·백필 (5) 분석이 모두 adj 입력을 받는다. 별도 진입점 수정 불필요.

### 1. LLM 입력을 adj 로 (생산 측)

- **`payload_builder.py`**:
  - `_fetch_daily_ohlcv`(현재 `SELECT date, open, high, low, close, volume`): `COALESCE(adj_open,open)` 등으로 교체. **JSON 키(open/high/low/close/volume) 유지, 값만 adj** → `daily_ohlcv_recent_60d` 구조·프롬프트 무변경.
  - `_fetch_weekly_ohlcv`(`weekly_ohlcv_recent_104w`): 동일.
  - `_build_current_metrics`(adj_close), `_fetch_indicators_recent`(adj_close+adj지표): 이미 adj — **무변경**. (전환 후 payload 내 current_metrics.close, OHLCV, indicators 가 모두 adj 로 정합)
- **`chart_render.py`** (`render_daily_chart`/`render_weekly_chart`): 캔들 그리는 컬럼(open/high/low/close), 거래량, pocket_pivot/distribution 마커(low*0.99/high*1.01)를 `COALESCE(adj_*,raw)` 로. SMA/52주/RS 오버레이는 이미 adj. (adj_close 는 이미 SELECT 되나 미사용 → 캔들에 사용)
- **`payload_lite.py`**:
  - `build_for_5b` `recent_daily_ohlcv_20d`(raw OHLC): adj 로. current_metrics.close 는 이미 adj.
  - `build_for_6` `current_state.intraday_high/low/open`(raw): adj 로. close 는 이미 adj (현재 mixed → 정합).
- **`csv_builder.py`**: 이미 adj_close only — **무변경(검증)**.

### 2. 프롬프트 정합

- **4개 프롬프트**(`analyze_chart_v3.md`, `evaluate_pivot_trigger_v1.md`, `calculate_entry_params_v2_0.md`, `verify_analysis_v1.md`)에 **"제공되는 모든 가격(OHLCV·차트·지표)은 수정주가(split-adjusted) 기준" 명시 한 줄** 추가. `verify_analysis_v1.md` 는 measurements 를 차트/OHLCV 와 대조하는 검증자(`zip_builder.py:187` 가 (5) ZIP 에 번들)이므로, 분할을 불일치로 오판하지 않도록 동일 명시 필요. `analyze_chart_v3.md:60` 의 기존 adjusted 언급은 전환 후 **사실이 됨**(문구 검증·유지). 출력 스키마는 변경하지 않음(entry_price 계약은 비목표).

### 3. 소비 측 게이트 정합

- **`failed_breakout.py`**(현재 `SELECT date, close FROM daily_prices`): `close` → `COALESCE(adj_close, close)`. (1개 컬럼)
- **`handle_quality.py`**(현재 `SELECT p.date, p.high, p.low, p.close, p.volume, i.sma_50`): `high/low/close/volume` **4개 전부** → `COALESCE(adj_high,high)`/`adj_low`/`adj_close`/`COALESCE(adj_volume,volume)`. (close 만 바꾸면 베이스 깊이[high/low]·거래량비율[volume]이 raw 로 남아 adj 피벗과 어긋남). sma_50 은 이미 adj.
- **`trigger_gate.py`/`evaluate_pivot.py`/`load.get_active_with_current`**: 종가가 이미 `i.adj_close` — **무변경(검증)**. (생산 측 전환으로 pivot 이 adj 가 되면 기존 cross-scale 비교가 *해소*됨)
- **`performance.py`**: 미래가 이미 `daily_prices.adj_close`. 생산 측 전환 후 LLM 이 산출하는 매수가도 adj 눈금 → **미래(adj) vs 매수(adj) 눈금 정합. 코드 무변경(검증+테스트)**. (entry_price *계약* 정확성은 비목표.)

### 4. 데이터 흐름

adj_* 저장컬럼 → 입력(payload·PNG·payload_lite) → LLM 이 adj 피벗/매수가 산출·저장 → 게이트·performance 가 adj 종가/미래가로 비교. 전 구간 단일 adj 눈금.

## 에러 처리 / 엣지

- adj_high/adj_low/adj_open/adj_volume 는 **nullable**(close/adj_close 만 NOT NULL). 모든 전환점에 `COALESCE(adj_x, raw_x)` 필수 — 누락 시 NULL 이 내려가 캔들/계산 깨짐. (현재 데이터는 100% 채워졌으나 방어.)
- 전환은 값 pass-through 만 바꿈(파생 비율·gap 계산 없음 — 감사 확인) → 정상 종목(adj=raw)은 동작 불변.

## 테스트 (함정 회피 — 분할 픽스처 필수)

최신일 adj≈raw 라 **평범한 픽스처로는 버그가 안 드러난다.** 모든 검증은 **윈도우 안에 raw≠adj 인 분할 픽스처**로 수행:

- **payload_builder**: `_fetch_daily_ohlcv`/`_fetch_weekly_ohlcv` 가 분할종목에서 raw 가 아닌 adj 값을 반환(키는 open/high/low/close 유지).
- **payload_lite**: `build_for_5b.recent_daily_ohlcv_20d`, `build_for_6.current_state.intraday_*` 가 adj 값.
- **failed_breakout**: 분할로 raw_close 와 adj_close 가 피벗 대비 다른 판정을 낼 픽스처 → adj_close 기준으로 판정함을 확인.
- **handle_quality**: 베이스 깊이·거래량비율이 adj 기준으로 계산됨(4컬럼 모두 전환 확인).
- **performance**: adj 매수가 행 직접 삽입 + adj 미래가 → 수익률이 adj-vs-adj 로 정확(분할 끼어도 일관). (entry_price 계약은 비목표라, 잘 정의된 adj entry 를 주입해 *눈금* 만 검증.)
- **chart_render**: 분할종목 PNG 렌더가 에러 없이 동작 + 캔들 SELECT 가 adj 컬럼 사용함을 확인(PNG 픽셀값 단언은 비실용적 → SELECT/df 레벨 검증 + 스모크).
- **회귀**: base 대비 신규 실패 0. 기존 LLM 러너/payload/chart 테스트 통과. 정상종목(adj=raw) 동작 불변 확인.

## 파일 변경 예상

- 변경: `payload_builder.py`(SELECT 2), `chart_render.py`(plot 컬럼 2 함수), `payload_lite.py`(build_for_5b/6), `failed_breakout.py`(close), `handle_quality.py`(4컬럼), 프롬프트 **4개**(analyze_chart_v3·evaluate_pivot_trigger_v1·calculate_entry_params_v2_0·verify_analysis_v1, 명시 한 줄).
- 무변경(검증): `csv_builder.py`, `trigger_gate.py`, `evaluate_pivot.py`, `load.py`, `performance.py`.
- 테스트: payload_builder/payload_lite/failed_breakout/handle_quality/performance 분할 픽스처 + chart_render 스모크.

## 후속 (본 작업 후 별도 후보)

1. **entry_price 출력-계약 버그**: 프롬프트가 entry_price/stop_loss/risk_reward 등을 출력 스키마에 정의하도록 + store 와 정합. performance 정확성 완성.
2. `ChartMetaBar` 주간 누적거래량 adj 전환.
3. (선택) 과거 raw 눈금 저장 행 마이그레이션 — 필요 시.
