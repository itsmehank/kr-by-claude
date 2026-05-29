# Step 5 SCOPE — 5/28 배치 신뢰성 + 잔여 mismatch 조사

> **결론**: **재실행 불필요 + 잔여 mismatch 0건.** Phase 0 종료 가능.

조사 시점: 2026-05-29. 도구: 직접 SQL (`/tmp/step5_scope.py`).

## 1. 5/27 ~ 5/29 분류 분포

| classified_at (KST) | classification | count |
|---------------------|----------------|-------|
| 2026-05-29 | entry | 1 |
| 2026-05-29 | ignore | 114 |
| 2026-05-29 | watch | 10 |

**5/27, 5/28 의 weekly_classification 행은 0건.**

해석: 사용자 v2 지시에 명시된 "5/28 배치 2,416 종목" 은 실제로 *분류가 일어나지 않은*
상태였다. 이는 다음 추론과 일관:

- 5/28 13:29 daily_indicators partial 적재가 일어난 시점에서, 분류 (`weekend.py`)
  자체는 그 이후 *돌지 못함* — Step 1 cleanup 이 분류 시작 *전에* 들어왔거나 또는
  분류 stage 가 그날 비활성.
- 5/29 새 데이터 (incremental re-run 후 mismatch 3,791 → 5) 로 분류 단 1회만 수행 →
  결과 = 125 종목 (트렌드템플릿 통과 + LLM 분류 대상).

즉 **오염된 입력으로 분류된 weekly_classification 행 자체가 존재하지 않음** →
분류 신뢰성 위협 없음 → 재실행 불필요.

## 2. 5/29 분류 → 현재 상태 유지

| may28 (실제 5/29) | 현재 latest | count |
|-------------------|-------------|-------|
| entry | entry | 1 |
| watch | watch | 10 |

모든 entry/watch 가 현재까지 동일 상태 유지 — 다음 trigger/entry_params 사이클에
정상 입력.

## 3. 후속 결과물 영향 범위

| table | 5/27~5/29 row count |
|-------|---------------------|
| entry_params | 0 |
| (signals 테이블 자체 부재 — 별도 모델로 대체) | — |

**후속처리 영향 범위 = 0**. 오염 가능성 있던 분류가 entry_params/trigger 로 흘러갔을
가능성 자체가 없음.

## 4. 잔여 daily_prices ↔ daily_indicators mismatch

```sql
SELECT i.ticker, i.date, p.adj_close, i.adj_close
  FROM daily_indicators i
  JOIN daily_prices p ON p.ticker = i.ticker AND p.date = i.date
 WHERE i.date >= '2026-05-27' AND ABS(p.adj_close - i.adj_close) > 0.01;
```

**결과: 0 행.** Step 1 cleanup 직후 잔존했던 "5 종목" 은 그 후 ohlcv pipeline 의
자연스러운 incremental 재계산 사이클에서 해소된 것으로 추정 (별도 추적 불필요).

## 5. 추가 검증: 5/29 mismatch 종목이 5/27~5/29 분류 배치에 포함되었는가

```
분류 배치 포함 종목 수: 0
```

이는 §4 의 0 행 결과의 자연스러운 따름. 트렌드템플릿 통과군 안에서 GUARD 가 막은
mismatch 종목 = 0.

## 6. Triage 보강 — entry 문턱민감 × 다운스트림 소비

> 사용자 지적 (2026-05-29) 반영. 단순 카운트가 아닌 *문턱 근접* + *다운스트림 흐름* 점검.

### 6-A. 5/29 entry/watch 분류 상세

| symbol | class | conf | pattern | flags |
|--------|-------|------|---------|-------|
| **005850** | **entry** | **0.62** | cup_with_handle | **`extended_from_ma`** |
| 049960 | watch | 0.68 | none | unfavorable_market_context, extended_from_ma |
| 037760 | watch | 0.65 | flat_base | unfavorable_market_context |
| 011560 | watch | 0.65 | none | unfavorable_market_context, **wide_and_loose** |
| 010780 | watch | 0.62 | none | wide_and_loose, volume_contraction_on_advance |
| 198080 | watch | 0.60 | none | wide_and_loose, unfavorable_market_context |
| 033780 | watch | 0.60 | none | **late_stage_base**, wide_and_loose |
| 036570 | watch | 0.60 | none | wide_and_loose, late_stage_base |
| 002810 | watch | 0.58 | cup_with_handle | late_stage_base, volume_contraction_on_advance |
| 019210 | watch | 0.55 | none | unfavorable_market_context, wide_and_loose |
| 017650 | watch | 0.50 | cup_with_handle | unfavorable_market_context, wide_and_loose |

**005850 = 검증자 v2 가 지목한 *바로 그 케이스*** — entry + `extended_from_ma` flag.
Phase 1 의 2-E (faulty handle + extended → hard watch) 적용 시 *entry → watch 강등*
대상 1순위.

037760 (watch, flat_base) = 검증자 v2 의 또 다른 핵심 케이스 — handle 결함 인코딩
결정 (handle_quality vs faulty_pivot) 의 직접 대상.

### 6-B. Confidence 분포 — *역전*

| classification | min | max | avg | n |
|----------------|-----|-----|-----|---|
| entry | 0.62 | 0.62 | 0.62 | 1 |
| watch | 0.50 | 0.68 | 0.60 | 10 |
| ignore | 0.65 | 0.95 | 0.86 | 114 |

`ignore.min(0.65) > entry(0.62)` 이고 `watch.max(0.68) > entry(0.62)`. confidence 는
entry 결정의 *단독* 임계가 아님 — 패턴 + flag 게이트 기반. 그러나 *문턱 민감* 지점이
분명히 존재. Phase 1 의 2-E 게이트 강화 필요성을 정량 근거로 확인.

### 6-C. 다운스트림 소비자 식별 (grep `FROM weekly_classification`)

| 호출처 | 사용 목적 | 영향 |
|--------|-----------|------|
| `kr_pipeline/llm_runner/compute/delta.py:33` | daily_delta 가 *이미 분류된 종목 제외* | ignore 114건이 다음 daily_delta 사이클에 안 들어옴 (정상) |
| `kr_pipeline/llm_runner/compute/payload_lite.py:32` | evaluate_pivot 의 *watch 종목 입력* | **watch 10건이 다음 evaluate_pivot 사이클 진입 — 037760 등 포함** |
| `kr_pipeline/llm_runner/compute/payload_lite.py:156` | entry_params 의 *entry 종목 입력* | **entry 005850 이 다음 entry_params 사이클 진입 — 현재 룰 그대로면 진입 파라미터까지 생성** |
| `kr_pipeline/llm_runner/load.py:54` | 일반 조회 (후속 stage 라우팅) | 정상 흐름 |
| `kr_pipeline/llm_runner/modes.py:41,44` | 모드별 카운트 표시 | UI/운영 표시만 |
| `api/routers/classifications.py:44` | UI 조회 endpoint | 표시만 |
| `api/services/zip_builder.py:110` | verify ZIP 빌더 | 검증용 |

### 6-D. 즉시 권고 — 005850 entry_params 진행 격리

005850 의 *현재* entry 분류는 Phase 1 의 2-E (faulty handle + extended → hard watch
강등) 룰 적용 *전* 의 결정. Phase 1 룰 적용 후 *entry → watch* 로 강등될 가능성 높음.

→ **Phase 1 룰 강화 완료 + 005850 재분류 확정 전까지 005850 에 대해 entry_params 사이클
실행 중단**. 운영 옵션:

(i) 자동: entry_params runner 가 005850 만 skip (코드 변경)
(ii) 수동: Phase 1 완료까지 entry_params 사이클 자체를 *돌리지 않음* (가장 간단)

권고: **(ii) 수동 보류** — Phase 1 이 짧은 사이클로 닫힐 것이고, 005850 외 다른 entry 행도 없으므로 entry_params 사이클 *전체 보류* 부담 작음.

## 7. 결론 + 권고

| 항목 | 상태 |
|------|------|
| 5/28 배치 재실행 필요 여부 | **불필요** — 오염 입력 기반 분류 자체가 없음 |
| 잔여 5 종목 mismatch 후속 조치 | **불필요** — 0 행으로 자연 해소 |
| 후속처리 *현재까지* 진행 | **0** — entry_params 0건 |
| 후속처리 *다음 사이클* 위험 | **있음** — 005850 entry, 037760 등 watch 10건이 *현재 룰 그대로* 다음 사이클에 진입 |
| 즉시 격리 권고 | **entry_params 사이클 보류** (Phase 1 완료 + 005850 재분류 확정까지) |
| GUARD 작동 검증 | 정상 — mismatch 0 행 환경에서 정상 통과 |

→ **Phase 0 종료 가능 + Phase 1 즉시 진입 필요** (entry_params 보류 상태 길어지면 안 됨).

## 8. 후속 모니터링

- (γ) finalized 가드 백로그 (PROJECT_ROADMAP §5 등록 완료) — 동일 partial 모드
  (양 테이블 동일 partial) 가 나타나면 검출 불가, 그때 가드 강화.
- 5/29 분류 1건 entry (특정 종목) — 다음 trigger 사이클에 정상 진입할 것. FREEZE
  되어 있으니 검증 시 분류 시점 입력 재현 가능.
- weekly_classification 의 5/29 분류 125건 — FREEZE 가 weekend.py 통합 *직후*
  분류부터 적용되었는지 확인:

```sql
SELECT COUNT(*) FROM classification_freezes
 WHERE stage = 'weekend' AND frozen_at::date = '2026-05-29';
```

기대: 125 (이번 분류 전체에 대해 freeze 생성). 미만이면 FREEZE 통합 시점 이후
분류분만 적용 — 정상.
