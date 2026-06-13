# 분류 verdict 규율 (A) — 설계 스펙

> 2026-06-13. SK하이닉스 백필 entry 0 → "주도주 watch 기아" 진단. 미너비니 전문가
> AI 4라운드 + 사용자 co-design 으로 확정. 후속(B: 재진입 패턴)은 별도 스펙.

## 0. 문제와 목표

SK하이닉스(2025-06~2026-06, +1,039%, RS 평균 94, 전 기간 TT 통과)의 주간 백필이
**entry 0 / watch 10 / ignore 37**. 진단: entry 0 은 정상(주말=후보선정, 평일=진입).
**진짜 결함은 ignore 37 — climax/extended 과대적용이 주도주를 평일 트리거 경로
(watch/entry 만 감시)에서 제외 = "watch 기아"**.

목표 분포 (책 기준, 재백필 검증):
- **ignore ≈ 4-6** (2026-05 진짜 climax 클러스터만)
- **watch ≈ 46-48** (베이스 형성·돌파대기·extended-holding)
- **entry ≈ 0~소수** (주간 스냅샷 특성)
- **유효 피벗 포착률 ≥ 90-95%** (분모 = 표준 베이스 피벗만)

## 1. 범위

**이번(A)**: §5.1 flag→verdict 매핑 · §5.2 wide_loose 측정 · §6.1 climax 재정의 ·
§6.2 topping · §8 ignore 가이드 교정 · thresholds.py 변경 · 양면 검증.
**후속(B, 범위 외)**: pullback_10w, three_weeks_tight, pattern enum 확장.

## 2. 핵심 기제 — pattern=none/demote-flag 의 잔존 ignore 경로 차단

**확인된 사실(코드 검증):**
- ignore 를 만드는 유일 경로 = LLM 의 §8 synthesis 텍스트. Python 경로 없음
  (`gates.py:51` backstop 은 `_most_conservative(prev, "watch")` — 강등 상한 watch,
  ignore 로 내리지 않음). 따라서 **§8 텍스트 교정만으로 ② 완결**.
- ETF 는 prompt 최상단 Pre-Check 가 별도 처리(instrument 스코프) — §5.1 무관, §8 에선 제거.

**§8 교정 (line 36, 291 두 곳 동일 리스트):**

변경 전:
```
- **ignore**: climax run, wide-and-loose, no base, late-stage with multiple
  high-impact flags, post-reverse-split distortion, or ETF.
```
변경 후:
```
- **ignore**: ONLY when §6.1 climax gate OR §6.2 topping gate is satisfied.
  No other condition produces ignore. "No base / forming base" is NOT ignore —
  it is watch (base_forming): a TT-passing leader without a current pivot is
  waiting for one, not disqualified. wide-and-loose / late-stage / extended /
  volume-contraction / reverse-split are DEMOTE-TO-WATCH or INFORMATIONAL per
  §5.1, never ignore. (ETF/fund handled upstream by the Pre-Check.)
```

cup-tree(`not_cup_family → none`)도 이 경로로 수렴: pattern=none 은 shape 판정일 뿐,
climax/topping 게이트 미발화 시 verdict=watch(base_forming). 기존 "경계 수렴 규칙"과
정합(이미 watch 로 수렴하던 방향의 완성).

**M3 — cup-tree "climax" 와 §6.1 의 layer 분리 (필수)**: cup-tree 1차 라우팅의
"명백한 climax run → pattern=none" 은 *느슨한 shape 휴리스틱*(pattern 결정)이고, §6.1 은
*엄격한 verdict 게이트*(ignore 결정)다. §5.1 이 "climax_run force-ignore = §6.1 충족 시"로
이미 바인딩하지만, cup-tree 의 느슨한 climax 가 §6.1 을 우회해 ignore 를 만들지 않도록
cup-tree 1차 라우팅 문구를 **"climax 형태(shape; verdict 는 §6.1 이 판정) → pattern=none"**
으로 명시 — climax_run flag 발화와 ignore 는 §6.1 게이트만이 결정한다.

## 3. §5.1 — risk flag → verdict 매핑 (신설)

risk flags 표 직후 삽입. flag 존재가 곧 verdict 가 아님:

- **FORCE-IGNORE (verdict=ignore, 평일 감시 제외) — 둘뿐**:
  `climax_run`(§6.1 충족), `topping_distribution`(§6.2 충족).
- **DEMOTE-TO-WATCH (verdict≤watch, 평일 경로 유지, entry-params 가 사이즈/손절 축소)**:
  `late_stage_base`(4th+, 평일 ×0.7), `wide_and_loose`(현 베이스 미매수·tighten 대기),
  `volume_contraction_on_advance`, `unfavorable_market_context`(§3.5 가 이미 watch 상한).
- **INFORMATIONAL (단독으로 verdict 불변)**: `extended_from_ma`, `faulty_pivot`,
  `narrow_base`, `low_volume_breakout`(평일 entry-gate 소관), `prior_uptrend_insufficient`,
  `reverse_split_distortion`, `thin_liquidity_us_only`.
- **결합 규칙**: ignore 는 FORCE-IGNORE 조건을 요구. DEMOTE/INFORMATIONAL 은 몇 개가
  겹쳐도 watch 로 cap 될 뿐 **ignore 로 합쳐지지 않음**.

근거: TT 를 매주 통과하는 Stage 2 주도주가 근시일 매수 돌파를 못 만드는 책-정당
사유는 blow-off(climax) 또는 top 뿐. 나머지는 "이번 진입이 더 작거나 신중" = watch +
평일 사이즈 로직(`calculate_entry_params §3.3` 이 late_stage ×0.7 적용 — 종목이 평일
경로에 도달해야 실행되므로 주말 force-ignore 는 이 로직을 죽은 코드로 만듦).

## 4. §6.1 — climax_run 게이트 (재정의)

- **Anchor (advance start = base-count 앵커, 동일 주)**: Stage 1→2 전환 — 직전 Stage 1
  (40주선 평탄/하락 아래) 후 첫 베이스를 주간 거래량 ≥ `BREAKOUT_VOL_FLOOR`(1.4×, 50주
  평균 — 50일 아님) 로 돌파하며 30주·40주선 상향전환·그 위로 올라선 가장 최근 주.
  **MA 입력**: 30주·40주선은 사전계산본이 아님 — LLM 이 104주 종가로 계산하거나 공급되는
  daily SMA-150(≈30주)·SMA-200(≈40주)으로 근사. 50주 거래량평균은 payload 의
  `weekly_ohlcv_recent_104w.adj_volume` 로 계산.
  104주 창 밖이면 P1 충족 간주 + baseline "left-censored" 라벨(창 왼쪽 끝을 가짜
  시작점으로 쓰지 않음).
- **Preconditions (ALL)**: P1 성숙도(앵커 후 ≥18주, 후기 베이스발이면 ≥12주) · P2(max
  1~3주 수익률 ≥25% AND 전체 advance 내 최고 가속).
- **Triggers (≥1, 전체 advance 기준)**: T1 최대 주간 고저폭 · T2 최대 주간 거래량 ·
  T3 일봉 exhaustion gap · T4 7~15일 중 ≥70% 상승일. 보조(단독 불가): SMA200 +70%.
- **E1 제외 (NARROW — 1·2차 베이스 돌파에만)**: 1·2차 베이스 돌파 3주 내 ≥25% =
  leadership(climax 아님). **3차+ 베이스 돌파엔 E1 미적용** — 후기 베이스 급등은
  blow-off 발생 지점이므로 게이트가 판정 (TLSMW Ch.5 pp.82-83). → 2026-05(5차 돌파)는
  E1 침묵 → P1+P2+T1 발화 → climax 정확히 유지.
- **Temporal scope**: 현재 주 조건만. climax 고점 후 >15% 조정 또는 4주+ 경과 = post-climax
  consolidation, climax_run 미발화. 과거 참조는 reasoning 에 "(history)" 표기(규칙2 예외).

## 5. §6.2 — topping_distribution 게이트 (신설, force-ignore)

- **G0 글로벌 전제(필수)**: weekly close < 10주선 일 때만 작동. (HMMS p.269 Breaking
  Support / Minervini Stage 4 = MA 아래). G0 가 정상 조정(주도주 최대 하락이 추세 중
  발생)을 force-ignore 하는 오발화를 차단 — SK하이닉스 검증: 03-06(-12.9%) 등 5/6 하락주가
  10주선 위라 trivially 침묵, 유일 G0-통과 주 08-22 도 T-A~D 미발화로 침묵.
- **Triggers (G0 ∧ ≥1)**: T-A 전체 advance 내 최대 주간 하락 · T-B 10주선 아래 연속 ≥8주
  (단일 종가 하회는 정상 눌림, topping 아님) · T-C 40주선(≈daily SMA-200) 하락전환 ·
  T-D 최대 주간 down-거래량 OR 분배 ≥`STOCK_DISTRIBUTION_COUNT_25D`(4).
  (T-D 의 "10주선 아래" 조건은 G0 가 이미 요구하므로 생략 — 중복 제거.)
- SK하이닉스는 in-window topping 없음 → §6.2 0 기여(false-positive 검증 전용).

## 6. thresholds.py 변경 (provenance 태그 필수)

| 상수 | 값 | provenance |
|---|---|---|
| `CLIMAX_GAIN_PCT` / 창 | 25% / 1–3주 | **PRESERVES** (HMMS p.262-3, TTLC Ch.9) |
| `CLIMAX_UP_DAYS_PCT` / 창 | 70% / 7–15일 | **PRESERVES** (TTLC Ch.9) |
| `TOPPING_BELOW_10W_WEEKS` | 8 | **PRESERVES** (HMMS p.269) |
| `CLIMAX_MATURITY_WEEKS` / late | 18 / 12 | 숫자 **PRESERVES** (HMMS p.263); **적용은 EXTENDS** (hard P1 gate keyed to advance-start). drift 테스트 목적 = "적용 결정, 변경 시 §6.1 재검증" |
| `STOCK_DISTRIBUTION_COUNT_25D` (신규 추출) | 4 | **DESIGN-JUDGMENT** (분배 개념은 책, 카운트 4 는 convention). 기존 §6 prompt 리터럴을 SSOT 승격. §6.2 T-D 가 상속 |
| (재사용) `BREAKOUT_VOL_FLOOR` | 1.4× | PRESERVES (HMMS p.117). §6.1 anchor 가 import, prompt 재박기 금지(drift). "50주 baseline" 만 규칙 주석 |
| (재사용) `CUP_DEPTH_MAX_NORMAL_PCT` | 33% | wide_loose 구조결함이 재사용(신규 40% 도입 금지) |
| **prompt 전용** wide_loose 상대폭 | 자기 6개월 중앙값 ×1.5 | **DESIGN-JUDGMENT** (O'Neil 정성 테스트 operationalize, 주석 명시) |

## 7. §5.2 — wide_and_loose 측정 (절대 10-15% 대체)

DEMOTE-TO-WATCH only (느슨한 베이스는 tighten 가능 — HMMS pp.140-143). 둘 다 충족 시 발화:
(a) 상대폭: 베이스 주간 고저폭의 다수가 종목 자기 6개월 중앙값 ×1.5 초과 (절대 10-15% 는
고변동 KR 주도주의 매주를 오발화 — SK 중앙값 ≈12%). (b) 구조결함: 깊이 >
`CUP_DEPTH_MAX_NORMAL_PCT`(33%) + erratic(V·wedging·매주 큰 스프레드). 데이터 증거:
wide_loose 8주의 spread 6.3~11.0% 가 종목 중앙값 12% 미만 → 과대적용 확정.

## 8. 의존성 맵 (threshold-change-checklist)

| 상수 | 기존 소비처 | 신규 소비처 |
|---|---|---|
| `CUP_DEPTH_MAX_NORMAL_PCT`(33%) | cup depth gate | §5.2 wide_loose 구조결함 |
| `STOCK_DISTRIBUTION_COUNT_25D`(4) | §6 stock-distribution flag | §6.2 T-D |
| `BREAKOUT_VOL_FLOOR`(1.4×) | low_volume_breakout(일봉) | §6.1 anchor(주봉, 50주 baseline) |

(작성 시 2축 판정표 — `docs/superpowers/threshold-change-checklist.md` 형식 — 별도 작성)

## 9. 검증 (양면 패널, 필수)

- **False-positive (SK하이닉스 47주 재백필)**: ignore ~4-6(2026-05 climax 클러스터만),
  §6.2 전 구간 침묵(특히 G0-통과 주 08-22), watch ~46-48. 유효 피벗 포착률 ≥90-95%
  (분모 = 표준 베이스 피벗 flat/cup/double_bottom/vcp 만; SK 실측 3피벗 전부 표준).
- **False-negative (분배형 천정 종목 1~2개 백필)**: (a) **non-climactic 확인 필수** —
  climax 형이면 §6.1 이 먼저 발화해 §6.2 미검증. (b) §6.2 가 천정 포착하는지 + **T-A~D 중
  무엇이 발화하는지 기록, 미발화 트리거는 "미검증"으로 정직 표기**. 종목 선정 = "minervini
  통과 → 분배형 천정 → Stage 4(10주선 아래 안착)" 조건으로 데이터 추출(구현계획서).

## 10. 테스트

- prompt drift-detection: thresholds.py ↔ prompt 임계 텍스트 정합(기존 Phase 2i 패턴).
  P1 18/12주 drift 테스트는 "변경 시 §6.1 재검증 필요" 신호 용도.
- `STOCK_DISTRIBUTION_COUNT_25D` 단위테스트 + §6/§6.2 가 이를 참조하는지.
- `topping_distribution` 를 `RISK_FLAGS_TAXONOMY`(risk_flags.py)에 등록.
- export_thresholds.py 재실행(웹 SSOT 동기화).

## 11. 범위 외 (YAGNI / B 후속)
pullback_10w, three_weeks_tight, pattern enum 확장, 8주 보유 룰 등 매도/포지션 관리.
