# RS 지표 개선 — threshold-change-checklist (2026-06-03)

> 트리거: `kr_pipeline/indicators/rs_rating.py`·`rs_line.py`·`modes.py` 의 계산 로직 변경(RS Rating 입력 교체, RS Line 분모 KOSPI 단일화, 파생 boolean 재정의) + `kr_pipeline/common/thresholds.py` 에 신규 상수 추출.
> `docs/superpowers/threshold-change-checklist.md` §(a) 기준 — 계산 로직 소비처 수정 해당.

---

## 베이스라인

`uv run pytest tests/ -q` 실행 결과 (2026-06-03):

```
26 failed, 447 passed, 1 warning in 29.62s
```

- **passed**: 447
- **failed**: 26 (weekly/llm/ohlcv DB isolation — 사전 존재 baseline)
- **error**: 0 (DB 연결 실패는 psycopg.errors 로 FAILED 분류됨)

이후 작업이 failed 수를 26보다 늘리면 회귀로 판정.

---

## 변경 상수

### thresholds.py 신규 추가 (현재 modes.py 하드코딩 → 추출)
- `RS_LINE_UPTREND_SHORT_WEEKS = 6` — 6주 상향 판정 윈도우
- `RS_LINE_UPTREND_LONG_WEEKS = 13` — 13주 상향 판정 윈도우
- `RS_LINE_DECLINE_GATE_WEEKS = 30` — 7개월 게이트 윈도우(현행 28주→30주 변경 포함)

### 계산 로직 변경 (thresholds.py 소비처)
| 대상 | 현재 | 변경 |
|---|---|---|
| `rs_rating` 입력 | `C/C[-252] − 1` 단일 1년 수익률 | IBD 가중 SF = `2·(C/C[-63]) + 1·(C/C[-126]) + 1·(C/C[-189]) + 1·(C/C[-252])` |
| RS Line 분모 | 종목 시장별 지수(`_market_to_index_code()`: 코스닥→2001) | KOSPI(1001) 단일 고정 |
| `rs_line_uptrend_6w/13w` 정의 | `rs_line > rolling(N).mean()` (MA 위) | 최근 N주 회귀 기울기 > 0 |
| 7개월 게이트 컬럼 | `rs_line_in_decline_7m` (신고가 없음 ≥140/196일) | `rs_line_not_declining_7m` 신규 (pure-declining: 기울기<0 AND `rs_line[t]<rs_line[t-30w]`) |

---

## 축 1 — 이 상수를 소비하는 고정 상수/룰

### 1단계 (파생 신호)

- `rs_rating` (IBD SF → 백분위) → **`C8_RS_RATING_MIN=70`** 게이트 소비
- `rs_line_not_declining_7m` (신규 boolean) → **후보 쿼리 하드 필터** (`AND rs_line_not_declining_7m = TRUE`)
- `rs_line_uptrend_6w/13w` (기울기 재정의) → LLM 페이로드 · UI (필터 아님)
- `rs_line` (분모 변경) → `rs_line_at_52w_high`, `rs_line_uptrend_*`, `rs_line_not_declining_7m` 파생 전체 영향

### 2단계 (소비 룰)

- `C8_RS_RATING_MIN=70`: `kr_pipeline/indicators/store.py:93` (daily gate), `store.py:179,184` (weekly 하드코딩 `70` → 정리 대상)
- `minervini_pass`: `daily_indicators.minervini_pass` 에 `rs_rating ≥ 70` 포함 → 후보 쿼리 `load.py:28-44`
- 후보 쿼리 (`load.py:28-44`): `minervini_pass = TRUE AND rs_line_not_declining_7m = TRUE` (신규 AND 조건)
- LLM 페이로드: `payload_builder.py:142-174` — `rs_line_uptrend_6w/13w`, `rs_line_at_52w_high` 신규 추가
- 프롬프트: `prompts/analyze_chart_v3.md §4.6` — boolean 입력 명시 필요

### 3단계 (룰 내부 고정 상수) — 2축 판정

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| `C8_RS_RATING_MIN=70` | 불가 (백분위 커트라인, 비례 조정 의미 없음) | **있음** — RS Rating 정의가 단일 1년 수익률 → IBD SF로 바뀌면 동일 종목도 점수가 달라짐. 70 커트라인 통과 분포가 "최근 모멘텀 강세주" 쪽으로 이동. | **EXTENDS** (Minervini TLSWM Ch.5: ≥70 요구, 숫자 70은 시스템 채택. O'Neil HTMMIS p.190: 80 미만 회피 권고이나 70 커트라인은 시스템 자체) | **B-수치** — SF 전환 후 후보 수·구성 변화 실측 재검증 필요 (Task 14). 70 자체는 변경 안 하되 분포 이동 데이터 확보 후 재검토. |
| `weekly store.py` 하드코딩 `70` | 불가 (같은 이유) | **있음** — daily는 `C8_RS_RATING_MIN` 참조, weekly는 리터럴 `70` → SF 전환 후에도 일치하지만 SSOT 깨짐. 별도 PR에서 다른 값으로 실수 변경 가능. | EXTENDS (70 숫자 동일) | **보정 포함** — 이번 작업에서 `C8_RS_RATING_MIN` 으로 통일(§C9 정리). |
| `rs_line_not_declining_7m` AND 조건 (후보 쿼리) | 불가 (boolean, 비례 없음) | **있음** — 신규 게이트 추가로 기존 minervini_pass 통과 종목 일부 탈락. 후보 수 감소 예상. | **EXTENDS** (O'Neil HMMS p.189-190: 7개월+ RS Line 하락 시 매도/회피. 우리는 진입 하드 필터로 용도전환) | **B-수치** — 게이트 추가 전후 후보 수 비교 측정(Task 14). 7개월 pure-declining 정의(기울기<0 AND 기간 대비 레벨 하락)가 O'Neil 의도에 충실한지 샘플 검증 필요. |
| `RS_LINE_DECLINE_GATE_WEEKS=30` (신규, 현행 28주 → 30주) | 불가 (시간 단위) | **미미** — 30주 vs 28주 차이 ≈ 0.07배 (14일). 7개월 경계에서 판정 번복 종목은 극소수. pure-declining 정의 특성상 30주 중 단기 반등 포함 시 FALSE — 2주 차이의 판정 변화 실질 없음. | **PRESERVES** (O'Neil "7개월" = ~30.4주에 가장 가까움. 현행 28주는 196일 기준 변환 오차) | **모니터링** (근거: 2주 조정은 7개월 정의 오차 보정이며, pure-declining 조건에서 극단 경계 케이스 이외 판정 변동 없음. 샘플 비교로 영향 미미 확인 후 유지.) |
| `RS_LINE_UPTREND_SHORT_WEEKS=6` (신규, 현행 `30일` 하드코딩) | 불가 (시간) | **미미** — 6주 = 30거래일 ≈ 현행 window=30과 유사. 단 이동평균 위 → 기울기>0으로 정의 자체가 바뀌어 비교 무의미. 6w는 필터 아닌 LLM 참고 신호이므로 판정 오류가 후보 선정에 직접 미치지 않음. | **EXTENDS** (Minervini TLSWM Ch.5: "I like to see the RS line trending upward for at least the past 6 weeks". 숫자 6은 책 직접 인용) | **모니터링** (근거: 필터 아닌 LLM 참고 신호 — 기울기 재정의가 LLM 해석 품질에만 영향. 후보 선정·minervini_pass 로직에 무관. 기울기 방식이 실제로 더 약한 신호를 걸러내는지 LLM 분류 결과로 관찰.) |
| `RS_LINE_UPTREND_LONG_WEEKS=13` (신규, 현행 `65일` 하드코딩) | 불가 (시간) | **미미** — 13주 = 65거래일 = 현행 동일. 정의(기울기)만 변경, 윈도우 불변. LLM 참고 신호, 필터 아님. | **EXTENDS** (Minervini: 13주+ 상향 강세 선호 언급. O'Neil "강세 RS Line" 서술에 부합) | **모니터링** (근거: 6주와 동일 — 필터 아닌 LLM 참고. 윈도우 자체 불변. 기울기 방식 전환 효과를 LLM 분류 결과로 관찰.) |

**소비 경계 (1줄)**: `rs_rating/rs_line_not_declining_7m → daily_indicators.minervini_pass + 후보 쿼리(load.py) → LLM runner → classify/entry_params → analyze_chart_v3.md §4.6 RS Line 해석`. (하류 LLM 레이어 단일 경로, rs는 종목 레벨, market_context 미접촉.)

---

## 축 2 — prompt 임계 텍스트 정합

| 대상 파일 | 현재 | 필요 작업 |
|---|---|---|
| `prompts/analyze_chart_v3.md §4.6` RS Line 섹션 | 일반 서술, boolean 입력 없음 | `rs_line_uptrend_6w`, `rs_line_uptrend_13w`, `rs_line_at_52w_high` boolean 입력 명시 추가 |
| `prompts/analyze_chart_v3.md §Inputs` (line ~46) | `rs_line`, `rs_rating` 수치만 | RS boolean 3개 추가 |
| `web/src/data/thresholds.generated.ts` | 현재 `C8_RS_RATING_MIN=70` 포함 | `scripts/export_thresholds.py` 재실행 — 신규 상수 3개 추가 후 |

---

## 충돌 점검 결과

- **FTD/distribution 룰 무관**: RS 지표는 종목 레벨. `status.py` (FTD_INVALIDATION_DAYS, DIST_COUNT 등) 는 시장 레벨 `market_context`. 접촉 없음. 충돌 없음.
- **minervini_pass 정합**: C8(`rs_rating≥70`) 이 SF 전환으로 **정의 불연속** 발생 → 히스토리 전체 재계산 확정(§9.1). 과거 minervini_pass 기록은 재계산 전까지 정의 불일치 상태임을 인지.
- **rs_line_in_decline_7m 소비처**: `chart_render.py`, `routers/indicators.py`, `csv_builder.py` 에서 기존 컬럼 제거 → 회귀 점검 필요 (Task 5 범위).

---

## 작성 근거 / 출처

- 설계 문서: `docs/superpowers/specs/2026-06-03-rs-indicator-rework-design.md` (전체)
- 템플릿: `docs/superpowers/threshold-change-checklist.md`
- 코드 대조: `kr_pipeline/indicators/rs_rating.py`, `rs_line.py`, `modes.py:107,183-186,504-507`, `store.py:93,179,184`, `llm_runner/load.py:28-44`, `api/services/payload_builder.py:142-174`, `prompts/analyze_chart_v3.md:194-200`, `kr_pipeline/common/thresholds.py:48`
