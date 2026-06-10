# 의존성 맵 — 종목 distribution_day 호출부 SSOT 정렬 (1.25 리터럴 제거)

> threshold-change-checklist (a) 트리거: thresholds.py 상수
> (`STOCK_DISTRIBUTION_VOL_MULT`) 를 **소비하는 계산 로직**
> (`kr_pipeline/indicators/modes.py` 호출부) 수정.

## 변경 내용

`indicators/modes.py` 의 `distribution_day(..., threshold=1.25)` 리터럴 제거
→ SSOT default (`STOCK_DISTRIBUTION_VOL_MULT = 1.0`) 사용.

**성격: 신규 임계 변경이 아니라 2026-05-22 (P0-2) 에 의도된 1.25→1.0 정렬의
미완성 복원.** 당시 volume.py default 는 SSOT 참조로 바뀌었으나(8edc90a)
호출부의 명시적 `threshold=1.25` 가 남아 default 를 무력화했다.
실측: 2026-05-01 이후 `volume_ratio_50d ∈ (1.0, 1.25]` 하락일 4,662행 미플래깅.
prompt `analyze_chart_v3.md` §6 ("volume > 1.0×") · `web/src/data/
thresholds.generated.ts` (1.0) 와 3중 불일치 상태였음.

**시장 레벨 무영향**: market_context 의 distribution 카운트는 별도 경로
(`MARKET_DISTRIBUTION_*` + σ 보정, `market_context/compute/distribution_day.py`)
— 이번 변경과 무관.

## 1단계 (파생 신호)

`STOCK_DISTRIBUTION_VOL_MULT` → `distribution_day_flag` (daily_indicators 컬럼,
`indicators/modes.py` Phase A 에서 생성)

## 2단계 (소비 룰)

`grep -rn "distribution_day_flag" kr_pipeline/ api/` (종목 레벨만):

1. `llm_runner/compute/handle_quality.py:113-114` — handle 구간
   `dist_days >= 1` → `distribution_in_handle` 발화 → phase1 게이트
   (cup_with_handle entry→watch 강등)
2. `prompts/analyze_chart_v3.md` §6 — "4+ distribution days in 25 sessions →
   demote to watch". 컬럼이 authoritative ("Use the `distribution_day_flag`
   series ... as the authoritative per-day signal")
3. 표시/전달 전용 (룰 아님): `api/services/payload_builder.py:182` (payload),
   `csv_builder.py:18` (ZIP CSV), `chart_render.py:142` (차트 마커),
   `api/routers/indicators.py:64` (웹 표시)

## 3단계 (룰 내부 고정 상수) — 2축 판정

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| handle_quality `dist_days >= 1` (하드코딩 1) | 불가 (카운트 임계 — 거래량 배수와 비례환산 무의미) | **있음** — 1.0 복원으로 flag 발동 빈도 증가(미플래깅 4,662행/5주 해소) → handle 구간에 1개만 있어도 발화하므로 handle_quality 강등 빈도 증가. 단 방향은 prompt·SSOT 정의로의 *복원* (1.25 가 비의도 상태) | EXTENDS (O'Neil 은 기관 매도 *존재* 를 보라 함, "≥1" 숫자는 시스템 자체) | **B-수치** — 복원 후 handle_quality 발화율 변화를 cron 누적으로 확인. Phase 2 (i) cup-scoped 재측정(가지별 음성패널)과 같은 창에서 관찰 가능 |
| prompt §6 `4+ in 25 sessions` | 불가 (카운트) | **있음** — flag 빈도 증가 → 4+ 도달 빈도 증가 → LLM watch 강등 증가. 단 §6 의 flag 정의 자체가 1.0× 이므로 4+/25 는 1.0× 전제로 캘리브레이션된 값 — 이번 변경은 그 전제의 복원 | 클러스터=경고 는 PRESERVES (O'Neil), 4/25 숫자는 EXTENDS | **모니터링** (근거: prompt 텍스트(1.0×)와 코드가 이제 일치 — 4+/25 가 전제하던 분포로 돌아가는 것이므로 추가 행동 불요. 발화율 추이는 위 B-수치와 동일 창에서 함께 관찰됨) |
| flag 의 가격 축 (is_down=0% 컷 vs prompt -0.2%) | 가능 (σ) — 단 종목 레벨은 σ 보정 미적용 | 미미 — 이번 변경은 거래량 축만 건드림. 가격 축 차이는 volume.py:97-98 docstring 에 기존 기록된 별건 | PRESERVES (O'Neil -0.2%; 0% 컷은 보수 방향) | 변경 없음 (기존 기록 유지) |

## 소비 경계 (1줄)

`distribution_day_flag → (a) handle_quality → apply_phase1_gates → entry→watch 강등, (b) payload/CSV → analyze_chart_v3.md §6 → LLM watch 강등, (c) 차트 마커·웹 표시 (룰 없음)`

## 검증

- RED→GREEN: `tests/test_indicators_modes.py::test_process_ticker_daily_distribution_flag_uses_ssot_threshold`
  — 파이프라인 경로 기능 테스트 (ratio 1.0978 하락일이 flag=TRUE). 호출부
  리터럴 재유입 시 즉시 RED (기존 단위테스트는 1.25 를 명시 인자로 핀해 못 잡던 갭).
- 기존 테스트: indicators 3종 스윕 22 passed, 실패 1건은 HEAD 동일(사전 존재) stash 검증.
- **production 재계산 필요**: daily_indicators 의 기존 flag 는 1.25 기준 —
  incremental(30일)로는 5/1 이후 미플래깅분 일부만 복구. full-refresh 권장.

## 합격 조건 self-review

1. 의존성 맵 섹션 있음 ✓ 2. 3단계 고정 상수 행 포함 ✓ 3. 축1/축2 전 행 기입 ✓
4. 영향있음 행의 후속: B-수치(행동 예약)/모니터링(근거 명시) ✓ 5. 소비 경계 1줄 ✓
