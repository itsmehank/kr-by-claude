# Phase 2 (i) Threshold 의존성 맵 (2축)

> CLAUDE.md 의무 (threshold-change-checklist). thresholds.py 변경 *선행* 게이트.
> 신규/이관 상수: CUP_DEPTH_MAX_NORMAL_PCT, CUP_DEPTH_MAX_BEAR_RECOVERY_PCT,
> CUP_PRIOR_UPTREND_MIN_PCT, FLAT_BASE_DEPTH_MAX_PCT, FLAT_BASE_PRIOR_UPTREND_MIN_PCT,
> MIN_BASE_WEEKS, HANDLE_DEPTH_BULL_MIN/MAX_PCT, HANDLE_LEGIT_MIN_DAYS, HANDLE_DEEP_RATIO,
> HANDLE_VOLUME_NOT_CONTRACTING_RATIO, HANDLE_MIN_DAYS, BASE_MIN_DAYS, HANDLE_POSITION_LOW_RATIO,
> FAILED_BREAKOUT_K_DAYS, FAILED_BREAKOUT_CONSECUTIVE_BELOW, MEASUREMENT_TOLERANCE_PCT.
>
> 성격: 대부분 *신규* 또는 기존 로컬상수(handle_quality.py / failed_breakout.py)의 *이관* — 값 변화 0
> (동작 불변). 신규 트리 임계(depth/선행상승/핸들길이)만 신규 동작 도입.

## 의존성 (3 depth + boundary)

- **Depth1 파생신호**: cup depth/선행상승/핸들 측정값 → analyze_chart_v3.md §2 트리(Gate0~3)의 cup/none/watch 분기.
- **Depth2 소비룰**:
  - `prompts/analyze_chart_v3.md` §2 결정 트리 (Gate0 선행상승 / Gate1 depth×시장 / Gate2 U·V / Gate3 핸들 길이·품질).
  - `kr_pipeline/llm_runner/compute/handle_quality.py` (HANDLE_DEEP_RATIO / HANDLE_VOLUME_NOT_CONTRACTING_RATIO / HANDLE_MIN_DAYS / BASE_MIN_DAYS / HANDLE_POSITION_LOW_RATIO).
  - `kr_pipeline/llm_runner/compute/failed_breakout.py` (FAILED_BREAKOUT_K_DAYS / CONSECUTIVE_BELOW).
  - `kr_pipeline/llm_runner/gates.py` (monotone-combine — handle_quality 발화 결과 소비).
  - `prompts/verify_analysis_v1.md` (6차원이 동일 임계로 재계산).
- **Depth3 고정상수 (각 소비룰 내)**: handle_quality 의 ratio_a/ratio_b 비교식, cup_bottom→right_rim 윈도우 경계, MIN_BASE_DAYS/HANDLE_MIN_DAYS 계산 가드.
- **Boundary(1줄)**: → analyze_chart_v3.md `classification`(entry/watch/ignore) + `pattern` → `weekly_classification` 테이블.

## 2축 판정표

| 상수 | 축1: 비율조정 가능? | 축2: 영향? | 책 정합 | Action → Follow-up |
|---|---|---|---|---|
| CUP_DEPTH_MAX_NORMAL_PCT 33% | 불가 (책 고정 앵커, O'Neil HMMS Ch.2) | Present (Gate1 cup/none 분기 직접) | PRESERVES | 변경 금지(book-anchor); 시장축과 동시 점검 |
| CUP_DEPTH_MAX_BEAR_RECOVERY_PCT 50% | 불가 (책 예외 앵커) | Present (Gate1 약세회복 분기) | PRESERVES | **핵심 셀** — F3 트리거(market_context downtrend→confirmed_uptrend 60세션 전환) 동시 점검 |
| CUP_PRIOR_UPTREND_MIN_PCT 30% | 불가 (책 앵커, O'Neil) | Present (Gate0 none 분기) | PRESERVES | cup-scoped — flat 20% 와 분리(다패턴 트리 미소비) |
| HANDLE_LEGIT_MIN_DAYS 5 | 불가 (책 ~1주 floor, O'Neil/Minervini) | Present (Gate3 길이 → not_formed 분기) | PRESERVES | HANDLE_MIN_DAYS(3, heuristic 윈도우)와 분리 — 분류 게이트 |
| HANDLE_DEPTH_BULL_MIN/MAX_PCT 8/12% | 불가 (책 앵커, O'Neil p.116) | Present (Gate3 faulty 분기) | PRESERVES | 변경 금지(book-anchor) |
| MEASUREMENT_TOLERANCE_PCT 5% | 가능 (heuristic) | Present (경계 straddle 흡수 — shape 안정성 load-bearing) | MethodDiff(시스템 정책, ±5% 노이즈) | **calibration-target** — 재측정(plan Task 11)이 'depth read 회차간 분산'으로 보정 |
| HANDLE_DEEP_RATIO 0.33 | 가능 (heuristic) | Present (handle_quality 발화) | MethodDiff (책 8~12% 절대치와 reconcile 미완 — trace) | 변경 시 재측정. 이관(값 불변)이라 현 사이클 동작 0 변화 |
| HANDLE_VOLUME_NOT_CONTRACTING_RATIO 0.80 | 가능 | Present (handle_quality 발화) | MethodDiff | 이관(값 불변) — 동작 0 변화 |
| HANDLE_POSITION_LOW_RATIO 0.33 | 가능 (heuristic weight) | Absent — 단독 트리거 아님 (가중 기록만) | MethodDiff | 모니터링: 분류 경계는 50%(상단절반)이고 이 0.33 은 별개 weight — 혼동 금지 |
| HANDLE_MIN_DAYS 3 / BASE_MIN_DAYS 5 | 가능 (heuristic 윈도우) | Absent — 계산 가드(미달 시 skip), 분류 경계 아님 | MethodDiff | 모니터링: 길이 분류 게이트는 HANDLE_LEGIT_MIN_DAYS(5) |
| FAILED_BREAKOUT_K_DAYS 5 / CONSECUTIVE_BELOW 2 | 시간상수 — 비율조정 부적절 | Present (2-F 기록만, 강등 안 함) | MethodDiff | B-수치 (사례 누적 후 재조정). 이관(값 불변) — 동작 0 변화 |
| FLAT_BASE_* / MIN_BASE_WEEKS(flat/vcp/double) | — | Absent — (i) cup-scoped 트리 미소비 (향후 다패턴용 SSOT) | PRESERVES (현 prompt §4 표) | 모니터링: 다패턴 트리 착수 시 활성화 |

## 시장축 교차 점검 (depth × 시장 — 핵심 셀)

- CUP_DEPTH 변경 시 **(정상장 33 / 약세회복 50) 두 셀 + F3 market_context 전환 감지 로직** 동시 점검.
  (한 임계만 바꾸면 정상/약세 분기 정합이 깨짐 — 2축 맵의 load-bearing 셀.)
- `wide_and_loose`(2-B) · `status.py` 와의 상호작용: (i) 는 cup-scoped 라 직접 충돌 없음. 단 2-B 진입 전 재확인(2-B 도 동일 라벨-게이팅).

## 통과 자기점검 (checklist §c 5 게이트)

- [x] 의존성 맵 섹션 존재
- [x] 모든 depth3/소비 상수 행 등재
- [x] 축1·축2 공란 없음
- [x] 축2=Present 행에 action 명시 (공란/무근거 monitoring 없음)
- [x] 소비 boundary 1줄 존재
