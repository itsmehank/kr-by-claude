> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# #54 바닥 예외 경로 — RS 선행 hard 게이트 + 파일럿 사이징 — 설계 (DRAFT)

> 상태: **LOCKED (2026-08-14, 사용자 게이트 승인)** — 독립 검토 2건(10건) 반영 +
> §4 판정 구조를 2단(A+B 관찰 → C 재현, F-S2 선례)으로 확정(사용자 결정),
> prereg §9.2 에 Arm-54 로 등록됨. 이후 수정 금지(결과 열람 후 소급 수정 금지).
> 전제: **Arm-53 LOCKED**(2026-08-14, 커밋 6433db6) — 본 설계의 "국면"은 전부
> Arm-53 확정 사다리 기준이다. 규율: 독립 구간(2017-H2~2020) 결과 비열람 작성.

## 1. 목표 (이슈 #54 의 진단 4개)

1. `rs_line_at_52w_high`(RS 라인 선행 신고가)는 매일 계산·저장·프롬프트 주입까지
   되지만 게이트 소비처 0 — advisory 로 묶임 (`prompts/analyze_chart_v3.md:256`).
2. 사이징에 시장 국면 입력 없음 — `entry_params_calc.py` 는 flag 기반 감액만.
3. watch 경로는 confirmed 전 매수 불가 — §3.5 회복 게이트(`market_recovery_ok` =
   confirmed_uptrend 요구)가 rally_attempt 에서 go_now 를 구조적으로 차단.
4. 부수(비대칭): entry(§3.1 breakout) 경로에는 트리거 당일 시장 게이트가 없음.

책 근거: 새 상승 사이클의 주도주는 시장 확인(FTD→confirmed) **전에** 먼저
신고가권에 도달한다(O'Neil 주도주 선행성·Minervini pilot buy). 현행은 이 구간을
전부 버린다.

## 2. 재사용 가능한 기존 인프라 (설계에 구속력 있는 사실)

- **Stage 8 파일럿 하네스 (`kr_pipeline/backtest/portfolio.py` — 기각된 것은 신호,
  하네스 아님)**: `pilot_mode`(v4), `pilot_frac=0.5`(정상 목표의 50%),
  `pilot_stop_pct=0.06`, `pilot_retry_cap=2`(종목·에피소드당), 증액 트리거(FTD 유효
  OR 활성 파일럿≥2 ∧ 합산 미실현>0), ARMS 레지스트리(`armP-pilot` 선례).
  기각된 v4 발동 신호 = `bottoming_series`(15세션 신저가 후 첫 상승 마감 — DOWN
  국면에서 발동). **본 설계는 발동부만 교체**한다.
- 3중 필터 재료는 전부 `daily_indicators` 에 이미 존재: `minervini_pass`(트렌드
  템플릿 — Stage 2 판정의 시스템 내 정의), `rs_line_at_52w_high`,
  **`pct_from_52w_high`**(52주 수정 고가 대비 낙폭, 고가 아래면 음수 —
  `indicators/compute/high_low.py`. 소비 시 부호 반전 불요).
- Arm-53 사다리(LOCKED): rally_attempt = close>SMA50 ∧ (유효 FTD 없음 또는 dist≥6
  로 confirmed 불성립). **주의**: Arm-53 에서 "FTD 직후 + close>SMA50 + dist<6"은
  이미 confirmed 로 흡수된다 — 원 이슈의 "FTD 직후" 문구는 Arm-53 하에서 정상
  경로가 담당하므로, 예외 경로의 몫은 **confirmed 이전 구간**이다.

## 3. 설계 결정 (E1~E6)

### E1. 발동 국면 — **rally_attempt ∧ dist_count < 6** (Arm-53 사다리 기준)

- downtrend·correction 발동은 배제. 근거: Stage 8 v4 파일럿은 DOWN 국면 발동으로
  기각(대박 제외 −5.9%) — 같은 국면에서 신호만 바꿔 재도전하는 것은 기각 실험의
  변형 재시도다. 본 경로는 "시장이 이미 오르기 시작했으나(50일선 위) 아직 확인
  전"인 구간만 담당한다.
- confirmed 에서는 정상 경로가 열리므로 예외 경로 불필요(발동 안 함).
- **분배 경고 국면 배제(검토 2 발견 2)**: Arm-53 사다리에는 "ftd_valid ∧
  close>SMA50 ∧ dist≥6 ∧ FTD 후 ≤10일"인 날이 rally_attempt(5′)로 떨어지는 하위
  사례가 있다 — FTD 직후 기관 매도가 급격히 쌓인 경고 국면으로, 1′ 이 10일 경과
  시 correction 강등을 예약한 상태다. 이 국면에서 파일럿이 발동하면 안 되므로
  발동 조건에 `dist_count < STATUS_DIST_COUNT_FOR_FTD_INVALIDATION(=6)` 을
  명시적으로 추가한다(같은 상수를 파일럿 규칙이 직접 소비 — §5 행 추가).

### E2. 3중 하드 필터 (전부 결정론, as-of 지표 — AND 결합)

| # | 조건 | 지표 | 성격 |
|---|---|---|---|
| ① | 종목 Stage 2 | `minervini_pass = TRUE` | 기존 지표 소비(트렌드 템플릿 = 시스템의 Stage 2 정의) |
| ② | RS 라인 선행 신고가 | `rs_line_at_52w_high = TRUE` | **advisory → 이 경로 한정 hard 승격**(이슈 본문의 "선행 신고가 신호 한정" 그대로 — 전역 하드 필터 승격 아님) |
| ③ | 신고가 근접 밴드 | `pct_from_52w_high` ∈ **[−15.0, −5.0]** | 신설 상수 2개(SSOT 등록: `PILOT_OFF_HIGH_MIN_PCT=-15.0`, `PILOT_OFF_HIGH_MAX_PCT=-5.0`) |

- ③ 의 상한을 0%가 아닌 −5%로 두는 이유: 신고가 0~5% 이내는 pivot 돌파 임박
  구간으로 정상 경로(§3.1/§3.5)가 담당 — 예외 경로는 "거의 회복했지만 아직 돌파
  전" 종목을 겨냥한다. 5~15% 수치는 이슈 원문 그대로(EXTENDS — 책은 "신고가
  부근"만 요구, 수치는 시스템 설계값).

### E3. 경로 메커니즘 — §3.5 회복 게이트의 파일럿 분기

- 현행: `market_recovery_ok = (status == confirmed_uptrend ∧ mkt_dist < 5)` 아니면
  watch 경로 go_now 차단.
- 신설: `pilot_eligible = (status == rally_attempt) ∧ 3중 필터 전부 통과`.
  `market_recovery_ok == False` 라도 `pilot_eligible == True` 면 go_now 허용하되
  **pilot 파라미터**(E4)로 진입. 게이트 판정은 결정론 선계산(gate_precompute 위치)
  — LLM 재량 없음.
- **entry/watch 비대칭(목표 4) 처리**: Arm-54 백테스트에서는 트리거 시뮬 층이
  entry·watch 양 경로에 동일 게이트(정상 = market_recovery_ok, 예외 = pilot_eligible)
  를 적용해 비대칭을 해소한 상태로 측정한다. production 반영 시 entry 경로 게이트
  신설이 구현 범위에 포함된다(§6) — 별도 이슈로 미루지 않는다(이슈 본문의 "일관성
  함께 정리" 요구).
- **트리거 평가 상속(검토 2 발견 1 — #45 추격 상한)**: 파일럿 경로도 §3.1/B 트리거
  평가(추격 상한 `PIVOT_EXTENDED_BAND_MULT` 인터셉트 포함)를 **그대로 통과해야**
  go_now — 파일럿이라고 인터셉트 예외를 주지 않는다(이슈 #54 본문의 "#45 동일 적용
  필요" 요구 그대로).

### E4. 파일럿 사이징 — 정상 목표의 **50%** + 파일럿 스톱

- `pilot_frac = 0.5` 재사용(v4 prereg 값 — 이슈 범위 25~50% 의 상한). 근거: 선별이
  3중 하드 필터로 강해 과소 배팅 손실이 더 크고, 검증된 상수 재사용이 비교
  가능성을 준다. 25% 하향은 백테스트 실패 시 재설계 옵션으로만 남긴다.
- `pilot_stop_pct = 0.06` 재사용(정상 7~8%보다 타이트 — 시장 미확인 구간 보수).
- **flag 감액과의 관계(#80 동결 불변)**: 파일럿 50%는 시장 국면 오버레이로, 기존
  flag 배수(×0.7/×0.5)와 **곱연산**. #80 의 티어·배수 2층 구조는 건드리지 않는다
  (동결 유지 — 재개봉 조건 미충족). *(2026-09-08 #153 으로 #80 구조 자체가 superseded — 기록, #155)*
- **하한 클램프 상호작용(검토 2 발견 4 — 명문화)**: `entry_params_calc` 는 최종
  사이즈를 `ENTRY_WEIGHT_PCT_MIN=3.0 ~ MAX=25.0` 으로 클램프한다. 파일럿 곱은
  클램프 **전** 적용이며, 곱 결과가 3.0 미만이면 floor 로 수렴해 파일럿 차등이
  소거되는 사례가 생긴다(예: fallback 7.0 × unfavorable 0.5 × pilot 0.5 = 1.75 →
  3.0). 단, E1 이 발동을 rally_attempt 로 한정하므로 `unfavorable_market_context`
  (×0.5) 와의 중첩 빈도가 관건 — floor 도달 빈도를 §7 B-수치로 보고하고, 과다 시
  재설계 옵션(파일럿 전용 floor)을 연다.

### E5. 연속 손절 자동 잠금 — 전역 N=3 + 기존 에피소드 캡 병존

- 기존 `pilot_retry_cap=2`(종목·에피소드당)는 유지.
- 신설: **전역 잠금** — 파일럿 경로 청산이 손실(스톱 아웃)로 **연속 3회** 누적되면
  경로 전체 잠금. 근거: 오닐의 시험 매수 후퇴 관행(파일럿 2~3회 실패 = 시장 판단
  오류 신호) — EXTENDS(수치 3은 시스템 설계값, SSOT: `PILOT_CONSEC_STOP_LOCK=3`).
- **잠금 해제 = 새 FTD 발생 단독**(검토 2 발견 3 반영 — confirmed 전환 조건 제거).
  근거: 사다리엔 이력 지속(hysteresis) 장치가 없어 close 가 SMA50 을 하루 웃도는
  노이즈로 confirmed 가 하루 성립했다 되돌아올 수 있다 — "시장 판단 오류가
  정정됐다"는 증거로는 이벤트성 신호(새 FTD)만 인정한다. §7 단위테스트에 하루
  whipsaw 사례를 고정한다.
- **판정 재료(검토 1 발견 2 + 검토 2 발견 5 — "스키마 변경 불요" 철회)**: 현재
  `positions` 는 파일럿 식별 컬럼·청산가·손익 컬럼이 없고 `close_reason` 은 자유
  텍스트이며, 스톱 트리거 감지(`position_stop_evaluations`)와 실제 청산 기록이
  코드상 연결돼 있지 않다 — 조회만으로는 "파일럿 경로의 손실 청산"을 판정할 수
  없다. 따라서 **production 채택 시 스키마 변경을 구현 범위로 인정**한다(§6):
  `positions.entry_kind`('normal'|'pilot') + `exit_price`(청산가) + 구조화된 청산
  사유(`is_stop_loss BOOLEAN` 또는 enum). 백테스트는 영향 없음(시뮬 내부 청산
  기록으로 결정론 재계산).

### E6. 판정 층위 — LLM 무관여

- 3중 필터·발동 국면·잠금 전부 결정론 선계산. LLM 분류(verdict)와 pivot 은 기존
  것을 그대로 소비 — 본 경로는 "이미 watch 인 종목의 go_now 허용 조건"만 넓힌다.
  분류층 프롬프트 변경 없음(§3.5 게이트 문구만 동기화, §6).

## 4. Arm-54 정의 (§9.2 고정 후보)

- **Arm-54 = Arm-53 사다리 + 파일럿 예외 경로(E1~E5)**.
- **비교 설계(효과 분리)**: Arm-53 vs **Arm-53+54** — 파일럿 경로의 한계 효과만
  측정한다(Arm A 대비는 #53 몫으로 이미 분리).
- **판정 구조 — 2단(관찰→재현), F-S2 선례 승계(사용자 결정 2026-08-14)**: prereg §4
  의 "방향 재현"은 2021~2024 관측 방향의 재현을 요구하는데 이 3중 필터 버전은 그
  구간 실행 선례가 없다(검토 2 발견 8). 선례 부재를 "기준 교체"가 아니라 **관찰
  단계 신설**로 해소한다 — F-S2 트랙(정의 봉인 → A+B 관찰 → C 재현)과 동일 규율:
  1. **정의 봉인(본 §9.2 고정)** — 관찰 전에 잠가 A+B 결과 기반 튜닝을 차단.
  2. **관찰(look): 표본 A+B, 2021~2024(비보호 구간)** — Arm-53 vs Arm-53+54 결정론
     리플레이. 관찰 통과 기준: (i) 파일럿 한정 mean excess_net > 0 AND
     (ii) 포트폴리오 final_multiple 이 Arm-53 대비 악화하지 않음.
     **미통과 시 Arm-54 는 C 개봉 없이 기각**(C 는 Arm-53 판정용으로만 개봉 —
     싼 조기 기각).
  3. **재현 판정: 표본 C, 2017-H2~2020** — 관찰에서 확정된 개선 방향(해당 지표)이
     재현되고 AND MDD 가 Arm-53 대비 5pp 초과 악화하지 않을 것(prereg §4 문언
     원형 복원). 실패 시 기각(재설계 옵션: pilot 25%·전용 floor — 재도전은 별도
     사전등록 필요).
  - 순서 규율: C 개봉은 두 arm 모두 봉인 + Arm-54 관찰 완료 후 1회.
- 파일럿 전용 산출물: 파일럿 진입 수·승률·평균 손익, 전역 잠금 발동 횟수·잠금 중
  놓친 진입 수, 에피소드 캡 도달 분포, 3중 필터 각각의 단독 탈락 기여도.

## 5. 의존성 맵 (threshold-change-checklist 2축 판정)

- **1단계 (파생 신호)**: 신설 `pilot_eligible` ← (Arm-53 status, minervini_pass,
  rs_line_at_52w_high, 52주 고가 낙폭, 신설 상수 3개). 신설 `pilot_lock` ← 파일럿
  청산 이력.
- **2단계 (소비 룰)**: `pilot_eligible` → §3.5 회복 게이트 분기(go_now 허용) +
  사이징(E4). `pilot_lock` → 발동 차단. 기존 `market_recovery_ok` 로직은 불변.
- **3단계 (룰 내부 고정 상수) — 2축 판정**:

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| `PILOT_OFF_HIGH_MIN/MAX_PCT = −15/−5` (신설, E2③) | 가능 — 낙폭 % | **있음** — 필터 통과 모집단을 직접 결정 | EXTENDS(책은 "신고가 부근"만) | B-수치: arm 산출물에 밴드 경계 분포(통과 종목의 낙폭 히스토그램) 보고 |
| `PILOT_CONSEC_STOP_LOCK = 3` (신설, E5) | 불가 — 횟수 | **있음** — 잠금 빈도 결정 | EXTENDS(관행 2~3회의 상한) | B-수치: 잠금 발동 횟수·잠금 중 놓친 진입의 사후 성과 보고 |
| `pilot_frac = 0.5` (portfolio 기존, E4) | 가능 — 비율 | **있음** — 파일럿 진입 규모 직접 결정 | EXTENDS(v4 prereg 승계) | 값 재사용 — B-수치: 파일럿 전용 산출물(실효 사이징 분포) |
| `pilot_stop_pct = 0.06` (portfolio 기존, E4) | 가능 — 비율 | **있음** — 파일럿 손절 폭·연속 손절 잠금(E5) 발동 빈도에 직결 | EXTENDS(v4 prereg 승계) | 값 재사용 — B-수치: 파일럿 스톱 아웃 빈도 보고 |
| `pilot_retry_cap = 2` (portfolio 기존, E5 병존) | 불가 — 횟수 | **있음** — 에피소드당 재진입 상한 | EXTENDS(v4 prereg 승계) | 값 재사용 — B-수치: 캡 도달 분포 (검토 2 발견 7 — 집계 행 금지 이력에 따라 3행 분리) |
| `ENTRY_WEIGHT_PCT_MIN=3.0 / MAX=25.0` (사이징 클램프 — 검토 발견 행 추가) | 가능 — 비율 | **있음** — 파일럿 곱 결과가 floor 에 수렴하면 파일럿 차등 소거(E4 명문화) | EXTENDS | B-수치: floor 도달 사례 빈도·비율 보고, 과다 시 파일럿 전용 floor 재설계 |
| `STATUS_DIST_COUNT_FOR_FTD_INVALIDATION=6` (E1 발동 조건 직접 소비 — 검토 발견 행 추가) | 부분 — #55 보류 이력 | **있음** — 파일럿 발동 국면의 분배 경고 배제 경계 | EXTENDS | 값 6 고정(#55 보류 유지·Arm-53 과 동일 상수 공유) — B-수치: 이 조건으로 배제된 발동 후보 수 보고 |
| `minervini_pass` 내부 8조건 (필터 ①) | — 조건 묶음 | 미미 — 소비만, 정의 불변. 근거: 본 경로는 이 값을 읽기만 하고 임계·계산에 손대지 않음 | PRESERVES | 변경 없음 |
| `rs_line_at_52w_high` 계산 정의 (필터 ②) | — 불리언 | 미미 — 동상(소비만). advisory→hard 승격은 이 경로 한정 | PRESERVES(오닐 RS 선행 신고가) | 변경 없음. 프롬프트 advisory 문구는 유지(전역 의미 불변, §6) |
| `MARKET_DIST_DEMOTION_COUNT_25S=5` (§3.5 기존 게이트) | 부분 | 미미 — pilot 분기는 이 상수를 우회하는 별도 경로(기존 판정식 불변). 근거: `market_recovery_ok` 조건식 무변경 | EXTENDS | 변경 없음 — Arm-53 맵의 6 vs 5 비대칭 행이 이미 커버 |
| Arm-53 사다리 상수 일체 (rally_attempt 정의) | — | **있음** — E1 발동 국면이 Arm-53 산출에 종속 | (Arm-53 LOCKED 승계) | Arm-53 맵(9행)이 담당 — 본 맵은 중복 판정하지 않고 참조만 |
| `_SIZE_*` 티어·`_FLAG_MULT` (entry_params) | — | 미미 — 파일럿 50%는 별도 오버레이 곱, 티어·배수 정의 불변(#80 동결 존중) | EXTENDS | 변경 없음. B-수치: 실효 사이징 분포(파일럿×flag 중첩 사례) 보고 |

- **소비 경계 (1줄)**: `pilot_eligible` → §3.5 게이트 분기 → watch/entry go_now +
  pilot 사이징 → 실매매 신호 크기 — 시장 미확인 구간에 실노출이 새로 생기는
  경로다(그래서 채택 게이트가 백테스트 통과다).

## 6. 소비처 동기화 목록 (채택 시 구현 범위)

| 소비처 | 변경 |
|---|---|
| `gate_precompute.py` | `pilot_eligible`·`pilot_lock` 결정론 선계산 추가(기존 `market_recovery_ok` 불변) |
| `entry_params_calc.py` | 파일럿 오버레이(×0.5) + 파일럿 스톱 입력 추가 — 티어·flag 구조 불변 |
| `prompts/analyze_chart_v3.md`·`evaluate_pivot_trigger_v1.md` §3.5 | 회복 게이트 문구에 파일럿 분기 1줄 동기화 |
| `kr_pipeline/common/thresholds.py` | 신설 상수 3개 SSOT 등록 + export 재실행 |
| entry 경로(§3.1) | 시장 게이트 신설(E3 비대칭 해소) — watch 와 동일 판정 소비 |
| `positions` 스키마 + 조회 유틸 | **스키마 변경 포함**(E5 판정 재료): `entry_kind`('normal'\|'pilot') + `exit_price` + 구조화 청산 사유(`is_stop_loss`) 추가, 양쪽 DB psql 수동 적용 관례 준수 |
| `web/src` 용어집 | 파일럿 경로 서술 추가 |

## 7. 검증 계획 (채택 게이트)

1. **arm 구현은 backtest-local**: `portfolio.py` 파일럿 하네스 재사용, 발동부를
   `bottoming_series` → E1+E2(3중 필터) 로 교체한 `pilot_mode_v2`(가칭) 추가.
   합성 데이터 단위테스트만 — 독립 구간 실행 금지(결과 열람 규율).
2. **관찰(A+B, 2021~24)**: arm 구현 완료 후 비보호 구간에서 Arm-53 vs Arm-53+54
   리플레이 — §4 관찰 기준 판정. 미통과 시 조기 기각(C 는 Arm-53 몫만 개봉).
3. **재현 판정(C)**: §4 의 2단 구조 3항 — 관찰 통과 시에만.
4. 통과 전 production 반영 금지. 통과 시 §6 전체가 한 구현 PR 범위.
5. **순서**: [두 arm §9.2 고정] → [arm 구현·합성 테스트] → [Arm-54 A+B 관찰] →
   [C 1회 개봉: Arm-53 판정 + (관찰 통과 시) Arm-54 재현 판정] — C 열람은 1회.

## 8. §9.2 고정 후보 요약 (사용자 게이트 대기)

- **Arm-54** = Arm-53 + [rally_attempt 한정 · 3중 하드 필터(minervini_pass ∧
  rs_line_at_52w_high ∧ 낙폭 −15~−5%) · 파일럿 50%/스톱 6%/에피소드 캡 2 ·
  전역 연속 손절 3회 잠금(해제 = confirmed 또는 새 FTD)].
- 미결정으로 남긴 것: 없음 — E1~E6 전부 권고안 확정. 이의 시 해당 E 항목만 수정.
- 고정 절차: 본 문서 검토 승인 → prereg §9.2 Arm-54 placeholder 교체 → LOCKED 플립.

## 부록 A — A+B 관찰 결과 (look, 2026-08-14 실행 — 본문 비수정 부록)

- 실행: `scripts/arm54_observe_ab.py`, 산출물
  `data/backtest/arm54_observe_ab_20260814.json`. arm53 vs arm53-pilot54,
  표본 A+B·2021~24(비보호). 결정론·LLM 0콜.
- **결과: 관찰 미통과 — 파일럿 발동 0건.** 기준 (i) 판정 불능(트레이드 0),
  (ii) final_multiple 1.1311 = 1.1311(동일 — 파일럿 무발동이므로 자명).
- 탈락 분해(§4 산출물, 후보 신호 73건): **phase 미충족 64**(correction 42 +
  downtrend 22 — unfavorable_market watch 돌파가 대부분 DOWN 국면에서 발생),
  dist≥6 2, **rally_attempt ∧ dist<6 도달 7** — 그 7건 전부 3중 필터 탈락
  (rs 선행 신고가 부재 5, 밴드 밖 5, 트렌드 템플릿 미달 1 — 비배타).
- 해석(정직): 2021~24 구간에서 이 경로의 이론적 기회 자체가 7건뿐이었고
  필터가 전부 걸렀다. 밴드 탈락 5건은 "돌파일에는 주가가 이미 신고가
  5% 이내"라는 구조적 긴장(E2③ 상한 −5%)과 부합.
- **결론(사용자 확정 2026-08-14): Arm-54 불채택 — 단 가설은 미검증 유지.**
  ① 불채택(절차): 발동 기회 부재(실측 0건/4년)가 실용성 부족을 실증 — §4 2단
  구조 2항에 따라 표본 C 개봉 없이 종료(C 는 Arm-53 판정 + F-S2 look #10 몫).
  ② 미검증(인식): 트레이드 0건이므로 "조기 선취의 수익 기여" 가설 자체는
  어느 방향으로도 **반증되지 않았다** — "기각(가설이 틀림)"으로 오독 금지
  (F-S2 트랙의 "미달 ≠ 효과 없음의 증명" 규율 동일).
  ③ 재도전 조건: 재설계(밴드 상한 등) + **신규 독립 구간** + 별도 사전등록 —
  2021~24 는 모수 7건 규모라 재관찰 실익 낮고, C 는 본 트랙 개봉 후 오염.
