# 분류 히스토리 테이블 — 설계 스펙

> 2026-06-12. 브레인스토밍 결정: 행 구성 **C(변화점 기본 + 펼침에 구간 주간 기록)**,
> 사유 노출 **A(아코디언)**, 배치 **전폭 테이블**. 시안: `.superpowers/brainstorm/33514-*/content/`.

## 1. 목적

차트 페이지에서 종목의 **과거 분류 이력**(언제 watch→entry 로 바뀌었고 왜)을
볼 수 없다. 차트 색 밴드는 구간을 시각화하지만 **사유(reasoning)·패턴·확신도**
를 보여주지 못한다. 백필(`classification_backfill`)로 쌓이는 백테스트 분류의
1차 소비 화면이기도 하다.

## 2. 데이터 — 기존 API 확장 (신규 엔드포인트 없음)

`GET /api/classifications/history/{ticker}` 응답 행에 3개 필드 추가:

| 필드 | 타입 | 비고 |
|---|---|---|
| `pattern` | `str \| None` | disqualified/구형 행은 NULL |
| `confidence` | `float \| None` | 〃 |
| `reasoning` | `str \| None` | 〃 |

- 쿼리 구조(live+backfill UNION, 같은 날짜 live 우선, `DISTINCT ON(d)`) 불변 —
  SELECT 컬럼만 확장. CTE 양쪽 분기에 동일 컬럼 추가.
- **하위호환 검증 완료**: 소비자 전수 3곳 — ChartPage 밴드(date/classification만
  사용), 기존 pytest 2건(부분 추출 비교) — 모두 additive 변경에 무영향.
- pydantic `ClassificationHistoryRow` 와 TS `ClassificationHistoryRow` 에
  Optional 로 추가.
- 페이로드: 5y 기간 ~260행 × reasoning ≈ 수십 KB — 허용. 분리 최적화는 YAGNI.

## 3. 분류 값 — 4종 (LLM 3종 + 시스템 1종)

`entry / watch / ignore`(LLM 출력) + **`disqualified`**(시스템 강등 이벤트 —
평일 disqualify 스윕이 minervini 탈락 시 기록, LLM 아님).

- disqualified 행: 패턴·확신도 NULL → "—" 표시, 사유는 저장된 고정 문구 표시.
- 칩 색: entry 초록 / watch 노랑(기존 ClassificationsPage 톤) / ignore 회색 /
  **disqualified 빨강** (차트 밴드 "미통과/탈락" 과 통일).

### 부수 작업 — 분류 값 집합 문서화 (이번에 발견된 문서 갭)

"테이블에 들어가는 분류 값 전체 집합(4종)"이 어디에도 정리돼 있지 않다
(로드맵·prompt·SimClassification 모두 3종 표기 — LLM 출력 관점에선 맞지만
데이터 관점 SSOT 부재).

- `web/src/lib/types.ts` 에 `export type Classification = "entry" | "watch" |
  "ignore" | "disqualified"` 신설, 신규 코드는 이를 사용 (기존 string 필드의
  일괄 교체는 범위 외).
- `web/src/data/llm-pipeline/glossary.ts` 에 `disqualified` 항목 추가
  (시스템 강등 — LLM 분류 아님, 평일 결정론 스윕).

## 4. 변화점 그룹핑 — 프론트 순수 함수

`web/src/lib/historySegments.ts` 의 `groupHistorySegments(rows)`:

- 입력: API 행(날짜 오름차순). 출력: 구간 배열(**표시는 최신 우선 역순**).
- 구간 = **연속된 동일 `classification`** 의 행 묶음. 분석 없는 주(갭)는 구간을
  끊지 않음 — 사이에 *다른 분류 행*이 올 때만 분할.
- 구간 대표값(행에 표시): `pattern`/`confidence`/`reasoning` 은 **구간 첫 주**
  기준 — "왜 이 분류로 전환됐나"에 답하는 값. 구간 내 변화는 펼침의 주간
  기록에서 추적.
- 구간 메타: `시작일`, `마지막 분석일`, `분석 주 수 N`(실제 행 수만 — 갭 주를
  세지 않음. 백테스트 해석 왜곡 방지).
- **차트 밴드와의 의도적 차이**: 밴드는 carry-forward(다음 분류까지 이월 시각화),
  테이블은 분석 행 기준(기록 사실만). 목적이 다름 — 갭은 행 날짜 사이로 자연히
  드러나고 밴드가 시각 보완.

## 5. 컴포넌트 — `ClassificationHistoryTable`

- 파일: `web/src/components/panels/ClassificationHistoryTable.tsx`
  (TriggerHistoryTable 스타일 미러).
- 위치: ChartPage 하단, **TriggerHistoryTable 위** `lg:col-span-2` 전폭 섹션.
- 데이터: ChartPage 의 기존 `classHistoryQ`(밴드용 쿼리) **재사용** — 추가 fetch
  없음. 기간은 차트 기간 선택과 자동 연동.
- 변화점 행: `기간(시작~마지막 분석일) | 분류 칩 | 패턴 | 확신도 | ▸ N주`.
- 펼침(아코디언, 행 클릭): **사유 전문** + 구간 주간 기록 표
  (`날짜 | 분류 칩 | 패턴 | conf | live/backfill 뱃지`). reasoning NULL →
  "사유 기록 없음".
- 빈 상태: "이 기간 분류 이력이 없습니다".

## 6. 에러 처리

- API 행의 NULL 필드(pattern/confidence/reasoning) → "—"/"사유 기록 없음".
- 미지의 classification 문자열 → 회색 기본 칩 (P2-10 DecisionPill 가드와 동일
  패턴 — 렌더 크래시 금지).

## 7. 테스트

- **백엔드(pytest)**: history 응답에 신규 3필드 포함 + disqualified 행의 NULL
  전달 — 기존 `test_api_classifications.py` 에 추가.
- **프론트(vitest)**: `groupHistorySegments` — 빈 입력 / 단일 구간 / 분류 교차
  분할 / 갭은 비분할 / 대표값=첫 주 / N주=행 수 / disqualified 구간.
- tsc + 프로덕션 빌드.

## 8. 범위 외 (YAGNI)

- 차트 밴드 클릭 ↔ 행 하이라이트 연동
- 사유 hover 툴팁(시안 B 요소)
- 기존 string 분류 필드들의 `Classification` 타입 일괄 마이그레이션
- reasoning 페이로드 분리(lazy load)
