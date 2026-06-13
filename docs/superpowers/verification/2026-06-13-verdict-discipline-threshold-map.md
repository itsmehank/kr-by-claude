# 임계 변경 의존성 맵 — 분류 verdict 규율 (A)

> `docs/superpowers/threshold-change-checklist.md` (b) 2축 판정 적용본.
> 트리거: thresholds.py 신규 상수 8종 + 재사용 상수 3종의 신규 소비처 + 연동 prompt 임계 텍스트.
> 스펙: `specs/2026-06-13-classification-verdict-discipline-design.md`. 구현: VD-1~8.

## 1단계 (파생 신호)

신규/재사용 임계 → 만드는 파생값:
- `CLIMAX_*` (8종) → §6.1 climax_run flag (force-ignore 조건)
- `TOPPING_BELOW_10W_WEEKS` → §6.2 topping_distribution flag (force-ignore 조건)
- `STOCK_DISTRIBUTION_COUNT_25D` → §6 stock-distribution flag(demote) + §6.2 T-D(force-ignore)
- `CUP_DEPTH_MAX_NORMAL_PCT` → cup depth gate(pattern) + §5.2 wide_and_loose 구조결함(신규)
- `BREAKOUT_VOL_FLOOR` → low_volume_breakout(일봉, 기존) + §6.1 anchor(주봉, 신규)

## 2단계 (소비 룰)

`grep -rn` 으로 식별한 소비처 (Python + prompt):
- climax_run / topping_distribution flag → **§5.1 매핑** → classification=ignore → `weekly_classification` → 평일 트리거 경로(`load.get_active_monitoring`: entry/watch 만 감시) **제외**
- §6 stock-distribution flag → §5.1 demote-to-watch (ignore 아님)
- 모든 verdict 산출 = LLM prompt 판정. **Python 에 classification=ignore set 경로 없음**(전수 grep 확인: `gates.py:51` backstop 은 watch 까지만 강등; `disqualify` 는 별도 `disqualified` 이벤트). → ignore 의 단일 기제 = §8/§5.1/§6.1/§6.2/§1 prompt 텍스트(§1 = reverse-split 데이터-무결성 force-ignore, 조건부·clean post-split base 카브아웃).
- ⚠ **비대칭 주의(미래 코드)**: `reverse_split_distortion` 은 "§1 조건이면 항상 emit + verdict 는 *조건부* force-ignore(clean post-split base 면 normal)" 이라, `climax_run`/`topping_distribution`("게이트 충족 시에만 emit, emit=곧 force-ignore")과 비대칭. 현재는 안전 — verdict 는 LLM 단일 산출이고 flag 로부터 Python 이 재도출하지 않음. **단 미래에 "force-ignore flag 존재 ⟹ classification=ignore" 를 가정하는 분석/집계 코드를 작성하면 reverse_split 카브아웃 케이스(flag 有 + verdict=normal)가 예외가 됨** → 그런 코드는 §1 카브아웃을 명시 처리할 것.

## 3단계 (룰 내부 고정 상수) — 2축 판정

| 상수 | 값 | 축1 환산? | 축2 영향? | 책정합 | 후속 |
|---|---|---|---|---|---|
| `CLIMAX_GAIN_PCT` | 25 | 부분(σ 보정 후보지만 종목레벨 미적용) | 있음 — climax force-ignore 빈도 직접 결정 | PRESERVES (HMMS p.262-3) | 보정 후보. 현재 정량 정의 복원이 목적 → B-수치(재백필로 climax 정확도 확인) |
| `CLIMAX_GAIN_WINDOW_WEEKS` | 3 | 불가(시간) | 있음(측정 창) | PRESERVES (TTLC '1-3주') | 모니터링(책 명시 창). SSOT 블록 등재 → drift 보호 |
| `CLIMAX_UP_DAYS_PCT` / WINDOW | 70 / 7-15 | 불가 | 있음(T4 트리거) | PRESERVES (TTLC Ch.9) | 모니터링. WINDOW_MIN/MAX(7/15) SSOT 블록 등재 → drift 보호 |
| `CLIMAX_MATURITY_WEEKS` / LATE | 18 / 12 | 불가(시간) | **있음** — P1 하드 전제, climax 발화 가부 좌우 | 숫자 PRESERVES (HMMS p.263 'usually'), **적용 EXTENDS** | **B-수치**: 적용이 EXTENDS 이므로 값 변경 시 §6.1 재검증 필수(drift 테스트가 이 신호 전달). 'usually' 수식 = 하드컷 아님, 재백필로 18/12 경계 종목 확인 |
| `TOPPING_BELOW_10W_WEEKS` | 8 | 불가(시간) | 있음(§6.2 T-B) | PRESERVES (HMMS p.269) | 모니터링 |
| `STOCK_DISTRIBUTION_COUNT_25D` | 4 | 불가(카운트) | **있음** — §6(demote) + §6.2 T-D(force-ignore) 이중 소비. 값↓ 시 양쪽 발화↑ | **DESIGN-JUDGMENT** (분배 개념 책, 카운트 4 는 IBD convention) | **B-수치**: §6.2 force-ignore 에 영향하므로 천정종목 재백필로 4 의 정합 확인. G0(10주선 아래)가 §6.2 쪽 추가 엄격화 |
| `CUP_DEPTH_MAX_NORMAL_PCT` | 33 | 부분 | **있음** — 기존 cup gate + 신규 §5.2 wide_loose 구조결함 이중 소비. 값 변경 시 두 룰 동시 이동 | PRESERVES (O'Neil cup depth) | 모니터링(기존 검증된 값, 신규 소비처는 재사용이라 값 불변) |
| `BREAKOUT_VOL_FLOOR` | 1.4 | 부분 | **있음** — low_volume_breakout(일봉) + §6.1 anchor(주봉) 이중 소비. **단 baseline 차원이 다름**(50일 vs 50주) | PRESERVES (HMMS p.117 '40-50%') | 모니터링. ⚠ dimension 주의: 상수는 무차원 배수 1.4, baseline(일/주)은 사용처 지정 — 혼선 금지 |

## 소비 경계 (1줄)

`risk_flag/§6.1/§6.2 → §5.1 매핑 → classification(ignore/watch) → weekly_classification → 평일 트리거 경로(get_active_monitoring: entry/watch 만) 포함/제외`. (하류는 평일 evaluate_pivot 단일 경로 — 내부 2차 파생은 entry-params 사이즈 로직(late_stage ×0.7)뿐, §5.1 demote 와 정합.)

## 합격 조건 (게이트) self-review

1. 의존성 맵 섹션 존재 ✓
2. 소비 룰의 3단계 고정상수 행 포함 ✓ (8 신규 + 3 재사용 전부)
3. 축1/축2 전 행 기입 ✓
4. 축2 "영향있음" 행의 후속: CLIMAX_GAIN_PCT·MATURITY·STOCK_DIST_COUNT = B-수치(재백필 검증 예약), CUP_DEPTH·BREAKOUT_VOL = 모니터링(근거: 재사용·값 불변), 나머지 PRESERVES = 모니터링(책 명시) ✓ — 근거 없는 모니터링 도피 없음
5. 소비 경계 1줄 존재 ✓

## §6.2 ~99% inert — VD-11 사전검증 발견 (2026-06-13)

§6.2/`TOPPING_BELOW_10W_WEEKS`/`STOCK_DISTRIBUTION_COUNT_25D`(T-D) 소비처는 사실상
도달 불가. force-ignore 후보 풀 필터 minervini **C5 = `close > sma_50`**(50일선) 과
§6.2 **G0 = 주봉 close < 10주선**(≈50일선) 이 충돌 → G0=참 ⟹ C5=거짓 ⟹ TT 탈락 ⟹
상류 제외. 전 종목 실측: G0 주 98,255 중 daily minervini 동반 743(0.76%, MA 교차 노이즈).
→ **§6.2 force-ignore 도메인 ≈ ∅**. confirmed topping 은 minervini 스크리너가 exclusion-
by-default 로 처리. `TOPPING_BELOW_10W_WEEKS`·T-D 카운트는 경계 노이즈에만 영향 →
값 변경 영향도 무시 가능(B-수치 재백필 불요). 상세: spec §5.1-bis. 처리=경량 유지+문서화.

## 검증 아티팩트

VD-11 백필 = **SK하이닉스 false-positive 단독**(§6.2 천정 쪽은 inert 로 검증 불가 → 스킵).
이 맵의 B-수치 중 climax 정확도(`CLIMAX_GAIN_PCT`·18/12주 경계)를 실측 확인.
§6.2 T-D 항목은 위 inert 발견으로 moot. 결과는 `data/expert-inquiry/validation_results.md`.
