# RS 지표 개선 — 설계 (CLI 세션 정정판)

날짜: 2026-06-03
대상: `kr_pipeline/indicators/` (RS Rating / RS Line 계산·저장), 후보 선정
(`kr_pipeline/llm_runner/load.py`), LLM 페이로드·프롬프트
(`api/services/payload_builder.py`, `prompts/analyze_chart_v3.md`),
`kr_pipeline/common/thresholds.py`.

## 0. 이 문서의 위치

- **원본**: web 세션이 작성한 "RS 지표 개선 — 구현 명세(최종본)". 책 충실성 판정 +
  아키텍처 검토 산출물. 단, 코드를 직접 보지 않고 도면(설계 기억)만으로 작성되었다.
- **본 문서**: CLI 세션이 위 명세를 **실제 코드와 6개 영역 병렬 대조**한 뒤 정정한 판.
  결정(D1~D8)·책 근거·출처는 보존하고, **"신규 적재" 전제가 틀린 부분을
  "기존 구현 재정의/배선"으로 바로잡는다.**
- **핵심 결론**: 이 작업은 그린필드(신규)가 아니라 **브라운필드(기존 운영 코드 수정)**다.
  RS Line·파생 boolean·차트·API·테스트가 이미 운영 중이므로 회귀 위험 관리가 본질이다.

---

## 1. 검증으로 드러난 사실 정정 (원 명세 대비)

| # | 원 명세 주장 | 코드 실제 | 근거 | 정정 |
|---|---|---|---|---|
| C1 | RS Rating = 단일 1년 수익률 → 백분위, 백분위 코드는 입력만 교체 가능 | **사실** | `compute_1y_return(window=252/52)` `rs_rating.py:7`; 순수 백분위 함수 `assign_rs_rating_percentiles()` `rs_rating.py:15-38`; 일·주봉 `modes.py:189,508` | ✅ 작업 1 그대로 유효 |
| C2 | RS Line "신규 적재", `compute_rs_line` "흔적 있음, 재활용 확인" | **이미 완성·테스트·운영 중** | `compute_rs_line()`+5함수 `rs_line.py:7-83`; 테스트 `tests/test_indicators_rs_line.py`(10건); 스키마 일 `schema.sql:107-113`/주 `153-159`; 차트 `chart_render.py:149-154`, API `routers/indicators.py`, CSV `csv_builder.py` | ❌→ 작업 2는 "신규"가 아님. **분모 KOSPI 단일화만 실제 변경** (아래 C3) |
| C3 | RS Line 분모 = KOSPI 단일(D2) | **현재 종목 시장별 지수** (코스닥→코스닥지수 2001) | `_market_to_index_code()` `modes.py:107`; `load_index_daily/weekly_index` `load.py:39,86` | ⚠️ **D2는 실제 변경 작업**. §2.3 "코스닥 탈락 현상"이 곧 이 변경의 결과 |
| C4 | `rs_line_uptrend_6w/13w` "재사용"(기존 존재) | **존재하나 정의가 D7이 기각한 방식** | `rs_line > rs_line.rolling(N).mean()` `rs_line.py:48-57`; 윈도우 일 `modes.py:183(30),184(65)`/주 `504(6),505(13)` | ❌→ "재사용" 아님. **기울기>0으로 재정의** 필요 |
| C5 | `rs_line_in_decline_7m` 기존 정의 = "신고가 없음(보수적)" | **사실** | `(today − rs_line_52w_high_date) ≥ 140일(일)/196일(주)` `rs_line.py:60-83`, `modes.py:186,507` | ✅ 발견 B 정확. D6(pure-declining)로 재정의 대상 |
| C6 | LLM이 `rs_line_at_52w_high` 등 boolean "이미 수신" | **수신 안 함** (수치 `rs_line`·`rs_rating`만) | 페이로드 `payload_builder.py:142-174` SELECT에 boolean 없음; 프롬프트 §4.6 `analyze_chart_v3.md:194-200`은 일반 서술 | ❌→ 페이로드+프롬프트 **신규 배선** 필요 |
| C7 | 후보 쿼리가 `daily_indicators.minervini_pass`를 봄 | **사실**, weekly 미JOIN | `get_qualifying_tickers()` `llm_runner/load.py:28-44`; `weekly_indicators` 존재 `schema.sql:138-178` 그러나 미사용; JOIN 선례 `chart_render.py:181-182` | ✅ 발견 D·Open#2 유효 |
| C8 | (원 명세 언급 없음) RS 윈도우 상수 위치 | **6w/13w/7m 윈도우가 `modes.py`에 하드코딩**, `thresholds.py`엔 `C8_RS_RATING_MIN=70`만 | `thresholds.py:48`; 윈도우 `modes.py:183-186,504-507`; export `thresholds.generated.ts:12` | ⚠️ 정의 변경 시 **thresholds.py 추출 → threshold-change-checklist 트리거** |
| C9 | (원 명세 언급 없음) weekly C8 게이트 | **weekly는 상수 대신 `70` 하드코딩** | `store.py:179,184`(daily는 `C8_RS_RATING_MIN` `store.py:93`) | ⚠️ 정리 대상(기술부채) |

---

## 2. 확정된 결정 (Decision Log — 원 명세 유지)

| # | 결정 | 선택 | 태그 |
|---|---|---|---|
| D1 | RS Rating 계산 방식 | 단일 1년 → **IBD 가중 SF** | `[design]` |
| D2 | RS Line 벤치마크(분모) | **KOSPI 단일 광역 벤치마크** | `[design]` |
| D3 | RS Line 일/주봉 역할 | 일봉=차트·LLM 컨텍스트 / 주봉=필터 게이트 | `[design]` |
| D4 | O'Neil 7개월 룰 | **하드 필터** (minervini_pass와 AND) | `[book]`+용도전환`[design]` |
| D5 | Minervini 6주 룰 | **필터 아님**, LLM 참고 + UI | `[book-soft]` |
| D6 | 7개월 판정 강도 | **순수 하락(pure-declining, 완화적)** | `[measurement]` |
| D7 | 6주 판정 방식 | **회귀 기울기 > 0** (이동평균 위 아님) | `[measurement]` |
| D8 | 신고점 리더십 | 지표화 안 함, **차트 표시** | `[design]` |

태그: `[book]` 책 근거 / `[measurement]` 측정 정의 / `[design]` 설계 판단 /
`[book-soft]` 책의 선호("I like to see") 수준.

---

## 3. 작업 1 — RS Rating을 IBD 가중 SF로 교체 (변경 거의 없음, 정확)

### 3.1 현재 상태 (검증됨)
- `compute_1y_return(adj_close, window=252)` (`rs_rating.py:7`) = `C/C[-252] − 1`. 주봉 `window=52`.
- `assign_rs_rating_percentiles(returns)` (`rs_rating.py:15-38`) — **입력 Series만 받는 순수 함수**.
  내림차순 rank → `((n−rank)/n)*99` → 정수. 일·주봉 동일 함수 사용(`modes.py:266,573`).

### 3.2 변경
- **`compute_1y_return` 호출 지점의 입력 산출만 IBD 가중 SF로 교체.** 백분위 함수는 불변.

**IBD 가중 SF (수정종가, 최근 분기 2배)**
```
일봉:  SF = 2·(C/C[-63]) + 1·(C/C[-126]) + 1·(C/C[-189]) + 1·(C/C[-252])
주봉:  SF = 2·(C/C[-13w]) + 1·(C/C[-26w]) + 1·(C/C[-39w]) + 1·(C/C[-52w])
```
- 동등 변형(ROC형) `SF_B = 0.4·ROC63 + 0.2·ROC126 + 0.2·ROC189 + 0.2·ROC252` 는
  `SF_A = 5·SF_B + 5` 의 단조 affine → **백분위 순위 동일**. 가격비율 합산형(SF_A) 권장.
- 지수(KOSPI)로 나누지 않는다 `[design]`: "시장 대비"는 백분위(peers 대비)가 담당,
  시장 신호는 RS Line 몫. Rating="peers 대비", Line="market 대비"로 역할 분리.

### 3.3 주의 / 검증 필수 `[measurement]`
- 히스토리 252일(52주) 미만 NaN. SF는 63/126/189/252 **네 시점 모두** 필요 → 중간 lookback 결측 시
  해당 종목 그날 NaN(보간 안 함, §9.2).
- 분할 보정: adj_close 사용으로 방어.
- C8 게이트(`rs_rating≥70`)는 daily 기준 → daily SF 교체가 후보 선정에 직접 영향.
- **전환 후 ≥70 통과 종목 구성이 최근 모멘텀 쪽으로 이동.** (a) 컷오프·후보 수 재검증,
  (b) 과거 rs_rating과 정의 불연속(백테스트 주의), (c) **히스토리 전체 재계산 확정**(§9.1).

---

## 4. 작업 2 — RS Line 분모 KOSPI 단일화 (신규 아님 / 분모만 변경)

### 4.1 현재 상태 (이미 운영 중)
- `compute_rs_line(stock_adj_close, index_close)` (`rs_line.py:7`) = 종목 수정종가 / 지수 종가.
  일·주봉 모두 계산·저장·차트 렌더링됨.
- **분모가 종목 시장별 지수**: `_market_to_index_code()` (`modes.py:107`) → KOSPI 종목은
  지수 1001, **코스닥 종목은 2001**. 즉 현재는 광역 단일 분모가 **아니다.**

### 4.2 변경 (D2)
- **모든 종목(코스피·코스닥)의 분모를 KOSPI(1001) 단일로 통일.**
  `_market_to_index_code()` 의존 지점을 광역 분모 고정으로 바꾼다.
- 종목=수정종가 / 지수=일반종가(지수는 분할 개념 없음 — 의도된 비대칭). 추세(방향)만 사용.
- 일·주봉 둘 다 적용.

### 4.3 알고 써야 할 결과 `[design]`
- 코스닥 종목도 KOSPI 대비로 측정 → **KOSPI 주도장에서 코스닥 강세주가 7개월 게이트에
  걸려 탈락**할 수 있다. "general market 대비 laggard"로는 일관되며, 단일 벤치마크의
  의도된 결과. (코스닥에 코스닥지수 분모 — 즉 *현행* — 는 universe 일관성을 깨므로 D2에서 기각.)
- **회귀 위험**: 분모 변경은 기존에 적재된 모든 RS Line 값·파생 boolean·차트를 바꾼다.
  **히스토리 전체 재계산 확정**(§9.1) — 적재 시작일~현재 전 구간. 차트 표시 영향 점검 필요.

### 4.4 검증
- 주봉 RS Line week-ending 정렬(종목·KOSPI 일치) 재확인.
- 분모 전환 전후 RS Line 표본 비교(코스닥 종목 대상)로 의도된 변화 확인.

---

## 5. 작업 3 — 파생 지표 재정의 + LLM 배선

### 5.1 O'Neil 7개월 — 하드 필터 (재정의 + 신규 컬럼) `[D4·D6]`
O'Neil HMMS: RS Line 7개월+ 하락(또는 4개월+ 급락) = laggard. 이를 **진입 제외 게이트**로 용도전환.

- **신규 컬럼**: `rs_line_not_declining_7m` (BOOLEAN, **TRUE = 건강 = 하락 아님**) — 현재 미존재.
- **정의(순수 하락, 완화적)** `[D6]`:
  ```
  약 30주(≈7개월) 윈도우에서
    declining_7m             = (회귀 기울기 < 0) AND (RS_line[t] < RS_line[t-30w])
    rs_line_not_declining_7m = NOT declining_7m
  ```
  건강한 횡보 base 보존(신고가 없음 방식과 달리 실제 하락선만 포착).
  - **윈도우 = 30주 확정** (결정): 7개월(≈30.4주)에 충실. 현행 코드값 28주(196일)에서 변경.
- **기존 컬럼 처리 = 새 컬럼 교체 확정** (결정): 기존 `rs_line_in_decline_7m`(`schema.sql:113,159`,
  `rs_line.py:60-83`, "신고가 없음" 보수적 정의 — D6 기각)을 **폐기**하고
  `rs_line_not_declining_7m`(TRUE=건강) 신규 컬럼으로 교체. 폴라리티 통일.
  - weekly_indicators·daily_indicators 양쪽에서 기존 컬럼 제거 + 신규 컬럼 추가(schema.sql 양쪽 DB 수동 적용).
  - 소비처(차트/API/CSV)에서 `rs_line_in_decline_7m` 참조 제거·갱신 필요.
- **배선 = daily 미러링 확정** (결정): 게이트는 **주봉 RS Line으로 계산**(`weekly_indicators.rs_line_not_declining_7m`)하고,
  **최신 주봉 값(최신 `week_end_date ≤ date`)을 `daily_indicators.rs_line_not_declining_7m` 컬럼에 미러링**한다.
  - 후보 쿼리(`llm_runner/load.py:28-44`)는 기존대로 `daily_indicators`만 보되, 조건에
    `AND rs_line_not_declining_7m = TRUE` 추가. JOIN 없이 단일 테이블 유지.
  - daily 미러링 로직(주→일 최신값 복사)을 indicators 적재 단계에 추가.
  - 히스토리: 7개월 게이트 ~30주 필요하나 `minervini_pass`가 이미 ≥52주 요구 → 후보 항상 충분.
    NaN 은 `= TRUE` 비교로 자동 제외됨만 확인.
- **선택적 후속**: O'Neil "4개월 급락"은 임계 정의 필요 → 초기 7개월만, 4개월은 2차 게이트로 보류.

### 5.2 Minervini 6주 — 필터 아님, LLM 참고 (재정의 + 배선 신규) `[D5·D7]`
- **컬럼**: `rs_line_uptrend_6w` (존재하나 정의 변경) + `rs_line_uptrend_13w`(보완 신호).
- **재정의(기울기)** `[D7]`: 현재 `rs_line > rolling(N).mean()`(이동평균 위, `rs_line.py:48-57`)는
  평평/스파이크에도 TRUE라 약함 → **주봉 RS Line 최근 6주(13주) 회귀 기울기 > 0** 으로 교체.
  - 6포인트 노이즈 있음 — soft 신호이므로 허용.
- **배선(신규)**: 산출 boolean을 **LLM 페이로드에 추가** + UI 표시.
  - 현재 `payload_builder._fetch_indicators_recent()`(`payload_builder.py:142-174`)는 `rs_line`·`rs_rating`만
    SELECT → **`rs_line_uptrend_6w`, `rs_line_uptrend_13w`(+`rs_line_at_52w_high`) 추가**.
  - 프롬프트 §4.6(`analyze_chart_v3.md:194-200`)에 이 boolean 입력 명시 추가.
  - **후보 쿼리에는 영향 없음.** 기존 LLM 분석 흐름(분류/진입 파라미터)은 변경하지 않음.

### 5.3 신고점 리더십 — 차트 표시 (지표화 안 함) `[D8]`
- `rs_line_at_52w_high`(`schema.sql:110,156`, 계산됨) 는 존재. 단 현재 LLM 미수신(C6) → 5.2에서 함께 페이로드 추가.
- 게이트로 쓰지 않음. 차트에 RS Line + 신고점 위치 표기로 충분.
- 향후 필요 시 `rs_line_52w_high_date` vs 주가 52주 신고점 날짜 비교로 leadership boolean화 가능.

---

## 6. 변경 요약 (정정판)

| 항목 | 현재 상태 | 변경 | 배선 위치 | 폴라리티 |
|---|---|---|---|---|
| RS Rating | 단일 1년→백분위(분리 구조) | 입력만 IBD SF로 교체 | `compute_1y_return` 호출부(일·주봉) | — |
| RS Line | **이미 운영**, 분모=시장별 지수 | **분모 KOSPI 단일화**(`_market_to_index_code` 우회) | 일=차트/LLM, 주=게이트 | — |
| `rs_line_not_declining_7m` | 미존재 | **신규**(pure-declining, 30주) | **후보 하드 필터**(daily 미러링, minervini_pass AND) | TRUE=건강 |
| `rs_line_in_decline_7m` | 존재(보수적 정의) | **폐기**(새 컬럼으로 교체) | 양쪽 DB 제거 + 소비처 갱신 | — |
| `rs_line_uptrend_6w` | 존재(MA위 정의) | **기울기>0 재정의** | **LLM 참고 + UI**(필터 아님) | TRUE=상향 |
| `rs_line_uptrend_13w` | 존재(MA위 정의) | 기울기>0 재정의 | LLM 참고(강도) | TRUE=상향 |
| `rs_line_at_52w_high` | 존재, **LLM 미수신** | 페이로드 추가 | LLM 참고 + 차트 | TRUE=신고점 |
| 신고점 리더십 | — | 지표화 안 함 | 차트 표시 | — |
| RS 윈도우 상수 | modes.py 하드코딩 | thresholds.py 추출(정의 변경 시) | SSOT | — |
| weekly C8 `70` | 하드코딩 | `C8_RS_RATING_MIN` 사용 | (정리) | — |

---

## 7. Threshold / SSOT 영향 (CLAUDE.md 규칙)

- `thresholds.py` 또는 그 소비 계산 로직을 건드리면 **`docs/superpowers/threshold-change-checklist.md`
  의 의존성 맵(2축 판정) 작성 필수.**
- 본 작업의 트리거 해당 항목:
  - RS Rating SF 교체 = `rs_rating`(→ `C8_RS_RATING_MIN` 소비) 계산 로직 변경 → **체크리스트 대상.**
  - 6w/13w/7m 윈도우(30/65/140/196) 정의 변경 → 상수 추출 시 thresholds.py 추가 → **체크리스트 대상.**
- 상수 추가/변경 시 `scripts/export_thresholds.py` 재실행 → `web/src/data/thresholds.generated.ts` 갱신.
- 프롬프트(.md)의 임계 텍스트는 수동 동기화(§4.6, `analyze_chart_v3.md`).

---

## 8. 회귀 위험 (브라운필드)

기존 운영 코드를 수정하므로 다음이 영향받는다 — 작업 시 회귀 점검:
- RS Line 분모 변경 → `chart_render.py:149-154`(차트), `routers/indicators.py`(API),
  `csv_builder.py`(CSV), `api/schemas/indicator.py`.
- 파생 boolean 재정의 → `tests/test_indicators_rs_line.py`(기존 10건, **정의 변경 시 갱신 필요**),
  `tests/test_indicators_store.py`.
- 후보 쿼리 변경 → `llm_runner/{weekend,backfill}.py`, disqualify 경로.
- 베이스라인: `uv run pytest tests/` — 사전 isolation fail ~25개는 baseline, 그 수를 늘리지 않을 것.

---

## 9. 확정 결정 (구 Open Items)

### 9.1 사용자 결정 (2026-06-03)
| # | 항목 | 결정 |
|---|---|---|
| 2 | 7개월 게이트 배선 | **daily 미러링** (주봉 계산 → 최신값 daily 행 복사, JOIN 안 함) |
| 3 | 7개월 lookback 윈도우 | **30주** (현행 28주=196일에서 변경) |
| 4 | `rs_line_in_decline_7m` 처리 | **새 컬럼 교체** (`rs_line_not_declining_7m`, TRUE=건강) |
| 6/10 | 히스토리 | **전체 재계산** (RS Rating SF·RS Line 분모 모두 과거 전 구간) |

### 9.2 기본값 채택 (이의 시 변경)
| # | 항목 | 기본값 |
|---|---|---|
| 1 | IBD SF 수식 형태 | **가격비율 합산형(SF_A)** — ROC형과 순위 동일, 재현 표준형 |
| 7 | SF 데이터 갭(중간 lookback 결측) | **해당 종목 그날 NaN** (보간 안 함, 게이트 자동 제외) |
| 8 | RS 윈도우 상수 추출 | **이번 변경 대상(6w/13w/7m)만 thresholds.py 추출** + threshold-change-checklist 작성 |
| 9 | weekly C8 `70` 하드코딩 | **`C8_RS_RATING_MIN` 상수로 통일** (정리 포함) |

### 9.3 구현 단계 잔여 (결정 아님 — 작업 중 수행)
- 5. `rs_line_uptrend_6w/13w` 기울기 재정의 시 기존 테스트·소비처(차트/UI) 영향 점검·갱신.
- SF 전환 후 **≥70 후보 수·구성 재검증** (정의 불연속 인지하에).
- 슬로프 회귀 구현 세부(엔드포인트 비교 RS_line[t] vs RS_line[t-30w] + 기울기 부호).
- 전체 재계산 실행 범위(적재 시작일~현재)·소요 시간 측정.

### 9.4 재계산 검증 (2026-06-04, production kr_pipeline)
weekly full-refresh → daily full-refresh 실행. 둘 다 failures=0, warnings=0.
- weekly: 2552종목, Phase B(rs_rating) 262,501 / Phase C(minervini) 262,501 행.
- daily: Phase B 1,225,247 / Phase C 1,225,247 / Phase D 미러 1,225,247 행.
- 최신일(2026-06-02) 후보 구성: rs_rating≥70 **739**(2552 중 29% = 백분위 상위~30%, SF 교체 후에도 백분위 로직 정상),
  minervini_pass **180**, 게이트 적용 최종 후보 **92**, 게이트 탈락 **88**(KOSPI 대비 7개월 하락).
- 미러 커버리지: NULL 40(히스토리 부족, =TRUE 게이트에서 자동 제외) / TRUE 344 / FALSE 2168.
- 해석: 게이트가 minervini 통과주를 180→92로 컷 — 설계 §2.3 KOSPI 단일 분모의 의도된 laggard 회피 효과(0 아님=버그아님, 변화있음=게이트작동).

---

## 10. 출처

**1차 (책)**
- Minervini, *Trade Like a Stock Market Wizard*, Ch.5 Trend Template — criterion 8: RS 랭킹 ≥70,
  선호 80s~90s; 주석: RS Line 강한 하락 금지, 6주(선호 13주+) 상향.
- Minervini, *Think and Trade Like a Champion*, Ch.6 Trend Template; Ch.7 "How to Correctly Use
  Relative Strength" — RS ranking·RS line·기술적 흐름 조합.
- O'Neil, *How to Make Money in Stocks*, "L = Leader or Laggard"(p.189–190) — RS Rating 1~99,
  12개월, 최고 종목 평균 87; 80 미만 매수 회피, 큰 승자 90+; RS line 7개월+ 하락 또는 4개월+ 급락 시 매도.

**IBD 산식 재구성 (책 아님, 공개 구현체 정설 — 2:1:1:1 = 0.4/0.2/0.2/0.2 가중으로 수렴)**
- skyte `relative-strength`(GitHub): 최근 분기 2배 가중, 분할 보정 경고.
- Optuma / TradingView "IBD Style RS Rating" 스크립트: 0.4/0.2/0.2/0.2 ROC.
- stockmaniacs 가이드: 2:1:1:1 가격비율 합산형 예시.

---

## 부록 — 쉬운 말 정리

- **RS Rating**: "1년 성적 한 방" → "최근 3개월에 2배 점수 주는 IBD식"으로 교체. 등수 매기는
  기계(백분위)는 그대로, 넣는 점수만 교체. 코스피지수는 안 들어감(등수 자체가 "다른 애들 대비").
- **RS Line**: "내 주가 ÷ 지수" 추세선. **이미 만들어져 차트에 그려지는 중.** 새로 만드는 게 아니라,
  지금은 코스닥 종목을 코스닥지수와 비교하는 걸 **전부 코스피와 비교하도록 분모만 통일**한다.
  (그래서 코스피 주도장에선 멀쩡한 코스닥 종목이 걸러질 수 있음 — 알고 쓰기.)
- **합격 도장(7개월)**: "7개월째 밀리는 중이면 탈락"(진짜 필터). 단 *진짜 내려가는 선*만 잡고
  *쉬는 선(횡보)*은 살림. 기존 컬럼은 "신고가 못 찍은 지 오래"로 재던 거라 **새로 고쳐 정의**한다.
- **참고 신호(6주/13주)**: 탈락 기준 아님, LLM에 "참고해"로 넘김. **그런데 지금은 LLM한테 안 넘기고
  있어서 넘기는 배선을 새로 추가**해야 함. 재는 방법도 "평균 위냐"→"실제 올라왔냐(기울기)"로 바꿈.
- **요약**: 원 명세는 "새로 만든다"였지만 실제로는 대부분 **"이미 있는 걸 고쳐 쓴다"**. 운영 중인
  차트·API·테스트가 그걸 쓰고 있으니 잘못 건드리면 멀쩡한 게 깨질 수 있어 회귀 점검이 핵심.
