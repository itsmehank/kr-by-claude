# 이슈 #55 재측정 — 분배일 정의 4 시나리오 리플레이 (2026-07-21)

- 스크립트: `scripts/issue55_dist_replay.py` (read-only — `default_transaction_read_only=on`,
  upsert/commit 없음). 원자료: `2026-07-21-issue55-dist-replay.csv` (4,452행).
- 구간: 지수별 σ warmup 252세션 이후 전 가용 구간 = **2017-06-20 ~ 2026-07-20,
  KOSPI·KOSDAQ 각 2,226 거래일** (σ fallback 0일 — 전 일자 σ-보정 임계 적용).
- 시나리오: A=classic×6 (현행) / B=classic×5 / C=classic+stalling×6 (#55 신설 정의) /
  D=stalling×5. 임계 파생·FTD 감지·status 사다리는 운영 경로와 동일 함수
  (look-ahead 없음 — σ는 `WHERE date <= as_of`).

## 사전등록 채택 기준 (.loop/LOOP_SPEC.md DC-6 — 측정 전 확정)

6→5 채택 = (i) A→B 라벨 변경 일수 ≤ 3% (지수별) **AND** (ii) 전이 100% 강등
(서열 confirmed_uptrend > rally_attempt > correction > downtrend 하향), 승격 0건.

## 결과

### KOSPI (1001) — 2,226일

| 비교 | 변경 일수 | 비율 | 전이 내역 | 승격(역방향) |
|---|---|---|---|---|
| A→B (6→5, classic) | 188 | **8.45%** | confirmed→correction 110, confirmed→rally 43, rally→correction 35 | 0건 |
| A→C (stalling 신설, 6) | 127 | 5.71% | confirmed→correction 76, confirmed→rally 26, rally→correction 25 | 0건 |
| A→D (stalling+5) | 368 | 16.53% | confirmed→correction 200, confirmed→rally 88, rally→correction 80 | 0건 |

- confirmed_uptrend 일수: A=783 / B=630 / C=681 / D=495
- 룰3(FTD 무효화 correction) 발동 일수: A=149 / B=379 / C=290 / D=542
- co-anchor 경계 (C vs A): dist≥5 일수 1,078→1,388 (+310), dist>3 일수 1,500→1,763 (+263)
- 일 단위: classic 분배일 400, stalling 분배일 54 (**+13.5%**),
  classic 중 상단 절반 마감 74일 (광의 해석 시 제거될 비중 18.5%)

### KOSDAQ (2001) — 2,226일

| 비교 | 변경 일수 | 비율 | 전이 내역 | 승격(역방향) |
|---|---|---|---|---|
| A→B (6→5, classic) | 123 | **5.53%** | confirmed→correction 83, confirmed→rally 17, rally→correction 23 | 0건 |
| A→C (stalling 신설, 6) | 65 | 2.92% | confirmed→correction 49, confirmed→rally 7, rally→correction 9 | 0건 |
| A→D (stalling+5) | 177 | 7.95% | confirmed→correction 130, confirmed→rally 20, rally→correction 27 | 0건 |

- confirmed_uptrend 일수: A=371 / B=271 / C=315 / D=221
- 룰3 발동 일수: A=211 / B=335 / C=283 / D=395
- co-anchor 경계 (C vs A): dist≥5 일수 1,283→1,444 (+161), dist>3 일수 1,679→1,789 (+110)
- 일 단위: classic 분배일 456, stalling 분배일 39 (**+8.6%**),
  classic 중 상단 절반 마감 57일 (광의 해석 시 제거될 비중 12.5%)

## 판정

### 6→5: **채택 보류** (사전등록 기준 미충족)

- 조건 (ii) 는 충족 — 양 지수 전 시나리오에서 승격(역방향) 0건, 전이 3종
  (confirmed→correction / confirmed→rally / rally→correction) 전부 서열 하향 = 방어 조기화.
- 조건 (i) 는 **미충족** — A→B 변경 8.45% (KOSPI) / 5.53% (KOSDAQ) > 3%.
  "라벨 변화 소수" 가 아니라 국면 지형의 유의미한 재편: KOSPI confirmed 일수 −19.5%
  (783→630), 룰3 발동 +154% (149→379).
- 추가 근거 — **이중 조임**: stalling 신설(C)만으로 이미 dist_count 가 상향돼 방어가
  조기화된다 (KOSPI confirmed 783→681, dist≥5 일수 +310). 6→5 를 겹치면 (D) 변경
  16.53%·confirmed −36.8% (783→495) — 신설 정의의 발동률 데이터가 누적되기 전에
  두 조임을 동시 채택하면 개별 효과 귀속이 불가능해진다 (#30 B-수치 관례 위반).
- 결론: `STATUS_DIST_COUNT_FOR_FTD_INVALIDATION = 6` **유지**. stalling 정의가
  production 에 안착·재계산(후속 ops)된 뒤, 신정의 기준 dist_count 분포로 6→5 를
  재측정하는 것이 올바른 순서 (그 시점 기준선 = 본 문서 C 시나리오).

### stalling 신설 (C): 채택 (구현 확정 — 원전 규칙 복원)

- 영향 규모: 라벨 변경 5.71% / 2.92% — LOOP_SPEC A7 의 극단 기준 (>20%) 대비 안전.
- 방향성 100% 보수화 (승격 0건) — 분배 누적 기반 방어의 조기화라는 이슈 목표와 일치.
- co-anchor 경계 영향 (B-수치 기준선): dist≥5 (강등·회복 게이트) 일수 KOSPI +310 /
  KOSDAQ +161, dist>3 (normal_range) 일수 +263 / +110 — LLM 게이트 보수화 방향.

### A2 광의 해석 stakes (참고 측정 — 사용자 후속 결정용)

상단 절반 마감 예외를 classic 하락 분배일에도 적용(광의 해석)하면 기존 분배일의
**18.5% (KOSPI 74/400) / 12.5% (KOSDAQ 57/456)** 가 제거된다 — 방어 *지연* 방향으로
비중이 작지 않음. 본 구현은 협의 해석 (stalling 에만 예외 적용, 근거: 이슈 본문 괄호
구조·IBD 실무·이슈 목표 정합) — 광의 해석 채택 여부는 사용자 결정 사항으로 이관.

## 주의 (측정 한계)

- 비교는 동일 파이프라인 내 A vs B/C/D 상대 비교 — production 저장 라벨과의 절대
  대조 아님 (과거 저장분은 P2-1a 이전 임계 혼재).
- fwd return 등 수익성 지표는 미측정 (이슈 범위 = 라벨 재생 비교).
