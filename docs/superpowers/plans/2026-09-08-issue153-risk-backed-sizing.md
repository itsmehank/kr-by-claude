# #153 — production 사이징을 리스크 역산으로 교체: 판정·정의 원문·의존성 맵·사전등록

> 트리거: thresholds.py 상수 **추가**(SIZING_RISK_PER_TRADE·SIZING_PILOT_FRAC)·**삭제**
> (ENTRY_WEIGHT_PCT_MIN) + 소비처(entry_params_calc·store·backtest PortfolioConfig) 변경 —
> checklist (a) 사실 기준 해당 → §5 의존성 맵. 원칙 2-1(현 main G2) 적용.

## 0. 판정(사용자 결정 A, 전문가 사양 2026-09-08)

production 사이징을 백테스트 방법(Minervini TTLC Ch.8 "backing into risk")으로 통일.
- R = 1.25%(거래당 최대 리스크, % of equity) · stop_pct = −8.0%(예상 매입가 = pivot 기준; 관리
  단계는 기존대로 평균매입가 기준 8% — 규칙 동일, 앵커만 실제값) · full = min(R/|stop|, 25%) =
  15.625% · pilot = full × 0.5 = 7.8125%.
- entry_params 출력 size = pilot, stop = pivot × 0.92, full·method="risk_backed"·R 필드 추가.
  entry_mode 구분 없음.
- **원칙 1-1 4조건**(폐기 대상 = 티어·배수·no_flags·confidence·바닥·스탑 후보·클램프):
  (a) 제약 추가형·필수 매개변수 아님 — 제거 후 suite 정상 / (b) 커버리지 손실 없음 — 플래그의 진입
  억제는 go_now/wait(evaluate_pivot)가, 크기는 R 이 담당 / (c) book-mandated 신호와 방향 충돌 —
  책은 "스탑 **또는** 크기 중 하나"를 조정하는데 구 구조는 flag 로 둘 다 조정 / (d) 미정의 계산
  없음 — 산출·소비 동시 제거. **충족.**

## 1. Phase A 사실(2026-09-08 회신 요지)

- 저장본: entry_params **0행**, go_now **0건**(wait 168·abort 22) → 구 구조 production 미실행.
- 121행 재계산(trigger_evaluation_log → build_for_6 → calc): stop −5.5 지배(91/116, unfavorable
  105/121), size 3.0 바닥 97/121(80%), 리스크 중앙값 0.17%(0.12~0.34) — 책 1.25~2.5% 와 자릿수 차이.
- 수량 = positions 수동 `--qty` → 시스템 미강제. 백테스트 = 이미 역산(1.25%/8% = 15.625%).
- stop_stack(8%·본전·SMA50)은 entry_params.stop_loss 와 미연결 — 실효 스탑 = 8% 평균매입가.

## 2. 폐기된 정의 원문 보존(원칙 1-2 (i) — 재계산 정의 소실 방지)

구 `entry_params_calc.py` §2/§3(#21 이식, 2026-07-12~2026-09-08):
```
§2 stop (pivot 기준 %, stop_price = pivot × (1 + pct/100)):
  pivot_breakout: absolute = −7.0 (wide_and_loose|unfavorable_market_context|3c_cheat → −5.5)
                  logical  = (base_low × 0.995 − pivot)/pivot × 100
                  binding  = logical if logical > absolute else absolute
                  경고 absolute_stop_used_due_to_wide_handle (logical < −10)
                  clamp [ENTRY_STOP_PCT_FROM_PIVOT_FLOOR −10.0, −5.0]
  pocket_pivot:   absolute = −5.5 (wide|unfav → −4.5); logical = (PP_low × 0.995 − pivot)/pivot;
                  sma50 = (SMA50 × 0.995 − pivot)/pivot (pivot ≥ SMA50×0.995 일 때만)
                  binding = max(sma50, logical, absolute) (동률 시 앞 순서); clamp [−8.0, −4.0]
                  경고 stop_at_50day_ma_for_pocket_pivot
§3 size (%):
  티어 pivot_breakout: vcp∧conf≥0.8∧no_flags 15 / {flat_base,cup_with_handle,vcp,double_bottom}∧no_flags 10
                      / 3c_cheat|wide 5 / else 7
  티어 pocket_pivot:   wide 3.0 floor / vcp∧conf≥0.85∧no_flags 10 / 표준∧no_flags 7 / else 5
  no_flags = raw risk_flags 비어 있음(cup_without_handle 은 no_handle_shakeout_absent 결정론 주입)
  배수 _FLAG_MULT: no_handle_shakeout_absent·late_stage_base·narrow_base·thin_liquidity_us_only·
       extended_from_ma·low_volume_breakout·volume_contraction_on_advance·faulty_pivot ×0.7,
       unfavorable_market_context·reverse_split_distortion ×0.5 (eff_flags 기준 — breakout_from_watch
       는 unfavorable 제외); confidence < 0.7 → ×0.7
  clamp [ENTRY_WEIGHT_PCT_MIN 3.0, ENTRY_WEIGHT_PCT_MAX 25.0]; 바닥 도달 시 경고 size_floored_due_to_multiple_flags
  §7 climax_run / etf_methodology_mismatch → size 3.0 강제
  경고: size_reduced_due_to_{unfavorable_market,no_handle_shakeout,late_stage,thin_liquidity}
```
정의 근거 문서: #80 결정문(§1 이중 작용 의미론), #74 spec §4(4.9pp), 은퇴 프롬프트
calculate_entry_params_v2_0.md(동결 아카이브, 값 유지).

## 3. 변경(구현)

| 파일 | 변경 |
|---|---|
| `kr_pipeline/common/thresholds.py` | +SIZING_RISK_PER_TRADE=0.0125 [PRESERVES/design, TTLC Ch.8 1.25~2.5% 하한] · +SIZING_PILOT_FRAC=0.5 [design] · −ENTRY_WEIGHT_PCT_MIN · TRADE_STOP_INITIAL_PCT·ENTRY_WEIGHT_PCT_MAX docstring(공유 SSOT 명기) |
| `kr_pipeline/llm_runner/compute/entry_params_calc.py` | §2 stop = pivot×(1−0.08) 고정, §3 size = min(R/stop, MAX)×pilot, 출력 +suggested_weight_full_pct·sizing_method·sizing_risk_pct. 폐기 상수·경고 6종·티어·배수·confidence·바닥·클램프 제거. target/window/chase 규칙(no_flags·wide·unfav·conf 참조) **불변** |
| `kr_pipeline/llm_runner/store.py` | 정규화 +position_size_full_pct·sizing_method·sizing_risk_pct·position_size_basis(산식 텍스트), sanity 하한 3.0 → >0, INSERT 3컬럼 |
| `kr_pipeline/db/schema.sql` | entry_params +3 컬럼(ALTER IF NOT EXISTS) — kr_pipeline·kr_test 적용 완료 |
| `kr_pipeline/backtest/portfolio.py` | PortfolioConfig risk_pct/max_position_pct/fixed_stop_pct/pilot_frac 기본값 ← SSOT(값 동일) |
| `kr_pipeline/llm_runner/slack.py`·`entry_params.py` | 매수 시그널 알림에 "비중 x.x%(파일럿)" 추가 |
| `api/schemas/signal.py`·`api/routers/signals.py`·`web/src/lib/types.ts`·`SignalsPage.tsx` | full 사이즈·method 노출 |
| `web/src/data/...` | entry-params-fields(사이징 4필드·스탑 서술)·prompt-explanations keyRules·stages 서술·thresholds.generated.ts 재생성 |
| 테스트 | test_entry_params_calc(사이징·스탑 기대값 전면 교체 +산식·플래그 무관·confidence 무관), test_schema_llm_runner(+3 컬럼) |

**미변경**: evaluate_pivot 프롬프트(사이징 서술 없음 — grep 0). analyze_chart_v3 §4·§8.5 의 "C 단계
사이징 감액" 언급 2곳은 Q-2 판정 B 로 삭제(§8). 은퇴 프롬프트
calculate_entry_params_v2_0.md 는 동결 아카이브(값 유지, drift 비감시). #44 replay 등 과거 스크립트 불변.

## 4. 백테스트 회귀

PortfolioConfig 기본값이 SSOT 상수로 바뀌었으나 값 동일(0.0125/0.25/0.08/0.5) → 동작 불변.
`tests/test_backtest_portfolio.py`(15.625% 사이징·파일럿 50% 고정 테스트 포함)·frozen sample
테스트 전부 통과(전체 suite §8).

## 5. 의존성 맵(2축 판정)

**1단계**: SIZING_RISK_PER_TRADE·TRADE_STOP_INITIAL_PCT·ENTRY_WEIGHT_PCT_MAX·SIZING_PILOT_FRAC →
`stop_loss_price/pct`·`suggested_weight_pct/full` → entry_params 행·Slack·SignalsPage;
동일 상수 → backtest PortfolioConfig.
**2단계**: `grep -rn "SIZING_\|TRADE_STOP_INITIAL_PCT\|ENTRY_WEIGHT_PCT_MAX"` → entry_params_calc,
store sanity, backtest/portfolio.py, trade_management/stop_stack.py(initial 8%), web export.

| 고정 상수/룰 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| TRADE_STOP_INITIAL_PCT=0.08 (신규 공유: entry stop·backtest·관리) | 가능(배수) | **있음** — 이제 3소비처가 한 값. 변경 시 사이징(1/stop)·관리 스탑·백테스트 동시 이동 | PRESERVES(HMMS 7~8%) | **B-수치** — 값 변경 금지, 변경 제안 시 3소비처 맵 필수 |
| SIZING_RISK_PER_TRADE=0.0125 | 가능(비율) | **있음** — 사이즈 선형 | PRESERVES(TTLC Ch.8 하한) | 사전등록 holdout(§6) |
| ENTRY_WEIGHT_PCT_MAX=25 (cap) | 불변 | **미미** — 15.625 < 25 라 현 값에서 비활성. stop ≤ 5% 가 되면 활성 | PRESERVES(HMMS 1/4) | **모니터링** — 근거: #161(구조 스탑) 착수 전 cap 도달 경로 없음 |
| SIZING_PILOT_FRAC=0.5 | 가능 | **있음** — 출력 사이즈 선형 | design(TTLC Ch.8 5~10% 시작) | holdout |
| TRADE_STOP_MAX_PCT=0.10 (uncle point) | 불변 | **없음** — 8% < 10% | PRESERVES | 없음 |
| stop_distance 경고 임계 = TRADE_STOP_INITIAL_PCT(8%, Q-1 판정 B — 구 7.5 폐기) | 불가(경고) | **미미** — current > pivot(추격) 에서만 발행, 게이트·사이징 비소비 | 시스템 값(책 8% 한계 준용) | **모니터링** — 근거: 소비처 없음(known_warnings 기록 전용) |
| A 프롬프트 §4·§8.5 서술(Q-2 판정 B — 사이징 감액 언급 삭제) | 해당 없음 | **미미** — 판정 규칙·필드 불변, LLM 입력 텍스트만 변경 | — | **모니터링** — 근거: 사이징은 C 단계 결정론이라 A 텍스트가 사이징에 닿을 경로 없음. **분류 변동 귀속 후보로 별도 행 기록(§8)** |
| §4 target(no_flags·conf·wide·unfav)·§5 window/chase | 불변 | **없음** — 사이징과 분리, 규칙 불변 | PRESERVES | 없음 |
| trade_management stop_stack | 불변 | **없음** — entry_params 미참조(#162 참조 연결은 별건) | PRESERVES | 없음 |
| gates.py·evaluate_pivot 게이트 | 불변 | **없음** — 플래그의 진입 억제 역할 그대로 | — | 없음 |

**소비 경계 (1줄)**: `calculate_entry_params → entry_params 행 + Slack 매수 시그널 → (사용자 수동
체결·positions 등록) → trade_management(8% 평균매입가 앵커)`. 하류 추적 안 함.
**게이트 점검**: 1 맵 ✓ 2 상수 행 ✓ 3 축1·축2 ✓ 4 영향 행 후속(B-수치·holdout·Q-1) ✓ 5 경계 ✓

## 6. 사전등록(배포 전 기록)

1. 변경 성격: **book-fidelity** — production·백테스트 사이징 방법 통일. 성과 개선 목적 아님.
2. production 영향: 현재 **0**(go_now 0건). 향후 go_now 발생 시 size 7.8125%·stop −8% 출력.
3. 관측(판정 아님) — 121행 재계산 구 vs 신:

   | | 구(티어·배수) | 신(리스크 역산) |
   |---|---|---|
   | size | 3.0: 97 / 3.4: 13 / 4.9: 5 / 3.5: 4 | 7.8125 × 121 |
   | stop(pivot) | −5.5: 91 / −7.0: 17 / −6.7: 7 / −5.0: 1 / PP −4.0~−4.5 | −8.0 × 121 |
   | 리스크(pivot 기준) 중앙값 | 0.17% (0.12~0.34) | 0.625% (전부) |
   | 리스크(현재가 기준) 중앙값 | 0.15% (0.00~0.86) | 0.50% (0.00~1.88) |
4. 성과 판정: 없음. 목적은 향후 holdout 판독이 production 을 설명하게 되는 것.
5. 재실행 비교 금지.

## 7. 기록만(착수 금지)

- **#161** 구조 기준가 스탑(base_low×0.995) 도입 검토 — 백테스트·production 동시.
- **#162** entry_params.stop_price → positions 참조 연결(관리 화면 참고 표기, 실효 스탑 유지).
- analyze_chart_v3.md §4(cup_without_handle "사이징 감액 — C 단계 자동")·§8.5(base_forming "C 단계
  사이징 감액") 두 문구는 A 프롬프트의 **분류 판정 근거 서술**(LLM 이 사이징을 하지 않음, §11 명시)이라
  판정에 영향 없으나 사실과 어긋남 — 이번 사양의 프롬프트 범위(§7 통합표·evaluate_pivot §3)에 없어
  미수정, Q-2 로 질의.
- **#80** 클로즈(superseded, 결정문 §6). **#74** F1~F3 제재 = 코호트 R×0.5(spec §7 부록).

## 8. 전문가 판정 반영(Q-1·Q-2, 2026-09-08 — 머지 전)

| 질의 | 판정 | 구현 |
|---|---|---|
| Q-1 stop_distance 경고 임계 | **(B) 임계 = TRADE_STOP_INITIAL_PCT(8%)** | `abs(stop_from_current) > TRADE_STOP_INITIAL_PCT*100`. current > pivot(추격) 케이스만 발행, current == pivot 은 정확히 −8.0 → 미발행. happy-path 테스트 "Q-1 대기" 해제, 3케이스(추격/동일/하회) 테스트 |
| Q-2 A 프롬프트 문구 | **(B) "사이징 감액" 언급 삭제**, strict 1.5× 거래량 게이트 서술만 유지 | §4 cup_without_handle 진입 규율 문구·§8.5 base_forming 각주 수정 |

**별도 행 — A 프롬프트 §4·§8.5 문구 변경(향후 분류 변동 귀속 후보)**: 두 문구는 분류 판정 근거
서술이며 출력 필드·게이트와 무관하나, LLM 입력 텍스트가 바뀌었으므로 이 시점(2026-09-08, PR #163)
이후 cup_without_handle·base_forming 분류 빈도에 변동이 관측되면 귀속 후보로 검토한다. 판정 아님.
§5 의존성 맵 보강: | A 프롬프트 §4·§8.5 서술 | 해당 없음 | **미미** — 판정 규칙·필드 불변, 서술만 | — | **모니터링** — 근거: 사이징은 C 단계 결정론이라 A 텍스트가 사이징에 닿을 경로 없음; 분류 빈도 변동 시 귀속 후보로만 기록 |
