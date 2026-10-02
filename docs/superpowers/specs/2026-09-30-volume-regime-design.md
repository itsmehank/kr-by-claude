# 거래량 정의 경계(volume_regime) — 봉 단위 저장 + 창 유도 표지 — 설계 spec

작성 2026-09-30. 상태: **사용자 검토 대기**. 근거: #207 회신 21 Q-5c(1·2·3)·회신 20 (ii)·Q-4c.
선행: PR #217(행 문자열 표지 `volume_regime_unverified_#207`, 트립와이어 (4)), PR #219(Q-5a, 머지 대기).

## 1. 목표

2026-09-28 부터 KRX 일별 거래량은 애프터마켓(16:00~20:00) 체결을 합산한 값이다(회신 21: **이를 정의로 수용**, 정규장 복원 폐기).
거래량 규칙은 "최근 봉 ÷ 과거 창 평균/최대" 구조라, 창이 경계(09-28)에 걸치는 동안만 비율이 왜곡된다(분자 새 정의·분모 옛 정의).
이 spec 은 (1) 봉 자체에 정의를 기록하고 (2) 판정마다 계산 창이 경계에 걸치는지(mixed)를 유도해 그때만 표지하며 (3) 표지를
기존 경고 칸에서 분리한다. **판정 규칙·숫자 변경 0.**

## 2. 범위

**포함** — `daily_prices.volume_regime`·`index_daily.volume_regime`·`weekly_prices.volume_regime` 컬럼(소급 채움·수집기 기록) ·
경계일 전일 대비 비교(분배일·FTD) 무효화 · 창 상태 {clean, mixed, new} 유도 함수 · 판정 행 전용 컬럼 `volume_regime_flag`
(분류·트리거·진입·보유 climax/decline 평가) · 기존 문자열 표지 제거·이관 · 웹 표시.

**제외** — 백테스트 금지 구간 해제(회신 21: mixed 구현 후 별건) · 트립와이어 (4) 변경 · 백테스트 격리 테이블(bt_*, delisted_*:
전부 경계 이전) · 정규장 거래량 복원(폐기).

## 3. 결정 사항

| # | 질의 | 결정 | 근거 |
|---|---|---|---|
| D1 | 봉 컬럼 값 | `volume_regime VARCHAR(8) NOT NULL`: 일봉·지수 = `regular`(date < 경계) / `extended`(date ≥ 경계). 주봉 = 구성 일봉이 전부 같으면 그 값, 섞이면 `mixed` | 회신 21 Q-5c 1. 경계 `VOLUME_REGIME_BOUNDARY = 2026-09-28`(data_regimes, 기존 VOLUME_REGIME_UNVERIFIED_FROM 개명) |
| D2 | 채우는 주체 | 수집기(`to_price_rows`/`to_index_rows` → store upsert)가 날짜로 결정. 소급 = 1회 UPDATE(양쪽 DB). 주봉은 집계(`weekly/transform`)에서 유도 | 값이 날짜의 함수라 writer 가 항상 같은 답. 경계 정정 시 상수 1곳 + UPDATE 1회 |
| D3 | 창 상태 유도 | `regime_window_state(bars: 창 안 봉들의 regime 목록) → clean(전부 regular) / new(전부 extended) / mixed(혼재)`. 저장하지 않고 소비처가 자기 창의 봉으로 호출 | 회신 21 Q-5c 2(비저장). 창 길이는 소비처 상수 그대로(일간 50 봉, 주간 50 주, T2/T-D = 앵커~현재) |
| D4 | 표지 대상·형식 | 판정 행 전용 컬럼 `volume_regime_flag VARCHAR(8)`: **mixed 일 때만 'mixed'**, 그 외 NULL. 대상 5 테이블: weekly_classification·trigger_evaluation_log·entry_params·position_climax_evaluations·position_decline_evaluations | 회신 21 Q-5c 2·3. clean/new 는 저장 가치 없음(표지 목적) |
| D5 | 기존 문자열 표지 | `sanity_warnings`/`known_warnings` 에서 `volume_regime_unverified_#207` 제거(26행 + 이후 신규 행), 같은 행 `volume_regime_flag='mixed'` 로 이관. `with_volume_regime` 헬퍼·`warningLabels` 매핑 삭제 | 회신 21 Q-5c 3(칸 의미 분리) |
| D6 | 경계일 전일 비교 | 분배일(`distribution_day`)·FTD(`follow_through`)에서 today/yesterday 의 `volume_regime` 이 다르면 **비교 불가 → 그날 분배일·FTD 아님(NULL 취급)**, `computation_notes` 에 사유 기록. 대상 = 09-25→09-28 1쌍(지수 2종) | 회신 21 Q-5c 1 |
| D7 | 보유 종목 평가 | T2(`t2_max_volume_now`, 주간 거래량 최대)·T-D(`td_max_down_volume_now`, 주간 하락일 거래량 최대)의 창(앵커 주~현재)에 대해 D3 로 상태 유도 → mixed 면 평가 행 flag. **발화 판정 자체는 불변**(억제 아님) | 회신 21 "자동 적용" = 표지 자동 부착. TA-d 는 가격 낙폭 신호라 거래량 무관(정정) |
| D8 | 백테스트 | `BACKTEST_EXCLUDED_FROM` 유지·가드 유지 | 회신 21 마지막 절 |
| D9 | 웹 | flag 배지("거래량 혼재 창 — 09-28 정의 경계, 비율 상향 편향 가능"). **PR-2 = Signals 카드(EntrySignalCard·SignalsPage)**, `known_warnings` 칩에서는 사라짐. **Positions 카드는 PR-3** — position_*_evaluations.volume_regime_flag 는 PR-2 에서 쓰기만 하고 노출은 PR-3 창 유도(T2·T-D)와 함께(#220 리뷰: spec·구현 불일치 정정) | D5 |

## 4. 데이터 모델

```sql
-- (2026-09-30 #207 회신 21 Q-5c) 거래량 정의 경계 — 봉 단위. regular(정규장) / extended(애프터마켓 합산, 2026-09-28~) / mixed(주봉 혼재)
ALTER TABLE daily_prices  ADD COLUMN IF NOT EXISTS volume_regime VARCHAR(8) NOT NULL DEFAULT 'regular';
ALTER TABLE index_daily   ADD COLUMN IF NOT EXISTS volume_regime VARCHAR(8) NOT NULL DEFAULT 'regular';
ALTER TABLE weekly_prices ADD COLUMN IF NOT EXISTS volume_regime VARCHAR(8) NOT NULL DEFAULT 'regular';
-- 판정 행 표지(mixed 창만 'mixed', 그 외 NULL). sanity_warnings/known_warnings 와 의미 분리.
ALTER TABLE weekly_classification        ADD COLUMN IF NOT EXISTS volume_regime_flag VARCHAR(8);
ALTER TABLE trigger_evaluation_log       ADD COLUMN IF NOT EXISTS volume_regime_flag VARCHAR(8);
ALTER TABLE entry_params                 ADD COLUMN IF NOT EXISTS volume_regime_flag VARCHAR(8);
ALTER TABLE position_climax_evaluations  ADD COLUMN IF NOT EXISTS volume_regime_flag VARCHAR(8);
ALTER TABLE position_decline_evaluations ADD COLUMN IF NOT EXISTS volume_regime_flag VARCHAR(8);
```
소급(운영·테스트 양쪽, 멱등): `UPDATE daily_prices SET volume_regime='extended' WHERE date >= '2026-09-28'`(index_daily 동일);
weekly_prices 는 재집계 대신 `week_end_date >= '2026-10-02'` → extended, 09-28 주(week_end 10-02)는 전 일봉이 extended 이므로 mixed 없음
(경계가 월요일이라 혼재 주 0 — 실측 후 확정). 기존 26행: 문자열 제거 + flag 'mixed'.

## 5. 창 상태 유도(D3) — 소비처별 창

| 소비처 | 창 | 유도 입력 | flag 기록 위치 |
|---|---|---|---|
| 분류(weekly_classification) | 주간 C3 50주 + 일간 volume_ratio_50d 50봉 → **둘 중 하나라도 mixed 면 mixed** | payload 의 weekly/daily 봉 regime | store.insert_classification(+backfill 계열) |
| 트리거(trigger_evaluation_log) | 일간 50봉(gate_precompute volume_band 입력 = daily_indicators.volume_ratio_50d) | as_of 기준 최근 50 일봉 regime | store.insert_trigger_log |
| 진입(entry_params) | 일간 50봉(observed_breakout_volume_ratio) | 동일 | store.insert_entry_params |
| 보유 climax(T2) | 앵커 주 ~ 평가 주 | weekly regime | trade_management/held_climax 저장 |
| 보유 decline(T-D) | 앵커 주 ~ 평가 주 | weekly regime | trade_management/held_decline 저장 |

유도 함수(순수): `regime_window_state(regimes: Iterable[str]) -> Literal["clean","mixed","new"]` — 빈 입력은 clean. 창 봉 조회는
각 소비처의 기존 로더가 이미 읽는 프레임에 `volume_regime` 컬럼을 추가해 얻는다(추가 SQL 0 목표).
**자연 만료**: 일간 창은 경계 후 50 거래일(≈2026-12 중순), 주간 창은 50주(≈2027-09)에 mixed 가 사라진다.

## 6. 경계일 비교 무효화(D6)

`market_context/load.py` 가 `volume_regime` 을 함께 읽고, `distribution_day`/`follow_through` 의 today/yesterday 비교에서
regime 이 다르면 해당 일은 분배일 후보·FTD 후보에서 제외(기존 "거래량 ≤ 전일" 과 같은 분기), `computation_notes` 에
`volume_regime_boundary:<date>` 추가. 09-28 재계산 1회(운영 UPDATE 승인 후).

## 7. 작업 분할

- **PR-2 (Q-5c 1·3)**: schema 8 ALTER + 소급 UPDATE · 수집기·주봉 집계 regime 기록 · D6 · 전용 컬럼 + D5 이관(문자열 제거) ·
  flag 초기 규칙 = "as_of ≥ 경계 → mixed"(PR-3 전까지 현행 표지 범위와 동일) · 웹 배지. 테스트: writer 값·주봉 유도·경계일
  비교 제외·이관 멱등.
- **PR-3 (Q-5c 2)**: `regime_window_state` + 소비처 5곳 창 유도로 flag 축소(new → NULL) · 보유 평가 flag · **Positions 카드 배지(D9 잔여)** · 만료 검증 테스트
  (경계 + 50봉/50주 이후 NULL). 완료 후 백테스트 금지 해제 별건 판정 요청.

## 8. 테스트·검증

- 단위: regime 결정(날짜 함수)·주봉 유도(regular/extended/mixed)·window_state·D6 분기·store flag 기록·이관 SQL 멱등.
- 통합: `_run_upsert` 가 extended 로 저장, 지수 동일. 09-28 market_context 재계산에서 분배일·FTD 후보 제외 확인.
- 기대: `uv run pytest tests/` 실패 0 · vitest · build. 운영 적용은 규칙 4(양쪽 DB psql).

## 9. 남기는 것

- 경계 09-28 은 관측 추정(09-14 애프터마켓 개장일과 다름). KRX 문의 회신으로 정정되면 상수 1곳 + UPDATE 1회 + flag 재계산.
- 트립와이어 (4) 임계(1,361)는 extended 정의 하에서 재측정 후보(별건).
