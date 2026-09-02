# #151 — spread_wide_loose 게이트 제거: 의존성 맵(2축 판정) + 변경 이력

> 트리거: thresholds.py 상수 3종(SPREAD_WIDE_LOOSE_MULT·SPREAD_AVG_WINDOW_DAYS·
> SPREAD_AVG_MIN_ROWS) **제거** + 소비 로직(gate_precompute) + 연동 프롬프트 텍스트
> (evaluate_pivot §3.1 등) 변경 — 체크리스트 (a) 사실 기준 해당.
> ※ 외부 전문가 지시문은 "checklist 대상 아님(임계 변경 아님)"이라 했으나, 리포 규칙은
> "thresholds.py 를 건드렸나"의 사실 트리거이므로 본 맵을 작성한다.

## 변경 이력 (전문가 지시 4항목)

- **제거 사유 = book-fidelity (오귀속 확인)** — 성과 근거 아님. 백테스트 결과와 무관하게 적용.
- **오귀속 2건**:
  1. 베이스 구조 개념(wide-and-loose 타이트함)의 **돌파 당일 봉 전용(轉用)** — 책의 요구는
     돌파 직전 구간(베이스 우측·피봇 영역)에 걸리며, 돌파 당일 봉이 좁아야 한다는 규칙은
     O'Neil·Minervini 어디에도 없음(돌파일은 오히려 크게 움직이는 게 정상이라고 명시).
  2. "이례적으로 넓은 일간 스프레드"의 책 정합적 위치는 **exit/topping 측**(HMMS Ch.10
     Climax Tops 등)이지 매수 게이트가 아님(매도 도메인 규칙의 매수 도메인 전용).
- **성과 근거로 제거한 것이 아님**을 명시한다.
- **저장본 측정치**(돌파류 17건 중 wide=true 9건(53%), corr(거래량 배수, spread 배수)=+0.578)는
  book-mandated 거래량 확대 원칙과의 **상충의 존재 근거일 뿐, 비용 크기의 근거가 아님**.

**사전등록**: 이 변경의 성과 효과는 현 표본(n=17)으로 판정하지 않는다. P0 재수집 완료 후
별도 holdout 사전등록으로만 평가한다.

## 제거 판정 기준 4조건 (전문가 확정, 코드로 재확인)

(a) 제약 추가형·필수 매개변수 아님(제거 후 파이프라인 정상 — suite 1339p) /
(b) 커버리지 손실 없음(베이스 구간은 A `wide_and_loose` §5.2 담당 — D4 불변) /
(c) book-mandated 신호와 방향 충돌(corr +0.578) / (d) 미정의 계산 없음(산출·소비 동시 제거).

## 1단계 (파생 신호)

SPREAD_* 상수 → `spread_ratio_vs_avg`·`spread_wide_loose`(computed_gates) → **제거로 소멸**.
`spread_ratio_vs_avg` 는 판정 소비처가 전부 사라지므로 기록용 잔존 없이 전면 제거
(전문가 지시의 "매핑 보고 후 결정" 항목 — 잔존 시 죽은 필드 + LLM 재량 감점 통로 잔존이
근거. 과거 freeze artifact 는 불변 파일이라 과거 판독에 영향 없음).

## 2단계 (소비 룰) — grep 전수

- evaluate_pivot 프롬프트 9곳(§SSOT 블록·입력 설명·§3 규약 산문·§3.1 go_now/wait·
  abort 20일선 가드 예시·reason 용어집·공통 표준 돌파 검증) — 유일한 판정 소비.
- 결정론 소비 0(evaluate_pivot.py 인터셉트는 extended 게이트뿐). 웹 소비 0(generated
  export만 존재 → 재생성으로 소멸). 과거 감사 스크립트 2개·plans/specs 문서는 기록물 보존.

## 3단계 (룰 내부 고정 상수) — 2축 판정

| 고정 상수/룰 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| §3.1 go_now 잔여 조건(BREAKOUT_VOL_*·close_upper_third·no_dist_3d) | 해당 없음(불변) | **있음** — go_now 필요조건 5→4로 완화, 발동 증가 가능 | 잔여 조건 전부 book 앵커(HTMMIS Ch.2 등) | **사전등록 holdout**(위 명시)으로만 평가 — 현 표본 판정 금지 |
| abort 20일선 가드(TTLC Ch.1) 예시 목록 | 불변 | **미미** — spread 는 '예시' 중 하나였고 룰 발동 조건(sma_21 이탈+거래량+추가 위반)은 불변, dist_days_last_5 등 잔여 예시 존재 | PRESERVES | 없음 |
| wait 조건 잔여(volume wait_band·close_middle_third) | 불변 | **미미** — borderline-wide 항목 삭제는 wait 사유 축소일 뿐 잔여 wait 경로 불변 | EXTENDS | go_now 완화와 동일 holdout 에 포함 |
| A 프롬프트 `wide_and_loose`(§5.2)와 entry_params 소비(−5.5/−4.5 stop·PP floor 3.0) | 불변 | **없음** — D4 로 불변, B 제거와 독립 경로 | PRESERVES(HMMS pp.140-143) | 없음 |

## 소비 경계 (1줄)

`computed_gates → evaluate_pivot LLM 판정(go_now/wait/abort) → trigger_evaluation_log → (go_now 시) entry_params` — 하류 깊이 추적 안 함.

## 게이트 자체 점검

1. 맵 있음 ✓ 2. 잔여 고정 상수 행 등재 ✓ 3. 축1·축2 전 행 기입 ✓
4. 축2 있음 행 후속=사전등록 holdout 예약 ✓ 5. 소비 경계 1줄 ✓

## 별건 (delta attribution — 이 변경에 미포함)

- Q1: entry_params 당일 변동성 반영 — 확인 결과 베이스 구간 변동성(A wide_and_loose →
  absolute stop 강화·PP 사이징 floor)은 반영, **돌파 당일 변동성 직접 반영·staggered stop 부재**
  → 별도 이슈 등록.
- Q2: 최대 일간 스프레드의 exit/topping 측 배치 — 스코프 승인 대기, 착수 금지.
