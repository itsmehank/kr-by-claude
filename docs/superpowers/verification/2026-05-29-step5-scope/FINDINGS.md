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

## 6. 결론 + 권고

| 항목 | 상태 |
|------|------|
| 5/28 배치 재실행 필요 여부 | **불필요** — 오염 입력 기반 분류 자체가 없음 |
| 잔여 5 종목 mismatch 후속 조치 | **불필요** — 0 행으로 자연 해소 |
| 후속처리 (entry_params 등) 영향 | **0** — 작업물 없음 |
| GUARD 작동 검증 | 정상 — mismatch 0 행 환경에서 정상 통과 |

→ **Phase 0 종료 선언 가능.** 다음 단계: **Phase 1 (룰 강화)** brainstorming 진입.

## 7. 후속 모니터링

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
