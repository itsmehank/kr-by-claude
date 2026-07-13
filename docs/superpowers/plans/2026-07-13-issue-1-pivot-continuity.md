# 이슈 #1 — pivot 재판독 연속성 추적(관측 로그) 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 주간 재분류 시 직전 분류 대비 pivot/base 연속성을 결정론으로 계산해 `weekly_classification.pivot_continuity`(JSONB, 신규 컬럼)에 기록하고, 상태 비저장 재분석 트레이드오프를 docs 로 정식 문서화한다. **판정·분류 동작 변화 0** — 순수 관측(쓰기 전용).

**결정(브리프 재검토 후 채택):** D1=A(연속성 로그 — 임계 게이트 B/베이스 ID E 는 이 관측 데이터 누적 후 재검토), D2=②(docs/pivot-reanalysis-tradeoff.md + weekend/daily_delta 주석에 링크), D3=①(#1 먼저, #3 은 다음 순번).

### 세부 결정
- 비교 대상 = 같은 종목의 (이 행 유효일 이전) 직전 최신 분류 1건 — entry/watch 일 때만 기록, ignore 개재 시 기준선 단절로 NULL (get_active_monitoring 동치 의미론. #39 리뷰 반영: 상한 없는 조회는 --date 재실행 look-ahead, entry/watch 선필터는 재확립 베이스 오계수).
- base_continuity 분류: `same`(base_start_date 동일) / `near`(±10일 이내 — 이슈의 실측 그룹핑 재사용) / `different` / `unknown`(어느 쪽이든 base_start_date 결측). 직전 분류 없으면 컬럼 NULL.
- 10일은 관측 분류용 휴리스틱(판정 무영향, 책 임계 아님) → store 사설 상수 `_BASE_NEAR_DAYS`, thresholds.py 비등재 (D1-A 의 "임계값 변경 없음 — checklist 비대상" 유지).
- 기록 필드: prev_classified_at, prev_pivot_price, pivot_change_pct, base_start_delta_days, base_continuity, pattern_changed, prev_pattern. same-base & pivot 변경 시 log.warning (운영 관측 신호).
- 스키마: `ADD COLUMN IF NOT EXISTS pivot_continuity JSONB` (sanity_warnings 선례) — **production 반영은 psql 수동 적용 필요(kr_pipeline·kr_test 양쪽), PR 본문에 명시**.
- ★재실행 비교 금지 규율과의 관계: 이 로그는 재실행 비교가 아니라 *다른 주(다른 as_of)의 정상 분류 간* 연속성 기록 — 규율 비저촉. docs 에 명시.

## Tasks
1. schema.sql ALTER 추가 → conftest 리셋 경유 테스트 확인.
2. store: `_pivot_continuity(conn, symbol, result, classified_at)` 계산 + insert 컬럼 추가 (TDD: same/near/different/first/결측 5케이스).
3. docs/pivot-reanalysis-tradeoff.md 작성 + weekend.py/daily_delta.py 주석에 링크 1줄.
4. 전체 스위트 → PR(머지 금지) → 코드리뷰 → 반영 → 재검증.
