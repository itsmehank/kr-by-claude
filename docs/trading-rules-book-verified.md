# 책-검증 매매 규칙 대장 (Minervini / O'Neil)

전문 에이전트와의 문답(2026-07-02, 총 5라운드)으로 원문 검증된 규칙의 단일 대장.
태그: **[B]** = book-mandated(원문 근거), **[D]** = design-judgment(책 범위 내 수치화),
**[C]** = community-approximation(IBD 관례 등).

> **적용 범위 주의**: 아래 규칙은 현재 **백테스트 포트폴리오 시뮬에서 검증**된
> 상태이며, production 파이프라인 반영 여부는 §4 상충표 참조. production 반영은
> 별도 사전등록 + `docs/superpowers/threshold-change-checklist.md` 의존성 맵 필수.

## 1. 진입·손절

| 규칙 | 값 | 태그 | 근거 |
|---|---|---|---|
| 초기 손절 anchor | **매수가(분할 시 가중평균 매입가)** — pivot 아님 | B | O'Neil HMMS "below your purchase price"; Minervini TLSMW ch.13 "from the average cost of his three buys" |
| 초기 손절 폭 | **8%** (7–8% 상한 범위의 상단) | B/D | O'Neil "7% to 8% is your absolute loss limit"; 8 선택은 종가판정 보상 |
| 절대 상한 | **10%** (uncle point) — 코드 불변식으로 상시 감시 | B | Minervini TLSMW·TTLC §8 |
| "평균 손실 5–6%" | 설정값 아님 — **결과 통계 목표**(재량 조기매도 전제). 명목 스톱으로 오용 금지 | B | TTLC §8 + HMMS(조기매도 재량) |
| 추격 상한 | pivot +5% 초과 진입 금지 | C | 책은 정성적("too far past a correct buy point"), 5%는 IBD 관례 |
| 종가 판정 | 명목 8% 유지, 완화 금지 — 종가 판정 자체가 책(장중 즉시 집행) 대비 이미 완화 | D | HMMS "no need to wait for the day's market close" |

## 2. 보유 관리 (3층 청산 스택 = TTLC §1 contingency 사다리)

유효 손절선 = 매일 `max(①, ②, ③)`, 종가 이탈 시 전량 청산:

| 층 | 규칙 | 태그 | 근거 |
|---|---|---|---|
| ① 초기 | 평균매입가 × 0.92 (상시) | B | §1 |
| ② 본전 방어 | 종가 ≥ 평균매입가 × **1.20** 도달 시 장전(armed) → 이후 평균매입가가 플로어. 장전식 = min(3R, +20%) | B/D | O'Neil HMMS "Any stock that rises close to 20% should never be allowed to drop back into the loss column"; Minervini TLSMW "2–3R에 스톱 상향" |
| ③ 추세 추적 | sma50 ≥ 평균매입가인 날부터 sma50 이 플로어 (Breakeven or Better) | B | Minervini TTLC §9 — 종가 판정까지 원문 명시 |
| 8주 룰 | 진입 21 달력일 내 +20% 도달 → 진입 +56일까지 교체 면제. 56일 후 첫 거래일 ≥ +20% 면 (5B 시) 절반 매도, 미만이면 전량 보유 | B/D | O'Neil HMMS p.269–271 |
| base_low | **포지션 청산 규칙에서 제거**(8% 스톱보다 항상 아래 = 도달 불가 잉여). 신호 감지 게이트(돌파 유효성)에는 유지 | D | 백테스트 진단(스킵 53%) |

## 3. 사이징·포트폴리오

| 규칙 | 값 | 태그 | 근거 |
|---|---|---|---|
| 사이징 | 리스크 역산: **계좌 리스크 1.25%/건 ÷ stop_pct**, 상한 25% (스톱 8% 고정 시 일률 15.625%) | B | Minervini TTLC §8 "backing into risk"; 1.25 하한 선택은 D |
| 동시 보유 | 최대 5종목 | B | O'Neil HMMS p.273–274; Minervini 4–8 |
| 슬롯 만석 교체 | 최약(평균매입가 대비 수익률 최저) ≤ 0% 일 때만 교체. 면제: 당일 진입·8주 면제 | B/D | O'Neil "sell your least attractive stock"; ≤0% 수치는 D |
| 동일일 우선순위 | rs_rating DESC(결측 최하) → 돌파일 거래량배수 | D | 책의 리더십 강조 준용 |
| 피라미딩 | 50/30/20, T2=+2%/T3=+4%(T1가 기준), 추격상한 공유, 미체결 트랜치=자유현금·현금부족 시 소멸 | B/C | O'Neil HMMS pp.274–275(구조 B, 비율 C) |
| 강세 분할매도(5B) | +20% 도달 시(>3주 경과분) 절반 매도 — **꼬리 절단 비용 실측됨**(CAGR 반토막↔MDD 대폭개선), 기본 OFF·시나리오 비교용 | B | O'Neil HMMS p.269 + 8주 예외 |

## 4. production 파이프라인과의 상충표 (2026-07-02 조사)

| # | 위치 | 현재 동작 | 검증 규칙과의 차이 | 판정 |
|---|---|---|---|---|
| 1 | `calculate_entry_params_v2_0.md` §2 | 스톱 anchor = **pivot**, 클램프 [−10,−5], 현재가 기준은 경고만(허용범위 −15%까지) | 검증 anchor = **매수가**, 상한 10%. 추격 +5% 진입 시 매수가 기준 실질 스톱이 최대 −14~15%로 uncle point 초과 가능 | **상충(조건부)** — 추격 진입에서만 발현 |
| 2 | 같은 프롬프트 §3 | 사이징 = 셋업 품질 티어(3~25%), 스톱 거리와 **무관** | 검증 = 리스크 역산(1.25%/stop). 티어 방식은 건별 계좌 리스크가 스톱 폭에 따라 최대 2배 변동 | **방법론 상충** |
| 3 | `load.py:164` (daily 모니터링) | invalidation 판정 stop_loss = **weekly_classification.base_low** (무클램프 구조적 스톱) | 백테스트가 진단한 바로 그 패턴(중앙 13%, 최대 24%). 단 현 용도는 *분류 모니터링*(재평가 트리거)이지 포지션 손절 집행이 아님 | **주의** — 포지션 손절로 오용 시 결함 재현 |
| 4 | 포지션 관리 전반 | `manage_active_trade` 미구현(프롬프트에 out-of-scope 선언만). 8% 초기 스톱·본전 방어·트레일링이 production 에 **부재** | §2 스택 전체가 이식 대상 | **공백** — 실전 가동 전 필수 설계 |
| 5 | `evaluate_pivot_trigger_v1.md` | go/wait/abort 판정만 — 스톱 수치 없음 | 상충 없음 | 정합 |

**처리 방침**: 시스템이 실전 가동 전(cron --dry-run)이므로 즉시 수정 대상 아님.
production 반영 시 각 항목을 별도 사전등록 + 의존성 맵으로 진행. #4(포지션 관리)가
실전 가동의 선결 과제.

## 5. 알려진 편차 (known deviations, 의도적)

- **strength 매도 부재**: 승자 청산이 전적으로 weakness(트레일링) 기반. O'Neil 의
  20–25% 익절·Minervini free roll 은 5B 시나리오로만 존재(기본 OFF). 백테스트
  설계 결정(전량 추세 청산) 승계.
- 종가 체결 근사(장중 집행 불가), 소수 주 허용.

## 6. 변경 프로토콜

이 문서의 규칙 변경 = ① 에이전트 자문(원문 근거 요구) → ② 사전등록(결과 보기 전
고정) → ③ 백테스트 실측 → ④ 본 문서 갱신. production 반영은 추가로 threshold
checklist. 검증 이력: 사전등록 문서들(`docs/superpowers/specs/2026-07-02-*`)과
결과 문서(`backtest-profitability-results.md`)가 원본 기록.
