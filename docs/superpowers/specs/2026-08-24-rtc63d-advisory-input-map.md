# recent_transition_count_63d 자문 입력 — 변경 지점 맵 (12차 ④ 선제출)

> 12차 채택 조건 이행: 구현은 **별도 사이클** — 본 맵 승인 후 착수.
> 태그: design-judgment + **예측력 미확증(탐색 유래)**. 하드 게이트 승격
> 재논의 시 순환성 가드 적용 병기.

## 0. 정의 (계산 규약)

- `recent_transition_count_63d` = 판정 기준일(as-of) 직전 63거래일 내
  `minervini_pass` 의 False→True 전환 횟수 (당일 포함, look-ahead 금지 —
  기준일 이후 행 접근 불가).
- 소스 = `daily_indicators.minervini_pass` 시계열 (실전 지표 표면 — 판정
  당시 라이브 값과 동일 계보).

## 1. 변경 지점 (4곳 — 1버전 1변경 원칙으로 단독 배포)

| # | 지점 | 파일 | 변경 내용 |
|---|---|---|---|
| 1 | 계산 | `kr_pipeline/llm_runner/compute/` 신규 순수 함수 (`tt_marginal.py` 병렬 관례) | pass 시계열 → 전환 카운트. 순수 함수 + 단위 테스트(경계: 63행 정확·기준일 포함·결측 행 무시) |
| 2 | payload | `api/services/payload_builder.py` | A(analyze_chart) payload 에 `recent_transition_count_63d` 필드 추가 — `demotion_trigger` 인근 배치. 값 None 허용(이력 부족 시) |
| 3 | 프롬프트 | `prompts/analyze_chart_v3.md` | **중립 노출(12차 ①)**: 정의 1문장 + 해석 프레임 1문장("경계 진동 = choppy 성격 신호 ↔ 매끈한 추세 선호 — TTLC 앵커")까지만. 지시어·가중치 문구 금지(LLM 재량). "예측력 미확증(탐색 유래)" 명기 |
| 4 | 검증 | `tests/` (payload/프롬프트 정합) | 유령 입력 방지 관례: 프롬프트 언급 필드 = payload 실재 검증 테스트 확장 + sanity_warnings 무영향 확인. `weekly_classification` 스키마 변경 없음(자문 입력 — 저장 판정 구조 불변) |

## 2. 비변경 확인 (범위 밖 명시)

- 게이트·강등·트리거 로직 무변경(백스톱 원칙 비적용 — pocket_pivot_flag 전례
  동형). `thresholds.py` 무접촉(의존성 맵 트리거 없음 — 신규 상수 없음, 63일
  은 §0 정의 상수로 compute 모듈 내 지역 정의).
- B(evaluate_pivot_trigger) payload 는 1차 범위 밖(1버전 1변경 — A 만).

## 3. 관찰 규율 (12차 ②)

- 배포 후 **전후 비교 재실행 무효** — 저장본 드리프트 관찰만(판정 아님):
  weekend 분류의 watch_reason·confidence 분포를 기존 성과 관측 루틴에서
  눈으로 추적. 관찰 창·판정 기준 없음(탐색 유래 자문 입력).

## 4. 게이트

- [x] 13차 맵 승인 (2026-08-24) → 구현 사이클 착수(브랜치·TDD·PR 관례).

## 5. 13차 구현 전 확인 3건 (승인 조건 — 구현 시 이행 의무)

1. **정의 계보**: F→T 전환 정의 = #117 이벤트 정의와 **자구 동일**.
   compute 함수 docstring 에 #117 계보 참조 명기.
2. **관측창 부족 = None**: as-of 직전 관측창이 63거래일 미만이면 **None
   반환(0 금지)** — 신규 상장이 '전환 0회 = 안정 통과'로 위장되는 것 방지.
   경계 테스트(62행 → None / 63행 → 값) 포함. #125 가설(d) 접점.
3. **프레임 자구 회부**: 프롬프트 해석 프레임 1문장은 **배포(머지) 전
   자구만 세션 회부**. 타 항목 재회부 불요.
