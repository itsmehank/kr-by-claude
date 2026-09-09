> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# 항목 ① — 일간 climax/topping 신호 3종 신설(T5·T6·TA-d): 사양·의존성 맵·사전등록

> 트리거: `kr_pipeline/llm_runner/compute/climax_topping.py`(CLIMAX_* 상수 소비처)에 산출
> 함수 추가 + `analyze_chart_v3.md` §6.1/§6.2 게이트 텍스트 변경 — 체크리스트 (a) 사실 기준
> 해당(governance 원칙 2-1 / 현 main G2: 방법론 판정("임계 변경 아님")이 트리거를 면제하지
> 않음). thresholds.py 상수 추가·변경 **0**.

## 0. 판정 체인(전문가 확정, 2026-09-07 — 재질의 사항 없음)

| 항목 | 판정 | tag |
|---|---|---|
| D-1 최대 일간 상승폭 | HMMS Ch.10 Climax Tops #1 + TTLC Ch.9 | book-mandated |
| D-2 최대 일간 스프레드 | TTLC Ch.9 **단독**(HMMS 는 주간판만) — 프롬프트에 "Minervini 단독 출처" 병기 | book-mandated |
| D-3 최대 일간 하락폭 | TTLC Ch.9 / TLSMW Ch.5, 기준점 "Stage 2 상승 시작" = 기존 find_anchor 일치 | book-mandated |
| D-4 척도 = 비율(%) | 책 미명시. 절대금액은 장기 상승 종목 후반부 자동 발화 → 비율 | design-judgment |
| D-5 소비처 | 현행 §6.1/§6.2 소비처(A 프롬프트 분류) 한정. trade_management 연결 금지(항목 ③) | scope |
| D-6 결합 위치 | T5·T6 = §6.1 **동급 OR 트리거**(T1~T4 병렬, HMMS Ch.10 평면 구조). TA-d = §6.2 T-A 옆 일간판 | book-mandated |
| Q-1 baseline 시작 | anchor 주 **첫 거래일**(W-SUN 그룹 min(date)) — "beginning of the move" | book-mandated |
| Q-2 분모 | 상승·하락률 = (close−prev_close)/prev_close(독법 + T4·T-A 관례). 스프레드 = (high−low)/prev_close | book-mandated / design-judgment |
| Q-3 동률·결측 | 동률 `>=`(기존 관례 — 가격제한 동률 실재, 노출 축소 방향, 책 "larger than" 이탈 명시). no_transition = 전체 일봉 이력 | 기존 관례 |
| Q-4 주간 T1 절대값 | 본 항목 미포함 → 별도 이슈(아래 §6) | — |

## 1. 신호 정의(구현 원문)

공통: baseline = anchor 주 첫 거래일 ~ on_date, `date <= on_date` look-ahead 가드,
`COALESCE(adj_*, raw)`, zero-bar 제외, anchor 3모드(left_censored → None·발화 금지 /
no_transition → 전체 일봉 / anchored) 주간과 동일. 오늘 = 조회 마지막 행(T3 관례).

- **T5 `t5_daily_max_up_now`** [§6.1]: 오늘 상승일(close>prev) AND up_pct ≥ max(baseline 상승일
  up_pct), up_pct = (close−prev_close)/prev_close. 상승일 아니면 False(자격 없음, T-A 관례).
- **T6 `t6_daily_max_spread_now`** [§6.1]: spread_pct = (high−low)/prev_close, 전 거래일 대상,
  오늘 ≥ max(baseline).
- **TA-d `ta_d_daily_max_decline_now`** [§6.2, T-A 옆]: 오늘 하락일 AND down_pct ≥ max(baseline
  하락일 down_pct), down_pct = (prev_close−close)/prev_close. G0 등 §6.2 전제 상속, 재판정 없음.

baseline 첫날의 prev_close 는 baseline 직전 비-zero-bar 1행으로 공급(`_fetch_daily_since`
UNION 규약) — anchor 주 첫 거래일(돌파일)이 baseline 에 **포함**되도록.

## 2. 변경 파일

| 파일 | 변경 |
|---|---|
| `kr_pipeline/llm_runner/compute/climax_topping.py` | `compute_daily_extremes(daily_hist, baseline_start, anchor)` 순수 함수 + `_DAILY_KEYS` |
| `api/services/payload_builder.py` | `_anchor_baseline_start`(ISO 주 월요일), `_fetch_daily_since`(anchor 이후 전 일봉 + 직전 1행, 전 이력 모드), build_payload 병합. 기존 `_fetch_daily_ohlcv`(60일)·T3/T4 입력(마지막 20행) **불변** |
| `prompts/analyze_chart_v3.md` | §6.1 트리거 목록 T5·T6 추가, 결합식 "T1~T6 중 ≥1", left_censored null 목록 갱신 / §6.2 TA-d(T-A 옆) + anchor 의존 게이트 목록. P1∧P2·E1·scope 문구 불변 |
| `tests/test_climax_topping.py` | 단위 10건(정상·미발화·동률/상한가·비율 분모·TA-d·left_censored·no_transition·첫 거래일 포함·prev_close 공급·결측) |
| `tests/test_climax_payload.py` | 월요일 환산·`_fetch_daily_since` 규약·anchored 통합·left_censored None 4건 |
| `tests/test_climax_daily_prompt_sync.py` | 코드 키 ↔ 프롬프트 grep 가드 3건 |

미변경(사양 명시): `gates.py` 결정론 백스톱(§6.1 백스톱 없음이 현 설계), `entry_params_calc`
정합 검사(climax_run + entry 모순 → 그대로 동작), thresholds.py.

## 3. 의존성 맵(2축 판정)

**1단계 (파생 신호)**: (신설 상수 없음) `_fetch_daily_since` 일봉 → `t5_daily_max_up_now`·
`t6_daily_max_spread_now`·`ta_d_daily_max_decline_now`(bool|None).

**2단계 (소비 룰)**: `grep -rn "t5_daily_max_up_now\|ta_d_daily_max_decline_now"` →
analyze_chart_v3.md §6.1 트리거 OR(T5·T6) / §6.2 T-A 옆 OR(TA-d) — 유일 소비. 결정론 소비 0
(gates.py 미추가). payload JSON 은 dict 전체를 직렬화하므로 키 자동 전달.

**3단계 (룰 내부 고정 상수)**:

| 고정 상수/룰 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| §6.1 결합식 트리거 카운트 "≥1"(T1~T4 → T1~T6) | 해당 없음(카운트 임계 1 불변) | **있음** — OR 분지 2개 추가 → climax_run 발화 집합 확대(P1∧P2·E1·scope 전제는 불변이라 확대 폭은 전제 통과 종목 내로 한정) | PRESERVES(HMMS Ch.10 평면 구조) | **사전등록 holdout**(§5) — 현 표본 판정 금지. 관측 기록만 |
| §6.2 결합식 "G0 AND ANY ONE"(T-A/B/C/D → +TA-d) | 해당 없음 | **있음** — G0 하 OR 분지 1개 추가 → topping_distribution 발화 확대 | PRESERVES(TTLC Ch.9/TLSMW Ch.5) | 동일 holdout. gates.py §6.2 shadow 백스톱은 book-mandated 분지(T-B/T-D분배일)만 보므로 **무영향**(TA-d 미참조) |
| CLIMAX_MATURITY_WEEKS=18 / CLIMAX_GAIN_PCT=25 (P1·P2 전제) | 불변 | **없음** — 전제는 트리거와 AND, 값·산술 불변 | PRESERVES | 없음 |
| CLIMAX_UP_DAYS_*(T4) / T3 daily 20행 창 | 불변 | **없음** — 입력 경로 분리(daily_ohlcv[-20:] 그대로), 테스트로 고정 | PRESERVES | 없음 |
| CLIMAX_SCOPE_*(scope_active) | 불변 | **없음** — 주간 종가 기준, 일간 신호와 독립 | PRESERVES | 없음 |
| 동률 `>=` 관례 | 해당 없음 | **미미** — 책 "larger than"(`>`) 대비 동률일 추가 발화. 가격제한(±30%) 동률이 실재하는 KRX 특성상 노출 축소 방향 | 방법론차이(명시) | **모니터링** — 근거: 방향이 보수(ignore 확대)이고 P2·T1·T-A 가 이미 같은 관례, 별도 임계 아님 |
| entry_params_calc "climax_run + entry 모순" 검사 | 불변 | **없음** — 플래그 이름·발화 경로 불변, 발화 증가 시 검사 빈도만 증가 | — | 없음 |

**소비 경계 (1줄)**: `climax_topping_gates.{t5,t6,ta_d} → analyze_chart_v3.md §6.1/§6.2 LLM
판정(climax_run / topping_distribution → verdict ignore) → weekly_classification.risk_flags`.
하류 깊이 추적 안 함.

**게이트 자체 점검**: 1 맵 ✓ 2 고정 상수 행 ✓ 3 축1·축2 전 행 ✓ 4 축2 있음 행 후속 = holdout
예약, 모니터링 행 근거 기입 ✓ 5 소비 경계 ✓

## 4. 코드 사실(설계 확인 회신 S1~S6 요지, 2026-09-07)

- 결합 판단 주체 = LLM(결정론 코드는 필드 값만). §6.1 결정론 백스톱 없음.
- 주봉 산술 입력은 전 이력(LIMIT 없음), 일봉은 60일 조회·20행 사용 → 본 변경으로 별도 경로 신설.
- week_end_date = ISO 주 max(date) → daily_prices 동일 날짜 행 존재. 월요일 환산 = weekday() 되돌림.
- 가격 = COALESCE(adj_*, raw). daily 비정지 adj NULL 0행, weekly adj_high NULL 1,019/1,139,135.
- 기존 T1 = 절대값(척도 불일치) → Q-4 별도 이슈.

## 5. 사전등록(구현 착수 전 기록)

1. **변경 성격**: book-fidelity 보완. 성과 개선 목적 아님.
2. **기대 방향**: §6.1 climax_run·§6.2 topping_distribution 발화 **증가**. 폭 미예측.
3. **관측 기록 — 배포 전 저장본 기준선(2026-09-07 로컬 kr_pipeline 실측, `risk_flags ? '<flag>'`)**:

   | 테이블 | climax_run | topping_distribution | 전체 행 |
   |---|---|---|---|
   | weekly_classification | 678 | 27 | 2,139 |
   | classification_backfill | 43 | 0 | 322 |
   | backtest_classification | 242 | 51 | 6,023 |

   배포 후 동일 집계를 기록한다. **관측만 — 판정 아님.** (전문가 지시문의 "topping 26" 은
   실측 27 — 지시 후 저장본 증분으로 봄.)
4. **성과 판정**: 현 표본으로 하지 않음. P0 재수집 후 holdout 으로만.
5. **재실행 비교 금지**(LLM 비결정성).

## 6. 별도 이슈(착수 금지)

- **#156** "§6.1 T1 주간 스프레드 절대값 → 비율 전환 검토" — 사유 D-4 동일·P2/T-A 척도 불일치.
  tag design-judgment 후보. 순서는 사용자 결정(전문가 권고: ① 직후, ② 전).

## 7. 로컬 코드리뷰 반영(2026-09-07, PR #157 머지 전)

**단독 수리(명명·문구·테스트 구조·중복 — 임계·분기 무영향)**:
- 프롬프트 §6.1 baseline 문장(L404)·no_transition 모드 항목(L420)에 T5/T6/TA-d 일간 baseline 명시
  (left_censored 항목만 갱신돼 형제 열거가 빠졌던 것).
- §6.1 트리거 헤더 "필수·보조 구분 없음"을 **T1~T6 사이**로 한정하고 "Supporting 은 트리거가
  아니다(7번째 OR 분지 아님)" 명시 — supporting_ext_sma200_pct 단독 발화 오독 차단.
- payload_builder 일봉 조회 SQL 조각(`_DAILY_OHLCV_COLS`·`_DAILY_NOT_ZERO_BAR`·`_daily_row`)을
  `_fetch_daily_ohlcv`/`_fetch_daily_since` 공유로 단일화(바 집합 분기 방지). ISO-월요일 식의
  공용 helper 승격(weekly/store.py·modes.py 사본)은 범위 밖 — 사실만 기록.
- anchored 통합 테스트를 시드 유도 기대값(T5 False·T6 True·TA-d False)으로 교체 — 구현 helper
  재호출 동어반복 제거. 월요일-vs-anchor_week 시작·직전 1행 누락이 각각 T5 를 뒤집도록 구성.

**사실 기록(변경 없음)**:
- `scripts/stage3_replay_climax_topping.py`(#44 사전등록 측정)는 §6.1 트리거를 t1~t4 로 고정 —
  **4-트리거 정의에 동결된 측정**이며 T5/T6 를 반영하지 않는다(편집 금지 대상). 발화 집합 확대
  크기 측정은 본 문서 §5-3 저장본 집계로만 한다.
- no_transition 경로 비용 실측: 005930 전 일봉 2,508행 조회 9.5ms, build_payload 전체 17ms —
  집계 SQL 전환 불요.
- daily_prices 비정지 행의 adj_high/adj_low NULL = **0행**(2026-09-07 실측) — T6 척도 혼입은 현
  데이터에서 미발현. 스키마상 NULL 허용이라 구조 노출은 존재(아래 Q-7).

**전문가 질의(분기 조건 — 원칙 2-2, 회신 전 현 구현 유지)**: Q-5 quality_flag 시 일간 신호
null 여부 / Q-6 정지 재개 갭의 prev_close 처리 / Q-7 adj_high·adj_low NULL 행 처리 /
Q-8 no_transition 전체 일봉 baseline 의 관성(전환 없는 종목 3,821/4,252=89.9%에서 과거 상한가
1회가 T5 를 영구 False 로 고정) — 회신 본문 참조.

## 8. 전문가 판정 반영(Q-5~Q-8, 2026-09-07 — governance 추가 없음)

| 질의 | 판정 | 구현 |
|---|---|---|
| Q-5 quality_flag | **(A) 강등** — anchor 의존 게이트 관례 | `compute_daily_extremes(..., quality_flag=climax["quality_flag"])` → 3신호 None. build_payload 는 조회 생략 |
| Q-6 정지 갭 | **(C) 연속 세션만** — prev↔today 사이 zero-bar 존재 시 쌍 제외(baseline·today 양쪽), today 가 재개일이면 3신호 None | `_fetch_daily_since` 가 zero-bar 행을 제외하지 않고 `zero_bar=True` 로 표시, compute 가 gap 추적 |
| Q-7 조정 기준 혼합 | **(A) 행 제외** — high·low·prev_close 가 같은 조정 기준일 때만 T6 산출(규칙 신설 아님, 공식 유효성 조건) | `adj_hl`(adj_high·adj_low 둘 다 non-NULL) False 행은 스프레드 후보 제외, today 가 그런 행이면 T6 만 None. prev_close=adj_close 는 NOT NULL 이라 "전부 raw" 조합은 발생 불가 |
| Q-8 no_transition | **None**(left_censored 동일 처리) — 책 정의 "since the beginning of the move" 는 식별된 시작점 전제 | compute·build_payload 모두 no_transition → None, 조회 생략. 프롬프트 §6.1·§6.2 에 "null 이면 해당 트리거 미평가, 나머지로만 판정" 추가. 전 필드 null(left_censored) 규칙 불변 |

**관례 불일치 명기(Q-8)**: no_transition 모드에서 **주간** P2/T1/T2/T-A/T-D 는 전체 이력 기준
값을 공급하고(기존 관례), **일간** T5/T6/TA-d 는 null 이다. 두 관례가 병존한다 — 해소는 별도
이슈(#158, find_anchor 커버리지) 착수 시. **[#169 해소 2026-09-09: 주간도 None — 병존 종결]**

**관측 사실(Q-6 파생, 수정 금지)**: 주간 T-A(`ta_max_decline_now`)도 zero-bar 주 제외 후 직전
주를 prev 로 쓰므로 정지 재개 주의 점프가 baseline 극값을 점유할 수 있다 — 동일 노출. **#156
(T1 척도) 검토 시 함께 볼 항목**으로 표기. 이번 변경에서 주간 코드는 건드리지 않았다.

**사전등록 §5-3 관측 보완(전문가 지시)**: 배포 후 집계 시 anchor 모드별 분리 기록 —
anchored / no_transition(null) / left_censored(null) / quality(null) 각 행 수 + anchored 모드의
T5·T6·TA-d 발화 횟수. 데이터 소스: `climax_topping_gates` 는 DB 컬럼으로 저장되지 않으나
분류별 freeze 아티팩트(`save_freeze` — inline_input.md 의 payload.json)에 전 필드가 보존되므로
사후 집계 가능. 관측만 — 판정 아님.

**테스트 추가(Q 반영)**: quality_flag None / zero-bar 사이 쌍 제외 / 재개일 None / 혼합 행 T6
제외·today 혼합 시 T6 만 None / no_transition None(단위+payload) / `_fetch_daily_since` 의
zero_bar·adj_hl 플래그 / 프롬프트 null-미평가 문장·left_censored 규칙 불변 가드.
