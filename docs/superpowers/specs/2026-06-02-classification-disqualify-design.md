# 분류 자격 상실(disqualified) 강등 이벤트 — 설계

> **문제**: minervini 자격을 잃은(=`minervini_pass=false`) 종목이 `weekly_classification` 에서 갱신되지 않아, 최신 분류(watch/entry/ignore)가 **stale** 하게 남는다. 시스템에 "강등/이탈" 이벤트가 없어, /classifications 에 최대 ~14일간 옛 분류로 표시되다 lookback 만료로 *조용히* 사라진다(무분류로 *바뀌어* 표시되지 않음).
>
> **해결(Option 1)**: 평일 분석 시 active 분류 종목이 minervini 미통과로 떨어지면 **시스템이 `disqualified` 분류 행을 기록**한다(명시적 이탈 이벤트). → 즉시 active/분류 화면에서 빠지고, 이력에 "들어옴→나감"이 또렷이 남는다. life cycle 통합성의 '이탈 이벤트 부재' gap 을 닫는다.
>
> 배경: 이 gap 은 `/docs/llm-pipeline` 생애주기 모달 검토 중 사용자가 발견. ⑨ 손절 '열린 루프', promotion 비-가속과 같은 결("exit 이벤트 없음")의 일부.

## 0. 목적 / 성공 기준

- minervini 자격을 잃은 종목이 **그날 평일 분석에서 즉시 `disqualified` 로 강등**(새 행 기록)된다.
- 강등 종목은 active 모니터링(트리거 대상)·`/classifications` 기본 뷰에서 **즉시 제외**된다(이력은 보존, 필터로 조회 가능).
- 동일 종목을 **매일 재기록하지 않는다**(멱등).
- 성공: 평일 `full-daily` 실행 후, minervini_pass=false 가 된 기존 entry/watch/ignore 종목에 `disqualified` 행이 1개 생기고, active/분류 기본 쿼리에서 빠진다.

## 1. 메커니즘 (데이터 흐름)

`run_full_daily`(평일) **맨 앞에 "강등 점검(disqualify)" 단계 신규 추가**. 순서:

```
강등 점검(disqualify) → daily_delta → evaluate_pivot → entry_params → performance
```

강등 점검:
1. 최신 분류가 `entry`/`watch`/`ignore` 인 종목(= "분류된 active 집합") 로드.
2. 그중 **오늘(as_of) `daily_indicators.minervini_pass = false`** 인 종목 선별.
3. 각 종목에 `weekly_classification` **`disqualified` 행 기록**(시스템 발 origin, LLM 미호출).
- **멱등**: 이미 `disqualified` 인 종목은 1단계 집합(entry/watch/ignore)에 없으므로 재선별·재기록 안 됨.
- **강등을 맨 앞에** 둬서 같은 실행의 evaluate_pivot 이 깨끗한 active 집합을 보게 함.

**평일만** (주말 미적용): 한국 증시 주말 휴장 → 주말엔 minervini 가 안 바뀌고, 금요일 평일 실행이 이미 강등을 처리. (필터링은 실행 무관하게 항상 동작 — §4.)

## 2. 새 분류값 + 스키마

- 값 = **`disqualified`** (자격 상실). `entry`/`watch`/`ignore`(품질 미달, *통과는 함*) 와 의미 구분 — `disqualified` = *통과 자체를 잃음*.
- `weekly_classification.classification` 컬럼 `VARCHAR(10)` → **`ALTER ... TYPE VARCHAR(20)`** ("disqualified"=12자, 현 10자 부족). schema.sql 의 idempotent ALTER 패턴 사용.

## 3. 컴포넌트 / 파일

| 파일 | 책임 | 작업 |
|---|---|---|
| `kr_pipeline/db/schema.sql` | classification 컬럼 VARCHAR(20) widen | Modify |
| `kr_pipeline/llm_runner/load.py` | `get_classified_losing_minervini(conn, as_of)` 신규 — 최신 분류 ∈ {entry,watch,ignore} ∧ 오늘 minervini_pass=false | Modify |
| `kr_pipeline/llm_runner/store.py` | `insert_disqualification(conn, *, symbol, classified_at, market, reason)` 신규 — **게이트 우회 직접 INSERT** (classification='disqualified', source='system_disqualify', pattern/pivot/confidence NULL, reasoning=자동 문구, triggered_rules NULL) | Modify |
| `kr_pipeline/llm_runner/disqualify.py` | 강등 점검 단계 `run(conn, *, dry_run, as_of, limit)` — load → insert. dry_run 시 쓰기 skip. RunStats 유사 반환 | Create |
| `kr_pipeline/llm_runner/modes.py` | `run_full_daily` 에 disqualify 단계(맨 앞) 추가 | Modify |
| `api/routers/classifications.py` | 기본 쿼리에서 `disqualified` 제외 — `classifications` 필터에 명시될 때만 노출 | Modify |
| `web/src/pages/ClassificationsPage.tsx` (+ 필터 컴포넌트) | "자격 상실" opt-in 필터 칩 추가 | Modify |
| `web/src/data/llm-pipeline/lifecycle-story.ts` | ⑥장면에 강등 이탈 경로 한 줄 + (선택) glossary 용어 | Modify |

**게이트 우회 이유**: `disqualified` 는 *시스템 결정론 이벤트* 이지 LLM 분류가 아님. `apply_phase1_gates`(handle_quality)는 pattern≠cup_with_handle 이면 no-op 이라 무해하지만, 의미상·안전상 별도 직접 INSERT 가 깨끗(VERDICT_ORDER 의 미정의 값 엣지도 회피).

## 4. 소비처 / 필터링 (항상 동작)

`disqualified` 행이 최신이 되면, **실행 종류와 무관하게 쿼리 레벨에서 자동 제외**:
- `get_active_monitoring`: `classification in ('entry','watch')` 필터 → disqualified 자동 제외 → **트리거 대상 아님**.
- `/classifications`: 기본 WHERE 에 `classification <> 'disqualified'` (단 `classifications` 파라미터로 명시 요청 시 노출). 기본 뷰에서 빠지되 이력·필터 조회 가능.
- 이력 보존(append-only) — "언제/왜 나갔나" 추적 가능.

## 5. 엣지 / 비목표

- **재자격(다시 통과)**: 주말 weekend batch 가 minervini-pass 전체 재분류 → disqualified 종목이 다시 통과하면 새 watch/entry/ignore 행으로 자연 복귀(disqualified 가 최신이 아니게 됨). (평일 daily_delta 는 7일 내 재분류 제외라 주말이 복귀 처리.)
- **dry_run**: 쓰기 skip, 카운트만 로그.
- **오늘 데이터 없는 종목**: minervini_pass 판정 불가 → skip(강등 안 함).
- **멱등**: §1 — 이미 disqualified 는 재선별 집합 밖.
- **비목표**: ⑨ 손절 '열린 루프'·promotion 비-가속 미해결(별개). 상장폐지(`delisted_at`)도 별개. 주말 강등 미적용(평일만). ignore→watch/entry 승격 로직 변경 없음. thresholds.py 무관(책 임계 변경 아님 → checklist 불요).

## 6. 테스트

- **백엔드**(real DB rollback fixture, `tests/test_llm_*` 패턴):
  - entry 종목 + 오늘 minervini_pass=false 셋업 → `disqualify.run` → `weekly_classification` 에 disqualified 행 1개, source='system_disqualify'.
  - **멱등**: 2회 실행 시 추가 행 없음.
  - minervini_pass=true 인 active 는 강등 안 됨(음성).
  - dry_run: 행 미기록.
- **API**: `/classifications` 기본 호출 → disqualified 제외 확인. `classifications=['disqualified']` → 포함 확인.
- **프론트**: `npm run build`(tsc) + `npm run lint` + 수동(필터 칩 동작·모달 ⑥ 문구). (FE 단위테스트 프레임워크 없음.)

## 7. Authoritative sources

- minervini_pass 계산: `kr_pipeline/indicators/compute/minervini.py`
- active 로드: `kr_pipeline/llm_runner/load.py` (`get_active_monitoring`)
- 평일 오케스트레이션: `kr_pipeline/llm_runner/modes.py` (`run_full_daily`)
- 분류 저장: `kr_pipeline/llm_runner/store.py` · 스키마 `kr_pipeline/db/schema.sql`
- /classifications 쿼리: `api/routers/classifications.py`
- 배경(gap 발견): 생애주기 모달 spec `docs/superpowers/specs/2026-06-01-llm-lifecycle-story-modal-design.md`
