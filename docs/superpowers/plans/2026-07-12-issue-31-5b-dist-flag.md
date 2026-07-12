# Issue #31 — 5b 분배일 flag 전달 + authoritative 선언(방안 a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox 문법.

**Goal:** B(5b)가 종목 분배일을 LLM 자체 재계산으로 판정하던 이중 정의를 해소 — payload의 20일 시계열에 `distribution_day_flag`를 실어 주고, B 프롬프트가 "flag 컬럼이 정답(직접 재계산 금지)"을 선언하게 한다(A §6 관례와 동일).

**Architecture:** `build_for_5b`의 recent_daily_ohlcv_20d 쿼리에 daily_indicators LEFT JOIN(+원소 키 1개) — #18의 build_for_6 선례와 동일 패턴. 프롬프트는 입력 명세에 flag 추가 + authoritative 규약 1문장(게이트 4곳의 "3일/5일/3개" 창·개수 문구는 불변 — 코드 비소비 프롬프트 전용값, 비등재 원칙 유지). 가드: B 프롬프트의 flag 언급+재계산 금지 문구 텍스트 가드 + payload 테스트.

## Global Constraints
- `uv run pytest tests/` 실패 0. 커밋 trailer 금지.
- **checklist 트리거 해당**(프롬프트 임계 텍스트 변경 — 분배일 판정 정의의 재배선) → 아래 맵.
- 동작 성격: 판정 기준의 **단일화**(완화/보수화가 아니라 정의 정합 — LLM 재량 제거). 방향 비대칭 없음.

## 사전 확인된 사실 (main 9d6c7c3 — #31 브리핑 2라운드 검증 완료)
- 5b 쿼리(payload_lite.py:64-79)는 daily_prices 단독, 0-바 제외 조항 보유 — JOIN 추가 시 halt 행은 애초에 리스트에 없어 flag NULL 노출 없음. **정정(리뷰)**: 초기 구간은 distribution_day 말미 fillna(False)라 NULL 이 아니라 False — NULL 은 daily_indicators 행 자체 부재(JOIN miss: 지표 재계산 지연·비유니버스)뿐 → 프롬프트에 null=분배일 아님 규약 명시.
- B 프롬프트 분배일 소비 7곳(게이트 :42·:52·:112·:132 + 서술 :56·:101·:156), 입력 명세 :26, 컷 정의·flag 언급 0건.
- flag는 #20(−0.2% 컷)+#30(전 기간 재계산)으로 규정 정합 완료 — 전달 적기.
- 소비자 영향: evaluate_pivot 러너는 payload 통과만(추가 키 additive), backtest prior_row 주입은 prior_analysis 한정 — 무영향.

## 의존성 맵 (checklist (b))
**변경**: 5b 분배일 판정 입력을 LLM 재계산 → flag 컬럼으로 재배선(임계값 자체 무변경).
**1단계**: `distribution_day_flag`(STOCK_DISTRIBUTION_PCT_DOWN=-0.2 · VOL_MULT=1.0 산출물) → 5b 게이트 판정 입력(신규).
**2단계**: ① B 게이트 4곳(신규 소비) ② A §6 카운트(기존) ③ handle_quality(기존) ④ 표시 계층(기존).
**3단계 (2축)**:

| 고정 상수 | 축1 | 축2 | 책 정합 | 후속 |
|---|---|---|---|---|
| STOCK_DISTRIBUTION_PCT_DOWN=-0.2 | 부분 | **있음** — 이제 B 발동(go_now 3일 조건·abort 5일 3+)도 이 컷이 직접 구동. 컷 변경 시 B 발동률 연동 | PRESERVES | #30의 B-수치 재검토 항목에 "B 게이트 발동률" 연동 명시(checklist 이력에 기재) |
| 프롬프트 전용값 3일/5일/3개 | 불가(시간·개수) | 미미 — 창·개수 불변, 각 날의 판정 정의만 단일화 | EXTENDS | 비등재 원칙 유지(#22 이관 시 코드화) |
| 20d 리스트 0-바 제외 조항 | 불가 | 미미 — halt 행이 리스트에 없어 flag NULL 미노출. NULL 은 JOIN miss(지표 재계산 지연 등)뿐이며 프롬프트 null 규약으로 처리 | EXTENDS | 모니터링(근거: 제외 조항이 선행 필터 + null 규약) |

**소비 경계**: `flag → daily_indicators → build_for_5b 20d 리스트 → B 게이트 go_now/wait/abort → entry_params 직행` (+기존 A/handle_quality 경로 불변).
**게이트 자가 점검**: 맵✓ 3행✓ 축 전칸✓ 있음행 후속 예약✓ 경계 1줄✓.

## Tasks
1. **RED**: ① tests/test_llm_compute_payload_lite.py — 5b 원소에 `distribution_day_flag` 키+값 검증(시드: 최신일 TRUE, 그 외 FALSE) ② tests/test_prompt_trigger_gates.py — B 프롬프트에 flag authoritative 선언 존재 가드(`distribution_day_flag` + "재계산" 금지 취지 토큰).
2. **GREEN**: payload_lite 5b 쿼리 JOIN+키, 프롬프트 입력 명세(:26)와 §3 도입부에 규약 1문장.
3. 구 계획 문서(2026-05-22 :55)에 superseded 추기 1줄 + checklist 이력 append → 전체 회귀 → PR(Closes #31).

## Self-Review: 소비 7곳 커버(정의 단일화는 규약 1곳으로 전 게이트에 적용— 게이트별 문구 수정 불요)✓ / #18 선례 패턴✓ / 비등재 원칙✓ / placeholder 없음✓.
