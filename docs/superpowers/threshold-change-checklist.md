# 임계 변경 의존성 맵 체크리스트

> 책-유래 임계 / 상수를 바꿀 때 *의존 룰과의 상호작용을 점검* 하는 절차.
> P2-1a 검증 (2026-05-25) 에서 "FTD 임계 상향이 status.py 의 FTD 무효화 룰
> (FTD_INVALIDATION_DAYS=10) 과 상호작용해 회복을 correction 으로 오판" 한
> 발견 (action plan v2 §후속 발견 F1) 이 계기. 임계 변경이 *그것을 소비하는
> 고정 상수* 와 정합한지 점검 안 하면 같은 누락이 반복된다.

---

## (a) 트리거 규칙 — 언제 이 체크리스트가 필수인가

**결과 기준** (주관적 "임계 변경인가?" 판단 아님 — git diff 로 확인 가능한 사실):

> `kr_pipeline/common/thresholds.py` 의 상수를 **추가/변경** 하거나, 그 상수를 **소비하는 계산 로직** 을 수정하는 작업.

추가 — **연동되는 prompt 임계 텍스트**: prompt (.md) 는 thresholds.py 를 코드로 import 하지 않고 *수동 동기화* 하지만, thresholds.py 값과 *연동되는 prompt 의 임계 텍스트* (예: §6.1 breakout 1.4×) 를 바꾸는 작업도 이 체크리스트 대상.

이유: "이건 임계 변경 아닌데?" 오판 방지. P2-1a 도 "FTD 임계 하나 바꾼 줄 알았는데 파생 신호 (last_ftd_date) 를 건드려 룰 3 까지 영향" — 주관 분류로는 안 걸렸을 케이스. "thresholds.py 또는 그 소비처를 건드렸나" 라는 *사실* 로 걸린다.

---

## (b) 의존성 맵 템플릿 (2축 판정)

깊이 **1~3 단계 필수 + 소비 경계 1줄**:

- **1단계 (파생 신호)**: 임계 → 그것이 만드는 파생 값. (예: `pct_threshold` → `last_ftd_date` / `days_since_ftd`)
- **2단계 (소비 룰)**: 파생 신호를 쓰는 모든 룰/분기. **찾는 법**: 파생 신호명으로 `grep -rn "<신호명>" kr_pipeline/` → 사용처 전부 식별. (예: `days_since_ftd` → status.py 룰 3/4/5)
- **3단계 (룰 내부 고정 상수)**: 각 소비 룰 안의 *다른 고정 상수* — 임계 변경이 이 상수와 정합한가가 핵심. (예: 룰 3 의 `FTD_INVALIDATION_DAYS=10`, 룰 4 의 `FTD_RECENT_DAYS=90`, 룰 3 의 `DIST_COUNT=6`)
- **소비 경계 (4단계 대체, 1줄)**: 이 모듈의 최종 출력이 *어느 레이어로 넘어가는가* — 한 줄. 하류 깊이 추적 *안 함* (폭발 방지). (예: `current_status → analyze_chart_v3.md §3.5 → entry 강제 watch`)
  - *모듈 내부 2차 파생* (룰끼리 엮임) 은 별개 — status.py 처럼 룰이 배타적 (각 즉시 return) 이면 내부 2차 파생 0. 엮이는 모듈이면 그 연쇄만 추적.

### 2축 판정 (각 3단계 고정 상수마다)

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| (상수명) | 가능/부분/불가 + 이유 | 있음/미미 + 근거 | PRESERVES/EXTENDS/방법론차이 | (아래 규칙) |

- **축1 (환산 가능성)**: 이 상수를 σ (또는 보정 기준) 로 *비례 조정* 가능한가? — 시간 단위 (일수) 는 보통 불가, 변동성 배수는 가능, 다른 임계와 연동되면 부분.
- **축2 (영향 여부)**: *환산 불가여도*, 임계 변경이 이 상수의 *실제 동작* 을 바꾸나? — 후속을 가르는 핵심 축. (환산 불가 ≠ 방치 가능)
- **책 정합**: 이 상수가 책 인용 (PRESERVES) / 책은 *존재* 만 요구하고 숫자는 시스템 자체 (EXTENDS) / 책과 다른 방법 (방법론차이) 중 무엇인가.
- **후속 규칙** (축2 기준):
  - 환산불가 + 영향있음 → **B-수치** (데이터 누적 후 강제 재검토)
  - 환산불가 + 영향미미 → **모니터링** (단 근거 필수 — 아래 합격 조건 4)
  - 환산가능 + 영향있음 → **임계와 함께 보정**

---

## (c) 합격 조건 (게이트)

**승인 불가 조건 — 하나라도 해당 시 spec 미완성** (= 진행 차단):

1. 의존성 맵 섹션 자체가 없음
2. 소비 룰의 3단계 고정 상수가 행으로 안 들어감
3. 어느 행의 축1 (환산) 또는 축2 (영향) 칸이 빔
4. 축2 = "영향 있음" 인데 (**후속 빈칸** OR **근거 없는 "모니터링"**)
   - 후속 = B-수치 / 보정 → 행동 예약됨, 근거 불필요
   - 후속 = 모니터링 → *"왜 지금 행동 안 하고 지켜보나"* 한 줄 근거 필수. 근거 없으면 빈칸과 동일 → fail
   - 이유: 영향 있는 상수가 "모니터링" 으로 도피하는 것 차단. P2-1a 의 FTD_INVALIDATION_DAYS=10 이 정확히 이 도피로로 방치됐다 4월 case 로 터짐.
5. 소비 경계 1줄 없음

**검증 주체/시점** (둘 다 — 기계적 조건이 사람 판단을 보강):
- **spec self-review** (작성자): brainstorming/writing-plans 의 self-review 단계에서 위 5 조건 대조.
- **사람 review gate**: spec 승인 전 사람이 위 5 조건 확인. 4월 case 교훈 = 사람 review 만으론 못 잡음 → "축2 영향있음인데 후속 빈칸/근거없는 모니터링" 같은 *눈으로 보이는 조건* 으로 사람 게이트 신뢰도 자체를 올림.

---

## (d) P2-1a 소급 예시 (이번에 놓쳤던 것 명문화)

P2-1a (한국시장 FTD/distribution 임계 σ 보정) 가 *작성 당시 이 맵을 안 그려서* 룰 3/4/5 의 고정 상수 정합성을 놓쳤다. 소급 적용:

**1단계 (파생 신호)**: `pct_threshold` (FTD/distribution 보정 임계) → `last_ftd_date` / `days_since_ftd` (follow_through.detect_last_ftd) + `dist_count` (count_distribution_days)

**2단계 (소비 룰)**: `grep -rn "days_since_ftd\|last_ftd_date" kr_pipeline/market_context/compute/status.py` → 룰 3 (FTD 무효화), 룰 4 (confirmed_uptrend), 룰 5 (rally_attempt) — *세 곳*

**3단계 (룰 내부 고정 상수) — 2축 판정**:

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| FTD 임계 자체 (1.4→3.28) | 가능 (σ) | 있음 | **방법론차이** (책 TLOND p.117 은 ATR 기준, 우리 σ — 아래 각주) | 임계와 보정 (= P2-1a 본체) + ATR 차이 기록 |
| 룰3 `FTD_INVALIDATION_DAYS=10` | 불가 (시간 ≠ 가격 σ) | **있음 (단 bounded)** — 4월 case: 보정 FTD 후퇴 → days_since 14>10 → 룰3 correction 오판, fwd_return 양수. **그러나** 룰3 발동 조건이 `dist≥6` → §3.5 line77 (`dist≥5` prefer-watch) 와 **항상 co-fire** → 10일이 만드는 flip 은 "prefer-watch → force-watch" 이지 "clean-entry(line78: confirmed_uptrend AND dist≤3) → watch" 가 아님. replay 22 갈린 날 전부 dist≥5 → clean-entry flip **실측 0건**. (잔여: dist 5~7 + 소프트 바이어스 이기는 강한 셋업 = 저신뢰 entry↔watch 갈림 가능, 무시가능하나 0 아님) | **EXTENDS** (책 TLOND p.118 은 "reset 규칙 *존재*" 만 요구, 구체 숫자 10 은 시스템 자체. p.232-233 에도 10 없음) | **B-수치, 시급 아님** (entry/watch 직접 뒤집기 bounded 입증됨 → cron 누적 후 정상 순서 재검토. 1건 과적합 금지) |
| 룰4 `FTD_RECENT_DAYS=90` | 불가 (시간) | **미미** (여유 커서 보정 FTD 후퇴 폭이 90일 경계에 안 닿음 — 4월 case 미발현) | **EXTENDS** (책 인용 없음, 시스템 자체) | **모니터링** (근거: 90일 여유가 보정 FTD 후퇴 최대폭보다 충분히 큼) |
| 룰3 `DIST_COUNT_FOR_FTD_INVALIDATION=6` | 부분 (distribution_pct 보정 → dist_count 변동과 연동) | **연동** (보정 distribution_pct 가 dist_count 를 바꿔 룰3 발동 빈도 변경) | EXTENDS (IBD/Dr.K 통용, 책 구체 숫자 6 은 시스템 채택) | **B-수치** (dist_pct 보정과 6 의 정합 데이터 확인) |

**소비 경계 (1줄)**: `current_status (correction/confirmed_uptrend/rally_attempt/downtrend) → market_context_daily → analyze_chart_v3.md §3.5 하드룰 → entry 강제 watch`. (status.py 룰은 배타적 = 내부 2차 파생 0. 하류는 LLM 레이어 단일 경로.)

**각주 — 알려진 방법론 차이 (ATR vs σ)**: 책 TLOND p.117 은 임계 조정을 **ATR (Average True Range)** 기준으로 권고 ("adjusted based on the average true range"). P2-1a 는 **σ (close-to-close 표준편차)** 사용. 시스템에 ATR 계산 코드 *없음* (`grep -rn "atr|average_true_range" kr_pipeline/` 빈 결과). σ 와 ATR 은 둘 다 변동성 측정 (ATR 은 gap/intraday range 포함, σ 는 종가 기준) — 결함 아니나 *책과 다른 선택*. ATR 전환은 큰 작업 (ATR 계산 신규 + 재측정 + replay 재검증) → 후속. 현재는 차이 인지 + 기록.

**검증 아티팩트**: `docs/superpowers/verification/2026-05-25-p2-1a-replay.csv` (base vs corrected status 비교, 4월 case 증거) + `docs/superpowers/verification/2026-05-25-p2-1a-ftd-invalidation-entry-impact.md` (§3.5 co-fire 분석 — 22 갈린 날 entry/watch 추론 표, clean-entry flip 0건 입증).

---

## 적용 이력

- 2026-05-25: P2-1a 소급 (위 (d)). 이후 P2-1b (cup depth) 부터 신규 spec 작성 시 (a)~(c) 의무.
- 2026-05-27: P2-1d wide_and_loose 주석 정정 (`analyze_chart_v3.md:189`). **동작 중립** 케이스 — operative 임계 (주간 봉폭 10–15%) 불변, 비-operative 주석 ("1.5–2.5× general market correction") 만 수정. 파생 신호 `wide_and_loose` flag → 소비처 `calculate_entry` (stop −5.5/−4.5, size, window=1, target 15). 축2 (영향) = NONE (flag 발동 동작 동일). 게이트 통과. (상세: book-audit-findings.md F5.)
- 2026-06-12: SSOT 리터럴 일괄 정리 (**동작 중립** — 값 변경 0). 호출부가 SSOT default 를 리터럴로 덮던 곳(indicators pocket_pivot/volume_dry_up/minervini lookback, market_context dist/ftd lookback)과 메타데이터(COMPUTATION_NOTES)·웹 표기(LlmPipelinePage promotion 0.95/1.4~1.5, PromptPage C6/C7/C8)를 import 보간으로 통일. operative 임계 불변, "호출부 리터럴이 SSOT 무력화" 재발 통로 제거(P0-2/1.25 사건 재발 방지). 게이트: 동작 중립 — 의존성 맵 생략 (P2-1d 전례).
- 2026-07-08: P1-7 프롬프트 drift 감시 확장 (**동작 중립** — 값 변경 0). store.py 사설상수 4종을 SSOT 승격(ENTRY_STOP_PCT_FROM_PIVOT_FLOOR −10 / ENTRY_TARGET_PCT_MIN·MAX 15·50 / ENTRY_WEIGHT_PCT_MIN·MAX 3·25 / ENTRY_TRIGGER_BUFFER_MAX 1.005, import 보간) + evaluate_pivot_trigger_v1.md·calculate_entry_params_v2_0.md 에 SSOT-THRESHOLDS 블록 도입 + drift 테스트 3프롬프트 파라미터라이즈(음수 파싱 지원). operative 임계 불변 — 게이트: 동작 중립, 의존성 맵 생략 (2026-06-12 전례). 코드 비소비 프롬프트 전용값(1.2~1.4 wait 밴드·0.98·0.995 등)은 과등재 방지 원칙으로 비등재.
- 2026-07-10: #19 B §3.5 unfavorable_market 회복 게이트에 dist<5 재확인 추가 (03편 조건부모순 I 수리). 의존성 맵 = docs/superpowers/plans/2026-07-10-issue-19-dist5-recovery-recheck.md. "5"는 코드 비소비 프롬프트 전용값 — SSOT 비등재 원칙 유지, A↔B 동치는 tests/test_prompt_trigger_gates.py 가 강제. 동작 방향 = 보수화만(AND 게이트).
- 2026-07-10: #20 종목레벨 분배일 하락 컷 0%→−0.2% 정합 (03편 확정모순 B 수리). STOCK_DISTRIBUTION_PCT_DOWN 신설(SSOT·프롬프트 블록·drift·웹 export 동기). 의존성 맵 = docs/superpowers/plans/2026-07-10-issue-20-stock-dist-pct-cut.md. 방향 = 완화(flag 감소 → §6 발동 감소) — production 재계산 시 전후 발동률 비교 B-수치 예약. A/D ratio 의 is_down(0% 컷)은 의도적 별개 명문화.
- 2026-07-11: #30 이행 — 일봉 지표 full-refresh 재계산(5,247,399행, 실패 0)으로 STOCK_DISTRIBUTION_PCT_DOWN 소급 완료. **B-수치**: 최근 1년(≤07-06 동일창) flag 78,762→75,727(−3,035, 사전 예측 3,038과 0.1% 오차) / §6 경계(25일 ≥4) 종목 698→691(−7). 경계 잔차 6건(0.008%)=SQL 십진 vs pandas 부동소수 산술 차이 추정. halt 해제일 미탐지 주장은 실측 반증(해제일 분배 후보 64건 전부 탐지 중)→docstring 정정. σ보정 도입 여부는 이 수치 기반 후속 재검토.
