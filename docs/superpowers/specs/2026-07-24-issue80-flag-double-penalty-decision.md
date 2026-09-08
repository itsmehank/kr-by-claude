# #80 사이징 flag 이중 페널티 — 결정 기록 (2026-07-24, 사용자 확정)

> **결정: 1안 — 현행 유지 + 의도 명문화. 2안(역할 분리)은 기각이 아니라
> 아래 재개봉 조건으로 동결.** 근거: 독립 검토(#74 리뷰어 연속) 권고 +
> 사용자 게이트.

## 1. 확정된 의미론

risk flag 는 사이징에 **이중 작용(의도된 2층 보수 장치)** 한다:

1. **티어 자격 박탈** — flag ≥1 이면 `no_flags` False → standard(10pp)/top
   (15pp) 도달 불능, fallback(7pp) 이하로.
2. **배수 감액** — `_FLAG_MULT`(×0.7/×0.5, flag 별 곱).

문면 "×0.7" 보다 항상 더 깎인다(late_stage 단독 = 10→7→**4.9pp**).
신설 flag 도 이중 작용이 **기본값** — 단일 감액 의도라면 명시적 예외를
설계하고 사유를 기록한다(threshold-change-checklist 가이드).

## 2. 결정 근거 (독립 검토 3줄)

1. 2안은 빈도가중 평균 배팅 3.2→4.9~5.3pp(상대 +50~60%) 의 **실질 위험
   정책 변경** — 수익 미입증(CI 0 포함·플라시보 p=0.19) 시스템에서 배팅
   상향은 책 규율(미입증→축소)의 정반대.
2. "티어 사멸(flag 96~98%)" 관측은 **시장 국면에 조건화**돼 있다 — 최빈
   flag 가 unfavorable_market_context(시장 자동 발화, ×0.5). 건강한
   confirmed_uptrend 에선 no_flags 행이 재출현해 10pp 티어가 살아난다.
   나쁜 시장에서 3.0pp 바닥(ENTRY_WEIGHT_PCT_MIN)에 눌리는 것은 책이
   처방하는 행동.
3. #74 F1~F4 사전등록(강화 후속 ×0.5 포함)이 이중 페널티 의미론(4.9pp)
   전제로 방금 배포됨 — 첫 판독 전 구조 변경은 코호트 오염.

바닥 포화의 flag 차등 소실(0.7 vs 0.5·갯수)은 위험 계층이 아닌 표시 계층의
정보 압축 — flag 조합·`mults` 가 행에 기록되므로 사후 복원 가능(추가 컬럼
불요).

## 3. 재개봉 조건 (2안 재검토의 입장권 — 사전 등록)

**둘 다** 충족 시에만 재개봉:

1. 수익성 첫 판독에서 **기대값 > 0 확인** (#59/#45 코호트 프레임,
   go_now ≥ 20 표본 기준)
2. **#74 F1~F4 첫 판독 완료** (코호트 오염 창 종료)

재개봉 시 필수 절차: 의존성 맵 **상수별 행**(`_SIZE_*`·`_FLAG_MULT` 9종+
no_handle·ENTRY_WEIGHT_PCT_MIN·confidence ×0.7·§7 티어 승격 금지 규칙) +
사이징 분포 전후 B-수치 + 사용자 게이트. 조건 없는 "나중에 재검토"는
금지(P2-1a 형 도피 방지).

## 4. 기준선 실측 (재개봉 시 전후 비교의 고정점 — 2026-07-24)

- 표본: 실전 `weekly_classification` entry/watch 219행(05-19~07-23) +
  `backtest_classification` 4,027행. 사이징은 `calculate_entry_params`
  실함수 호출로 산출.
- **flag 보유율 96~98%** (최빈: unfavorable_market_context, late_stage_base,
  extended_from_ma, wide_and_loose/handle_quality).
- 빈도가중 평균: **현행 3.22(실전)/3.33(백테스트) pp vs 역할분리안
  5.27/4.86 pp** — 두 안이 갈리는 행 93%/91%.
- 최빈 갈림: 현행 3.0(바닥) → 분리안 5.0 (Δ+2.0pp).

## 5. 이행 내역 (명문화 3곳)

- `entry_params_calc.py` §3 티어 블록 주석(no_flags 부근) — 의미론+예시+
  신설 flag 기본값+재개봉 참조
- `threshold-change-checklist.md` — flag 신설 가이드 1줄 + 적용 이력
- web `entry-params-fields.ts` suggested_weight_pct 설명 — 이중 작용 명시

## 6. Superseded (2026-09-08, #153 — 동결 해제가 아니라 **대체**)

production 사이징이 티어×배수 구조에서 **리스크 역산**(Minervini TTLC Ch.8, 백테스트와 동일:
R 1.25% ÷ stop 8% → full 15.625%, 파일럿 50%)으로 교체되어 본 문서의 이중 작용 구조 자체가
소멸했다. 근거(#153 Phase A 실측):
- go_now 0건 → 이 구조는 production 에서 한 번도 실행되지 않았다.
- trigger_evaluation_log 121행 가정 계산에서 3.0pp 바닥 포화 80%(97/121) → 이중 작용의 실효 없음.
- 수량은 positions 수동 입력(`--qty`) → 시스템이 사이징을 강제하지 않았다.
- 백테스트는 이미 리스크 역산 사용 → 방법론 불일치.

§3 재개봉 조건(수익성 판독·#74 F1~F4 첫 판독)은 이 구조에 대한 것이므로 **소멸**. #74 F1~F3
발화 시 제재 "사이징 ×0.5" 는 "해당 코호트 R × 0.5(0.625%)" 로 재매핑(#74 spec §7 부록).
구 정의 원문(티어·배수·바닥·absolute/logical/sma50 스탑)은
docs/superpowers/plans/2026-09-08-issue153-risk-backed-sizing.md §2 에 보존. 이슈 #80 클로즈.
