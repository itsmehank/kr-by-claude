> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# #145 — daily_delta 7일 가드에서 system_disqualify 행 제외: 의존성 맵 (2축 판정)

> 트리거: `RECENT_CLASSIFICATION_WINDOW_DAYS`(thresholds.py:28) **소비 로직**
> (`kr_pipeline/llm_runner/compute/delta.py::find_new_tickers`) 수정 — 체크리스트 (a) 사실 기준 해당.
> 상수 **값(7일)은 불변**, 창이 세는 행의 종류만 축소(`wc.source <> 'system_disqualify'`).

## 변경 요약

가드 취지 = "최근에 **LLM을 실행**한 종목은 건너뛰어 호출 비용 절약"(delta.py 주석의 설계 결정)인데,
현행 조건은 weekly_classification의 **아무 행**을 세서 LLM 미호출인 실격 행(system_disqualify)도
가드를 트리거한다. 실측(072870): 08-26 watch → 08-27 실격 → 08-28 재통과가 09-04까지 제외
(1안 적용 시 09-03). 부수효과 상한 = 재분석 1~6일 앞당김 × 각 1회 호출 (이슈 #145 본문의 정정 분석).

## 1단계 (파생 신호)

`RECENT_CLASSIFICATION_WINDOW_DAYS` → `cutoff = as_of − 7일` → **new_tickers 집합**
(오늘 minervini_pass ∧ 최근 7일 분류 행 없음). 이번 변경 = 집합의 정의 변경:
"최근 행이 실격뿐인 종목"이 집합에 **추가**된다 (그 외 종목 판정 불변 — 보수화도 완화도 아닌 편입 확대).

## 2단계 (소비 룰) — grep 실측

`grep -rn "find_new_tickers|RECENT_WINDOW_DAYS" kr_pipeline api tests` 결과:

- **daily_delta.run** (`daily_delta.py:35`) — 유일한 생산 소비처. new_tickers 순회 → LLM 분류.
- 테스트 mock 2곳(`test_llm_daily_delta.py:67`, `test_llm_runner_freeze_integration.py:105`) — 판정 무관.
- weekend 경로는 이 함수를 쓰지 않음(`load.get_qualifying_tickers`, 7일 가드 없음) — 비소비.

## 3단계 (룰 내부 고정 상수·룰) — 2축 판정

| 고정 상수/룰 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| `RECENT_CLASSIFICATION_WINDOW_DAYS=7` (값 불변, 세는 행 축소) | 불가 (시간 단위) | **있음** — 제외 집합 축소로 평일 호출 증가. 상한은 구조적으로 bounded: 편입 첫 호출이 남기는 LLM 분류 행이 다시 7일을 막아 종목당 ≤ 7일 1회, 실격 행은 멱등이라 반복 적재 불가 | EXTENDS (책 인용 없음, 비용 절약용 시스템 자체 창) | **B-수치** — 적용 후 daily_delta 일별 처리 건수와 "실격발 재편입" 건수(최근 7일 행이 실격뿐인 편입) 관측, 급증 시 재검토 |
| daily_delta UsageLimitError 재실행 멱등 (`daily_delta.py:66` 주석 — "기처리분은 7일 가드가 재실행 시 제외") | 불가 (로직) | **미미** — 기처리분은 **LLM 분류 행**(watch/entry/ignore)을 남기고, 그 행은 여전히 가드 대상. daily_delta는 system_disqualify 행을 생성하지 않으므로(생성처는 disqualify.run뿐) 재실행 멱등성 불변 | EXTENDS | 모니터링 (근거: 제외 대상 축소가 LLM 행에는 미적용 — 멱등의 근거 행 종류가 변경과 교집합 없음) |
| disqualify 멱등 룰 (`disqualify.py` — "최신 분류 종목이 미통과 시 1회, 이미 disqualified 대상 밖") | 불가 (로직) | **미미** — 판정 로직 불변. 재분류가 며칠 앞당겨지면 watch 재부여→재탈락 시 실격 행 빈도가 다소 늘 수 있으나 기록량 문제일 뿐. 같은 날 무한 루프 불가: 실격 조건(당일 미통과)과 후보 조건(당일 통과)이 상호배타 | EXTENDS | 모니터링 (근거: 당일 상호배타로 루프 구조 없음, 빈도 변화는 위 B-수치 관측에 포함) |
| weekend `_already_classified` (source='weekend' 한정, `weekend.py:49`) | 불가 (로직) | **없음** — 원래 daily_delta·실격 행을 참조하지 않음 | EXTENDS | 없음 |

## 소비 경계 (1줄)

`new_tickers → daily_delta LLM 분류 → weekly_classification(source='daily_delta') → 트리거 게이트(evaluate_pivot)·/review streak 화면` — 하류 깊이 추적 안 함.

## 게이트 자체 점검 (체크리스트 (c))

1. 맵 섹션 있음 ✓ 2. 소비 룰 고정 상수 행 등재 ✓ 3. 축1·축2 전 행 기입 ✓
4. 축2 "있음" 행(1행)은 후속 B-수치 예약 ✓, "미미" 행은 근거 병기 ✓ 5. 소비 경계 1줄 ✓
