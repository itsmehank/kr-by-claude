# #45 extended 게이트 사전등록 — 재진입 코호트 기준 + 결정론 사전 측정

날짜: 2026-07-21 (측정 **전** 기준 고정) · 준거: plans/2026-07-21-issue45-extended-gate.md §1

## 1. 사전등록 — 3′ 기각(→abort 회귀) 조건

측정 대상: dry-run/실전 trigger_evaluation_log + 매매 결과 (실전 전환 후 누적).

- **재진입 코호트**: go_now 행과 동일 `prior_classification_at` 내에서, 그
  go_now 이전에 `wait_reason='extended_past_buy_range'` 행이 ≥1 존재하는 매수.
- **직행 코호트**: 동일 조건에서 차단 이력 0인 매수.
- **기각 조건** (하나라도 충족 시 3′ 기각, abort 회귀):
  1. 재진입 코호트 스탑 도달률 > 직행 코호트 스탑 도달률 × 1.5
  2. 재진입 코호트 평균 실현 손실 < −9% (하드 기준)
- 질의 규약: `wait_reason` **동등비교만** 허용 (LIKE/자유 텍스트 파싱 금지 —
  사전등록 기준의 가변화 방지, 외부 검토 2차 (iii) 기각 사유).
- 판정 시점: 실전 전환 후 재진입 코호트 표본 ≥20건 도달 시 1차 판정.

## 2. 결정론 사전 측정 — abort 대비 3′ 의 기회이득 크기 (LLM 0회)

목적: "extended 차단 후 같은 주 내 buy zone 복귀" 빈도 실측 — abort 였다면
잃었을 재평가 기회의 규모를 확정. 결과와 무관하게 §1 기준은 불변(참고 측정).

방법 (read-only, 저장 데이터만):
- 모집단: `backtest_classification` 의 entry 행(pivot NOT NULL).
- 각 행에 대해 analyzed_for_date 이후 5거래일(다음 주말 재분류 전) 중
  **첫 트리거일** = close > pivot 인 첫 날.
- 그 첫 트리거일에 `close > pivot × 1.05` (extended-at-trigger) 인 부분집합에서,
  이후 같은 윈도 내 `pivot < close ≤ pivot × 1.05` (buy zone 복귀) 발생 비율.

## 3. 측정 결과 (2026-07-21 실측 — §2 방법 고정 후 실행)

실행: `scripts/issue45_premeasure.py` (kr_pipeline, read-only). 윈도 구현 =
analyzed_for_date(토요일 앵커) + 달력 7일(다음 금요일까지 ≈ 5거래일, 휴장일만큼 축소).

| 지표 | 값 |
|---|---|
| entry 셀(pivot 有) | 14 |
| 주중 첫 트리거 발생 | 8 |
| 트리거일 extended (close > pivot×1.05) | 2 (트리거의 25.0%) |
| 같은 주 buy zone 복귀 | **2 (extended 의 100%)** |

판독: 표본이 작지만(extended n=2) 방향은 명확 — extended-at-trigger 2건 전부가
같은 주 안에 buy zone 으로 복귀했다. abort 채택 시 이 2건의 재평가 기회가 전부
소멸했을 것. HMMS 의 40~60% 되돌림 통계와 방향 일치(본 표본에선 상회). §1 기각
기준은 본 측정과 무관하게 불변 — 이 측정은 기회이득 크기의 참고 실측이다.
