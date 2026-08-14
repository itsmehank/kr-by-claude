# #53 국면 사다리 재정렬 + FTD 만료의 가격 기반 무효화 교체 — 설계 (DRAFT)

> 상태: **LOCKED (2026-08-14, 사용자 게이트 승인)** — 독립 검토 2건(11건) + 사후 1회
> 검토(2건) 반영 완료, independent-window prereg §9.2 에 Arm-53 으로 등록됨.
> 이후 수정 금지(독립 구간 결과 열람 후 소급 수정 금지 — prereg 규율).
> 규율: 이 설계는 독립 구간(2017-H2~2020) **결과를 일절 열람하지 않고** 작성됐다
> (2026-07-21 independent-window prereg — arm 소급 정의 금지). 고정 전까지 analyze /
> F-S2 판정 등 독립 구간 결과 열람 금지.

## 1. 목표 (이슈 #53 의 결함 3개)

1. **선점**: 규칙 1(downtrend)·2(correction)가 FTD 규칙 4보다 먼저 매칭 — 깊은 바닥에서
   FTD 가 떠도 confirmed_uptrend 영구 불성립 (`status.py:48-57`).
2. **90일 시간 만료**: `STATUS_FTD_RECENT_DAYS=90` 은 원전(HMMS/TLOND)에 없는 설계값.
   규칙 1에 막힌 동안 만료되면 다음 FTD까지 매수 문 폐쇄.
3. **무효화 반쪽**: 분배 누적 무효화(규칙 3)만 있고 원전의 가격 기반(랠리 저점 이탈)
   무효화 부재.

## 2. 현행 구조 — 설계에 구속력 있는 사실

- **사다리**: `status.py` 6규칙, 위→아래 첫 매칭 즉시 반환(배타적 — 내부 2차 파생 0).
- **`STATUS_FTD_RECENT_DAYS=90` 은 2중 역할 상수** (소비처 4곳):
  ① 사다리 규칙 4·5 의 만료/부재 판정 (`status.py:66,73`)
  ② **FTD 탐지기 검색 범위** (`follow_through.py:33` `lookback_days` 기본값,
     `modes.py:61` "ftd_lookback_days")
  ③ `api/services/payload_builder.py:81` — market_direction_gate 의 rally_attempt
     force_watch 한정어("경과일 ≤ 90 = FTD 존재 취급", #38 재리뷰 유래)
  ④ prompt 텍스트 수동 동기화 1곳 (`analyze_chart_v3.md:69` 만료 문구).
     `evaluate_pivot_trigger_v1.md` 는 **동기화 대상 아님**(검토 1 발견 3) — 90일/만료
     문구가 없고 §3.5 `market_recovery_ok` 는 gate_precompute 코드가 계산(간접 영향만).
  → 만료 제거는 "상수 삭제"가 아니라 **역할 분리** 문제다 (§3 D4).
- **Stage 7 선례 (`kr_pipeline/backtest/market_regime.py`, 사전등록 v3.2 — 기각됨)**:
  규칙 1·2·3 은 그대로 두고 4′만 교체(재정렬 없음 = 이슈가 말한 "반쪽 버전").
  4′ = `ftd_valid AND dist<6` — **close>SMA50 대기 제거 + 시간 만료 제거를 동시 적용**.
  단, 이 파일은 재사용 가능한 인프라 2개를 이미 구현·검증해 뒀다:
  - `ftd_validity_series()`: **가격 기반 무효화** — 랠리 저점(FTD 포함 직전 15세션 최저
    low, `RALLY_LOW_WINDOW=15`) 을 종가가 이탈하면 무효, 새 FTD 발생 시 갱신.
  - FTD 이력 carry-forward 복원: `market_context_daily.last_follow_through_day` 의
    고유 날짜 집합 = 이벤트 로그 (90일 창 내 기록되므로 이벤트 누락 없음)
    → **탐지 lookback 을 늘리지 않고도 90일 밖 FTD 를 기억**할 수 있다.
- 이슈 원문·final-review 의 미검증 조합 = **"재정렬 포함"** — Stage 7 기각이 닫은 것은
  "재정렬 없는 당일 개방"이지 재정렬 자체가 아니다.

## 3. 설계 결정 (D1~D5)

### D1. 선점 해소 방식 — 안 A(재정렬) vs 안 B(조건 우회) → **안 A 채택**

| | 안 A: FTD 규칙을 1·2 앞으로 | 안 B: 1·2 에 "유효 FTD 시 스킵" 가드 |
|---|---|---|
| 결과 동등성 | 기준 | A 와 동등하려면 confirmed 몫 가드 + 1′(분배 무효화, dist≥6 — confirmed 조건과 정반대) 몫 가드 **2종**이 각각 규칙 1·2 에 필요 |
| 구현 | 순서 이동만, 단일 평가 흐름 | 가드 2종 × 규칙 2곳 = 조건식 4중 중복 |
| 유지보수 | 조건 1곳 | 조건 수정 시 다중 동기화 (drift 위험) |
| 가독성 | "FTD 사이클이 가격 급락 판정에 우선" — 책 서사와 일치 | 예외 가드가 규칙 의미를 흐림 |

동일 결과라면 조건 중복이 없는 안 A. (#21 리뷰 교훈 — 상수·조건의 다중 사본은 상호작용
판정을 어렵게 한다.)

### D2. confirmed 조건 — **`close > SMA50` 대기 유지** (v3.2 와의 의도적 차이)

Stage 7 v3.2 는 [재정렬 없음] + [당일 개방(close>SMA50 제거)] + [만료 제거] 중 뒤 2개를
동시 적용해 기각됐다 — 어느 축이 실패 원인인지 분해 불가. #53 arm 은 **Stage 7 대비
한 축 교체**(당일 개방 → 재정렬)로 축 구성을 정리하고, close>SMA50 은 유지한다.
당일 개방 축은 이 arm 이 통과한 뒤 별도 arm 으로만 재검토(§7).
정직한 한정(검토 2 발견 7): **production 기준선 대비로는 [재정렬]+[무효화 교체] 2축
동시 변경**이다 — 실패 시 축 분해를 위해 §7 부가 산출물(국면 분포·1′ 발화·재전환
빈도)을 진단 자료로 강제한다.

### D3. 시간 만료 → 가격 기반 무효화 교체

- FTD 유효성 = `ftd_validity_series` 의미론 그대로: **랠리 저점(FTD 일 포함 직전
  15세션 최저 low) 을 지수 종가가 하회하면 무효**. 새 FTD 발생 시 저점·유효성 갱신.
- 종가 기준(장중 low 아님) 근거: v3.2 사전등록이 이미 종가 이탈로 고정했고, 장중
  일시 이탈에 의한 무효화 노이즈를 줄인다(보수 방향 — 무효화가 덜 예민). 책은 이탈
  기준의 봉 단위를 명시하지 않으므로 EXTENDS.
- 분배 누적 무효화(규칙 1′)는 **임계 수치(dist 6·10일)는 불변**이되, 이력 존재 판정
  (`last_ftd_date is not None`)이 가격-유효성 판정(`ftd_valid`)으로 교체된다(검토 1
  발견 2 — 위치 이동과 별개의 명시적 조건 변경). 이로써 원전의 두 무효화 수단
  (가격·분배)이 모두 구비된다.
- **두 무효화의 수명주기 비대칭(검토 2 발견 2 — 명문화)**: 가격 무효화는 sticky —
  한 번 저점 이탈로 무효화되면 **새 FTD 발생 전까지 영구** 무효. 분배 무효화(1′)는
  non-sticky — `dist_count`(25세션 롤링)가 롤오프로 6 미만이 되면 **같은 FTD 로
  confirmed(2′)가 재발화**할 수 있다. 이 non-sticky 성질은 현행 규칙 3↔4 사이에도
  90일 창 내에서 이미 존재하는 동작이며, 본 설계는 그 지대를 (만료 제거·재정렬로)
  깊은 바닥·90일 밖까지 확장한다 — 의도된 동작인지의 판단은 §7 산출물
  "1′→2′ 재전환 빈도" 실측에 위임한다.

### D4. `STATUS_FTD_RECENT_DAYS` 역할 분리 (2중 역할 해소)

- **사다리 만료 소비 제거** (규칙 4 의 `days_since ≤ 90`, 규칙 5 의 `> 90` 절 삭제).
- **탐지 lookback 은 유지하되 전용 상수로 개명**: `FTD_DETECT_LOOKBACK_DAYS = 90`
  신설(값 불변), `follow_through.py`·`modes.py` 가 이것을 소비. FTD 는 저점 후
  3~15세션 내 발생하므로 90세션 탐지 창은 "신규 이벤트 포착"에 충분 — '기억'은
  탐지 창이 아니라 carry-forward 가 담당한다.
- **FTD 기억 = carry-forward**: production `modes.py` 가 v3.2 방식대로 자신의
  `market_context_daily.last_follow_through_day` 이력에서 최신 FTD 를 복원해
  `last_ftd_date` 로 쓴다(탐지 창 90일 밖이어도 유지, 가격/분배 무효화가 수명 결정).
  스키마 변경 불요.
- `STATUS_FTD_RECENT_DAYS` 상수 자체는 payload_builder ③ 소비를 §6 교체가 끝날
  때까지 잔존시켰다가 최종 제거(한 PR 에서 정리).
- **콜드스타트/재계산(검토 2 발견 4)**: 이력 0건(신규 지수·제네시스·전체 재계산 초입)
  구간은 carry-forward 조회가 빈 결과 → `last_ftd_date=None` 폴백 — 현행과 동일한
  무-FTD 동작. 탐지 창 값이 90 그대로라 기존 production 이력의 이벤트 기록도 무결.

### D5. 규칙 3(분배 무효화)의 위치 — **confirmed 앞, 내용 불변**

무효화 검사는 confirmed 판정보다 반드시 앞이어야 한다(무효화된 FTD 로 상승 확정 방지).
임계 수치는 현행 그대로 두고 위치를 confirmed 와 함께 앞으로 이동하되, 이력 존재
판정 → `ftd_valid` 교체(D3)가 함께 적용된다.
**알려진 의미 변화(수용)**: 깊은 바닥 + 유효 FTD + 분배 6+ 인 날이 현행 "downtrend"
대신 "correction" 라벨이 될 수 있다 — 발생 요건이 좁고(유효 FTD 존재 중 분배 폭풍),
하류 게이트 동작(force_watch)은 두 라벨 모두 동일해 실질 영향은 라벨 표시·국면 통계
집계뿐. 백테스트 산출물에서 발생 빈도를 함께 보고한다(§7).

## 4. 확정 사다리 (안 A — §9 고정 후보)

입력 추가: `ftd_valid: bool` (가격 기반 유효성, D3), `last_ftd_date` 는 carry-forward.

```
1′ (구 규칙 3) FTD 분배 무효화:
    dist_count ≥ 6 AND ftd_valid AND days_since_ftd > 10  → correction
2′ (구 규칙 4, 만료 제거) confirmed_uptrend:
    ftd_valid AND close > SMA50 AND dist_count < 6         → confirmed_uptrend
3′ (구 규칙 1) downtrend:
    close < SMA200 AND SMA50 < SMA200 AND off_high < -15   → downtrend
4′ (구 규칙 2) correction(가격):
    off_high < -10 AND close < SMA50                        → correction
5′ rally_attempt:
    close > SMA50                                           → rally_attempt
6′ fallback:                                                → correction
```

- 5′ 는 현행 규칙 5 의 "(FTD 없거나 90일 초과)" 절이 만료 제거로 무의미해져 규칙 6
  과 통합된 형태(v3.2 의 5′ 과 동일).
- **영향 범위 3분류(검토 1 발견 1 정정)**:
  ① FTD 이력 자체가 없는 기간 — 1′·2′ 미발화, 현행 1→2→5→6 과 **완전 동일**.
  ② 유효 FTD 존재 기간 — 재정렬·만료 제거의 효과 지대(설계 목표).
  ③ **이력은 있으나 가격 이탈로 무효화된 기간** — 현행 규칙 4 는 (90일 내면) 여전히
  confirmed 를 낼 수 있지만 새 사다리는 내지 않는다. 이는 무영향이 아니라 **D3 가
  의도한 변화의 정확한 타깃**(무효 FTD 로 상승 확정 차단)이다. §7 산출물에서 별도
  범주로 빈도를 보고한다.

## 5. 의존성 맵 (threshold-change-checklist 2축 판정)

- **1단계 (파생 신호)**: 사다리 재정렬 + `ftd_valid` 신설 → `current_status` 산출 변화.
  `last_ftd_date` 는 carry-forward 로 수명 연장(90일 창 밖 유지).
- **2단계 (소비 룰)**: `current_status` → gate_precompute `market_recovery_ok`
  (`== confirmed_uptrend AND mkt_dist < MARKET_DIST_DEMOTION_COUNT_25S`),
  payload_builder `market_direction_gate`(force_watch/normal_range), backtest
  `phases.py` 국면 라벨, `analyze_chart_v3.md` §3.5 하드룰, web 용어집/표.
  `ftd_valid` → 사다리 1′·2′ 및 payload_builder 한정어 교체(§6).
- **3단계 (룰 내부 고정 상수) — 2축 판정**:

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| `STATUS_FTD_RECENT_DAYS=90` (만료) | 불가 — 시간 창 | **있음** — 소비 자체가 제거됨 | 방법론차이(책에 없음) → 제거가 정합 회복 | 사다리 소비 제거 + `FTD_DETECT_LOOKBACK_DAYS=90` 신설(탐지 전용, 값 불변). B-수치: arm 백테스트가 제거 효과 판정 |
| `STATUS_FTD_INVALIDATION_DAYS=10` (1′) | 불가 — 일수 | **있음** — 1′ 이 confirmed 앞으로 이동해 발화 순서 변화 | EXTENDS(존재는 책, 숫자는 시스템) | B-수치: arm 백테스트 산출물에서 1′ 발화 빈도·라벨 변화 보고 |
| `STATUS_DIST_COUNT_FOR_FTD_INVALIDATION=6` (1′·2′ 공용) | 부분 — #55 에서 6→5 재측정 보류 이력 | **있음** — 형제 상수(10일)와 같은 AND 절에서 co-fire, 재정렬로 도달 범위가 동일하게 확장(검토 2 발견 1 — 두 상수를 다르게 판정할 근거 없음) | EXTENDS | B-수치: arm 백테스트 산출물에서 1′ 발화 시 dist 분포·구 downtrend/correction 영역 잠식 빈도 보고. 값 자체는 6 고정(#55 보류 유지) |
| `STATUS_DOWNTREND_OFF_HIGH_PCT=-15` (3′) | 가능 — 낙폭 % | **있음** — 유효 FTD 기간에 선점권 상실(2′ 가 먼저) | PRESERVES(현행 값 유지) | B-수치: arm 백테스트의 국면 분포 전후 비교에 포함 |
| `STATUS_CORRECTION_OFF_HIGH_PCT=-10` (4′) | 가능 — 낙폭 % | **있음** — 동상 | PRESERVES | 동상 (같은 산출물) |
| `RALLY_LOW_WINDOW=15` (market_regime 사설) | 불가 — FTD 발생 창(3~15세션)과 연동 | **있음** — `ftd_valid` 의 랠리 저점 정의 | EXTENDS — **값(15)만 우연히 동일, 경계는 상이**(검토 2 발견 3): `FTD_LOW_LOOKBACK_DAYS` 창은 FTD 당일 제외 `[i-15, i-1]`(탐지용), 본 창은 당일 포함 `[i-14, i]`(무효화 기준선용) | 채택 시 SSOT 승격은 **상수 값 공유만** — 각 함수의 윈도 계산 로직은 유지. §7 에 당일 포함/제외 차이 단위테스트 추가 |
| `FTD_PCT_BASE` 등 탐지 임계 | 불가(해당 없음) — 탐지 로직 자체 미변경이라 재정렬 영향 경로 밖 | 없음 — 탐지 로직 불변 | PRESERVES | 변경 없음 (행 명시로 무영향 기록) |
| `MARKET_DIST_DEMOTION_COUNT_25S=5` (소비 룰: market_recovery_ok·confidence_penalty — 사후 검토 발견) | 부분 — 분배일 카운트라 #55 계열 재측정 가능 | **있음** — confirmed 도달 범위 확대로 **6 vs 5 비대칭 지대**(사다리 2′ 는 dist<6 로 confirmed, 회복 게이트는 dist<5 요구·페널티는 ≥5 발화)가 깊은 바닥까지 함께 확장. 상호작용 자체는 현행에도 존재(발생 지대만 확대) | EXTENDS | B-수치: arm 산출물에 "confirmed 인데 회복 게이트 차단(dist=5)" 일수 보고. 값 변경 없음 |
| `MARKET_DIST_NORMAL_MAX_25S=3` (소비 룰: normal_range — 사후 검토 발견) | 부분 — 동상 | **있음** — normal_range(confirmed AND dist≤3)의 성립 가능 지대가 재정렬로 확대(dist 4~5 미규정 갭 보존 포함) | EXTENDS | B-수치: 동일 산출물에 normal_range 성립 일수 전후 비교 포함. 값 변경 없음 |

- **표의 고도 주석**: 상단 7행은 변경 대상 룰(사다리·ftd_valid) 내부 상수, 하단 2행은
  `current_status` 소비 룰(회복 게이트·direction gate) 내부 상수 — 이번 변경의 파생
  신호가 current_status 자체이므로 소비 룰 상수도 3단계에 포함(1회 검토 발견 반영).
- **소비 경계 (1줄)**: `current_status` → analyze_chart_v3 §3.5 force_watch /
  evaluate_pivot §3.5 `market_recovery_ok` → entry/watch 강등·go_now 허용 — confirmed
  진입 시점이 당겨지면 회복 게이트 발화 범위가 확대된다(#53 이슈 본문 그대로).

## 6. 소비처 동기화 목록 (채택 시 구현 범위)

| 소비처 | 변경 |
|---|---|
| `status.py` | 사다리 안 A 로 교체 + `ftd_valid` 파라미터 추가 (+리플레이 주입용 시그니처 유지) |
| `follow_through.py`·`modes.py` | lookback 상수 개명 소비 + carry-forward 복원 추가 |
| `api/services/payload_builder.py:81` | 한정어 `ftd_age ≤ 90` → `ftd_valid` 교체 (#38 재리뷰 취지 "만료 FTD 부재 취급" 은 "무효 FTD 부재 취급"으로 승계) |
| `prompts/analyze_chart_v3.md:69,114-119` | §3.5 만료 문구 → 가격/분배 무효화 문구 수동 동기화 |
| `prompts/evaluate_pivot_trigger_v1.md` | **수정 불요**(검토 1 발견 3) — 만료/90일 문구 없음, market_recovery_ok 는 코드 계산이라 status 발화 시점 변화만 자연 반영 |
| `web/src` 용어집·표 | 국면 정의 서술 갱신 (`scripts/export_thresholds.py` 재실행 포함) |
| `gate_precompute.py` | 코드 변경 없음 (조건식 불변 — 발화 시점만 자연 변화) |
| `kr_pipeline/backtest/phases.py` | 코드 변경 없음 (저장값 조회 전용) |

## 7. 검증 계획 (채택 게이트)

1. **arm 구현은 backtest-local**: v3.2 인프라(`ftd_validity_series`·carry-forward 복원)
   재사용, `variant_ladder_a53()` 신설 — production 무접촉. 합성 데이터 단위테스트만
   (독립 구간 실행 금지 — 결과 열람 규율).
2. **판정 = independent-window prereg §4 그대로**: 포트폴리오층
   (`kr_pipeline/backtest/portfolio.py` `run_portfolio` — `gate_mode` 에 "variant" 슬롯
   실존, Arm-53 배선이 arm 구현 범위)에서 Arm A(gate_mode="prod") vs Arm-53 비교 —
   (i) 개선 방향 재현 AND (ii) MDD 5pp 초과 악화 없음.
   **부가 산출물(축 분해·검토 반영으로 확정)**: ① 국면 분포 전후 비교(§4 영향 범위
   3분류 각각의 일수 — 특히 ③ 가격-무효 기간) ② 1′ 발화 빈도와 발화 시 dist 분포
   ③ D5 라벨 전환 빈도 ④ **1′→2′ 재전환(같은 FTD, dist 롤오프) 빈도**(D3 비대칭
   수명주기 실측).
   단위테스트 추가: 랠리 저점 창의 FTD 당일 포함/제외가 `ftd_valid` 를 가르는 경계
   사례(검토 2 발견 3).
3. 통과 전 production 반영 금지. 통과 시 §6 목록 전체가 한 구현 PR 의 범위
   (프롬프트 동기화·SSOT export 포함).

## 8. §9 부록 고정 후보 요약 (사용자 게이트 대기)

- **Arm-53** = §4 사다리 안 A + D3 가격 무효화(종가 이탈) + D4 carry-forward.
  변경 축 2개(재정렬·만료 교체), 고정 축(close>SMA50 유지, dist 임계 6, 무효화 10일).
- 미결정으로 남긴 것: 없음 — D1~D5 전부 권고안 확정. 사용자 게이트에서 이의 시 해당
  D 항목만 수정 후 재검토.
- 고정 절차: 본 문서 검토 승인 → independent-window prereg §9 에 Arm-53 정의 추가
  → 본 문서 상태를 LOCKED 로 플립.

## 부록 A — 표본 C 재현 판정 결과 (2026-08-14, 1회 개봉 — 본문 비수정 부록)

- A+B 관찰(방향): final_multiple +0.113 · CAGR +2.38pp · MDD +0.87pp 개선
  (`data/backtest/arm53_observe_ab_20260814.json`).
- **표본 C 재현: 실패** (`data/backtest/arm53_judge_c_20260814.json`) —
  armA 0.9681 vs arm53 0.9486 (delta −0.0195), CAGR −0.45pp, MDD −4.34pp
  (가드레일 5pp 내이나 악화 방향). 진입 32→42 — 문은 더 열렸으나 추가 진입이
  손실 기여. **§4 채택 원칙 (i) 방향 재현 불충족 → "독립 구간 미재현" — 재설계(보류).**
- **후기(사용자 승인 2026-08-14, 판정 어휘 정정)**: 최초 기록의 "기각" 표기를 §4
  봉인 어휘의 다른 갈래인 **"재설계(보류)"** 로 정정한다. 근거: ① 두 관측 창의
  부호가 상반(A+B +11.3pp vs C −1.95pp)이고 양쪽 모두 CI 없는 점추정이라
  "가설이 틀렸다"는 반증이 성립하지 않음 ② 방향-재현 기준 자체가 점추정 방향
  체크라는 도구 한계 명기. 채택 불가 상태는 동일하며, 재검증 경로 = 실전 축적
  데이터(신규 독립 구간) + 별도 사전등록.
- 해석(정직): 2021~24 의 +11.3pp 개선이 독립 구간에서 소멸·역전 — 관찰 구간
  과적합을 독립 창이 정확히 걸러낸 사례. 사다리 재정렬의 이론적 정합성(책
  원전)과 별개로, 이 시스템의 신호·게이트 구성 하에서는 실측 이득이 재현되지
  않았다. production 반영 금지 유지. 재설계 재도전 = 별도 사전등록 + 신규
  독립 구간(C 는 본 개봉으로 소모).
