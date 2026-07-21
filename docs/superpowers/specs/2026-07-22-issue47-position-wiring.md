# #47 포지션 wiring 사전등록 — 수동 기록 + 일일 손절 평가 러너 (2026-07-22)

> 스펙 §5(2026-07-13-manage-active-trade.md)가 예약한 wiring 의 이행 사전등록.
> 선행 결정(2026-07-22, 사용자): **포지션 소스 = 수동 기록** — 어댑터 구조
> (source 컬럼)로 브로커 연동 교체 가능하게 설계.

## 1. 범위

- `positions` / `position_stop_evaluations` 테이블 (schema.sql — psql 양쪽 수동 적용 관례)
- 수동 기록 store(open/close/list) + CLI(`python -m kr_pipeline.trade_management`)
- 일일 평가 러너 `run_daily_eval`: open 포지션마다 `evaluate_stop` 호출 →
  평가 로그 기록(멱등: position_id+eval_date) → 래치 영속화 → 매도 신호 Slack
  (`notify_stop_triggered`) — 신규 insert 시에만(중복 알림 방지)
- 조회: API `/api/positions`(+`/{id}/evaluations`) + 웹 `/positions` 페이지
- cron(머지 후 수동 반영 제안): 평일 19:10 — 일봉 체인(18:30, 최근 최대 26분) 종료 후
  `10 19 * * 1-5  cd <repo> && uv run python -m kr_pipeline.trade_management --mode=daily-eval >> $HOME/.kr-by-claude/cron.log 2>&1`

## 2. §3 불변 계약 승계 체크리스트 (준거: 2026-07-13 스펙)

- [x] anchor = `positions.entry_price`(매수 시점 고정) — 러너는 분류 테이블
  (weekly_classification 의 pivot/base_low)을 **조회조차 하지 않음** (구조적 차단,
  회귀 테스트 `test_daily_eval_anchor_is_entry_price_not_classification`)
- [x] `load.py get_active_with_current` 의 `stop_loss=base_low` 정의 재사용 금지 —
  러너는 load.py 미사용
- [x] 래치(breakeven_armed) 영속·단조 True(해제 없음) — positions 컬럼에 운반
- [x] halt 센티널(close≤0)·봉 부재 skip — stop_stack ValueError 규약을 러너가 사전 이행
- [x] 재분류·abort 와 독립 — 분류 상태가 손절 상태를 리셋하지 않음
- [x] 단순 abort 모델 정합 — 전량 매도 신호만(quantity 는 기록용, 판정 무영향)

## 3. 신규 규약 (본 wiring 이 추가)

- **as_of 기본값 = daily_prices 최신 날짜** — cron 이 일봉 체인 뒤에 실행되는 규약과
  결합해 "오늘 적재된 봉"을 평가. 명시 `--as-of` 재실행은 **기존 평가 행이 있는
  날짜만** 안전(ON CONFLICT 멱등) — **미평가 과거일의 신규 평가는 러너가
  `backdated_as_of` 로 거부**(리뷰 반영): 현재 래치의 과거 소급(시대착오)과
  기업행위 후 스케일 불일치를 차단. Slack 알림에는 eval_date 를 명시해 과거일
  알림의 실시간 오독 방지.
- **close 원천 = daily_prices.close(raw)**: 당일 봉의 raw == 당일 adj(수정주가는
  현재 앵커)라 sma_50(adj 기반)과 스케일 일관.
- **수동 기록 모델의 한계와 보강**: 보유 중 기업행위(분할·증자) 발생 시
  entry_price 만 과거 스케일로 남는다 — 러너가 corporate_actions 를 조회해
  `corp_action_after_entry` 경고를 평가 로그에 기록(entry_price 수동 재조정 안내).
  자동 조정은 브로커 연동 어댑터 도입 시 재검토.
- 매도 신호는 **알림·표시까지만** — 주문 집행 없음(수동 매매). 신호 후 처리
  (close_position 기록)는 사용자 CLI.

## 4. 검증 계획

- 단위: tests/test_trade_positions.py 9건(래치 영속·트리거·halt/결측 skip·멱등·
  중복 알림 방지·corp-action 경고·anchor 절연·as_of 기본값) + API 2건 — TDD(RED 선행).
- 실전 확인(머지·cron 반영 후): 첫 포지션 등록 → 다음 거래일 평가 로그 1행·
  runs 성공 확인. go_now 발생 전이라도 러너는 빈 포지션에서 무해(no-op).
