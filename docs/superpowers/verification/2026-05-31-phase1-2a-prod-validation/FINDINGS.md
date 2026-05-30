# Phase 1 2-A 프로덕션 검증 — gate inert 발견 + LLM 비결정성 정량

> **결론**: 후처리-온리 gate (2-A) 는 **LLM 의 비결정적 pattern 라벨 + pivot 에 게이팅**되어, 재실행에서 대부분 inert. 검증자 지목 005850 케이스가 재분류 시 안 잡힘. **Phase 2 (prompt sync) 가 *주 메커니즘*, 후처리는 backstop** 으로 재정의 필요.

검증 시점: 2026-05-30~31. 데이터 5/28 고정 (재적재 없음, 순수 경로 검증). 모든 LLM 호출은 동일 ZIP 입력.

## 1. 실행 경로 (Step 1~4)

- 005850 은 daily_delta 후보에서 **제외** (어제 분류 → 최근 7일 내 → `find_new_tickers` NOT EXISTS). daily_delta 는 "지표 큰 변화"가 아니라 "minervini_pass + 최근 7일 미분류 신규 후보".
- 경로: daily_delta 12 + `weekend.run(ticker="005850")` 강제 = 13건. as_of=2026-05-28.
- **Step 2~3 GUARD**: 13/13 daily_prices↔daily_indicators 정합 통과, 차단 0.
- **Step 4**: 13/13 처리, 크래시 0, fail-soft 정상, freeze 13 저장.

## 2. ⛔ 이상치 — 13건 전부 pattern=none

| | 기대 (5/29 기준) | 실제 (5/30) |
|---|---|---|
| 005850 classification | watch | watch (단 LLM 자체 판정, gate 아님) |
| 005850 confidence | ≤0.50 (Tier2) | 0.62 |
| 005850 pattern | cup_with_handle | **none** |
| 005850 triggered_rules | 2E_tier2 | **None** |

13건 룰 카운트: 2E_tier1=0 / 2E_tier2=0 / 2F=0 (발화 0 — 전부 pattern=none 이라 gate inert).
→ 13건 롤백 완료 (백업 `/tmp/diag/rollback_backup_5_30.json`, freeze 13 진단용 보존). 005850 = 5/29 entry 로 복귀.

## 3. 진단 A — 입력 열화 가설 **반증**

`build_analysis_zip` on_date=5/29 ↔ 5/30 산출물 비교:

| 산출물 | 결과 |
|--------|------|
| daily_chart.png | **바이트 동일** (sha f070b468…). freeze PNG 와도 동일 = LLM 이 본 차트 |
| weekly_chart.png | 바이트 동일 |
| daily.csv | 바이트 동일 |
| payload.json | `.date` 필드 1개만 차이 (5/29 vs 5/30) |

daily_chart.png 시각 확인: 005850 전체 가격사 + cup 구조 완전·정상 렌더. **입력 열화 아님. on_date 렌더 무관.** → pattern=none 은 **LLM 판정 비결정성**.

## 4. 진단 B — 비결정성 정량 (N=5, 동일 입력, DB 미기록)

| run | pattern | pivot | base 기하 | cls |
|-----|---------|-------|----------|-----|
| 1 | none | None | None | watch |
| 2 | none | None | None | watch |
| 3 | cup_with_handle | 71,900 | base_high 73,400 / start 2026-02-27 | watch |
| 4 | none | None | None | ignore |
| 5 | none | None | None | watch |

**집계**: cup_with_handle **1/5** · pivot **1/5** · base 기하 **1/5** · **entry 0/5** (watch 4, ignore 1).

### 핵심 발견

1. **pattern 비결정성 심각**: 동일 입력에 cup_with_handle 1/5 (20%). 80% 는 pattern=none → handle_quality (cup_with_handle 게이팅) **inert**.
2. **entry 0/5**: 5회 모두 entry 아님 (5/29 entry 가 이례적). 2-E 강등은 `classification=='entry'` 일 때만 → 이 5회 중 **2E_tier2 발화 기회 0** (run 3 도 cup_with_handle 이나 이미 watch).
3. **(c) 옵션 (ii) 실현성 빨간불**: base_high·base_start 가 **pattern 라벨과 함께만** 존재 (1/5). pattern=none 일 때 base 기하도 None → "라벨 분리해 base 기하로 폴백" *불가* (폴백 대상 부재). 현 휴리스틱은 `pivot_basis=='handle_high'` + base 필드 의존이라 pivot=None 이면 **휴리스틱도 inert**.

## 5. Phase 2 설계 함의 (정량 근거)

- **재정의**: 후처리 gate 는 LLM 이 (entry ∧ cup_with_handle ∧ pivot=handle_high ∧ extended_from_ma) **전부** 내보낼 때만 2E_tier2 발화. 이 결합은 실측상 희귀 (5회 중 0회). → **2-A 단독으로는 faulty-handle 을 신뢰성 있게 못 잡는다.**
- **옵션 (i) prompt 안정화 = 주 메커니즘**: Phase 2 prompt 가 LLM 이 *처음부터* faulty handle 을 watch + 일관 reasoning 으로 분류하게 해야 함. 후처리는 backstop (이중 보장). prompt 변경 후 비결정성 재측정 필요.
- **옵션 (ii) 라벨 분리 = 큰 스코프**: OHLCV 독립 base/handle 검출 필요 → **패턴 재분류 룰과 정면 얽힘** (별도 backlog). (i) 가 불충분할 때만 착수.
- **handle depth 장중 low vs 종가** (이전 노트) 도 Phase 2 에서 함께 결정.

## 6. 프로덕션 상태

깨끗. 005850 = 5/29 entry/cup_with_handle (복귀). 5/30 실험 13건 롤백됨. B 5회는 DB 미기록. freeze 13건 (5/30) 진단용 보존.
