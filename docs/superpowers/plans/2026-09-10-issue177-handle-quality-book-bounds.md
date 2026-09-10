> **[기록 문서]** 본 문서의 규약 문장은 작성 시점 기록이며, 현행 규칙은 `docs/superpowers/governance.md` 절 ID를 따른다 (#155, 2026-09-09).

# #177 — compute_handle_quality 를 책 경계로(재설계 아님): 조건 A 제거 + 책 최소 길이 강제

> 트리거: thresholds.py 상수 **삭제 2건**(HANDLE_DEEP_RATIO·HANDLE_MIN_DAYS) + 소비처 `handle_quality.py` 산술 변경
> — checklist (a) 사실 기준 해당(governance 2-1) → §4 의존성 맵. 신규 숫자 **0**(대체값 HANDLE_LEGIT_MIN_DAYS 5 는
> 기존 book-anchor). governance 인용: 1-1, 1-2, 1-3, 3-2, 3-3, 3-5.
> 같은 검출기의 재설계(시작점 규칙·창 상한·VCP/3C)는 **#175(보류)** 범위 — 교차 기록(#175 plan §3 참조).

## 0. 판정(전문가, 2026-09-10)

- 실전 저장본 영향 **0**(발화 36/36 이미 watch, demoted 0). 백테스트는 검출기 단독 강등 258·잃은 entry 7 —
  **holdout 재료 오염**. 재설계(#175)는 보류 유지. 지금은 **책 경계 강제 2건만**.
- 변경 성격: **book-fidelity**(책 근거 없는 조건 제거 + 책 하한 강제, governance 3-5). 성과 목적 아님.

### 정정 — 방법론 세션 오류 기록(원칙 3-6)
Phase A 회신에서 "잃은 entry 7건 전부 3~15일 핸들 → 책 하한 미달"로 서술했으나, 실제 하한(5일) 미달은 **4건**
(3·3·3·4일)이고 5일 2건·15일 1건은 하한 충족. 변경 2로 소멸하는 것은 4건. 15일 건(213420 2020-01-18)은 LLM
`handle_status=faulty ∧ verdict=entry` **자기 모순 사례** — 검출기가 LLM 비일관성을 잡은 경우로 별도 표기.

## 1. 변경(이것 두 개만)

### 변경 1 — 조건 A(깊이비) 제거, 상수 삭제
원칙 1-1 4조건: (a) 제약형 (b) 깊이는 프롬프트 §4 Gate3 가 절대 8~12%(HANDLE_DEPTH_BULL_*)로 담당 (c) 비율 방식은
깊은 컵의 정상 핸들(20% 컵의 7% 핸들 = 0.35)을 불량 처리 — 책과 충돌 (d) 계산 미정의 없음. **충족.**
원칙 1-3: 검출기 의도("품질 층")는 책 근거를 대체하지 않는다.

**정의 원문 보존(원칙 1-2)** — 구 `handle_quality.py` (A) 및 상수:
```
HANDLE_DEEP_RATIO: Final[float] = 0.33
"""[heuristic] 컵깊이 대비 핸들깊이 비 발화 임계. **trace 필요**: 책의 8~12% 절대치
(HANDLE_DEPTH_BULL_*)와 reconcile 미완 — 현재는 휴리스틱."""

# (A) deep handle — 깊이-퍼센트 비 (통일 공식 §3-2).
handle_depth_pct = (handle_high - handle_low) / handle_high * 100.0
ratio_a = handle_depth_pct / base_depth_pct
fired_a = ratio_a > thresholds.HANDLE_DEEP_RATIO
fired = fired_a or fired_b or fired_dist ; reasons: "deep_handle" ; metrics: ratio_a
```
handle_depth_pct 는 감사 echo(`metrics.handle_depth_pct`)로 남기되 판정 비관여.

### 변경 2 — 책 최소 길이 강제
검출 핸들 창 < **HANDLE_LEGIT_MIN_DAYS(5, book-anchor)** 면 핸들 미형성 → 검출기 **미평가(None)**. 5일은 평가(경계
포함). 근거: HMMS "핸들은 대개 1~2주 이상". 구 `HANDLE_MIN_DAYS: Final[int] = 3` `"""[heuristic] handle_quality 의
handle 구간 계산 최소 윈도우 (≠ HANDLE_LEGIT_MIN_DAYS 분류 게이트)."""` 삭제(원문 보존). 창 길이 사전 검사도
BASE_MIN_DAYS + HANDLE_LEGIT_MIN_DAYS 로.

### 불변
(B) 거래량비 0.80 · (D) 분배일 ≥1 유지(개념 book — HMMS 핸들 중 거래량 증가 금지·분배; 수치는 design, 별도 판정
대상). 시작점 규칙·창 상한 미변경(#175). Gate3(LLM) 불변. conf cap 유지(표시 전용 — Phase A A7). 2E_tier2 로직
불변(플래그 감소로 자연 축소).

## 2. 변경 파일

| 파일 | 변경 |
|---|---|
| `kr_pipeline/common/thresholds.py` | HANDLE_DEEP_RATIO·HANDLE_MIN_DAYS 삭제(삭제 기록 주석), HANDLE_VOLUME_NOT_CONTRACTING_RATIO docstring 에 개념 book/수치 design 표기 |
| `kr_pipeline/llm_runner/compute/handle_quality.py` | (A) 판정·reasons `deep_handle`·metrics `ratio_a` 제거, echo `handle_depth_pct` 추가; 핸들 창 하한 HANDLE_LEGIT_MIN_DAYS |
| `web/src/data/thresholds.generated.ts` | export 재생성(94 상수) |
| `tests/test_compute_handle_quality.py` | 재작성(13): A 부재 가드·echo·<5일 미평가·5일 경계 평가·B·D 회귀·skip 3종·Gate3 무영향·결정론 재현·adj |
| `tests/test_store_phase1_gate.py`·`test_gates_phase1.py`·`test_common_thresholds.py` | 시드를 5봉 핸들·거래량 발화로, mock reasons 명칭, 삭제 상수 재도입 가드 |

## 3. 측정(저장본 결정론 재계산 — triggered_rules metrics 로 사유 복원, 판정 아님, 변경별 분리)

| 표 | 지표 | 현행 | 변경 1만 | 변경 2만 | 둘 다 |
|---|---|---|---|---|---|
| weekly 36 | 발화 | 36 | 31 | 31 | **27** |
| | 검출기 단독 강등(LLM 비-faulty) | 4 | 3 | 2 | **2** |
| | 잃은 entry(demoted) | 0 | 0 | 0 | **0** |
| | tier2(go_now 제외) | 7 | 7 | 3 | **3** |
| backtest 585 | 발화 | 585 | 578 | 516 | **510** |
| | 검출기 단독 강등 | 258 | 258 | 224 | **224** |
| | 잃은 entry(demoted) | 7 | 7 | 3 | **3** |
| | tier2 | 254 | 253 | 225 | **224** |

사전 기록 기대 방향(전부 감소, weekly A 단독 5·<5일 5 소멸(겹침 1), backtest A 단독 7·<5일 69 소멸, 잃은 entry
7→3) — 관측치 일치. **잔존 3건**(B·D 발화, 길이 충족): 213420 2020-01-18(15일, B+D, LLM faulty ∧ verdict entry
자기 모순) · 160980 2021-04-10(5일, B+D, LLM legitimate) · 264660 2021-04-10(5일, B, LLM not_formed) — "검출기 vs
LLM 판단 불일치"로 기록. B·D 수치 검토는 별도 판정 대상, 이번 미착수.

**백테스트 armA-prod 표본 A+B**: 백테스트는 **저장본 verdict**(backtest_classification)를 읽고 저장본 in-place
재계산 경로가 없으므로(#175 A6) 검출기 변경으로 진입 집합이 **바뀌지 않는다**. 실행 결과 = #164 배포 후·#162
값과 동일(회신에 수치). 위 표의 백테스트 열은 "재수집 시 예상 변화"의 관측이며, 실제 저장본 갱신은 P0 재수집
(3-2) 때 이뤄진다.

## 4. 의존성 맵(2축 판정)

**1단계**: HANDLE_LEGIT_MIN_DAYS(5) → 검출기 핸들 창 하한(신규 소비) / HANDLE_DEEP_RATIO·HANDLE_MIN_DAYS →
소멸. **2단계**: `handle_quality.fired → gates.apply_phase1_gates → risk_flags handle_quality · verdict floor watch ·
conf cap · 2E_tier → entry_params 러너 go_now 제외(tier2)` / store 3테이블 triggered_rules.

| 고정 상수/룰 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| HANDLE_LEGIT_MIN_DAYS=5 (신규 소비처: 검출기) | 불가(시간) | **있음** — 발화 36→31(weekly)·585→516(backtest), tier2 7→3·254→225 | PRESERVES(HMMS 1~2주) | **holdout**(§5) |
| HANDLE_DEPTH_BULL_MIN/MAX 8/12 (Gate3) | 불변 | **없음** — 검출기 미소비 그대로, LLM 판정 불변 | PRESERVES | 없음 |
| HANDLE_VOLUME_NOT_CONTRACTING_RATIO 0.80 (B) | 가능(배수) | **있음** — A 제거 후 B·D 가 유일 발화 조건(잔존 3건 전부 B 계열) | 개념 book·수치 design | **관측 기록만** — 수치 판정 별도 |
| 분배일 ≥1 (D) | 가능 | 동상 | 개념 book·수치 design | 관측 기록만 |
| BASE_MIN_DAYS 5·HANDLE_POSITION_LOW_RATIO 0.33 | 불변 | 없음(가중 기록만) | heuristic | 없음 |
| TIER1/2_CONF_CAP 0.60/0.50 | 불변 | 없음(표시 전용, A7) | — | 없음 |
| 2E_tier2 → go_now 제외 | 불변 | **있음(간접)** — tier2 행 감소 | — | holdout |

**소비 경계 (1줄)**: `compute_handle_quality → apply_phase1_gates(risk_flags·verdict floor·conf cap·2E_tier) →
weekly_classification/backtest_classification 저장 → entry_params 러너 tier2 제외`. 하류 추적 안 함.
**게이트 점검**: 1 맵 ✓ 2 상수 행 ✓ 3 축1·축2 ✓ 4 영향 행 후속(holdout·관측) ✓ 5 경계 ✓

## 5. 사전등록(배포 전 기록)

1. 변경 성격: book-fidelity — 책 근거 없는 조건 제거 + 책 하한 강제(3-5). 성과 목적 아님.
2. 기대 방향: 발화·검출기 단독 강등·잃은 entry·tier2 전부 **감소**(§3 사전 기록 → 관측 일치). 백테스트 진입 집합은
   재수집 시 변동 예상, **방향 미예측**.
3. 사전 기준선: §3 현행 열 + armA-prod(exits 37 = stop8 19·decline 11·sma50 5·floor 2, final 1.1676).
4. 성과 판정: P0 재수집 후 **holdout 으로만**(3-2). 재실행 비교 금지(3-1). §3 수치는 관측 라벨(3-3).
5. 잔존 3건 = 검출기 vs LLM 판단 불일치 기록. B·D 수치는 별도 판정 대상(미착수).
