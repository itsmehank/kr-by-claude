> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# #162 — 시그널 정보를 positions 에 연결 + 추격 매수 표시: 배관 성격·책 근거·runtime 무영향

> 트리거: thresholds.py 값 변경 **0**(PIVOT_EXTENDED_BAND_MULT 재사용, 신규 소비처 = 표시 전용). 판정
> 코드(stop_stack·held_climax·held_decline·sell_half·backtest) diff **0**. schema 변경 → 운영 규칙 4(양쪽 DB
> 적용 완료). governance 인용: 4-3(상수 계약 — 재사용, 값 신설 아님), 4-6(매매 규칙 SSOT = trading-rules).

## 0. 판정(전문가, 2026-09-09)

- 손절 규칙(매입가 × 0.92) **불변** — book-mandated(HMMS 7~8% 매입가 기준). 추격 여부는 기록·표시만,
  기록 거부 없음(수동 체결 모델). 신규 숫자 0 — 5% 임계는 기존 extended 인터셉트 상수 재사용.
- 성격: **배관(plumbing)**. 어떤 판정에도 새 입력이 들어가지 않는다.

## 1. 책 근거(표시 문구의 출처)

- 손절은 **매입가 기준** 7~8%(HMMS Ch.10; trading-rules §손절). 시그널 시점 권고 손절(pivot × 0.92)은
  참고 표기일 뿐 집행 기준이 아니다.
- 추격 한계 pivot +5%(O'Neil/Minervini "pivot 5% 이내 매수") — 코드는 A §8.5 extended 경계
  `PIVOT_EXTENDED_BAND_MULT=1.05` 로 이미 보유. 5% 초과 매수는 정상 되돌림에 8% 손절이 걸릴 수 있다(HMMS)
  → 경고 문구만.

## 2. 변경 파일

| 파일 | 변경 |
|---|---|
| `kr_pipeline/db/schema.sql` | positions +6 nullable 컬럼(signal_at, pivot_price, signal_stop_price, chase_pct[분수], chase_over_limit, signal_gap_days) + 복합 FK `(symbol, signal_at) → entry_params` (entry_params 는 surrogate id 없음 — "entry_params_id" 를 복합 키로 실현). kr_pipeline·kr_test 적용 완료 |
| `kr_pipeline/trade_management/signal_link.py` (신규) | `match_signal`(symbol 의 entry_params 중 signal_at 날짜 ≤ entry_date 최근 행 / `signal_at` 명시 시 그 행, 없으면 ValueError / 매칭 없음 → None), `chase_fields`(entry/pivot − 1, 6자리 반올림 후 strict > 0.05 — 정확히 5% 는 미초과), `link_warnings`(시그널 없음·5% 초과 문구) |
| `kr_pipeline/trade_management/store.py` | `open_position(signal=)` 참고 컬럼 영속, `get_open_positions` 6필드 반환 |
| `kr_pipeline/trade_management/__main__.py` | `--add` 매칭·경고 출력(시그널 없음 / 추격 초과) + `--signal-at` 명시 지정 + 5% 초과 시 `notify_chase_entry` Slack |
| `kr_pipeline/trade_management/runner.py` | `notify_stop_triggered` 호출에 signal_stop_price·chase_pct·chase_over_limit 전달(병기만, evaluate_stop 입력 불변) |
| `kr_pipeline/llm_runner/slack.py` | `signal_note` + `notify_stop_triggered` 병기(시그널 없으면 기존 문구 그대로) + `notify_chase_entry` |
| `api/routers/positions.py` · `web/src/pages/PositionsPage.tsx` | 목록 응답 +6필드, 페이지에 "시그널 손절(참고)"(+gap 일)·"추격"(5% 초과 배지) 열. SignalsPage 무변경 |
| `tests/test_trade_signal_link.py` (+14) | chase 상수 재사용·경계(정확히 5% 미초과, 5.01% 초과, 음수)·null 안전 / 매칭(최근 행·당일 포함·명시 지정·미존재 ValueError·없음 None+경고) / 경고 문구 / store 영속·null / 손절가 불변 회귀(추격 +8% 여도 108×0.92 로 발동, 시그널 손절 92 아님) / 알림 병기 문구·chase 알림 |

**weekend_digest**: `notify_weekend_digest` 는 분류 카운트만 보내며 포지션 내용이 없다 — 병기할 자리가
없어 **무변경**(사실 기록). 포지션 요약을 다이제스트에 넣는 것은 신규 기능이라 범위 밖.

## 3. runtime 무영향 증빙

- 판정 코드 diff 0: stop_stack·held_climax·held_decline·sell_half·backtest/·thresholds.py.
- 백테스트 armA-prod 표본 A+B: #164 배포 후 값과 동일(exits 37 = stop8 19·decline 11·sma50 5·floor 2,
  final 1.1676, MDD −18.96%).
- suite: 기존 1427 + 신규 14 = 1441 예상(회신에 실측).
- production 영향 0(positions 0행). 기존 행은 새 컬럼 전부 NULL(시그널 없음 표시).

## 4. 매칭 규약(사람이 보는 값)

- 매칭 창(N일) 신설하지 않음 — `signal_gap_days` 를 저장해 사람이 판단. `--signal-at` 로 다른 행 지정 가능.
- signal_at 은 TIMESTAMPTZ, 비교는 `signal_at::date <= entry_date`(DB 세션 타임존 기준 날짜).
- chase_pct 는 분수(0.08 = +8%). UI·Slack 은 % 로 표시.
