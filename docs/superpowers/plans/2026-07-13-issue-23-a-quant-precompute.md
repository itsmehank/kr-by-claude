# 이슈 #23 — A(analyze_chart_v3) 정량 섹션 부분 이관 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A 프롬프트의 6개 정량 섹션 중 입력-유래 2곳(§2 마진 카운트, §3.5 시장 하드룰 입력)을 payload 선계산으로, 출력-유래 2곳(§4.7 pivot 산술, §8.5 ±5% 밴드)을 store 사후검증(SOFT sanity)으로 이관한다. §6.1/§6.2 는 본 PR 범위에서 명시 제외.

**Architecture:** (a) `payload_builder` 가 `conditions_summary`(marginal 카운트)와 `market_direction_gate`(§3.5 하드룰 boolean)를 payload 에 추가 — 프롬프트는 규칙 텍스트(정의)를 유지하되 판정 입력을 선계산 값으로 명시(재계수 금지). (b) `store._validate_classification_prices` 를 확장해 §8.5 밴드 정합·§4.7 pivot 산술(+0.1 오프셋, base_high 상한)을 SOFT 경고로 사후검증 — **기존 sanity_warnings 컬럼 재사용, 스키마 변경 0**.

**Tech Stack:** Python (psycopg), pytest, prompt markdown, thresholds.py SSOT.

## 사전 결정 사항 (브리프 3건 — 재검토 후 확정)

| 결정 | 브리프 추천 | 채택안 (재검토) |
|---|---|---|
| 1. 착수 시점 | (b) 저위험 섹션 선착수 | **(b) 채택하되 범위 재정의** — 브리프 작성 후 상황 변화: #21(PR #36)·#22(PR #37) 이관이 이미 PR 로 존재해 "C·B 이후" 순서 제약이 사실상 해소됨. 단 두 PR 모두 미머지라 §6.1/§6.2(최복잡)만 대기 유지, 나머지 4개 섹션 착수. |
| 2. 착수 순서 | 난이도 낮은 순(§8.5→§4.7→§2→§3.5) | **채택** — 단, §8.5/§4.7 은 "코드 선계산"이 불가능(pivot 이 LLM 출력이라 입력 시점에 없음)함을 브리프가 짚지 않음. 메커니즘을 둘로 분리: 입력-유래(§2/§3.5)=payload 선계산, 출력-유래(§8.5/§4.7)=store 사후검증(기존 P1-2 Part A sanity 패턴 확장). |
| 3. §6.1/§6.2 범위 | (b) 착수 시점 최신 전문 기준 재확인 | **채택 + 본 PR 제외** — anchor 식별 등 시각 판단과 정량 조건이 얽힌 최복잡 게이트. #22 패턴(측정 코드화+결정 LLM 잔류)이 머지·검증된 뒤 별도 계획으로. PR 에 명시. |

### 세부 결정

- **프롬프트 규칙 텍스트(§2 "<3%"/"3 or more", §3.5 ">=5" 리터럴)는 유지** — PR #37 의 A-텍스트 co-anchor 가드(test_a_demotion_threshold_matches_ssot 등)가 이 리터럴을 대조하므로, 삭제하면 #37 머지 후 상호 파손. 리터럴은 정의(co-anchor)로 남기고 "판정 입력은 선계산 값, 재계수 금지" 규약만 추가.
- **SSOT 상수 3종(TT_MARGIN_MARGINAL_PCT, TT_MARGINAL_DEMOTION_COUNT, MARKET_DIST_DEMOTION_COUNT_25S)은 PR #37 과 동일 텍스트로 중복 추가** — 어느 쪽이 나중에 머지되든 충돌이 자명하게 해소되도록 정의문을 문자 단위로 일치시킴. PR 본문에 명시.
- 가드 테스트는 **새 파일 tests/test_prompt_a_gates.py** — #37 이 재작성한 test_prompt_trigger_gates.py 와의 충돌 회피.
- §3.5 의 "confirmed_uptrend 인데 dist 4" 구간(하드룰 텍스트가 원래 미규정)은 선계산 boolean 도 동일하게 미규정(force_watch=False, confidence_penalty=False, normal=False) — 기존 프롬프트의 갭을 그대로 보존(동작 변화 0), 갭 자체는 PR에 기록.
- §8.5 밴드 사후검증은 SOFT 경고 전용(저장 차단 없음) — LLM 산술 실수 탐지 목적. 비교 종가는 기존 sanity 와 동일 소스(daily_indicators adj_close as_of).
- §4.7 검증 2종: (i) pivot > base_high + 0.1 + ε → 경고(모든 basis 는 base 내부 고점), (ii) +0.1 오프셋 규칙 패턴(flat_base/cup_with_handle/vcp/double_bottom)에서 pivot 소수부 ≉ 0.1 → 경고.

## 임계 의존성 맵 (2축 판정)

**트리거**: thresholds.py 상수 추가 + A 프롬프트 임계 텍스트 연동.

**1단계 (파생 신호)**: 신규 상수 → `conditions_summary.marginal_count`, `market_direction_gate.*`, store 경고 3종(`sanity_band_mismatch`, `sanity_pivot_above_base_high`, `sanity_pivot_offset_rule`)

**2단계 (소비 룰)**: A 프롬프트 §2(confidence 상한·watch 선호), §3.5(강제 강등·감점), §8.5(watch_reason 경계 — store 는 사후검증만); weekly_classification.sanity_warnings (쓰기 전용, 하류 소비 없음 — P1-2 Part A 와 동일).

**3단계 (룰 내부 고정 상수) — 2축 판정**:

| 고정 상수 | 축1 환산? | 축2 영향? | 책 정합 | 판정 → 후속 |
|---|---|---|---|---|
| TT_MARGIN_MARGINAL_PCT=3.0 / TT_MARGINAL_DEMOTION_COUNT=3 (#37 과 동일 중복) | 부분 | 미미 — 기존 §2 텍스트 값의 승격, 값 변화 0. 계수 주체만 LLM→코드 | EXTENDS | 모니터링(동작 중립 승격 — 이관 전후 marginal 카운트 분산은 실가동 데이터로 후속 확인) |
| MARKET_DIST_DEMOTION_COUNT_25S=5 (#37 동일 중복) | 불가 | 있음 — §3.5 감점 boolean 의 코드 소비 | PRESERVES(HMMS Ch.9) | 임계와 함께 보정(#37 과 동일 SSOT) |
| MARKET_DIST_NORMAL_MAX_25S=3 (신규) | 불가(카운트) | 미미 — §3.5 "≤3 → 정상 진행" 텍스트 승격, 값 변화 0 | EXTENDS(3 은 시스템 채택 — 책은 5~6 강등만 명시) | 모니터링(동작 중립 승격) |
| PIVOT_EXTENDED_BAND_MULT=1.05 (신규) | 가능(비율) | 있음 — store 밴드 경고의 상단 경계 (§8.5 텍스트와 co-anchor) | EXTENDS(O'Neil 5% 추격 한계의 대칭 적용은 design judgment — §8.5 명시) | B-수치(경고 발생률 관찰) |
| PIVOT_PRICE_OFFSET=0.1 (신규) | 불가(호가 단위 관례) | 있음 — §4.7 오프셋 경고 기준 | EXTENDS(+0.1 은 시스템 관례 — 책은 "10 cents" 유사 관행) | 모니터링(경고 전용, 판정 무영향) |
| (기존) GATE_PROMOTION_PRICE_RATIO=0.95 | — | 소비처 추가(store 밴드 하단, §8.5 "promotion 임계와 정합" 텍스트 그대로) — 값 변화 0 | EXTENDS | 변경 없음 |
| (기존) _PIVOT_CLOSE_BAND(0.3,3.0) | — | 영향 없음 — 신규 경고와 독립 병존(자릿수 오류 vs 밴드 정합, 목적 상이) | 휴리스틱 | 변경 없음 |

**소비 경계 (1줄)**: `conditions_summary`/`market_direction_gate` → A 프롬프트 분류·confidence → weekly_classification → 하류(트리거 게이트·5b)는 기존과 동일; sanity_warnings 는 쓰기 전용 감사 컬럼.

## File Structure

- Modify: `kr_pipeline/common/thresholds.py` (+6: 중복 3 + 신규 3)
- Modify: `api/services/payload_builder.py` — 순수 헬퍼 2개 + payload 필드 2개
- Modify: `kr_pipeline/llm_runner/store.py` — `_validate_classification_prices` 확장(SOFT 3종)
- Modify: `prompts/analyze_chart_v3.md` — Inputs 문서화, §2/§3.5 재계수 금지 규약, SSOT 블록
- Create: `tests/test_prompt_a_gates.py` (신규 가드 — #37 충돌 회피용 별파일)
- Modify: `tests/test_api_payload_builder.py`, store sanity 테스트(기존 파일), `tests/test_prompt_threshold_drift.py`(A 목록)
- Regenerate: `web/src/data/thresholds.generated.ts`

## Global Constraints

- `uv run pytest tests/` 기대 실패 0. 스키마 변경 금지(기존 sanity_warnings 재사용). Co-Authored-By 금지, 명시 경로 스테이징만.
- 동작 변화 0 원칙: 프롬프트 규칙·강등 결과는 불변(계산 주체만 이동 + 사후 경고 추가). 유일한 신규 산출물 = payload 필드 2개, sanity 경고 3종.

## Tasks

### Task 1: thresholds 상수 + export
- [ ] 상수 6종 추가(중복 3종은 #37 과 문자 단위 동일 정의; A SSOT 블록·drift 목록은 기존 GATE_PROMOTION_PRICE_RATIO 등재 포함 +7), export 재실행, drift/threshold 테스트, commit.

### Task 2: payload_builder 선계산 (TDD)
- [ ] 테스트: `conditions_summary` (marginal_count = passed∧margin<3% 계수, None margin 미계수, 8키 전제) / `market_direction_gate` (force_watch: downtrend·correction·rally_attempt, confidence_penalty: dist≥5, normal: confirmed_uptrend∧dist≤3, dist 4 갭 보존, None 입력 → null) — FAIL 확인.
- [ ] 구현: 순수 헬퍼 `_conditions_summary(minervini)`, `_market_direction_gate(market_context)` + build_payload 에 필드 추가. PASS, commit.

### Task 3: store 사후검증 (TDD)
- [ ] 테스트: §8.5 밴드 불일치 경고 3종(`sanity_band_mismatch_entry` / `_valid_base` / `_extended`), §4.7 경고 2종(`sanity_pivot_above_base_high` / `sanity_pivot_offset_rule`), 정상 케이스 무경고, pivot/close 결측 시 skip — FAIL 확인.
- [ ] 구현: `_validate_classification_prices` 확장. PASS, commit.

### Task 4: 프롬프트 + 가드 (단일 커밋)
- [ ] A Inputs 에 두 필드 문서화, §2/§3.5 에 "선계산 값이 판정 입력 — 재계수/재판정 금지, 규칙 리터럴은 정의(co-anchor)" 규약 추가(기존 리터럴 유지), SSOT 블록 +6.
- [ ] tests/test_prompt_a_gates.py: §2 재계수 금지 토큰 가드, §3.5 market_direction_gate 참조 가드, §8.5 밴드 리터럴(0.95/1.05) ↔ SSOT 대조.
- [ ] test_prompt_threshold_drift.py A 목록 +6. 전체 관련 테스트 PASS, commit.

### Task 5: 전체 검증 → PR
- [ ] `uv run pytest tests/` 0 failed → PR 생성(머지 금지, 결정·의존성 맵·#37 중복 상수 명시) → 코드리뷰 → 반영 → 재검증.
