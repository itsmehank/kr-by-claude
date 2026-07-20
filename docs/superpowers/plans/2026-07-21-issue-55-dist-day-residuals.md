# 이슈 #55 — 분배일 정의 잔여 보강: 의존성 맵 (2축 판정)

> 트리거 사실: `kr_pipeline/common/thresholds.py` 상수 신설
> (`MARKET_STALL_CLOSE_RANGE_POS_MAX`) + 소비 로직 수정
> (`count_distribution_days` stalling 합산, `determine_status` 파라미터화)
> + 임계 변경 후보 (`STATUS_DIST_COUNT_FOR_FTD_INVALIDATION` 6→5 재측정).
> 절차: docs/superpowers/threshold-change-checklist.md (a)~(c).

## 변경 요약

1. **churning/stalling 분배 계수 신설** (HMMS p.209-210): 거래량 > 전일 AND
   0 ≤ Δ% ≤ |σ-보정 dist 임계| (미러 밴드 — 별도 상수 없음, P2-1a ratio 자동 상속)
   AND 일중 range 하단 절반 마감 ((close−low)/(high−low) ≤ 0.5). 상단 절반 마감
   예외는 stalling 판정에만 적용 (classic 하락 분배일은 range 위치 무관 — IBD 실무.
   광의 해석 stakes 는 리플레이 참고 측정, 아래 §재측정).
2. **6→5 재측정**: `scripts/issue55_dist_replay.py` (read-only) 로 전 가용 구간
   4 시나리오 (A=classic×6 현행 / B=classic×5 / C=stall×6 / D=stall×5) 라벨 재생.
   결과 = docs/superpowers/verification/2026-07-21-issue55-dist-replay.md.
   채택 여부는 사전등록 기준 (LOOP_SPEC DC-6) 으로 판정.

## 1단계 (파생 신호)

- `MARKET_STALL_CLOSE_RANGE_POS_MAX` + 미러 밴드 → `is_stalling_day` →
  **`dist_count` (= market_context_daily.distribution_day_count_last_25) 단조 증가**
  (stalling 은 합산만 — 기존 classic 계수는 불변).
- `STATUS_DIST_COUNT_FOR_FTD_INVALIDATION` (6→5 후보) → `current_status` 라벨
  (룰 3 발동 조기화 + 룰 4 confirmed 차단 강화 — 방향 단조: 강등만 가능, 승격 불가).

## 2단계 (소비 룰) — `grep -rn "dist_count\|distribution_day_count_last_25" kr_pipeline api`

| 소비처 | 룰 |
|---|---|
| `kr_pipeline/market_context/compute/status.py` 룰 3·4 | FTD 무효화 correction / confirmed 차단 |
| `kr_pipeline/backtest/market_regime.py` variant_ladder 룰 3·4′ | 동일 상수 import — 6→5 시 자동 추종 (백테스트 로컬 전용) |
| `kr_pipeline/llm_runner/compute/gate_precompute.py:171` | B §3.5 회복 게이트 `mkt_dist < MARKET_DIST_DEMOTION_COUNT_25S(5)` |
| `api/services/payload_builder.py` (§3.5 선계산) | `confidence_penalty = dist ≥ 5`, `normal_range = dist ≤ MARKET_DIST_NORMAL_MAX_25S(3)` |
| `kr_pipeline/market_context/modes.py` `_run_sanity_checks` | dist_count 0~25 범위 가드 (stalling 합산도 25 세션 상한 내 — 영향 없음) |
| prompt `analyze_chart_v3.md` §3.5 / `evaluate_pivot_trigger_v1.md` §3.5 | dist≥5 soft 강등·회복 게이트 텍스트 (값 소비만 — 정의 서술 없음, 수정 불요 grep 확인) |
| `web/src/pages/HomePage.tsx` Distribution tip | 정의 산문 — stalling 반영 갱신 (동반 수리 완료) |

## 3단계 (룰 내부 고정 상수) — 2축 판정

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| `MARKET_STALL_CLOSE_RANGE_POS_MAX = 0.5` (신설) | 불가 (range 내 위치 비율 — σ 와 무관한 기하 조건) | 있음 (stalling 계수 관문 자체) | **book-anchor** (HMMS '상단 절반' 직역) | 신설 본체 — 값 변경 금지 (책 문구 유래) |
| stalling 미러 밴드 (0 ≤ Δ% ≤ \|dist_pct\|, 상수 아님) | 가능 (dist_pct 의 미러 — σ-보정 자동 상속) | 있음 (밴드 폭 = stalling 후보 범위) | EXTENDS (책은 '정체' 만, 수치 미명시) | **B-수치** (발동률 누적 후 밴드 폭 재검토 — 리플레이 실측 stalling +N% 가 기준선) |
| `STATUS_DIST_COUNT_FOR_FTD_INVALIDATION = 6` (룰 3·4) | 부분 (dist_pct 보정 → dist_count 연동 — P2-1a 맵 (d) 기존 행) | **있음** (stalling 합산으로 dist_count 상향 → 룰 3 발동 조기화. 6→5 는 추가 조기화) | EXTENDS (책 3~5 구간, 6 은 시스템 채택 — 책보다 관대) | **재측정 후 판정** (LOOP_SPEC DC-6 사전등록 기준 — 결과는 verification 문서. 채택 시 backtest/market_regime.py 자동 추종·test_common_thresholds 핀 동반 수리) |
| `STATUS_FTD_INVALIDATION_DAYS = 10` (룰 3) | 불가 (시간) | 있음 (bounded — P2-1a 맵 (d) 분석 유효: 룰 3 은 dist≥5 soft 룰과 co-fire) | EXTENDS | **B-수치 유지** (P2-1a 판정 승계 — stalling 합산으로 co-fire 빈도 증가하나 방향 동일·보수화) |
| `STATUS_FTD_RECENT_DAYS = 90` (룰 4) | 불가 (시간) | 미미 (dist_count 변화는 90일 창과 독립) | EXTENDS | 모니터링 (근거: P2-1a 맵 (d) 와 동일 — 창 여유가 충분) |
| `MARKET_DIST_DEMOTION_COUNT_25S = 5` (A §3.5 강등·B 회복 co-anchor) | 부분 (dist_count 연동) | **있음** (dist_count 상향 → dist≥5 일수 증가 → 강등 빈도↑·회복 게이트 통과율↓ — 방향은 보수화만) | EXTENDS (책 '5~6 일이 랠리를 꺾는다') | **B-수치** (리플레이 실측: C vs A 의 ≥5 경계 통과 일수 — verification 문서에 기록. 값 변경 없음 — 이원 구조 유지) |
| `MARKET_DIST_NORMAL_MAX_25S = 3` (A §3.5 normal_range) | 부분 (dist_count 연동) | **있음** (dist>3 일수 증가 → normal_range=false 일수 증가 — full 분류 허용 축소, 보수화만) | EXTENDS (시스템 채택) | **B-수치** (리플레이 실측: C vs A 의 >3 경계 통과 일수 — 동 문서 기록. 값 변경 없음) |
| `MARKET_DISTRIBUTION_LOOKBACK_DAYS = 25` | 불가 (세션 수) | 미미 (stalling 도 동일 25 세션 창 내 계수 — 창 자체 불변) | PRESERVES (HMMS 25 세션) | 유지 |
| `STOCK_DISTRIBUTION_*` (종목 레벨, volume.py) | — | **없음** (별개 함수·별개 정의 — 이번 변경 미접촉, grep 확인) | — | 범위 외 명시 |

## 소비 경계 (1줄)

`distribution_day_count_last_25 (stalling 합산) → market_context_daily → ① status.py 룰 3·4 → current_status ② payload_builder §3.5 선계산 (force_watch/confidence_penalty/normal_range) ③ gate_precompute B 회복 게이트 → LLM 분류·트리거 레이어 단일 경로` (status.py 룰은 배타적 — 내부 2차 파생 0).

## 이원 구조 명시 (이슈 #55 특기)

`STATUS_DIST_COUNT_FOR_FTD_INVALIDATION`(status 라벨, 6) 과
`MARKET_DIST_DEMOTION_COUNT_25S`(A 강등·B 회복 co-anchor, 5) 는 **의도적 별개 상수**.
6→5 채택 시 수치가 우연히 일치하게 되나 **통일(단일 상수화)은 본 이슈 범위 밖** —
소비 레이어가 다르고 (status enum vs LLM 게이트), 통일은 별도 이슈로 결정
(이슈 본문: "통일 여부는 재측정 후 결정"). 리플레이 결과가 그 결정의 입력.

## 재측정·채택 판정

결과와 판정: `docs/superpowers/verification/2026-07-21-issue55-dist-replay.md` 참조
(사전등록 기준 = .loop/LOOP_SPEC.md DC-6: A→B 라벨 변경 ≤ 3%/지수 AND 전이 100%
강등(서열 confirmed>rally>correction>downtrend 하향), 승격 0건).

## 후속 (본 브랜치 범위 밖)

- production `market_context_daily` 히스토리 재계산 ops (#30 전례) — 머지 후 별도 수행
  전까지 과거 저장 행은 구정의 카운트 (신규 incremental 계산분부터 신정의).
- A2 광의 해석 (상단 절반 예외를 classic 하락일에도 적용) — stakes 실측치와 함께
  최종 보고 에스컬레이션, 사용자 결정 시 별도 이슈.
- stalling 밴드 폭·발동률 B-수치 재검토 (위 표).
