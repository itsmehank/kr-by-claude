# #45 extended 상한 게이트 — 구현 계획 (결정 3′: 결정론 wait 기록)

날짜: 2026-07-21 · 결정 확정: 사용자 (외부 red-team 검토 2왕복 후)

## 1. 결정 기록

**채택: 3′ — extended 일은 LLM 없이 결정론 wait 기록, buy zone 복귀일만 LLM 평가.**

- 게이트: 트리거(breakout·breakout_from_watch) 발화일에 `close > pivot ×
  PIVOT_EXTENDED_BAND_MULT(1.05)` 이면 LLM 호출 없이 게이트가 직접
  `decision='wait', wait_reason='extended_past_buy_range'` 를 기록.
- 채택 근거 3종 (외부 검토, 스키마 비용 반영 후에도 유지):
  1. 책 정합 — O'Neil 5% 규칙이 금지하는 것은 *extended 상태의 매수 행위*이지
     신호 폐기가 아님. 승자 주식의 40~60% 가 buy zone 으로 되돌아온다는 HMMS
     통계상 되돌림 재매수는 book-mandated 근거 위에 있음. abort 는 책보다
     과잉 엄격한 design-judgment.
  2. abort 는 가장 강한 돌파(5% 초과 오버슈팅)를 체계적으로 배제하는 선택 편향.
  3. pivot ±20% 재판독 노이즈(이슈 #1 실측) 아래서 abort 는 노이즈 1회가
     1주를 소거하는 비가역 결정. wait 는 1일 가역.
- 검토 왕복 기록: 1차 권고의 "extended_past_buy_range 기존 enum 재사용" 주장은
  사실 오류로 **철회**됨(기존 값은 weekly watch_reason='extended', trigger 로그엔
  wait_reason 컬럼 자체가 없었음). 스키마 신설 비용 반영 후에도 3′ 유지 —
  근거 3종은 비용 무관.
- 어휘 대응 (리네임 없음): `weekly_classification.watch_reason='extended'`
  (주 단위 경로) ↔ `trigger_evaluation_log.wait_reason='extended_past_buy_range'`
  (일 단위 경로). 시간상수가 다른 두 경로의 별개 값.
- 마커 방식: (i) wait_reason 컬럼 신설 채택. (ii) abort_reason 공용화는 기존
  `abort_reason IS NOT NULL` 질의 오염으로 기각, (iii) reasoning LIKE 마커는
  사전등록 코호트 기준의 가변화로 기각. 코호트 질의는 동등비교만 허용.
- **기각(회귀) 조건** — 사전등록(specs/2026-07-21-issue45-extended-gate-prereg.md):
  재진입 코호트 스탑 도달률 > 직행 코호트 × 1.5 OR 재진입 코호트 평균 실현
  손실 < −9% → 3′ 기각, abort 회귀.
- 차선(스키마 변경 불가 제약 발생 시): abort + `abort_reason='extended_past_buy_range'`.
  (ii)/(iii) 은 차선도 아님 — 의미론 깨진 관측보다 온전한 abort 가 낫다.
- 후속 트랙으로 명시 이관: evaluate_pivot_trigger 프롬프트의 extension 이력
  참조 규칙, 종목 레벨 stalling 판별. 단 **payload 필드 3종의 기록·전달은 이번
  범위** (후속 트랙 소급 데이터 확보 — 프롬프트가 참조 전까지 무해).

## 2. 범위 (구현 항목)

1. **스키마**: `trigger_evaluation_log` 에 `wait_reason VARCHAR(60)` NULL 신설
   (schema.sql + 머지 후 kr_pipeline·kr_test psql 적용 관례).
2. **결정론 인터셉트** (`evaluate_pivot.py`): 트리거 타입이 breakout ·
   breakout_from_watch 이고 `close > pivot × PIVOT_EXTENDED_BAND_MULT` 이면
   `_process_one`(LLM) 대신 결정론 wait 행 기록. `insert_trigger_log` 에
   `wait_reason` 선택 파라미터 추가. reasoning 에 결정론 산식
   (close/pivot/extension_pct) 기입 — 조회 기준은 wait_reason 동등비교만.
   - promotion 비대상: §3.3 이 promotion 에서 go_now 전면 금지 — 매수 위험 0.
   - invalidation 비대상: 하향 트리거.
   - dry_run: 기존 관례대로 기록 생략 + 로그만.
3. **복귀일 extension 이력 주입**: LLM 평가 직전, 같은 `prior_classification_at`
   의 `wait_reason='extended_past_buy_range'` 행을 조회해 존재 시 payload 에
   `extension_history` 3종 추가: `max_extension_pct`(기록 close/pivot 재계산 최대),
   `days_extended`(행 수), `return_day_volume_ratio`(오늘 volume/avg_volume_50d).
   이력 없으면 payload 무변경(기존 경로 보존).
4. **사전등록 문서 + 결정론 사전 측정** (LLM 0회): 저장된 백테스트 데이터에서
   "트리거일 extended & 같은 주 내 buy zone 복귀" 빈도 실측 → 기회이득 크기 확정.

## 3. 의존성 맵 (threshold-change-checklist §b — PIVOT_EXTENDED_BAND_MULT 소비처 추가, 값 변화 0)

- **1단계 (파생 신호)**: `PIVOT_EXTENDED_BAND_MULT(1.05)` → extended 판정 3곳:
  A층 §8.5 강등(gates.py) · A층 사후검증 SOFT(store.py sanity_band_mismatch_*) ·
  **신규 B층 결정론 wait**(evaluate_pivot). 신규 2차 파생: `wait_reason` 행 →
  extension_history payload 3종.
- **2단계 (소비 룰)**: `grep -rn PIVOT_EXTENDED_BAND_MULT` 전수 —
  store.py:266(사후검증) / gates.py:87(§8.5 강등) / prompts/analyze_chart_v3.md:51
  (수동 동기화 텍스트, 값 불변이라 프롬프트 수정 없음) / 신규 evaluate_pivot.
- **3단계 (룰 내부 고정 상수) 2축 판정**:

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| `GATE_PROMOTION_PRICE_RATIO`(0.95, §8.5 하단·promotion 발화) | 부분 — 1.05 와 대칭 설계(§8.5) | 미미 — 인터셉트는 상단만 검사, promotion 경로는 §3.3 go_now 전면 금지라 매수 위험 0 | EXTENDS | 모니터링 (근거: promotion 은 어떤 조건에서도 go_now 불가 — 상단 미검사가 매수로 이어질 경로 부재) |
| `GATE_BREAKOUT_VOL_MULT`(breakout 발화 거래량 배수) | 불가 (거래량 배수) | 미미 — 인터셉트는 트리거 *발화 후* 적용, 발화 조건 자체 불변 | PRESERVES | 모니터링 (근거: 적용 순서상 독립 — 발화 집합을 바꾸지 않고 발화 후 처리만 분기) |
| fresh_cross 규칙(breakout_from_watch 의 prev_close≤pivot<close) | 불가 (구조 규칙) | **있음** — 갭업 fresh_cross 가 extended 인터셉트에 선점되어 LLM 정밀판정 기회가 결정론 wait 로 대체됨(의도된 추격 차단) | EXTENDS | **B-수치** — 사전등록 코호트(기각 조건 등록됨)가 이 영향의 강제 재검토 장치 |
| abort 의미론(`_aborted_since_classification` 의 classified_at 단위 skip) | 불가 | **있음** — wait 는 skip 을 만들지 않아 extended 지속 시 매일 결정론 행 누적(LLM 비용 0), 복귀일 LLM 1회. 주말 재분류가 TTL(≤5거래일) | EXTENDS | **B-수치** — 동일 사전등록. 관측: days_extended 분포를 후속 트랙에서 확인 |

- **소비 경계 (1줄)**: `trigger_evaluation_log.wait_reason` → 사전등록 코호트
  질의(동등비교) + 후속 게이트 개선 트랙의 extension 판별 실험 — 프롬프트/UI 는
  이번 범위에서 미소비.

### 리뷰 발견 2건 (머지 전 문서화)

1. **breakout_from_watch 비재발화 비대칭**: bfw 는 fresh_cross(prev_close≤pivot)
   요건 때문에 extended 차단 *다음날* buy zone 복귀해도 재발화하지 않는다
   (prev_close=차단일 종가 > pivot). 복귀 재평가 서사는 **entry 경로 한정**
   (breakout 은 매일 재발화). bfw 차단분은 pivot 하회 후 재크로스 or 주말
   재분류로만 복귀 — 사실상 abort-until-weekend 에 근접. 사전 측정(prereg §3)도
   entry 셀 한정이라 이 비대칭을 반영하지 않음. 후속 트랙 관측 항목:
   bfw 차단→재발화 카운트(코호트 판독 시 bfw 과소표집 오독 방지).
2. **extension 정보의 기존 유입 채널**: payload_lite 가 최근 7일 트리거 행
   (reasoning 포함)을 5b payload 에 이미 주입하므로, 결정론 wait 행의 산식
   텍스트도 다음날부터 LLM 에 노출된다. "프롬프트 참조 전 무해" 판정은
   extension_history *키* 에 대한 것 — 이 기존 채널은 방향 일치(무해)하나
   존재를 명시해 둔다.

## 4. 구현 순서 (TDD, 각 단계 RED→GREEN)

- T1: schema.sql wait_reason + `insert_trigger_log(wait_reason=...)` 관통 저장
- T2: evaluate_pivot 결정론 인터셉트 (breakout/breakout_from_watch × extended →
  wait 기록·LLM 미호출, promotion/invalidation/비-extended 는 기존 경로 불변)
- T3: 복귀일 extension_history payload 주입 (이력 있음/없음 두 경로)
- T4: 사전 측정 스크립트 (`scripts/issue45_premeasure.py`, read-only) + prereg 결과 기입
- 검증: 전체 스위트 0 failed + 독립 코드리뷰 → PR (머지 후 psql 양쪽 적용)
