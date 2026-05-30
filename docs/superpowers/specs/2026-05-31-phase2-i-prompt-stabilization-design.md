# Phase 2 (i) — prompt 안정화 (cup-shape 결정론화 + 3층 분해)

> **재개 순서상 최우선** (2026-05-31). Phase 1 2-A 프로덕션 검증이 발견한 *gate inert* 병의 주 치료.
>
> **하드 게이트**: 본 사이클의 *재측정* (cup-scoped 트리 전 가지 안정 + 005850 → 안정 watch + handle_quality) 통과 전까지 2-B / 2-C / 2-D 진입 금지.
>
> **이유**: 2-A 후처리 gate 가 LLM 의 비결정적 pattern 라벨에 종속 → 대부분 inert (`cup_with_handle` 1/5, entry 0/5; `verification/2026-05-31-phase1-2a-prod-validation/`). 2-B/C/D 도 동일 라벨-게이팅이라 같은 병 → prompt 안정화가 *주 메커니즘*, 후처리는 backstop 으로 강등.

## 0. 방향 / 성공 정의

프로덕션 검증(2026-05-31)이 정량화한 핵심: 바이트-동일 입력에 LLM 의 `pattern` 라벨이 비결정적(`cup_with_handle` 1/5). 차트·CSV 바이트 동일 → 입력 열화 아님, 순수 LLM 판정 비결정성. 후처리 gate 는 LLM 이 non-null pivot/base 를 줬을 때만 발화하므로 4/5 의 `pattern=none` 에서 inert.

**근인 진단**: `pattern` 단일 칸이 *3개의 별개 판단* 을 융합하고 있음 — 모양(shape), 핸들 품질(handle quality), 매수가능성(verdict). LLM 이 회차마다 "구조는 cup"(→`cup_with_handle`) vs "핸들 나빠서 못 산다"(→`none`)를 번갈아 보고. 둘 다 현 prompt 에서 방어 가능 → 흔들림. O'Neil(HMMS Ch.2)은 faulty handle(위로 wedging / 하단 절반 / 10주선 아래)도 **여전히 "cup-with-handle"이라 부르고** 단지 "failure-prone"으로 평가 — 모양과 매수가능성은 별개 질문이다.

**성공 정의** (바이트-동일 입력에 대해):
1. **shape 판정이 feature 층에서 재현** — 측정값(depth%·선행상승% 등)이 회차 간 안정, 그 함수인 라벨도 안정.
2. **verdict 재현** (entry/watch/ignore).
3. **faulty handle 시 재현 가능한 watch + handle_quality 인용.**

→ `cup_with_handle` 라벨 카운트는 (1)에서 도출되는 *파생 검증치* 이지 일차 타깃이 아님.

**★ 범위 스코핑 (필수 — 오독 방지)**: (i)의 활성 결정 트리는 **`cup_with_handle` 검증 *전용*** 이다. Gate2(U/V)·Gate3(핸들)이 컵 전용 게이트이고 §6 음성 패널도 전부 컵 경로(→none)이므로, 설계 전체가 cup-scoped. **`flat_base` / `vcp` / `double_bottom` 분류 안정화는 (i) 범위 밖** (§8 비목표). 따라서 §0의 "shape 안정화" = *cup-shape 안정화* 를 뜻한다.

## 1. 3층 분해 (책-충실 핵심)

| 층 | 질문 | 성격 | 소유 |
|---|------|------|------|
| **shape** | cup 구조인가? | 구조적 *사실* (depth/기간/U-vs-V/핸들존재 = 측정값) | LLM (허용밴드) |
| **handle quality** | 핸들이 적법한가 faulty 한가? | 핸들 측정값의 결정론 판정 | 코드(backstop) + prompt 자기보고 |
| **verdict** | 그래서 사도 되나? | entry / watch / ignore (= shape + quality + 시장(M) + **돌파 거래량 확인**) | monotone-combine |

**verdict 입력에 돌파 거래량 확인 포함 (분해 누락 금지)**: 돌파는 50일 평균 대비 **≥1.4~1.5× 거래량** 이 핵심 확인 기준(O'Neil HMMS / Minervini). 약한 거래량 돌파 → `low_volume_breakout` → entry 아닌 watch. ⚠ §2 measurement 의 `handle_volume_ratio` 는 *핸들 거래량 dry-up*(품질/VCP 특성)이라 **돌파 거래량 확인과 별개** — 혼동 금지. 기존 prompt 가 보유한 market-direction(M) + breakout-volume 게이트는 verdict 층에 **그대로 유지**(분해로 누락하지 말 것).

**불가침 규칙**:
- faulty handle 도 shape = `cup_with_handle` **유지** (handle_quality 발화 → verdict=watch). shape 를 `none` 으로 강등하면 방금 분리한 shape/quality 를 다시 한 칸에 합치는 **원래 버그 재발**.
- "when in doubt → none" 식 보수성은 shape 가 아니라 **verdict 층** 으로 내린다.
- 과잉강제 금지: 목표는 "always cup" 이 아니라 **"같은 feature → 같은 판정"**. V자 / depth>33% / 선행상승<30% 면 `none` 이 맞고, *그 none 도 안정적이어야* 한다.

## 2. 측정-우선 scaffolding (주 메커니즘 — analyze prompt)

근거: 책의 실제 방식이 측정-우선(Minervini footprint = Time/Price/Symmetry 숫자, 예 "40W 31/3 4T"; O'Neil 정량 기준; Minervini 의 "general appearance 게슈탈트" 명시 경고). 핵심 효과 = **결정해야 할 차원을 낮춤** — depth%·선행상승% 는 같은 OHLCV 바이트에서 나오는 *저차원 산술 읽기*, "무슨 모양 같나" 는 *고차원 퍼지 판단*. 후자를 전자의 함수로 묶는다.

### 2.1 measurement = 정식 출력 스키마 필드

(reasoning 내부 산문 아님 — 재측정 게이트가 "feature 가 회차 간 안정한가" 를 기계 측정하려면 숫자가 정식 필드여야 함.)

신설 필드(cup 경로):
- `prior_uptrend_pct` (선행상승 %)
- `cup_depth_pct` (장중 high/low 기준 — §4)
- `cup_shape` (`U` | `V`)
- `handle_status` (`legitimate` | `faulty` | `not_formed`)
- `handle_position` (`upper_half` | `lower_half`)
- `handle_vs_sma50` (`above` | `below`) — O'Neil "10-week MA" → 시스템 일봉 50일선 매핑
- `handle_drift` (`down` | `flat` | `up`)
- `handle_depth_pct`, `handle_volume_ratio`

### 2.2 결정 트리 = 책 의존성 순서 (cup-scoped)

진입: "cup 계열 기하인가" 1차 라우팅 통과 종목만. (1차 라우팅은 기존 분류 로직 유지 — (i) 가 새로 만들지 않음.)

```
Gate0  선행상승 ≥ PRIOR_UPTREND_CUP(30%)?      아니오 → none
Gate1  cup_depth ≤ DEPTH_CUP(패턴×시장, §4)?    초과 → none
Gate2  U자 vs V자?                              V → none
Gate3  핸들 상태? ──┬─ 적법         → cup_with_handle (entry 후보)
                    ├─ faulty       → cup_with_handle + handle_quality → watch
                    ├─ 미형성        → cup_with_handle + handle_status:not_formed → watch  (none 아님!)
                    └─ cup 구조 아님 → none
```

**불가침**: 트리에 **"핸들 faulty → none" 가지 절대 금지** (재융합). 그리고 **"핸들 미형성 → none" 도 금지** — 형성 중 cup 은 shape=cup, verdict=watch (매수점 없음 = verdict 판단이지 shape 판단 아님). O'Neil 의 진짜 "cup-without-handle" 은 *완성된* cup 이 핸들 없이 돌파한 경우라 형성 중에 그 라벨 붙이면 조기 오분류 → taxonomy 신규값은 별건 보류.

### 2.3 허용밴드 (경계 칼날 금지)

LLM 숫자 읽기는 근사(±5% 노이즈 허용 정책). depth 가 33% 근처 0.5% 흔들림으로 cup↔none 뒤집히면 안 됨 → 경계에 허용밴드. **±5% 는 잠정 시작값이며 Q2 의 'depth read 회차간 분산'으로 calibrate (고정상수 아님 — §5 calibration-target)**. 경계에서 *계속* 흔들리는 측정값은 코드 계산으로 "졸업"이 정답(=(ii) 신호, 본 trip 의 실패가 아니라 진단 결과).

## 3. backstop 권위 관계 (좁은 gap-filler)

후처리 gate(`gates.py`)는 prompt 가 *놓친* false-positive 만 잡는 좁은 안전망.

### 3.1 monotone-combine (detector 없음)

"prompt 가 이미 처리했나" 감지기를 만들지 않는다. 두 층 결과를 보수적으로 합친다:

```
final_verdict        = most_conservative(prompt_verdict, backstop_verdict)   # ignore > watch > entry
final_confidence     = min(prompt_conf, backstop_cap)
entry_params_block   = prompt_block OR backstop_block
```

본질적으로 **멱등 + 순서무관**: watch 를 다시 watch 로 내려도 no-op, conf cap 도 min 이라 중복 적용 없음. backstop 은 verdict==entry 일 때만 의미 있음(watch/ignore 강등은 정의상 no-op) → 자연 멱등. 별도 detector 불요.

### 3.2 헌법 — backstop 에 기대하지 말 것

1. **기생적**: handle_quality 는 LLM 이 non-null pivot/base_start 줬을 때만 발화. `pattern=none` → null → inert (프로덕션 검증의 그 발견). **4/5 none 은 backstop 이 못 고친다 — 전적으로 §2 소관.**
2. **비대칭**: false positive("entry 인데 핸들 faulty"→watch)만 잡음. **false negative("none 인데 사실 valid cup")은 못 잡음** (monotone 이 none→cup 승격 불가 + none 이면 경계 null 이라 코드가 계산조차 불가). 4/5 none = 정확히 이 false-negative 류.

## 4. depth 정의 + 단일소스 (Q5)

- **장중 high/low** 채택. 근거: O'Neil/Minervini 의 depth 는 absolute peak→absolute low = 바차트 장중 극값. 종가 아님 = 책-충실. (005850 ratio_a 0.791 장중 / 0.690 종가 흔들림을 "종가로 바꿔" 덮는 건 책-충실 희생이라 금지.)
- **(i)에선 단일 권위 depth 불필요**: 단일패스 파이프라인(`build payload → LLM 1회 → 후처리`)에서 코드의 정밀 depth 는 LLM 출력의 하류라 *같은 호출에 피드백 불가*. shape=LLM(밴드) + verdict=monotone-combine 이 이미 "라벨 vs 게이트" 불일치 클래스를 제거 — shape 는 순수 LLM 소유라 코드가 라벨을 못 바꾸고, 코드 정밀 depth 는 오직 verdict(handle_quality→강등)에만 기여. 두 depth 숫자가 *다른 층* 에 살아 "같은 숫자" 일 필요 없음.
- **단일소스 주입은 (ii) 연기** (부트스트랩상 단일패스 불가; §8).

## 5. SSOT 이관 (thresholds.py)

### 5.1 이관 대상 + 구조

**★ 단일 스칼라 금지 — 패턴별 표** (현 prompt §4 표 구조 그대로 SSOT화):

| 상수군 | 값 | 출처 라벨 |
|---|---|---|
| depth (패턴×시장) | cup 정상장 ≤33% / 약세장회복 ≤50% · flat ≤15% · vcp ~25% · double 별도 | **book-anchor** (O'Neil/Minervini) |
| 선행상승 | cup ≥30% · flat ≥20% | **book-anchor** |
| min_base_weeks | cup 7 · flat 5 · double 7 · vcp 5 | **book-anchor** |
| 핸들 깊이 8~12%(bull) · 상단절반 · 10주선(→50일선) · ≥1주 | — | **book-anchor** |
| `DEEP_HANDLE_RATIO` 0.33 | 컵깊이 대비 핸들깊이 비 | **heuristic** (책 8~12% 절대치와 reconcile 필요 — trace 주석) |
| `VOLUME_NOT_CONTRACTING_RATIO` 0.80 | — | **heuristic** |
| 허용밴드 ±5% | — | **heuristic · calibration-target (고정상수 아님, Q2 보정)** |
| failed_breakout `K_DAYS` 5 / `CONSECUTIVE_BELOW` 2 | — | **heuristic** |

- **depth = 패턴 × 시장 2축**: 약세장회복(`market_context` downtrend→uptrend 전환 within 60 sessions) cup ≤50%. F3(cup depth 50% 예외 연속화)가 여기 묶임.
- **book-anchor vs heuristic 라벨 + 출처 주석 필수** (메모리 원칙 — "못 바꾸는 책 숫자냐 튜닝값이냐" 혼선 방지).
- 10주선 → 50일선 매핑 코드/주석 명시.
- §2 트리·§4·flat 20% 등 **다패턴 표는 '향후 다패턴 트리용 SSOT'** 임을 주석 (현재는 cup 행만 (i) 트리가 소비).

### 5.2 prompt 동기화 = (A) 수동 + drift-detection 테스트

(i)는 *안정화* 작업이지 인프라 확장이 아니므로 prompt auto-sync 인프라(backlog SSOT-1)는 짓지 않는다. 대신:
- prompt 임계를 .md 상단 **구조화 threshold 블록** 에 모음 (산문 분산 금지 — 파서 brittle 방지). 본문은 그걸 참조.
- **drift 테스트 양방향**: ① prompt 숫자 ↔ thresholds.py 일치 assert. ② **orphan 검출** — thresholds.py 의 prompt-대상 상수가 prompt 에 실제 등장하나(코드만 바뀌고 prompt 미반영 케이스).
- 재발 시 (C) 타깃 placeholder 주입 → (B) auto-sync 로 Wake-trigger 졸업.

### 5.3 ★ 의존성 맵 (CLAUDE.md 의무 — 선택 아님)

thresholds.py 를 건드리므로 `threshold-change-checklist.md` 2축 맵 필수. **1순위 셀**: depth 변경 시 (각 패턴 행) × (정상장 / 약세장회복) 전 조합 + F3 트리거(market_context 전환 감지) 동시 점검. 추가 점검: `wide_and_loose`(2-B) · `status.py`. 이 맵은 본 spec 의 일부로 작성.

## 6. verify prompt 6차원 (필수 갱신 — stale = 위험)

stale verify 는 옛 게슈탈트 방법론을 담고 있어 신구조("faulty handle 이어도 shape=cup→watch")를 "none 이어야 하는데 틀림"으로 *오판 disagree* → 분석가를 재융합으로 끌어당김. 갱신은 필수.

차원(재측정 게이트의 진단축과 같은 언어):
- **(a) 측정 정확성** — 보고 숫자가 차트와 일치? 검증자도 LLM read 라 **같은 허용밴드 상속**. 밴드 초과 또는 *트리 결과를 바꾸는* 차이만 flag (false precision/nitpick 금지).
- **(b) shape** — 측정값에 트리 Gate0~3 가 올바로 적용? (위 cup-scoping 상속, SSOT 재계산.)
- **(c) handle_quality** — 발화/미발화가 핸들 measurement 와 정합?
- **(d) verdict** — shape + quality + 시장이 monotone(보수)하게 결합?
- **(e) layer-분리 무결성** (신규·핵심 guardrail) — **체크 규칙**: shape=none/강등의 *정당화* 를 감사. 구조적 실격(컵없음/V자/depth>33%/선행상승<30%) → 정상. 품질·tradability 이유(핸들나쁨/매수점없음/위험) → **재융합 → disagree**. 역방향도(shape=cup 인데 정당화가 tradability → flag). **shape 주장은 오직 구조 feature 로만 정당화.**
- **(f) reasoning 논리 + 인용 정확성.**

- **출력 = 6 정식 필드** (reasoning 흡수 아님 — (e)가 guardrail 이려면 추적 가능 discrete 신호여야 regression 체크 "수정 후 layer-분리가 disagree 로 뒤집힌 적?" 가능).
- **확장 매핑(재작성 아님)**: old `pattern` → (a)+(b)+(e) 분화 / `classification` → (d) / `risk_flags` 유지 + handle_quality → (c) 특화 / `reasoning` → (f).
- **역할 경계**: verify 는 대조자이지 제2의 분석가 아님. 밴드 내 차이 존중("disagree 로 보이려 disagree 말 것").

## 7. handle_quality = 14번째 risk_flag

analyze prompt 의 risk taxonomy 13 → 14 (handle_quality 추가). verify 의 risk_flag 전수 점검 목록도 14. handle_quality 는 *품질 층* flag(faulty 핸들 발화)이지 shape disqualifier 아님 — 이 의미를 양 prompt 에 명시.

## 8. 범위 경계 (비목표 — 명시 연기)

- **(ii) OHLCV 독립 base/handle 검출** = 연기. Q2 가 특정 측정값의 경계 불안정을 *입증* 할 때만 그 측정값에 한해 "코드 졸업". 전면 OHLCV 독립 검출은 패턴 재분류 룰과 얽힌 큰 스코프.
- **단일소스 depth 주입 / 두-패스 LLM** = 연기 (§4).
- **prompt auto-sync 인프라** = 연기 (§5.2, Wake-trigger 졸업).
- **`flat_base`/`vcp`/`double_bottom` shape 안정화** = 연기. (i) 트리는 cup-scoped. 다패턴 pre-routing → 패턴별 게이트는 (i) 후속.
- **taxonomy 신규값 `cup_without_handle`** = 보류.

## 9. 실행 순서 (plan 에서 상세화)

1. **SSOT 이관** — thresholds.py 패턴별 표(book/heuristic 라벨) + 의존성 맵 checklist + drift 테스트(양방향).
2. **analyze prompt** — measurement 정식 필드 + 트리 Gate0~3(4분기 명시) + 허용밴드 + 14th flag. (DB: weekly_classification measurement 컬럼.) **기존 market-direction(M) + breakout-volume(≥1.4~1.5×) 게이트는 verdict 층에 유지 — 분해로 누락 금지(§1).**
3. **verify prompt** — 6차원 + layer-분리 체크규칙 + 6 정식 출력 필드.
4. **backstop** — `gates.py` monotone-combine 리팩토링 (detector 제거). **monotone 결합 입력에 기존 breakout-volume/M 게이트 포함 유지 확인.**
5. **재측정 게이트 → 2-B/C/D 해제** (★ **build-first 확정**):
   - **타이밍 = build-first** (diagnose-first 아님). 근거: 밴드 calibration 이 필요로 하는 건 *새 프롬프트가 depth 를 명시 요청했을 때의 회차 분산* 인데, 옛 프롬프트는 depth 를 암묵적(게슈탈트 부산물)으로 읽어 분포가 다름(통상 더 좁음) → 옛 분포로 맞추면 *틀린 분포에 calibrate* (diagnose-first/hybrid 공통 함정). 또 스캐폴딩이 무조건 적용(low-regret)이라 사전 진단이 가지칠 분기가 없음.
   - **Q2 역할(이동)**: 스캐폴딩(step2)은 진단과 *무관히 무조건 적용*. 따라서 Q2 는 "어느 fix 할지 결정"이 아니라 **fix 후 검증 + 밴드 calibration + 잔여 진단** (= §10 진단형 게이트가 그 자리).
   - **±5% = 고정 시작값** (기존 정책값). 고정 밴드로 build → 1회 재측정이 calibration 겸 검증 → "스캐폴딩이 먹혔나"를 밴드폭 선택과 *분리* 해 깨끗이 읽음(confound 제거). 재측정에서 feature 가 밴드 straddle 로 흔들리면 → **그때 밴드 폭 수정 후 step2 1회 재방문**.
   - **측정 스펙**: 005850 5+회 — 선행상승%·depth%·U/V·핸들위치·50일선 대비·drift·핸들거래량 + **각 측정값 회차간 분산**(특히 depth, 밴드 calibration 입력).

## 10. 재측정 HARD GATE (수용 기준)

**본질 = '함수가 결정론적인가' 확인** (동전 편향 추정 아님). shape 를 측정값의 결정론 함수로 못박았으므로 결정론 함수는 2/10 안 뒤집힌다.

- **1차 바 = feature 재현성 near-unanimous (9~10/10, band-containment)**. 80% 를 목표로 두지 말 것.
- **N=10** ('강한 신뢰' 아님 — 8/10 → 95% CI ≈44~97%, '합리적 신호' 라벨).
- **게이트 = 1비트 아닌 진단** (수정처가 다름):
  - feature 안정 + verdict 안정 → **청정 통과**
  - feature 안정 + verdict 흔들 → **트리/precedence 구멍** (§2 수정)
  - feature 흔들(밴드 straddle 32/34) → **측정 문제 (#2 졸업 / (ii))**
- **음성 패널 = 결정트리 가지마다 1개** (책 disqualifier ↔ 트리 가지 1:1, 실패 시 어느 Gate 깨졌는지 판별):

| 가지 | 케이스 | 기대 (안정) |
|---|---|---|
| Gate0 음성 | 선행상승 <30% | none |
| Gate1 음성 | depth >33% / wide-loose | none |
| Gate2 음성 | 진짜 V자 | none |
| Gate3 음성 | 005850 faulty handle | watch + handle_quality |
| 양성 | 적법 핸들 cup (상단절반·50일선 위·하향 drift·거래량 dry-up) | entry/watch |

- "게이트 통과 = cup-scoped 트리 전 가지 안정 작동 증명" (단순히 005850 안정 아님).
- 5종목 × N=10 ≈ 50 호출/사이클 (1회성 수용).
- **티커 선정은 plan/구현 단계** — V자/wide-loose/선행상승부족 사례를 데이터에서 실측 확인해야 정직한 음성.

## 11. Authoritative sources

- 프로덕션 검증(병의 정량): `docs/superpowers/verification/2026-05-31-phase1-2a-prod-validation/FINDINGS.md`
- 2-A 코드 상태: `docs/superpowers/verification/2026-05-30-phase1-2a/FINDINGS.md`, `docs/superpowers/specs/2026-05-29-phase1-2a-design.md`
- 임계 절차: `docs/superpowers/threshold-change-checklist.md` · SSOT: `kr_pipeline/common/thresholds.py`
- 거시 로드맵: `docs/PROJECT_ROADMAP.md` §5
